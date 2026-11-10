<script setup lang="ts">
/**
 * One business review as Maslahatchi wrote it: its chibi with the period and who wrote it (Claude
 * or the templates), the headline, the four numbers it stands on (read from its facts), what went
 * well and what went wrong, the three things to do (each opening the page of the number it rests
 * on), and each pharmacy's numbers. Every number comes from the review's facts, never retyped.
 */
import { ArrowRight, Building2, CircleCheck, Lightbulb, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import DeltaBadge from "@/components/DeltaBadge.vue";
import KpiCard from "@/components/KpiCard.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";

import { periodLabel, reviewKpis, writerKey } from "../advisor";
import type { Briefing } from "../briefings";
import AgentChibi from "./AgentChibi.vue";

const props = defineProps<{ review: Briefing; agentName: string; on: boolean }>();

const { t } = useI18n();
const fmt = useFormat();
const { isPhone } = useBreakpoints();

const kpis = computed(() => reviewKpis(props.review.facts, t, fmt.lang.value));
const sections = computed(() => {
  const found = new Map(props.review.sections.map((section) => [section.key, section] as const));
  return (["went_well", "went_wrong"] as const).map((key) => found.get(key)).filter((section) => !!section && section.bullets.length);
});
const period = computed(() => periodLabel(props.review.period, fmt.lang.value));
const kindLabel = computed(() => t(`ai.advisor.kind.${props.review.kind}`));
const todoTitle = computed(() => t(props.review.kind === "monthly" ? "ai.advisor.todoMonth" : "ai.advisor.todoWeek"));
const branches = computed(() => (props.review.facts.finance?.branches.length ?? 0) > 1 ? props.review.facts.finance!.branches : []);
const currency = computed<Currency>(() => (props.review.facts.currency === "USD" ? "USD" : "UZS"));

function pts(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** A move in percentage points: "+5", "−10", "0,5". */
function signedPoints(value: string): string {
  const moved = Number(value);
  const text = fmt.number(Math.abs(moved), 1);
  return moved > 0 ? `+${text}` : moved < 0 ? `−${text}` : text;
}
</script>

<template>
  <article class="ui-card overflow-hidden" data-testid="advisor-review" :data-review="review.id">
    <header class="advisor-hero flex items-start gap-3 px-4 pb-4 pt-5 md:gap-5 md:px-6 md:pb-5 md:pt-6">
      <div class="advisor-chibi grid shrink-0 place-items-center rounded-2xl" aria-hidden="true">
        <AgentChibi agent-key="advisor" :name="agentName" :on="on" :size="isPhone ? 46 : 58" />
      </div>
      <div class="flex min-w-0 flex-1 flex-col gap-1.5">
        <p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
          <span class="font-semibold text-fg">{{ kindLabel }}</span>
          <span aria-hidden="true">·</span>
          <span class="num" data-testid="advisor-period">{{ period }}</span>
          <UiBadge :tone="review.written_by === 'ai' ? 'primary' : 'neutral'" data-testid="advisor-writer">{{ t(writerKey(review.written_by)) }}</UiBadge>
        </p>
        <h2 class="font-display text-lg leading-snug text-fg md:text-[1.6rem] md:leading-tight" data-testid="advisor-headline">{{ review.headline }}</h2>
        <p v-if="review.written_at" class="text-xs text-subtle">{{ t("ai.advisor.writtenAt", { time: fmt.instant(review.written_at, "short") }) }}</p>
      </div>
    </header>

    <div v-if="kpis.length" class="advisor-kpis grid grid-cols-2 border-y border-line xl:grid-cols-4" data-testid="advisor-kpis">
      <KpiCard
        v-for="kpi in kpis"
        :key="kpi.id"
        variant="plain"
        :label="kpi.label"
        :value="kpi.value"
        :format="kpi.format"
        :currency="currency"
        :compact="kpi.compact"
        :delta="kpi.delta"
        :points="kpi.points"
        :inverse="kpi.inverse"
        :delta-label="kpi.deltaLabel"
        :hint="kpi.hint"
        :to="kpi.to"
        :data-kpi="kpi.id"
      />
    </div>

    <div v-if="sections.length" class="grid gap-5 px-4 py-5 md:grid-cols-2 md:px-6 md:py-6">
      <section v-for="section in sections" :key="section!.key" class="flex min-w-0 flex-col gap-3" :data-section="section!.key">
        <h3 class="flex items-center gap-2 text-md font-semibold text-fg">
          <span :class="['grid size-7 place-items-center rounded-full', section!.key === 'went_well' ? 'bg-success-soft text-success' : 'bg-warning-soft text-warning']" aria-hidden="true">
            <CircleCheck v-if="section!.key === 'went_well'" :size="15" />
            <TriangleAlert v-else :size="15" />
          </span>
          {{ section!.title }}
        </h3>
        <ul class="flex flex-col gap-2">
          <li v-for="(bullet, index) in section!.bullets" :key="index" class="flex gap-2.5 text-base leading-relaxed text-fg">
            <span :class="['mt-[0.6rem] size-1.5 shrink-0 rounded-full', section!.key === 'went_well' ? 'bg-success' : 'bg-warning']" aria-hidden="true" />
            <span class="min-w-0">{{ bullet }}</span>
          </li>
        </ul>
      </section>
    </div>

    <section v-if="review.actions.length" class="border-t border-line px-4 py-5 md:px-6 md:py-6" data-testid="advisor-actions">
      <h3 class="mb-3 flex items-center gap-2 text-md font-semibold text-fg">
        <span class="grid size-7 place-items-center rounded-full bg-accent-soft text-accent-fg" aria-hidden="true"><Lightbulb :size="15" /></span>
        {{ todoTitle }}
      </h3>
      <ol class="grid gap-3 lg:grid-cols-3">
        <li v-for="(action, index) in review.actions" :key="action.fact" class="advisor-action flex flex-col gap-3 rounded-[14px] border border-line bg-surface p-3.5" :data-fact="action.fact">
          <div class="flex gap-3">
            <span class="num grid size-7 shrink-0 place-items-center rounded-full bg-primary text-sm font-semibold text-on-primary" aria-hidden="true">{{ index + 1 }}</span>
            <p class="min-w-0 flex-1 text-base leading-relaxed text-fg">{{ action.text }}</p>
          </div>
          <UiButton :to="action.url" size="sm" variant="secondary" :icon-right="ArrowRight" class="self-start lg:mt-auto">{{ action.label }}</UiButton>
        </li>
      </ol>
    </section>

    <section v-if="branches.length" class="border-t border-line px-4 py-5 md:px-6 md:py-6" data-testid="advisor-branches">
      <h3 class="mb-3 flex items-center gap-2 text-md font-semibold text-fg">
        <span class="grid size-7 place-items-center rounded-full bg-surface-2 text-muted dark:bg-surface-3" aria-hidden="true"><Building2 :size="15" /></span>
        {{ t("ai.advisor.branches") }}
      </h3>
      <div class="overflow-x-auto">
        <table class="w-full min-w-[520px] text-sm">
          <thead>
            <tr class="text-left text-xs uppercase tracking-wide text-subtle">
              <th class="py-2 pr-3 font-medium">{{ t("ai.advisor.col.branch") }}</th>
              <th class="py-2 pr-3 text-right font-medium">{{ t("ai.advisor.kpi.revenue") }}</th>
              <th class="py-2 pr-3 text-right font-medium">{{ t("ai.advisor.kpi.grossMargin") }}</th>
              <th class="py-2 text-right font-medium">{{ t("ai.advisor.kpi.profit") }}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="branch in branches" :key="branch.id" :data-branch="branch.id">
              <td class="py-2.5 pr-3 font-medium text-fg">
                <RouterLink :to="branch.url" class="hover:underline">{{ branch.name }}</RouterLink>
              </td>
              <td class="num py-2.5 pr-3 text-right text-fg">
                {{ fmt.money(branch.revenue.value, currency, { compact: true }) }}
                <DeltaBadge class="ml-1.5" :value="pts(branch.revenue.change_pct)" variant="text" size="sm" />
              </td>
              <td class="num py-2.5 pr-3 text-right text-fg">
                {{ branch.gross_margin ? `${fmt.number(branch.gross_margin.value, 1)}%` : "—" }}
                <span v-if="branch.gross_margin?.change_pts" :class="['ml-1.5 text-xs', Number(branch.gross_margin.change_pts) < 0 ? 'text-danger' : 'text-success']">
                  {{ t("ai.advisor.points", { value: signedPoints(branch.gross_margin.change_pts) }) }}
                </span>
              </td>
              <td :class="['num py-2.5 text-right', Number(branch.profit.value) < 0 ? 'text-danger' : 'text-fg']">{{ fmt.money(branch.profit.value, currency, { compact: true }) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </article>
</template>

<style scoped>
.advisor-hero {
  background:
    radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, #6b8fd6 16%, transparent) 0%, transparent 55%),
    radial-gradient(90% 120% at 100% 0%, color-mix(in srgb, #f2b544 10%, transparent) 0%, transparent 60%),
    var(--c-surface);
}
.advisor-chibi {
  width: 76px;
  height: 76px;
  background: color-mix(in srgb, #6b8fd6 14%, var(--c-surface));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #6b8fd6 22%, transparent);
}
@media (max-width: 639px) {
  .advisor-chibi {
    width: 60px;
    height: 60px;
  }
}
.advisor-kpis > :deep(*) {
  border-color: var(--c-line);
}
.advisor-kpis > :deep(*:nth-child(odd)) {
  border-right: 1px solid var(--c-line);
}
.advisor-kpis > :deep(*:nth-child(-n + 2)) {
  border-bottom: 1px solid var(--c-line);
}
@media (min-width: 1280px) {
  .advisor-kpis > :deep(*) {
    border-right: 1px solid var(--c-line);
    border-bottom: 0;
  }
  .advisor-kpis > :deep(*:last-child) {
    border-right: 0;
  }
}
.advisor-action {
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.advisor-action:hover {
  border-color: var(--c-line-strong);
  box-shadow: var(--shadow-raised, 0 1px 2px rgb(0 0 0 / 0.06));
}
</style>
