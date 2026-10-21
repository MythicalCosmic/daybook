<script setup lang="ts">
/**
 * "Who has read it" (?readers=1): everyone the page is for, within the viewer's branches, with what
 * they read: the current version, an older one, or nothing yet. "Remind" pings those who haven't.
 */
import { BellRing, CheckCheck, CircleDashed, History } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, useReaders, useRefresh } from "../api";
import type { PageDetail, ReaderStatus } from "../types";

const props = defineProps<{ page: PageDetail }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const route = useRoute();
const open = computed(() => route.query.readers !== undefined);
const readers = useReaders(computed(() => props.page.id), open);
const filter = ref<"all" | ReaderStatus>("all");
const reminding = ref(false);

const counts = computed(() => readers.data.value?.counts ?? { read: 0, outdated: 0, unread: 0 });
const total = computed(() => counts.value.read + counts.value.outdated + counts.value.unread);
const rows = computed(() => (readers.data.value?.results ?? []).filter((row) => filter.value === "all" || row.status === filter.value));
const options = computed(() => [
  { value: "all" as const, label: t("common.all"), count: total.value },
  { value: "unread" as const, label: t("knowledge.readers.unread"), count: counts.value.unread },
  { value: "outdated" as const, label: t("knowledge.readers.outdated"), count: counts.value.outdated },
  { value: "read" as const, label: t("knowledge.readers.read"), count: counts.value.read },
]);
const tones = { read: "success", outdated: "warning", unread: "neutral" } as const;

async function remind(): Promise<void> {
  reminding.value = true;
  try {
    const { reminded } = await knowledgeApi.remind(company.currentId ?? 0, props.page.id);
    toast.success(reminded ? t("knowledge.readers.reminded", { n: reminded }, reminded) : t("knowledge.readers.nobodyToRemind"));
    void refresh();
  } catch {
    // Shown by the HTTP layer.
  } finally {
    reminding.value = false;
  }
}
</script>

<template>
  <UiDrawer query-key="readers" :title="t('knowledge.readers.title')" :description="page.title" size="md">
    <div class="flex flex-col gap-4 p-5">
      <ErrorState v-if="readers.isError.value" compact :error="readers.error.value" :retry="() => readers.refetch()" />
      <template v-else-if="!readers.data.value">
        <SkeletonBlock height="72px" radius="12px" />
        <SkeletonBlock v-for="n in 5" :key="n" height="40px" radius="8px" />
      </template>
      <template v-else>
        <div class="ui-card flex items-center gap-4 p-4">
          <ProgressRing :value="counts.read" :max="total || 1" :size="56" tone="auto" show-value />
          <div class="min-w-0 flex-1">
            <p class="text-base font-semibold text-fg">{{ t("knowledge.readers.summary", { read: counts.read, total }) }}</p>
            <p class="text-sm text-muted">{{ page.require_ack ? t("knowledge.readers.versionHint", { v: page.ack_version }) : t("knowledge.readers.optionalHint") }}</p>
          </div>
          <UiButton v-if="counts.unread + counts.outdated > 0" size="sm" :icon="BellRing" :loading="reminding" @click="remind">{{ t("knowledge.readers.remind") }}</UiButton>
        </div>
        <SegmentedControl v-model="filter" :options="options" size="sm" block />
        <EmptyState v-if="!rows.length" size="sm" tone="success" :icon="CheckCheck" :title="t('knowledge.readers.emptyFilter')" />
        <ul v-else class="flex flex-col">
          <li v-for="row in rows" :key="row.member.id" class="flex items-center gap-3 border-b border-line py-2.5 last:border-0">
            <PersonCell :person="row.member" :subtitle="[row.member.position, row.member.branch].filter(Boolean).join(' · ') || null" class="min-w-0 flex-1" />
            <div class="flex shrink-0 flex-col items-end gap-0.5">
              <StatusPill size="sm" :tone="tones[row.status]" :icon="row.status === 'outdated' ? History : row.status === 'unread' ? CircleDashed : undefined" :label="t(`knowledge.readers.status.${row.status}`, { v: row.version ?? '' })" />
              <RelativeTime v-if="row.at" :value="row.at" class="text-[11px] text-subtle" />
            </div>
          </li>
        </ul>
      </template>
    </div>
  </UiDrawer>
</template>
