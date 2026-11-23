/**
 * Fixture mode only: one company's Ko‘z as the backend would keep it. A pharmacy company gets a
 * paired box per branch (the second branch with three cameras, one of them offline); a company
 * that isn't a pharmacy has none, so its overview shows the empty state that leads to pairing.
 * Days, hours and the alert history are generated from the date, the same on every load.
 */
import type { BranchRef, Company, Language } from "@/api/types";
import { addDays, todayIn, zonedIso } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { DEFAULT_RULES } from "../lib/rules";
import type { Agent, Alert, Camera, CameraRole, Clip, HourRow, Insight, Overview, Pairing, ReviewItem, VisionSettings, Zone } from "../types";
import { cyclePosition, isoAgo } from "./clock";
import { drawScene, jpegUrl, type DrawOptions } from "./draw";
import {
  CYCLE,
  bodiesAt,
  emptyScene,
  rng,
  simulateCounter,
  simulateEntrance,
  simulateFloor,
  simulateStoreroom,
  statsAt,
  type Incident,
  type Scene,
  type SceneKind,
} from "./sim";


export const STAFF = [
  { id: 9, name: "Madina Yusupova" },
  { id: 2, name: "Bekzod Mirzayev" },
  { id: 12, name: "Farrux Aliyev" },
  { id: 14, name: "Shahnoza Rahimova" },
  { id: 17, name: "Alimardon Tursunov" },
];

// ─── Scenes per branch ──────────────────────────────────────────────────────

interface Site {
  variant: number;
  /** Seconds the branch's cycle is shifted, so two branches never move in step. */
  offset: number;
  scenes: Record<SceneKind, Scene>;
}

const sites = new Map<number, Site>();

export function site(variant: number): Site {
  let found = sites.get(variant);
  if (!found) {
    const counter = simulateCounter(7 + variant * 31);
    found = {
      variant,
      offset: variant * 190,
      scenes: {
        counter,
        entrance: simulateEntrance(counter, 9 + variant),
        floor: simulateFloor(13 + variant),
        storeroom: simulateStoreroom(counter),
        empty: emptyScene(),
      },
    };
    sites.set(variant, found);
  }
  return found;
}

const SCENE_OF: Record<CameraRole, SceneKind> = { counter: "counter", entrance: "entrance", floor: "floor", storeroom: "storeroom", other: "empty" };

export interface CameraRecord extends Camera {
  scene: SceneKind;
  variant: number;
}

export interface AgentRecord extends Agent {
  variant: number;
  pairing: (Pairing & { at: number }) | null;
  /** When it paired (fixture time, ms), to bring its cameras in one by one. */
  pairedAt: number | null;
}

interface ClipRecord {
  clip: Clip;
  scene: SceneKind;
  variant: number;
  startT: number;
}

export interface World {
  companyId: number;
  branches: BranchRef[];
  timezone: string;
  agents: AgentRecord[];
  cameras: CameraRecord[];
  settings: VisionSettings;
  clips: Map<number, ClipRecord>;
  /** Clips asked for review items and alerts, by their key. */
  clipOf: Map<string, number>;
  snapshotsDue: Map<number, number>;
  nextId: number;
}

const worlds = new Map<number, World>();

function snapshot(kind: SceneKind, variant: number, zones: Zone[], t: number): string {
  const scene = site(variant).scenes[kind];
  return jpegUrl(drawScene({ kind, variant, bodies: bodiesAt(scene, t), zones }));
}

function camera(id: number, key: string, name: string, role: CameraRole, branch: BranchRef, agent: number, variant: number, extra: Partial<CameraRecord> = {}): CameraRecord {
  const scene = SCENE_OF[role];
  const zones = role === "other" || role === "storeroom" ? [] : site(variant).scenes[scene].zones.map((zone) => ({ ...zone, points: zone.points.map((p) => [...p] as [number, number]) }));
  return {
    id,
    key,
    name,
    role,
    enabled: role !== "other" && role !== "storeroom",
    branch: { id: branch.id, name: branch.name },
    agent_id: agent,
    source: "nvr",
    channel: Number(key.split(":")[1]),
    w: 1920,
    h: 1080,
    online: true,
    last_seen_at: isoAgo(3),
    zones,
    register: null,
    snapshot_url: null,
    snapshot_at: isoAgo(6 * 60 + id * 17),
    scene,
    variant,
    ...extra,
  };
}

