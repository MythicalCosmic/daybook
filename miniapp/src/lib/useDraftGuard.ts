import { createContext, useContext, useEffect } from "react";

import { confirm, confirmClosing, disableVerticalSwipes } from "../telegram";

/** True inside a sheet: a draft there also guards closing the sheet (see `closeUnlessDraft`). */
export const InSheet = createContext(false);

/** Drafts held by the sheet on screen (one sheet shows at a time), each with its own question if any. */
const sheetDrafts: { question?: string }[] = [];

/**
 * While `dirty` (a typed comment, a picked photo, a half-written task): a swipe down no longer
 * minimises the app, and closing it asks first. Nothing typed is lost to a stray gesture (audit M-6).
 * Inside a sheet, closing the sheet (a tap beside it, Back, Escape) asks first too: `question`
 * when the draft has words of its own for it (a recording), else the sheet's.
 */
export function useDraftGuard(dirty: boolean, question?: string): void {
  const inSheet = useContext(InSheet);
  useEffect(() => {
    if (!dirty) return;
    const allowSwipes = disableVerticalSwipes();
    const stopAsking = confirmClosing();
    const draft = { question };
    if (inSheet) sheetDrafts.push(draft);
    return () => {
      allowSwipes();
      stopAsking();
      const index = sheetDrafts.indexOf(draft);
      if (index >= 0) sheetDrafts.splice(index, 1);
    };
  }, [dirty, inSheet, question]);
}

/** Whether the sheet on screen holds something typed or picked that closing it would lose. */
export function sheetHasDraft(): boolean {
  return sheetDrafts.length > 0;
}

/**
 * Close the sheet on screen, as the person asked (a tap beside it, Back, Escape): at once, or when
 * it holds a draft, only once they confirm `question` (or the draft's own). Sending a sheet closes
 * it without asking.
 */
export async function closeUnlessDraft(close: () => void, question: string): Promise<void> {
  if (sheetHasDraft() && !(await confirm(sheetDrafts.at(-1)?.question ?? question))) return;
  close();
}
