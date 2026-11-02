<script setup lang="ts">
/**
 * The compliance matrix (plan §6.2 HR): people × the document kinds their position requires, each
 * cell in force / expiring / expired / missing / not checked yet, grouped by position. By default
 * only people who lack something are listed ("who lacks what"). A cell opens the document, or, when
 * it is missing, the upload prefilled with the person and the kind. Phones get one card per person
 * with the gaps as chips.
 */
import { CircleCheck, CircleDashed, CircleX, Clock4, ListChecks, ShieldQuestion, Upload } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { useCompliance } from "../api";
import { COMPLIANCE_TONES, shapeCompliance } from "../lib";
import type { ComplianceStatus, DocumentKind } from "../types";

const props = defineProps<{ canManage: boolean }>();
const emit = defineEmits<{ upload: [prefill: { member: { id: number; name: string }; kind: DocumentKind }]; configure: [] }>();

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();

const scope = ref<"gaps" | "all">("gaps");
const query = useCompliance({});
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const collator = computed(() => new Intl.Collator(locale.value));
const matrix = computed(() => shapeCompliance(query.data.value, { onlyGaps: scope.value === "gaps", collator: collator.value }));
const noRules = computed(() => !!query.data.value && !query.data.value.kinds.length);

const icons: Record<ComplianceStatus, typeof CircleCheck> = { ok: CircleCheck, expiring: Clock4, expired: CircleX, missing: CircleDashed, unverified: ShieldQuestion };
const colors: Record<ComplianceStatus, string> = { ok: "text-success", expiring: "text-warning", expired: "text-danger", missing: "text-danger", unverified: "text-info" };

