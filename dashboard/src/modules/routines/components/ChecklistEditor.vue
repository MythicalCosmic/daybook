<script setup lang="ts">
/**
 * Steps of a task as an editable list: type and press Enter to add the next one, remove with ×,
 * reorder with ↑/↓ while a step is focused (Alt+↑/↓).
 */
import { Plus, X } from "@lucide/vue";
import { nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";

import IconButton from "@/components/IconButton.vue";
import TextInput from "@/components/TextInput.vue";

const items = defineModel<string[]>({ default: () => [] });
const props = withDefaults(defineProps<{ max?: number; placeholder?: string }>(), { max: 50, placeholder: undefined });

const { t } = useI18n();
const list = ref<HTMLElement | null>(null);

async function focus(index: number): Promise<void> {
  await nextTick();
  list.value?.querySelectorAll<HTMLInputElement>("input")[index]?.focus();
}

function set(index: number, value: string | null): void {
  const next = [...items.value];
  next[index] = value ?? "";
  items.value = next;
}

async function add(after = items.value.length - 1): Promise<void> {
  if (items.value.length >= props.max) return;
  const next = [...items.value];
  next.splice(after + 1, 0, "");
  items.value = next;
  await focus(after + 1);
}

async function remove(index: number): Promise<void> {
  items.value = items.value.filter((_, i) => i !== index);
  await focus(Math.max(0, index - 1));
}

async function onKeydown(event: KeyboardEvent, index: number): Promise<void> {
  if (event.key === "Enter") {
    event.preventDefault();
    await add(index);
  } else if (event.key === "Backspace" && !items.value[index]) {
    event.preventDefault();
    await remove(index);
  } else if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
    event.preventDefault();
    const target = index + (event.key === "ArrowUp" ? -1 : 1);
    if (target < 0 || target >= items.value.length) return;
    const next = [...items.value];
    [next[index], next[target]] = [next[target]!, next[index]!];
    items.value = next;
    await focus(target);
  }
}
</script>

<template>
  <div ref="list" class="flex flex-col gap-1.5">
    <div v-for="(item, index) in items" :key="index" class="flex items-center gap-1.5">
      <span class="w-5 shrink-0 text-right text-xs font-semibold tabular-nums text-subtle">{{ index + 1 }}.</span>
      <TextInput :model-value="item" size="sm" :maxlength="200" :placeholder="placeholder ?? t('routines.checklist.placeholder')" class="flex-1" @update:model-value="(value) => set(index, value)" @keydown="onKeydown($event, index)" />
      <IconButton :icon="X" :label="t('routines.checklist.remove')" size="sm" :tooltip="false" @click="remove(index)" />
    </div>
    <button
      v-if="items.length < max"
      type="button"
      class="flex h-8 items-center gap-1.5 self-start rounded-[8px] px-2 text-sm font-medium text-muted transition-colors hover:bg-highlight hover:text-fg"
      @click="add()"
    >
      <Plus :size="15" />{{ items.length ? t("routines.checklist.addMore") : t("routines.checklist.add") }}
    </button>
  </div>
</template>
