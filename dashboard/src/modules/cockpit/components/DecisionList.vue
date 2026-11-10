<script setup lang="ts">
/**
 * "Qaroringizni kutmoqda": what waits for the owner's yes or no, oldest first, with chips per
 * kind of decision. Approve is one tap; a Reject that needs a reason asks for it. Each button
 * calls the endpoint its module gave the item, so the module's own service decides; the item
 * leaves at once and comes back if the server refuses. The same requests also reach Telegram.
 */
import { ArrowUpRight, CircleDot, Clock, Gavel, HandCoins, PackageMinus, Percent, Plane, ReceiptText, ShoppingCart, UserPlus } from "@lucide/vue";
import { computed, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import type { QueueAction } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import { useDecision, type CockpitDecisions, type Decision } from "../api";
import { companyUrl, decisionGroups } from "../lib";

const props = withDefaults(defineProps<{ decisions: CockpitDecisions; limit?: number }>(), { limit: 8 });

const { t } = useI18n();
const company = useCompanyStore();
const confirm = useConfirm();
const decide = useDecision();

const ICONS: Record<string, Component> = {
  expense: ReceiptText,
  hire: UserPlus,
  people: UserPlus,
  time_off: Plane,
  overtime: Clock,
  pay: HandCoins,
  purchase: ShoppingCart,
  discount: Percent,
  stock: PackageMinus,
  other: CircleDot,
};

const groups = computed(() => decisionGroups(props.decisions));
const chosen = ref<string | null>(null);
const items = computed(() => props.decisions.items.filter((item) => !chosen.value || item.group === chosen.value).slice(0, props.limit));
/** What the list doesn't show: in the chosen kind, or in all of them. */
const more = computed(() => {
  const waiting = chosen.value ? (groups.value.find((group) => group.group === chosen.value)?.count ?? 0) : props.decisions.total;
  return Math.max(0, waiting - items.value.length);
});
const inbox = computed(() => `/c/${company.currentId}/inbox`);
const pending = ref<string | null>(null);
const keyOf = (item: Decision) => `${item.kind}:${item.id}`;

async function run(item: Decision, action: QueueAction): Promise<void> {
  let reason: string | undefined;
  if (action.needs_reason) {
    const answer = await confirm({ title: action.label, message: item.title, reason: "required", tone: action.style === "danger" ? "danger" : "primary", confirmLabel: action.label });
    if (!answer) return;
    reason = answer.reason;
  }
  pending.value = `${keyOf(item)}:${action.key}`;
  try {
    await decide.mutateAsync({ item, action, reason });
    toast.success(t("cockpit.decisions.done", { action: action.label }), { description: item.title });
  } catch {
    // The HTTP layer showed the server's message; the item is back in the list.
  } finally {
    pending.value = null;
  }
}
</script>

<template>
  <section class="ui-card flex min-w-0 flex-col" :aria-label="t('cockpit.decisions.title')" data-decisions>
    <header class="flex items-center gap-3 px-4 pb-3 pt-4">
      <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg" aria-hidden="true"><Gavel :size="17" /></span>
      <div class="min-w-0 flex-1">
        <h2 class="text-base font-semibold leading-5 text-fg">{{ t("cockpit.decisions.title") }}</h2>
        <p class="text-xs text-muted">{{ t("cockpit.decisions.subtitle") }}</p>
      </div>
      <UiBadge v-if="decisions.total" :count="decisions.total" tone="primary" />
    </header>

    <div v-if="groups.length > 1" class="no-scrollbar flex gap-1.5 overflow-x-auto px-4 pb-3" role="group" :aria-label="t('cockpit.decisions.title')">
      <button
        type="button"
        :aria-pressed="!chosen"
        :class="['shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors', !chosen ? 'border-transparent bg-fg text-surface' : 'border-line text-muted hover:border-line-strong hover:text-fg']"
        @click="chosen = null"
      >
        {{ t("cockpit.decisions.everything") }} · {{ decisions.total }}
      </button>
      <button
        v-for="group in groups"
        :key="group.group"
        type="button"
        :aria-pressed="chosen === group.group"
        :data-group="group.group"
        :class="[
          'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
          chosen === group.group ? 'border-transparent bg-fg text-surface' : 'border-line text-muted hover:border-line-strong hover:text-fg',
        ]"
        @click="chosen = chosen === group.group ? null : group.group"
      >
        <component :is="ICONS[group.group] ?? CircleDot" :size="12" aria-hidden="true" />
        {{ t(`cockpit.decisions.group.${group.group}`) }} · {{ group.count }}
      </button>
    </div>

    <EmptyState v-if="!decisions.items.length" class="border-t border-line" size="sm" tone="success" :title="t('cockpit.decisions.empty')" :description="t('cockpit.decisions.emptyBody')" />
    <TransitionGroup v-else name="list" tag="ul" class="relative flex flex-col divide-y divide-line border-t border-line">
      <li v-for="item in items" :key="keyOf(item)" class="flex gap-3 px-4 py-3" :data-decision="keyOf(item)">
        <span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-[9px] bg-surface-2 text-muted dark:bg-surface-3" aria-hidden="true">
          <component :is="ICONS[item.group] ?? CircleDot" :size="15" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-start gap-2">
            <p class="min-w-0 flex-1 text-sm font-semibold leading-5 text-fg">{{ item.title }}</p>
            <RelativeTime v-if="item.created_at" :value="item.created_at" class="shrink-0 pt-0.5 text-[11px] text-subtle" />
          </div>
          <p v-if="item.subtitle" class="mt-0.5 line-clamp-2 text-xs text-muted">{{ item.subtitle }}</p>
          <div class="mt-2 flex flex-wrap items-center gap-1.5">
            <UiButton
              v-for="action in item.actions"
              :key="action.key"
              size="sm"
              :variant="action.style === 'primary' ? 'primary' : 'secondary'"
              :class="action.style === 'danger' && 'hover:!text-danger'"
              :loading="pending === `${keyOf(item)}:${action.key}`"
              :disabled="!!pending && pending.startsWith(`${keyOf(item)}:`)"
              :data-action="action.key"
              @click="run(item, action)"
              >{{ action.label }}</UiButton
            >
            <RouterLink
              v-if="item.url"
              :to="companyUrl(company.currentId, item.url)"
              class="ml-auto inline-flex h-7 items-center gap-1 rounded-[7px] px-2 text-xs font-medium text-muted transition-colors hover:bg-highlight hover:text-fg"
            >
              {{ t("cockpit.decisions.open") }}<ArrowUpRight :size="13" aria-hidden="true" />
            </RouterLink>
          </div>
        </div>
      </li>
    </TransitionGroup>

    <footer class="mt-auto flex items-center justify-end border-t border-line px-4 py-2.5">
      <RouterLink :to="inbox" class="inline-flex items-center gap-1 text-xs font-semibold text-muted transition-colors hover:text-fg">
        {{ more ? t("cockpit.decisions.more", { n: more }, more) : t("cockpit.decisions.all") }}<ArrowUpRight :size="13" aria-hidden="true" />
      </RouterLink>
    </footer>
  </section>
</template>
