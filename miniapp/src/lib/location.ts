/**
 * Where the person is, for check-in and anything else that needs a position.
 *
 * Inside Telegram 8.0+ the LocationManager asks once per bot and remembers the answer; elsewhere
 * (older clients, desktop, a browser during development) the browser's geolocation stands in.
 * The result always says how accurate the fix is, so the server can decide what "at the branch"
 * means, and failures come back as a reason instead of an exception.
 */

import type { Lang } from "../i18n";

export type LocationSource = "telegram" | "browser";

export type LocationFix = {
  latitude: number;
  longitude: number;
  /** Radius in meters the device is confident about, or null when it doesn't say. */
  accuracy: number | null;
  source: LocationSource;
  /** When the fix was taken (ms since epoch). */
  at: number;
};

export type LocationFailure = "denied" | "unavailable" | "timeout" | "unsupported";

export type LocationResult =
  | { ok: true; fix: LocationFix }
  /** `canOpenSettings`: Telegram can open its location settings so the person can allow access. */
  | { ok: false; reason: LocationFailure; canOpenSettings: boolean };

export type LocationOptions = {
  /** Give up after this long (default 15 s). */
  timeoutMs?: number;
  /** Ask the browser for GPS-grade accuracy (default true). */
  highAccuracy?: boolean;
  /** Accept a browser fix this old (default 30 s). */
  maximumAgeMs?: number;
};

type WebApp = Window["Telegram"]["WebApp"];

/** What the lookup talks to; tests pass fakes. */
export type LocationEnv = {
  webApp?: Pick<WebApp, "isVersionAtLeast" | "LocationManager"> | undefined;
  geolocation?: Pick<Geolocation, "getCurrentPosition"> | undefined;
  now?: () => number;
};

function defaultEnv(): LocationEnv {
  return {
    webApp: typeof window !== "undefined" ? window.Telegram?.WebApp : undefined,
    geolocation: typeof navigator !== "undefined" ? navigator.geolocation : undefined,
    now: Date.now,
  };
}

/** The LocationManager, when this Telegram client has one (Bot API 8.0+). */
function locationManager(env: LocationEnv) {
  const webApp = env.webApp;
  if (!webApp?.LocationManager || !webApp.isVersionAtLeast?.("8.0")) return null;
  return webApp.LocationManager;
}

function withTimeout<T>(promise: Promise<T>, ms: number, onTimeout: T): Promise<T> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(onTimeout), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        clearTimeout(timer);
        resolve(onTimeout);
      },
    );
  });
}

const failure = (reason: LocationFailure, canOpenSettings = false): LocationResult => ({ ok: false, reason, canOpenSettings });

function fromTelegram(env: LocationEnv): Promise<LocationResult | null> {
  const manager = locationManager(env);
  if (!manager) return Promise.resolve(null);
  return new Promise((resolve) => {
    const ask = () => {
      // No location services on this device: let the browser try before giving up.
      if (!manager.isLocationAvailable) {
        resolve(null);
        return;
      }
      if (manager.isAccessRequested && !manager.isAccessGranted) {
        resolve(failure("denied", true));
        return;
      }
      manager.getLocation((data) => {
        if (!data) {
          resolve(failure("denied", true));
          return;
        }
        resolve({
          ok: true,
          fix: {
            latitude: data.latitude,
            longitude: data.longitude,
            accuracy: data.horizontal_accuracy ?? null,
            source: "telegram",
            at: (env.now ?? Date.now)(),
          },
        });
      });
    };
    if (manager.isInited) ask();
    else manager.init(ask);
  });
}

function fromBrowser(env: LocationEnv, options: Required<LocationOptions>): Promise<LocationResult> {
  const geolocation = env.geolocation;
  if (!geolocation) return Promise.resolve(failure("unsupported"));
  return new Promise((resolve) => {
    geolocation.getCurrentPosition(
      (position) =>
        resolve({
          ok: true,
          fix: {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: Number.isFinite(position.coords.accuracy) ? position.coords.accuracy : null,
            source: "browser",
            at: position.timestamp || (env.now ?? Date.now)(),
          },
        }),
      (error) => {
        // GeolocationPositionError codes: 1 denied, 2 unavailable, 3 timeout.
        const reason: LocationFailure = error.code === 1 ? "denied" : error.code === 3 ? "timeout" : "unavailable";
        resolve(failure(reason));
      },
      { enableHighAccuracy: options.highAccuracy, timeout: options.timeoutMs, maximumAge: options.maximumAgeMs },
    );
  });
}

/** One position fix: Telegram's LocationManager first, the browser's geolocation as the fallback. */
export async function getLocation(options: LocationOptions = {}, env: LocationEnv = defaultEnv()): Promise<LocationResult> {
  const settings: Required<LocationOptions> = {
    timeoutMs: options.timeoutMs ?? 15_000,
    highAccuracy: options.highAccuracy ?? true,
    maximumAgeMs: options.maximumAgeMs ?? 30_000,
  };
  const telegram = await withTimeout(fromTelegram(env), settings.timeoutMs, failure("timeout"));
  if (telegram) return telegram;
  return withTimeout(fromBrowser(env, settings), settings.timeoutMs + 1_000, failure("timeout"));
}

/**
 * Open Telegram's location settings so the person can allow access. Only works in response to a
 * tap. Returns false when this client can't do it (then explain how in words instead).
 */
export function openLocationSettings(env: LocationEnv = defaultEnv()): boolean {
  const manager = locationManager(env);
  if (!manager) return false;
  manager.openSettings();
  return true;
}

type Point = { latitude: number; longitude: number };

/** Great-circle distance in meters (haversine), good to a few meters at city scale. */
export function distanceMeters(a: Point, b: Point): number {
  const radius = 6_371_008.8;
  const rad = (degrees: number) => (degrees * Math.PI) / 180;
  const dLat = rad(b.latitude - a.latitude);
  const dLon = rad(b.longitude - a.longitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.latitude)) * Math.cos(rad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 2 * radius * Math.asin(Math.min(1, Math.sqrt(h)));
}

const UNITS: Record<Lang, { m: string; km: string; point: string }> = {
  en: { m: "m", km: "km", point: "." },
  ru: { m: "м", km: "км", point: "," },
  uz: { m: "m", km: "km", point: "," },
};

/** "80 m", "1.2 km" / "1,2 км": meters under a kilometre, one decimal up to 10 km, whole above. */
export function formatDistance(meters: number, lang: Lang): string {
  const unit = UNITS[lang];
  const rounded = meters < 10 ? Math.max(0, Math.round(meters)) : Math.round(meters / 10) * 10;
  if (rounded < 1000) return `${rounded} ${unit.m}`;
  const km = meters / 1000;
  const text = km < 10 ? (Math.round(km * 10) / 10).toFixed(1).replace(/\.0$/, "") : String(Math.round(km));
  return `${text.replace(".", unit.point)} ${unit.km}`;
}