export function worldFor(companyId: number): World {
  let world = worlds.get(companyId);
  if (world) return world;
  const store = useCompanyStore();
  const company: Company | undefined = store.companies.find((c) => c.id === companyId) ?? store.current ?? undefined;
  const branches = company?.branches ?? [];
  const pharmacy = !company || company.business_kind !== "distributor";
  world = {
    companyId,
    branches,
    timezone: company?.timezone ?? "Asia/Tashkent",
    agents: [],
    cameras: [],
    settings: { ...DEFAULT_RULES },
    clips: new Map(),
    clipOf: new Map(),
    snapshotsDue: new Map(),
    nextId: 1000,
  };
  if (pharmacy) {
    branches.slice(0, 2).forEach((branch, index) => {
      const agentId = 4 + index;
      world!.agents.push({
        id: agentId,
        name: `${branch.name} qutisi`,
        branch: { id: branch.id, name: branch.name },
        online: true,
        last_seen_at: isoAgo(4),
        version: "0.1.0",
        host: index === 0 ? { hostname: "KASSA-PC", os: "Windows 11" } : { hostname: "dorixona-2", os: "Ubuntu 24.04" },
        paired: true,
        cameras: index === 0 ? 5 : 3,
        created_at: isoAgo((14 - index * 3) * 86_400),
        variant: index,
        pairing: null,
        pairedAt: null,
      });
      const base = index === 0 ? 11 : 21;
      world!.cameras.push(
        camera(base, "nvr:1", "Kirish", "entrance", branch, agentId, index),
        camera(base + 1, "nvr:2", "Kassa 1", "counter", branch, agentId, index, { register: { id: index + 1, name: "Kassa 1" } }),
        camera(base + 2, "nvr:3", "Zal", "floor", branch, agentId, index, index === 1 ? { online: false, last_seen_at: isoAgo(41 * 60) } : {}),
      );
      if (index === 0) {
        world!.cameras.push(
          camera(base + 3, "nvr:4", "Ombor", "storeroom", branch, agentId, index),
          camera(base + 4, "nvr:5", "Kamera 5", "other", branch, agentId, index, { snapshot_at: isoAgo(25 * 60) }),
        );
      }
    });
  }
  worlds.set(companyId, world);
  return world;
}

/** Snapshots are drawn on first use (a canvas is needed), then kept. */
export function withSnapshot(world: World, record: CameraRecord): CameraRecord {
  const due = world.snapshotsDue.get(record.id);
  if (due && Date.now() >= due) {
    world.snapshotsDue.delete(record.id);
    record.snapshot_url = null;
    record.snapshot_at = new Date().toISOString();
  }
  if (!record.snapshot_url) {
    const { t } = cyclePosition(site(record.variant).offset);
    record.snapshot_url = snapshot(record.scene, record.variant, record.zones, due ? t : (20 + record.id * 7) % CYCLE);
  }
  return record;
}

export function publicCamera(record: CameraRecord): Camera {
  const { scene: _scene, variant: _variant, ...camera } = record;
  return camera;
}

export function publicAgent(record: AgentRecord): Agent {
  const { variant: _variant, pairing: _pairing, pairedAt: _pairedAt, ...agent } = record;
  return agent;
}

// ─── Pairing ────────────────────────────────────────────────────────────────

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function pairingCode(random = Math.random): string {
  const part = () => Array.from({ length: 4 }, () => CROCKFORD[Math.floor(random() * 32)]).join("");
  return `KOZ-${part()}-${part()}`;
}

