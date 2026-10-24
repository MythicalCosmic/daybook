<script setup lang="ts">
/**
 * Routines → To confirm: routine work waiting for the viewer's check, grouped by routine and day
 * (oldest first), with the photo proofs in a grid. "Confirm all" confirms a group at once (each
 * run on its own, by the same rules as confirming one: only who may confirm, never their own);
 * one run goes back with a reason. One-off tasks keep their own check (Tasks → Waiting for check).
 */
import { Check, CheckCheck, ChevronRight, ClipboardCheck, Clock, FileText, ListChecks, RotateCcw, Store } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { returnReasonFields } from "@/components/returnReasons";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { usePulseCount } from "@/core/pulse";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useConfirmRuns, useSendBackRun, useToConfirm } from "../api";
import RoutinesHeader from "../components/RoutinesHeader.vue";
import type { ConfirmGroup, RoutineRun } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const ask = useConfirm();
// Confirm and send back are finger-sized on phones.
const { isPhone } = useBreakpoints();
const tap = computed(() => (isPhone.value ? "lg" : "sm"));
const oneOffChecks = usePulseCount("tasks.review");

const query = useToConfirm();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const confirmRuns = useConfirmRuns();
const sendBackRun = useSendBackRun();

// Decided runs leave at once; a refusal brings them back.
const hidden = ref(new Set<number>());
function hide(ids: number[], value: boolean): void {
  const next = new Set(hidden.value);
  for (const id of ids) {
    if (value) next.add(id);
    else next.delete(id);
  }
  hidden.value = next;
}
const groups = computed(() =>
  (query.data.value?.groups ?? []).map((group) => ({ ...group, items: group.items.filter((run) => !hidden.value.has(run.id)) })).filter((group) => group.items.length > 0),
);
const total = computed(() => groups.value.reduce((sum, group) => sum + group.items.length, 0));

async function confirm(runs: RoutineRun[], label: string): Promise<void> {
  const ids = runs.map((run) => run.id);
  hide(ids, true);
  try {
    const result = await confirmRuns.mutateAsync(ids);
    const failed = result.results.filter((row) => !row.ok);
    hide(
      failed.map((row) => row.id),
      false,
    );
    if (result.done) toast.success(t("routines.confirm.done", { n: result.done }, result.done), { description: label });
    if (failed.length) toast.error(t("routines.confirm.someFailed", { n: failed.length }, failed.length), { description: failed[0]?.error });
  } catch {
    hide(ids, false); // the HTTP layer showed why
  }
}

async function sendBack(run: RoutineRun, group: ConfirmGroup): Promise<void> {
  const answer = await ask({
    title: t("routines.confirm.sendBackTitle"),
    message: `${run.member.name} · ${group.routine.title}`,
    ...returnReasonFields(t),
    reasonLabel: t("routines.confirm.reason"),
    reasonPlaceholder: t("routines.confirm.reasonPlaceholder"),
    confirmLabel: t("routines.confirm.sendBack"),
    tone: "danger",
  });
  if (!answer) return;
  hide([run.id], true);
  try {
    await sendBackRun.mutateAsync({ id: run.id, reason: answer.reason });
    toast.success(t("routines.confirm.sentBack"), { description: `${run.member.name} · ${group.routine.title}` });
  } catch {
    hide([run.id], false);
  }
}

