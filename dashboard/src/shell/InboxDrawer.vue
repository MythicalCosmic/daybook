<script setup lang="ts">
/**
 * The inbox drawer (plan §6.5), open while `?inbox=needs|notifications` is in the URL.
 * "Needs you": approvals from every module, decided in place through each item's QueueActions.
 * "Notifications": the person's notifications, drawn by the module that owns the kind when it
 * registered a renderer, by the default row otherwise.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { ArrowUpRight, BellRing, CheckCheck, CircleAlert, Info, TriangleAlert } from "@lucide/vue";
import { computed, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { keys } from "@/api/keys";
import { shellApi, withoutQueueItem } from "@/api/shell";
import type { Notification, QueueAction, QueueItem, QueueView, Severity } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import { iconForKind } from "@/components/kindIcons";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { isModuleVisible } from "@/core/access";
import { modules } from "@/core/modules";
import { companyUrl as linkInCompany } from "@/lib/links";
import { applyQueryPatch, closeQueryKey } from "@/lib/useRouteState";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const client = useQueryClient();
const company = useCompanyStore();
const fmt = useFormat();
const confirm = useConfirm();

const companyId = computed(() => company.currentId ?? 0);
const isOpen = computed(() => route.query.inbox !== undefined);
const tab = computed<"needs" | "notifications">(() => (route.query.inbox === "notifications" ? "notifications" : "needs"));
const notesFilter = ref<"unread" | "all">("unread");

function setTab(next: "needs" | "notifications"): void {
  void router.replace({ path: route.path, query: applyQueryPatch(route.query, { inbox: next }), hash: route.hash });
}

function close(): void {
  closeQueryKey(router, "inbox");
}

const queue = useQuery({
  queryKey: computed(() => keys.queue(companyId.value)),
  queryFn: ({ signal }) => shellApi.queue(companyId.value, null, signal),
  enabled: computed(() => isOpen.value && companyId.value > 0),
  staleTime: 10_000,
});

const notes = useQuery({
  queryKey: computed(() => keys.inbox(companyId.value, notesFilter.value)),
  queryFn: ({ signal }) => shellApi.inbox(companyId.value, notesFilter.value, 1, signal),
  enabled: computed(() => isOpen.value && tab.value === "notifications" && companyId.value > 0),
  staleTime: 10_000,
});

const queueSkeleton = useDelayedPending(computed(() => queue.isPending.value && isOpen.value));
const notesSkeleton = useDelayedPending(computed(() => notes.isPending.value && isOpen.value));

const groups = computed(() => {
  const data = queue.data.value;
  if (!data) return [];
  return data.kinds
    .map((kind) => ({ ...kind, items: data.items.filter((item) => item.kind === kind.kind) }))
    .filter((group) => group.items.length > 0);
});

// Deciding with a reason: the item and action waiting for the text.
const reasonFor = ref<{ itemKey: string; action: QueueAction } | null>(null);
const reason = ref("");
const itemKey = (item: QueueItem) => `${item.kind}:${item.id}`;

/** Everything the bell, the drawer and the inbox page show, after a decision. */
function refreshInbox(): void {
  const id = companyId.value;
  void client.invalidateQueries({ queryKey: [id, "shell", "queue"] });
  void client.invalidateQueries({ queryKey: [id, "shell", "inbox"] });
  void client.invalidateQueries({ queryKey: keys.unread(id) });
  void client.invalidateQueries({ queryKey: keys.pulse(id) });
  void client.invalidateQueries({ queryKey: [id, "inbox"] });
}

const decide = useMutation({
  mutationFn: ({ action, text }: { item: QueueItem; action: QueueAction; text?: string }) => shellApi.runQueueAction(companyId.value, action, text),
  onMutate: async ({ item }) => {
    const key = keys.queue(companyId.value);
    await client.cancelQueries({ queryKey: key });
    const previous = client.getQueryData<QueueView>(key);
    if (previous) client.setQueryData<QueueView>(key, withoutQueueItem(previous, item));
    return { previous };
  },
  onSuccess: (_data, { action }) => toast.success(t("shell.inbox.actionDone", { action: action.label })),
  onError: (_error, _vars, context) => {
    if (context?.previous) client.setQueryData(keys.queue(companyId.value), context.previous);
  },
  onSettled: refreshInbox,
});

