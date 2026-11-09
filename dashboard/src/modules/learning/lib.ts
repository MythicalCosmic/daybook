/** Small pure helpers of the learning module (tested in __tests__/learning.test.ts). */
import type { StatusTone } from "@/components/StatusPill.vue";

import type { AssignmentState, Status, VideoState, ViewerState } from "./types";

export const STATUS_TONES: Record<Status, StatusTone> = { draft: "neutral", published: "success", archived: "warning" };

export const STATE_TONES: Record<AssignmentState, StatusTone> = {
  assigned: "neutral",
  in_progress: "info",
  completed: "success",
  exempt: "primary",
  cancelled: "neutral",
};

export const VIEWER_TONES: Record<ViewerState, StatusTone> = { never: "neutral", watching: "info", watched: "success" };

export const VIDEO_TONES: Record<VideoState, StatusTone> = { uploading: "info", processing: "info", ready: "success", failed: "danger" };

/** "1:05", "12:40", "1:02:03" from seconds. */
export function clock(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.round(seconds ?? 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** Whole minutes, rounded up (a 10-second lesson takes a minute). */
export function minutesOf(seconds: number | null | undefined): number {
  return seconds ? Math.max(1, Math.ceil(seconds / 60)) : 0;
}

/** "120 MB", "1,4 GB". */
export function bytes(size: number, locale = "en"): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit >= 2 && value < 10 ? 1 : 0;
  return `${value.toLocaleString(locale, { maximumFractionDigits: digits })} ${units[unit]}`;
}

export interface Segment {
  /** Where it starts, percent of the video. */
  left: number;
  width: number;
}

/** Watched ranges as segments of a strip `duration` long (merged, clipped, at least 0.5 % wide). */
export function segments(ranges: readonly (readonly [number, number])[], duration: number): Segment[] {
  if (!duration || duration <= 0) return [];
  const clipped = ranges
    .map(([a, b]) => [Math.max(0, Math.min(a, duration)), Math.max(0, Math.min(b, duration))] as [number, number])
    .filter(([a, b]) => b > a)
    .sort((x, y) => x[0] - y[0]);
  const merged: [number, number][] = [];
  for (const [a, b] of clipped) {
    const last = merged[merged.length - 1];
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else merged.push([a, b]);
  }
  return merged.map(([a, b]) => ({ left: (a / duration) * 100, width: Math.max(0.5, ((b - a) / duration) * 100) }));
}

const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;
const YOUTUBE_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"]);

/** The video id of a YouTube link (as the server reads it), for the preview; null otherwise. */
export function youtubeId(value: string): string | null {
  const text = value.trim();
  if (YOUTUBE_ID.test(text)) return text;
  let url: URL;
  try {
    url = new URL(text.includes("://") ? text : `https://${text}`);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  const host = url.hostname.toLowerCase();
  const parts = url.pathname.split("/").filter(Boolean);
  let found = "";
  if ((host === "youtu.be" || host === "www.youtu.be") && parts.length) found = parts[0]!;
  else if (YOUTUBE_HOSTS.has(host)) {
    if (parts.length === 1 && parts[0] === "watch") found = url.searchParams.get("v") ?? "";
    else if (parts.length >= 2 && ["shorts", "embed", "live", "v"].includes(parts[0]!)) found = parts[1]!;
  }
  return YOUTUBE_ID.test(found) ? found : null;
}

/** The privacy-enhanced embed the lesson preview plays (the dashboard's CSP allows it). */
export function youtubeEmbed(id: string): string {
  return `https://www.youtube-nocookie.com/embed/${id}?rel=0&modestbranding=1`;
}

/** "SRT-2026-0001": what the next certificate number looks like. */
export function nextCertificate(prefix: string, next: number, year: number): string {
  return `${prefix || "SRT"}-${year}-${String(next).padStart(4, "0")}`;
}
