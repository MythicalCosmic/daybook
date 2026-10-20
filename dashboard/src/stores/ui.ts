/** Client-only UI state: sidebar, density, theme, open panels. */
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import { isBoolean, oneOf, readStored, writeStored } from "@/lib/storage";
import { useSessionStore } from "@/stores/session";

export type ThemeMode = "system" | "light" | "dark";
export type Theme = "light" | "dark";
export type Density = "comfortable" | "compact";

const isThemeMode = oneOf<ThemeMode>("system", "light", "dark");
const isDensity = oneOf<Density>("comfortable", "compact");

function systemTheme(): Theme {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export const useUiStore = defineStore("ui", () => {
  const session = useSessionStore();

  const sidebarCollapsed = ref(readStored("sidebarCollapsed", false, isBoolean));
  const themeMode = ref<ThemeMode>(readStored("theme", "system", isThemeMode));
  const system = ref<Theme>(systemTheme());
  /** Set by TelegramBridge inside Telegram: the console then follows Telegram's colors. */
  const telegramTheme = ref<Theme | null>(null);
  const density = ref<Density>("comfortable");

  const theme = computed<Theme>(() => {
    if (telegramTheme.value && themeMode.value === "system") return telegramTheme.value;
    return themeMode.value === "system" ? system.value : themeMode.value;
  });

  // Overlays the shell owns.
  const shortcutsOpen = ref(false);
  const aiPanelOpen = ref(false);
  const aiPrompt = ref("");
  const newCompanyOpen = ref(false);
  const moreOpen = ref(false);

  if (typeof window !== "undefined" && window.matchMedia) {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener?.("change", () => (system.value = media.matches ? "dark" : "light"));
  }

  // Density is remembered per person (plan §6.3), so it waits for `me`.
  const densityKey = computed(() => (session.me ? `density.${session.me.user.id}` : null));
  watch(
    densityKey,
    (key) => {
      density.value = key ? readStored(key, "comfortable", isDensity) : "comfortable";
    },
    { immediate: true },
  );

  function setSidebarCollapsed(value: boolean): void {
    sidebarCollapsed.value = value;
    writeStored("sidebarCollapsed", value);
  }

  function toggleSidebar(): void {
    setSidebarCollapsed(!sidebarCollapsed.value);
  }

  function setThemeMode(mode: ThemeMode): void {
    themeMode.value = mode;
    writeStored("theme", mode === "system" ? null : mode);
  }

  function setDensity(value: Density): void {
    density.value = value;
    if (densityKey.value) writeStored(densityKey.value, value);
  }

  function toggleDensity(): void {
    setDensity(density.value === "compact" ? "comfortable" : "compact");
  }

  function askAi(prompt = ""): void {
    aiPrompt.value = prompt;
    aiPanelOpen.value = true;
  }

  return {
    sidebarCollapsed,
    themeMode,
    theme,
    telegramTheme,
    density,
    shortcutsOpen,
    aiPanelOpen,
    aiPrompt,
    newCompanyOpen,
    moreOpen,
    setSidebarCollapsed,
    toggleSidebar,
    setThemeMode,
    setDensity,
    toggleDensity,
    askAi,
  };
});
