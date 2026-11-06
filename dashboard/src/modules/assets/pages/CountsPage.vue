<script setup lang="ts">
/**
 * Inventory counts (inventarizatsiya): start one for a branch, go down the list marking each
 * asset found, found damaged or missing, then close it. Found ones get a line on their timeline,
 * damaged ones their condition, missing ones stay for the owner to decide (write off as lost).
 */
import { ClipboardCheck, ClipboardList, Plus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { assetsApi, useCount, useCounts, useRefresh } from "../api";
import type { CountResult } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const counts = useCounts();
const canManage = computed(() => company.can("assets.manage"));
const starting = useRouteState("new", rs.boolean(false));
const openId = useRouteState("count", rs.number(0));
const count = useCount(computed(() => openId.value || null));
const drawerOpen = computed({ get: () => openId.value > 0, set: (value) => (openId.value = value ? openId.value : 0) });

const branch = ref<number | null>(null);
const busy = ref(false);
watch(starting, (value) => {
  if (value) branch.value = company.branchFilter.length === 1 ? company.branchFilter[0] : null;
});

async function start(): Promise<void> {
  busy.value = true;
  try {
    const made = await assetsApi.startCount(company.currentId ?? 0, { branch: branch.value });
    starting.value = false;
    refresh();
    openId.value = made.id;
  } finally {
    busy.value = false;
  }
}

async function mark(line: number, result: CountResult): Promise<void> {
  if (!openId.value) return;
  await assetsApi.markLine(company.currentId ?? 0, openId.value, line, { result });
  refresh();
}

async function close(): Promise<void> {
  const current = count.data.value;
  if (!current) return;
  const answer = await confirm({
    title: t("assets.counts.closeTitle"),
    message: t("assets.counts.closeBody", { pending: current.totals.pending, missing: current.totals.missing }),
    confirmLabel: t("assets.counts.close"),
    onConfirm: () => assetsApi.closeCount(company.currentId ?? 0, current.id),
  });
  if (answer) {
    toast.success(t("assets.counts.closed"));
    refresh();
  }
}

const resultOptions = computed(() =>
  (["found", "damaged", "missing"] as const).map((value) => ({ value, label: t(`assets.count.${value}`) })),
);
const tone = (result: CountResult) => (result === "found" ? "success" : result === "missing" ? "danger" : result === "damaged" ? "warning" : "neutral");
</script>

<template>
  <div>
    <PageHeader :title="t('assets.nav.counts')" :description="t('assets.counts.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="starting = true">{{ t("assets.counts.start") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="counts.isPending.value" class="grid gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="64px" radius="12px" /></div>
    <div v-else-if="!counts.data.value?.length" class="ui-card">
      <EmptyState :icon="ClipboardList" :title="t('assets.counts.emptyTitle')" :description="t('assets.counts.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="starting = true">{{ t("assets.counts.start") }}</UiButton>
      </EmptyState>
    </div>
    <ul v-else class="flex flex-col gap-2">
      <li v-for="row in counts.data.value" :key="row.id">
        <button type="button" class="ui-card flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left hover:bg-surface-2/40" @click="openId = row.id">
          <ClipboardCheck :size="18" class="text-muted" aria-hidden="true" />
          <span class="min-w-0 flex-1">
            <span class="block font-medium text-fg">{{ row.branch?.name ?? t("assets.counts.everything") }}</span>
            <span class="block text-xs text-muted">{{ t("assets.counts.started", { day: fmt.day(row.started_on, "medium") }) }}</span>
          </span>
          <span class="flex gap-1.5 text-xs">
            <StatusPill size="sm" tone="success" :label="t('assets.counts.foundN', { n: row.totals.found + row.totals.damaged })" />
            <StatusPill v-if="row.totals.missing" size="sm" tone="danger" :label="t('assets.counts.missingN', { n: row.totals.missing })" />
            <StatusPill v-if="row.totals.pending" size="sm" tone="neutral" :label="t('assets.counts.pendingN', { n: row.totals.pending })" />
          </span>
          <StatusPill :tone="row.status === 'open' ? 'primary' : 'neutral'" :label="t(`assets.counts.status.${row.status}`)" />
        </button>
      </li>
    </ul>

    <UiDialog v-model:open="starting" :title="t('assets.counts.startTitle')" :description="t('assets.counts.startBody')" size="sm">
      <FormField :label="t('assets.col.branch')">
        <BranchPicker v-model="branch" clearable :placeholder="t('assets.counts.everything')" />
      </FormField>
      <template #footer>
        <UiButton variant="ghost" @click="starting = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" @click="start">{{ t("assets.counts.start") }}</UiButton>
      </template>
    </UiDialog>

    <UiDrawer v-model:open="drawerOpen" :title="count.data.value ? count.data.value.branch?.name ?? t('assets.counts.everything') : t('assets.nav.counts')" size="lg">
      <template v-if="count.data.value">
        <p class="mb-3 text-sm text-muted">{{ t("assets.counts.started", { day: fmt.day(count.data.value.started_on, "medium") }) }}</p>
        <ul class="divide-y divide-line" data-testid="count-lines">
          <li v-for="line in count.data.value.lines" :key="line.id" class="flex flex-wrap items-center gap-3 py-2.5">
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-fg">{{ line.asset.name }}</span>
              <span class="block font-mono text-xs text-muted">{{ line.number }}</span>
            </span>
            <SegmentedControl
              v-if="count.data.value.status === 'open' && canManage"
              :model-value="line.result"
              size="sm"
              :options="resultOptions"
              @update:model-value="(value) => mark(line.id, value as CountResult)"
            />
            <StatusPill v-else size="sm" :tone="tone(line.result)" :label="t(`assets.count.${line.result}`)" />
          </li>
        </ul>
      </template>
      <template v-if="count.data.value?.status === 'open' && canManage" #footer>
        <UiButton variant="primary" :icon="ClipboardCheck" @click="close">{{ t("assets.counts.close") }}</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>
