<script setup lang="ts">
/**
 * The pair every approval uses (time off, claims, join requests, advances, shifts): Approve, and
 * Reject that asks for a reason first (`reason="required"` by default; the person will see it).
 * Pass async `onApprove` / `onReject(reason)` and the buttons spin while they run; `result` shows
 * the outcome instead of the buttons. `compact` shows icons only (tables, cards).
 *
 *   <ApproveRejectButtons :on-approve="() => approve(id)" :on-reject="(reason) => reject(id, reason)" />
 */
import { Check, X } from "@lucide/vue";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import IconButton from "./IconButton.vue";
import StatusPill from "./StatusPill.vue";
import UiButton from "./UiButton.vue";
import { useConfirm } from "./useConfirm";

const props = withDefaults(
  defineProps<{
    onApprove?: () => unknown;
    onReject?: (reason: string) => unknown;
    approveLabel?: string;
    rejectLabel?: string;
    reason?: "required" | "optional" | "none";
    /** Shown in the reason dialog ("Reject Madina's time off?"). */
    rejectTitle?: string;
    size?: "sm" | "md";
    compact?: boolean;
    disabled?: boolean;
    result?: "approved" | "rejected" | null;
  }>(),
  {
    onApprove: undefined,
    onReject: undefined,
    approveLabel: undefined,
    rejectLabel: undefined,
    reason: "required",
    rejectTitle: undefined,
    size: "sm",
    compact: false,
    disabled: false,
    result: null,
  },
);

const emit = defineEmits<{ approve: []; reject: [reason: string] }>();

const { t } = useI18n();
const confirm = useConfirm();
const busy = ref<"approve" | "reject" | null>(null);

async function approve(): Promise<void> {
  if (busy.value) return;
  busy.value = "approve";
  try {
    await props.onApprove?.();
    emit("approve");
  } catch {
    // The HTTP layer already showed what went wrong.
  } finally {
    busy.value = null;
  }
}

async function reject(): Promise<void> {
  if (busy.value) return;
  let reason = "";
  if (props.reason !== "none") {
    const answer = await confirm({
      title: props.rejectTitle ?? t("common.approve.reasonTitle"),
      message: t("common.approve.reasonHint"),
      tone: "danger",
      reason: props.reason,
      confirmLabel: props.rejectLabel ?? t("common.reject"),
    });
    if (!answer) return;
    reason = answer.reason;
  }
  busy.value = "reject";
  try {
    await props.onReject?.(reason);
    emit("reject", reason);
  } catch {
    // Already toasted.
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <StatusPill v-if="result" :tone="result === 'approved' ? 'success' : 'danger'" :label="result === 'approved' ? t('common.approve.approved') : t('common.approve.rejected')" />
  <span v-else-if="compact" class="inline-flex items-center gap-1">
    <IconButton :icon="X" :label="rejectLabel ?? t('common.reject')" variant="secondary" :size="size" :loading="busy === 'reject'" :disabled="disabled || busy === 'approve'" class="hover:!text-danger" @click.stop="reject" />
    <IconButton :icon="Check" :label="approveLabel ?? t('common.approve')" variant="primary" :size="size" :loading="busy === 'approve'" :disabled="disabled || busy === 'reject'" @click.stop="approve" />
  </span>
  <span v-else class="inline-flex flex-wrap items-center gap-1.5">
    <UiButton :size="size" variant="secondary" :icon="X" class="hover:!text-danger" :loading="busy === 'reject'" :disabled="disabled || busy === 'approve'" @click.stop="reject">
      {{ rejectLabel ?? t("common.reject") }}
    </UiButton>
    <UiButton :size="size" variant="primary" :icon="Check" :loading="busy === 'approve'" :disabled="disabled || busy === 'reject'" @click.stop="approve">
      {{ approveLabel ?? t("common.approve") }}
    </UiButton>
  </span>
</template>
