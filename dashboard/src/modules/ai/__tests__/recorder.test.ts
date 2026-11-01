import { effectScope, nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isDenial, pickMimeType, recorderNext, recordingSupported, useRecorder, voiceFilename, type RecorderState } from "../recorder";

class FakeTrack {
  stopped = false;
  stop(): void {
    this.stopped = true;
  }
}

class FakeStream {
  tracks = [new FakeTrack()];
  getTracks(): FakeTrack[] {
    return this.tracks;
  }
}

class FakeRecorder {
  static instances: FakeRecorder[] = [];
  static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  timeslice: number | undefined;
  constructor(
    public stream: FakeStream,
    options?: { mimeType?: string },
  ) {
    this.mimeType = options?.mimeType ?? "";
    FakeRecorder.instances.push(this);
  }
  start(timeslice?: number): void {
    this.state = "recording";
    this.timeslice = timeslice;
  }
  stop(): void {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["voice"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  state = "running";
  constructor() {
    FakeAudioContext.instances.push(this);
  }
  createAnalyser() {
    return { fftSize: 0, connect: () => undefined, getByteTimeDomainData: (data: Uint8Array) => data.fill(170) };
  }
  createMediaStreamSource() {
    return { connect: () => undefined };
  }
  resume() {
    return Promise.resolve();
  }
  close() {
    this.state = "closed";
    return Promise.resolve();
  }
}

let stream: FakeStream;
let getUserMedia: ReturnType<typeof vi.fn>;

function install(): void {
  stream = new FakeStream();
  getUserMedia = vi.fn(async () => stream);
  FakeRecorder.instances = [];
  FakeAudioContext.instances = [];
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => setTimeout(() => callback(0), 16) as unknown as number);
  vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
}

function recorder(maxSeconds = 120) {
  const scope = effectScope();
  const instance = scope.run(() => useRecorder({ maxSeconds, bars: 8 }))!;
  return { scope, instance };
}

beforeEach(() => {
  vi.useFakeTimers();
  install();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "mediaDevices");
});

describe("state machine", () => {
  it("moves only along the recording's path", () => {
    const steps: Array<[RecorderState, Parameters<typeof recorderNext>[1]["type"], RecorderState]> = [
      ["idle", "request", "requesting"],
      ["requesting", "granted", "recording"],
      ["requesting", "denied", "denied"],
      ["recording", "stop", "stopping"],
      ["stopping", "data", "done"],
      ["done", "request", "requesting"],
      ["denied", "request", "requesting"],
      ["recording", "cancel", "idle"],
      ["recording", "request", "recording"],
      ["idle", "stop", "idle"],
      ["idle", "data", "idle"],
      ["unsupported", "cancel", "unsupported"],
      ["unsupported", "request", "unsupported"],
      ["recording", "failed", "error"],
    ];
    for (const [from, event, to] of steps) expect(recorderNext(from, { type: event } as never), `${from} + ${event}`).toBe(to);
  });

  it("picks a format the server reads and names the file after it", () => {
    expect(pickMimeType((type) => type === "audio/webm;codecs=opus")).toBe("audio/webm;codecs=opus");
    expect(pickMimeType((type) => type === "audio/mp4")).toBe("audio/mp4");
    expect(pickMimeType(() => false)).toBe("");
    expect(pickMimeType(undefined)).toBe("");
    expect(voiceFilename("audio/webm;codecs=opus")).toBe("voice.webm");
    expect(voiceFilename("audio/ogg;codecs=opus")).toBe("voice.ogg");
    expect(voiceFilename("audio/mp4")).toBe("voice.m4a");
    expect(voiceFilename("")).toBe("voice.webm");
  });

  it("knows when recording can't work at all", () => {
    expect(recordingSupported({ navigator, MediaRecorder: FakeRecorder, isSecureContext: true })).toBe(true);
    expect(recordingSupported({ navigator, MediaRecorder: undefined, isSecureContext: true })).toBe(false);
    expect(recordingSupported({ navigator, MediaRecorder: FakeRecorder, isSecureContext: false })).toBe(false);
    expect(isDenial({ name: "NotAllowedError" })).toBe(true);
    expect(isDenial({ name: "NotFoundError" })).toBe(false);
  });
});

