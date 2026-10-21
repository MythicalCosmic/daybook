<script setup lang="ts">
/**
 * The kind of a new money account as a compact grid of tiles: four across on wider screens, two on
 * phones, arrow keys move between them. It keeps the "New account" dialog short enough to fit a
 * laptop screen with its footer in view (RadioCards with a sentence each would need two screens).
 */
import { RadioGroupItem, RadioGroupRoot } from "reka-ui";
import { useI18n } from "vue-i18n";

import { useControl } from "@/components/field";

import { ACCOUNT_ICONS, ACCOUNT_KINDS } from "../lib";
import type { AccountKind } from "../types";

const model = defineModel<AccountKind>({ required: true });
const props = withDefaults(defineProps<{ id?: string; disabled?: boolean; invalid?: boolean }>(), { id: undefined, disabled: false, invalid: false });

const { t } = useI18n();
const control = useControl(props);

function pick(value: unknown): void {
  model.value = value as AccountKind;
}
</script>

<template>
  <RadioGroupRoot
    :id="control.id.value"
    :model-value="model"
    :aria-labelledby="control.labelId.value"
    :aria-describedby="control.describedBy.value"
    loop
    class="grid grid-cols-2 gap-2 sm:grid-cols-4"
    @update:model-value="pick"
  >
    <RadioGroupItem
      v-for="kind in ACCOUNT_KINDS"
      :key="kind"
      :value="kind"
      :data-testid="`account-kind-${kind}`"
      class="pressable group flex min-h-[52px] items-center gap-2.5 rounded-[10px] border border-line bg-surface p-2.5 text-left outline-offset-2 hover:border-line-strong sm:min-h-[68px] sm:flex-col sm:items-start sm:gap-2 data-[state=checked]:border-primary data-[state=checked]:bg-accent-soft/40 data-[state=checked]:shadow-[0_0_0_1px_var(--c-primary)]"
    >
      <span class="grid size-7 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-muted transition-colors group-data-[state=checked]:bg-primary group-data-[state=checked]:text-on-primary dark:bg-surface-3">
        <component :is="ACCOUNT_ICONS[kind]" :size="15" aria-hidden="true" />
      </span>
      <span class="text-sm font-semibold leading-[18px] text-fg">{{ t(`finance.accountKind.${kind}`) }}</span>
    </RadioGroupItem>
  </RadioGroupRoot>
</template>
