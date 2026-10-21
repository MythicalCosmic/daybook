<script setup lang="ts">
/** The root: the routed page, toasts and `useConfirm()` dialogs. (Tooltips need no provider: UiTooltip.) */
import { defineAsyncComponent, ref, watch } from "vue";
import { RouterView } from "vue-router";

import ToastHost from "@/components/ToastHost.vue";
import { confirmQueue } from "@/components/useConfirm";

// The dialog stack loads on the first confirmation, not with the shell.
const ConfirmHost = defineAsyncComponent(() => import("@/components/ConfirmHost.vue"));
const confirmMounted = ref(false);
watch(confirmQueue, (queue) => queue.length && (confirmMounted.value = true));
</script>

<template>
  <RouterView />
  <ToastHost />
  <ConfirmHost v-if="confirmMounted" />
</template>
