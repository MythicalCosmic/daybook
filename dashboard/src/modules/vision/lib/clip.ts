/**
 * A clip as the player shows it (docs/KOZ.md §6.6): asking for it, waiting while the Ko‘z box
 * looks for the video and sends it (`pending`, `fetching`, polled every 2 s), then the player
 * (`ready`) or a clear reason (`failed`, or the request refused, such as no counter camera).
 */
import { isApiError } from "@/api/http";

import { CLIP_FAILURES, type Clip, type ClipFailure } from "../types";

export const CLIP_POLL_MS = 2_000;

export type ClipPhase = "requesting" | "pending" | "fetching" | "ready" | "failed" | "refused";

export function clipPhase(clip: Clip | null, requestError: unknown): ClipPhase {
  if (requestError) return "refused";
  if (!clip) return "requesting";
  if (clip.state === "ready" && !clip.video_url) return "fetching";
  return clip.state;
}

/** Still waiting for the box: keep asking. */
export function shouldPoll(phase: ClipPhase): boolean {
  return phase === "pending" || phase === "fetching";
}

/** The dictionary key of a failure ("vision.clip.failure.not_recorded"), any unknown code generic. */
export function failureKey(failure: ClipFailure | string | null | undefined): string {
  return failure && (CLIP_FAILURES as readonly string[]).includes(failure) ? `vision.clip.failure.${failure}` : "vision.clip.failure.unknown";
}

/** Why a request was refused: the backend's code when it has one we explain (409 `no_camera`). */
export function refusalKey(error: unknown): string {
  if (isApiError(error)) {
    if (error.code === "no_camera") return "vision.clip.refused.no_camera";
    if (error.status === 403) return "vision.clip.refused.forbidden";
    if (error.isNetwork) return "vision.clip.refused.offline";
  }
  return "vision.clip.refused.generic";
}

/** A step index for the waiting animation: asked (0), the box is looking (1), sending (2). */
export function waitingStep(phase: ClipPhase): 0 | 1 | 2 {
  if (phase === "requesting" || phase === "pending") return 0;
  if (phase === "fetching") return 1;
  return 2;
}
