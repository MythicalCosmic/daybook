/**
 * Whether an Overview widget shows its skeleton: whenever its first data is still loading, at once.
 *
 * Pages wait 150 ms before a skeleton (useDelayedPending) so a fast answer never flashes one. On the
 * Overview the widget's cell already showed a placeholder of the same shape while its code loaded
 * (overview/components/WidgetCell.vue); waiting again would shrink the card to its header for a
 * moment and grow it back. Refetches keep their data (`isPending` stays false): no skeleton then.
 */
import { computed, toValue, type ComputedRef, type MaybeRefOrGetter } from "vue";

export function useWidgetSkeleton(pending: MaybeRefOrGetter<boolean>): ComputedRef<boolean> {
  return computed(() => toValue(pending));
}
