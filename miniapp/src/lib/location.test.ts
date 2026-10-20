import { describe, expect, it, vi } from "vitest";

import { distanceMeters, formatDistance, getLocation, openLocationSettings, type LocationEnv } from "./location";

type Manager = NonNullable<LocationEnv["webApp"]>["LocationManager"];

const FIX = {
  latitude: 41.2856,
  longitude: 69.2034,
  altitude: null,
  course: null,
  speed: null,
  horizontal_accuracy: 12,
  vertical_accuracy: null,
  course_accuracy: null,
  speed_accuracy: null,
};

function telegram(manager: Partial<Manager>, version = "8.0"): LocationEnv["webApp"] {
  return {
    isVersionAtLeast: (wanted: string) => Number(wanted) <= Number(version),
    LocationManager: {
      isInited: true,
      isLocationAvailable: true,
      isAccessRequested: false,
      isAccessGranted: false,
      init: vi.fn(),
      getLocation: vi.fn(),
      openSettings: vi.fn(),
      ...manager,
    } as Manager,
  };
}

function browser(result: { coords?: Partial<GeolocationCoordinates>; error?: number }) {
  return {
    getCurrentPosition: vi.fn((success: PositionCallback, failure?: PositionErrorCallback | null) => {
      if (result.error) failure?.({ code: result.error, message: "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 } as GeolocationPositionError);
      else success({ coords: { latitude: 41.3, longitude: 69.24, accuracy: 35, ...result.coords }, timestamp: 1000 } as GeolocationPosition);
    }),
  };
}

const now = () => 5000;

describe("getLocation", () => {
  it("uses Telegram's LocationManager on 8.0+ and reports accuracy", async () => {
    const webApp = telegram({ getLocation: vi.fn((callback) => callback(FIX)) as Manager["getLocation"] });
    const geolocation = browser({});
    const result = await getLocation({}, { webApp, geolocation, now });
    expect(result).toEqual({ ok: true, fix: { latitude: 41.2856, longitude: 69.2034, accuracy: 12, source: "telegram", at: 5000 } });
    expect(geolocation.getCurrentPosition).not.toHaveBeenCalled();
  });

  it("initialises the manager first when needed", async () => {
    const init = vi.fn((done?: () => void) => done?.());
    const webApp = telegram({ isInited: false, init: init as unknown as Manager["init"], getLocation: vi.fn((callback) => callback(FIX)) as Manager["getLocation"] });
    const result = await getLocation({}, { webApp, now });
    expect(init).toHaveBeenCalledOnce();
    expect(result.ok).toBe(true);
  });

  it("says denied (and that settings can help) when the person refused", async () => {
    const refused = telegram({ isAccessRequested: true, isAccessGranted: false });
    expect(await getLocation({}, { webApp: refused, now })).toEqual({ ok: false, reason: "denied", canOpenSettings: true });

    const declinedNow = telegram({ getLocation: vi.fn((callback) => callback(null)) as Manager["getLocation"] });
    expect(await getLocation({}, { webApp: declinedNow, now })).toEqual({ ok: false, reason: "denied", canOpenSettings: true });
  });

  it("falls back to the browser on older Telegram clients", async () => {
    const webApp = telegram({}, "7.10");
    const geolocation = browser({});
    const result = await getLocation({ highAccuracy: false, timeoutMs: 5000 }, { webApp, geolocation, now });
    expect(result).toEqual({ ok: true, fix: { latitude: 41.3, longitude: 69.24, accuracy: 35, source: "browser", at: 1000 } });
    expect(geolocation.getCurrentPosition).toHaveBeenCalledWith(expect.any(Function), expect.any(Function), {
      enableHighAccuracy: false,
      timeout: 5000,
      maximumAge: 30_000,
    });
  });

  it("falls back to the browser when the device has no location services for Telegram", async () => {
    const webApp = telegram({ isLocationAvailable: false });
    const result = await getLocation({}, { webApp, geolocation: browser({}), now });
    expect(result.ok && result.fix.source).toBe("browser");
  });

  it("works outside Telegram, and explains each browser failure", async () => {
    expect((await getLocation({}, { geolocation: browser({}), now })).ok).toBe(true);
    expect(await getLocation({}, { geolocation: browser({ error: 1 }), now })).toEqual({ ok: false, reason: "denied", canOpenSettings: false });
    expect(await getLocation({}, { geolocation: browser({ error: 2 }), now })).toEqual({ ok: false, reason: "unavailable", canOpenSettings: false });
    expect(await getLocation({}, { geolocation: browser({ error: 3 }), now })).toEqual({ ok: false, reason: "timeout", canOpenSettings: false });
    expect(await getLocation({}, { now })).toEqual({ ok: false, reason: "unsupported", canOpenSettings: false });
  });

  it("gives up after the timeout when nothing answers", async () => {
    vi.useFakeTimers();
    try {
      const silent = telegram({ getLocation: vi.fn() as Manager["getLocation"] });
      const pending = getLocation({ timeoutMs: 2000 }, { webApp: silent, now });
      await vi.advanceTimersByTimeAsync(2001);
      expect(await pending).toEqual({ ok: false, reason: "timeout", canOpenSettings: false });
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens Telegram's settings only where it can", () => {
    const openSettings = vi.fn();
    expect(openLocationSettings({ webApp: telegram({ openSettings: openSettings as unknown as Manager["openSettings"] }) })).toBe(true);
    expect(openSettings).toHaveBeenCalledOnce();
    expect(openLocationSettings({ webApp: telegram({}, "7.0") })).toBe(false);
    expect(openLocationSettings({})).toBe(false);
  });
});

describe("distances", () => {
  it("measures city distances to within a few meters", () => {
    // One degree of latitude on the mean Earth radius is 111 195 m.
    expect(Math.round(distanceMeters({ latitude: 0, longitude: 0 }, { latitude: 1, longitude: 0 }))).toBe(111195);
    const chilonzor = { latitude: 41.2756, longitude: 69.2034 };
    const amirTemur = { latitude: 41.3111, longitude: 69.2797 };
    // 3.95 km north and 6.38 km east.
    expect(Math.round(distanceMeters(chilonzor, amirTemur) / 10) * 10).toBe(7500);
    expect(distanceMeters(chilonzor, amirTemur)).toBeCloseTo(distanceMeters(amirTemur, chilonzor), 6);
    expect(distanceMeters(chilonzor, chilonzor)).toBe(0);
  });

  it("reads naturally in each language", () => {
    expect(formatDistance(4.4, "en")).toBe("4 m");
    expect(formatDistance(84, "uz")).toBe("80 m");
    expect(formatDistance(996, "en")).toBe("1 km");
    expect(formatDistance(1234, "ru")).toBe("1,2 км");
    expect(formatDistance(1234, "en")).toBe("1.2 km");
    expect(formatDistance(15400, "uz")).toBe("15 km");
  });
});
