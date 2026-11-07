/**
 * The camera scanner: the back camera in a frame, read by the browser's BarcodeDetector a few
 * times a second. The first good code goes back to the screen that opened it (`params.target`)
 * and the sheet closes; a refused or missing camera says so and leaves typing. The camera stops
 * whenever the sheet closes.
 */
import { CameraOff, Keyboard } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { haptic } from "../../telegram";
import { EmptyState, SheetTitle } from "../../ui";
import type { SheetProps } from "../registry";
import { createDetector, emitScan, pickCode, scanFormats } from "./scan";
import { useStockT } from "./text";
import "./stock.css";

type State = "starting" | "live" | "denied" | "failed";

/** How often a frame is read: quick enough to feel instant, light on an old phone. */
const EVERY_MS = 220;

export default function ScanSheet({ params, close }: SheetProps) {
  const t = useStockT();
  const target = String(params.target ?? "lookup");
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<State>("starting");
  const done = useRef(close);
  done.current = close;

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: number | undefined;
    let stopped = false;
    const stop = () => {
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
    };
    void (async () => {
      const formats = await scanFormats();
      const detector = formats ? createDetector(formats) : null;
      if (stopped) return;
      if (!detector || !navigator.mediaDevices?.getUserMedia) {
        setState("failed");
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      } catch (error) {
        if (!stopped) setState((error as { name?: string } | null)?.name === "NotAllowedError" ? "denied" : "failed");
        return;
      }
      const element = video.current;
      if (stopped || !element) {
        stop();
        return;
      }
      element.srcObject = stream;
      await element.play().catch(() => undefined);
      if (stopped) return;
      setState("live");
      const read = async () => {
        if (stopped) return;
        try {
          const code = pickCode(await detector.detect(element));
          if (code && !stopped) {
            stop();
            haptic.notify("success");
            emitScan(target, code);
            done.current();
            return;
          }
        } catch {
          // A frame the detector couldn't read (the video not ready yet): try the next one.
        }
        timer = window.setTimeout(() => void read(), EVERY_MS);
      };
      void read();
    })();
    return stop;
  }, [target]);

  if (state === "denied" || state === "failed") {
    return (
      <>
        <SheetTitle>{t("scan.title")}</SheetTitle>
        <EmptyState
          compact
          icon={CameraOff}
          title={t(state === "denied" ? "scan.denied" : "scan.failed")}
          action={{ label: t("scan.typeInstead"), icon: Keyboard, onClick: () => done.current() }}
        />
      </>
    );
  }
  return (
    <>
      <SheetTitle>{t("scan.title")}</SheetTitle>
      <div className="stk-scan" data-state={state}>
        <video ref={video} className="stk-scan-video" playsInline muted autoPlay aria-label={t("scan.title")} />
        <span className="stk-scan-frame" aria-hidden />
      </div>
      <p className="ft-hint stk-note">{t("scan.hint")}</p>
    </>
  );
}
