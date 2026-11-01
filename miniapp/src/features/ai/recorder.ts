/**
 * The voice recorder: the microphone through MediaRecorder (whichever of opus/webm, ogg or mp4
 * this phone records), a live level from Web Audio, a timer that stops at the company's limit,
 * Telegram haptics, and the screen kept awake while it listens. Every track is stopped and the
 * AudioContext closed when it ends, is cancelled, or the screen goes away.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { haptic } from "../../telegram";

export type RecorderPhase =
  /** Not started (or reset). */
  | "idle"
  /** Asking for the microphone. */
  | "starting"
  | "recording"
  /** Stopped; the last data is being collected. */
  | "stopping"
  /** A recording is ready in `recording`. */
  | "done"
  /** The person (or Telegram) said no to the microphone. */
  | "denied"
  /** No getUserMedia, no MediaRecorder, or no microphone at all. */
  | "unsupported"
  | "failed";

export type Recording = { blob: Blob; seconds: number; mimeType: string; fileName: string };

/** Most compact first: Chrome and Android record opus in webm, Firefox ogg, iOS mp4 (AAC). */
export const MIME_TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4", "audio/webm", "audio/ogg", "audio/aac"] as const;

/** Bars in the level meter. */
export const LEVEL_BARS = 28;
const TICK_MS = 80;
/** Shorter than this is a slip of the finger, not a voice note. */
export const MIN_SECONDS = 1;

type MediaRecorderClass = typeof MediaRecorder;

function recorderClass(): MediaRecorderClass | null {
  return typeof window !== "undefined" && typeof window.MediaRecorder === "function" ? window.MediaRecorder : null;
}

/** Whether this browser could record at all (Telegram Desktop's webview often can't). */
export function canRecord(): boolean {
  return Boolean(recorderClass() && typeof navigator !== "undefined" && navigator.mediaDevices?.getUserMedia);
}

/** The first type this browser records, or null to let it choose. */
export function pickMimeType(isSupported: (type: string) => boolean = (type) => recorderClass()?.isTypeSupported?.(type) ?? false): string | null {
  for (const type of MIME_TYPES) {
    try {
      if (isSupported(type)) return type;
    } catch {
      // An old engine that throws on unknown types: try the next one.
    }
  }
  return null;
}

/** "voice.webm", "voice.ogg", "voice.m4a": the server reads the kind from the name as well. */
export function fileNameFor(mimeType: string): string {
  const type = mimeType.toLowerCase();
  if (type.includes("ogg")) return "voice.ogg";
  if (type.includes("mp4") || type.includes("m4a")) return "voice.m4a";
  if (type.includes("aac")) return "voice.aac";
  if (type.includes("wav")) return "voice.wav";
  return "voice.webm";
}

/** Loudness 0–1 from a time-domain frame (bytes around 128): the frame's RMS, eased so speech fills the meter. */
export function levelOf(frame: Uint8Array): number {
  if (!frame.length) return 0;
  let sum = 0;
  for (const byte of frame) {
    const sample = (byte - 128) / 128;
    sum += sample * sample;
  }
  const rms = Math.sqrt(sum / frame.length);
  return Math.min(1, Math.sqrt(rms) * 1.6);
}

/** Why getUserMedia failed, as the phase to show. */
export function phaseForError(error: unknown): "denied" | "unsupported" | "failed" {
  const name = error instanceof Error || (error && typeof error === "object" && "name" in error) ? String((error as { name?: unknown }).name) : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "denied";
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError" || name === "TypeError") return "unsupported";
  return "failed";
}

type Live = {
  stream: MediaStream | null;
  recorder: MediaRecorder | null;
  context: AudioContext | null;
  analyser: AnalyserNode | null;
  frame: Uint8Array<ArrayBuffer> | null;
  timer: number | null;
  wakeLock: { release: () => Promise<void> } | null;
  chunks: Blob[];
  startedAt: number;
  /** Throw the data away when it stops (Cancel, leaving the screen). */
  discard: boolean;
  /** Bumped by every start and cancel, so a late getUserMedia answer knows it is stale. */
  run: number;
};

