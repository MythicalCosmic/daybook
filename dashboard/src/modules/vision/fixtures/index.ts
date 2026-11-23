/**
 * Fixture mode only (VITE_VISION_FIXTURES=1 on the dev server, see ../mode.ts): answers every
 * `vision/` call the way docs/KOZ.md §6 describes, from a drawn pharmacy that moves with the
 * clock. Writes change the fixture world for the rest of the visit. Errors come back as the
 * backend's would (ApiError with `detail`, `code` or field messages), toasted like the HTTP client
 * toasts them.
 */
import { ApiError } from "@/api/http";
import type { Language, Page } from "@/api/types";
import { toast } from "@/components/useToast";
import { i18n } from "@/i18n";

import type { CallOptions } from "../api";
import { cleanZone, validateZones } from "../lib/geometry";
import type { Alert, CameraPatch, ClipRequest, Frame, Live, LiveCamera, VisionSettings } from "../types";
import { cyclePosition, delay } from "./clock";
import { createClip, getClip } from "./clips";
import { drawScene, jpegBase64 } from "./draw";
import { bodiesAt, framePeople, statsAt } from "./sim";
import {
  advancePairing,
  findAlert,
  historyAlerts,
  liveAlerts,
  newPairing,
  overview,
  publicAgent,
  publicAlert,
  publicCamera,
  review,
  site,
  withSnapshot,
  worldFor,
  type AgentRecord,
  type World,
} from "./world";

const RANGES: Partial<Record<keyof VisionSettings, [number, number]>> = {
  queue_people: [1, 20],
  queue_wait_s: [15, 1800],
  unattended_s: [15, 1800],
  clear_after_s: [5, 120],
  cooldown_s: [0, 3600],
  analysis_fps: [1, 5],
  live_fps: [1, 4],
  record_hours: [1, 168],
  stats_keep_days: [30, 800],
  photos_keep_days: [1, 365],
  clips_keep_days: [1, 365],
};

function language(): Language {
  const locale = i18n.global.locale.value;
  return locale === "ru" || locale === "en" ? locale : "uz";
}

function num(value: unknown): number | undefined {
  const n = Number(value);
  return value === undefined || value === null || value === "" || !Number.isFinite(n) ? undefined : n;
}

function notFound(): never {
  throw new ApiError(404, { detail: "Not found." });
}

export async function answer<T>(companyId: number, rest: string, options: CallOptions): Promise<T> {
  const method = options.method ?? "GET";
  const path = rest.replace(/^\/+/, "");
  const fast = /\/frame\/$/.test(path) || path === "live/";
  await delay(fast ? 25 + Math.random() * 40 : 140 + Math.random() * 220, options.signal);
  try {
    return route(worldFor(companyId), method, path, options) as T;
  } catch (error) {
    const wantsToast = options.toast ?? method !== "GET";
    if (error instanceof ApiError && wantsToast && error.detail) toast.error(error.detail);
    throw error;
  }
}

