<script setup lang="ts">
/**
 * A terminal pointed at Daybook for the first time uploads everything it ever stored, oldest
 * first; those scans are skipped, only counted. This says so: while they still come (live scans
 * start after them), once they stopped (a quiet line), or, instead, that the terminal's clock is
 * so far behind that its live scans look old too.
 */
import { History, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

import type { DeviceHistory } from "../types";

const props = defineProps<{ history: DeviceHistory }>();

const { t } = useI18n();
const fmt = useFormat();
const counts = computed(() => ({
  n: fmt.number(props.history.skipped),
  date: props.history.until ? fmt.instant(props.history.until, "date") : "—",
}));
</script>

<template>
  <p v-if="history.clock_hides" class="flex items-start gap-2 rounded-[10px] bg-warning-soft px-3 py-2 text-left text-sm text-warning" role="status">
    <TriangleAlert :size="15" class="mt-0.5 shrink-0" aria-hidden="true" />
    <span>{{ t("faceid.history.clockHides") }}</span>
  </p>
  <div v-else-if="history.active" class="flex items-start gap-2 rounded-[10px] bg-info-soft px-3 py-2 text-left text-sm text-info" role="status">
    <History :size="15" class="mt-0.5 shrink-0" aria-hidden="true" />
    <span class="min-w-0">
      <span class="block">{{ t("faceid.history.sending") }}</span>
      <span class="mt-0.5 block text-xs tabular-nums opacity-85">{{ t("faceid.history.skipped", counts) }}</span>
    </span>
  </div>
  <p v-else-if="history.skipped" class="flex items-start gap-2 text-left text-xs text-subtle">
    <History :size="13" class="mt-px shrink-0" aria-hidden="true" />
    <span class="tabular-nums">{{ t("faceid.history.done", counts) }}</span>
  </p>
</template>