export function newPairing(agent: AgentRecord): Pairing {
  const code = pairingCode();
  const pairing = { code, expires_at: new Date(Date.now() + 15 * 60_000).toISOString(), command: `koz-agent pair https://daybook.example ${code}`, at: Date.now() };
  agent.pairing = pairing;
  if (agent.paired) {
    // A new code issues a new token and revokes the old one: the box is offline until it pairs again.
    agent.paired = false;
    agent.online = false;
  }
  return { code: pairing.code, expires_at: pairing.expires_at, command: pairing.command };
}

/** A box someone is pairing comes online a few seconds later, and its cameras arrive one by one. */
export function advancePairing(world: World): void {
  for (const agent of world.agents) {
    if (!agent.paired && agent.pairing && Date.now() - agent.pairing.at > 7_000) {
      agent.paired = true;
      agent.online = true;
      agent.host = { hostname: "KASSA-PC", os: "Windows 11" };
      agent.version = "0.1.0";
      agent.last_seen_at = new Date().toISOString();
      agent.pairing = null;
      agent.pairedAt ??= Date.now();
    }
    if (agent.paired && agent.pairedAt) {
      const due = Math.min(4, Math.floor((Date.now() - agent.pairedAt) / 1300) + 1);
      const branch = world.branches.find((b) => b.id === agent.branch.id) ?? { id: agent.branch.id, name: agent.branch.name, code: "" };
      const roles: CameraRole[] = ["counter", "entrance", "floor", "storeroom"];
      while (world.cameras.filter((c) => c.agent_id === agent.id).length < due) {
        const n = world.cameras.filter((c) => c.agent_id === agent.id).length;
        const record = camera(world.nextId++, `nvr:${n + 1}`, `Kamera ${n + 1}`, "other", branch, agent.id, 2, { snapshot_at: new Date().toISOString() });
        record.scene = SCENE_OF[roles[n]!];
        world.cameras.push(record);
      }
      agent.cameras = world.cameras.filter((c) => c.agent_id === agent.id).length;
      agent.last_seen_at = new Date().toISOString();
    }
  }
}

// ─── Days and hours ─────────────────────────────────────────────────────────

const VISITORS = [0, 0, 0, 0, 0, 0, 0, 0, 9, 18, 24, 27, 31, 29, 25, 27, 33, 45, 61, 52, 34, 17, 0, 0];
const RECEIPTS = [0, 0, 0, 0, 0, 0, 0, 0, 7, 14, 18, 20, 23, 22, 19, 20, 24, 30, 34, 36, 26, 13, 0, 0];
const QUEUE = [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2, 3, 3, 2, 2, 2, 3, 4, 6, 5, 3, 1, 0, 0];
const WAIT = [0, 0, 0, 0, 0, 0, 0, 0, 25, 40, 55, 70, 95, 60, 45, 50, 80, 130, 260, 190, 75, 30, 0, 0];
const AT_COUNTER = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1.1, 1.3, 1.4, 1.2, 1.5, 1.6, 1.4, 1.5, 1.6, 1, 1.7, 1.4, 1, 0, 0];
const ON_SHIFT = [0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 2, 2, 0, 0];
const UNATTENDED = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 2, 0, 0, 9, 0, 0, 0, 0, 0];

function hashDay(day: string, salt: number): number {
  let hash = salt * 7919;
  for (const char of day) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  return Math.abs(hash);
}

function localNow(tz: string): { day: string; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date());
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return { day: todayIn(tz), hour, minute };
}

