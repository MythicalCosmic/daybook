<script setup lang="ts">
/**
 * The global "Record" entry point (plan §6.2: quick add with `N` or a button), rendered in the top
 * bar's `shell.topbar.end` slot on every page of a company with the finance module. It binds the
 * `N` shortcut and mounts the dialog (loaded on first use) whenever `openQuickAdd()` is called.
 */
import { Plus } from "@lucide/vue";
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted } from "vue";
import { useI18n } from "vue-i18n";

import IconButton from "@/components/IconButton.vue";
import { registerHotkey } from "@/core/hotkeys";
import { useCompanyStore } from "@/stores/company";

import { closeQuickAdd, openQuickAdd, quickAdd } from "../quickAdd";

// The slot passes its context; the launcher needs none of it.
defineProps<{ context?: unknown }>();

const QuickAddDialog = defineAsyncComponent(() => import("./QuickAddDialog.vue"));

const { t } = useI18n();
const company = useCompanyStore();
const canRecord = computed(() => company.can("finance.record"));

const open = computed({
  get: () => quickAdd.value !== null,
  set: (value: boolean) => {
    if (!value) closeQuickAdd();
  },
});

let unbind: (() => void) | null = null;
onMounted(() => {
  unbind = registerHotkey("n", () => openQuickAdd("expense"), {
    description: "finance.quick.hotkey",
    group: "general",
    enabled: () => canRecord.value && quickAdd.value === null,
  });
});
onBeforeUnmount(() => unbind?.());
</script>

<template>
  <template v-if="canRecord">
    <IconButton :icon="Plus" :label="t('finance.quick.button')" shortcut="N" tooltip variant="soft" data-testid="quick-add" @click="openQuickAdd('expense')" />
    <QuickAddDialog v-if="quickAdd" v-model:open="open" :request="quickAdd" />
  </template>
</template>
