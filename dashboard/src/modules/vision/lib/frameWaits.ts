/**
 * The longest wait each camera's pictures show right now, shared by the pictures on the live page
 * with the page's numbers. A frame is at most half a second old; the live report can be five
 * seconds older (docs/KOZ.md §5.5, §5.6). So while a camera's picture is on screen, its tile, the
 * counters and the banner read the wait from the frames (lib/tracks.ts `freshReport`), and show
 * the same second as the pill of the person waiting.
 */
import { inject, provide, shallowReactive, type InjectionKey } from "vue";

/** By camera id: when the longest wait began (`Date.now()` time), null when nobody waits. */
export type FrameWaits = Map<number, number | null>;

const KEY: InjectionKey<FrameWaits> = Symbol("koz-frame-waits");

/** On the page that shows the numbers: the pictures below it fill this in. */
export function provideFrameWaits(): FrameWaits {
  const waits = shallowReactive(new Map<number, number | null>());
  provide(KEY, waits);
  return waits;
}

/** In a picture: null outside a page that reads the waits. */
export function useFrameWaits(): FrameWaits | null {
  return inject(KEY, null);
}
