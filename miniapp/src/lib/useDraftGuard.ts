import { createContext, useContext, useEffect } from "react";

import { confirm, confirmClosing, disableVerticalSwipes } from "../telegram";

/** True inside a sheet: a draft there also guards closing the sheet (see `closeUnlessDraft`). */
export const InSheet = createContext(false);

/** Drafts held by the sheet on screen (one sheet shows at a time). */
let sheetDrafts = 0;

/**
 * While `dirty` (a typed comment, a picked photo, a half-written task): a swipe down no longer
 * minimises the app, and closing it asks first. Nothing typed is lost to a stray gesture (audit M-6).
 * Inside a sheet, closing the sheet (a tap beside it, Back, Escape) asks first too.
 */
export function useDraftGuard(dirty: boolean): void {
  const inSheet = useContext(InSheet);
  useEffect(() => {
    if (!dirty) return;
    const allowSwipes = disableVerticalSwipes();
    const stopAsking = confirmClosing();
    if (inSheet) sheetDrafts += 1;
    return () => {
      allowSwipes();
      stopAsking();
      if (inSheet) sheetDrafts -= 1;
    };
  }, [dirty, inSheet]);
}

/** Whether the sheet on screen holds something typed or picked that closing it would lose. */
export function sheetHasDraft(): boolean {
  return sheetDrafts > 0;
}

/**
 * Close the sheet on screen, as the person asked (a tap beside it, Back, Escape): at once, or when
 * it holds a draft, only once they confirm `question`. Sending a sheet closes it without asking.
 */
export async function closeUnlessDraft(close: () => void, question: string): Promise<void> {
  if (sheetHasDraft() && !(await confirm(question))) return;
  close();
}
