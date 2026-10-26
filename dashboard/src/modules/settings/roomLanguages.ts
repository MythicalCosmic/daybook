/**
 * The languages a poster or the live screen speaks to a room: the company's language first, then
 * Russian (Uzbek, when the company speaks Russian). The dashboard loads a module's dictionary only
 * in the language on screen, so this loads the settings dictionary of both: without it the second
 * line would repeat the first in the fallback language.
 */
import { computed, ref, watch } from "vue";

import type { Language } from "@/api/types";
import { findModule } from "@/core/modules";
import { ensureModuleMessages, i18n } from "@/i18n";

export function roomLanguages(primary: Language): Language[] {
  return [primary, primary === "ru" ? "uz" : "ru"];
}

export function useRoomLanguages(primary: () => Language) {
  const languages = computed(() => roomLanguages(primary()));
  const loaded = ref(0);
  watch(
    languages,
    (list) => {
      const module = findModule("settings");
      if (!module) return;
      void Promise.allSettled(list.map((language) => ensureModuleMessages(module, language))).then(() => loaded.value++);
    },
    { immediate: true },
  );
  /** `key` in `language`, read again once that language's dictionary has arrived. */
  function say(key: string, language: Language): string {
    void loaded.value;
    return i18n.global.t(key, {}, { locale: language });
  }
  return { languages, say };
}
