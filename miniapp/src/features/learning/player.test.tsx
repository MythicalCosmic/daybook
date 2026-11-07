/**
 * The lesson player (docs/PLAN-LEARNING.md §4.2): resumed at the position, what was really played
 * reported on start, every 10 s, after a seek, on pause, in the background and on leaving; the
 * server's percent on the bar; "Next step" with confetti once watched; the states of a video
 * being prepared or one that won't play; YouTube through its IFrame API, polled each second.
 */
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { membership, navigationState, person, renderApp } from "../../test/harness";
import { learningKeys } from "./api";
import { lesson } from "./fixtures";
import LessonPage from "./LessonPage";
import { resetYouTube, type YTNamespace } from "./players";
import { REPORT_EVERY_MS } from "./progress";
import { resetQueue } from "./queue";
import type { LessonDetail, ProgressReport } from "./types";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../../api/client")>()), api }));
const celebrate = vi.hoisted(() => vi.fn(() => () => undefined));
vi.mock("../../ui/celebrate", () => ({ celebrate, prefersReducedMotion: () => false }));

const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["learning"] };
const me = person([membership({ company } as never)]);
const PAGE = { feature: "learning", page: "lesson", params: { id: 12, course: 4, assignment: 31 } };

type Answer = { percent: number; position: number; completed: boolean; completed_now: boolean; points: number | null };
let answer: Answer;
const reports = () =>
  api.mock.calls.filter(([path]) => String(path).endsWith("/lessons/12/progress/")).map(([, options]) => (options as { json: ProgressReport }).json);

function show(detail: LessonDetail = lesson()) {
  return renderApp(<LessonPage params={PAGE.params} />, {
    me,
    init: { stack: [PAGE] },
    seed: (client) => client.setQueryData(learningKeys.lesson(1, 12, 4), detail),
  });
}

/** A media element's state, as the browser would have it. */
function media(element: HTMLMediaElement, state: Partial<Record<"currentTime" | "duration" | "paused" | "seeking" | "playbackRate", number | boolean>>) {
  for (const [name, value] of Object.entries(state)) Object.defineProperty(element, name, { value, writable: true, configurable: true });
}

/** Play from `from` to `to` with a timeupdate every quarter second. */
function playTo(video: HTMLVideoElement, from: number, to: number) {
  for (let at = from; at <= to + 1e-9; at += 0.25) {
    media(video, { currentTime: Number(at.toFixed(2)), paused: false, seeking: false });
    fireEvent.timeUpdate(video);
  }
}

beforeEach(() => {
  resetQueue();
  localStorage.clear();
  api.mockReset();
  celebrate.mockClear();
  answer = { percent: 20, position: 24, completed: false, completed_now: false, points: null };
  api.mockImplementation(async (path: string) => (String(path).endsWith("/progress/") ? answer : lesson()));
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete window.YT;
  resetYouTube();
});