function route(world: World, method: string, path: string, options: CallOptions): unknown {
  const query = options.query ?? {};
  const body = (options.json ?? {}) as Record<string, unknown>;
  const branch = num(query.branch);
  let match: RegExpExecArray | null;

  if (path === "overview/" && method === "GET") return overview(world, { branch, day: (query.day as string) || undefined }, language());
  if (path === "live/" && method === "GET") return live(world, branch);
  if (path === "cameras/" && method === "GET") {
    advancePairing(world);
    return world.cameras.filter((c) => !branch || c.branch.id === branch).map((c) => publicCamera(withSnapshot(world, c)));
  }
  if ((match = /^cameras\/(\d+)\/frame\/$/.exec(path)) && method === "GET") return frame(world, Number(match[1]));
  if ((match = /^cameras\/(\d+)\/snapshot\/$/.exec(path)) && method === "POST") {
    const cam = world.cameras.find((c) => c.id === Number(match![1])) ?? notFound();
    world.snapshotsDue.set(cam.id, Date.now() + 2500);
    return undefined;
  }
  if ((match = /^cameras\/(\d+)\/$/.exec(path)) && method === "PATCH") return patchCamera(world, Number(match[1]), body as CameraPatch);
  if (path === "alerts/" && method === "GET") return alerts(world, query);
  if ((match = /^alerts\/(\d+)\/$/.exec(path)) && method === "GET") return findAlert(world, Number(match[1])) ?? notFound();
  if ((match = /^alerts\/(\d+)\/clip\/$/.exec(path)) && method === "POST") return createClip(world, { alert_id: Number(match[1]) });
  if (path === "clips/" && method === "POST") return createClip(world, body as unknown as ClipRequest);
  if ((match = /^clips\/(\d+)\/$/.exec(path)) && method === "GET") return getClip(world, Number(match[1]));
  if (path === "settings/" && method === "GET") return { ...world.settings };
  if (path === "settings/" && method === "PATCH") return patchSettings(world, body as Partial<VisionSettings>);
  if (path === "agents/" && method === "GET") {
    advancePairing(world);
    return world.agents.map(publicAgent);
  }
  if (path === "agents/" && method === "POST") return createAgent(world, body);
  if ((match = /^agents\/(\d+)\/pairing\/$/.exec(path)) && method === "POST") {
    const agent = world.agents.find((a) => a.id === Number(match![1])) ?? notFound();
    return newPairing(agent);
  }
  if ((match = /^agents\/(\d+)\/$/.exec(path)) && method === "DELETE") {
    const id = Number(match[1]);
    if (!world.agents.some((a) => a.id === id)) notFound();
    world.agents = world.agents.filter((a) => a.id !== id);
    for (const cam of world.cameras) if (cam.agent_id === id) cam.online = false;
    return undefined;
  }
  if (path === "review/" && method === "GET") return { items: review(world, { branch, day: (query.day as string) || undefined }) };
  notFound();
}

function live(world: World, branch: number | undefined): Live {
  const cameras: LiveCamera[] = world.cameras
    .filter((c) => !branch || c.branch.id === branch)
    .map((c) => {
      const agent = world.agents.find((a) => a.id === c.agent_id);
      const online = c.online && !!agent?.online;
      const where = site(c.variant);
      const stats = statsAt(where.scenes[c.scene], cyclePosition(where.offset).t);
      const counting = online && c.enabled;
      return {
        id: c.id,
        name: c.name,
        role: c.role,
        branch_id: c.branch.id,
        online,
        stale: !online,
        people: counting ? stats.people : null,
        queue: counting && c.role === "counter" ? stats.queue : null,
        staff: counting && c.role === "counter" ? stats.staff : null,
        wait_s: counting && c.role === "counter" ? stats.wait : null,
        fps: counting ? 2 : null,
      };
    });
  const scope = world.branches.filter((b) => !branch || b.id === branch);
  const day = overview(world, { branch }, language());
  return {
    at: new Date().toISOString(),
    today: { visitors: day.totals.visitors, receipts: day.totals.receipts },
    cameras,
    open_alerts: liveAlerts(world, scope.map((b) => b.id)),
  };
}

function frame(world: World, id: number): Frame | undefined {
  const cam = world.cameras.find((c) => c.id === id) ?? notFound();
  const agent = world.agents.find((a) => a.id === cam.agent_id);
  if (!cam.online || !agent?.online) return undefined;
  const where = site(cam.variant);
  const scene = where.scenes[cam.scene];
  const { t, cycle } = cyclePosition(where.offset);
  const bodies = bodiesAt(scene, t);
  const el = drawScene({ kind: cam.scene, variant: cam.variant, bodies, zones: cam.zones });
  return {
    at: new Date().toISOString(),
    w: 960,
    h: 540,
    // A camera that isn't analysed sends pictures without people (it only helps setting it up).
    people: cam.enabled ? framePeople({ ...scene, zones: cam.zones }, bodies, cycle) : [],
    image_b64: jpegBase64(el, 0.78),
  };
}

