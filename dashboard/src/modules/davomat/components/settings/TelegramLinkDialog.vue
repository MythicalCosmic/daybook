<script setup lang="ts">
/**
 * Ties a person's Telegram to their account (docs/DAVOMAT.md §1.5): a one-time link as a QR code
 * to scan with the phone camera, "Open in Telegram" on the same device, Copy, and the 24 hours it
 * stays valid. Once linked, the bot writes to them; Unlink stops it.
 */
import { Check, CircleCheck, Copy, RefreshCw, Send, Unlink } from "@lucide/vue";
import { computed, defineAsyncComponent, ref, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";

import type { TelegramLink } from "../../types";

const QrCode = defineAsyncComponent(() => import("@/components/QrCode.vue"));

const open = defineModel<boolean>("open", { default: false });

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    linked: boolean;
    create: () => Promise<TelegramLink>;
    unlink?: () => Promise<unknown>;
  }>(),
  { description: undefined, unlink: undefined },
);

const { t } = useI18n();
const fmt = useFormat();
const now = useNow();

const link = shallowRef<TelegramLink | null>(null);
const error = shallowRef<unknown>(null);
const loading = ref(false);
const unlinking = ref(false);
const copied = ref(false);

async function make(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    link.value = await props.create();
  } catch (failure) {
    error.value = failure;
  } finally {
    loading.value = false;
  }
}

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    copied.value = false;
    if (!props.linked && !link.value) void make();
  },
  { immediate: true },
);

const minutesLeft = computed(() => (link.value ? Math.max(0, Math.round((Date.parse(link.value.expires_at) - now.value) / 60_000)) : 0));
const expired = computed(() => !!link.value && minutesLeft.value <= 0);

async function copy(): Promise<void> {
  if (!link.value) return;
  try {
    await navigator.clipboard.writeText(link.value.url);
    copied.value = true;
    setTimeout(() => (copied.value = false), 2000);
  } catch {
    // No clipboard: the link is on the button and in the code.
  }
}

async function doUnlink(): Promise<void> {
  if (!props.unlink) return;
  unlinking.value = true;
  try {
    await props.unlink();
    link.value = null;
  } finally {
    unlinking.value = false;
  }
}

const notConfigured = computed(() => isApiError(error.value) && (error.value.status === 400 || error.value.status === 409 || error.value.status === 503));
</script>

<template>
  <UiDialog v-model:open="open" :title="title" :description="description" size="sm">
    <!-- Linked already -->
    <div v-if="linked" class="flex flex-col items-center py-4 text-center" data-linked>
      <span class="grid size-14 place-items-center rounded-full bg-success-soft text-success">
        <CircleCheck :size="28" />
      </span>
      <p class="mt-4 text-md font-semibold text-fg">{{ t("davomat.telegram.link.linkedTitle") }}</p>
      <p class="mt-1 max-w-[300px] text-balance text-sm text-muted">{{ t("davomat.telegram.link.linkedBody") }}</p>
      <UiButton v-if="unlink" class="mt-5" variant="ghost" :icon="Unlink" :loading="unlinking" data-unlink @click="doUnlink">{{ t("davomat.telegram.link.unlink") }}</UiButton>
    </div>

    <ErrorState
      v-else-if="error"
      compact
      :error="error"
      :title="notConfigured ? t('davomat.telegram.link.noBotTitle') : undefined"
      :description="notConfigured ? t('davomat.telegram.link.noBotBody') : undefined"
      :retry="make"
      :retrying="loading"
    />

    <!-- The code -->
    <div v-else class="flex flex-col items-center" data-link>
      <div class="relative mt-1">
        <QrCode v-if="link && !expired" :value="link.url" :size="196" level="M" />
        <div v-else class="grid size-[220px] place-items-center rounded-[14px] border border-line bg-surface-2">
          <SkeletonBlock v-if="loading || !link" width="196px" height="196px" radius="8px" />
          <div v-else class="flex flex-col items-center gap-3 px-6 text-center">
            <p class="text-sm text-muted">{{ t("davomat.telegram.link.expired") }}</p>
            <UiButton size="sm" :icon="RefreshCw" @click="make">{{ t("davomat.telegram.link.again") }}</UiButton>
          </div>
        </div>
        <span class="absolute -bottom-2 -right-2 grid size-9 place-items-center rounded-full border-[3px] border-surface bg-primary text-on-primary" aria-hidden="true">
          <Send :size="15" />
        </span>
      </div>

      <ol class="mt-6 flex w-full flex-col gap-2 text-sm text-muted">
        <li v-for="step in 3" :key="step" class="flex items-start gap-2.5">
          <span class="grid size-5 shrink-0 place-items-center rounded-full bg-accent-soft text-[11px] font-semibold tabular-nums text-accent-fg">{{ step }}</span>
          <span>{{ t(`davomat.telegram.link.step${step}`) }}</span>
        </li>
      </ol>

      <p v-if="link && !expired" class="mt-4 text-xs tabular-nums text-subtle" data-expires>{{ t("davomat.telegram.link.expires", { time: fmt.duration(minutesLeft) }) }}</p>
    </div>

    <template v-if="!linked && !error" #footer>
      <UiButton variant="ghost" :icon="copied ? Check : Copy" :disabled="!link || expired" data-copy @click="copy">
        {{ copied ? t("common.copied") : t("davomat.telegram.link.copy") }}
      </UiButton>
      <UiButton variant="primary" :icon="Send" :href="link && !expired ? link.url : undefined" target="_blank" :disabled="!link || expired">{{ t("davomat.telegram.link.open") }}</UiButton>
    </template>
  </UiDialog>
</template>