describe("the HTML5 player", () => {
  it("plays the signed MP4 inline with its poster, resumed where the person left off", () => {
    show();
    const video = document.querySelector("video")!;
    expect(video.getAttribute("src")).toBe("/api/v1/files/signed-video/");
    expect(video.getAttribute("poster")).toBe("/api/v1/files/signed-poster/");
    expect(video.hasAttribute("playsinline")).toBe(true);
    expect(video.getAttribute("preload")).toBe("metadata");
    media(video, { duration: 120 });
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(24);
    expect(screen.getByText("20%")).toBeTruthy();
    expect(screen.getByText("Watch at least 90% to finish the lesson. Skipping ahead doesn’t count.")).toBeTruthy();
  });

  it("reports what was really played: on start, every 10 s, after a seek, on pause and on leaving", async () => {
    const { unmount } = show();
    const video = document.querySelector("video")!;
    media(video, { duration: 120, currentTime: 24, paused: false });
    fireEvent.loadedMetadata(video);
    fireEvent.playing(video);
    await act(async () => {});
    expect(reports()).toHaveLength(1);
    const session = reports()[0].session;
    expect(reports()[0]).toEqual({ session, position: 24, duration: 120, ranges: [], playing: true });
    const sent = api.mock.calls.find(([path]) => String(path).endsWith("/progress/"))!;
    expect(sent[0]).toBe("/companies/1/learning/lessons/12/progress/");
    expect(sent[1]).toMatchObject({ method: "POST", keepalive: true });

    playTo(video, 24.25, 34);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REPORT_EVERY_MS);
    });
    expect(reports()[1]).toEqual({ session, position: 34, duration: 120, ranges: [[24, 34]], playing: true });

    // Dragging the slider ahead: nothing skipped counts, and one report follows the seek.
    media(video, { currentTime: 90, seeking: true });
    fireEvent.seeking(video);
    playTo(video, 90, 95);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_300);
    });
    expect(reports()[2]).toEqual({ session, position: 95, duration: 120, ranges: [[90, 95]], playing: true });

    playTo(video, 95.25, 97);
    media(video, { paused: true });
    fireEvent.pause(video);
    await act(async () => {});
    expect(reports()[3]).toEqual({ session, position: 97, duration: 120, ranges: [[95, 97]], playing: false });

    // The app goes to the background mid-play.
    fireEvent.playing(video);
    playTo(video, 97.25, 99);
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    await act(async () => {});
    expect(reports()[4]).toEqual({ session, position: 99, duration: 120, ranges: [[97, 99]], playing: true });

    playTo(video, 99.25, 101);
    unmount();
    await act(async () => {});
    expect(reports()[5]).toEqual({ session, position: 101, duration: 120, ranges: [[99, 101]], playing: false });
    expect(reports()).toHaveLength(6);
  });

  it("shows the server's percent, and once watched celebrates and offers the next step", async () => {
    show();
    const video = document.querySelector("video")!;
    media(video, { duration: 120, currentTime: 100, paused: false });
    fireEvent.loadedMetadata(video);
    answer = { percent: 92, position: 110, completed: true, completed_now: true, points: 10 };
    fireEvent.playing(video);
    await act(async () => {});
    expect(screen.getByText("92%")).toBeTruthy();
    expect(celebrate).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Lesson watched. Well done! +10 points")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    // In place of the lesson: Back goes to the course, not to the finished lesson.
    expect(navigationState().stack).toEqual([{ feature: "learning", page: "quiz", params: { id: 8, course: 4, assignment: 31 } }]);
  });

  it("offers the way back to the course when the lesson is the last step", () => {
    show(lesson({ next: null, progress: { percent: 100, position: 0, completed_at: "2026-10-20T07:00:00Z", ranges: [[0, 120]] } }));
    expect(screen.getByRole("button", { name: "Back to the course" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Next step" })).toBeNull();
  });

  it("says when the video is still being prepared, or won't play, and tries again", async () => {
    show(lesson({ processing: true, video: null }));
    expect(screen.getByText("The video is being prepared")).toBeTruthy();
    expect(document.querySelector("video")).toBeNull();
    cleanup();

    show();
    fireEvent.error(document.querySelector("video")!);
    expect(screen.getByText("The video won’t play")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    await act(async () => {});
    // A fresh signed link, and the player back.
    expect(api.mock.calls.some(([path]) => path === "/companies/1/learning/lessons/12/?course=4")).toBe(true);
    expect(document.querySelector("video")).not.toBeNull();
    cleanup();

    show(lesson({ video: null }));
    expect(screen.getByText("No video in this lesson yet")).toBeTruthy();
  });

  it("pauses while another page covers it", () => {
    const paused = vi.mocked(HTMLMediaElement.prototype.pause);
    renderApp(<LessonPage params={PAGE.params} />, {
      me,
      init: { stack: [PAGE, { feature: "knowledge", page: "page", params: { id: 5 } }] },
      seed: (client) => client.setQueryData(learningKeys.lesson(1, 12, 4), lesson()),
    });
    expect(paused).toHaveBeenCalled();
  });
});

describe("the YouTube player", () => {
  type Events = { onReady?: (event: { target: unknown; data: number }) => void; onStateChange?: (event: { target: unknown; data: number }) => void; onError?: () => void };
  let made: { element: HTMLElement; events: Events } | null;
  let at: number;
  const target = { getCurrentTime: () => at, getDuration: () => 300, getPlaybackRate: () => 1, getPlayerState: () => 1, pauseVideo: vi.fn(), destroy: vi.fn() };

  beforeEach(() => {
    made = null;
    at = 0;
    window.YT = {
      Player: class {
        constructor(element: HTMLElement, options: { events: Events }) {
          made = { element, events: options.events };
          return target;
        }
      },
      PlayerState: { ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 },
    } as unknown as YTNamespace;
  });

  it("embeds the privacy-enhanced player with the JS API and polls the time while it plays", async () => {
    show(lesson({ source: "youtube", youtube_id: "dQw4w9WgXcQ", video: null, duration_seconds: 0, progress: null }));
    await act(async () => {});
    const frame = document.querySelector("iframe")!;
    const src = new URL(frame.src);
    expect(src.origin + src.pathname).toBe("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ");
    expect(Object.fromEntries(src.searchParams)).toMatchObject({ enablejsapi: "1", playsinline: "1", rel: "0" });
    expect(made?.element).toBe(frame);

    made!.events.onReady!({ target, data: -1 });
    made!.events.onStateChange!({ target, data: 1 });
    await act(async () => {});
    // The duration comes from the player: the server learns it from the first report.
    const session = reports()[0].session;
    expect(reports()[0]).toEqual({ session, position: 0, duration: 300, ranges: [], playing: true });

    for (let second = 1; second <= 10; second += 1) {
      at = second;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
    }
    expect(reports()[1]).toEqual({ session, position: 10, duration: 300, ranges: [[0, 10]], playing: true });

    // A jump the API doesn't announce is a seek: it doesn't count, and a report follows.
    at = 200;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    at = 201;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(reports()).toHaveLength(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(reports()[2]).toEqual({ session, position: 201, duration: 300, ranges: [[200, 201]], playing: true });

    at = 202;
    made!.events.onStateChange!({ target, data: 2 });
    await act(async () => {});
    expect(reports()[3]).toEqual({ session, position: 202, duration: 300, ranges: [[201, 202]], playing: false });
  });

  it("says it can't play when YouTube refuses the video", async () => {
    show(lesson({ source: "youtube", youtube_id: "dQw4w9WgXcQ", video: null }));
    await act(async () => {});
    act(() => made!.events.onError!());
    expect(screen.getByText("The video won’t play")).toBeTruthy();
  });
});
