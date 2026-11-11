/**
 * Whether an Overview widget shows its skeleton: whenever its first data is still loading, at once.
 *
 * Elsewhere a skeleton fades in only after 150 ms (useDelayedPending, SkeletonBlock's CSS) so a fast
 * answer never flashes one. On the Overview the widget's cell already showed a placeholder of the
 * same shape while its code loaded (overview/components/WidgetCell.vue), so its skeletons show at
 * once (`.skeleton-now` on the page): waiting again would blank the card for a moment. Refetches keep their data (`isPending` stays false): no skeleton then.
 */
import { computed, toValue, type ComputedRef, type MaybeRefOrGetter } from "vue";

export function useWidgetSkeleton(pending: MaybeRefOrGetter<boolean>): ComputedRef<boolean> {
  return computed(() => toValue(pending));
}
