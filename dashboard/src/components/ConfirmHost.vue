<script setup lang="ts">
/** Shows `useConfirm()` requests one at a time. Mounted once by App.vue. */
import { computed, ref, watch } from "vue";

import ConfirmDialog from "./ConfirmDialog.vue";
import { confirmQueue, settleConfirm } from "./useConfirm";

const current = computed(() => confirmQueue.value[0] ?? null);
/** The request as the dialog's props: its `onConfirm` becomes the dialog's `action`, so it can't
 * merge with the `@confirm` listener below. */
const dialogProps = computed(() => {
  const request = current.value?.request;
  if (!request) return null;
  const { onConfirm, ...rest } = request;
  return { ...rest, action: onConfirm };
});
const open = ref(false);
const answered = new Set<number>();

watch(
  () => current.value?.id,
  (id) => (open.value = id !== undefined),
  { immediate: true },
);

function settle(answer: { reason: string } | null): void {
  const entry = current.value;
  if (!entry || answered.has(entry.id)) return;
  answered.add(entry.id);
  settleConfirm(entry.id, answer);
}
</script>

<template>
  <ConfirmDialog
    v-if="current && dialogProps"
    :key="current.id"
    v-model:open="open"
    v-bind="dialogProps"
    @confirm="(reason: string) => settle({ reason })"
    @cancel="settle(null)"
  />
</template>