function run(item: QueueItem, action: QueueAction): void {
  if (action.needs_reason) {
    reasonFor.value = { itemKey: itemKey(item), action };
    reason.value = "";
    return;
  }
  decide.mutate({ item, action });
}

function confirmReason(item: QueueItem): void {
  if (!reasonFor.value || !reason.value.trim()) return;
  decide.mutate({ item, action: reasonFor.value.action, text: reason.value.trim() });
  reasonFor.value = null;
}

const companyUrl = (url: string) => linkInCompany(companyId.value, url);

const markRead = useMutation({
  mutationFn: (ids: number[] | "all") => shellApi.markRead(companyId.value, ids),
  onSettled: refreshInbox,
});

function openNote(note: Notification): void {
  if (!note.read_at) markRead.mutate([note.id]);
  if (note.url) void router.push(companyUrl(note.url));
}

const noteAction = useMutation({
  mutationFn: ({ note, key, reason: text }: { note: Notification; key: string; reason?: string }) => shellApi.runInboxAction(companyId.value, note.id, key, text),
  // The module's handler says what happened ("Approved."); the button's label is the fallback.
  onSuccess: (result, { note, key }) =>
    toast.success(result?.message || t("shell.inbox.actionDone", { action: note.actions.find((a) => a.key === key)?.label ?? key })),
  onSettled: refreshInbox,
});

async function runNoteAction(note: Notification, key: string): Promise<void> {
  const action = note.actions.find((item) => item.key === key);
  if (!action) return;
  let text: string | undefined;
  if (action.needs_reason) {
    const answer = await confirm({ title: action.label, message: note.title, reason: "required", tone: action.style === "danger" ? "danger" : "primary", confirmLabel: action.label });
    if (!answer) return;
    text = answer.reason;
  }
  noteAction.mutate({ note, key, reason: text });
}

/** Module renderers for notification kinds ("sales.cash_difference" → the sales module's component). */
const renderers = computed(() => {
  const map = new Map<string, Component>();
  for (const module of modules) {
    if (!module.inbox || !isModuleVisible(module, company.current)) continue;
    for (const [kind, component] of Object.entries(module.inbox)) map.set(kind, component);
  }
  return map;
});

const severityIcon: Record<Severity, Component> = { info: Info, warning: TriangleAlert, critical: CircleAlert };
const severityTone: Record<Severity, string> = {
  info: "bg-info-soft text-info",
  warning: "bg-warning-soft text-warning",
  critical: "bg-danger-soft text-danger",
};

const inboxPage = computed(() => router.resolve(`/c/${companyId.value}/inbox`).name !== "company-not-found");
const unreadCount = computed(() => (notesFilter.value === "unread" ? (notes.data.value?.count ?? 0) : 0));
</script>

