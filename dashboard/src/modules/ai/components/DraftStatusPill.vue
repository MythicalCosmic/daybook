<script setup lang="ts">
/** A voice note's state in a word: working (live), to check, created, didn't work, discarded, expired. */
import { useI18n } from "vue-i18n";

import StatusPill from "@/components/StatusPill.vue";

import { DRAFT_TONE, isWorking } from "../lib";
import type { DraftStatus } from "../types";

withDefaults(defineProps<{ status: DraftStatus; size?: "sm" | "md" }>(), { size: "md" });
const { t } = useI18n();
</script>

<template>
  <StatusPill :tone="DRAFT_TONE[status]" :size="size" dot :live="isWorking(status)" :label="t(`ai.status.${status}`)" :data-status="status" />
</template>
