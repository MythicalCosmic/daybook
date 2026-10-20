<script setup lang="ts">
/**
 * Something failed to load. Explains it in plain words (network, permission, gone, server) and
 * offers "Try again" when `retry` is given. `compact` is a one-line version for widgets.
 */
import { CloudOff, Lock, SearchX, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";

import UiButton from "./UiButton.vue";

const props = withDefaults(
  defineProps<{
    error?: unknown;
    title?: string;
    description?: string;
    retry?: () => unknown;
    retrying?: boolean;
    compact?: boolean;
  }>(),
  { error: undefined, title: undefined, description: undefined, retry: undefined, retrying: false, compact: false },
);

const { t } = useI18n();

const kind = computed(() => {
  if (!isApiError(props.error)) return "generic" as const;
  if (props.error.isNetwork) return "network" as const;
  if (props.error.status === 403) return "forbidden" as const;
  if (props.error.status === 404) return "notFound" as const;
  if (props.error.status >= 500) return "server" as const;
  return "generic" as const;
});

const icon = computed(() => ({ network: CloudOff, forbidden: Lock, notFound: SearchX, server: TriangleAlert, generic: TriangleAlert })[kind.value]);

const message = computed(() => {
  if (props.description) return props.description;
  if (isApiError(props.error) && props.error.detail && kind.value === "generic") return props.error.detail;
  return t(`common.error.${kind.value}`);
});
</script>

<template>
  <div
    v-if="compact"
    role="alert"
    class="flex items-center gap-3 rounded-card border border-line bg-surface px-3 py-2.5 text-sm"
  >
    <component :is="icon" :size="16" class="text-danger" aria-hidden="true" />
    <span class="min-w-0 flex-1 truncate text-muted">{{ title ?? message }}</span>
    <UiButton v-if="retry" size="sm" variant="ghost" :loading="retrying" @click="retry()">{{ t("common.retry") }}</UiButton>
  </div>
  <div v-else role="alert" class="flex flex-col items-center gap-3 px-6 py-12 text-center">
    <div class="grid size-12 place-items-center rounded-full bg-danger-soft text-danger" aria-hidden="true">
      <component :is="icon" :size="22" />
    </div>
    <h3 class="text-md font-semibold text-fg">{{ title ?? t("common.error.title") }}</h3>
    <p class="max-w-[380px] text-base text-muted">{{ message }}</p>
    <UiButton v-if="retry" class="mt-1" :loading="retrying" @click="retry()">{{ t("common.retry") }}</UiButton>
  </div>
</template>
