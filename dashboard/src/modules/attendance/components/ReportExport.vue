<script setup lang="ts">
/**
 * The Reports page's export: each of the five reports as Excel or PDF, for the period and filters
 * on the page (the server builds the file; it needs `data.export`, so the button is hidden
 * without it). The table the page shows comes first.
 */
import { CalendarDays, ChevronDown, Download, FileSpreadsheet, FileText, Network, Store, Trophy, Users } from "@lucide/vue";
import { computed, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import UiPopover from "@/components/UiPopover.vue";
import { toast } from "@/components/useToast";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { downloadReport } from "../api";
import type { ReportFormat, ReportKind, ReportParams } from "../types";

const props = defineProps<{ kind: ReportKind; params: ReportParams }>();

const { t } = useI18n();
const company = useCompanyStore();
const companyId = useCompanyId();
const open = ref(false);
const busy = ref<string | null>(null);

const allowed = computed(() => company.can("data.export"));

const ITEMS: Array<{ kind: ReportKind; label: string; icon: Component }> = [
  { kind: "summary", label: "attendance.reports.view.people", icon: Users },
  { kind: "departments", label: "attendance.reports.view.departments", icon: Network },
  { kind: "branches", label: "attendance.reports.view.branches", icon: Store },
  { kind: "trend", label: "attendance.reports.trend.title", icon: CalendarDays },
  { kind: "punctuality", label: "attendance.reports.export.ranking", icon: Trophy },
];
const items = computed(() => [...ITEMS].sort((a, b) => Number(b.kind === props.kind) - Number(a.kind === props.kind)));

async function download(kind: ReportKind, format: ReportFormat): Promise<void> {
  if (busy.value) return;
  busy.value = `${kind}.${format}`;
  try {
    const name = await downloadReport(companyId.value, kind, props.params, format);
    open.value = false;
    toast.success(t("attendance.reports.export.ready", { name }));
  } catch {
    // The HTTP client said why.
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <UiPopover v-if="allowed" v-model:open="open" width="340px" align="end" :padded="false">
    <template #trigger>
      <UiButton :icon="Download" :icon-right="ChevronDown" :loading="busy !== null" data-report-export>{{ t("common.export.title") }}</UiButton>
    </template>
    <div class="flex flex-col p-1.5">
      <p class="px-2.5 pb-1.5 pt-1 text-xs text-muted">{{ t("attendance.reports.export.hint") }}</p>
      <div
        v-for="item in items"
        :key="item.kind"
        :data-report-kind="item.kind"
        :class="['flex items-center gap-2 rounded-[10px] py-1 pl-2.5 pr-1', item.kind === kind ? 'bg-surface-2' : '']"
      >
        <component :is="item.icon" :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
        <span class="min-w-0 flex-1 truncate text-sm font-medium text-fg">{{ t(item.label) }}</span>
        <UiButton
          size="sm"
          variant="ghost"
          :icon="FileSpreadsheet"
          :loading="busy === `${item.kind}.xlsx`"
          :disabled="busy !== null && busy !== `${item.kind}.xlsx`"
          :data-format="`${item.kind}.xlsx`"
          @click="download(item.kind, 'xlsx')"
        >
          {{ t("attendance.reports.export.xlsx") }}
        </UiButton>
        <UiButton
          size="sm"
          variant="ghost"
          :icon="FileText"
          :loading="busy === `${item.kind}.pdf`"
          :disabled="busy !== null && busy !== `${item.kind}.pdf`"
          :data-format="`${item.kind}.pdf`"
          @click="download(item.kind, 'pdf')"
        >
          {{ t("attendance.reports.export.pdf") }}
        </UiButton>
      </div>
    </div>
  </UiPopover>
</template>