const emptyLive = (): Live => ({
  stream: null,
  recorder: null,
  context: null,
  analyser: null,
  frame: null,
  timer: null,
  wakeLock: null,
  chunks: [],
  startedAt: 0,
  discard: false,
  run: 0,
});

const flat = () => Array.from({ length: LEVEL_BARS }, () => 0);

export type Recorder = {
  phase: RecorderPhase;
  /** Seconds recorded so far (or the length of the finished recording). */
  seconds: number;
  /** The latest levels, oldest first, 0–1 each. */
  levels: number[];
  /** Whether the meter is real (a phone without Web Audio still records, the meter rests). */
  metered: boolean;
  recording: Recording | null;
  /** The last recording was too short to send (it was dropped). */
  tooShort: boolean;
  /** It stopped by itself at the limit. */
  autoStopped: boolean;
  start: () => Promise<void>;
  /** Stop and keep the recording. */
  stop: () => void;
  /** Stop and throw it away; back to idle. */
  cancel: () => void;
};

/** The recorder for one screen; `maxSeconds` is the company's limit (it stops itself there). */
export function useRecorder(maxSeconds: number): Recorder {
  const [phase, setPhase] = useState<RecorderPhase>("idle");
  const [seconds, setSeconds] = useState(0);
  const [levels, setLevels] = useState<number[]>(flat);
  const [metered, setMetered] = useState(false);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [tooShort, setTooShort] = useState(false);
  const [autoStopped, setAutoStopped] = useState(false);
  const live = useRef<Live>(emptyLive());
  const limit = useRef(maxSeconds);
  limit.current = maxSeconds;
  const mounted = useRef(true);

  /** Let go of the microphone, the meter, the timer and the wake lock (the recorder itself may still flush). */
  const release = useCallback(() => {
    const current = live.current;
    if (current.timer !== null) window.clearInterval(current.timer);
    current.timer = null;
    current.stream?.getTracks().forEach((track) => track.stop());
    current.stream = null;
    if (current.context && current.context.state !== "closed") void current.context.close().catch(() => undefined);
    current.context = null;
    current.analyser = null;
    current.frame = null;
    void current.wakeLock?.release().catch(() => undefined);
    current.wakeLock = null;
  }, []);

  const finish = useCallback(
    (mimeType: string) => {
      const current = live.current;
      const elapsed = (performance.now() - current.startedAt) / 1000;
      const chunks = current.chunks;
      current.chunks = [];
      current.recorder = null;
      release();
      if (!mounted.current) return;
      if (current.discard) {
        setPhase("idle");
        return;
      }
      const length = Math.min(elapsed, limit.current);
      if (length < MIN_SECONDS || !chunks.length) {
        setTooShort(true);
        setPhase("idle");
        haptic.notify("warning");
        return;
      }
      const blob = new Blob(chunks, { type: mimeType });
      setSeconds(length);
      setRecording({ blob, seconds: length, mimeType, fileName: fileNameFor(mimeType) });
      setPhase("done");
      haptic.notify("success");
    },
    [release],
  );

  const stopRecorder = useCallback(
    (discard: boolean) => {
      const current = live.current;
      current.discard = current.discard || discard;
      // No more ticks: the limit can't ask to stop twice.
      if (current.timer !== null) window.clearInterval(current.timer);
      current.timer = null;
      const recorder = current.recorder;
      if (recorder && recorder.state !== "inactive") {
        if (!discard) setPhase("stopping");
        try {
          // Its "stop" event finishes the job (finish above).
          recorder.stop();
          return;
        } catch {
          // A recorder that can't stop has nothing to give: let go by hand.
        }
      } else if (recorder) {
        // Already stopping: its "stop" event is on the way.
        return;
      }
      current.recorder = null;
      release();
      if (mounted.current) setPhase("idle");
    },
    [release],
  );

  const tick = useCallback(() => {
    const current = live.current;
    const elapsed = (performance.now() - current.startedAt) / 1000;
    let level = 0;
    if (current.analyser && current.frame) {
      current.analyser.getByteTimeDomainData(current.frame);
      level = levelOf(current.frame);
    }
    setSeconds(Math.min(elapsed, limit.current));
    setLevels((previous) => [...previous.slice(1), level]);
    if (elapsed >= limit.current) {
      setAutoStopped(true);
      haptic.notify("warning");
      stopRecorder(false);
    }
  }, [stopRecorder]);

  const start = useCallback(async () => {
    const current = live.current;
    if (current.recorder || current.stream) return;
    const Recorder = recorderClass();
    if (!Recorder || !canRecord()) {
      setPhase("unsupported");
      return;
    }
    current.run += 1;
    const run = current.run;
    setPhase("starting");
    setTooShort(false);
    setAutoStopped(false);
    setRecording(null);
    setSeconds(0);
    setLevels(flat());
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    } catch (error) {
      if (run !== live.current.run || !mounted.current) return;
      const next = phaseForError(error);
      setPhase(next);
      haptic.notify(next === "denied" ? "error" : "warning");
      return;
    }
    // Cancelled or gone while the permission question was open: let go of the microphone at once.
    if (run !== live.current.run || !mounted.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    current.stream = stream;
    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = mimeType ? new Recorder(stream, { mimeType, audioBitsPerSecond: 32_000 }) : new Recorder(stream);
    } catch {
      release();
      setPhase("failed");
      return;
    }
    const type = recorder.mimeType || mimeType || "audio/webm";
    current.recorder = recorder;
    current.chunks = [];
    current.discard = false;
    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) current.chunks.push(event.data);
    };
    recorder.onstop = () => finish(type);
    recorder.onerror = () => {
      current.discard = true;
      release();
      if (mounted.current) setPhase("failed");
    };

    // The meter is a nicety: a phone without Web Audio still records.
    try {
      const Context = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Context) {
        const context = new Context();
        if (context.state === "suspended") void context.resume().catch(() => undefined);
        const analyser = context.createAnalyser();
        analyser.fftSize = 512;
        context.createMediaStreamSource(stream).connect(analyser);
        current.context = context;
        current.analyser = analyser;
        current.frame = new Uint8Array(new ArrayBuffer(analyser.fftSize));
        setMetered(true);
      }
    } catch {
      setMetered(false);
    }

    current.startedAt = performance.now();
    try {
      recorder.start(1000);
    } catch {
      current.recorder = null;
      release();
      setPhase("failed");
      return;
    }
    current.timer = window.setInterval(tick, TICK_MS);
    setPhase("recording");
    haptic.impact("medium");

    // Keep the screen on while it listens, where the phone allows it; the recording never waits for it.
    const wakeLock = (navigator as Navigator & { wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> } }).wakeLock;
    wakeLock
      ?.request("screen")
      .then((lock) => {
        if (run === live.current.run && live.current.recorder === recorder) live.current.wakeLock = lock;
        else void lock.release().catch(() => undefined);
      })
      .catch(() => undefined);
  }, [finish, release, tick]);

  const stop = useCallback(() => {
    if (!live.current.recorder) return;
    stopRecorder(false);
  }, [stopRecorder]);

  const cancel = useCallback(() => {
    live.current.run += 1;
    if (live.current.recorder || live.current.stream) haptic.impact("light");
    stopRecorder(true);
    setRecording(null);
    setTooShort(false);
    setAutoStopped(false);
    setSeconds(0);
    setLevels(flat());
  }, [stopRecorder]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const current = live.current;
      current.run += 1;
      current.discard = true;
      try {
        if (current.recorder && current.recorder.state !== "inactive") current.recorder.stop();
      } catch {
        // Stopping is best effort; the tracks are released below either way.
      }
      current.recorder = null;
      release();
    };
  }, [release]);

  return { phase, seconds, levels, metered, recording, tooShort, autoStopped, start, stop, cancel };
}

/** "0:07", "1:30": the timer under the microphone. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
