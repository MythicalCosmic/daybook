<script setup lang="ts">
/** "?" (plan §6.5): every shortcut — general ones, "g + letter" jumps, and the current page's own. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import KbdKey from "@/components/KbdKey.vue";
import UiDialog from "@/components/UiDialog.vue";
import { registeredHotkeys } from "@/core/hotkeys";
import type { NavGroup } from "@/core/nav";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ groups: NavGroup[]; aiAvailable: boolean }>();

const { t } = useI18n();

interface Row {
  keys: string[] | string;
  label: string;
  sequence?: boolean;
}

const general = computed<Row[]>(() => {
  const rows: Row[] = [{ keys: "mod+k", label: t("shell.shortcuts.palette") }];
  if (props.aiAvailable) rows.push({ keys: "mod+j", label: t("shell.shortcuts.ai") });
  rows.push({ keys: "?", label: t("shell.shortcuts.help") }, { keys: "[", label: t("shell.shortcuts.sidebar") });
  return rows;
});

const navigation = computed<Row[]>(() =>
  props.groups
    .flatMap((group) => group.modules)
    .filter((module) => module.hotkey)
    .map((module) => ({ keys: ["g", module.hotkey!], label: t(module.title), sequence: true })),
);

const navigationColumns = computed(() => {
  const half = Math.ceil(navigation.value.length / 2);
  return [navigation.value.slice(0, half), navigation.value.slice(half)].filter((column) => column.length);
});

const page = computed<Row[]>(() =>
  registeredHotkeys.filter((hotkey) => hotkey.group === "page").map((hotkey) => ({ keys: hotkey.combo, label: t(hotkey.description) })),
);
</script>

<template>
  <UiDialog v-model:open="open" :title="t('shell.shortcuts.title')" size="lg">
    <div class="grid gap-x-6 gap-y-6 md:grid-cols-2">
      <section v-for="section in [
        { id: 'general', title: t('shell.shortcuts.general'), columns: [general] },
        { id: 'page', title: t('shell.shortcuts.page'), columns: [page] },
        { id: 'navigation', title: t('shell.shortcuts.navigation'), columns: navigationColumns },
      ].filter((s) => s.columns.some((c) => c.length))" :key="section.id" :class="(section.id === 'navigation' || !page.length) && 'md:col-span-2'">
        <h3 class="mb-2 text-xs font-medium text-subtle">{{ section.title }}</h3>
        <div :class="['grid gap-3', section.id === 'navigation' && 'md:grid-cols-2']">
          <ul v-for="(column, index) in section.columns" :key="index" class="divide-y divide-line rounded-card border border-line">
            <li v-for="row in column" :key="row.label" class="flex h-10 items-center justify-between gap-4 px-3">
              <span class="truncate text-base text-fg">{{ row.label }}</span>
              <span class="flex shrink-0 items-center gap-1.5 text-xs text-subtle">
                <template v-if="row.sequence && Array.isArray(row.keys)">
                  <KbdKey :keys="row.keys[0]!" />
                  <span>{{ t('shell.shortcuts.then') }}</span>
                  <KbdKey :keys="row.keys[1]!" />
                </template>
                <KbdKey v-else :keys="row.keys" />
              </span>
            </li>
          </ul>
        </div>
      </section>
    </div>
  </UiDialog>
</template>
