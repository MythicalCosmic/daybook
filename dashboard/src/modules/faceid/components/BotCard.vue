<script setup lang="ts">
/**
 * Face ID › Settings › Telegram bot: the company's own Face ID bot. With it connected, everything
 * Face ID sends to Telegram (who came with the snapshot, unknown faces, the person's own check-in,
 * group posts where the bot was added) goes through it; without it, the usual bots send. The token
 * is pasted once (checked with Telegram, kept encrypted, never shown again). Telegram lets a bot
 * write only to people who pressed Start in it: the card lists who still has to, with the link
 * and its QR code to share.
 */
import { AlertTriangle, CircleCheck, Copy, ExternalLink, MessageCircleQuestion, RefreshCw, Send, Unplug } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageSection from "@/components/PageSection.vue";
import QrCode from "@/components/QrCode.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { faceKeys, removeBot, saveBotToken, testBot, useBot } from "../api";
import type { FaceIdBot } from "../types";

const { t } = useI18n();
const client = useQueryClient();
const cid = useCompanyId();
const query = useBot();
const bot = computed(() => query.data.value ?? null);
const status = computed(() => bot.value?.status ?? "not_set");
const statusKey = computed(() => (status.value === "ok" ? "ok" : status.value === "invalid" ? "invalid" : "notSet"));

const replacing = ref(false);
const showForm = computed(() => status.value !== "ok" || replacing.value);
const token = ref("");
const tokenError = ref<string | null>(null);
const saving = ref(false);

async function save(): Promise<void> {
  const value = token.value.trim();
  if (!value) {
    tokenError.value = t("faceid.bot.token.required");
    return;
  }
  saving.value = true;
  tokenError.value = null;
  try {
    const saved = await saveBotToken(cid.value, value);
    client.setQueryData<FaceIdBot>(faceKeys.bot(cid.value), saved);
    token.value = "";
    replacing.value = false;
    toast.success(t("faceid.bot.token.saved", { name: saved.bot_username ? `@${saved.bot_username}` : "" }));
  } catch (error) {
    if (isApiError(error) && error.status === 400) {
      tokenError.value = error.fieldErrors.token?.[0] ?? error.detail ?? t("faceid.bot.token.refused");
    }
  } finally {
    saving.value = false;
  }
}

const confirm = useConfirm();
const removing = ref(false);
async function remove(): Promise<void> {
  const answer = await confirm({
    title: t("faceid.bot.remove.title"),
    message: t("faceid.bot.remove.body"),
    confirmLabel: t("faceid.bot.remove.confirm"),
    tone: "danger",
    icon: Unplug,
  });
  if (!answer) return;
  removing.value = true;
  try {
    await removeBot(cid.value);
    client.setQueryData<FaceIdBot>(faceKeys.bot(cid.value), { configured: false, bot_username: null, bot_name: null, status: "not_set", checked_at: null, start_url: null, started: 0, pending: [] });
    replacing.value = false;
    testResult.value = null;
    toast.success(t("faceid.bot.remove.done"));
  } catch {
    // The HTTP layer toasted the refusal.
  } finally {
    removing.value = false;
  }
}

const testing = ref(false);
const testResult = ref<{ tone: "success" | "warning"; text: string } | null>(null);
async function sendTest(): Promise<void> {
  testing.value = true;
  testResult.value = null;
  try {
    await testBot(cid.value);
    testResult.value = { tone: "success", text: t("faceid.bot.test.sent") };
  } catch (error) {
    if (isApiError(error) && error.status === 400) testResult.value = { tone: "warning", text: error.detail ?? t("faceid.bot.test.failed") };
  } finally {
    testing.value = false;
    void query.refetch();
  }
}

async function copyLink(): Promise<void> {
  const link = bot.value?.start_url;
  if (!link) return;
  try {
    await navigator.clipboard.writeText(link);
    toast.success(t("faceid.bot.start.copied"));
  } catch {
    toast.error(t("faceid.bot.start.copyFailed"));
  }
}
</script>

