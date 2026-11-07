/**
 * Camera barcode scanning (PLAN-OWNER §14.17). Telegram's own scanner reads QR codes only, so a
 * pack's EAN-13 is read with the browser's `BarcodeDetector`, and only where its
 * `getSupportedFormats()` lists EAN-13, a camera can be opened, and the company allows camera
 * scanning (`StockSettings.camera_scanning`). No decoder library is shipped: typed search
 * always works, and is the way in on phones without the detector.
 *
 * The scan sheet hands the code back to the screen that opened it through `emitScan(target)`.
 */
import { useEffect, useRef, useState } from "react";

import { isEan13 } from "./lib";

export type DetectedBarcode = { rawValue: string; format: string };

export interface BarcodeDetectorLike {
  detect(source: ImageBitmapSource): Promise<DetectedBarcode[]>;
}

export interface BarcodeDetectorClass {
  new (options?: { formats?: string[] }): BarcodeDetectorLike;
  getSupportedFormats(): Promise<string[]>;
}

/** A pack's barcodes, the main one first; scanning is offered only when EAN-13 is among them. */
const PACK_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"] as const;

type Scope = { BarcodeDetector?: unknown; navigator?: Navigator };

function detectorClass(scope: Scope): BarcodeDetectorClass | null {
  const found = scope.BarcodeDetector as BarcodeDetectorClass | undefined;
  return typeof found === "function" && typeof found.getSupportedFormats === "function" ? found : null;
}

function hasCamera(scope: Scope): boolean {
  return typeof scope.navigator?.mediaDevices?.getUserMedia === "function";
}

/** The formats to ask the detector for, or null when this webview can't scan a pack. */
export async function supportedFormats(scope: Scope = globalThis as Scope): Promise<string[] | null> {
  const Detector = detectorClass(scope);
  if (!Detector || !hasCamera(scope)) return null;
  try {
    const formats = await Detector.getSupportedFormats();
    if (!Array.isArray(formats) || !formats.includes("ean_13")) return null;
    return PACK_FORMATS.filter((format) => formats.includes(format));
  } catch {
    return null;
  }
}

let support: Promise<string[] | null> | null = null;

/** Asked once per app start: the answer doesn't change while the app runs. */
export function scanFormats(): Promise<string[] | null> {
  support ??= supportedFormats();
  return support;
}

/** Forget the cached answer (tests, or a webview that gained the detector). */
export function resetScanSupport(): void {
  support = null;
}

export function createDetector(formats: string[], scope: Scope = globalThis as Scope): BarcodeDetectorLike | null {
  const Detector = detectorClass(scope);
  if (!Detector) return null;
  try {
    return new Detector({ formats });
  } catch {
    return null;
  }
}

/** Whether to offer the scan button: the company allows it and this phone can. */
export function useCanScan(allowed: boolean): boolean {
  const [formats, setFormats] = useState<string[] | null>(null);
  useEffect(() => {
    if (!allowed) return;
    let live = true;
    void scanFormats().then((found) => {
      if (live) setFormats(found);
    });
    return () => {
      live = false;
    };
  }, [allowed]);
  return allowed && Boolean(formats?.length);
}

/**
 * The code worth acting on among a frame's detections: an EAN-13 whose check digit is right
 * (a half-read one is skipped), else any other pack code the detector was sure enough to give.
 */
export function pickCode(found: readonly DetectedBarcode[]): string | null {
  const codes = found.map((item) => ({ format: item.format, code: (item.rawValue ?? "").trim() })).filter((item) => /^\d{8,14}$/.test(item.code));
  const ean = codes.find((item) => item.format === "ean_13" && isEan13(item.code));
  if (ean) return ean.code;
  return codes.find((item) => item.format !== "ean_13")?.code ?? null;
}

// — handing the code back —

type Listener = (code: string) => void;
const listeners = new Map<string, Set<Listener>>();

export function emitScan(target: string, code: string): void {
  listeners.get(target)?.forEach((listener) => listener(code));
}

/** Hear the codes scanned for `target` while the screen is open. */
export function useScanResult(target: string, onCode: Listener): void {
  const latest = useRef(onCode);
  latest.current = onCode;
  useEffect(() => {
    const listener: Listener = (code) => latest.current(code);
    const set = listeners.get(target) ?? new Set<Listener>();
    set.add(listener);
    listeners.set(target, set);
    return () => {
      set.delete(listener);
      if (!set.size) listeners.delete(target);
    };
  }, [target]);
}
