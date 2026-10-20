<script setup lang="ts">
/** The root: tooltips provider, the routed page, toasts and `useConfirm()` dialogs. */
import { TooltipProvider } from "reka-ui";
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
  <TooltipProvider :delay-duration="450" :skip-delay-duration="250">
    <RouterView />
    <ToastHost />
    <ConfirmHost v-if="confirmMounted" />
  </TooltipProvider>
</template>