/** One branch's hours of a day; today stops at the current minute. */
function branchHours(branchIndex: number, day: string, until: { hour: number; minute: number } | null): HourRow[] {
  const random = rng(hashDay(day, branchIndex + 1));
  const size = (branchIndex === 0 ? 1 : 0.7) * (0.88 + random() * 0.24) * (new Date(`${day}T12:00:00Z`).getUTCDay() === 0 ? 0.8 : 1);
  const buys = 0.97 + random() * 0.06;
  return VISITORS.map((visitors, hour) => {
    const share = !until || hour < until.hour ? 1 : hour === until.hour ? until.minute / 60 : 0;
    const v = Math.round(visitors * size * share);
    const r = Math.min(v, Math.round(RECEIPTS[hour]! * size * buys * share));
    return {
      hour,
      visitors: v,
      receipts: r,
      queue_max: share ? Math.max(0, Math.round(QUEUE[hour]! * (branchIndex ? 0.8 : 1))) : 0,
      wait_max_s: share ? Math.round(WAIT[hour]! * (branchIndex ? 0.75 : 1) * (0.9 + random() * 0.2)) : 0,
      staff_avg: share ? Math.round(AT_COUNTER[hour]! * 10) / 10 : 0,
      staff_checked_in: share ? ON_SHIFT[hour]! : 0,
      unattended_minutes: share ? Math.round(UNATTENDED[hour]! * (branchIndex ? 0.5 : 1)) : 0,
    };
  });
}

function sumHours(lists: HourRow[][]): HourRow[] {
  return Array.from({ length: 24 }, (_, hour) => {
    const rows = lists.map((list) => list[hour]!);
    const add = (key: keyof HourRow) => rows.reduce((sum, row) => sum + ((row[key] as number | null) ?? 0), 0);
    return {
      hour,
      visitors: add("visitors"),
      receipts: add("receipts"),
      queue_max: Math.max(...rows.map((row) => row.queue_max ?? 0)),
      wait_max_s: Math.max(...rows.map((row) => row.wait_max_s ?? 0)),
      staff_avg: Math.round(add("staff_avg") * 10) / 10,
      staff_checked_in: add("staff_checked_in"),
      unattended_minutes: add("unattended_minutes"),
    };
  });
}

const TEXTS: Record<Language, Record<Insight["kind"], string>> = {
  uz: {
    lost_peak: "{range}: {v} kishi kirdi, {r} kishi xarid qildi. Navbat {q} kishiga yetdi, kassada esa {staff} turdi: {left} kishi xarid qilmay ketdi.",
    staff_gap: "{range}: ishda {checked} kishi bor edi, lekin kassada o‘rtacha {avg} kishi turdi.",
    unattended: "Jami {n} daqiqa mijozlar kutib turdi, kassada esa hech kim yo‘q edi.",
    long_wait: "Eng uzoq kutish {wait} bo‘ldi ({range}).",
    good_day: "Konversiya {now}: o‘tgan haftaning shu kunidagidan {pts} punkt yuqori.",
  },
  ru: {
    lost_peak: "{range}: зашли {v} человек, купили {r}. Очередь доходила до {q} человек, а за кассой стоял {staff}: {left} человек ушли без покупки.",
    staff_gap: "{range}: на смене было {checked} человека, но за кассой в среднем стоял {avg}.",
    unattended: "Всего {n} минут покупатели ждали, а за кассой никого не было.",
    long_wait: "Самое долгое ожидание — {wait} ({range}).",
    good_day: "Конверсия {now}: на {pts} п. п. выше, чем в тот же день прошлой недели.",
  },
  en: {
    lost_peak: "{range}: {v} people came in and {r} bought. The queue reached {q} while {staff} stood at the counter: {left} left without buying.",
    staff_gap: "{range}: {checked} people were on shift, but on average only {avg} stood at the counter.",
    unattended: "Customers waited for {n} minutes in all with nobody at the counter.",
    long_wait: "The longest wait was {wait} ({range}).",
    good_day: "Conversion {now}: {pts} points above the same day last week.",
  },
};

const ONE_PHARMACIST: Record<Language, string> = { uz: "bitta farmatsevt", ru: "один фармацевт", en: "only one pharmacist" };
const PHARMACISTS: Record<Language, (n: number) => string> = { uz: (n) => `${n} farmatsevt`, ru: (n) => `${n} фармацевта`, en: (n) => `${n} pharmacists` };

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => String(values[key] ?? ""));
}

function range(hour: number): string {
  const pad = (h: number) => `${String(h % 24).padStart(2, "0")}:00`;
  return `${pad(hour)}–${pad(hour + 1)}`;
}

