<script setup lang="ts">
/** The phone's "More" tab: every section the person can open, plus theme, language and log out. */
import { LogOut, Monitor, Moon, Sun } from "@lucide/vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import { changeLanguage } from "@/app/providers";
import { switchTheme } from "@/app/theme";
import { LANGUAGES } from "@/api/types";
import BottomSheet from "@/components/BottomSheet.vue";
import UiBadge from "@/components/UiBadge.vue";
import { isActivePath, type NavGroup } from "@/core/nav";
import { useUiStore, type ThemeMode } from "@/stores/ui";

const open = defineModel<boolean>("open", { default: false });
defineProps<{ groups: NavGroup[] }>();
const emit = defineEmits<{ signOut: [] }>();

const { t, locale } = useI18n();
const route = useRoute();
const ui = useUiStore();

const themes: Array<{ value: ThemeMode; icon: typeof Sun }> = [
  { value: "light", icon: Sun },
  { value: "dark", icon: Moon },
  { value: "system", icon: Monitor },
];

function close(): void {
  open.value = false;
}
</script>

<template>
  <BottomSheet v-model:open="open" :title="t('shell.tabs.more')" hide-header tall>
    <div class="flex flex-col gap-5 pb-2 pt-1">
      <section v-for="group in groups" :key="group.id">
        <h2 class="mb-1.5 px-1 text-xs font-medium text-subtle">{{ t(`shell.group.${group.id}`) }}</h2>
        <ul class="overflow-hidden rounded-card border border-line bg-surface">
          <li v-for="(module, index) in group.modules" :key="module.key" :class="index > 0 && 'border-t border-line'">
            <RouterLink
              :to="module.path"
              class="flex h-12 items-center gap-3 px-3.5 active:bg-highlight"
              :class="[module, ...module.children].some((e) => isActivePath(e, route.path)) && 'text-primary'"
              @click="close"
            >
              <component :is="module.icon" :size="19" class="text-muted" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate text-md font-medium text-fg">{{ t(module.title) }}</span>
              <UiBadge v-if="module.badge" :count="module.badge" tone="primary" />
            </RouterLink>
            <!-- Pages wrap onto more lines rather than running off the edge; each chip is a 44 px target (36 px plus 4 px above and below). -->
            <div v-if="module.children.length > 1" class="-mt-1 flex flex-wrap gap-2 px-3.5 pb-3 pl-[46px]">
              <RouterLink
                v-for="child in module.children.slice(1)"
                :key="child.key"
                :to="child.path"
                class="relative flex h-9 items-center gap-1.5 rounded-full border border-line px-3 text-sm font-medium text-muted after:absolute after:inset-x-0 after:-inset-y-1 after:content-[''] active:bg-highlight"
                @click="close"
              >
                {{ t(child.title) }}
                <UiBadge v-if="child.badge" :count="child.badge" />
              </RouterLink>
            </div>
          </li>
        </ul>
      </section>

      <section class="flex flex-col gap-3">
        <h2 class="px-1 text-xs font-medium text-subtle">{{ t("shell.user.appearance") }}</h2>
        <div class="grid grid-cols-3 gap-1 rounded-[12px] bg-surface-2 p-1" role="radiogroup" :aria-label="t('shell.topbar.theme')">
          <button
            v-for="theme in themes"
            :key="theme.value"
            type="button"
            role="radio"
            :aria-checked="ui.themeMode === theme.value"
            :class="['flex h-9 items-center justify-center gap-1.5 rounded-[9px] text-sm font-semibold', ui.themeMode === theme.value ? 'bg-surface text-fg shadow-raised' : 'text-muted']"
            @click="switchTheme(theme.value)"
          >
            <component :is="theme.icon" :size="15" />
            {{ t(`shell.theme.${theme.value}`) }}
          </button>
        </div>
        <div class="grid grid-cols-3 gap-1 rounded-[12px] bg-surface-2 p-1" role="radiogroup" :aria-label="t('shell.topbar.language')">
          <button
            v-for="language in LANGUAGES"
            :key="language"
            type="button"
            role="radio"
            :aria-checked="locale === language"
            :class="['h-9 rounded-[9px] text-sm font-semibold', locale === language ? 'bg-surface text-fg shadow-raised' : 'text-muted']"
            @click="changeLanguage(language)"
          >
            {{ t(`shell.language.${language}`) }}
          </button>
        </div>
        <button
          type="button"
          class="mt-1 flex h-11 items-center justify-center gap-2 rounded-[12px] border border-line text-base font-semibold text-danger active:bg-danger-soft"
          @click="emit('signOut')"
        >
          <LogOut :size="17" />
          {{ t("shell.user.signOut") }}
        </button>
      </section>
    </div>
  </BottomSheet>
</template>
