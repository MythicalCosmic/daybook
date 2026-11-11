<script setup lang="ts">
/**
 * "Hisobot tayyorlash": opens the dialog that prepares the PDF for a bank, a partner or a buyer
 * (v12). Shown to those with finance.view and data.export, while finance is on. Also mounted on
 * Egasi paneli through the `cockpit.header.actions` extension point (it receives `context`).
 */
import { FileText } from "@lucide/vue";
import { computed, defineAsyncComponent, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

const PrepareReportDialog = defineAsyncComponent(() => import("./PrepareReportDialog.vue"));

const props = withDefaults(
  defineProps<{ size?: "sm" | "md"; variant?: "primary" | "secondary"; context?: Record<string, unknown>; autoOpen?: boolean }>(),
  { size: "md", variant: "secondary", context: () => ({}), autoOpen: false },
);
const emit = defineEmits<{ opened: [] }>();

const { t } = useI18n();
const company = useCompanyStore();
const open = ref(false);
// Mounted on first use and kept, so closing plays its animation and a report being prepared
// keeps going (it downloads when ready) after "Hide".
const mounted = ref(false);
function show(): void {
  mounted.value = true;
  open.value = true;
}
const visible = computed(() => company.enabled("finance") && company.can("finance.view") && company.can("data.export"));
// The palette's "Prepare a report for a bank" lands with ?prepare=1.
onMounted(() => {
  if (props.autoOpen && visible.value) {
    show();
    emit("opened");
  }
});
</script>

<template>
  <template v-if="visible">
    <UiButton :size="size" :variant="variant" :icon="FileText" data-prepare-report @click="show">{{ t("finance.pack.button") }}</UiButton>
    <PrepareReportDialog v-if="mounted" v-model:open="open" />
  </template>
</template>
