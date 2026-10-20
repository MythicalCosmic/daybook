<script setup lang="ts">
/** A signed-in person with no company to open yet: create one (when available) or ask for access. */
import { Building2, Plus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import UiButton from "@/components/UiButton.vue";
import { modules } from "@/core/modules";
import { useUiStore } from "@/stores/ui";

const { t } = useI18n();
const ui = useUiStore();
// Creating a company needs no company context, so any module that registered the dialog counts.
const canCreate = computed(() => modules.some((m) => m.extensions?.["shell.company.create"]?.length));
</script>

<template>
  <div class="grid min-h-[70vh] place-items-center">
    <EmptyState size="lg" :icon="Building2" :title="t('shell.company.none')" :description="t('shell.company.noneBody')">
      <UiButton v-if="canCreate" variant="primary" :icon="Plus" @click="ui.newCompanyOpen = true">{{ t("shell.company.new") }}</UiButton>
    </EmptyState>
  </div>
</template>
