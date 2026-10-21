<script setup lang="ts">
/**
 * A project on the index: colour strip, key, name, status and health, progress ring with cards
 * done and overdue, the next milestone, budget burn (for people who see money), the team and the
 * due date. The whole card links to the board.
 */
import { CalendarDays, Check, Flag, Lock, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import AvatarStack from "@/components/AvatarStack.vue";
import MoneyText from "@/components/MoneyText.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { burnTone, colorVar, daysBetween, STATUS_TONE } from "../lib";
import type { ProjectItem } from "../types";
import HealthDot from "./HealthDot.vue";
import ProjectBadge from "./ProjectBadge.vue";

const props = defineProps<{ project: ProjectItem; companyId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const to = computed(() => `/c/${props.companyId}/projects/${props.project.id}`);
const done = computed(() => props.project.status === "completed");
const ring = computed(() => (done.value ? "success" : props.project.health === "off_track" ? "danger" : props.project.health === "at_risk" ? "warning" : "primary"));
const daysLeft = computed(() => (props.project.due_on && !done.value ? daysBetween(todayIn(company.timezone), props.project.due_on) : null));
</script>

<template>
  <RouterLink
    :to="to"
    class="project-card group relative flex min-w-0 flex-col overflow-hidden rounded-card border border-line bg-surface shadow-xs transition-[border-color,box-shadow,transform] duration-150 hover:-translate-y-px hover:border-line-strong hover:shadow-raised focus-visible:outline-2 focus-visible:outline-offset-2"
    :class="project.archived_at && 'opacity-70'"
  >
    <span class="h-1 w-full shrink-0" :style="{ background: colorVar(project.color) }" aria-hidden="true" />
    <div class="flex flex-1 flex-col gap-4 p-4">
      <header class="flex items-start gap-3">
        <ProjectBadge :color="project.color" :icon="project.icon" :size="40" />
        <div class="min-w-0 flex-1">
          <p class="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted">
            <span class="font-mono tabular-nums">{{ project.key }}</span>
            <UiTooltip v-if="project.visibility === 'members'" :content="t('projects.visibility.membersTip')">
              <Lock :size="11" class="text-subtle" :aria-label="t('projects.visibility.members')" />
            </UiTooltip>
            <span v-if="project.branch" class="truncate font-medium text-subtle">· {{ project.branch.name }}</span>
          </p>
          <h3 class="mt-0.5 line-clamp-2 text-md font-semibold leading-snug text-fg group-hover:text-primary">{{ project.name }}</h3>
        </div>
        <HealthDot :health="project.health" :reported="project.reported?.health ?? null" class="mt-1.5" />
      </header>

      <div class="flex items-center gap-3">
        <ProgressRing :value="project.progress.percent" :size="48" :tone="ring" :show-value="project.progress.percent < 100" :label="t('projects.card.progress')">
          <Check v-if="project.progress.percent >= 100" class="size-5 text-success" :stroke-width="3" aria-hidden="true" />
        </ProgressRing>
        <div class="min-w-0 flex-1 text-sm">
          <p class="font-semibold text-fg">
            {{ t("projects.card.cards", { done: project.progress.done, total: project.progress.total }) }}
            <span v-if="project.progress.overdue" class="ml-1 font-medium text-danger">· {{ t("projects.card.overdue", { n: project.progress.overdue }) }}</span>
          </p>
          <p v-if="project.next_milestone" class="mt-0.5 flex min-w-0 items-center gap-1 text-xs text-muted">
            <Flag :size="12" class="shrink-0" />
            <span class="truncate">{{ project.next_milestone.name }}</span>
            <span v-if="project.next_milestone.due_on" class="shrink-0 tabular-nums">· {{ fmt.day(project.next_milestone.due_on, "short") }}</span>
          </p>
          <p v-else class="mt-0.5 text-xs text-subtle">{{ t("projects.card.noMilestone") }}</p>
        </div>
      </div>

      <div v-if="project.budget && project.spent !== undefined" class="flex flex-col gap-1.5">
        <div class="flex items-baseline justify-between gap-2 text-xs">
          <span class="font-medium text-muted">{{ t("projects.card.budget") }}</span>
          <span class="tabular-nums text-fg">
            <MoneyText :value="project.spent" :currency="project.currency" compact />
            <span class="text-subtle"> / <MoneyText :value="project.budget" :currency="project.budget_currency" compact /></span>
          </span>
        </div>
        <ProgressBar :value="Math.min(project.burn ?? 0, 100)" :tone="burnTone(project.burn)" size="xs" :aria-label="t('projects.card.burn', { n: project.burn ?? 0 })" />
      </div>

      <footer class="mt-auto flex items-center gap-2 border-t border-line pt-3">
        <AvatarStack v-if="project.members.length" :people="project.members" :max="4" :size="28" />
        <span v-else class="inline-flex items-center gap-1 text-xs text-subtle"><Users :size="13" />{{ t("projects.card.noTeam") }}</span>
        <span class="flex-1" />
        <StatusPill v-if="project.status !== 'active'" size="sm" :tone="STATUS_TONE[project.status]" :label="t(`projects.status.${project.status}`)" />
        <span
          v-if="project.due_on"
          class="inline-flex items-center gap-1 text-xs font-medium tabular-nums"
          :class="daysLeft !== null && daysLeft < 0 ? 'text-danger' : daysLeft !== null && daysLeft <= 7 ? 'text-warning' : 'text-muted'"
        >
          <CalendarDays :size="13" />{{ fmt.day(project.due_on, "short") }}
        </span>
      </footer>
    </div>
  </RouterLink>
</template>
