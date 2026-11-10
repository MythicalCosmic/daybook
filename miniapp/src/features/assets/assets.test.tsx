// "Jihozlarim": the list, confirming, the empty page, and the module switch.
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { membership, person, renderApp, routeApi } from "../../test/harness";
import { features, findFeature } from "../registry";
import { toConfirm, type MineItem } from "./api";
import { messages } from "./messages";
import MinePage from "./MinePage";

const client = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api };
});

afterEach(() => {
  cleanup();
  client.api.mockReset();
});

const item = (overrides: Partial<MineItem> = {}): MineItem => ({
  id: 1,
  asset_id: 7,
  number: "AV-0007",
  name: "Noutbuk",
  model: "Lenovo",
  serial: "LN-1",
  category: "Kompyuterlar",
  icon: "monitor",
  branch: "Chilonzor",
  issued_on: "2026-11-01",
  condition: "good",
  note: "",
  acknowledged_at: null,
  photo_url: null,
  ...overrides,
});

const feature = findFeature(features, "assets")!;

describe("my equipment", () => {
  it("asks to confirm only what isn't confirmed yet", () => {
    expect(toConfirm([item(), item({ id: 2, acknowledged_at: "2026-11-02T10:00:00+05:00" })]).map((row) => row.id)).toEqual([1]);
    expect(toConfirm(undefined)).toEqual([]);
  });

  it("shows only with the assets module on", () => {
    const member = (features: string[]) => ({ status: "approved", company: { features } }) as never;
    expect(feature.visible?.(member(["assets"]), {} as never)).toBe(true);
    expect(feature.visible?.(member(["finance"]), {} as never)).toBe(false);
  });

  it("shows the photo taken when it was given, whole in a sheet, and the confirm button", async () => {
    let confirmed = 0;
    routeApi(client.api, {
      "/assets/mine/": [item({ photo_url: "/files/handout.jpg?sig=1", name: "Xalat №3", model: "", serial: "", category: "Xalatlar" })],
      "POST /assets/mine/1/acknowledge/": () => {
        confirmed += 1;
        return item({ photo_url: "/files/handout.jpg?sig=1", name: "Xalat №3", model: "", serial: "", acknowledged_at: "2026-11-02T10:00:00+05:00" });
      },
    });
    renderApp(<MinePage />, { me: person([membership({ company: { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["assets"] } } as never)]) });

    const photo = await screen.findByTestId("mine-photo");
    expect(photo.querySelector("img")?.getAttribute("src")).toBe("/files/handout.jpg?sig=1");
    fireEvent.click(photo);
    expect(await screen.findByAltText("Xalat №3 when it was given")).toBeTruthy();
    expect(screen.getByText(messages.en["row.photoNote"])).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: messages.en["row.confirm"] }));
    await waitFor(() => expect(confirmed).toBe(1));
    expect(await screen.findByText(/^Confirmed /)).toBeTruthy();
  });

  it("has every text in the three languages and opens from the bot's link", () => {
    const keys = Object.keys(messages.en).sort();
    expect(Object.keys(messages.ru).sort()).toEqual(keys);
    expect(Object.keys(messages.uz).sort()).toEqual(keys);
    expect(Object.values(messages.uz).join(" ")).not.toMatch(/['`]/);
    expect(feature.routes?.["assets.mine"]).toEqual({ page: "home", tab: "profile" });
  });
});
