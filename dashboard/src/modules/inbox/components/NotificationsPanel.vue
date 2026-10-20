<script setup lang="ts">
/**
 * Notifications: a list beside the selected one (SplitView). Opening one marks it read; rows can be
 * selected for "Mark read" / "Archive" in bulk. The module that owns a kind may register a renderer
 * for it (`inbox` in its defineModule); the detail uses it, like the shell's drawer does.
 * J/K move through the list, E archives, Enter opens the record.
 */
import { Archive, ArrowUpRight, BellRing, CheckCheck, CircleAlert, Info, TriangleAlert } from "@lucide/vue";
import { computed, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import BulkActionBar from "@/components/BulkActionBar.vue";
import CheckBox from "@/components/CheckBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PersonCell from "@/components/PersonCell.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import SplitView from "@/components/SplitView.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { isModuleVisible } from "@/core/access";
import { useHotkey } from "@/core/hotkeys";
import { modules } from "@/core/modules";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { companyUrl } from "@/lib/links";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useArchive, useMarkRead, useNotificationAction, useNotifications } from "../api";
import type { Notification, NotificationTab, Severity } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const { isPhone } = useBreakpoints();

const tab = useRouteState<NotificationTab>("show", rs.enum(["unread", "all"] as const, "unread"));
const openId = useRouteState("note", rs.optionalNumber(), { push: true });
const query = useNotifications(computed(() => ({ tab: tab.value })));
const notes = computed(() => query.data.value?.pages.flatMap((page) => page.results) ?? []);
const total = computed(() => query.data.value?.pages[0]?.count ?? 0);
const skeleton = useDelayedPending(computed(() => query.isPending.value));

// Keep the open notification visible after it is read (the unread tab would drop it otherwise).
const kept = ref<Notification | null>(null);
const selected = computed(() => notes.value.find((note) => note.id === openId.value) ?? (kept.value?.id === openId.value ? kept.value : null));

const markRead = useMarkRead();
const archive = useArchive();
const act = useNotificationAction();

function open(note: Notification): void {
  kept.value = note;
  openId.value = note.id;
}

watch(tab, () => {
  checked.value = [];
});

// A notification opened from a link (?note=) counts as read too; once per visit, so a server that
// still reports it unread can't start a loop of refetch and mark-read.
const markedHere = new Set<number>();
watch(
  selected,
  (note) => {
    if (!note || note.read_at || markedHere.has(note.id)) return;
    markedHere.add(note.id);
    markRead.mutate([note.id]);
  },
  { immediate: true },
);

// Bulk selection.
const checked = ref<number[]>([]);
function toggleCheck(id: number, value: boolean): void {
  checked.value = value ? [...checked.value, id] : checked.value.filter((item) => item !== id);
}

async function archiveMany(ids: number[]): Promise<void> {
  if (!ids.length) return;
  if (ids.includes(openId.value ?? -1)) openId.value = null;
  checked.value = checked.value.filter((id) => !ids.includes(id));
  try {
    await archive.mutateAsync(ids);
    toast.success(t("inbox.archived", { n: ids.length }));
  } catch {
    // Rolled back; the error was toasted.
  }
}

async function runAction(note: Notification, key: string): Promise<void> {
  const action = note.actions.find((item) => item.key === key);
  if (!action) return;
  let reason: string | undefined;
  if (action.needs_reason) {
    const answer = await confirm({ title: action.label, message: note.title, reason: "required", tone: action.style === "danger" ? "danger" : "primary", confirmLabel: action.label });
    if (!answer) return;
    reason = answer.reason;
  }
  try {
    const result = await act.mutateAsync({ note, key, reason });
    // The open notification may have left the list (unread tab): show its new state anyway.
    if (result?.notification && kept.value?.id === result.notification.id) kept.value = result.notification;
    toast.success(result?.message || t("inbox.done", { action: action.label }));
  } catch {
    // Toasted by the HTTP layer.
  }
}

const link = (url: string) => companyUrl(company.currentId, url);

// Renderers other modules registered for their notification kinds.
const renderers = computed(() => {
  const map = new Map<string, Component>();
  for (const module of modules) {
    if (!module.inbox || !isModuleVisible(module, company.current)) continue;
    for (const [kind, component] of Object.entries(module.inbox)) map.set(kind, component);
  }
  return map;
});

