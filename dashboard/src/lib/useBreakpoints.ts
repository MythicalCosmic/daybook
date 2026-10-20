/** Layout breakpoints, shared by every component: phone < 768 px, desktop ≥ 1024 px. */
import { createSharedComposable, useMediaQuery } from "@vueuse/core";

export const useBreakpoints = createSharedComposable(() => ({
  /** Bottom tab bar, bottom sheets, card lists. */
  isPhone: useMediaQuery("(max-width: 767.98px)"),
  /** Sidebar rail only. */
  isTablet: useMediaQuery("(min-width: 768px) and (max-width: 1023.98px)"),
  /** Full sidebar available. */
  isDesktop: useMediaQuery("(min-width: 1024px)"),
}));
