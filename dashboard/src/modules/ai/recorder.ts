/**
 * The browser recorder every AI component shares (Dictate in New task, the dictate dialog): the
 * microphone through MediaRecorder in a format the browser can write (Opus in WebM or Ogg, AAC in
 * MP4 on iPhones), a live level from Web Audio, a timer that stops at the agent's limit, Telegram
 * haptics, and the screen kept awake while recording. Whatever happens (Done, Cancel, the dialog
 * closing), every track is stopped and the audio context closed.
 *
 * The states are a small pure machine (`recorderNext`), tested on its own and with a fake
 * MediaRecorder.
 */
import { getCurrentScope, onScopeDispose, ref, shallowRef, toValue, type MaybeRefOrGetter } from "vue";

export type RecorderState = "idle" | "requesting" | "recording" | "stopping" | "done" | "denied" | "unsupported" | "error";

export type RecorderEvent =
  | { type: "request" }
  | { type: "granted" }
  | { type: "denied" }
  | { type: "unsupported" }
  | { type: "failed" }
  | { type: "stop" }
  | { type: "data" }
  | { type: "cancel" }
  | { type: "reset" };

/** The next state; events that don't fit the current one change nothing. */
export function recorderNext(state: RecorderState, event: RecorderEvent): RecorderState {
  switch (event.type) {
    case "request":
      return state === "idle" || state === "done" || state === "error" || state === "denied" ? "requesting" : state;
    case "granted":
      return state === "requesting" ? "recording" : state;
    case "denied":
      return state === "requesting" ? "denied" : state;
    case "unsupported":
      return "unsupported";
    case "failed":
      return state === "unsupported" ? state : "error";
    case "stop":
      return state === "recording" ? "stopping" : state;
    case "data":
      return state === "stopping" ? "done" : state;
    case "cancel":
    case "reset":
      return state === "unsupported" ? state : "idle";
  }
}

/** Formats in the order we prefer them: the server reads every one of them (contract §1). */
export const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4", "audio/webm", "audio/aac"] as const;

export function pickMimeType(isTypeSupported: ((type: string) => boolean) | undefined): string {
  if (!isTypeSupported) return "";
  return MIME_CANDIDATES.find((type) => {
    try {
      return isTypeSupported(type);
    } catch {
      return false;
    }
  }) ?? "";
}

/** A file name the server can read the format from ("voice.webm", "voice.m4a"). */
export function voiceFilename(mime: string): string {
  const type = mime.split(";")[0]?.trim() ?? "";
  if (type.endsWith("ogg")) return "voice.ogg";
  if (type.endsWith("mp4") || type.endsWith("aac") || type.endsWith("m4a")) return "voice.m4a";
  if (type.endsWith("wav")) return "voice.wav";
  return "voice.webm";
}

/** Whether this browser can record at all (a secure page with a microphone API and MediaRecorder). */
export function recordingSupported(scope: { navigator?: Navigator; MediaRecorder?: unknown; isSecureContext?: boolean } = globalThis): boolean {
  return Boolean(scope.isSecureContext !== false && scope.navigator?.mediaDevices?.getUserMedia && typeof scope.MediaRecorder === "function");
}

/** "Permission denied" in its several spellings across browsers and webviews. */
export function isDenial(error: unknown): boolean {
  const name = (error as { name?: string } | null)?.name ?? "";
  return name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError";
}

function haptic(kind: "start" | "done" | "error"): void {
  const feedback = window.Telegram?.WebApp?.HapticFeedback;
  if (!feedback) return;
  try {
    if (kind === "start") feedback.impactOccurred("medium");
    else feedback.notificationOccurred(kind === "done" ? "success" : "error");
  } catch {
    // Haptics are a nicety; an old client without them must not stop the recording.
  }
}

type AudioContextClass = typeof AudioContext;

export interface RecorderOptions {
  /** The limit in seconds (the voice agent's `max_seconds`); recording stops by itself there. */
  maxSeconds: MaybeRefOrGetter<number>;
  /** How many level samples the meter keeps (bars on screen). */
  bars?: number;
}

