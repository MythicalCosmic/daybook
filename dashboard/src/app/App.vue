<script setup lang="ts">
/** The root: tooltips provider, the routed page, toasts and `useConfirm()` dialogs. */
import { TooltipProvider } from "reka-ui";
import { RouterView } from "vue-router";

import ConfirmHost from "@/components/ConfirmHost.vue";
import ToastHost from "@/components/ToastHost.vue";
</script>

<template>
  <TooltipProvider :delay-duration="450" :skip-delay-duration="250">
    <RouterView />
    <ToastHost />
    <ConfirmHost />
  </TooltipProvider>
</template>
