import { afterEach, describe, expect, it, vi } from "vitest";

import { celebrate } from "./celebrate";

vi.mock("../telegram", () => ({ haptic: vi.fn() }));

describe("celebrate", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("buzzes even when nothing can be drawn", async () => {
    const { haptic } = await import("../telegram");
    const stop = celebrate();
    expect(haptic).toHaveBeenCalledWith("success");
    stop();
  });

  it("draws nothing when the person asked for reduced motion", () => {
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce") }) as MediaQueryList);
    celebrate({ haptic: null });
    expect(document.querySelector(".celebrate-canvas")).toBeNull();
    expect(getContext).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("puts one canvas over the screen and takes it away when stopped", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      scale: vi.fn(),
      clearRect: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      translate: vi.fn(),
      rotate: vi.fn(),
      fillRect: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    const stop = celebrate({ haptic: null, pieces: 5 });
    expect(document.querySelectorAll(".celebrate-canvas")).toHaveLength(1);
    stop();
    expect(document.querySelector(".celebrate-canvas")).toBeNull();
  });
});
