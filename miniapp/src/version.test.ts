import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("release", () => {
  it("is the version in package.json, which Me shows", () => {
    const { version } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as { version: string };
    expect(__APP_VERSION__).toBe(version);
    expect(version).toMatch(/^\d+\.\d+\.\d+$/);
  });
});
