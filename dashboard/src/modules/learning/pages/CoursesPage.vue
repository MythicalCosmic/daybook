<script setup lang="ts">
/**
 * Courses: every course with its steps, about how long it takes, whether it is mandatory and how
 * far its people are (in the viewer's branches). `?new=1` asks for a title and opens the editor.
 */
import { GraduationCap, Plus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useDataTable } from "@/components/useDataTable";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { learningApi, useCourses, useRefresh } from "../api";
import { STATUS_TONES } from "../lib";
import type { CourseRow, Status } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const router = useRouter();
const refresh = useRefresh();

const search = useRouteState("q", rs.string(""));
const status = useRouteState("status", rs.string(""));
const creating = useRouteState("new", rs.boolean(false));
const canManage = computed(() => company.can("learning.manage"));
const params = computed(() => ({ q: search.value || undefined, status: status.value || undefined }));
const courses = useCourses(params);
const table = useDataTable({ id: "learning.courses", pageSize: 100 });

const statusOptions = computed(() => [
  { value: "" as const, label: t("learning.courses.live") },
  ...(["draft", "published", "archived"] as const).map((value) => ({ value, label: t(`learning.status.${value}`) })),
]);
const statusModel = computed({ get: () => status.value as "" | Status, set: (value: "" | Status) => (status.value = value) });

const columns = computed<TableColumn<CourseRow>[]>(() => [
  { id: "title", header: t("learning.col.course"), minWidth: 260, sticky: true },
  { id: "status", header: t("learning.col.status"), width: 130 },
  { id: "steps", header: t("learning.col.steps"), numeric: true, width: 90 },
  { id: "minutes", header: t("learning.col.minutes"), numeric: true, width: 110 },
  { id: "deadline", header: t("learning.col.deadline"), width: 150, value: (row) => row.due_days ?? 0 },
  { id: "progress", header: t("learning.col.progress"), minWidth: 220, value: (row) => row.stats.percent },
  { id: "late", header: t("learning.col.late"), numeric: true, width: 90, value: (row) => row.stats.overdue },
]);
const filtered = computed(() => Boolean(search.value || status.value));

// A new course: a title first, then everything else in the editor.
const title = ref("");
const mandatory = ref(false);
const busy = ref(false);
watch(creating, (value) => {
  if (value) {
    title.value = "";
    mandatory.value = false;
  }
});
async function create(): Promise<void> {
  if (!title.value.trim()) return;
  busy.value = true;
  try {
    const course = await learningApi.createCourse(cid.value, { title: title.value.trim(), mandatory: mandatory.value });
    refresh();
    creating.value = false;
    void router.push(`/c/${company.currentId}/learning/courses/${course.id}`);
  } finally {
    busy.value = false;
  }
}

function open(row: CourseRow): void {
  void router.push(`/c/${company.currentId}/learning/courses/${row.id}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('learning.nav.courses')" :description="t('learning.courses.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("learning.courses.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="courses.data.value && !courses.data.value.length && !filtered" class="ui-card">
      <EmptyState :icon="GraduationCap" :title="t('learning.courses.emptyTitle')" :description="t('learning.courses.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("learning.courses.new") }}</UiButton>
      </EmptyState>
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="courses.data.value"
      :total="courses.data.value?.length"
      row-key="id"
      :loading="courses.isPending.value"
      :fetching="courses.isFetching.value"
      :error="courses.error.value"
      :retry="() => courses.refetch()"
      clickable
      :filtered="filtered"
      csv-name="courses"
      @row-click="open"
      @clear-filters="
        search = '';
        status = '';
      "
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('learning.courses.search')" clearable />
          <SegmentedControl v-model="statusModel" :options="statusOptions" size="sm" />
        </div>
      </template>
      <template #cell-title="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <span class="grid size-8 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-base" aria-hidden="true">{{ row.emoji || "📘" }}</span>
          <span class="min-w-0">
            <span class="block truncate font-medium text-fg">{{ row.title }}</span>
            <span v-if="row.mandatory" class="block truncate text-xs text-accent-fg">{{ t("learning.mandatory") }}</span>
          </span>
        </div>
      </template>
      <template #cell-status="{ row }">
        <StatusPill :tone="STATUS_TONES[row.status]" :label="t(`learning.status.${row.status}`)" size="sm" />
      </template>
      <template #cell-minutes="{ row }">{{ row.minutes ? fmt.duration(row.minutes) : "—" }}</template>
      <template #cell-deadline="{ row }">
        <span class="text-sm text-muted">
          {{ row.due_days ? t("learning.courses.dueDays", { n: row.due_days }, row.due_days) : "—" }}
          <template v-if="row.renew_months"> · {{ t("learning.courses.renews", { n: row.renew_months }, row.renew_months) }}</template>
        </span>
      </template>
      <template #cell-progress="{ row }">
        <div class="flex items-center gap-2">
          <ProgressBar class="flex-1" size="sm" :value="row.stats.completed" :max="row.stats.people || 1" tone="auto" :label="row.title" />
          <span class="w-16 text-right text-xs text-muted tabular-nums">{{ row.stats.people ? `${row.stats.completed}/${row.stats.people}` : "—" }}</span>
        </div>
      </template>
      <template #cell-late="{ row }">
        <span :class="row.stats.overdue ? 'font-semibold text-danger' : 'text-subtle'">{{ row.stats.overdue || "—" }}</span>
      </template>
    </DataTable>

    <UiDialog v-model:open="creating" :title="t('learning.courses.new')" :description="t('learning.courses.newHint')" size="sm">
      <form class="flex flex-col gap-4" @submit.prevent="create">
        <FormField :label="t('learning.course.name')" required>
          <TextInput v-model="title" :maxlength="200" autofocus :placeholder="t('learning.course.namePlaceholder')" />
        </FormField>
        <ToggleSwitch v-model="mandatory" layout="row" :label="t('learning.course.mandatory')" :description="t('learning.course.mandatoryHint')" />
      </form>
      <template #footer>
        <UiButton variant="ghost" @click="creating = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" :disabled="!title.trim()" @click="create">{{ t("common.create") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
