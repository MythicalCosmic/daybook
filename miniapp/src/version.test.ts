import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("release", () => {
  it("is the version in package.json, which Me shows", () => {
    // Vitest runs in miniapp/; under jsdom import.meta.url isn't a file URL.
    const { version } = JSON.parse(readFileSync(resolve(process.cwd(), "package.json"), "utf8")) as { version: string };
    expect(__APP_VERSION__).toBe(version);
    expect(version).toMatch(/^\d+\.\d+\.\d+$/);
  });
});