function waitText(seconds: number, lang: Language): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return lang === "uz" ? `${m} daq ${s} s` : lang === "ru" ? `${m} мин ${s} с` : `${m} min ${s} s`;
}

function percent(value: number, lang: Language): string {
  const text = (Math.round(value * 10) / 10).toString().replace(".", lang === "en" ? "." : ",");
  return lang === "ru" ? `${text} %` : `${text}%`;
}

function insights(hours: HourRow[], totals: Overview["totals"], lang: Language, rules: VisionSettings): Insight[] {
  const out: Insight[] = [];
  const t = TEXTS[lang];
  let worst: HourRow | null = null;
  for (const row of hours) if ((row.visitors ?? 0) - (row.receipts ?? 0) > ((worst?.visitors ?? 0) - (worst?.receipts ?? 0))) worst = row;
  const lost = worst ? (worst.visitors ?? 0) - (worst.receipts ?? 0) : 0;
  if (worst && lost >= 10 && (worst.wait_max_s ?? 0) >= rules.queue_wait_s) {
    const staff = (worst.staff_avg ?? 0) < 1.5 ? ONE_PHARMACIST[lang] : PHARMACISTS[lang](Math.round(worst.staff_avg ?? 0));
    out.push({ kind: "lost_peak", severity: "bad", hour: worst.hour, text: fill(t.lost_peak, { range: range(worst.hour), v: worst.visitors ?? 0, r: worst.receipts ?? 0, q: worst.queue_max ?? 0, staff, left: lost }) });
    if ((worst.staff_checked_in ?? 0) - (worst.staff_avg ?? 0) >= 1.5) {
      out.push({ kind: "staff_gap", severity: "warn", hour: worst.hour, text: fill(t.staff_gap, { range: range(worst.hour), checked: worst.staff_checked_in ?? 0, avg: Math.round(worst.staff_avg ?? 0) }) });
    }
  }
  if ((totals.unattended_minutes ?? 0) >= 5) out.push({ kind: "unattended", severity: "warn", hour: null, text: fill(t.unattended, { n: totals.unattended_minutes ?? 0 }) });
  const longest = [...hours].sort((a, b) => (b.wait_max_s ?? 0) - (a.wait_max_s ?? 0))[0];
  if (out.length < 3 && longest && (longest.wait_max_s ?? 0) >= 240) out.push({ kind: "long_wait", severity: "warn", hour: longest.hour, text: fill(t.long_wait, { wait: waitText(longest.wait_max_s ?? 0, lang), range: range(longest.hour) }) });
  if (totals.conversion !== null && totals.compare?.conversion) {
    const points = (totals.conversion - totals.compare.conversion) * 100;
    if (points >= 1) out.push({ kind: "good_day", severity: "good", hour: null, text: fill(t.good_day, { now: percent(totals.conversion * 100, lang), pts: (Math.round(points * 10) / 10).toString().replace(".", lang === "en" ? "." : ",") }) });
  }
  return out.slice(0, 4);
}

