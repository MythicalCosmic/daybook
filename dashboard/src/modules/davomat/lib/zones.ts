/**
 * Time zones for the setup wizard and the organization settings: Uzbekistan and its neighbours
 * first, then every zone the browser knows (a searchable list), with the offset right now.
 */
import type { SelectOption } from "@/components/options";

export const DEFAULT_ZONE = "Asia/Tashkent";

/** Zones named in the dictionary (`davomat.tz.<key>`), in the order they are offered. */
export const MAIN_ZONES: ReadonlyArray<{ zone: string; key: string }> = [
  { zone: "Asia/Tashkent", key: "tashkent" },
  { zone: "Asia/Samarkand", key: "samarkand" },
  { zone: "Asia/Almaty", key: "almaty" },
  { zone: "Asia/Bishkek", key: "bishkek" },
  { zone: "Asia/Dushanbe", key: "dushanbe" },
  { zone: "Asia/Ashgabat", key: "ashgabat" },
  { zone: "Europe/Moscow", key: "moscow" },
  { zone: "Europe/Istanbul", key: "istanbul" },
  { zone: "Asia/Dubai", key: "dubai" },
];

/** "UTC+5" for a zone now ("" when the browser doesn't know it). */
export function utcOffset(zone: string, now = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "shortOffset" })
      .formatToParts(now)
      .find((p) => p.type === "timeZoneName")?.value;
    return (part ?? "GMT").replace("GMT", "UTC").replace(/^UTC$/, "UTC+0");
  } catch {
    return "";
  }
}

/** The browser's own zone when it is a valid IANA name. */
export function browserZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

function allZones(): string[] {
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    return intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    return [];
  }
}

const cityOf = (zone: string) => zone.split("/").pop()!.replace(/_/g, " ");

/** Options for a ComboBox: the main zones by city, then the rest; `current` always among them. */
export function zoneOptions(t: (key: string) => string, current?: string | null): SelectOption<string>[] {
  const main = new Set(MAIN_ZONES.map((z) => z.zone));
  const options: SelectOption<string>[] = MAIN_ZONES.map(({ zone, key }) => ({
    value: zone,
    label: `${t(`davomat.tz.${key}`)} (${utcOffset(zone)})`,
    description: zone,
    group: t("davomat.tz.groupMain"),
    keywords: [zone, key],
  }));
  const rest = new Set(allZones());
  if (current && !main.has(current)) rest.add(current);
  for (const zone of [...rest].sort()) {
    if (main.has(zone)) continue;
    options.push({ value: zone, label: `${cityOf(zone)} (${utcOffset(zone)})`, description: zone, group: t("davomat.tz.groupOther"), keywords: [zone] });
  }
  return options;
}
