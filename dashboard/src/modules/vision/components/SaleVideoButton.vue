<script setup lang="ts">
/**
 * Sales › Receipts, beside Void (`sales.entry.actions`): the till's camera at the moment of the
 * sale, as a video receipt (docs/KOZ.md §6.6, `POST clips/ {sale_id}`). Shown only with the Ko‘z
 * module on (the slot checks it) and `vision.video`.
 */
import { Play } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import IconButton from "@/components/IconButton.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import type { ClipRequest } from "../types";
import ClipPlayer from "./ClipPlayer.vue";

const props = defineProps<{ context: { entry?: { id: number; number?: string; total?: string } } }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const entry = computed(() => props.context.entry ?? null);
const allowed = computed(() => !!entry.value && company.can("vision.video"));
const request = ref<ClipRequest | null>(null);
const open = computed({ get: () => request.value !== null, set: (value: boolean) => (request.value = value ? request.value : null) });
const label = computed(() => t("vision.sale.video", { n: entry.value?.number || entry.value?.id || "" }));
</script>

<template>
  <template v-if="allowed && entry">
    <IconButton :icon="Play" :label="label" size="sm" data-sale-video @click.stop="request = { sale_id: entry.id }" />
    <ClipPlayer v-model:open="open" :request="request" :context="entry.total ? `${label} · ${fmt.money(entry.total)}` : label" />
  </template>
</template>