export function overview(world: World, query: { branch?: number; day?: string }, lang: Language): Overview {
  const today = todayIn(world.timezone);
  const day = query.day && query.day <= today ? query.day : today;
  const scope = world.branches.filter((b) => !query.branch || b.id === query.branch);
  const boxed = scope.filter((b) => world.agents.some((a) => a.branch.id === b.id && a.paired));
  const now = localNow(world.timezone);
  const until = day === today ? { hour: now.hour, minute: now.minute } : null;
  const lists = boxed.map((b) => branchHours(world.branches.indexOf(b), day, until));
  const hours = lists.length ? sumHours(lists) : Array.from({ length: 24 }, (_, hour) => ({ hour, visitors: 0, receipts: 0, queue_max: 0, wait_max_s: 0, staff_avg: 0, staff_checked_in: 0, unattended_minutes: 0 }));
  const before = boxed.length ? sumHours(boxed.map((b) => branchHours(world.branches.indexOf(b), addDays(day, -7), until).map((row) => ({ ...row, receipts: Math.round((row.receipts ?? 0) * 0.955) })))) : [];
  const total = (rows: HourRow[], key: "visitors" | "receipts") => rows.reduce((sum, row) => sum + (row[key] ?? 0), 0);
  const visitors = total(hours, "visitors");
  const receipts = total(hours, "receipts");
  const compareVisitors = total(before, "visitors");
  const compareReceipts = total(before, "receipts");
  const conversion = visitors > 0 && visitors >= receipts ? receipts / visitors : null;
  const alerts = historyAlerts(world).filter((alert) => dayOf(world, alert.started_at) === day && scope.some((b) => b.id === alert.branch.id));
  const totals: Overview["totals"] = {
    visitors: boxed.length ? visitors : null,
    receipts: boxed.length ? receipts : null,
    conversion: boxed.length ? conversion : null,
    conversion_note: null,
    left: boxed.length ? Math.max(visitors - receipts, 0) : null,
    wait_avg_s: boxed.length ? 38 + (hashDay(day, 3) % 9) : null,
    wait_max_s: boxed.length ? Math.max(...hours.map((row) => row.wait_max_s ?? 0)) : null,
    alerts: alerts.length,
    unattended_minutes: hours.reduce((sum, row) => sum + (row.unattended_minutes ?? 0), 0),
    compare: boxed.length ? { visitors: compareVisitors, receipts: compareReceipts, conversion: compareVisitors ? compareReceipts / compareVisitors : null, label: "same_weekday_last_week" } : null,
  };
  const agents = world.agents.filter((a) => scope.some((b) => b.id === a.branch.id));
  return {
    day,
    branch: query.branch ? (scope[0] ? { id: scope[0].id, name: scope[0].name } : null) : null,
    setup: {
      agents: agents.length,
      cameras: world.cameras.filter((c) => scope.some((b) => b.id === c.branch.id)).length,
      entrance: world.cameras.some((c) => c.role === "entrance" && c.enabled && scope.some((b) => b.id === c.branch.id)),
      counter: world.cameras.some((c) => c.role === "counter" && c.enabled && scope.some((b) => b.id === c.branch.id)),
    },
    agents: agents.map((a) => ({ id: a.id, name: a.name, branch_id: a.branch.id, online: a.online, last_seen_at: a.last_seen_at, version: a.version })),
    totals,
    hours,
    insights: boxed.length ? insights(hours, totals, lang, world.settings) : [],
    open_alerts: day === today ? liveAlerts(world, scope.map((b) => b.id)) : [],
  };
}

function dayOf(world: World, iso: string): string {
  return todayIn(world.timezone, new Date(iso));
}

// ─── Alerts ─────────────────────────────────────────────────────────────────

const photos = new Map<number, string>();

function counterCamera(world: World, branchId: number): CameraRecord | undefined {
  return world.cameras.find((c) => c.branch.id === branchId && c.role === "counter");
}