function openCell(member: { id: number; name: string }, kind: DocumentKind, status: ComplianceStatus | null, documentId?: number | null): void {
  if (status === null) return;
  if (documentId) {
    void router.push({ query: { ...route.query, document: String(documentId) } });
    return;
  }
  if (props.canManage) emit("upload", { member, kind });
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-3">
      <SegmentedControl
        v-model="scope"
        size="sm"
        :aria-label="t('hr.compliance.scope')"
        :options="[
          { value: 'gaps', label: t('hr.compliance.onlyGaps') },
          { value: 'all', label: t('hr.compliance.everyone') },
        ]"
      />
      <p v-if="query.data.value && !noRules" class="text-sm text-muted">
        {{ matrix.withGaps ? t("hr.compliance.summary", { n: matrix.withGaps, total: matrix.people }, matrix.withGaps) : t("hr.compliance.summaryNone", { total: matrix.people }, matrix.people) }}
      </p>
    </div>

    <div v-if="skeleton" class="ui-card flex flex-col gap-3 p-4">
      <SkeletonBlock v-for="n in 6" :key="n" height="36px" />
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="noRules" class="ui-card">
      <EmptyState :icon="ListChecks" :title="t('hr.compliance.noRulesTitle')" :description="t('hr.compliance.noRulesBody')">
        <UiButton v-if="canManage" variant="primary" :icon="ListChecks" @click="emit('configure')">{{ t("hr.required.button") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else-if="query.data.value && !matrix.groups.length" class="ui-card">
      <EmptyState tone="success" :icon="CircleCheck" :title="t('hr.compliance.allGoodTitle')" :description="t('hr.compliance.allGoodBody')" />
    </div>

    <template v-else-if="query.data.value">
      <!-- Desktop and tablets: the matrix -->
      <div class="ui-card hidden overflow-hidden md:block">
        <div class="overflow-x-auto">
          <table class="w-full border-collapse text-sm">
            <thead>
              <tr class="bg-surface-2/70">
                <th scope="col" class="sticky left-0 z-[1] min-w-[220px] bg-surface-2 px-4 py-2.5 text-left text-xs font-semibold text-muted">{{ t("hr.field.person") }}</th>
                <th v-for="kind in matrix.kinds" :key="kind" scope="col" class="min-w-[112px] px-2 py-2.5 text-center align-bottom text-xs font-semibold text-muted">
                  <span class="block leading-tight">{{ t(`hr.kind.${kind}`) }}</span>
                  <span v-if="matrix.gapsByKind[kind]" class="mt-1 inline-block rounded-full bg-danger-soft px-1.5 text-[11px] font-bold tabular-nums text-danger">{{ matrix.gapsByKind[kind] }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <template v-for="group in matrix.groups" :key="group.key">
                <tr>
                  <th :colspan="matrix.kinds.length + 1" scope="colgroup" class="border-t border-line bg-surface px-4 pb-1 pt-3 text-left text-xs font-semibold uppercase tracking-[0.04em] text-subtle">
                    {{ group.position ?? t("hr.compliance.noPosition") }} · {{ group.rows.length }}
                  </th>
                </tr>
                <tr v-for="row in group.rows" :key="row.member.id" class="border-t border-line first:border-t-0 hover:bg-highlight/60">
                  <th scope="row" class="sticky left-0 z-[1] bg-surface px-4 py-2 text-left font-normal">
                    <div class="flex min-w-0 items-center gap-2.5">
                      <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="26" />
                      <span class="truncate font-medium text-fg">{{ row.member.name }}</span>
                    </div>
                  </th>
                  <td v-for="kind in matrix.kinds" :key="kind" class="px-2 py-1.5 text-center">
                    <span v-if="row.byKind[kind] === null" class="text-subtle" :aria-label="t('hr.compliance.notRequired')">—</span>
                    <button
                      v-else
                      type="button"
                      :class="[
                        'pressable inline-flex size-9 items-center justify-center rounded-[9px] transition-colors hover:bg-surface-2',
                        colors[row.byKind[kind]!],
                        !row.cells.find((c) => c.kind === kind)?.document_id && !canManage && 'cursor-default hover:bg-transparent',
                      ]"
                      :aria-label="`${t(`hr.kind.${kind}`)}: ${t(`hr.compliance.status.${row.byKind[kind]}`)}`"
                      :title="t(`hr.compliance.status.${row.byKind[kind]}`)"
                      @click="openCell(row.member, kind, row.byKind[kind], row.cells.find((c) => c.kind === kind)?.document_id)"
                    >
                      <component :is="icons[row.byKind[kind]!]" :size="18" />
                    </button>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <footer class="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-line px-4 py-2.5 text-xs text-muted">
          <span v-for="status in (['ok', 'expiring', 'expired', 'missing', 'unverified'] as const)" :key="status" class="inline-flex items-center gap-1.5">
            <component :is="icons[status]" :size="14" :class="colors[status]" aria-hidden="true" />{{ t(`hr.compliance.status.${status}`) }}
          </span>
        </footer>
      </div>

      <!-- Phones: one card per person with what they lack -->
      <div class="flex flex-col gap-4 md:hidden">
        <section v-for="group in matrix.groups" :key="group.key" class="flex flex-col gap-2">
          <h3 class="px-1 text-xs font-semibold uppercase tracking-[0.04em] text-subtle">{{ group.position ?? t("hr.compliance.noPosition") }} · {{ group.rows.length }}</h3>
          <article v-for="row in group.rows" :key="row.member.id" class="ui-card p-3.5">
            <div class="flex items-center gap-3">
              <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="34" />
              <p class="min-w-0 flex-1 truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <StatusPill v-if="!row.gaps.length" tone="success" size="sm" :label="t('hr.compliance.complete')" />
            </div>
            <ul v-if="row.gaps.length" class="mt-2.5 flex flex-col gap-1.5">
              <li v-for="gap in row.gaps" :key="gap.kind">
                <button
                  type="button"
                  class="pressable flex min-h-11 w-full items-center gap-2.5 rounded-[10px] border border-line px-3 py-2 text-left hover:bg-highlight"
                  @click="openCell(row.member, gap.kind, gap.status, gap.document_id)"
                >
                  <component :is="icons[gap.status]" :size="17" :class="['shrink-0', colors[gap.status]]" aria-hidden="true" />
                  <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ t(`hr.kind.${gap.kind}`) }}</span>
                  <StatusPill :tone="COMPLIANCE_TONES[gap.status]" size="sm" :label="t(`hr.compliance.status.${gap.status}`)" />
                  <Upload v-if="!gap.document_id && canManage" :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
                </button>
              </li>
            </ul>
          </article>
        </section>
      </div>
    </template>
  </div>
</template>
