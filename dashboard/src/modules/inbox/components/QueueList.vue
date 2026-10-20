<script setup lang="ts">
/**
 * "Needs you": every decision waiting for the person, grouped by kind, decided in place. Actions
 * that need a reason ask for it first; a decided item leaves at once (and returns if the server
 * refuses). J/K move between items, Enter opens the record.
 */
import { ArrowUpRight, BellRing, ListFilter } from "@lucide/vue";
import { computed, nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useQueue, useQueueDecision } from "../api";
import { queueKey, type QueueAction, type QueueItem } from "../types";

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();

const kind = useRouteState("kind", rs.string(""));
// All kinds come from the unfiltered queue; the list shows the chosen one.
const all = useQueue(null);
const kinds = computed(() => all.data.value?.kinds ?? []);
const items = computed(() => (all.data.value?.results ?? []).filter((item) => !kind.value || item.kind === kind.value));
const groups = computed(() =>
  kinds.value
    .filter((entry) => !kind.value || entry.kind === kind.value)
    .map((entry) => ({ ...entry, items: items.value.filter((item) => item.kind === entry.kind) }))
    .filter((group) => group.items.length),
);
const skeleton = useDelayedPending(computed(() => all.isPending.value));

const decide = useQueueDecision();
const pendingKey = ref<string | null>(null);

async function run(item: QueueItem, action: QueueAction): Promise<void> {
  let reason: string | undefined;
  if (action.needs_reason) {
    const answer = await confirm({
      title: action.label,
      message: item.title,
      reason: "required",
      tone: action.style === "danger" ? "danger" : "primary",
      confirmLabel: action.label,
    });
    if (!answer) return;
    reason = answer.reason;
  }
  pendingKey.value = `${queueKey(item)}:${action.key}`;
  try {
    await decide.mutateAsync({ item, action, reason });
    toast.success(t("inbox.done", { action: action.label }), { description: item.title });
  } catch {
    // The HTTP layer toasted the server's message; the item is back in the list.
  } finally {
    pendingKey.value = null;
  }
}

function link(url: string): string {
  if (!url) return `/c/${company.currentId}`;
  return url.startsWith("/c/") ? url : `/c/${company.currentId}/${url.replace(/^\/+/, "")}`;
}

// Keyboard: J/K between items, Enter opens.
const list = ref<HTMLElement | null>(null);
function focusItem(step: 1 | -1): void {
  const cards = [...(list.value?.querySelectorAll<HTMLElement>("[data-queue-item]") ?? [])];
  if (!cards.length) return;
  const index = cards.indexOf(document.activeElement as HTMLElement);
  const next = cards[Math.min(cards.length - 1, Math.max(0, index === -1 ? 0 : index + step))]!;
  next.focus();
  next.scrollIntoView?.({ block: "nearest" });
}
useHotkey("j", () => focusItem(1), { description: "inbox.keys.next", group: "page" });
useHotkey("k", () => focusItem(-1), { description: "inbox.keys.previous", group: "page" });

function onKeydown(event: KeyboardEvent, item: QueueItem): void {
  if (event.key === "Enter" && event.target === event.currentTarget && item.url) void router.push(link(item.url));
}

async function pickKind(next: string): Promise<void> {
  kind.value = next;
  await nextTick();
}
</script>

