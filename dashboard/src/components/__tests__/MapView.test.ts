import { afterEach, describe, expect, it, vi } from "vitest";

import MapView from "@/components/MapView.vue";
import { mountWithProviders, testApp } from "@/test/plugins";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("MapView", () => {
  it("puts branch and people's names in as text, never as HTML", async () => {
    const app = await testApp("/c/1/attendance");
    const name = '<img src=x onerror="window.__pwned = 1">';
    const { wrapper } = mountWithProviders(MapView, {
      props: {
        branches: [{ id: 1, name, latitude: "41.285680", longitude: "69.203430", geofence_m: 150 }],
        points: [{ id: 5, lat: "41.2857", lng: "69.2035", tone: "ok", label: name }],
      },
      plugins: app.plugins,
    });
    // Leaflet loads on mount, in its own chunk.
    await vi.waitFor(() => expect(document.querySelector(".ui-map-label")).not.toBeNull(), { timeout: 5000 });
    const label = document.querySelector(".ui-map-label")!;
    expect(label.textContent).toBe(name);
    expect(label.querySelector("img")).toBeNull();
    expect(document.querySelector(".ui-map-point.ui-map-ok")).not.toBeNull();
    wrapper.unmount();
  });

  it("picks a place: the pin and its circle, a hint until there is one, and the map's clicks", async () => {
    const app = await testApp("/c/1/settings/branches");
    const empty = mountWithProviders(MapView, { props: { picker: true, latitude: null, longitude: null, radius: 150, placeHint: "Click to place the branch" }, plugins: app.plugins });
    await vi.waitFor(() => expect(empty.wrapper.text()).toContain("Click to place the branch"), { timeout: 5000 });
    expect(empty.wrapper.text()).toContain("My location");
    expect(document.querySelector(".ui-map-pin")).toBeNull();
    empty.wrapper.unmount();

    const placed = mountWithProviders(MapView, { props: { picker: true, latitude: "41.311100", longitude: "69.279700", radius: 150 }, plugins: app.plugins });
    await vi.waitFor(() => expect(document.querySelector(".ui-map-pin")).not.toBeNull(), { timeout: 5000 });
    expect(document.querySelector(".ui-map-fence")).not.toBeNull();
    expect(placed.wrapper.text()).not.toContain("Click the map");
    placed.wrapper.unmount();

    // Read-only: the place shows, nothing to move it with.
    const readOnly = mountWithProviders(MapView, { props: { picker: true, editable: false, latitude: "41.311100", longitude: "69.279700", radius: 150 }, plugins: app.plugins });
    await vi.waitFor(() => expect(document.querySelector(".ui-map-pin")).not.toBeNull(), { timeout: 5000 });
    expect(readOnly.wrapper.text()).not.toContain("My location");
    readOnly.wrapper.unmount();
  });
});