function photoFor(world: World, alert: Alert, t: number, variant: number): string | null {
  if (alert.kind === "agent_offline") return null;
  let url = photos.get(alert.id);
  if (!url) {
    const scene = site(variant).scenes.counter;
    const time = new Intl.DateTimeFormat("en-GB", { timeZone: world.timezone, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(new Date(alert.started_at));
    const options: DrawOptions = { kind: "counter", variant, bodies: bodiesAt(scene, t), zones: scene.zones, annotate: { caption: `${alert.camera?.name ?? ""} · ${dayOf(world, alert.started_at)} ${time}`, waitOver: world.settings.queue_wait_s } };
    url = jpegUrl(drawScene(options), 0.78);
    photos.set(alert.id, url);
  }
  return url;
}

/** The alerts the clock opened right now, for the given branches. */
export function liveAlerts(world: World, branchIds: number[]): Alert[] {
  const out: Alert[] = [];
  world.branches.forEach((branch, index) => {
    if (!branchIds.includes(branch.id) || index > 1) return;
    const cam = counterCamera(world, branch.id);
    const agent = world.agents.find((a) => a.branch.id === branch.id);
    if (!cam || !cam.enabled || !agent?.online) return;
    const where = site(index);
    const { t, cycle } = cyclePosition(where.offset);
    where.scenes.counter.incidents.forEach((incident, n) => {
      if (t < incident.start || t >= incident.end) return;
      out.push(incidentAlert(world, branch, cam, incident, n, cycle, t, index));
    });
  });
  return out;
}

function incidentAlert(world: World, branch: BranchRef, cam: CameraRecord, incident: Incident, n: number, cycle: number, t: number, variant: number): Alert {
  const scene = site(variant).scenes.counter;
  let peakQueue = 0;
  let peakWait = 0;
  for (let s = incident.start; s <= t; s += 1) {
    const stats = statsAt(scene, s);
    peakQueue = Math.max(peakQueue, stats.queue);
    peakWait = Math.max(peakWait, stats.wait);
  }
  const id = 800_000 + variant * 10_000 + (cycle % 1000) * 10 + n;
  const acked = incident.ackAt !== null && t >= incident.ackAt;
  const alert: Alert = {
    id,
    kind: incident.kind,
    state: "open",
    branch: { id: branch.id, name: branch.name },
    camera: { id: cam.id, name: cam.name },
    started_at: isoAgo(t - incident.start),
    resolved_at: null,
    duration_s: Math.floor(t - incident.start),
    peak_queue: peakQueue,
    peak_wait_s: peakWait,
    acknowledged_by: acked ? STAFF[0]! : null,
    acknowledged_at: acked ? isoAgo(t - incident.ackAt!) : null,
    photo_url: null,
    clip: clipRef(world, `alert:${id}`),
  };
  alert.photo_url = photoFor(world, alert, incident.start + 4, variant);
  return alert;
}

function clipRef(world: World, key: string): Alert["clip"] {
  const id = world.clipOf.get(key);
  const record = id ? world.clips.get(id) : undefined;
  return record ? { id: record.clip.id, state: record.clip.state } : null;
}

interface HistoryAlert extends Alert {
  photoAt: number;
  variant: number;
}

const history = new Map<number, HistoryAlert[]>();

/** Fourteen days of alerts per branch with a box, generated from the dates. */
export function historyAlerts(world: World): Alert[] {
  const today = todayIn(world.timezone);
  const key = world.companyId;
  let list = history.get(key);
  const stamp = `${today}`;
  if (!list || (list as HistoryAlert[] & { stamp?: string }).stamp !== stamp) {
    list = [];
    world.branches.slice(0, 2).forEach((branch, index) => {
      const cam = counterCamera(world, branch.id);
      if (!cam) return;
      for (let d = 0; d < 14; d++) {
        const day = addDays(today, -d);
        const random = rng(hashDay(day, 40 + index));
        const times = d === 0 && index === 0 ? ["12:41", "18:12", "18:47"] : Array.from({ length: 1 + Math.floor(random() * 3) }, () => `${17 + Math.floor(random() * 3)}:${String(Math.floor(random() * 60)).padStart(2, "0")}`);
        times.sort().forEach((time, n) => {
          const kind = d === 0 && index === 0 ? (["queue", "queue", "unattended"] as const)[n]! : random() < 0.72 ? "queue" : "unattended";
          const started = zonedIso(day, time, world.timezone);
          if (new Date(started).getTime() > Date.now() - 20 * 60_000) return;
          const duration = kind === "queue" ? 140 + Math.floor(random() * 400) : 70 + Math.floor(random() * 160);
          const acked = random() < 0.75;
          const who = STAFF[Math.floor(random() * STAFF.length)]!;
          list!.push({
            id: 5000 + index * 1000 + d * 10 + n,
            kind,
            state: "resolved",
            branch: { id: branch.id, name: branch.name },
            camera: { id: cam.id, name: cam.name },
            started_at: started,
            resolved_at: new Date(new Date(started).getTime() + duration * 1000).toISOString(),
            duration_s: duration,
            peak_queue: kind === "queue" ? 3 + Math.floor(random() * 4) : 1 + Math.floor(random() * 2),
            peak_wait_s: kind === "queue" ? 125 + Math.floor(random() * 240) : 95 + Math.floor(random() * 100),
            acknowledged_by: acked ? who : null,
            acknowledged_at: acked ? new Date(new Date(started).getTime() + (20 + random() * 70) * 1000).toISOString() : null,
            photo_url: null,
            clip: d > 9 && n === 0 ? { id: 90_000 + index * 100 + d, state: "failed" } : null,
            photoAt: kind === "queue" ? 196 + (n % 3) * 9 : 392,
            variant: index,
          });
        });
        if (index === 1 && d === 3) {
          const started = zonedIso(day, "21:36", world.timezone);
          list!.push({
            id: 5000 + index * 1000 + d * 10 + 9,
            kind: "agent_offline",
            state: "resolved",
            branch: { id: branch.id, name: branch.name },
            camera: null,
            started_at: started,
            resolved_at: new Date(new Date(started).getTime() + 22 * 60_000).toISOString(),
            duration_s: 22 * 60,
            peak_queue: null,
            peak_wait_s: null,
            acknowledged_by: null,
            acknowledged_at: null,
            photo_url: null,
            clip: null,
            photoAt: 0,
            variant: index,
          });
        }
      }
    });
    list.sort((a, b) => (a.started_at < b.started_at ? 1 : -1));
    (list as HistoryAlert[] & { stamp?: string }).stamp = stamp;
    history.set(key, list);
  }
  return list;
}

/** A history alert with its photo and current clip, as the API answers it. */
export function publicAlert(world: World, alert: Alert): Alert {
  const record = alert as HistoryAlert;
  if (record.photoAt === undefined) return alert;
  const { photoAt, variant, ...rest } = record;
  const clip = clipRef(world, `alert:${alert.id}`) ?? rest.clip;
  return { ...rest, clip, photo_url: photoFor(world, rest, photoAt, variant) };
}

export function findAlert(world: World, id: number): Alert | null {
  const live = liveAlerts(world, world.branches.map((b) => b.id)).find((alert) => alert.id === id);
  if (live) return live;
  const past = historyAlerts(world).find((alert) => alert.id === id);
  return past ? publicAlert(world, past) : null;
}

// ─── Review (voids and payouts with nobody at the counter) ─────────────────

export function review(world: World, query: { branch?: number; day?: string }): ReviewItem[] {
  const today = todayIn(world.timezone);
  const day = query.day && query.day <= today ? query.day : today;
  const items: ReviewItem[] = [];
  world.branches.slice(0, 2).forEach((branch, index) => {
    if (query.branch && query.branch !== branch.id) return;
    const cam = counterCamera(world, branch.id);
    if (!cam) return;
    const random = rng(hashDay(day, 70 + index));
    const plan: Array<{ kind: ReviewItem["kind"]; time: string; amount: string }> =
      index === 0
        ? [
            { kind: "void", time: "13:05", amount: "54500.00" },
            { kind: "void", time: "18:24", amount: "186000.00" },
            { kind: "payout", time: "20:51", amount: "300000.00" },
          ]
        : [{ kind: random() < 0.5 ? "void" : "payout", time: "19:3" + Math.floor(random() * 10), amount: `${(40 + Math.floor(random() * 200)) * 1000}.00` }];
    plan.forEach((entry, n) => {
      const at = zonedIso(day, entry.time, world.timezone);
      if (new Date(at).getTime() > Date.now()) return;
      const saleId = entry.kind === "void" ? 1 + n + index * 3 : null;
      items.push({
        kind: entry.kind,
        at,
        amount: entry.amount,
        sale_id: saleId,
        cash_movement_id: entry.kind === "payout" ? 40 + n + index : null,
        cashier: STAFF[(n + index + 1) % STAFF.length]!,
        camera: { id: cam.id, name: cam.name },
        queue_max: 0,
        clip: clipRef(world, saleId ? `sale:${saleId}` : `at:${cam.id}:${at}`),
      });
    });
  });
  return items.sort((a, b) => (a.at < b.at ? 1 : -1));
}

export type { ClipRecord };