const severityIcon: Record<Severity, Component> = { info: Info, warning: TriangleAlert, critical: CircleAlert };
const severityTone = { info: "info", warning: "warning", critical: "danger" } as const;
const severityBox: Record<Severity, string> = { info: "bg-info-soft text-info", warning: "bg-warning-soft text-warning", critical: "bg-danger-soft text-danger" };

// Keyboard.
function step(direction: 1 | -1): void {
  const list = notes.value;
  if (!list.length) return;
  const index = list.findIndex((note) => note.id === openId.value);
  const next = list[Math.min(list.length - 1, Math.max(0, index === -1 ? 0 : index + direction))]!;
  open(next);
  document.querySelector<HTMLElement>(`[data-note="${next.id}"]`)?.scrollIntoView?.({ block: "nearest" });
}
useHotkey("j", () => step(1), { description: "inbox.keys.next", group: "page" });
useHotkey("k", () => step(-1), { description: "inbox.keys.previous", group: "page" });
useHotkey("e", () => selected.value && void archiveMany([selected.value.id]), { description: "inbox.keys.archive", group: "page", enabled: () => !!selected.value });
useHotkey("enter", () => selected.value?.url && void router.push(link(selected.value.url)), { group: "page", enabled: () => !!selected.value?.url });

const tabOptions = computed(() => [
  { value: "unread" as NotificationTab, label: t("inbox.unread") },
  { value: "all" as NotificationTab, label: t("inbox.all") },
]);
const unreadInView = computed(() => notes.value.filter((note) => !note.read_at).length);
</script>