<template>
  <UiDrawer
    :open="isOpen"
    :title="t('shell.inbox.title')"
    size="md"
    hide-header
    @update:open="(value: boolean) => !value && close()"
  >
    <div class="flex h-full flex-col">
      <div class="sticky top-0 z-10 shrink-0 border-b border-line bg-surface/95 px-4 pt-3 backdrop-blur md:px-5 md:pt-4">
        <div class="flex items-center gap-2">
          <h2 class="flex-1 text-md font-semibold text-fg">{{ t("shell.inbox.title") }}</h2>
          <UiButton
            v-if="tab === 'notifications' && unreadCount > 0"
            variant="ghost"
            size="sm"
            :icon="CheckCheck"
            @click="markRead.mutate('all')"
            >{{ t("shell.inbox.markAllRead") }}</UiButton
          >
        </div>
        <div class="mt-2 flex gap-1" role="tablist">
          <button
            v-for="item in (['needs', 'notifications'] as const)"
            :key="item"
            type="button"
            role="tab"
            :aria-selected="tab === item"
            :class="[
              'relative flex h-9 items-center gap-2 rounded-[6px] px-2 text-base font-semibold transition-colors focus-visible:outline-offset-[-2px]',
              tab === item ? 'text-fg' : 'text-muted hover:text-fg',
            ]"
            @click="setTab(item)"
          >
            {{ item === "needs" ? t("shell.inbox.needsYou") : t("shell.inbox.notifications") }}
            <UiBadge v-if="item === 'needs' && queue.data.value?.total" :count="queue.data.value.total" :tone="tab === item ? 'primary' : 'neutral'" />
            <UiBadge v-if="item === 'notifications' && unreadCount" :count="unreadCount" :tone="tab === item ? 'primary' : 'neutral'" />
            <span v-if="tab === item" class="absolute inset-x-1 -bottom-px h-[2px] rounded-full bg-primary" />
          </button>
        </div>
      </div>

      <!-- Needs you -->
      <div v-if="tab === 'needs'" class="flex-1 px-3 py-3 md:px-4">
        <div v-if="queueSkeleton" class="flex flex-col gap-2 p-1">
          <div v-for="n in 4" :key="n" class="flex gap-3 rounded-card border border-line p-3">
            <SkeletonBlock circle height="32px" />
            <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="70%" /><SkeletonBlock width="45%" height="12px" /></div>
          </div>
        </div>
        <ErrorState v-else-if="queue.isError.value" compact :error="queue.error.value" :retry="() => queue.refetch()" />
        <EmptyState
          v-else-if="queue.data.value && groups.length === 0"
          size="sm"
          tone="success"
          :title="t('shell.inbox.emptyNeedsTitle')"
          :description="t('shell.inbox.emptyNeedsBody')"
        />
        <div v-else class="flex flex-col gap-4">
          <section v-for="group in groups" :key="group.kind">
            <h3 class="mb-1.5 flex items-center gap-2 px-1 text-xs font-medium text-muted">
              {{ group.label }}
              <span class="text-subtle">{{ group.count }}</span>
            </h3>
            <TransitionGroup name="list" tag="ul" class="relative flex flex-col gap-1.5">
              <li v-for="item in group.items" :key="itemKey(item)" class="rounded-card border border-line bg-surface p-3 transition-colors hover:border-line-strong">
                <div class="flex items-start gap-3">
                  <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-accent-soft text-accent-fg" aria-hidden="true">
                    <component :is="iconForKind(item.kind)" :size="15" />
                  </span>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-baseline gap-2">
                      <p class="line-clamp-2 min-w-0 flex-1 text-base font-semibold text-fg md:line-clamp-1">{{ item.title }}</p>
                      <span v-if="item.created_at" class="shrink-0 text-xs text-subtle">{{ fmt.relative(item.created_at) }}</span>
                    </div>
                    <p v-if="item.subtitle" class="mt-0.5 line-clamp-2 text-sm text-muted">{{ item.subtitle }}</p>

                    <form
                      v-if="reasonFor?.itemKey === itemKey(item)"
                      class="mt-2.5 flex flex-col gap-2"
                      @submit.prevent="confirmReason(item)"
                    >
                      <label class="text-xs font-medium text-muted" :for="`reason-${itemKey(item)}`">{{ t("shell.inbox.reasonTitle") }}</label>
                      <textarea
                        :id="`reason-${itemKey(item)}`"
                        v-model="reason"
                        rows="2"
                        class="w-full resize-none rounded-input border border-line bg-surface px-2.5 py-2 text-base outline-none transition-shadow focus:border-primary focus:shadow-[0_0_0_3px_var(--c-accent-soft)]"
                        :placeholder="t('common.reasonPlaceholder')"
                        autofocus
                      />
                      <div class="flex justify-end gap-2">
                        <UiButton size="sm" variant="ghost" @click="reasonFor = null">{{ t("common.cancel") }}</UiButton>
                        <UiButton size="sm" type="submit" :variant="reasonFor.action.style === 'danger' ? 'danger' : 'primary'" :disabled="!reason.trim()">
                          {{ reasonFor.action.label }}
                        </UiButton>
                      </div>
                    </form>
                    <div v-else class="mt-2.5 flex flex-wrap items-center gap-1.5">
                      <UiButton
                        v-for="action in item.actions"
                        :key="action.key"
                        size="sm"
                        :variant="action.style === 'primary' ? 'primary' : action.style === 'danger' ? 'secondary' : 'secondary'"
                        :class="action.style === 'danger' && 'text-danger'"
                        :loading="decide.isPending.value && decide.variables.value?.item === item && decide.variables.value?.action.key === action.key"
                        @click="run(item, action)"
                        >{{ action.label }}</UiButton
                      >
                      <RouterLink
                        v-if="item.url"
                        :to="companyUrl(item.url)"
                        class="ml-auto inline-flex h-7 items-center gap-1 rounded-[7px] px-2 text-sm font-medium text-muted hover:bg-highlight hover:text-fg"
                      >
                        {{ t("common.open") }}
                        <ArrowUpRight :size="14" />
                      </RouterLink>
                    </div>
                  </div>
                </div>
              </li>
            </TransitionGroup>
          </section>
        </div>
      </div>

      <!-- Notifications -->
      <div v-else class="flex-1 px-3 py-3 md:px-4">
        <div class="mb-2 flex gap-1 rounded-[9px] bg-surface-2 p-0.5" role="radiogroup">
          <button
            v-for="filter in (['unread', 'all'] as const)"
            :key="filter"
            type="button"
            role="radio"
            :aria-checked="notesFilter === filter"
            :class="['h-7 flex-1 rounded-[7px] text-sm font-semibold transition-colors', notesFilter === filter ? 'bg-surface text-fg shadow-raised' : 'text-muted hover:text-fg']"
            @click="notesFilter = filter"
          >
            {{ filter === "unread" ? t("shell.inbox.unread") : t("shell.inbox.all") }}
          </button>
        </div>
        <div v-if="notesSkeleton" class="flex flex-col gap-3 p-2">
          <div v-for="n in 5" :key="n" class="flex gap-3">
            <SkeletonBlock height="28px" width="28px" radius="8px" />
            <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="80%" /><SkeletonBlock width="55%" height="12px" /></div>
          </div>
        </div>
        <ErrorState v-else-if="notes.isError.value" compact :error="notes.error.value" :retry="() => notes.refetch()" />
        <EmptyState
          v-else-if="notes.data.value && notes.data.value.results.length === 0"
          size="sm"
          tone="neutral"
          :icon="BellRing"
          :title="t('shell.inbox.emptyNotesTitle')"
          :description="t('shell.inbox.emptyNotesBody')"
        />
        <ul v-else class="flex flex-col">
          <li v-for="note in notes.data.value?.results ?? []" :key="note.id">
            <component :is="renderers.get(note.kind)" v-if="renderers.has(note.kind)" :notification="note" @open="openNote(note)" />
            <div
              v-else
              role="button"
              tabindex="0"
              class="group relative flex gap-3 rounded-[10px] px-2 py-2.5 outline-offset-[-2px] transition-colors hover:bg-highlight"
              @click="openNote(note)"
              @keydown.enter.self="openNote(note)"
              @keydown.space.self.prevent="openNote(note)"
            >
              <span :class="['grid size-7 shrink-0 place-items-center rounded-[8px]', severityTone[note.severity]]">
                <component :is="severityIcon[note.severity]" :size="15" />
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex items-baseline gap-2">
                  <p :class="['min-w-0 flex-1 truncate text-base', note.read_at ? 'font-medium text-muted' : 'font-semibold text-fg']">{{ note.title }}</p>
                  <span class="shrink-0 text-xs text-subtle">{{ fmt.relative(note.created_at) }}</span>
                </div>
                <p v-if="note.body" class="mt-0.5 line-clamp-2 text-sm text-muted">{{ note.body }}</p>
                <div v-if="note.actions.length && !note.acted_at" class="mt-2 flex gap-1.5" @click.stop>
                  <UiButton
                    v-for="action in note.actions"
                    :key="action.key"
                    size="sm"
                    :variant="action.style === 'primary' ? 'primary' : 'secondary'"
                    :loading="noteAction.isPending.value && noteAction.variables.value?.note.id === note.id && noteAction.variables.value?.key === action.key"
                    @click="runNoteAction(note, action.key)"
                    >{{ action.label }}</UiButton
                  >
                </div>
              </div>
              <span v-if="!note.read_at" class="absolute -left-0.5 top-[19px] size-1.5 rounded-full bg-primary" :aria-label="t('shell.inbox.unread')" />
            </div>
          </li>
        </ul>
      </div>

      <div v-if="inboxPage" class="sticky bottom-0 shrink-0 border-t border-line bg-surface/95 px-4 py-2.5 backdrop-blur md:px-5">
        <RouterLink :to="`/c/${companyId}/inbox`" class="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline" @click="close">
          {{ t("shell.inbox.openPage") }}
          <ArrowUpRight :size="14" />
        </RouterLink>
      </div>
    </div>
  </UiDrawer>
</template>