function patchCamera(world: World, id: number, patch: CameraPatch) {
  const cam = world.cameras.find((c) => c.id === id) ?? notFound();
  if (patch.zones) {
    const problems = validateZones(patch.zones);
    if (problems.length) throw new ApiError(400, { zones: problems.map((p) => `${p.zone ?? ""} ${p.code}`.trim()) });
    cam.zones = patch.zones.map(cleanZone);
  }
  if (patch.name !== undefined) {
    if (!patch.name.trim()) throw new ApiError(400, { name: [language() === "ru" ? "Обязательное поле." : language() === "en" ? "This field is required." : "Bu maydon to‘ldirilishi shart."] });
    cam.name = patch.name.trim();
  }
  // The picture stays what the camera sees; the role only says what it is for.
  if (patch.role !== undefined) cam.role = patch.role;
  if (patch.enabled !== undefined) cam.enabled = patch.enabled;
  if (patch.register_id !== undefined) cam.register = patch.register_id ? { id: patch.register_id, name: "Kassa 1" } : null;
  return publicCamera(withSnapshot(world, cam));
}

function patchSettings(world: World, patch: Partial<VisionSettings>): VisionSettings {
  const errors: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(patch) as Array<[keyof VisionSettings, unknown]>) {
    const range = RANGES[key];
    if (range && (typeof value !== "number" || value < range[0] || value > range[1])) errors[key] = [`${range[0]}–${range[1]}`];
  }
  if (Object.keys(errors).length) throw new ApiError(400, errors);
  Object.assign(world.settings, patch);
  return { ...world.settings };
}

function createAgent(world: World, body: Record<string, unknown>) {
  const name = String(body.name ?? "").trim();
  const branchId = num(body.branch_id);
  const branch = world.branches.find((b) => b.id === branchId);
  const errors: Record<string, string[]> = {};
  if (!name) errors.name = [language() === "ru" ? "Обязательное поле." : language() === "en" ? "This field is required." : "Bu maydon to‘ldirilishi shart."];
  if (!branch) errors.branch_id = [language() === "ru" ? "Выберите филиал." : language() === "en" ? "Pick a branch." : "Filialni tanlang."];
  if (Object.keys(errors).length) throw new ApiError(400, errors);
  const agent: AgentRecord = {
    id: world.nextId++,
    name,
    branch: { id: branch!.id, name: branch!.name },
    online: false,
    last_seen_at: null,
    version: null,
    host: null,
    paired: false,
    cameras: 0,
    created_at: new Date().toISOString(),
    variant: 2,
    pairing: null,
    pairedAt: null,
  };
  world.agents.push(agent);
  const pairing = newPairing(agent);
  return { agent: publicAgent(agent), pairing };
}

function alerts(world: World, query: Record<string, unknown>): Page<Alert> {
  const branch = num(query.branch);
  const state = query.state as string | undefined;
  const kind = query.kind as string | undefined;
  const from = query.from as string | undefined;
  const to = query.to as string | undefined;
  const page = num(query.page) ?? 1;
  const day = (iso: string) => new Intl.DateTimeFormat("en-CA", { timeZone: world.timezone }).format(new Date(iso));
  const all = [...liveAlerts(world, world.branches.map((b) => b.id)), ...historyAlerts(world)].filter(
    (alert) =>
      (!branch || alert.branch.id === branch) &&
      (!state || alert.state === state) &&
      (!kind || alert.kind === kind) &&
      (!from || day(alert.started_at) >= from) &&
      (!to || day(alert.started_at) <= to),
  );
  const size = num(query.page_size) ?? 50;
  const results = all.slice((page - 1) * size, page * size).map((alert) => publicAlert(world, alert));
  return { count: all.length, next: page * size < all.length ? `?page=${page + 1}` : null, previous: page > 1 ? `?page=${page - 1}` : null, results };
}