describe("useRecorder with a fake MediaRecorder", () => {
  it("records, meters, times and hands over the recording on Done", async () => {
    const { instance, scope } = recorder();
    expect(instance.state.value).toBe("idle");
    await instance.start();
    expect(getUserMedia).toHaveBeenCalledWith({ audio: expect.objectContaining({ echoCancellation: true }) });
    expect(instance.state.value).toBe("recording");
    expect(FakeRecorder.instances[0]!.mimeType).toBe("audio/webm;codecs=opus");
    await vi.advanceTimersByTimeAsync(3000);
    expect(instance.seconds.value).toBeGreaterThanOrEqual(2.8);
    expect(instance.level.value).toBeGreaterThan(0.3);
    expect(instance.levels.value.some((value) => value > 0)).toBe(true);
    instance.stop();
    await nextTick();
    expect(instance.state.value).toBe("done");
    expect(instance.blob.value?.type).toBe("audio/webm;codecs=opus");
    expect(instance.hitLimit.value).toBe(false);
    expect(stream.tracks.every((track) => track.stopped)).toBe(true);
    expect(FakeAudioContext.instances[0]!.state).toBe("closed");
    scope.stop();
  });

  it("stops by itself at the limit", async () => {
    const { instance, scope } = recorder(5);
    await instance.start();
    await vi.advanceTimersByTimeAsync(5200);
    expect(instance.state.value).toBe("done");
    expect(instance.hitLimit.value).toBe(true);
    expect(instance.seconds.value).toBe(5);
    scope.stop();
  });

  it("throws the recording away on Cancel and frees the microphone", async () => {
    const { instance, scope } = recorder();
    await instance.start();
    instance.cancel();
    await nextTick();
    expect(instance.state.value).toBe("idle");
    expect(instance.blob.value).toBeNull();
    expect(stream.tracks[0]!.stopped).toBe(true);
    expect(FakeAudioContext.instances[0]!.state).toBe("closed");
    scope.stop();
  });

  it("gives the microphone back when cancelled while the browser was still asking", async () => {
    let grant: (value: FakeStream) => void = () => undefined;
    getUserMedia.mockImplementation(() => new Promise((resolve) => (grant = resolve)));
    const { instance, scope } = recorder();
    const starting = instance.start();
    expect(instance.state.value).toBe("requesting");
    instance.cancel();
    grant(stream);
    await starting;
    expect(instance.state.value).toBe("idle");
    expect(stream.tracks[0]!.stopped).toBe(true);
    expect(FakeRecorder.instances).toHaveLength(0);
    scope.stop();
  });

  it("says denied, unsupported or error, by what the browser answered", async () => {
    getUserMedia.mockRejectedValueOnce(Object.assign(new Error("no"), { name: "NotAllowedError" }));
    const denied = recorder();
    await denied.instance.start();
    expect(denied.instance.state.value).toBe("denied");
    denied.scope.stop();

    getUserMedia.mockRejectedValueOnce(Object.assign(new Error("none"), { name: "NotFoundError" }));
    const missing = recorder();
    await missing.instance.start();
    expect(missing.instance.state.value).toBe("unsupported");
    missing.scope.stop();

    getUserMedia.mockRejectedValueOnce(Object.assign(new Error("busy"), { name: "NotReadableError" }));
    const busy = recorder();
    await busy.instance.start();
    expect(busy.instance.state.value).toBe("error");
    busy.scope.stop();
  });

  it("starts as unsupported where the browser has no MediaRecorder", () => {
    vi.stubGlobal("MediaRecorder", undefined);
    const { instance, scope } = recorder();
    expect(instance.state.value).toBe("unsupported");
    scope.stop();
  });

  it("stops every track and closes the audio context when its component goes away", async () => {
    const { instance, scope } = recorder();
    await instance.start();
    scope.stop();
    expect(stream.tracks[0]!.stopped).toBe(true);
    expect(FakeAudioContext.instances[0]!.state).toBe("closed");
    expect(instance.state.value).toBe("idle");
    expect(instance.blob.value).toBeNull();
  });
});
