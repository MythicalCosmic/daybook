/** The timezones offered in Settings and "New company": Uzbekistan and its neighbours first. */
import type { SelectOption } from "@/components/options";

const ZONES: ReadonlyArray<{ zone: string; city: string; group: "uz" | "near" }> = [
  { zone: "Asia/Tashkent", city: "settings.tz.tashkent", group: "uz" },
  { zone: "Asia/Samarkand", city: "settings.tz.samarkand", group: "uz" },
  { zone: "Asia/Almaty", city: "settings.tz.almaty", group: "near" },
  { zone: "Asia/Bishkek", city: "settings.tz.bishkek", group: "near" },
  { zone: "Asia/Dushanbe", city: "settings.tz.dushanbe", group: "near" },
  { zone: "Asia/Ashgabat", city: "settings.tz.ashgabat", group: "near" },
  { zone: "Europe/Moscow", city: "settings.tz.moscow", group: "near" },
  { zone: "Europe/Istanbul", city: "settings.tz.istanbul", group: "near" },
  { zone: "Asia/Dubai", city: "settings.tz.dubai", group: "near" },
];

/** "UTC+5" for a zone right now. */
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

/** Options for a SelectBox; a zone the company already uses stays in the list even when unusual. */
export function timezoneOptions(current: string | null | undefined, t: (key: string) => string): SelectOption<string>[] {
  const options: SelectOption<string>[] = ZONES.map(({ zone, city, group }) => ({
    value: zone,
    label: `${t(city)} (${utcOffset(zone)})`,
    description: zone,
    group: t(group === "uz" ? "settings.tz.groupUz" : "settings.tz.groupNear"),
    keywords: [zone, city],
  }));
  if (current && !ZONES.some((z) => z.zone === current)) {
    options.push({ value: current, label: `${current} (${utcOffset(current)})`, group: t("settings.tz.groupOther") });
  }
  return options;
}
