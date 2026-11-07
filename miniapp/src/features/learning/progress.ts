/**
 * The lesson player's progress reports (docs/PLAN-LEARNING.md §4.2): the players hand over what
 * they do (a position while playing, a seek, play, pause, the duration) and this sends
 * `{session, position, duration, ranges, playing}` every 10 s while playing, on pause, shortly
 * after a seek, when the app goes to the background and when the person leaves the lesson.
 * `ranges` are what was really played since the previous report (`WatchTracker`); the reports go
 * through the retry queue, so a dropped signal loses nothing.
 */
import { useEffect, useMemo, useRef } from "react";

import { reportProgress } from "./api";
import { sessionId, WatchTracker } from "./tracker";
import type { ProgressAnswer } from "./types";

export const REPORT_EVERY_MS = 10_000;
/** A burst of seeks (dragging the slider) makes one report. */
const SEEK_REPORT_MS = 1_200;

export type Watcher = {
  /** The player is at `position`, playing at `rate`. */
  time: (position: number, rate: number) => void;
  /** The player is seeking (HTML5 `seeking`). */
  seek: () => void;
  play: (position: number) => void;
  pause: (position: number) => void;
  /** The media's length once the player knows it (YouTube: from its first report). */
  duration: (seconds: number) => void;
  /**
   * How to read the player's position and rate right now (null while it isn't playing), so each
   * report counts up to this very moment, not to the last event or poll.
   */
  sampler: (read: (() => [number, number] | null) | null) => void;
};

type Reason = "start" | "tick" | "pause" | "seek" | "hidden" | "leave";

export function useWatchReporter({
  company,
  lesson,
  durationHint,
  onAnswer,
}: {
  company: number;
  lesson: number;
  /** The lesson's own duration, until the player says. */
  durationHint: number;
  onAnswer: (answer: ProgressAnswer) => void;
}): Watcher {
  const answer = useRef(onAnswer);
  answer.current = onAnswer;
  const state = useRef({
    session: sessionId(),
    tracker: new WatchTracker(),
    position: 0,
    duration: durationHint,
    playing: false,
    started: false,
    sent: null as { position: number; playing: boolean } | null,
    tick: undefined as ReturnType<typeof setInterval> | undefined,
    seekTimer: undefined as ReturnType<typeof setTimeout> | undefined,
    read: null as (() => [number, number] | null) | null,
  });

  const watcher = useMemo(() => {
    const s = state.current;
    const report = (reason: Reason) => {
      // Nothing to say before anything played; without the length the server can't place a
      // range: wait for the player to know it.
      if (!s.started || !(s.duration > 0)) return;
      try {
        const now = s.read?.();
        if (now) {
          s.position = now[0];
          s.tracker.time(now[0], now[1]);
        }
      } catch {
        // A player on its way out: the last position seen will do.
      }
      const ranges = s.tracker.take(s.duration);
      const position = Math.max(0, Math.min(Math.floor(s.position), Math.floor(s.duration)));
      const same = s.sent && s.sent.position === position && s.sent.playing === s.playing;
      if (!ranges.length && same && reason !== "start") return;
      s.sent = { position, playing: s.playing };
      const body = { session: s.session, position, duration: Math.round(s.duration), ranges, playing: s.playing };
      reportProgress(company, lesson, body).then(
        (reply) => answer.current(reply),
        () => undefined,
      );
    };
    const stopTicking = () => {
      if (s.tick !== undefined) clearInterval(s.tick);
      s.tick = undefined;
    };
    const soon = () => {
      if (s.seekTimer !== undefined) clearTimeout(s.seekTimer);
      s.seekTimer = setTimeout(() => {
        s.seekTimer = undefined;
        report("seek");
      }, SEEK_REPORT_MS);
    };
    const watcher: Watcher & { report: (reason: Reason) => void; stop: () => void } = {
      time: (position, rate) => {
        s.position = position;
        // A jump the player didn't announce (YouTube) is a seek: the range closed, a report follows.
        if (s.tracker.time(position, rate) === "jump" && s.playing) soon();
      },
      seek: () => {
        s.tracker.seek();
        soon();
      },
      play: (position) => {
        s.position = position;
        s.playing = true;
        // Playing starts here: the first step from this position counts.
        s.tracker.time(position, 1);
        if (!s.started) {
          s.started = true;
          report("start");
        }
        stopTicking();
        s.tick = setInterval(() => report("tick"), REPORT_EVERY_MS);
      },
      pause: (position) => {
        s.position = position;
        s.playing = false;
        stopTicking();
        report("pause");
      },
      duration: (seconds) => {
        if (Number.isFinite(seconds) && seconds > 0) s.duration = seconds;
      },
      sampler: (read) => {
        s.read = read;
      },
      report,
      stop: () => {
        stopTicking();
        if (s.seekTimer !== undefined) clearTimeout(s.seekTimer);
        s.seekTimer = undefined;
      },
    };
    return watcher;
  }, [company, lesson]);

  useEffect(() => {
    const onHidden = () => {
      if (document.visibilityState === "hidden") watcher.report("hidden");
    };
    const onPageHide = () => watcher.report("hidden");
    document.addEventListener("visibilitychange", onHidden);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onHidden);
      window.removeEventListener("pagehide", onPageHide);
      watcher.stop();
      // Leaving the lesson: what was played last goes too (keepalive, through the queue).
      state.current.playing = false;
      watcher.report("leave");
    };
  }, [watcher]);

  return watcher;
}