<template>
  <SplitView id="inbox" :detail-open="!!selected" :back-label="t('inbox.backToList')" height="calc(100dvh - 252px)" @back="openId = null">
    <template #list>
      <div class="flex shrink-0 items-center gap-2 border-b border-line px-3 py-2.5">
        <SegmentedControl v-model="tab" :options="tabOptions" size="sm" :aria-label="t('inbox.tabNotifications')" />
        <span class="flex-1" />
        <IconButton :icon="CheckCheck" :label="t('inbox.markAllRead')" size="sm" :disabled="!unreadInView" @click="markRead.mutate('all')" />
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1.5">
        <div v-if="skeleton" class="flex flex-col gap-1 p-1">
          <div v-for="n in 7" :key="n" class="flex gap-3 rounded-[10px] p-2.5">
            <SkeletonBlock height="28px" width="28px" radius="8px" />
            <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="80%" /><SkeletonBlock width="55%" height="11px" /></div>
          </div>
        </div>
        <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" class="m-2" />
        <EmptyState
          v-else-if="query.data.value && !notes.length"
          size="sm"
          :tone="tab === 'unread' ? 'success' : 'neutral'"
          :icon="tab === 'unread' ? undefined : BellRing"
          :title="tab === 'unread' ? t('inbox.emptyUnreadTitle') : t('inbox.emptyAllTitle')"
          :description="tab === 'unread' ? t('inbox.emptyUnreadBody') : t('inbox.emptyAllBody')"
        />
        <ul v-else class="flex flex-col gap-px">
          <li v-for="note in notes" :key="note.id" :data-note="note.id">
            <div
              role="button"
              tabindex="0"
              :aria-current="note.id === openId ? 'true' : undefined"
              :class="[
                'group/row relative flex gap-3 rounded-[10px] py-2.5 pl-2 pr-2.5 outline-offset-[-2px] transition-colors',
                note.id === openId ? 'bg-accent-soft' : checked.includes(note.id) ? 'bg-surface-2' : 'hover:bg-highlight',
              ]"
              @click="open(note)"
              @keydown.enter.self="open(note)"
            >
              <span class="relative size-7 shrink-0">
                <span :class="['absolute inset-0 grid place-items-center rounded-[8px] transition-opacity', severityBox[note.severity], (checked.length || false) && 'opacity-0', 'group-hover/row:opacity-0']">
                  <component :is="severityIcon[note.severity]" :size="15" />
                </span>
                <span :class="['absolute inset-0 grid place-items-center transition-opacity', checked.length ? 'opacity-100' : 'opacity-0 group-hover/row:opacity-100']" @click.stop>
                  <CheckBox :model-value="checked.includes(note.id)" :aria-label="note.title" @update:model-value="(value: boolean) => toggleCheck(note.id, value)" />
                </span>
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex items-baseline gap-2">
                  <p :class="['min-w-0 flex-1 truncate text-base', note.read_at ? 'font-medium text-muted' : 'font-semibold text-fg']">{{ note.title }}</p>
                  <RelativeTime :value="note.created_at" class="shrink-0 text-xs text-subtle" />
                </div>
                <p v-if="note.body" class="mt-0.5 line-clamp-1 text-sm text-muted">{{ note.body }}</p>
              </div>
              <span v-if="!note.read_at" class="absolute left-0 top-1/2 size-1.5 -translate-y-1/2 rounded-full bg-primary" :aria-label="t('inbox.unread')" />
            </div>
          </li>
        </ul>
        <div v-if="query.hasNextPage.value" class="flex justify-center p-2">
          <UiButton size="sm" variant="ghost" :loading="query.isFetchingNextPage.value" @click="query.fetchNextPage()">{{ t("inbox.loadMore") }}</UiButton>
        </div>
      </div>
      <p class="shrink-0 border-t border-line px-3 py-2 text-xs text-subtle">{{ t("inbox.count", { n: total }) }} · {{ t("inbox.keysHint") }}</p>
    </template>

    <template #detail>
      <article v-if="selected" class="flex min-h-0 flex-1 flex-col">
        <div class="min-h-0 flex-1 overflow-y-auto px-1 py-2 md:px-7 md:py-6">
          <div class="flex flex-wrap items-center gap-2">
            <StatusPill :tone="severityTone[selected.severity]" :label="t(`inbox.severity.${selected.severity}`)" size="sm" :live="selected.severity === 'critical' && !selected.acted_at" />
            <span class="text-xs text-subtle">{{ fmt.instant(selected.created_at) }}</span>
          </div>
          <component :is="renderers.get(selected.kind)" v-if="renderers.has(selected.kind)" :notification="selected" class="mt-4" />
          <template v-else>
            <h2 class="mt-3 text-lg font-semibold leading-7 tracking-[-0.01em] text-fg">{{ selected.title }}</h2>
            <p v-if="selected.body" class="mt-2 max-w-[640px] text-base leading-6 text-muted">{{ selected.body }}</p>
          </template>
          <div v-if="selected.actor" class="mt-6 border-t border-line pt-4">
            <p class="mb-2 text-xs font-medium text-muted">{{ t("inbox.from") }}</p>
            <PersonCell :person="selected.actor" link />
          </div>
          <div v-if="selected.actions.length" class="mt-6 flex flex-wrap gap-2">
            <template v-if="!selected.acted_at">
              <UiButton
                v-for="action in selected.actions"
                :key="action.key"
                :variant="action.style === 'primary' ? 'primary' : 'secondary'"
                :class="action.style === 'danger' && 'hover:!text-danger'"
                :loading="act.isPending.value && act.variables.value?.key === action.key"
                @click="runAction(selected, action.key)"
                >{{ action.label }}</UiButton
              >
            </template>
            <StatusPill v-else tone="success" :label="selected.acted_by ? t('inbox.actedBy', { name: selected.acted_by, time: fmt.relative(selected.acted_at) }) : t('inbox.acted', { time: fmt.relative(selected.acted_at) })" />
          </div>
        </div>
        <footer class="flex shrink-0 items-center gap-2 border-t border-line px-1 py-3 md:px-7">
          <UiButton
            v-if="selected.url"
            :to="link(selected.url)"
            :variant="selected.actions.length && !selected.acted_at ? 'secondary' : 'primary'"
            :icon-right="ArrowUpRight"
            >{{ t("common.open") }}</UiButton
          >
          <span class="flex-1" />
          <UiButton variant="ghost" :icon="Archive" :kbd="isPhone ? undefined : 'e'" @click="archiveMany([selected.id])">{{ t("inbox.archive") }}</UiButton>
        </footer>
      </article>
    </template>

    <template #empty>
      <div class="grid flex-1 place-items-center">
        <EmptyState size="sm" tone="neutral" :icon="BellRing" :title="t('inbox.pickTitle')" :description="t('inbox.pickBody')" />
      </div>
    </template>
  </SplitView>

  <BulkActionBar :count="checked.length" @clear="checked = []">
    <UiButton size="sm" :icon="CheckCheck" @click="markRead.mutate(checked); checked = []">{{ t("inbox.markRead") }}</UiButton>
    <UiButton size="sm" :icon="Archive" @click="archiveMany(checked)">{{ t("inbox.archive") }}</UiButton>
  </BulkActionBar>
</template>
