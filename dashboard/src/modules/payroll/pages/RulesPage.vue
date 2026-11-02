<script setup lang="ts">
/**
 * Automatic bonuses and fines (plan §6.2 "Rules builder with live preview"): every rule as a card
 * (what it measures, what it pays or takes, for whom, how often) with its on/off switch; the
 * shipped examples arrive switched off. A card opens the builder on `?rule=<id>`; "New rule"
 * opens it empty (`?rule=new&kind=bonus|fine`).
 */
import { Gift, Plus, Scale, Zap } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh, useRules } from "../api";
import RuleChips from "../components/RuleChips.vue";
import RuleDrawer from "../components/RuleDrawer.vue";
import type { Rule } from "../types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const refresh = useRefresh();

const rules = useRules();
const skeleton = useDelayedPending(computed(() => rules.isPending.value));
const sorted = computed(() => [...(rules.data.value ?? [])].sort((a, b) => Number(b.is_active) - Number(a.is_active) || a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name)));
const active = computed(() => sorted.value.filter((rule) => rule.is_active));
const inactive = computed(() => sorted.value.filter((rule) => !rule.is_active));

function open(rule: Rule): void {
  void router.push({ query: { ...route.query, rule: String(rule.id) } });
}
function create(kind: "bonus" | "fine"): void {
  void router.push({ query: { ...route.query, rule: "new", kind } });
}

const switching = ref<number | null>(null);
async function toggle(rule: Rule, value: boolean): Promise<void> {
  switching.value = rule.id;
  try {
    await payrollApi.updateRule(company.currentId ?? 0, rule.id, { is_active: value });
    toast.success(value ? t("payroll.rules.turnedOn", { name: rule.name }) : t("payroll.rules.turnedOff", { name: rule.name }));
    refresh();
  } catch {
    // The HTTP layer said why.
  } finally {
    switching.value = null;
  }
}
const activeKey = computed(() => (typeof route.query.rule === "string" ? route.query.rule : null));
</script>

<template>
  <div>
    <PageHeader :title="t('payroll.nav.rules')" :description="t('payroll.rules.description')">
      <template #actions>
        <UiButton :icon="Scale" data-testid="new-fine-rule" @click="create('fine')">{{ t("payroll.rules.newFine") }}</UiButton>
        <UiButton variant="primary" :icon="Gift" data-testid="new-bonus-rule" @click="create('bonus')">{{ t("payroll.rules.newBonus") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="grid gap-3 md:grid-cols-2">
      <SkeletonBlock v-for="n in 4" :key="n" height="132px" radius="12px" />
    </div>
    <ErrorState v-else-if="rules.isError.value" :error="rules.error.value" :retry="() => rules.refetch()" />
    <EmptyState v-else-if="rules.data.value && !sorted.length" :icon="Zap" :title="t('payroll.rules.emptyTitle')" :description="t('payroll.rules.emptyBody')">
      <UiButton variant="primary" :icon="Plus" @click="create('fine')">{{ t("payroll.rules.newFine") }}</UiButton>
    </EmptyState>
    <div v-else-if="rules.data.value" class="flex flex-col gap-6">
      <section v-for="group in [{ id: 'on', title: t('payroll.rules.on'), list: active }, { id: 'off', title: t('payroll.rules.off'), list: inactive }].filter((g) => g.list.length)" :key="group.id" class="flex flex-col gap-3">
        <h2 class="text-sm font-semibold text-muted">{{ group.title }} <span class="tabular-nums text-subtle">{{ group.list.length }}</span></h2>
        <div class="grid gap-3 md:grid-cols-2">
          <article
            v-for="rule in group.list"
            :key="rule.id"
            :class="[
              'ui-card group flex cursor-pointer flex-col gap-3 p-4 transition-colors hover:border-line-strong',
              activeKey === String(rule.id) && 'border-primary',
              !rule.is_active && 'bg-surface/70',
            ]"
            :data-rule="rule.id"
            @click="open(rule)"
          >
            <header class="flex items-start gap-3">
              <span :class="['grid size-9 shrink-0 place-items-center rounded-[10px]', rule.kind === 'bonus' ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger']">
                <component :is="rule.kind === 'bonus' ? Gift : Scale" :size="18" />
              </span>
              <div class="min-w-0 flex-1">
                <h3 class="truncate text-base font-semibold text-fg group-hover:underline" :title="rule.name">{{ rule.name }}</h3>
                <p class="text-xs text-muted">{{ t(`payroll.adjustmentKind.${rule.kind}`) }} · {{ t(`payroll.rules.mode.${rule.mode}`) }}</p>
              </div>
              <ToggleSwitch
                :model-value="rule.is_active"
                :loading="switching === rule.id"
                :aria-label="rule.is_active ? t('payroll.rules.turnOff') : t('payroll.rules.turnOn')"
                @click.stop
                @update:model-value="(value: boolean) => toggle(rule, value)"
              />
            </header>
            <RuleChips :rule="rule" />
          </article>
        </div>
      </section>
      <p class="text-sm text-muted">{{ t("payroll.rules.footnote") }}</p>
    </div>

    <RuleDrawer :rules="rules.data.value ?? []" />
  </div>
</template>
