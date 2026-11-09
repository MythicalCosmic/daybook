<script setup lang="ts">
/**
 * The employee's Telegram: linked (they get their own arrivals and departures from the
 * organization's bot) or not, with a one-time link to give them as a QR code or a link to send
 * (24 hours, one use). Scanning it opens the bot; pressing Start links the account.
 */
import { Copy, ExternalLink, Link2Off, QrCode as QrIcon, Send } from "@lucide/vue";
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import InlineAlert from "@/components/InlineAlert.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { employeeTelegramLink, employeeTelegramUnlink, useRefresh } from "../../api";
import type { Employee, TelegramLink } from "../../types";

const QrCode = defineAsyncComponent(() => import("@/components/QrCode.vue"));

const props = defineProps<{ employee: Employee }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const canManage = useCan("members.manage");

const link = ref<TelegramLink | null>(null);
const busy = ref(false);
const problem = ref<string | null>(null);

watch(
  () => [props.employee.id, props.employee.telegram_linked] as const,
  () => {
    link.value = null;
    problem.value = null;
  },
);

const expires = computed(() => (link.value ? fmt.instant(link.value.expires_at, "short") : ""));

async function create(): Promise<void> {
  busy.value = true;
  problem.value = null;
  try {
    link.value = await employeeTelegramLink(company.currentId ?? 0, props.employee.id);
  } catch (error) {
    // Most often: the organization's bot isn't connected yet (Settings › Telegram).
    problem.value = isApiError(error) && error.detail ? error.detail : t("davomat.employee.telegram.failed");
  } finally {
    busy.value = false;
  }
}

async function copy(): Promise<void> {
  if (!link.value) return;
  try {
    await navigator.clipboard.writeText(link.value.url);
    toast.success(t("davomat.employee.telegram.copied"));
  } catch {
    toast.error(t("davomat.employee.telegram.copyFailed"));
  }
}

async function unlink(): Promise<void> {
  const answer = await confirm({
    title: t("davomat.employee.telegram.unlinkTitle", { name: props.employee.full_name }),
    message: t("davomat.employee.telegram.unlinkBody"),
    confirmLabel: t("davomat.employee.telegram.unlink"),
    tone: "danger",
  });
  if (!answer) return;
  await employeeTelegramUnlink(company.currentId ?? 0, props.employee.id);
  toast.success(t("davomat.employee.telegram.unlinked"));
  refresh();
}
</script>

<template>
  <section class="ui-card flex flex-col gap-3 p-4" :aria-label="t('davomat.employee.telegram.title')" data-employee-telegram>
    <div class="flex items-start gap-3">
      <span :class="['grid size-10 shrink-0 place-items-center rounded-[12px]', employee.telegram_linked ? 'bg-success-soft text-success' : 'bg-info-soft text-info']">
        <Send :size="18" aria-hidden="true" />
      </span>
      <div class="min-w-0 flex-1">
        <h2 class="text-base font-semibold text-fg">{{ t("davomat.employee.telegram.title") }}</h2>
        <p class="mt-0.5 text-sm text-muted">
          {{ employee.telegram_linked ? t("davomat.employee.telegram.linkedBody") : t("davomat.employee.telegram.notLinkedBody") }}
        </p>
      </div>
    </div>

    <template v-if="employee.telegram_linked">
      <UiButton v-if="canManage" class="self-start" size="sm" variant="ghost" :icon="Link2Off" data-unlink @click="unlink">{{ t("davomat.employee.telegram.unlink") }}</UiButton>
    </template>

    <template v-else-if="link">
      <div class="flex flex-col items-center gap-3 rounded-[14px] border border-line bg-surface-2/50 p-4" data-telegram-qr>
        <QrCode :value="link.url" :size="176" level="M" :label="t('davomat.employee.telegram.qrLabel', { name: employee.full_name })" />
        <p class="max-w-[260px] text-balance text-center text-sm text-muted">{{ t("davomat.employee.telegram.scanHint") }}</p>
        <div class="flex flex-wrap justify-center gap-2">
          <UiButton size="sm" variant="secondary" :icon="Copy" @click="copy">{{ t("davomat.employee.telegram.copy") }}</UiButton>
          <UiButton size="sm" variant="secondary" :icon="ExternalLink" :href="link.url" target="_blank">{{ t("davomat.employee.telegram.open") }}</UiButton>
        </div>
        <p class="text-xs tabular-nums text-subtle">{{ t("davomat.employee.telegram.expires", { time: expires }) }}</p>
      </div>
    </template>

    <template v-else>
      <InlineAlert v-if="problem" tone="warning" size="sm" :description="problem" />
      <UiButton v-if="canManage" class="self-start" size="sm" variant="primary" :icon="QrIcon" :loading="busy" data-create-link @click="create">{{ t("davomat.employee.telegram.create") }}</UiButton>
    </template>
  </section>
</template>
