<script setup lang="ts">
/**
 * An unchangeable list as a bound journal: every line in order (number, when, who, the student,
 * the topic, what kind, the day or the reason, the start of its digest). A corrected line is struck
 * through and names the line that took it back; a correction names the line it takes back.
 */
import { CornerDownRight, NotebookPen } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";

import { dottedDay, journalOf, shortDigest, type JournalLine } from "../lists";
import type { StudyListDetail } from "../types";

const props = defineProps<{ list: StudyListDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const table = useDataTable({ id: "learning.listJournal", pageSize: 200 });

const lines = computed(() => journalOf(props.list));
const struck = (line: JournalLine) => line.correctedBy !== null;
const topicText = (line: JournalLine) => (line.topic ? `${line.topic.number}. ${line.topic.title}` : "—");
const detailText = (line: JournalLine) => (line.mark.kind === "studied" ? [dottedDay(line.mark.studied_on), line.mark.note].filter(Boolean).join(" · ") : line.mark.note);

const columns = computed<TableColumn<JournalLine>[]>(() => [
  { id: "number", header: "#", width: 64, numeric: true, hideable: false, value: (line) => line.mark.number },
  { id: "when", header: t("learning.lists.journal.when"), width: 168, value: (line) => line.mark.written_at, csv: (line) => fmt.instant(line.mark.written_at) },
  { id: "who", header: t("learning.lists.journal.who"), minWidth: 150, value: (line) => line.mark.written_by },
  { id: "student", header: t("learning.lists.student.label"), minWidth: 160, value: (line) => line.student?.name ?? "" },
  { id: "topic", header: t("learning.lists.topic.label"), minWidth: 200, value: topicText },
  { id: "kind", header: t("learning.lists.journal.kind"), width: 190, value: (line) => line.mark.kind, csv: (line) => t(`learning.lists.kind.${line.mark.kind}`) },
  { id: "detail", header: t("learning.lists.journal.detail"), minWidth: 220, value: detailText },
  { id: "digest", header: t("learning.lists.journal.digest"), width: 112, value: (line) => line.mark.digest, csv: (line) => line.mark.digest },
]);
</script>

<template>
  <div data-testid="list-journal">
    <DataTable
      :state="table"
      :columns="columns"
      :rows="lines"
      :total="lines.length"
      :row-key="(line: JournalLine) => line.mark.id"
      hide-pagination
      csv-name="journal"
      :empty-icon="NotebookPen"
      :empty-title="t('learning.lists.journal.emptyTitle')"
      :empty-description="t('learning.lists.journal.emptyBody')"
      :row-class="(line: JournalLine) => (struck(line) ? 'opacity-70' : undefined)"
    >
      <template #cell-number="{ row }">
        <span class="font-mono text-xs text-muted">#{{ row.mark.number }}</span>
      </template>
      <template #cell-when="{ row }">
        <span :class="['text-sm tabular-nums', struck(row) ? 'text-subtle line-through' : 'text-fg']">{{ fmt.instant(row.mark.written_at) }}</span>
      </template>
      <template #cell-who="{ row }">
        <span :class="['block truncate text-sm', struck(row) ? 'text-subtle line-through' : 'text-fg']">{{ row.mark.written_by || "—" }}</span>
      </template>
      <template #cell-student="{ row }">
        <span :class="['block truncate text-sm', struck(row) ? 'text-subtle line-through' : 'font-medium text-fg']">{{ row.student?.name ?? "—" }}</span>
      </template>
      <template #cell-topic="{ row }">
        <span :class="['block truncate text-sm', struck(row) ? 'text-subtle line-through' : 'text-fg']" :title="topicText(row)">{{ topicText(row) }}</span>
      </template>
      <template #cell-kind="{ row }">
        <span class="flex flex-col items-start gap-0.5">
          <StatusPill size="sm" :tone="row.mark.kind === 'studied' ? (struck(row) ? 'neutral' : 'success') : 'warning'" :label="t(`learning.lists.kind.${row.mark.kind}`)" />
          <span v-if="row.correctedBy" class="inline-flex items-center gap-1 text-[11px] text-warning" data-corrected-by>
            <CornerDownRight :size="11" aria-hidden="true" />{{ t("learning.lists.correctedByLine", { n: row.correctedBy.number }) }}
          </span>
          <span v-else-if="row.corrects" class="text-[11px] text-muted">{{ t("learning.lists.correctsLine", { n: row.corrects.number }) }}</span>
        </span>
      </template>
      <template #cell-detail="{ row }">
        <span :class="['block truncate text-sm', struck(row) ? 'text-subtle line-through' : row.mark.kind === 'correction' ? 'text-fg italic' : 'text-fg']" :title="detailText(row)">
          {{ detailText(row) || "—" }}
        </span>
      </template>
      <template #cell-digest="{ row }">
        <span class="font-mono text-xs text-muted" :title="row.mark.digest">{{ shortDigest(row.mark.digest, 8) }}</span>
      </template>
      <template #card="{ row }">
        <div class="flex flex-col gap-1">
          <div class="flex items-center justify-between gap-3">
            <span class="font-mono text-xs text-muted">#{{ row.mark.number }} · {{ fmt.instant(row.mark.written_at, "short") }}</span>
            <StatusPill size="sm" :tone="row.mark.kind === 'studied' ? (struck(row) ? 'neutral' : 'success') : 'warning'" :label="t(`learning.lists.kind.${row.mark.kind}`)" />
          </div>
          <p :class="['text-sm', struck(row) ? 'text-subtle line-through' : 'font-medium text-fg']">{{ row.student?.name ?? "—" }} · {{ topicText(row) }}</p>
          <p v-if="detailText(row)" :class="['text-sm', struck(row) ? 'text-subtle line-through' : 'text-muted']">{{ detailText(row) }}</p>
          <p class="text-xs text-subtle">
            {{ row.mark.written_by || "—" }} · <span class="font-mono">{{ shortDigest(row.mark.digest, 8) }}</span>
            <template v-if="row.correctedBy"> · {{ t("learning.lists.correctedByLine", { n: row.correctedBy.number }) }}</template>
            <template v-else-if="row.corrects"> · {{ t("learning.lists.correctsLine", { n: row.corrects.number }) }}</template>
          </p>
        </div>
      </template>
    </DataTable>
  </div>
</template>