<template>
  <div class="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
    <!-- Kinds -->
    <nav :aria-label="t('inbox.kinds')" class="min-w-0">
      <p class="mb-2 hidden items-center gap-1.5 px-2 text-xs font-semibold uppercase tracking-[0.05em] text-subtle lg:flex"><ListFilter :size="13" />{{ t("inbox.kinds") }}</p>
      <div class="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1 lg:mx-0 lg:flex-col lg:overflow-visible lg:px-0">
        <button
          type="button"
          :aria-pressed="!kind"
          :class="['flex shrink-0 items-center gap-2 rounded-[8px] px-2.5 py-1.5 text-left text-sm font-medium transition-colors', !kind ? 'bg-surface text-fg shadow-raised lg:bg-accent-soft lg:text-accent-fg lg:shadow-none' : 'text-muted hover:bg-highlight hover:text-fg']"
          @click="pickKind('')"
        >
          <span class="min-w-0 flex-1 truncate">{{ t("inbox.allKinds") }}</span>
          <UiBadge :count="all.data.value?.total ?? 0" :tone="!kind ? 'primary' : 'neutral'" />
        </button>
        <button
          v-for="entry in kinds"
          :key="entry.kind"
          type="button"
          :aria-pressed="kind === entry.kind"
          :class="['flex shrink-0 items-center gap-2 rounded-[8px] px-2.5 py-1.5 text-left text-sm font-medium transition-colors', kind === entry.kind ? 'bg-surface text-fg shadow-raised lg:bg-accent-soft lg:text-accent-fg lg:shadow-none' : 'text-muted hover:bg-highlight hover:text-fg']"
          @click="pickKind(entry.kind)"
        >
          <span class="min-w-0 flex-1 truncate">{{ entry.label }}</span>
          <UiBadge :count="entry.count" :tone="kind === entry.kind ? 'primary' : 'neutral'" />
        </button>
      </div>
    </nav>

    <!-- Items -->
    <div ref="list" class="min-w-0">
      <div v-if="skeleton" class="flex flex-col gap-2">
        <div v-for="n in 5" :key="n" class="ui-card flex gap-3 p-4">
          <SkeletonBlock circle height="36px" />
          <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="55%" /><SkeletonBlock width="35%" height="12px" /><SkeletonBlock width="160px" height="28px" radius="8px" /></div>
        </div>
      </div>
      <ErrorState v-else-if="all.isError.value" class="ui-card" :error="all.error.value" :retry="() => all.refetch()" />
      <div v-else-if="all.data.value && !groups.length" class="ui-card">
        <EmptyState tone="success" :title="t('inbox.emptyNeedsTitle')" :description="t('inbox.emptyNeedsBody')" />
      </div>
      <div v-else class="flex flex-col gap-6">
        <section v-for="group in groups" :key="group.kind" :aria-label="group.label">
          <h2 class="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
            {{ group.label }}
            <span class="text-xs font-medium text-subtle">{{ group.items.length }}</span>
          </h2>
          <TransitionGroup name="list" tag="ul" class="relative flex flex-col gap-2">
            <li
              v-for="item in group.items"
              :key="queueKey(item)"
              data-queue-item
              tabindex="0"
              class="ui-card group/item flex gap-3.5 p-4 outline-offset-2 transition-colors hover:border-line-strong focus-visible:border-primary"
              @keydown="onKeydown($event, item)"
            >
              <UserAvatar v-if="item.actor" :name="item.actor.name" :src="item.actor.photo_url" :size="36" />
              <span v-else class="grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg"><BellRing :size="16" /></span>
              <div class="min-w-0 flex-1">
                <div class="flex items-start gap-3">
                  <div class="min-w-0 flex-1">
                    <p class="text-base font-semibold leading-5 text-fg">{{ item.title }}</p>
                    <p v-if="item.subtitle" class="mt-0.5 text-sm text-muted">{{ item.subtitle }}</p>
                  </div>
                  <RelativeTime :value="item.created_at" class="shrink-0 pt-0.5 text-xs text-subtle" />
                </div>
                <ProofThumb v-if="item.photo_url" :src="item.photo_url" size="lg" class="mt-3" />
                <div class="mt-3 flex flex-wrap items-center gap-1.5">
                  <UiButton
                    v-for="action in item.actions"
                    :key="action.key"
                    size="sm"
                    :variant="action.style === 'primary' ? 'primary' : 'secondary'"
                    :class="action.style === 'danger' && 'hover:!text-danger'"
                    :loading="pendingKey === `${queueKey(item)}:${action.key}`"
                    :disabled="!!pendingKey && pendingKey.startsWith(queueKey(item))"
                    @click="run(item, action)"
                    >{{ action.label }}</UiButton
                  >
                  <RouterLink
                    v-if="item.url"
                    :to="link(item.url)"
                    class="ml-auto inline-flex h-7 items-center gap-1 rounded-[7px] px-2 text-sm font-medium text-muted transition-colors hover:bg-highlight hover:text-fg"
                  >
                    {{ t("common.open") }}<ArrowUpRight :size="14" />
                  </RouterLink>
                </div>
              </div>
            </li>
          </TransitionGroup>
        </section>
      </div>
    </div>
  </div>
</template>
