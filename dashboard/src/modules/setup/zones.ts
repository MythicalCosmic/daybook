/** Timezones offered when creating a company: Uzbekistan first, then its neighbours. */
import type { SelectOption } from "@/components/options";

const ZONES: ReadonlyArray<[zone: string, city: string]> = [
  ["Asia/Tashkent", "setup.tz.tashkent"],
  ["Asia/Samarkand", "setup.tz.samarkand"],
  ["Asia/Almaty", "setup.tz.almaty"],
  ["Asia/Bishkek", "setup.tz.bishkek"],
  ["Asia/Dushanbe", "setup.tz.dushanbe"],
  ["Europe/Moscow", "setup.tz.moscow"],
  ["Asia/Dubai", "setup.tz.dubai"],
];

function offset(zone: string): string {
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "shortOffset" }).formatToParts(new Date()).find((p) => p.type === "timeZoneName")?.value;
    return (part ?? "GMT").replace("GMT", "UTC");
  } catch {
    return "";
  }
}

export function zoneOptions(t: (key: string) => string): SelectOption<string>[] {
  return ZONES.map(([zone, city]) => ({ value: zone, label: `${t(city)} (${offset(zone)})`, description: zone, keywords: [zone] }));
}
