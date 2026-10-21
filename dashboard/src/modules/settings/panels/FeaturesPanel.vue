<script setup lang="ts">
/**
 * Settings › Modules (plan §3.2 `Company.features`, the only module switch): a card per module
 * with what it does and a switch. Switching on creates the module's defaults (payment methods,
 * categories, leave types…) and the module appears in the sidebar at once; switching off hides it
 * and keeps every row. The switch moves instantly and moves back if the server refuses.
 */
import { Banknote, Boxes, Clock, HeartHandshake, IdCard, Sparkles, ShoppingCart, Wallet, type LucideIcon } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiBadge from "@/components/UiBadge.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import type { CompanyFeature } from "@/core/features";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { useFeatures, useToggleModule } from "../api";
import PanelHeader from "../components/PanelHeader.vue";

const { t } = useI18n();
const features = useFeatures();
const toggle = useToggleModule();
const confirm = useConfirm();
const showSkeleton = useDelayedPending(() => features.isPending.value);
const busy = ref<CompanyFeature | null>(null);

const ICONS: Record<CompanyFeature, LucideIcon> = {
  finance: Wallet,
  sales: ShoppingCart,
  stock: Boxes,
  attendance: Clock,
  hr: IdCard,
  payroll: Banknote,
  ai: Sparkles,
  recognition: HeartHandshake,
};
/** Modules that work best together (a hint, not a rule). */
const PAIRS: Partial<Record<CompanyFeature, CompanyFeature[]>> = {
  sales: ["finance"],
  stock: ["sales"],
  payroll: ["attendance", "finance"],
};

const enabledCount = computed(() => features.data.value?.features.length ?? 0);
const cards = computed(() =>
  (features.data.value?.modules ?? []).map((module) => ({
    ...module,
    icon: ICONS[module.key],
    title: t(`settings.module.${module.key}.title`),
    body: t(`settings.module.${module.key}.body`),
    pairs: (PAIRS[module.key] ?? []).filter((other) => !features.data.value?.features.includes(other)),
  })),
);

async function flip(key: CompanyFeature, on: boolean): Promise<void> {
  const current = features.data.value?.features ?? [];
  const title = t(`settings.module.${key}.title`);
  if (!on) {
    const answer = await confirm({
      title: t("settings.modules.offTitle", { name: title }),
      message: t("settings.modules.offBody"),
      confirmLabel: t("settings.modules.offConfirm"),
    });
    if (!answer) return;
  }
  const next = on ? [...current, key] : current.filter((feature) => feature !== key);
  busy.value = key;
  try {
    await toggle.mutateAsync(next);
    toast.success(on ? t("settings.modules.on", { name: title }) : t("settings.modules.off", { name: title }), {
      description: on ? t("settings.modules.onHint") : undefined,
    });
  } catch {
    // The HTTP layer already showed why; the switch went back.
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <div>
    <PanelHeader :title="t('settings.panel.features')" :description="t('settings.modules.description')">
      <template v-if="features.data.value" #actions>
        <UiBadge tone="primary" size="md">{{ t("settings.modules.count", { n: enabledCount, total: cards.length }) }}</UiBadge>
      </template>
    </PanelHeader>

    <ErrorState v-if="features.isError.value" :error="features.error.value" :retry="() => features.refetch()" :retrying="features.isFetching.value" />

    <div v-else-if="showSkeleton || !features.data.value" class="grid gap-3 md:grid-cols-2" aria-busy="true">
      <div v-for="n in 8" :key="n" class="ui-card flex gap-3 p-4">
        <SkeletonBlock width="40px" height="40px" radius="10px" />
        <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="40%" /><SkeletonBlock :lines="2" /></div>
      </div>
    </div>

    <ul v-else class="grid gap-3 md:grid-cols-2">
      <li
        v-for="card in cards"
        :key="card.key"
        :class="[
          'ui-card flex gap-3.5 p-4 transition-[border-color,box-shadow] duration-200',
          card.enabled ? 'border-[color-mix(in_srgb,var(--c-primary)_38%,var(--c-border))] shadow-[0_0_0_3px_var(--c-accent-soft)]' : '',
        ]"
      >
        <span :class="['grid size-10 shrink-0 place-items-center rounded-[10px] transition-colors', card.enabled ? 'bg-primary text-on-primary' : 'bg-surface-2 text-muted']">
          <component :is="card.icon" :size="20" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-start justify-between gap-3">
            <p class="pt-0.5 text-base font-semibold text-fg">{{ card.title }}</p>
            <ToggleSwitch
              :model-value="card.enabled"
              :aria-label="card.title"
              :loading="busy === card.key"
              @update:model-value="(on: boolean) => flip(card.key, on)"
            />
          </div>
          <p class="mt-1 text-sm text-muted">{{ card.body }}</p>
          <p v-if="card.enabled && card.pairs.length" class="mt-2 text-xs text-accent-fg">
            {{ t("settings.modules.pairs", { names: card.pairs.map((p) => t(`settings.module.${p}.title`)).join(", ") }) }}
          </p>
        </div>
      </li>
    </ul>
  </div>
</template>
