<script setup lang="ts">
/**
 * Shows only when live updates stall: "Reconnecting…" after failed pulses, "Offline" when the
 * browser is offline. Clicking retries. `state` overrides the live value (component gallery).
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { connection, type ConnectionState } from "@/core/pulse";

const props = withDefaults(defineProps<{ state?: ConnectionState; compact?: boolean }>(), { state: undefined, compact: false });
const emit = defineEmits<{ retry: [] }>();

const { t } = useI18n();
const current = computed(() => props.state ?? connection.value);
</script>

<template>
  <Transition name="fade">
    <button
      v-if="current !== 'online'"
      type="button"
      :class="[
        'pressable inline-flex h-7 shrink-0 items-center gap-2 rounded-full px-2.5 text-xs font-semibold',
        current === 'offline' ? 'bg-danger-soft text-danger' : 'bg-warning-soft text-warning',
      ]"
      :title="t('shell.connection.retry')"
      @click="emit('retry')"
    >
      <span class="conn-dot size-2 rounded-full bg-current" aria-hidden="true" />
      <span v-if="!compact">{{ current === "offline" ? t("shell.connection.offline") : t("shell.connection.reconnecting") }}</span>
      <span v-else class="sr-only">{{ current === "offline" ? t("shell.connection.offline") : t("shell.connection.reconnecting") }}</span>
    </button>
  </Transition>
</template>

<style scoped>
.conn-dot {
  animation: breathe 1.6s var(--ease-standard) infinite;
}
</style>