const photo = (run: RoutineRun, group: ConfirmGroup) => ({
  src: run.proof_photo ?? run.proof_thumb!,
  caption: [run.member.name, group.routine.title, run.completed_at ? fmt.instant(run.completed_at, "short") : ""].filter(Boolean).join(" · "),
});
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <RoutinesHeader :description="t('routines.confirm.description')" />

    <p v-if="oneOffChecks > 0" class="-mt-2 flex flex-wrap items-center gap-1.5 text-sm text-muted">
      <ClipboardCheck :size="15" class="text-subtle" aria-hidden="true" />{{ t("routines.confirm.oneOff", { n: oneOffChecks }, oneOffChecks) }}
      <RouterLink :to="`/c/${company.currentId}/tasks/reviews`" class="inline-flex items-center font-medium text-accent-fg hover:underline">{{ t("routines.confirm.toTasks") }}<ChevronRight :size="14" /></RouterLink>
    </p>

    <div v-if="skeleton" class="flex flex-col gap-4">
      <div v-for="n in 2" :key="n" class="ui-card flex flex-col gap-3 p-4">
        <SkeletonBlock width="30%" height="18px" />
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"><SkeletonBlock v-for="m in 4" :key="m" height="220px" radius="12px" /></div>
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !total" class="ui-card">
      <EmptyState tone="success" size="lg" :icon="ClipboardCheck" :title="t('routines.confirm.emptyTitle')" :description="t('routines.confirm.emptyBody')">
        <UiButton :to="{ name: 'routines.today' }" :icon-right="ChevronRight">{{ t("routines.nav.today") }}</UiButton>
      </EmptyState>
    </div>
    <!-- A group of one run takes one column, so small groups sit side by side; bigger ones take the row. -->
    <TransitionGroup v-else name="list" tag="div" class="relative grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
      <section
        v-for="group in groups"
        :key="`${group.routine.id}-${group.day}`"
        :class="['ui-card min-w-0 overflow-hidden', group.items.length > 1 && 'md:col-span-full']"
        :data-group="`${group.routine.id}-${group.day}`"
      >
        <header class="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3">
          <div class="min-w-[min(100%,220px)] flex-1">
            <h2 class="truncate text-base font-semibold text-fg" :title="group.routine.title">{{ group.routine.title }}</h2>
            <p class="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
              <span class="font-medium text-fg">{{ fmt.day(group.day, "weekday") }}</span>
              <span class="inline-flex items-center gap-1 tabular-nums"><Clock :size="14" aria-hidden="true" />{{ group.routine.due_time }}</span>
              <span v-if="group.routine.branch" class="inline-flex items-center gap-1"><Store :size="14" aria-hidden="true" />{{ group.routine.branch.name }}</span>
              <span v-if="group.items.length > 1">{{ t("routines.confirm.waiting", { n: group.items.length }, group.items.length) }}</span>
            </p>
          </div>
          <UiButton v-if="group.items.length > 1" variant="primary" :size="tap" :icon="CheckCheck" :loading="confirmRuns.isPending.value" class="max-sm:w-full" @click="confirm(group.items, group.routine.title)">
            {{ t("routines.confirm.all", { n: group.items.length }, group.items.length) }}
          </UiButton>
        </header>
        <TransitionGroup name="list" tag="ul" :class="['relative grid gap-3 p-4', group.items.length > 1 && 'sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5']">
          <li v-for="run in group.items" :key="run.id" class="flex min-w-0 flex-col overflow-hidden rounded-[12px] border border-line bg-surface" :data-run="run.id">
            <!-- A photo gets the frame; work without one gets a compact card (no empty picture). -->
            <div v-if="run.proof_thumb" class="relative aspect-[4/3] w-full overflow-hidden bg-surface-2">
              <ProofThumb :src="run.proof_thumb" :images="[photo(run, group)]" :alt="run.member.name" size="fill" class="!rounded-none" />
            </div>
            <div class="flex flex-1 flex-col gap-2 p-3">
              <div class="flex min-w-0 items-center gap-2.5">
                <UserAvatar :name="run.member.name" :src="run.member.photo_url" :size="28" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-medium text-fg" :title="run.member.name">{{ run.member.name }}</p>
                  <p v-if="run.completed_at" :class="['truncate text-xs font-semibold tabular-nums', run.on_time === false ? 'text-warning' : 'text-success']">
                    {{ t(run.on_time === false ? "routines.confirm.late" : "routines.confirm.onTime", { time: fmt.instant(run.completed_at, "time") }) }}
                  </p>
                </div>
              </div>
              <p v-if="run.proof_thumb && run.proof_text" class="line-clamp-2 rounded-[8px] bg-surface-2 px-2.5 py-1.5 text-sm text-fg">{{ run.proof_text }}</p>
              <blockquote v-else-if="run.proof_text" class="line-clamp-3 rounded-[8px] border-l-[3px] border-primary bg-surface-2 px-2.5 py-1.5 text-sm text-fg">{{ run.proof_text }}</blockquote>
              <p v-else-if="!run.proof_thumb" :class="['inline-flex items-center gap-1 text-xs', run.proof === 'none' ? 'text-subtle' : 'font-medium text-warning']" data-testid="run-no-proof">
                <FileText :size="13" aria-hidden="true" />{{ run.proof === "none" ? t("routines.confirm.noProof") : t("routines.confirm.noPhoto") }}
              </p>
              <p v-if="run.checklist.total" class="inline-flex items-center gap-1 text-xs text-muted"><ListChecks :size="13" aria-hidden="true" />{{ t("routines.confirm.checklist", { done: run.checklist.done, total: run.checklist.total }) }}</p>
              <div class="mt-auto flex gap-2 pt-1">
                <UiButton :size="tap" :icon="Check" class="flex-1" @click="confirm([run], `${run.member.name} · ${group.routine.title}`)">{{ t("routines.confirm.one") }}</UiButton>
                <UiButton :size="tap" variant="ghost" :icon="RotateCcw" class="flex-1" @click="sendBack(run, group)">{{ t("routines.confirm.sendBack") }}</UiButton>
              </div>
            </div>
          </li>
        </TransitionGroup>
      </section>
    </TransitionGroup>
  </div>
</template>
