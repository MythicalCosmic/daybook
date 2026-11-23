/**
 * Fixture mode only: video receipts. A clip waits a moment (`pending`), then the "box" fetches it
 * (`fetching`): a few seconds of the scene are recorded from the canvas into a WebM, and it is
 * `ready`. A window older than the recordings kept fails with `too_old`, a camera that is offline
 * with `camera_offline`, as the real box answers.
 */
import { ApiError } from "@/api/http";

import type { Clip, ClipRequest } from "../types";
import { cyclePosition } from "./clock";
import { recordClip } from "./draw";
import { bodiesAt } from "./sim";
import { findAlert, site, type World } from "./world";

interface Record {
  clip: Clip;
  createdAt: number;
  scene: "counter" | "entrance" | "floor" | "storeroom" | "empty";
  variant: number;
  startT: number;
  /** Fails after a moment with this code, instead of recording. */
  fails: Clip["failure"];
  recording: Promise<void> | null;
}

const records = new Map<string, Map<number, Record>>();

function store(world: World): Map<number, Record> {
  const key = String(world.companyId);
  let found = records.get(key);
  if (!found) records.set(key, (found = new Map()));
  return found;
}

const CLIP_SECONDS = 6;

export function createClip(world: World, body: ClipRequest): Clip {
  let cameraId: number | null = null;
  let start: Date;
  let end: Date;
  let reason: Clip["reason"] = "manual";
  let saleId: number | null = null;
  let alertId: number | null = null;
  let startT = 0;
  let key: string;
  if ("alert_id" in body) {
    const alert = findAlert(world, body.alert_id);
    if (!alert || !alert.camera) throw new ApiError(404, { detail: "Not found." });
    cameraId = alert.camera.id;
    start = new Date(new Date(alert.started_at).getTime() - 10_000);
    end = new Date(Math.min(start.getTime() + 60_000, new Date(alert.resolved_at ?? Date.now()).getTime()));
    reason = "alert";
    alertId = alert.id;
    startT = alert.state === "open" ? cyclePosition(site(world.cameras.find((c) => c.id === cameraId)?.variant ?? 0).offset).t - (alert.duration_s ?? 0) - 10 : 186;
    key = `alert:${alert.id}`;
  } else if ("sale_id" in body) {
    // Fixture: every sale was rung up at the first branch's counter.
    const cam = world.cameras.find((c) => c.role === "counter" && c.enabled);
    if (!cam) throw new ApiError(409, { code: "no_camera", detail: "No counter camera for this sale's till." });
    cameraId = cam.id;
    end = new Date(Date.now() - 60_000);
    start = new Date(end.getTime() - 15_000);
    reason = "sale";
    saleId = body.sale_id;
    startT = 96;
    key = `sale:${body.sale_id}`;
  } else {
    cameraId = body.camera_id;
    const at = new Date(body.at).getTime();
    start = new Date(at - (body.before_s ?? 10) * 1000);
    end = new Date(at + (body.after_s ?? 5) * 1000);
    startT = 120;
    key = `at:${body.camera_id}:${body.at}`;
  }
  const existing = world.clipOf.get(key);
  const list = store(world);
  if (existing && list.has(existing)) return { ...list.get(existing)!.clip };
  const cam = world.cameras.find((c) => c.id === cameraId);
  if (!cam) throw new ApiError(404, { detail: "Not found." });
  const old = Date.now() - end.getTime() > 5 * 86_400_000;
  const clip: Clip = {
    id: world.nextId++,
    state: "pending",
    reason,
    camera: { id: cam.id, name: cam.name },
    start: start.toISOString(),
    end: end.toISOString(),
    sale_id: saleId,
    alert_id: alertId,
    video_url: null,
    poster_url: null,
    duration_s: null,
    failure: null,
    failure_text: null,
    created_at: new Date().toISOString(),
  };
  list.set(clip.id, { clip, createdAt: Date.now(), scene: cam.scene, variant: cam.variant, startT, fails: !cam.online ? "camera_offline" : old ? "too_old" : null, recording: null });
  // The same object the polls move on, so an alert or a review row shows the clip's state.
  world.clips.set(clip.id, { clip, scene: cam.scene, variant: cam.variant, startT });
  world.clipOf.set(key, clip.id);
  return { ...clip };
}

/** Clips the history says failed long ago (shown on old alerts). */
function preset(world: World, id: number): Record | null {
  if (id < 90_000 || id >= 91_000) return null;
  const clip: Clip = {
    id,
    state: "failed",
    reason: "alert",
    camera: world.cameras.find((c) => c.role === "counter") ? { id: world.cameras.find((c) => c.role === "counter")!.id, name: "Kassa 1" } : null,
    start: new Date(Date.now() - 11 * 86_400_000).toISOString(),
    end: new Date(Date.now() - 11 * 86_400_000 + 30_000).toISOString(),
    sale_id: null,
    alert_id: null,
    video_url: null,
    poster_url: null,
    duration_s: null,
    failure: "too_old",
    failure_text: null,
    created_at: new Date(Date.now() - 11 * 86_400_000).toISOString(),
  };
  return { clip, createdAt: 0, scene: "counter", variant: 0, startT: 0, fails: "too_old", recording: null };
}

export function getClip(world: World, id: number): Clip {
  const list = store(world);
  const record = list.get(id) ?? preset(world, id);
  if (!record) throw new ApiError(404, { detail: "Not found." });
  const age = Date.now() - record.createdAt;
  const { clip } = record;
  if (clip.state === "pending" && age > 1200) clip.state = "fetching";
  if (clip.state === "fetching" && record.fails && age > 2600) {
    clip.state = "failed";
    clip.failure = record.fails;
  }
  if (clip.state === "fetching" && !record.fails && !record.recording) {
    const scene = site(record.variant).scenes[record.scene];
    record.recording = recordClip(
      (elapsed) => ({ kind: record.scene, variant: record.variant, bodies: bodiesAt(scene, record.startT + elapsed), zones: [] }),
      CLIP_SECONDS,
    )
      .then(({ url, poster }) => {
        clip.state = "ready";
        clip.video_url = url;
        clip.poster_url = poster;
        clip.duration_s = CLIP_SECONDS;
      })
      .catch(() => {
        clip.state = "failed";
        clip.failure = "not_recorded";
      });
  }
  return { ...clip };
}
