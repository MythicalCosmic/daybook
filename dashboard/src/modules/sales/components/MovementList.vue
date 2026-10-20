<script setup lang="ts">
/**
 * Cash movements as a compact list: kind icon, what and why, who, when, the amount signed by its
 * direction (+ into the till, − out of it) and its state (a handover waiting for its receiver,
 * declined, void). A payout's receipt photo opens in the lightbox.
 */
import { Image } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ImageLightbox, { type LightboxImage } from "@/components/ImageLightbox.vue";
import MoneyText from "@/components/MoneyText.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import StatusPill from "@/components/StatusPill.vue";

import { MOVEMENT_ICONS, MOVEMENT_TONES, movementSign } from "../format";
import type { Movement } from "../types";

const props = withDefaults(defineProps<{ movements: Movement[]; showShift?: boolean; dense?: boolean }>(), { showShift: false, dense: false });
const emit = defineEmits<{ select: [movement: Movement] }>();

const { t } = useI18n();
const photos = computed<LightboxImage[]>(() => props.movements.filter((m) => m.photo).map((m) => ({ src: m.photo!, caption: m.reason || t(`sales.movement.kind.${m.kind}`) })));
const open = ref(false);
const index = ref(0);
function showPhoto(movement: Movement): void {
  index.value = Math.max(0, photos.value.findIndex((photo) => photo.src === movement.photo));
  open.value = true;
}

function subject(movement: Movement): string {
  if (movement.kind === "handover" && movement.receiver) return t("sales.movement.to", { name: movement.receiver.name });
  if ((movement.kind === "to_bank" || movement.kind === "deposit") && movement.to_account) return movement.to_account.name;
  if (movement.kind === "payout" && movement.category) return movement.category.name;
  return "";
}
</script>

<template>
  <ul class="flex flex-col">
    <li
      v-for="movement in movements"
      :key="movement.id"
      :class="['flex items-center gap-3 border-b border-line last:border-b-0', dense ? 'py-2' : 'py-2.5', movement.status === 'void' && 'opacity-55']"
    >
      <span
        :class="[
          'grid size-8 shrink-0 place-items-center rounded-[9px]',
          movementSign(movement.kind) > 0 ? 'bg-success-soft text-success' : 'bg-accent-soft text-accent-fg',
        ]"
        aria-hidden="true"
      >
        <component :is="MOVEMENT_ICONS[movement.kind]" :size="15" />
      </span>
      <button type="button" class="min-w-0 flex-1 text-left" @click="emit('select', movement)">
        <p class="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-fg">
          <span class="truncate">{{ t(`sales.movement.kind.${movement.kind}`) }}</span>
          <span v-if="subject(movement)" class="truncate font-normal text-muted">· {{ subject(movement) }}</span>
        </p>
        <p class="truncate text-xs text-muted">
          {{ movement.created_by.name }} · <RelativeTime :value="movement.created_at" mode="short" />
          <template v-if="showShift && movement.shift"> · {{ movement.shift.code }}</template>
          <template v-if="movement.reason"> · {{ movement.reason }}</template>
        </p>
      </button>
      <button
        v-if="movement.photo"
        type="button"
        class="pressable grid size-7 shrink-0 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg"
        :aria-label="t('sales.movement.photo')"
        @click="showPhoto(movement)"
      >
        <Image :size="15" />
      </button>
      <StatusPill v-if="movement.status !== 'done'" size="sm" :tone="MOVEMENT_TONES[movement.status]" :label="t(`sales.movement.status.${movement.status}`)" />
      <span :class="['shrink-0 text-sm font-semibold tabular-nums', movementSign(movement.kind) > 0 ? 'text-success' : 'text-fg']">
        {{ movementSign(movement.kind) > 0 ? "+" : "−" }}<MoneyText :value="movement.amount" />
      </span>
    </li>
  </ul>
  <ImageLightbox v-model:open="open" v-model:index="index" :images="photos" />
</template>
