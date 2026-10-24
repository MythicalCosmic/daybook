import { useEffect } from "react";

import { confirmClosing, disableVerticalSwipes } from "../telegram";

/**
 * While `dirty` (a typed comment, a picked photo, a half-written task): a swipe down no longer
 * minimises the app, and closing it asks first. Nothing typed is lost to a stray gesture (audit M-6).
 */
export function useDraftGuard(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return;
    const allowSwipes = disableVerticalSwipes();
    const stopAsking = confirmClosing();
    return () => {
      allowSwipes();
      stopAsking();
    };
  }, [dirty]);
}
