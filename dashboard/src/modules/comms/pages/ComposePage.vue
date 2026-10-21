<script setup lang="ts">
/**
 * The announcement composer (plan §6.2): Telegram formatting, audience by positions and branches
 * with a live count, send now or schedule, pin until and expiry, and a preview of the bubble
 * people get. `?edit=12` opens a scheduled announcement to change it. Hosts the
 * `comms.composer.tools` slot (package K's AI writer) with `{ text, setText }` in its context.
 */
import { CalendarClock, Pin, Send, Timer, Users } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import AvatarStack from "@/components/AvatarStack.vue";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { hasExtension } from "@/core/extensions";
import { addDays, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { useAnnouncement, useAudience, usePublish } from "../api";
import TelegramBubble from "../components/TelegramBubble.vue";
import TelegramHtmlEditor from "../components/TelegramHtmlEditor.vue";
import { fromEditor, toEditor } from "../telegramHtml";
import type { PublishInput } from "../types";
import { nextMorning, splitIso, zonedIso } from "../when";

const MAX = 3500;

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const tz = computed(() => company.timezone);
const me = computed(() => company.current);
const session = useSessionStore();

const editId = useRouteState("edit", rs.optionalNumber());
const editing = useAnnouncement(computed(() => editId.value ?? 0));

const html = ref("");
const positions = ref<number[]>([]);
const branches = ref<number[]>([]);
const mode = ref<"now" | "later">("now");
const sendDay = ref<string | null>(nextMorning(tz.value).day);
const sendTime = ref<string | null>("09:00");
const pin = ref(false);
const pinDay = ref<string | null>(addDays(todayIn(tz.value), 3));
const pinTime = ref<string | null>("20:00");
const expire = ref(false);
const expireDay = ref<string | null>(addDays(todayIn(tz.value), 7));
const expireTime = ref<string | null>("20:00");
const error = ref<string | null>(null);

// Opening a scheduled announcement to change it.
watch(
  () => editing.data.value,
  (row) => {
    if (!row) return;
    html.value = toEditor(row.text);
    positions.value = row.positions.map((p) => p.id);
    branches.value = row.branches.map((b) => b.id);
    if (row.scheduled_for) {
      mode.value = "later";
      ({ day: sendDay.value, time: sendTime.value } = splitIso(row.scheduled_for, tz.value));
    }
    if (row.pinned_until) {
      pin.value = true;
      ({ day: pinDay.value, time: pinTime.value } = splitIso(row.pinned_until, tz.value));
    }
    if (row.expires_at) {
      expire.value = true;
      ({ day: expireDay.value, time: expireTime.value } = splitIso(row.expires_at, tz.value));
    }
  },
  { immediate: true },
);

const telegram = computed(() => fromEditor(html.value));
const length = computed(() => telegram.value.length);
const audience = useAudience(computed(() => ({ position: positions.value, branch: branches.value })));
const scheduledFor = computed(() => (mode.value === "later" && sendDay.value && sendTime.value ? zonedIso(sendDay.value, sendTime.value, tz.value) : null));
const pinnedUntil = computed(() => (pin.value && pinDay.value && pinTime.value ? zonedIso(pinDay.value, pinTime.value, tz.value) : null));
const expiresAt = computed(() => (expire.value && expireDay.value && expireTime.value ? zonedIso(expireDay.value, expireTime.value, tz.value) : null));

const problems = computed(() => {
  const list: string[] = [];
  const now = Date.now();
  if (scheduledFor.value && new Date(scheduledFor.value).getTime() < now + 60_000) list.push(t("comms.compose.scheduleFuture"));
  const start = scheduledFor.value ? new Date(scheduledFor.value).getTime() : now;
  if (pinnedUntil.value && new Date(pinnedUntil.value).getTime() <= start) list.push(t("comms.compose.pinAfter"));
  if (expiresAt.value && new Date(expiresAt.value).getTime() <= start) list.push(t("comms.compose.expireAfter"));
  if (pinnedUntil.value && expiresAt.value && pinnedUntil.value > expiresAt.value) list.push(t("comms.compose.pinBeforeExpiry"));
  return list;
});

const publish = usePublish();
const canSend = computed(() => !!telegram.value.trim() && length.value <= MAX && !problems.value.length && (audience.data.value?.count ?? 1) > 0);

async function send(): Promise<void> {
  error.value = null;
  if (!telegram.value.trim()) {
    error.value = t("comms.compose.writeSomething");
    return;
  }
  const body: PublishInput = {
    text_html: html.value,
    position_ids: positions.value,
    branch_ids: branches.value,
    scheduled_for: scheduledFor.value,
    pinned_until: pinnedUntil.value,
    expires_at: expiresAt.value,
  };
  try {
    const row = await publish.mutateAsync({ id: editId.value, body });
    if (row.status === "scheduled") toast.success(t("comms.compose.scheduled", { when: fmt.instant(row.scheduled_for!, "datetime") }));
    else toast.success(t("comms.compose.sent", { n: row.recipients_count }, row.recipients_count));
    void router.push(`/c/${company.currentId}/announcements/${row.id}`);
  } catch {
    // The HTTP layer showed why.
  }
}

const sendLabel = computed(() => {
  if (editId.value) return t("comms.compose.saveChanges");
  if (mode.value === "later" && scheduledFor.value) return t("comms.compose.scheduleFor", { when: fmt.instant(scheduledFor.value, "short") });
  const n = audience.data.value?.count ?? 0;
  return t("comms.compose.sendTo", { n }, n);
});

const slotContext = computed(() => ({ companyId: company.currentId, text: telegram.value, html: html.value, setText: (value: string) => (html.value = toEditor(value)) }));
const hasTools = computed(() => hasExtension("comms.composer.tools", company.current));
const authorName = computed(() => editing.data.value?.author?.name ?? session.me?.user.full_name ?? "");
const previewTime = computed(() => (scheduledFor.value ? fmt.instant(scheduledFor.value, "time") : fmt.instant(new Date().toISOString(), "time")));
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader
      class="!mb-0"
      :title="editId ? t('comms.compose.editTitle') : t('comms.compose.title')"
      :description="t('comms.compose.description')"
      :back="`/c/${company.currentId}/announcements`"
      :back-label="t('comms.nav.announcements')"
    />

    <div v-if="editId && editing.isPending.value" class="ui-card flex flex-col gap-3 p-5"><SkeletonBlock height="200px" radius="12px" /><SkeletonBlock :lines="3" /></div>
    <ErrorState v-else-if="editId && editing.isError.value" class="ui-card" :error="editing.error.value" :retry="() => editing.refetch()" />
    <div v-else class="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_400px]">
      <div class="flex min-w-0 flex-col gap-5">
        <section class="ui-card p-5">
          <FormField :label="t('comms.compose.message')" :error="error" :count="length" :max="MAX" required>
            <TelegramHtmlEditor v-model="html" :placeholder="t('comms.compose.placeholder')" :invalid="length > MAX">
              <template v-if="hasTools" #tools>
                <ExtensionSlot name="comms.composer.tools" :context="slotContext" as="none" />
              </template>
            </TelegramHtmlEditor>
          </FormField>
        </section>

        <section class="ui-card flex flex-col gap-4 p-5">
          <div class="flex items-center gap-2">
            <Users :size="16" class="text-subtle" aria-hidden="true" />
            <h2 class="text-md font-semibold text-fg">{{ t("comms.compose.audience") }}</h2>
          </div>
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField :label="t('comms.compose.branches')" :hint="me?.branch_scope === null ? t('comms.compose.branchesHint') : t('comms.compose.branchesScoped')">
              <BranchPicker v-model="branches" multiple :placeholder="t('comms.compose.allBranches')" />
            </FormField>
            <FormField :label="t('comms.compose.positions')" :hint="t('comms.compose.positionsHint')">
              <PositionPicker v-model="positions" multiple :placeholder="t('comms.compose.allPositions')" />
            </FormField>
          </div>
          <div class="flex flex-wrap items-center gap-3 rounded-[12px] bg-surface-2/70 px-4 py-3 dark:bg-surface-2">
            <AvatarStack v-if="audience.data.value?.sample.length" :people="audience.data.value.sample" :max="5" :size="26" />
            <p class="text-base text-fg">
              <template v-if="audience.isPending.value">{{ t("comms.compose.counting") }}</template>
              <template v-else-if="audience.data.value?.count">
                <span class="font-semibold tabular-nums">{{ audience.data.value.count }}</span> {{ t("comms.compose.peopleGetIt", { n: audience.data.value.count }, audience.data.value.count) }}
              </template>
              <span v-else class="text-warning">{{ t("comms.compose.nobody") }}</span>
            </p>
          </div>
        </section>

        <section class="ui-card flex flex-col gap-4 p-5">
          <div class="flex items-center gap-2">
            <CalendarClock :size="16" class="text-subtle" aria-hidden="true" />
            <h2 class="text-md font-semibold text-fg">{{ t("comms.compose.timing") }}</h2>
          </div>
          <SegmentedControl
            v-model="mode"
            class="w-fit"
            :options="[
              { value: 'now', label: t('comms.compose.now'), icon: Send },
              { value: 'later', label: t('comms.compose.later'), icon: CalendarClock },
            ]"
          />
          <div v-if="mode === 'later'" class="flex flex-wrap items-end gap-3">
            <FormField :label="t('comms.compose.day')"><DatePicker v-model="sendDay" :min="todayIn(tz)" :max="addDays(todayIn(tz), 90)" format="weekday" /></FormField>
            <FormField :label="t('comms.compose.time')"><TimePicker v-model="sendTime" :step="15" /></FormField>
          </div>
          <div class="grid grid-cols-1 gap-4 border-t border-line pt-4 md:grid-cols-2">
            <div class="flex flex-col gap-3">
              <ToggleSwitch v-model="pin" layout="row" :label="t('comms.compose.pin')" :description="t('comms.compose.pinHint')" />
              <div v-if="pin" class="flex flex-wrap items-end gap-2">
                <FormField :label="t('comms.compose.pinUntil')"><DatePicker v-model="pinDay" :min="todayIn(tz)" /></FormField>
                <FormField :label="t('comms.compose.time')"><TimePicker v-model="pinTime" :step="15" /></FormField>
              </div>
            </div>
            <div class="flex flex-col gap-3">
              <ToggleSwitch v-model="expire" layout="row" :label="t('comms.compose.expire')" :description="t('comms.compose.expireHint')" />
              <div v-if="expire" class="flex flex-wrap items-end gap-2">
                <FormField :label="t('comms.compose.expiresOn')"><DatePicker v-model="expireDay" :min="todayIn(tz)" /></FormField>
                <FormField :label="t('comms.compose.time')"><TimePicker v-model="expireTime" :step="15" /></FormField>
              </div>
            </div>
          </div>
          <InlineAlert v-for="problem in problems" :key="problem" tone="warning" size="sm" :description="problem" />
        </section>
      </div>

      <aside class="flex min-w-0 flex-col gap-4 lg:sticky lg:top-4 lg:self-start">
        <section class="ui-card p-4">
          <div class="mb-3 flex items-center justify-between gap-2">
            <h2 class="text-sm font-semibold text-fg">{{ t("comms.compose.preview") }}</h2>
            <span class="inline-flex items-center gap-1 text-xs text-muted">
              <Pin v-if="pin" :size="12" class="text-primary" />{{ pin ? t("comms.compose.pinnedPreview") : "" }}
              <Timer v-if="expire" :size="12" class="ml-1.5 text-muted" />
            </span>
          </div>
          <TelegramBubble :text="telegram" :author="authorName" :time="previewTime" />
          <p class="mt-3 text-xs text-subtle">{{ t("comms.compose.previewHint") }}</p>
        </section>
        <UiButton variant="primary" size="lg" block :icon="mode === 'later' ? CalendarClock : Send" :loading="publish.isPending.value" :disabled="!canSend" @click="send">{{ sendLabel }}</UiButton>
      </aside>
    </div>
  </div>
</template>
