/** `lib.ts`'s run words bound to the page: the language, the company's zone and a ticking clock. */
import { computed, type ComputedRef } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";

import type { RunWords } from "./lib";

export function useRunWords(): ComputedRef<RunWords> {
  const { t } = useI18n();
  const fmt = useFormat();
  const company = useCompanyStore();
  const now = useNow();
  return computed(() => ({
    t,
    timeZone: company.timezone,
    now: now.value,
    time: (iso: string) => fmt.instant(iso, "time"),
    day: (day: string) => fmt.day(day, "short"),
  }));
}
