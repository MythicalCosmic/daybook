<script setup lang="ts">
/**
 * The component kitchen (plan §6.3): every design-system component, live, in both themes and both
 * densities, at /dashboard/_kitchen in development only. It is W0-D's visual acceptance test.
 *
 * URL: ?theme=light|dark|split  ?density=comfortable|compact  ?lang=uz|ru|en  ?only=<section>,…
 * "split" shows light and dark side by side on wide screens.
 */
import { computed, onMounted, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { LANGUAGES, type Language } from "@/api/types";
import SegmentedControl from "@/components/SegmentedControl.vue";
import { i18n, setLanguage } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { useUiStore, type Density } from "@/stores/ui";

import KitchenBasics from "./kitchen/KitchenBasics.vue";
import KitchenCharts from "./kitchen/KitchenCharts.vue";
import KitchenInputs from "./kitchen/KitchenInputs.vue";
import KitchenLayout from "./kitchen/KitchenLayout.vue";
import KitchenOverlays from "./kitchen/KitchenOverlays.vue";
import KitchenTable from "./kitchen/KitchenTable.vue";
import KitchenViews from "./kitchen/KitchenViews.vue";
import { DEV_MESSAGES } from "./stubMessages";

for (const language of LANGUAGES) i18n.global.mergeLocaleMessage(language, DEV_MESSAGES[language]);

type Theme = "light" | "dark" | "split";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const ui = useUiStore();
const session = useSessionStore();
const company = useCompanyStore();
const k = (key: string) => t(`dev.kitchen.${key}`);

const GROUPS: Array<{ id: string; sections: string[]; component: Component }> = [
  { id: "basics", sections: ["foundations", "actions"], component: KitchenBasics },
  { id: "inputs", sections: ["inputs"], component: KitchenInputs },
  { id: "overlays", sections: ["overlays", "feedback"], component: KitchenOverlays },
  { id: "table", sections: ["table"], component: KitchenTable },
  { id: "views", sections: ["records", "calendars", "boards"], component: KitchenViews },
  { id: "charts", sections: ["kpi", "charts"], component: KitchenCharts },
  { id: "layout", sections: ["layout"], component: KitchenLayout },
];

const query = (key: string) => {
  const value = route.query[key];
  return typeof value === "string" ? value : undefined;
};

const theme = computed<Theme>({
  get: () => (query("theme") === "dark" ? "dark" : query("theme") === "split" ? "split" : "light"),
  set: (value) => void router.replace({ query: { ...route.query, theme: value === "light" ? undefined : value } }),
});
const density = computed<Density>({
  get: () => (query("density") === "compact" ? "compact" : "comfortable"),
  set: (value) => void router.replace({ query: { ...route.query, density: value === "compact" ? value : undefined } }),
});
const language = computed<Language>({
  get: () => {
    const value = query("lang");
    return value === "uz" || value === "ru" || value === "en" ? value : "en";
  },
  set: (value) => void router.replace({ query: { ...route.query, lang: value === "en" ? undefined : value } }),
});
const only = computed(() => (query("only") ?? "").split(",").filter(Boolean));
const groups = computed(() => (only.value.length ? GROUPS.filter((g) => only.value.includes(g.id) || g.sections.some((s) => only.value.includes(s))) : GROUPS));
const sections = computed(() => groups.value.flatMap((g) => g.sections));

// Theme and density apply here without being saved, so the real console keeps the person's choice.
watch(
  [theme, density],
  ([nextTheme, nextDensity]) => {
    ui.themeMode = nextTheme === "dark" ? "dark" : "light";
    ui.density = nextDensity;
  },
  { immediate: true },
);
watch(language, (value) => setLanguage(value), { immediate: true });

onMounted(() => {
  // In the mock build the demo owner is signed in: format money and dates as Demo Dorixona does.
  if (session.me && company.currentId === null) company.setCurrent(company.defaultCompanyId());
});

const themeOptions = computed(() => [
  { value: "light" as Theme, label: k("light") },
  { value: "dark" as Theme, label: k("dark") },
  { value: "split" as Theme, label: k("split") },
]);
const densityOptions = computed(() => [
  { value: "comfortable" as Density, label: t("shell.density.comfortable") },
  { value: "compact" as Density, label: t("shell.density.compact") },
]);
const languageOptions = LANGUAGES.map((value) => ({ value, label: value.toUpperCase() }));
</script>

<template>
  <div class="min-h-dvh bg-canvas text-fg" :data-density="density">
    <header class="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur-md">
      <div class="mx-auto flex max-w-[1680px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 md:px-6">
        <div class="flex min-w-0 items-center gap-2.5">
          <svg viewBox="0 0 50 50" class="size-7 shrink-0" aria-hidden="true">
            <circle cx="21" cy="21" r="21" fill="#c67139" />
            <path d="M12.25 21.9 18.4 28 29.6 15.8" fill="none" stroke="#f5ead8" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round" />
            <circle cx="39" cy="39" r="11" fill="#7a8a5e" stroke="#f5ead8" stroke-width="3" />
          </svg>
          <div class="min-w-0 leading-tight">
            <p class="font-display text-md text-fg">Daybook</p>
            <p class="truncate text-xs text-muted">{{ k("title") }}</p>
          </div>
        </div>
        <span class="flex-1" />
        <SegmentedControl v-model="theme" :options="themeOptions" size="sm" :aria-label="k('theme')" />
        <SegmentedControl v-model="density" :options="densityOptions" size="sm" :aria-label="t('shell.density.label')" />
        <SegmentedControl v-model="language" :options="languageOptions" size="sm" :aria-label="t('shell.topbar.language')" />
      </div>
    </header>

    <div class="mx-auto flex max-w-[1680px] gap-8 px-4 pb-24 pt-6 md:px-6">
      <nav class="sticky top-[72px] hidden max-h-[calc(100dvh-96px)] w-[184px] shrink-0 self-start overflow-y-auto lg:block" :aria-label="k('title')">
        <p class="mb-2 px-2 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ k("sections") }}</p>
        <a
          v-for="section in sections"
          :key="section"
          :href="`#${section}`"
          class="block rounded-[7px] px-2 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-highlight hover:text-fg"
          >{{ k(`section.${section}`) }}</a
        >
        <p class="mt-6 px-2 text-xs leading-5 text-subtle">{{ k("intro") }}</p>
      </nav>

      <main :class="['min-w-0 flex-1', theme === 'split' && 'grid gap-6 2xl:grid-cols-2']">
        <div class="@container flex min-w-0 flex-col gap-12">
          <component :is="group.component" v-for="group in groups" :key="group.id" />
        </div>
        <div v-if="theme === 'split'" data-theme="dark" class="@container flex min-w-0 flex-col gap-12 rounded-[18px] bg-canvas p-4 text-fg md:p-6">
          <component :is="group.component" v-for="group in groups" :key="group.id" />
        </div>
      </main>
    </div>
  </div>
</template>
