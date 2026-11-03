<script setup lang="ts">
/**
 * One contract in a side panel synced with `?contract=`: whose, which kind and for how long,
 * probation, whether the employee has read and acknowledged it, the PDF (generated from the
 * template or the uploaded scan) in the viewer, and the actions its status allows.
 */
import { CircleCheck, EllipsisVertical, FileDown, FileText, Hourglass, LockKeyhole, Trash2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PdfPreview from "@/components/PdfPreview.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { closeQueryKey } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { hrApi, useContract, useHrMutation } from "../api";
import { ACTION_ICONS } from "../icons";
import { CONTRACT_TONES, contractActions, hrAccess, onProbation } from "../lib";
import type { Contract, ContractAction } from "../types";
import DaysChip from "./DaysChip.vue";

defineProps<{ warn: { contracts: number; probation: number } }>();
const emit = defineEmits<{ action: [contract: Contract, action: ContractAction] }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const access = computed(() => hrAccess((perm) => company.can(perm)));

const id = computed(() => {
  const raw = route.query.contract;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useContract(id);
const contract = computed(() => query.data.value ?? null);
const actions = computed(() => (contract.value ? contractActions(contract.value) : []));
/** The buttons at the bottom: the everyday ones; ending, terminating and the PDF sit in the menu. */
const buttons = computed(() => actions.value.filter((action) => action !== "terminate" && action !== "end" && action !== "generate-pdf"));
/** The footer reads left to right with the decision due first at the right end, as the primary. */
const footer = computed(() => [...buttons.value.slice(1).reverse(), ...buttons.value.slice(0, 1)]);

const items = computed<DescriptionItem[]>(() => {
  const c = contract.value;
  if (!c) return [];
  return [
    { key: "number", label: t("hr.field.number"), value: c.number || null },
    { key: "kind", label: t("hr.field.contractKind"), value: t(`hr.contractKind.${c.kind}`) },
    { key: "position", label: t("hr.field.position"), value: c.position?.name ?? null },
    { key: "hours", label: t("hr.field.weeklyHours"), value: c.weekly_hours ? t("hr.contract.hours", { n: fmt.number(c.weekly_hours, 1) }) : null },
    { key: "starts", label: t("hr.field.startsOn"), value: fmt.day(c.starts_on, "long") },
    { key: "ends", label: t("hr.field.endsOn"), value: c.ends_on ? fmt.day(c.ends_on, "long") : t("hr.contract.noEnd") },
    {
      key: "probation",
      label: t("hr.field.probation"),
      value: c.probation_until ? (c.probation_passed_at ? t("hr.contract.probationPassedOn", { date: fmt.day(c.probation_passed_at.slice(0, 10), "medium") }) : t("hr.contract.probationTill", { date: fmt.day(c.probation_until, "long") })) : t("hr.contract.noProbation"),
    },
    { key: "template", label: t("hr.field.template"), value: c.template?.name ?? (c.file ? t("hr.contract.scan") : null) },
    ...(c.terminated_on ? [{ key: "terminated", label: t("hr.contract.terminatedOn"), value: fmt.day(c.terminated_on, "long"), hint: c.termination_reason || undefined, wide: true }] : []),
  ];
});

const remove = useHrMutation((cid, contractId: number) => hrApi.removeContract(cid, contractId));
async function removeDraft(): Promise<void> {
  const c = contract.value;
  if (!c) return;
  const answer = await confirm({
    title: t("hr.contract.deleteTitle"),
    message: t("hr.contract.deleteBody", { name: c.member.name }),
    tone: "danger",
    confirmLabel: t("common.delete"),
    icon: Trash2,
    onConfirm: () => remove.mutateAsync(c.id),
  });
  if (answer) {
    toast.success(t("hr.contract.deleted"));
    closeQueryKey(router, "contract");
  }
}

const menu = computed<MenuEntry[]>(() => {
  const c = contract.value;
  if (!c || !access.value.manage) return [];
  const entries: MenuEntry[] = [];
  if (actions.value.includes("generate-pdf")) entries.push({ label: t("hr.contract.action.generate-pdf"), icon: FileDown, onSelect: () => emit("action", c, "generate-pdf") });
  const endings = (["end", "terminate"] as const).filter((action) => actions.value.includes(action));
  if (endings.length && entries.length) entries.push({ type: "separator" });
  for (const action of endings) entries.push({ label: t(`hr.contract.action.${action}`), icon: ACTION_ICONS[action], danger: true, onSelect: () => emit("action", c, action) });
  if (c.actions?.delete) {
    if (entries.length) entries.push({ type: "separator" });
    entries.push({ label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => void removeDraft() });
  }
  return entries;
});
</script>

<template>
  <UiDrawer query-key="contract" size="lg" :title="contract ? (contract.number ? t('hr.contract.titleNumber', { number: contract.number }) : t('hr.contract.one')) : t('hr.contract.one')">
    <template #header-actions>
      <DropdownMenu v-if="menu.length" :items="menu" align="end">
        <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" /></template>
      </DropdownMenu>
    </template>
    <div class="p-5">
      <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
        <SkeletonBlock height="56px" />
        <SkeletonBlock v-for="n in 4" :key="n" height="16px" />
        <SkeletonBlock height="320px" radius="12px" />
      </div>
      <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
      <div v-else-if="contract" class="flex flex-col gap-5">
        <header class="flex items-start gap-3">
          <RouterLink :to="`/c/${company.currentId}/people/${contract.member.id}`" class="shrink-0" :aria-label="contract.member.name">
            <UserAvatar :name="contract.member.name" :src="contract.member.photo_url" :size="44" />
          </RouterLink>
          <div class="min-w-0 flex-1">
            <RouterLink :to="`/c/${company.currentId}/people/${contract.member.id}`" class="block truncate text-base font-semibold text-fg hover:text-primary hover:underline">{{ contract.member.name }}</RouterLink>
            <p class="truncate text-sm text-muted">{{ t(`hr.contractKind.${contract.kind}`) }}<template v-if="contract.position"> · {{ contract.position.name }}</template></p>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusPill :tone="CONTRACT_TONES[contract.status]" size="sm" :label="t(`hr.contractStatus.${contract.status}`)" />
              <DaysChip v-if="contract.ends_on && contract.status === 'active'" :day="contract.ends_on" :warn-days="warn.contracts" prefix="ends" />
              <DaysChip v-if="onProbation(contract)" :day="contract.probation_until!" :warn-days="warn.probation" prefix="probation" always />
            </div>
          </div>
        </header>

        <!-- The employee's acknowledgement (they read it in the app) -->
        <div
          v-if="contract.status !== 'draft'"
          :class="['flex items-start gap-3 rounded-[12px] border px-3.5 py-3', contract.acknowledged_at ? 'border-transparent bg-success-soft' : 'border-line bg-surface-2/60']"
          data-contract-ack
        >
          <CircleCheck v-if="contract.acknowledged_at" :size="18" class="mt-px shrink-0 text-success" aria-hidden="true" />
          <Hourglass v-else :size="18" class="mt-px shrink-0 text-subtle" aria-hidden="true" />
          <div class="min-w-0">
            <p class="text-sm font-semibold text-fg">{{ contract.acknowledged_at ? t("hr.contract.acknowledged") : t("hr.contract.notAcknowledged") }}</p>
            <p class="text-xs text-muted">
              {{ contract.acknowledged_at ? t("hr.contract.acknowledgedOn", { date: fmt.instant(contract.acknowledged_at, "datetime") }) : t("hr.contract.notAcknowledgedHint") }}
            </p>
          </div>
        </div>

        <DescriptionList :items="items" :columns="2" />

        <section class="flex flex-col gap-2">
          <div v-if="contract.file_hidden" class="flex items-center gap-3 rounded-card border border-dashed border-line-strong px-4 py-5 text-sm text-muted" data-contract-file-hidden>
            <LockKeyhole :size="18" class="shrink-0 text-subtle" aria-hidden="true" />{{ t("hr.contract.fileHidden") }}
          </div>
          <PdfPreview v-else-if="contract.file" :src="contract.file" :title="contract.file_is_scan ? t('hr.contract.scan') : t('hr.contract.pdf')" :filename="contract.number ? `${contract.number}.pdf` : undefined" height="min(70vh, 820px)" />
          <div v-else class="rounded-card border border-dashed border-line-strong">
            <EmptyState size="sm" tone="neutral" :icon="FileText" :title="t('hr.contract.noPdf')" :description="contract.template ? t('hr.contract.noPdfTemplate') : t('hr.contract.noPdfScan')">
              <UiButton v-if="actions.includes('generate-pdf')" variant="primary" :icon="FileDown" @click="emit('action', contract, 'generate-pdf')">{{ t("hr.contract.action.generate-pdf") }}</UiButton>
            </EmptyState>
          </div>
        </section>
      </div>
    </div>
    <template v-if="contract && buttons.length" #footer>
      <UiButton
        v-for="action in footer"
        :key="action"
        :variant="action === buttons[0] ? 'primary' : 'secondary'"
        :icon="ACTION_ICONS[action]"
        @click="emit('action', contract, action)"
      >
        {{ t(`hr.contract.action.${action}`) }}
      </UiButton>
    </template>
  </UiDrawer>
</template>
