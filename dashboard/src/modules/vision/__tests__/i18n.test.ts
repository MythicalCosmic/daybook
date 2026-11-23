/**
 * Every text Ko‘z shows exists in Uzbek, Russian and English: each key written in the module's
 * code, and each key built from a value (`vision.role.${role}`) for every value it can take. And
 * nothing in the dictionaries is left over that no screen uses.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import { DEFAULT_RULES } from "../lib/rules";
import { ALERT_KINDS, CAMERA_ROLES, CLIP_FAILURES, ZONE_KINDS } from "../types";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DICTIONARIES: Record<string, Record<string, string>> = { en, ru, uz };

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return entry === "__tests__" || entry === "fixtures" || entry === "i18n" ? [] : sources(full);
    return /\.(ts|vue)$/.test(entry) ? [full] : [];
  });
}

/** Keys written out in the code: in t(…), as registry titles, or any dotted `vision.a.b` literal. */
function writtenKeys(): Set<string> {
  const found = new Set<string>();
  for (const file of sources(ROOT)) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(/\bt\(\s*["'`](vision\.[\w.]+)["'`]/g)) found.add(match[1]!);
    for (const match of text.matchAll(/\b(?:title|description):\s*["'](vision\.[\w.]+)["']/g)) found.add(match[1]!);
    for (const match of text.matchAll(/["'`](vision\.[\w]+\.[\w.]+)["'`]/g)) found.add(match[1]!);
  }
  return found;
}

const SETTING_KEYS = Object.keys(DEFAULT_RULES);

/** Keys built from values: every value each one can take. */
const FAMILIES: string[] = [
  ...CAMERA_ROLES.flatMap((role) => [`vision.role.${role}`, `vision.roleHint.${role}`]),
  ...ZONE_KINDS.map((kind) => `vision.zone.${kind}`),
  ...["select", ...ZONE_KINDS].flatMap((tool) => [`vision.zones.tool.${tool}`, `vision.zones.hint.${tool}`]),
  ...ALERT_KINDS.map((kind) => `vision.alert.kind.${kind}`),
  ...["open", "resolved"].map((state) => `vision.state.${state}`),
  ...["bad", "warn", "info", "good"].map((severity) => `vision.severity.${severity}`),
  ...["no_entrance", "no_sales", "undercount", "no_visitors", "no_counter"].map((reason) => `vision.missing.${reason}`),
  ...["offline", "denied", "connecting", "waiting", "error"].map((state) => `vision.camera.${state}`),
  ...["queue", "staff", "line"].map((kind) => `vision.cameras.needs.${kind}`),
  ...["nvr", "rtsp", "webcam", "file", "sim"].map((source) => `vision.cameras.source.${source}`),
  ...[...CLIP_FAILURES, "unknown"].map((failure) => `vision.clip.failure.${failure}`),
  ...["void", "payout"].map((kind) => `vision.review.kind.${kind}`),
  ...SETTING_KEYS.flatMap((key) => [`vision.settings.${key}`, `vision.settings.${key}.hint`]),
  ...["rules", "who", "privacy", "recording"].flatMap((group) => [`vision.settings.${group}.title`, `vision.settings.${group}.body`]),
  ...["people", "s", "h", "days", "fps"].map((unit) => `vision.unit.${unit}`),
  ...["point1", "point2", "point3"].flatMap((point) => [`vision.pitch.${point}.title`, `vision.pitch.${point}.body`]),
  ...[1, 2, 3].map((n) => `vision.pitch.step${n}`),
  ...["too_many", "kind", "id_format", "id_duplicate", "polygon_few", "polygon_many", "line_points", "line_side", "range"].map((code) => `vision.zones.problem.${code}`),
];

/** Strings that look like keys but name something else (permissions, routes). */
const NOT_KEYS = new Set(["vision.view", "vision.video", "vision.manage"]);

describe("Ko‘z's texts", () => {
  const written = [...writtenKeys()].filter((key) => !NOT_KEYS.has(key) || key === "vision.video");
  const used = new Set([...written, ...FAMILIES]);

  it("finds the keys in the code", () => {
    expect(written.length).toBeGreaterThan(250);
    expect(written).toContain("vision.live.title");
    expect(written).toContain("vision.nav.overview");
  });

  it("has every key it uses in uz, ru and en, none empty", () => {
    const missing: string[] = [];
    for (const key of used) {
      for (const [language, dictionary] of Object.entries(DICTIONARIES)) {
        if (!dictionary[key]?.trim()) missing.push(`${language}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("keeps no text that no screen shows", () => {
    // Route names and permissions are not texts; everything else in a dictionary is shown somewhere.
    const unused = Object.keys(en).filter((key) => !used.has(key));
    expect(unused).toEqual([]);
  });

  it("writes Uzbek with the product's letters and keeps the three languages in step", () => {
    expect(Object.keys(uz).sort()).toEqual(Object.keys(en).sort());
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort());
    const wrong = Object.entries(uz).filter(([, text]) => /[oOgG]['`ʻ]/.test(text) || /[A-Za-z]'[A-Za-z]/.test(text));
    expect(wrong).toEqual([]);
    // The product's name is the same everywhere.
    expect([en["vision.title"], ru["vision.title"], uz["vision.title"]]).toEqual(["Ko‘z", "Ko‘z", "Ko‘z"]);
  });
});
