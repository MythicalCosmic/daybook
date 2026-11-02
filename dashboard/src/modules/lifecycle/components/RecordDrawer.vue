<script setup lang="ts">
/**
 * One disciplinary record in a side panel synced with `?record=`: what happened and when, who issued
 * it, the evidence, the fine proposed to payroll, whether the employee has read it, and their
 * explanation in their own words. hr.discipline may withdraw it (with the reason).
 */
import { Banknote, CircleCheck, EllipsisVertical, Eye, FileText, Hourglass, MessageSquareQuote, Undo2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { lifecycleApi, useLifecycleMutation, useRecord } from "../api";
import { KIND_TONES, lifecycleAccess, STATUS_TONES } from "../lib";

const { t, te } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const confirm = useConfirm();
const access = computed(() => lifecycleAccess((perm) => company.can(perm)));

const id = computed(() => {
  const raw = route.query.record;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useRecord(id);
const record = computed(() => query.data.value ?? null);
const category = (value: string) => (te(`lifecycle.category.${value}`) ? t(`lifecycle.category.${value}`) : value);
const fineStatus = (value: string) => (te(`lifecycle.fineStatus.${value}`) ? t(`lifecycle.fineStatus.${value}`) : value);
const isImage = computed(() => /\.(jpe?g|png|webp|gif|heic)$/i.test((record.value?.evidence_name || record.value?.evidence || "").split(/[?#]/)[0]!));

const items = computed<DescriptionItem[]>(() => {
  const r = record.value;
  if (!r) return [];
  return [
    { key: "category", label: t("lifecycle.field.category"), value: category(r.category) },
    { key: "incident", label: t("lifecycle.field.incidentOn"), value: fmt.day(r.incident_on, "long") },
    { key: "issued", label: t("lifecycle.field.issued"), value: r.issued_by ? `${r.issued_by} · ${fmt.day(r.issued_at.slice(0, 10), "medium")}` : fmt.day(r.issued_at.slice(0, 10), "medium") },
    { key: "expires", label: t("lifecycle.field.expiresOn"), value: r.expires_on ? fmt.day(r.expires_on, "long") : t("lifecycle.record.noExpiry"), hint: t("lifecycle.record.expiresHint") },
  ];
});

const withdraw = useLifecycleMutation((cid, input: { id: number; reason: string }) => lifecycleApi.withdrawRecord(cid, input.id, input.reason));
const canWithdraw = computed(() => !!record.value && access.value.discipline && ["issued", "acknowledged", "disputed"].includes(record.value.status));
async function runWithdraw(): Promise<void> {
  const r = record.value;
  if (!r) return;
  const answer = await confirm({
    title: t("lifecycle.record.withdrawTitle"),
    message: t("lifecycle.record.withdrawBody", { name: r.member.name }),
    tone: "danger",
    reason: "required",
    reasonLabel: t("lifecycle.record.withdrawReason"),
    confirmLabel: t("lifecycle.record.withdraw"),
    icon: Undo2,
    onConfirm: (reason) => withdraw.mutateAsync({ id: r.id, reason }),
  });
  if (answer) toast.success(t("lifecycle.record.withdrawn"));
}
const menu = computed<MenuEntry[]>(() => (canWithdraw.value ? [{ label: t("lifecycle.record.withdraw"), icon: Undo2, danger: true, onSelect: () => void runWithdraw() }] : []));
</script>

<template>
  <UiDrawer query-key="record" size="md" :title="record ? t(`lifecycle.kind.${record.kind}`) : t('lifecycle.record.one')">
    <template #header-actions>
      <DropdownMenu v-if="menu.length" :items="menu" align="end">
        <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" /></template>
      </DropdownMenu>
    </template>
    <div class="p-5">
      <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
        <SkeletonBlock height="56px" />
        <SkeletonBlock v-for="n in 5" :key="n" height="16px" />
      </div>
      <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
      <div v-else-if="record" class="flex flex-col gap-5">
        <header class="flex items-start gap-3">
          <RouterLink :to="`/c/${company.currentId}/people/${record.member.id}`" class="shrink-0" :aria-label="record.member.name">
            <UserAvatar :name="record.member.name" :src="record.member.photo_url" :size="44" />
          </RouterLink>
          <div class="min-w-0 flex-1">
            <RouterLink :to="`/c/${company.currentId}/people/${record.member.id}`" class="block truncate text-base font-semibold text-fg hover:text-primary hover:underline">{{ record.member.name }}</RouterLink>
            <p v-if="record.position" class="truncate text-sm text-muted">{{ record.position }}</p>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusPill :tone="KIND_TONES[record.kind]" size="sm" :label="t(`lifecycle.kind.${record.kind}`)" />
              <StatusPill :tone="STATUS_TONES[record.status]" size="sm" variant="outline" :label="t(`lifecycle.status.${record.status}`)" />
            </div>
          </div>
        </header>

        <section class="flex flex-col gap-1.5">
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.field.description") }}</h3>
          <p class="whitespace-pre-line rounded-[10px] bg-surface-2 px-3.5 py-3 text-base text-fg">{{ record.description }}</p>
        </section>

        <DescriptionList :items="items" :columns="2" />

        <!-- The fine proposed to payroll -->
        <section v-if="record.fine" class="flex items-center gap-3 rounded-[12px] border border-line px-3.5 py-3" data-record-fine>
          <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-warning-soft text-warning" aria-hidden="true"><Banknote :size="18" /></span>
          <div class="min-w-0 flex-1">
            <p class="text-sm font-semibold text-fg">{{ t("lifecycle.record.fine") }}: <MoneyText :value="record.fine.amount" :currency="record.fine.currency" /></p>
            <p class="text-xs text-muted">{{ t("lifecycle.record.fineStatus", { status: fineStatus(record.fine.status) }) }}</p>
          </div>
        </section>

        <!-- Read and explained by the employee -->
        <section class="flex flex-col gap-2" data-record-response>
          <div :class="['flex items-center gap-2 text-sm', record.acknowledged_at ? 'text-success' : 'text-muted']">
            <CircleCheck v-if="record.acknowledged_at" :size="16" aria-hidden="true" />
            <Hourglass v-else :size="16" aria-hidden="true" />
            {{ record.acknowledged_at ? t("lifecycle.record.acknowledgedOn", { date: fmt.instant(record.acknowledged_at, "datetime") }) : t("lifecycle.record.notAcknowledged") }}
          </div>
          <figure v-if="record.employee_response" class="rounded-[12px] border-l-4 border-[var(--c-info)] bg-info-soft/50 px-4 py-3">
            <figcaption class="mb-1 flex items-center gap-1.5 text-xs font-semibold text-info">
              <MessageSquareQuote :size="14" aria-hidden="true" />{{ t("lifecycle.record.explanation") }}<template v-if="record.responded_at"> · {{ fmt.instant(record.responded_at, "short") }}</template>
            </figcaption>
            <blockquote class="whitespace-pre-line text-base text-fg">{{ record.employee_response }}</blockquote>
          </figure>
          <p v-else class="rounded-[10px] border border-dashed border-line-strong px-3.5 py-3 text-sm text-muted">{{ t("lifecycle.record.noExplanation") }}</p>
        </section>

        <!-- Evidence -->
        <section v-if="record.evidence" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.field.evidence") }}</h3>
          <a v-if="isImage" :href="record.evidence" target="_blank" rel="noopener" class="block overflow-hidden rounded-card border border-line bg-surface-2">
            <img :src="record.evidence" :alt="t('lifecycle.field.evidence')" class="max-h-[50vh] w-full object-contain" />
          </a>
          <UiButton v-else :href="record.evidence" target="_blank" :icon="FileText" class="w-fit">{{ record.evidence_name || t("lifecycle.record.openEvidence") }}</UiButton>
        </section>
        <p v-else class="inline-flex items-center gap-1.5 text-sm text-subtle"><Eye :size="14" aria-hidden="true" />{{ t("lifecycle.record.noEvidence") }}</p>
      </div>
    </div>
  </UiDrawer>
</template>
