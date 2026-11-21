<script setup lang="ts">
/**
 * The printed unchangeable list (Print, or the browser's own print on this page): only the list,
 * black on white. Its title, teacher, branch and dates; the grid with each line's day and number;
 * the corrections with their reasons; who sealed it, when, and the whole seal digest; a footer.
 * It sits at the end of <body> and only shows in print, where it hides everything else.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

import { cellKey, dottedDay, journalOf, studentLine, type StudyCell, type StudyProgress } from "../lists";
import type { StudyListDetail } from "../types";

const props = defineProps<{ list: StudyListDetail; cells: Map<string, StudyCell>; progress: StudyProgress }>();

const { t } = useI18n();
const fmt = useFormat();

const corrections = computed(() => journalOf(props.list).filter((line) => line.mark.kind === "correction"));
const standing = (topicId: number, studentId: number) => props.cells.get(cellKey(topicId, studentId))?.standing ?? null;
</script>

<template>
  <Teleport to="body">
    <article class="study-list-print" :aria-label="list.title">
      <header class="slp-head">
        <p class="slp-kicker">{{ t("learning.list.title") }}</p>
        <h1 class="slp-title">{{ list.title }}</h1>
        <p v-if="list.description" class="slp-description">{{ list.description }}</p>
        <dl class="slp-facts">
          <div v-if="list.teacher">
            <dt>{{ t("learning.lists.field.teacher") }}</dt>
            <dd>{{ list.teacher }}</dd>
          </div>
          <div v-if="list.branch">
            <dt>{{ t("learning.lists.field.branch") }}</dt>
            <dd>{{ list.branch.name }}</dd>
          </div>
          <div>
            <dt>{{ t("learning.lists.print.opened") }}</dt>
            <dd>{{ fmt.instant(list.created_at, "date") }}<template v-if="list.created_by">, {{ list.created_by }}</template></dd>
          </div>
          <div>
            <dt>{{ t("learning.lists.col.progress") }}</dt>
            <dd>{{ progress.studied }} / {{ progress.cells }}</dd>
          </div>
          <div>
            <dt>{{ t("learning.lists.print.lines") }}</dt>
            <dd>{{ list.marks.length }} · {{ list.intact ? t("learning.lists.print.intact") : t("learning.lists.print.broken") }}</dd>
          </div>
        </dl>
      </header>

      <table v-if="list.topics.length && list.students.length" class="slp-grid">
        <thead>
          <tr>
            <th class="slp-topic">{{ t("learning.lists.topic.column") }}</th>
            <th v-for="student in list.students" :key="student.id">
              <span class="slp-name">{{ student.name }}</span>
              <span v-if="studentLine(student)" class="slp-sub">{{ studentLine(student) }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="topic in list.topics" :key="topic.id">
            <th class="slp-topic">{{ topic.number }}. {{ topic.title }}</th>
            <td v-for="student in list.students" :key="student.id">
              <template v-if="standing(topic.id, student.id)">
                <span class="slp-day">{{ dottedDay(standing(topic.id, student.id)!.studied_on) }}</span>
                <span class="slp-sub">#{{ standing(topic.id, student.id)!.number }}</span>
              </template>
            </td>
          </tr>
        </tbody>
      </table>

      <section v-if="corrections.length" class="slp-section">
        <h2>{{ t("learning.lists.print.corrections") }}</h2>
        <table class="slp-lines">
          <thead>
            <tr>
              <th>#</th>
              <th>{{ t("learning.lists.journal.when") }}</th>
              <th>{{ t("learning.lists.journal.who") }}</th>
              <th>{{ t("learning.lists.print.takesBack") }}</th>
              <th>{{ t("learning.lists.correct.reason") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="line in corrections" :key="line.mark.id">
              <td>#{{ line.mark.number }}</td>
              <td>{{ fmt.instant(line.mark.written_at) }}</td>
              <td>{{ line.mark.written_by }}</td>
              <td>
                <template v-if="line.corrects">#{{ line.corrects.number }}: {{ line.student?.name ?? "—" }}, {{ line.topic ? `${line.topic.number}. ${line.topic.title}` : "—" }}, {{ dottedDay(line.corrects.studied_on) }}</template>
              </td>
              <td>{{ line.mark.note }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="slp-section slp-seal">
        <template v-if="list.state === 'sealed'">
          <p>
            <strong>{{ t("learning.lists.sealedBy", { name: list.sealed_by || "—", day: list.sealed_at ? fmt.instant(list.sealed_at) : "—" }) }}</strong>
          </p>
          <p>{{ t("learning.lists.print.seal") }}: <code>{{ list.seal_digest }}</code></p>
        </template>
        <p v-else>{{ t("learning.lists.print.notSealed") }}</p>
      </section>

      <footer class="slp-footer">Daybook · {{ t("learning.list.title") }}</footer>
    </article>
  </Teleport>
</template>

<style>
/* Never on screen. */
.study-list-print {
  display: none;
}

