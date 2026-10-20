/** Times of day as the API sends them ("HH:MM", 24-hour), and the quick ways people type them. */

const pad = (n: number) => String(n).padStart(2, "0");

export function toMinutes(time: string): number {
  return Number(time.slice(0, 2)) * 60 + Number(time.slice(3, 5));
}

export function fromMinutes(minutes: number): string {
  const wrapped = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${pad(Math.floor(wrapped / 60))}:${pad(wrapped % 60)}`;
}

/** "9" → "09:00", "930" → "09:30", "9:5" → "09:05", "21.15" → "21:15"; null when it isn't a time. */
export function parseTime(raw: string): string | null {
  const text = raw.trim();
  if (!text) return null;
  let hours: number;
  let minutes: number;
  const separated = /^(\d{1,2})\s*[:.,hч ]\s*(\d{1,2})$/i.exec(text);
  if (separated) {
    hours = Number(separated[1]);
    minutes = Number(separated[2]);
  } else if (/^\d{1,4}$/.test(text)) {
    hours = Number(text.length <= 2 ? text : text.slice(0, -2));
    minutes = text.length <= 2 ? 0 : Number(text.slice(-2));
  } else {
    return null;
  }
  if (hours > 23 || minutes > 59) return null;
  return `${pad(hours)}:${pad(minutes)}`;
}
