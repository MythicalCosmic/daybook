<script setup lang="ts">
/**
 * A photo of what is given or handed back: taken with the camera on a phone or tablet, chosen or
 * dropped on a computer. Shows the photo once there is one, with a way to take another or remove
 * it. Only pictures; the server re-encodes them (nothing of the original file is kept).
 */
import { Camera, ImagePlus, X } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

const photo = defineModel<File | null>({ default: null });
withDefaults(defineProps<{ id?: string }>(), { id: undefined });

const { t } = useI18n();
const MAX_BYTES = 15 * 1024 * 1024;
const camera = ref<HTMLInputElement | null>(null);
const picker = ref<HTMLInputElement | null>(null);
const over = ref(false);
const error = ref<string | null>(null);

const url = ref<string | null>(null);
watch(
  photo,
  (file) => {
    if (url.value) URL.revokeObjectURL(url.value);
    url.value = file && typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : null;
  },
  { immediate: true },
);
onBeforeUnmount(() => url.value && URL.revokeObjectURL(url.value));

function take(file: File | undefined | null): void {
  error.value = null;
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    error.value = t("lifecycle.equipment.photo.notImage");
    return;
  }
  if (file.size > MAX_BYTES) {
    error.value = t("lifecycle.equipment.photo.tooLarge");
    return;
  }
  photo.value = file;
}
function onInput(event: Event): void {
  const input = event.target as HTMLInputElement;
  take(input.files?.[0]);
  input.value = "";
}
function onDrop(event: DragEvent): void {
  over.value = false;
  take(event.dataTransfer?.files?.[0]);
}
const sizeLabel = computed(() => (photo.value ? `${Math.max(1, Math.round(photo.value.size / 1024))} KB` : ""));
</script>

<template>
  <div class="flex flex-col gap-1.5" data-photo-field>
    <input ref="camera" type="file" accept="image/*" capture="environment" class="sr-only" tabindex="-1" aria-hidden="true" @change="onInput" />
    <input ref="picker" :id="id" type="file" accept="image/*" class="sr-only" tabindex="-1" aria-hidden="true" data-photo-input @change="onInput" />
    <div v-if="photo" class="flex items-center gap-3 rounded-[12px] border border-line bg-surface-2/50 p-2 dark:bg-surface-3/40">
      <img v-if="url" :src="url" alt="" class="size-16 shrink-0 rounded-[9px] object-cover" data-photo-preview />
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium text-fg">{{ t("lifecycle.equipment.photo.ready") }}</p>
        <p class="truncate text-xs text-muted">{{ photo.name }} · {{ sizeLabel }}</p>
        <button type="button" class="mt-1 text-xs font-semibold text-primary hover:underline" @click="camera?.click()">{{ t("lifecycle.equipment.photo.again") }}</button>
      </div>
      <button type="button" class="grid size-8 shrink-0 place-items-center rounded-[8px] text-muted hover:bg-surface-3/70 hover:text-fg" :aria-label="t('lifecycle.equipment.photo.remove')" data-photo-remove @click="photo = null">
        <X :size="15" />
      </button>
    </div>
    <div
      v-else
      :class="[
        'flex flex-col items-center justify-center gap-2 rounded-[12px] border border-dashed px-4 py-4 text-center transition-colors',
        over ? 'border-[var(--c-primary)] bg-accent-soft' : 'border-line-strong bg-surface-2/30 dark:bg-surface-3/20',
      ]"
      @dragover.prevent="over = true"
      @dragleave="over = false"
      @drop.prevent="onDrop"
    >
      <div class="flex flex-wrap items-center justify-center gap-2">
        <button type="button" class="inline-flex items-center gap-1.5 rounded-[9px] bg-surface px-3 py-1.5 text-sm font-semibold text-fg shadow-[var(--sh-xs)] ring-1 ring-line hover:ring-line-strong" data-photo-take @click="camera?.click()">
          <Camera :size="15" class="text-primary" aria-hidden="true" />{{ t("lifecycle.equipment.photo.take") }}
        </button>
        <button type="button" class="inline-flex items-center gap-1.5 rounded-[9px] px-3 py-1.5 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg" data-photo-pick @click="picker?.click()">
          <ImagePlus :size="15" aria-hidden="true" />{{ t("lifecycle.equipment.photo.pick") }}
        </button>
      </div>
      <p class="text-xs text-subtle">{{ t("lifecycle.equipment.photo.hint") }}</p>
    </div>
    <p v-if="error" class="text-xs text-danger" role="alert">{{ error }}</p>
  </div>
</template>