export function useRecorder(options: RecorderOptions) {
  const state = ref<RecorderState>(recordingSupported() ? "idle" : "unsupported");
  const seconds = ref(0);
  /** 0–1, smoothed. */
  const level = ref(0);
  /** The last levels, oldest first, for the bars. */
  const levels = ref<number[]>(Array.from({ length: options.bars ?? 32 }, () => 0));
  const blob = shallowRef<Blob | null>(null);
  /** Stopped at the limit rather than by Done. */
  const hitLimit = ref(false);

  let stream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  let context: AudioContext | null = null;
  let frame: number | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  let wakeLock: { release: () => Promise<void> } | null = null;
  let chunks: Blob[] = [];
  let startedAt = 0;
  let discard = false;
  let disposed = false;

  const send = (event: RecorderEvent) => (state.value = recorderNext(state.value, event));

  function stopMeter(): void {
    if (frame !== null) (window.cancelAnimationFrame ?? clearTimeout)(frame);
    frame = null;
    if (context && context.state !== "closed") void context.close().catch(() => undefined);
    context = null;
  }

  /** Everything that holds the microphone or the screen goes. Safe to call twice. */
  function release(): void {
    if (timer !== null) clearInterval(timer);
    timer = null;
    stopMeter();
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    void wakeLock?.release().catch(() => undefined);
    wakeLock = null;
    level.value = 0;
  }

  function startMeter(media: MediaStream): void {
    const Context: AudioContextClass | undefined = window.AudioContext ?? (window as unknown as { webkitAudioContext?: AudioContextClass }).webkitAudioContext;
    if (!Context) return;
    try {
      context = new Context();
      // Created after the permission prompt, the context may start suspended (autoplay rules).
      void context.resume?.().catch(() => undefined);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      context.createMediaStreamSource(media).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const schedule = window.requestAnimationFrame?.bind(window) ?? ((callback: FrameRequestCallback) => setTimeout(() => callback(performance.now()), 50) as unknown as number);
      let count = 0;
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const value of data) {
          const sample = (value - 128) / 128;
          sum += sample * sample;
        }
        // Speech sits around 0.05–0.3 RMS: lift it so a normal voice fills most of the meter.
        const target = Math.min(1, Math.sqrt(sum / data.length) * 3.4);
        level.value = level.value * 0.55 + target * 0.45;
        count += 1;
        // The bars move at about 15 frames a second: smooth, without re-rendering every frame.
        if (count % 4 === 0) levels.value = [...levels.value.slice(1), level.value];
        frame = schedule(tick);
      };
      frame = schedule(tick);
    } catch {
      // No meter (an old webview): recording itself still works.
      stopMeter();
    }
  }

  async function keepAwake(): Promise<void> {
    try {
      const lock = await (navigator as Navigator & { wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> } }).wakeLock?.request("screen");
      if (!lock) return;
      if (state.value !== "recording") void lock.release().catch(() => undefined);
      else wakeLock = lock;
    } catch {
      // Not allowed here (no user gesture, battery saver): the recording doesn't depend on it.
    }
  }

  async function start(): Promise<void> {
    if (state.value === "requesting" || state.value === "recording" || state.value === "stopping") return;
    if (!recordingSupported()) {
      send({ type: "unsupported" });
      return;
    }
    blob.value = null;
    seconds.value = 0;
    hitLimit.value = false;
    discard = false;
    levels.value = levels.value.map(() => 0);
    send({ type: "request" });
    let media: MediaStream;
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (error) {
      haptic("error");
      send(isDenial(error) ? { type: "denied" } : (error as { name?: string })?.name === "NotFoundError" ? { type: "unsupported" } : { type: "failed" });
      return;
    }
    // Cancelled or closed while the browser asked: give the microphone straight back. (The state
    // changed during the await, which TypeScript's narrowing above can't know.)
    if (disposed || (state.value as RecorderState) !== "requesting") {
      media.getTracks().forEach((track) => track.stop());
      return;
    }
    stream = media;
    const mimeType = pickMimeType(MediaRecorder.isTypeSupported?.bind(MediaRecorder));
    try {
      recorder = mimeType ? new MediaRecorder(media, { mimeType }) : new MediaRecorder(media);
    } catch {
      release();
      send({ type: "failed" });
      return;
    }
    chunks = [];
    const current = recorder;
    current.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) chunks.push(event.data);
    };
    current.onstop = () => {
      release();
      if (discard || disposed) return;
      blob.value = new Blob(chunks, { type: current.mimeType || mimeType || "audio/webm" });
      send({ type: "data" });
      haptic("done");
    };
    current.start(1000);
    startedAt = Date.now();
    timer = setInterval(() => {
      seconds.value = (Date.now() - startedAt) / 1000;
      if (seconds.value >= toValue(options.maxSeconds)) {
        hitLimit.value = true;
        stop();
      }
    }, 200);
    startMeter(media);
    send({ type: "granted" });
    haptic("start");
    void keepAwake();
  }

  /** Done: the recording ends and `blob` follows (state "done"). */
  function stop(): void {
    if (state.value !== "recording" || !recorder) return;
    seconds.value = Math.min(toValue(options.maxSeconds), (Date.now() - startedAt) / 1000);
    send({ type: "stop" });
    if (timer !== null) clearInterval(timer);
    timer = null;
    try {
      if (recorder.state !== "inactive") recorder.stop();
      else release();
    } catch {
      release();
      send({ type: "failed" });
    }
  }

  /** Throw the recording away (or stop asking for the microphone) and go back to the start. */
  function cancel(): void {
    discard = true;
    try {
      if (recorder && recorder.state !== "inactive") recorder.stop();
    } catch {
      // Already stopped.
    }
    recorder = null;
    release();
    blob.value = null;
    seconds.value = 0;
    hitLimit.value = false;
    send({ type: "cancel" });
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      disposed = true;
      cancel();
    });
  }

  return { state, seconds, level, levels, blob, hitLimit, start, stop, cancel, reset: cancel };
}

export type Recorder = ReturnType<typeof useRecorder>;
