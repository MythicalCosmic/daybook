/**
 * The lesson's two players. Both hand what they do to a `Watcher` (progress.ts): the HTML5 video
 * from its own events (`timeupdate`, `seeking`, `playing`, `pause`), YouTube through its IFrame
 * API, polling `getCurrentTime()` each second while it plays (it announces no seeks; the tracker
 * notices the jump). Both resume at `start` and pause while the page is covered (`active`).
 */
import { useEffect, useRef } from "react";

import type { Watcher } from "./progress";
import type { LessonVideo } from "./types";

/** The uploaded video: the signed MP4 with its poster, inline on phones. */
export function VideoPlayer({
  video,
  start,
  watcher,
  active,
  label,
  onFail,
}: {
  video: LessonVideo;
  start: number;
  watcher: Watcher;
  active: boolean;
  label: string;
  onFail: () => void;
}) {
  const element = useRef<HTMLVideoElement>(null);
  const resumed = useRef(false);

  useEffect(() => {
    if (!active) element.current?.pause();
  }, [active]);

  return (
    <video
      ref={element}
      className="lrn-video"
      src={video.url}
      poster={video.poster_url ?? undefined}
      playsInline
      preload="metadata"
      controls
      controlsList="nodownload"
      aria-label={label}
      onLoadedMetadata={(event) => {
        const media = event.currentTarget;
        watcher.duration(media.duration || video.duration_seconds);
        // Back where they left off, once (a link that expired and came again must not jump back).
        if (!resumed.current && start > 0 && start < (media.duration || video.duration_seconds) - 5) media.currentTime = start;
        resumed.current = true;
      }}
      onDurationChange={(event) => watcher.duration(event.currentTarget.duration)}
      onTimeUpdate={(event) => {
        const media = event.currentTarget;
        if (!media.paused && !media.seeking) watcher.time(media.currentTime, media.playbackRate);
      }}
      onSeeking={() => watcher.seek()}
      onPlaying={(event) => watcher.play(event.currentTarget.currentTime)}
      onPause={(event) => watcher.pause(event.currentTarget.currentTime)}
      onEnded={(event) => watcher.pause(event.currentTarget.currentTime)}
      onError={onFail}
    />
  );
}

// — YouTube —

/** The parts of the IFrame API this player uses. */
export type YTPlayer = {
  getCurrentTime(): number;
  getDuration(): number;
  getPlaybackRate(): number;
  getPlayerState(): number;
  pauseVideo(): void;
  destroy(): void;
};

type YTEvent = { target: YTPlayer; data: number };

export type YTNamespace = {
  Player: new (
    element: HTMLElement,
    options: { events: { onReady?: (event: YTEvent) => void; onStateChange?: (event: YTEvent) => void; onError?: (event: YTEvent) => void } },
  ) => YTPlayer;
  PlayerState: { ENDED: number; PLAYING: number; PAUSED: number; BUFFERING: number; CUED: number };
};

declare global {
  interface Window {
    YT?: YTNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

export const YOUTUBE_API = "https://www.youtube.com/iframe_api";
let loading: Promise<YTNamespace> | null = null;

/** The IFrame API, loaded once for the app. */
export function loadYouTube(): Promise<YTNamespace> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  loading ??= new Promise<YTNamespace>((resolve, reject) => {
    const before = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      before?.();
      if (window.YT) resolve(window.YT);
    };
    const script = document.createElement("script");
    script.src = YOUTUBE_API;
    script.async = true;
    script.onerror = () => {
      loading = null;
      script.remove();
      reject(new Error("The YouTube player didn't load"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

/** Only for tests: load the API afresh. */
export function resetYouTube(): void {
  loading = null;
}

/** The embed address: the privacy-enhanced host, the JS API, inline play, no related videos from others. */
export function youtubeSrc(id: string, start: number, origin = window.location.origin): string {
  const params = new URLSearchParams({ enablejsapi: "1", playsinline: "1", rel: "0", origin });
  if (start > 0) params.set("start", String(Math.floor(start)));
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?${params}`;
}

export const POLL_MS = 1_000;

/** A YouTube lesson through the IFrame API. */
export function YouTubePlayer({
  id,
  start,
  watcher,
  active,
  label,
  onFail,
}: {
  id: string;
  start: number;
  watcher: Watcher;
  active: boolean;
  label: string;
  onFail: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const player = useRef<YTPlayer | null>(null);
  const fail = useRef(onFail);
  fail.current = onFail;
  const startAt = useRef(start);

  useEffect(() => {
    const box = host.current;
    if (!box) return;
    let cancelled = false;
    let poll: ReturnType<typeof setInterval> | undefined;
    const stopPolling = () => {
      if (poll !== undefined) clearInterval(poll);
      poll = undefined;
    };
    // The iframe is made here, not by React: the API takes it over and removes it on destroy().
    const frame = document.createElement("iframe");
    frame.className = "lrn-youtube-frame";
    frame.src = youtubeSrc(id, startAt.current);
    frame.title = label;
    frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    frame.allowFullscreen = true;
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    box.appendChild(frame);

    loadYouTube().then(
      (YT) => {
        if (cancelled) return;
        player.current = new YT.Player(frame, {
          events: {
            onReady: (event) => watcher.duration(event.target.getDuration()),
            onStateChange: (event) => {
              const target = event.target;
              if (event.data === YT.PlayerState.PLAYING) {
                watcher.duration(target.getDuration());
                watcher.play(target.getCurrentTime());
                stopPolling();
                poll = setInterval(() => watcher.time(target.getCurrentTime(), target.getPlaybackRate() || 1), POLL_MS);
              } else if (event.data === YT.PlayerState.PAUSED || event.data === YT.PlayerState.ENDED) {
                stopPolling();
                watcher.time(target.getCurrentTime(), target.getPlaybackRate() || 1);
                watcher.pause(target.getCurrentTime());
              } else if (event.data === YT.PlayerState.BUFFERING) {
                stopPolling();
              }
            },
            onError: () => fail.current(),
          },
        });
      },
      () => {
        if (!cancelled) fail.current();
      },
    );
    return () => {
      cancelled = true;
      stopPolling();
      try {
        player.current?.destroy();
      } catch {
        // A player that never finished loading has nothing to destroy.
      }
      player.current = null;
      frame.remove();
    };
  }, [id, label, watcher]);

  useEffect(() => {
    if (!active) {
      try {
        player.current?.pauseVideo();
      } catch {
        // Not ready yet: nothing plays.
      }
    }
  }, [active]);

  return <div ref={host} className="lrn-youtube" />;
}
