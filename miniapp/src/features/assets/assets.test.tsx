// "Jihozlarim": the list, confirming, the empty page, and the module switch.
import { describe, expect, it } from "vitest";

import { features, findFeature } from "../registry";
import { toConfirm, type MineItem } from "./api";
import { messages } from "./messages";

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

  it("has every text in the three languages and opens from the bot's link", () => {
    const keys = Object.keys(messages.en).sort();
    expect(Object.keys(messages.ru).sort()).toEqual(keys);
    expect(Object.keys(messages.uz).sort()).toEqual(keys);
    expect(Object.values(messages.uz).join(" ")).not.toMatch(/['`]/);
    expect(feature.routes?.["assets.mine"]).toEqual({ page: "home", tab: "profile" });
  });
});
