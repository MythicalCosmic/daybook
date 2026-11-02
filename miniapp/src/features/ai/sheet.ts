import { lazyScreen } from "../../lib/lazy";

/**
 * The AI sheet's code, loaded on first use; the ways in (the Home card, the (+) sheet's tools)
 * fetch it while the browser is idle, so the first tap on the mic shows the recorder at once
 * instead of a placeholder.
 */
export const DraftSheetScreen = lazyScreen(() => import("./DraftSheet").then((m) => ({ default: m.DraftSheet })));