<template>
  <PageSection variant="card" :heading-level="2" :title="t('faceid.bot.title')" :description="t('faceid.bot.hint')" data-bot-card>
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="!bot" class="flex items-center gap-4" aria-busy="true">
      <SkeletonBlock circle width="44px" height="44px" />
      <div class="flex flex-1 flex-col gap-2">
        <SkeletonBlock width="40%" height="14px" />
        <SkeletonBlock width="64%" />
      </div>
    </div>
    <div v-else class="flex flex-col gap-5" :data-status="status">
      <div class="flex flex-wrap items-start gap-4">
        <span :class="['grid size-11 shrink-0 place-items-center rounded-full', status === 'ok' ? 'bg-info-soft text-info' : status === 'invalid' ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted']">
          <AlertTriangle v-if="status === 'invalid'" :size="20" />
          <Send v-else :size="18" />
        </span>
        <div class="min-w-[min(100%,220px)] flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="text-base font-semibold text-fg">{{ status === "ok" ? bot.bot_name || t("faceid.bot.status.ok.title") : t(`faceid.bot.status.${statusKey}.title`) }}</h3>
            <StatusPill :tone="status === 'ok' ? 'success' : status === 'invalid' ? 'danger' : 'neutral'" :label="t(`faceid.bot.status.${statusKey}.pill`)" size="sm" />
          </div>
          <p v-if="bot.bot_username" class="mt-0.5 font-mono text-sm text-muted" data-username>@{{ bot.bot_username }}</p>
          <p class="mt-1 max-w-[560px] text-sm text-muted">{{ t(`faceid.bot.status.${statusKey}.body`) }}</p>
        </div>
        <div v-if="status === 'ok'" class="flex flex-wrap gap-2">
          <UiButton variant="secondary" :icon="MessageCircleQuestion" :loading="testing" data-send-test @click="sendTest">{{ t("faceid.bot.test.action") }}</UiButton>
          <UiButton v-if="!replacing" variant="ghost" :icon="RefreshCw" data-replace @click="replacing = true">{{ t("faceid.bot.token.replace") }}</UiButton>
          <UiButton variant="ghost" :icon="Unplug" :loading="removing" data-remove @click="remove">{{ t("faceid.bot.remove.action") }}</UiButton>
        </div>
      </div>

      <InlineAlert v-if="testResult" :tone="testResult.tone" size="sm" :description="testResult.text" data-test-result />

      <form v-if="showForm" class="flex flex-col gap-3 border-t border-line pt-4" novalidate data-token-form @submit.prevent="save">
        <ol class="flex list-decimal flex-col gap-1 pl-5 text-sm text-muted">
          <li>{{ t("faceid.bot.steps.one") }}</li>
          <li>{{ t("faceid.bot.steps.two") }}</li>
          <li>{{ t("faceid.bot.steps.three") }}</li>
        </ol>
        <FormField :label="t('faceid.bot.token.label')" :error="tokenError">
          <TextInput v-model="token" type="password" autocomplete="off" class="font-mono" :placeholder="t('faceid.bot.token.placeholder')" :invalid="!!tokenError" data-field="token" />
        </FormField>
        <p class="text-xs text-muted">{{ t("faceid.bot.token.secret") }}</p>
        <div class="flex flex-wrap gap-2">
          <UiButton variant="primary" type="submit" :loading="saving" :icon="CircleCheck" data-save-token>{{ t("faceid.bot.token.save") }}</UiButton>
          <UiButton v-if="replacing" variant="ghost" :disabled="saving" @click="replacing = false">{{ t("common.cancel") }}</UiButton>
        </div>
      </form>

      <div v-if="status === 'ok' && bot.start_url" class="grid gap-5 border-t border-line pt-4 md:grid-cols-[auto_minmax(0,1fr)]" data-start>
        <div class="flex flex-col items-center gap-2">
          <QrCode :value="bot.start_url" :size="144" :label="t('faceid.bot.start.qr')" downloadable filename="faceid-bot" />
        </div>
        <div class="flex min-w-0 flex-col gap-3">
          <div>
            <h3 class="text-sm font-semibold text-fg">{{ t("faceid.bot.start.title") }}</h3>
            <p class="text-sm text-muted">{{ t("faceid.bot.start.hint") }}</p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <code class="min-w-0 max-w-full truncate rounded-[6px] bg-surface-2 px-2 py-1 font-mono text-xs text-fg" data-start-url>{{ bot.start_url }}</code>
            <UiButton size="sm" variant="secondary" :icon="Copy" data-copy @click="copyLink">{{ t("faceid.bot.start.copy") }}</UiButton>
            <UiButton size="sm" variant="ghost" :icon-right="ExternalLink" :href="bot.start_url" target="_blank">{{ t("faceid.bot.start.open") }}</UiButton>
          </div>
          <p class="text-sm text-fg" data-start-counts>{{ t("faceid.bot.start.counts", { started: bot.started, pending: bot.pending.length }) }}</p>
          <p v-if="!bot.pending.length" class="flex items-center gap-2 text-sm text-success" data-all-started>
            <CircleCheck :size="16" aria-hidden="true" />{{ t("faceid.bot.start.everyone") }}
          </p>
          <ul v-else class="flex flex-col divide-y divide-line rounded-[10px] border border-line" data-pending>
            <li v-for="person in bot.pending" :key="person.id" class="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <div class="min-w-0">
                <p class="truncate text-sm font-medium text-fg">{{ person.name }}</p>
                <p class="text-xs text-muted">{{ t(`faceid.bot.role.${person.role}`) }}</p>
              </div>
              <StatusPill :tone="person.state === 'refused' ? 'warning' : 'neutral'" size="sm" :label="t(`faceid.bot.state.${person.state}`)" />
            </li>
          </ul>
        </div>
      </div>
    </div>
  </PageSection>
</template>
