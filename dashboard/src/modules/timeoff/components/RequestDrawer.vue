<script setup lang="ts">
/**
 * One request or stretch of time off (`?request=12`): who, when, how many days, why, who decided
 * or recorded it, a revoke if there was one, the sick note, and the actions: approve or reject a
 * waiting request, revoke approved time off. Its history at the bottom.
 */
import { CalendarX2, Check, FileText, X } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import AuditTrail from "@/components/AuditTrail.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import PersonCell from "@/components/PersonCell.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useDecide, useTimeOff } from "../api";
import RevokeDialog from "./RevokeDialog.vue";

const { t } = useI18n();
const fmt = useFormat();

const requestId = useRouteState("request", rs.optionalNumber());
const query = useTimeOff(requestId);
const row = computed(() => query.data.value ?? null);
const decide = useDecide();
const revoking = ref(false);

const TONES: Record<string, StatusTone> = { pending: "warning", approved: "success", rejected: "danger", cancelled: "neutral" };

const items = computed<DescriptionItem[]>(() => {
  const r = row.value;
  if (!r) return [];
  const list: DescriptionItem[] = [
    { key: "dates", label: t("timeoff.drawer.dates"), value: r.first_day === r.last_day ? fmt.day(r.first_day, "long") : fmt.range({ from: r.first_day, to: r.last_day }) },
    { key: "days", label: t("timeoff.drawer.days"), value: t("timeoff.days", { n: r.days }, r.days) },
    { key: "reason", label: t("timeoff.drawer.reason"), value: r.reason || null },
    { key: "asked", label: r.recorded_by ? t("timeoff.drawer.recordedAt") : t("timeoff.drawer.askedAt"), value: fmt.instant(r.created_at, "datetime") },
  ];
  if (r.recorded_by) list.push({ key: "recorded", label: t("timeoff.drawer.recordedBy"), value: r.recorded_by.name });
  else if (r.decided_by) list.push({ key: "decided", label: r.status === "rejected" ? t("timeoff.drawer.rejectedBy") : t("timeoff.drawer.approvedBy"), value: r.decided_by });
  if (r.revoked_at) {
    list.push({ key: "revoked", label: t("timeoff.drawer.revokedBy"), value: `${r.revoked_by ?? "—"} · ${fmt.instant(r.revoked_at, "short")}` });
    list.push({ key: "revokeReason", label: t("timeoff.drawer.revokeReason"), value: r.revoke_reason || null });
  }
  return list;
});

// The audit trail names the fields and shows its ISO days the way the rest of the drawer does.
const auditLabels = computed(() => ({
  first_day: t("timeoff.audit.firstDay"),
  last_day: t("timeoff.audit.lastDay"),
  cancelled_from: t("timeoff.audit.cancelledFrom"),
  cancelled_to: t("timeoff.audit.cancelledTo"),
  reason: t("timeoff.drawer.reason"),
  member: t("timeoff.audit.member"),
}));
/** The order a person reads them in (Postgres hands the keys back shortest first). */
const AUDIT_ORDER = ["member", "first_day", "last_day", "cancelled_from", "cancelled_to"];
function auditValue(_field: string, value: unknown): string | null {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) ? fmt.day(value, "medium") : null;
}

async function run(approve: boolean): Promise<void> {
  const r = row.value;
  if (!r) return;
  try {
    await decide.mutateAsync({ id: r.id, approve });
    toast.success(approve ? t("timeoff.approvedToast", { name: r.member.name }) : t("timeoff.rejectedToast", { name: r.member.name }));
  } catch {
    // The HTTP layer showed why.
  }
}
</script>

<template>
  <UiDrawer query-key="request" :title="t('timeoff.drawer.title')" size="md">
    <div v-if="query.isPending.value" class="flex flex-col gap-4 p-5"><SkeletonBlock height="40px" /><SkeletonBlock :lines="5" /></div>
    <ErrorState v-else-if="query.isError.value" compact class="m-5" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="row" class="flex flex-col gap-5 p-5">
      <div class="flex items-start justify-between gap-3">
        <PersonCell :person="row.member" :subtitle="[row.position, row.home_branch?.name].filter(Boolean).join(' · ')" size="lg" link />
        <StatusPill :tone="TONES[row.status]" :label="t(`timeoff.state.${row.status}`)" />
      </div>
      <DescriptionList :items="items" layout="rows" />
      <a
        v-if="row.attachment"
        :href="row.attachment"
        target="_blank"
        rel="noopener"
        class="inline-flex w-fit items-center gap-2 rounded-[10px] border border-line px-3 py-2 text-sm font-medium text-fg hover:bg-highlight"
      >
        <FileText :size="16" class="text-info" aria-hidden="true" />{{ t("timeoff.drawer.attachment") }}
      </a>
      <section class="border-t border-line pt-4">
        <h3 class="mb-3 text-sm font-semibold text-fg">{{ t("timeoff.drawer.history") }}</h3>
        <AuditTrail target-type="timeoff" :target-id="row.id" :page-size="10" :field-labels="auditLabels" :field-order="AUDIT_ORDER" :format-value="auditValue" />
      </section>
    </div>
    <template v-if="row && (row.can_decide || row.can_revoke)" #footer>
      <template v-if="row.can_decide">
        <UiButton :icon="X" class="hover:!text-danger" :loading="decide.isPending.value && decide.variables.value?.approve === false" @click="run(false)">{{ t("common.reject") }}</UiButton>
        <UiButton variant="primary" :icon="Check" :loading="decide.isPending.value && decide.variables.value?.approve === true" @click="run(true)">{{ t("common.approve") }}</UiButton>
      </template>
      <UiButton v-else-if="row.can_revoke" :icon="CalendarX2" class="hover:!text-danger" @click="revoking = true">{{ t("timeoff.revoke.action") }}</UiButton>
    </template>
  </UiDrawer>
  <RevokeDialog v-if="row && revoking" v-model:open="revoking" :row="row" />
</template>
