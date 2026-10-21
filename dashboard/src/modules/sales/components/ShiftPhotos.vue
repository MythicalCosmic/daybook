<script setup lang="ts">
/**
 * The Z-report and the terminal slip side by side with what the cashier typed and, when AI read
 * the photos (package K), what it saw: numbers that don't match are highlighted. Photos open in
 * the lightbox; links are short-lived signed URLs, checked again at download.
 */
import { ImageOff, ScanLine, Sparkles } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ImageLightbox, { type LightboxImage } from "@/components/ImageLightbox.vue";
import MoneyText from "@/components/MoneyText.vue";
import UiBadge from "@/components/UiBadge.vue";
import { compare, sum } from "@/lib/decimal";

import type { ShiftDetail } from "../types";

const props = defineProps<{ shift: ShiftDetail }>();
const { t } = useI18n();

const photos = computed(() =>
  [
    { key: "z", src: props.shift.z_photo, label: t("sales.photos.z"), hint: props.shift.z_number ? t("sales.photos.zNumber", { n: props.shift.z_number }) : "" },
    { key: "terminal", src: props.shift.terminal_photo, label: t("sales.photos.terminal"), hint: "" },
  ].filter((photo) => photo.src || photo.key === "z"),
);
const images = computed<LightboxImage[]>(() => photos.value.filter((p) => p.src).map((p) => ({ src: p.src!, alt: p.label, caption: p.label })));
const open = ref(false);
const index = ref(0);
function show(src: string): void {
  index.value = Math.max(0, images.value.findIndex((image) => image.src === src));
  open.value = true;
}

/** What the cashier typed: the fiscal totals, else the cash and non-cash method totals. */
const typedCash = computed(() => props.shift.fiscal_cash_total ?? sum(props.shift.payments.filter((p) => p.method.kind === "cash").map((p) => p.net)));
const typedCard = computed(
  () => props.shift.fiscal_card_total ?? sum(props.shift.payments.filter((p) => p.method.kind !== "cash" && p.method.kind !== "credit").map((p) => p.net)),
);
const reading = computed(() => props.shift.ai_reading ?? {});
const hasReading = computed(() => Object.keys(reading.value).length > 0);
const rows = computed(() => [
  { key: "cash", label: t("sales.photos.cashTotal"), typed: typedCash.value, read: reading.value.cash_total ?? null },
  { key: "card", label: t("sales.photos.cardTotal"), typed: typedCard.value, read: reading.value.card_total ?? null },
]);
const differs = (typed: string, read: string | null) => read !== null && read !== undefined && compare(typed, read) !== 0;
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="grid grid-cols-2 gap-3">
      <figure v-for="photo in photos" :key="photo.key" class="min-w-0">
        <button
          v-if="photo.src"
          type="button"
          class="pressable group relative block aspect-[3/4] w-full overflow-hidden rounded-[12px] border border-line bg-surface-2"
          :aria-label="t('sales.photos.open', { name: photo.label })"
          @click="show(photo.src)"
        >
          <img :src="photo.src" :alt="photo.label" class="size-full object-contain object-top transition-transform duration-200 group-hover:scale-[1.02]" loading="lazy" />
          <span class="absolute inset-x-2 bottom-2 rounded-[8px] bg-surface/90 px-2 py-1 text-left text-xs font-semibold text-fg shadow-xs backdrop-blur">
            {{ photo.label }}<span v-if="photo.hint" class="font-normal text-muted"> · {{ photo.hint }}</span>
          </span>
        </button>
        <div v-else class="grid aspect-[3/4] w-full place-items-center rounded-[12px] border border-dashed border-line-strong bg-surface-2/50 text-center">
          <div class="flex flex-col items-center gap-1.5 px-3 text-xs text-muted">
            <ImageOff :size="18" class="text-subtle" aria-hidden="true" />{{ t("sales.photos.missing", { name: photo.label }) }}
          </div>
        </div>
      </figure>
    </div>

    <div class="rounded-[12px] border border-line">
      <div class="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <ScanLine :size="15" class="text-subtle" aria-hidden="true" />
        <h4 class="flex-1 text-sm font-semibold text-fg">{{ t("sales.photos.check") }}</h4>
        <UiBadge v-if="shift.ai_mismatch" tone="danger" size="sm"><Sparkles :size="12" class="mr-1 inline" />{{ t("sales.photos.mismatch") }}</UiBadge>
        <UiBadge v-else-if="hasReading" tone="success" size="sm"><Sparkles :size="12" class="mr-1 inline" />{{ t("sales.photos.match") }}</UiBadge>
      </div>
      <table class="w-full text-sm tabular-nums">
        <thead>
          <tr class="text-xs text-muted">
            <th class="px-4 py-2 text-left font-medium">{{ t("sales.photos.what") }}</th>
            <th class="px-3 py-2 text-right font-medium">{{ t("sales.photos.typed") }}</th>
            <th class="px-4 py-2 text-right font-medium">{{ t("sales.photos.read") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key" class="border-t border-line">
            <td class="px-4 py-2 text-fg">{{ row.label }}</td>
            <td class="px-3 py-2 text-right text-fg"><MoneyText :value="row.typed" /></td>
            <td :class="['px-4 py-2 text-right', differs(row.typed, row.read) ? 'font-semibold text-danger' : 'text-muted']">
              <MoneyText v-if="row.read" :value="row.read" /><span v-else class="text-subtle">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="reading.notes" class="border-t border-line px-4 py-2.5 text-xs text-muted">{{ reading.notes }}</p>
      <p v-else-if="!hasReading" class="border-t border-line px-4 py-2.5 text-xs text-subtle">{{ t("sales.photos.noReading") }}</p>
    </div>
    <ImageLightbox v-model:open="open" v-model:index="index" :images="images" :title="shift.code" />
  </div>
</template>