@media print {
  @page {
    size: A4 landscape;
    margin: 12mm;
  }
  /* Only the list: everything else at the top of the page leaves the layout. */
  body:has(> .study-list-print) > :not(.study-list-print) {
    display: none !important;
  }
  body:has(> .study-list-print) {
    background: #fff !important;
  }
  .study-list-print {
    display: block !important;
    color: #000;
    background: #fff;
    font:
      9.5pt/1.35 system-ui,
      -apple-system,
      "Segoe UI",
      Roboto,
      sans-serif;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .study-list-print .slp-head {
    margin-bottom: 5mm;
    border-bottom: 1.5pt solid #000;
    padding-bottom: 3mm;
  }
  .study-list-print .slp-kicker {
    margin: 0;
    font-size: 8pt;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .study-list-print .slp-title {
    margin: 1mm 0 0;
    font-size: 16pt;
    font-weight: 700;
  }
  .study-list-print .slp-description {
    margin: 1mm 0 0;
  }
  .study-list-print .slp-facts {
    display: flex;
    flex-wrap: wrap;
    gap: 2mm 8mm;
    margin: 3mm 0 0;
  }
  .study-list-print .slp-facts dt {
    font-size: 7.5pt;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .study-list-print .slp-facts dd {
    margin: 0;
    font-weight: 600;
  }
  .study-list-print table {
    width: 100%;
    border-collapse: collapse;
  }
  .study-list-print th,
  .study-list-print td {
    border: 0.75pt solid #000;
    padding: 1.2mm 1.5mm;
    vertical-align: top;
    text-align: left;
    break-inside: avoid;
  }
  .study-list-print thead {
    display: table-header-group;
  }
  .study-list-print tr {
    break-inside: avoid;
  }
  .study-list-print .slp-grid td {
    text-align: center;
    min-width: 14mm;
  }
  .study-list-print .slp-topic {
    width: 55mm;
    font-weight: 600;
  }
  .study-list-print .slp-name,
  .study-list-print .slp-day,
  .study-list-print .slp-sub {
    display: block;
  }
  .study-list-print .slp-name {
    font-weight: 700;
  }
  .study-list-print .slp-sub {
    font-size: 7.5pt;
    font-weight: 400;
  }
  .study-list-print .slp-day {
    font-weight: 600;
    white-space: nowrap;
  }
  .study-list-print .slp-section {
    margin-top: 5mm;
    break-inside: avoid;
  }
  .study-list-print .slp-section h2 {
    margin: 0 0 2mm;
    font-size: 11pt;
  }
  .study-list-print .slp-seal p {
    margin: 0 0 1mm;
  }
  .study-list-print .slp-seal code {
    font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
    font-size: 8.5pt;
    word-break: break-all;
  }
  .study-list-print .slp-footer {
    margin-top: 6mm;
    border-top: 0.75pt solid #000;
    padding-top: 2mm;
    font-size: 8pt;
    text-align: center;
  }
}
</style>
