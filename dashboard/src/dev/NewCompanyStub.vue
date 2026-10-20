<script setup lang="ts">
/** Dev-only stand-in for package A's "New company" dialog body (extension `shell.company.create`). */
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";

const props = defineProps<{ context: Record<string, unknown> }>();
const { t } = useI18n();
const name = ref("");

function close(): void {
  const fn = props.context.close;
  if (typeof fn === "function") (fn as () => void)();
}
</script>

<template>
  <form class="flex flex-col gap-4" @submit.prevent="close">
    <label class="flex flex-col gap-1.5">
      <span class="text-sm font-medium text-fg">{{ t("dev.newCompany.name") }}</span>
      <input
        v-model="name"
        class="h-9 rounded-input border border-line bg-surface px-3 text-base outline-none focus:border-primary focus:shadow-[0_0_0_3px_var(--c-accent-soft)]"
        :placeholder="t('dev.newCompany.placeholder')"
      />
    </label>
    <p class="rounded-[8px] bg-surface-2 px-3 py-2 text-sm text-muted">{{ t("dev.newCompany.note") }}</p>
    <div class="flex justify-end gap-2">
      <UiButton variant="ghost" @click="close">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit">{{ t("common.create") }}</UiButton>
    </div>
  </form>
</template>
