<script setup lang="ts">
/**
 * Settings › Telegram (docs/DAVOMAT.md §1.5): the organization's own bot. Its state (not connected,
 * connected as @name, or refused by Telegram), the token pasted from @BotFather (checked with
 * Telegram before it is saved, kept encrypted, never shown again) with the steps to get one, a test
 * message, linking your own Telegram with a QR code, and what the bot sends to whom.
 */
import { AlertTriangle, BellRing, Camera, CircleCheck, ClipboardList, ExternalLink, MessageCircleQuestion, RefreshCw, Send, Sparkles, Timer, Unplug, UserRoundSearch } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { z } from "zod";

import { isApiError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageSection from "@/components/PageSection.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useCan } from "@/lib/usePermission";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useForm } from "@/lib/useForm";
import { useCompanyId, useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { davomatKeys, disconnectTelegram, saveTelegramToken, testTelegram, useBrandRefresh, useTelegram, userTelegramLink } from "../api";
import BotFatherGuide from "../components/settings/BotFatherGuide.vue";
import SecretInput from "../components/settings/SecretInput.vue";
import { useUsersWhen } from "../components/settings/settingsApi";
import TelegramLinkDialog from "../components/settings/TelegramLinkDialog.vue";
import type { TelegramSettings } from "../types";

const { t } = useI18n();
const client = useQueryClient();
const cid = useCompanyId();
const company = useCompanyStore();
const brandRefresh = useBrandRefresh();
const canEdit = useCan("company.settings");
const canSeeUsers = useCan("roles.manage");

const telegram = useTelegram();
const skeleton = useDelayedPending(computed(() => telegram.isPending.value));
const bot = computed(() => telegram.data.value ?? null);
const status = computed(() => bot.value?.status ?? "not_set");
const botUrl = computed(() => (bot.value?.bot_username ? `https://t.me/${bot.value.bot_username}` : null));

// The token form shows until a bot works, and again when asked to replace it.
const replacing = ref(false);
const showForm = computed(() => canEdit.value && (status.value !== "ok" || replacing.value));

/** A token as BotFather gives it: the bot's number, a colon, 35 letters, digits, _ and -. */
const TOKEN = /^\d{5,15}:[A-Za-z0-9_-]{30,}$/;
const schema = z.object({ token: z.string().trim().min(1, "common.form.required").regex(TOKEN, "davomat.telegram.token.format") });

const form = useForm(schema, { token: "" }, {
  onSubmit: async ({ token }) => {
    const saved = await saveTelegramToken(cid.value, token.trim());
    client.setQueryData<TelegramSettings>(davomatKeys.telegram(cid.value), saved);
    form.reset({ token: "" });
    replacing.value = false;
    if (saved.status === "ok") toast.success(t("davomat.telegram.token.saved", { name: saved.bot_username ? `@${saved.bot_username}` : (saved.bot_name ?? "") }));
    void brandRefresh();
  },
});

// ─── Disconnect ───────────────────────────────────────────────────────────────

const confirm = useConfirm();
const disconnecting = ref(false);
async function disconnect(): Promise<void> {
  const answer = await confirm({
    title: t("davomat.telegram.disconnect.title"),
    message: t("davomat.telegram.disconnect.body"),
    confirmLabel: t("davomat.telegram.disconnect.confirm"),
    tone: "danger",
    icon: Unplug,
  });
  if (!answer) return;
  disconnecting.value = true;
  try {
    await disconnectTelegram(cid.value);
    client.setQueryData<TelegramSettings>(davomatKeys.telegram(cid.value), { configured: false, bot_username: null, bot_name: null, status: "not_set", checked_at: null });
    replacing.value = false;
    testResult.value = null;
    toast.success(t("davomat.telegram.disconnect.done"));
    void brandRefresh();
  } catch {
    // The HTTP layer toasted the refusal.
  } finally {
    disconnecting.value = false;
  }
}

function cancelReplace(): void {
  replacing.value = false;
  form.reset({ token: "" });
}

// Telegram refused the token: its words if it sent any, else ours.
const tokenError = computed(() => form.errors.token ?? null);

// ─── Test message ─────────────────────────────────────────────────────────────

const testing = ref(false);
/** Sent, or what to do first in the server's words (link your Telegram, press Start in the bot…). */
const testResult = ref<{ tone: "success" | "warning"; text: string } | null>(null);
async function sendTest(): Promise<void> {
  testing.value = true;
  testResult.value = null;
  try {
    await testTelegram(cid.value);
    testResult.value = { tone: "success", text: t("davomat.telegram.test.sent") };
  } catch (error) {
    if (isApiError(error) && error.status === 400) testResult.value = { tone: "warning", text: error.detail ?? t("davomat.telegram.test.notLinked") };
    else toast.error(isApiError(error) && error.detail ? error.detail : t("davomat.telegram.test.failed"));
  } finally {
    testing.value = false;
  }
}

// ─── Your own Telegram ────────────────────────────────────────────────────────

const session = useSessionStore();
const users = useUsersWhen(canSeeUsers);
const me = computed(() => (users.data.value ?? []).find((user) => user.id === company.current?.membership_id) ?? null);
// The users list when the person may read it, else their own account (a linked Telegram has an id).
const meLinked = computed(() => me.value?.telegram_linked ?? (session.me?.user.telegram_id ?? null) !== null);
const linkOpen = ref(false);
const createMyLink = () => userTelegramLink(cid.value, company.current?.membership_id ?? 0);
watch(linkOpen, (open) => {
  // Back from the dialog: the person may have linked; show it.
  if (open) return;
  if (canSeeUsers.value) void users.refetch();
  void session.loadMe().catch(() => undefined);
});

const sends = computed(() => [
  { icon: Camera, text: t("davomat.telegram.sends.arrivals") },
  { icon: Timer, text: t("davomat.telegram.sends.late") },
  { icon: ClipboardList, text: t("davomat.telegram.sends.summary") },
  { icon: UserRoundSearch, text: t("davomat.telegram.sends.unknown") },
  { icon: BellRing, text: t("davomat.telegram.sends.own") },
]);
</script>

<template>
  <div class="flex flex-col gap-6" data-telegram-panel>
    <ErrorState v-if="telegram.isError.value" :error="telegram.error.value" :retry="() => telegram.refetch()" :retrying="telegram.isFetching.value" />

    <div v-else-if="skeleton || !bot" class="ui-card flex items-center gap-4 p-5" aria-busy="true">
      <SkeletonBlock circle width="52px" height="52px" />
      <div class="flex flex-1 flex-col gap-2">
        <SkeletonBlock width="38%" height="16px" />
        <SkeletonBlock width="62%" />
      </div>
    </div>

    <template v-else>
      <!-- The bot's state -->
      <section
        :class="[
          'ui-card relative overflow-hidden p-5',
          status === 'ok' && 'border-[color-mix(in_srgb,var(--c-success)_30%,var(--c-border))]',
          status === 'invalid' && 'border-[color-mix(in_srgb,var(--c-danger)_30%,var(--c-border))]',
        ]"
        :data-status="status"
      >
        <div class="flex flex-wrap items-start gap-4">
          <span
            :class="[
              'relative grid size-[52px] shrink-0 place-items-center rounded-full',
              status === 'ok' ? 'bg-info-soft text-info' : status === 'invalid' ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted',
            ]"
          >
            <AlertTriangle v-if="status === 'invalid'" :size="24" />
            <Send v-else :size="22" />
            <span v-if="status === 'ok'" class="absolute -bottom-0.5 -right-0.5 grid size-5 place-items-center rounded-full bg-success text-on-primary ring-[3px] ring-[var(--c-surface)]">
              <CircleCheck :size="12" />
            </span>
          </span>
          <div class="min-w-[min(100%,220px)] flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-md font-semibold text-fg">
                {{ status === "ok" ? bot.bot_name || t("davomat.telegram.status.ok.title") : t(`davomat.telegram.status.${status === "invalid" ? "invalid" : "notSet"}.title`) }}
              </h3>
              <StatusPill
                :tone="status === 'ok' ? 'success' : status === 'invalid' ? 'danger' : 'neutral'"
                :label="t(`davomat.telegram.status.${status === 'invalid' ? 'invalid' : status === 'ok' ? 'ok' : 'notSet'}.pill`)"
                size="sm"
                :live="status === 'ok'"
              />
            </div>
            <p v-if="status === 'ok' && bot.bot_username" class="mt-0.5 font-mono text-sm text-muted">@{{ bot.bot_username }}</p>
            <p class="mt-1.5 max-w-[560px] text-sm text-muted">
              {{ t(`davomat.telegram.status.${status === "invalid" ? "invalid" : status === "ok" ? "ok" : "notSet"}.body`) }}
            </p>
            <p v-if="bot.checked_at" class="mt-2 text-xs text-subtle">
              {{ t("davomat.telegram.checked") }} <RelativeTime :value="bot.checked_at" />
            </p>
          </div>
          <div v-if="status === 'ok'" class="flex flex-wrap gap-2">
            <UiButton v-if="botUrl" variant="secondary" :icon-right="ExternalLink" :href="botUrl" target="_blank">{{ t("davomat.telegram.openBot") }}</UiButton>
            <UiButton v-if="canEdit && !replacing" variant="ghost" :icon="RefreshCw" data-replace @click="replacing = true">{{ t("davomat.telegram.token.replace") }}</UiButton>
            <UiButton v-if="canEdit" variant="ghost" :icon="Unplug" :loading="disconnecting" data-disconnect @click="disconnect">{{ t("davomat.telegram.disconnect.action") }}</UiButton>
          </div>
        </div>
      </section>

      <InlineAlert v-if="!canEdit && status !== 'ok'" tone="info" :title="t('davomat.settings.readOnly.title')" :description="t('davomat.telegram.readOnly')" />

      <!-- The token, and how to get one -->
      <Transition name="fade">
        <div v-if="showForm" class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <PageSection variant="card" :title="t('davomat.telegram.guide.title')" :description="t('davomat.telegram.guide.hint')">
            <BotFatherGuide />
          </PageSection>
          <PageSection variant="card" :title="t('davomat.telegram.token.title')" :description="t('davomat.telegram.token.hint')">
            <form class="flex flex-col gap-4" novalidate data-token-form @submit="form.submit">
              <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />
              <FormField :label="t('davomat.telegram.token.label')" :error="tokenError">
                <SecretInput v-model="form.values.token" mono :placeholder="t('davomat.telegram.token.placeholder')" :invalid="!!tokenError" data-field="token" @blur="form.touch('token')" />
              </FormField>
              <p class="flex items-start gap-2 text-xs text-muted">
                <Sparkles :size="14" class="mt-px shrink-0 text-subtle" />
                {{ t("davomat.telegram.token.secret") }}
              </p>
              <div class="flex flex-wrap gap-2">
                <UiButton variant="primary" type="submit" :loading="form.submitting.value" :icon="CircleCheck">{{ t("davomat.telegram.token.save") }}</UiButton>
                <UiButton v-if="replacing" variant="ghost" :disabled="form.submitting.value" @click="cancelReplace">{{ t("common.cancel") }}</UiButton>
              </div>
            </form>
          </PageSection>
        </div>
      </Transition>

      <!-- With a working bot: your own Telegram, a test -->
      <div v-if="status === 'ok'" class="grid gap-4 md:grid-cols-2">
        <section class="ui-card flex flex-col gap-3 p-5" data-me>
          <h3 class="text-base font-semibold text-fg">{{ t("davomat.telegram.me.title") }}</h3>
          <p class="text-sm text-muted">{{ meLinked ? t("davomat.telegram.me.linked") : t("davomat.telegram.me.notLinked") }}</p>
          <div class="mt-auto flex flex-wrap gap-2 pt-1">
            <UiButton :variant="meLinked ? 'ghost' : 'primary'" :icon="Send" data-link-me @click="linkOpen = true">
              {{ meLinked ? t("davomat.telegram.me.relink") : t("davomat.telegram.me.link") }}
            </UiButton>
          </div>
        </section>
        <section class="ui-card flex flex-col gap-3 p-5" data-test>
          <h3 class="text-base font-semibold text-fg">{{ t("davomat.telegram.test.title") }}</h3>
          <p class="text-sm text-muted">{{ t("davomat.telegram.test.hint") }}</p>
          <InlineAlert v-if="testResult" :tone="testResult.tone" size="sm" :description="testResult.text" data-test-result />
          <div class="mt-auto flex flex-wrap gap-2 pt-1">
            <UiButton variant="secondary" :icon="MessageCircleQuestion" :loading="testing" data-send-test @click="sendTest">{{ t("davomat.telegram.test.action") }}</UiButton>
          </div>
        </section>
      </div>

      <!-- What goes where -->
      <PageSection variant="card" :title="t('davomat.telegram.sends.title')" :description="t('davomat.telegram.sends.hint')">
        <ul class="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          <li v-for="item in sends" :key="item.text" class="flex items-start gap-3">
            <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-accent-soft text-accent-fg"><component :is="item.icon" :size="16" /></span>
            <span class="pt-1.5 text-sm text-fg">{{ item.text }}</span>
          </li>
        </ul>
        <div class="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-4 text-sm text-muted">
          <span>{{ t("davomat.telegram.commands") }}</span>
          <code class="rounded-[6px] bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-fg">/today</code>
          <span>{{ t("davomat.telegram.commandToday") }}</span>
          <span aria-hidden="true">·</span>
          <code class="rounded-[6px] bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-fg">/me</code>
          <span>{{ t("davomat.telegram.commandMe") }}</span>
        </div>
      </PageSection>
    </template>

    <TelegramLinkDialog
      v-model:open="linkOpen"
      :title="t('davomat.telegram.me.dialogTitle')"
      :description="meLinked ? undefined : t('davomat.telegram.me.dialogHint')"
      :linked="false"
      :create="createMyLink"
    />
  </div>
</template>
