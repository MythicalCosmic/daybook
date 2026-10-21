<script setup lang="ts">
/** One emoji for a page or a space: a short, business-minded grid, or none. */
import { SmilePlus } from "@lucide/vue";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import UiPopover from "@/components/UiPopover.vue";

import { EMOJIS } from "../lib";

const model = defineModel<string>({ default: "" });
withDefaults(defineProps<{ size?: "md" | "lg"; label?: string }>(), { size: "md", label: undefined });

const { t } = useI18n();
const open = ref(false);

function pick(emoji: string): void {
  model.value = emoji;
  open.value = false;
}
</script>

<template>
  <UiPopover v-model:open="open" width="296px" align="start">
    <template #trigger>
      <button
        type="button"
        :class="[
          'pressable grid shrink-0 place-items-center rounded-[10px] border border-dashed border-line-strong text-muted transition-colors hover:border-solid hover:bg-highlight hover:text-fg',
          size === 'lg' ? 'size-14 text-[30px]' : 'size-9 text-[19px]',
          model && 'border-transparent bg-surface-2 dark:bg-surface-3',
        ]"
        :aria-label="label ?? t('knowledge.emoji.pick')"
      >
        <span v-if="model" aria-hidden="true">{{ model }}</span>
        <SmilePlus v-else :size="size === 'lg' ? 22 : 17" aria-hidden="true" />
      </button>
    </template>
    <div class="flex flex-col gap-2">
      <div class="grid grid-cols-8 gap-0.5" role="listbox" :aria-label="t('knowledge.emoji.pick')">
        <button
          v-for="emoji in EMOJIS"
          :key="emoji"
          type="button"
          role="option"
          :aria-selected="emoji === model"
          :class="['grid size-8 place-items-center rounded-[7px] text-[18px] hover:bg-highlight', emoji === model && 'bg-accent-soft']"
          @click="pick(emoji)"
        >
          {{ emoji }}
        </button>
      </div>
      <button v-if="model" type="button" class="self-start rounded-[6px] px-1.5 py-1 text-sm font-medium text-muted hover:bg-highlight hover:text-fg" @click="pick('')">
        {{ t("knowledge.emoji.none") }}
      </button>
    </div>
  </UiPopover>
</template>
