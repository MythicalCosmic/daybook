<script setup lang="ts">
/**
 * Reading a page: where it sits, its status, the body, and around it what managers need: who has
 * read it (with a reminder), its versions, its links to routines and tasks, and where it lives.
 * Readers confirm "I've read it" here when the page asks for it. Shortcuts: E edit, H history.
 */
import {
  Archive,
  ArchiveRestore,
  BellRing,
  CheckCheck,
  ChevronRight,
  CircleCheckBig,
  Ellipsis,
  Eye,
  EyeOff,
  FileText,
  FolderInput,
  History,
  Link2,
  ListTodo,
  Pencil,
  Repeat,
  Send,
  X,
} from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import AvatarStack from "@/components/AvatarStack.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { patchQuery } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, useAck, usePage, usePutPage, useReaders, useRefresh } from "../api";
import HistoryDrawer from "../components/HistoryDrawer.vue";
import LinkDialog from "../components/LinkDialog.vue";
import MoveDialog from "../components/MoveDialog.vue";
import PageBody from "../components/PageBody.vue";
import ReadersDrawer from "../components/ReadersDrawer.vue";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const putPage = usePutPage();
const ack = useAck();

const pageId = computed(() => Number(route.params.pageId));
const query = usePage(pageId);
const page = computed(() => query.data.value ?? null);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const canEdit = computed(() => !!page.value?.can_edit);
const showReaders = computed(() => canEdit.value && !!page.value?.published && !!page.value.require_ack && !page.value.archived);
const readers = useReaders(pageId, showReaders);
const base = computed(() => `/c/${company.currentId}/knowledge`);
const linking = ref(false);
const moving = ref(false);
const busy = ref(false);

const mustConfirm = computed(() => !!page.value && page.value.require_ack && page.value.published && !page.value.my_ack?.current);
const unread = computed(() => (readers.data.value?.results ?? []).filter((row) => row.status !== "read"));
const readCount = computed(() => readers.data.value?.counts.read ?? 0);
const audienceTotal = computed(() => {
  const counts = readers.data.value?.counts;
  return counts ? counts.read + counts.outdated + counts.unread : 0;
});

function openDrawer(key: "history" | "readers"): void {
  patchQuery(router, { [key]: "1" }, true);
}

async function act(run: () => Promise<unknown>, done: string): Promise<void> {
  busy.value = true;
  try {
    const result = await run();
    if (result && typeof result === "object" && "id" in result) putPage(result as never);
    void refresh();
    toast.success(done);
  } catch {
    // Shown by the HTTP layer.
  } finally {
    busy.value = false;
  }
}

async function publish(): Promise<void> {
  if (!page.value) return;
  await act(() => knowledgeApi.publish(company.currentId ?? 0, page.value!.id, true), t("knowledge.page.published"));
}

async function unpublish(): Promise<void> {
  if (!page.value) return;
  const answer = await confirm({ title: t("knowledge.page.unpublishTitle"), message: t("knowledge.page.unpublishBody"), confirmLabel: t("knowledge.page.unpublish") });
  if (answer) await act(() => knowledgeApi.unpublish(company.currentId ?? 0, page.value!.id), t("knowledge.page.unpublished"));
}

async function archive(): Promise<void> {
  if (!page.value) return;
  const id = page.value.id;
  const answer = await confirm({
    title: t("knowledge.page.archiveTitle", { title: page.value.title }),
    message: page.value.children.length ? t("knowledge.page.archiveBodyChildren", { n: page.value.children.length }) : t("knowledge.page.archiveBody"),
    confirmLabel: t("knowledge.page.archive"),
    tone: "danger",
  });
  if (!answer) return;
  await knowledgeApi.archive(company.currentId ?? 0, id);
  await refresh();
  toast.success(t("knowledge.page.archived"), {
    action: { label: t("common.undo"), onClick: () => act(() => knowledgeApi.restore(company.currentId ?? 0, id), t("knowledge.page.restored")) },
  });
  void router.push(`${base.value}/s/${page.value.space.id}`);
}

async function remind(): Promise<void> {
  if (!page.value) return;
  busy.value = true;
  try {
    const { reminded } = await knowledgeApi.remind(company.currentId ?? 0, page.value.id);
    toast.success(reminded ? t("knowledge.readers.reminded", { n: reminded }, reminded) : t("knowledge.readers.nobodyToRemind"));
    void refresh();
  } catch {
    // Shown by the HTTP layer.
  } finally {
    busy.value = false;
  }
}

async function unlink(linkId: number): Promise<void> {
  if (!page.value) return;
  await knowledgeApi.unlink(company.currentId ?? 0, linkId);
  putPage({ ...page.value, links: page.value.links.filter((link) => link.id !== linkId) });
  void refresh();
}

function confirmRead(): void {
  if (!page.value) return;
  ack.mutate(page.value.id, { onSuccess: () => toast.success(t("knowledge.page.thanks")) });
}

const menu = computed<MenuEntry[]>(() => {
  const current = page.value;
  if (!current) return [];
  const entries: MenuEntry[] = [
    { label: t("knowledge.history.title"), icon: History, shortcut: "H", onSelect: () => openDrawer("history") },
    { label: t("knowledge.links.add"), icon: Link2, onSelect: () => (linking.value = true) },
    { label: t("knowledge.move.title"), icon: FolderInput, onSelect: () => (moving.value = true) },
  ];
  if (current.published) entries.push({ label: t("knowledge.page.unpublish"), icon: EyeOff, onSelect: () => void unpublish() });
  entries.push({ type: "separator" });
  entries.push(
    current.archived
      ? { label: t("knowledge.page.restore"), icon: ArchiveRestore, onSelect: () => void act(() => knowledgeApi.restore(company.currentId ?? 0, current.id), t("knowledge.page.restored")) }
      : { label: t("knowledge.page.archive"), icon: Archive, danger: true, onSelect: () => void archive() },
  );
  return entries;
});

useHotkey("e", () => canEdit.value && void router.push(`${base.value}/p/${pageId.value}/edit`), { description: "knowledge.hotkey.edit", group: "page" });
useHotkey("h", () => canEdit.value && openDrawer("history"), { description: "knowledge.hotkey.history", group: "page" });
</script>

<template>
  <div>
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="skeleton || !page" class="flex max-w-[760px] flex-col gap-4">
      <SkeletonBlock width="30%" height="14px" />
      <SkeletonBlock width="70%" height="34px" />
      <SkeletonBlock width="45%" height="20px" />
      <SkeletonBlock :lines="7" class="mt-4" />
    </div>
    <div v-else class="grid gap-8 xl:grid-cols-[minmax(0,1fr)_288px]">
      <div class="min-w-0">
        <!-- Where it sits -->
        <nav class="mb-3 flex min-w-0 flex-wrap items-center gap-1 text-sm text-muted" :aria-label="t('knowledge.page.path')">
          <RouterLink :to="`${base}/s/${page.space.id}`" class="inline-flex min-w-0 items-center gap-1 rounded-[6px] px-1 py-0.5 font-medium hover:bg-highlight hover:text-fg">
            <span aria-hidden="true">{{ page.space.icon }}</span><span class="truncate">{{ page.space.name }}</span>
          </RouterLink>
          <template v-for="crumb in page.breadcrumbs" :key="crumb.id">
            <ChevronRight :size="13" class="shrink-0 text-subtle" aria-hidden="true" />
            <RouterLink :to="`${base}/p/${crumb.id}`" class="max-w-[220px] truncate rounded-[6px] px-1 py-0.5 hover:bg-highlight hover:text-fg">{{ crumb.emoji }} {{ crumb.title }}</RouterLink>
          </template>
        </nav>

        <header class="mb-5 flex flex-col gap-3">
          <div class="flex flex-wrap items-start gap-x-4 gap-y-3">
            <div class="flex min-w-[min(100%,280px)] flex-1 items-start gap-3">
              <span v-if="page.emoji" class="text-[34px] leading-[1.15]" aria-hidden="true">{{ page.emoji }}</span>
              <h1 class="min-w-0 text-xl font-semibold tracking-[-0.015em] text-fg md:text-2xl">{{ page.title }}</h1>
            </div>
            <div class="flex shrink-0 flex-wrap items-center gap-2">
              <UiButton v-if="mustConfirm && !canEdit" variant="primary" :icon="CircleCheckBig" :loading="ack.isPending.value" @click="confirmRead">{{ t("knowledge.page.iveRead") }}</UiButton>
              <template v-if="canEdit">
                <UiButton v-if="!page.published && !page.archived" :icon="Send" :loading="busy" @click="publish">{{ t("knowledge.page.publish") }}</UiButton>
                <UiButton variant="primary" :icon="Pencil" :to="`${base}/p/${page.id}/edit`" kbd="E">{{ t("common.edit") }}</UiButton>
                <DropdownMenu :items="menu">
                  <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" variant="secondary" /></template>
                </DropdownMenu>
              </template>
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-2 text-sm text-muted">
            <StatusPill v-if="page.archived" size="sm" tone="warning" :label="t('knowledge.archived')" />
            <StatusPill v-else-if="page.published" size="sm" tone="success" :icon="Eye" :dot="false" :label="t('knowledge.page.live')" />
            <StatusPill v-else size="sm" tone="neutral" :label="t('knowledge.draft')" />
            <StatusPill v-if="page.require_ack" size="sm" tone="primary" :icon="CheckCheck" :dot="false" :label="t('knowledge.mustRead')" />
            <span>{{ t("knowledge.history.versionN", { v: page.version }) }}</span>
            <span aria-hidden="true">·</span>
            <span>{{ t("knowledge.page.updated") }} <RelativeTime :value="page.updated_at" /><template v-if="page.updated_by"> · {{ page.updated_by.name }}</template></span>
          </div>
        </header>

        <InlineAlert v-if="page.archived" tone="warning" :title="t('knowledge.page.archivedTitle')" :description="t('knowledge.page.archivedBody')" class="mb-5" />
        <InlineAlert v-else-if="!page.published" tone="neutral" :title="t('knowledge.page.draftTitle')" :description="t('knowledge.page.draftBody')" class="mb-5" />
        <InlineAlert v-else-if="mustConfirm" tone="info" :title="t('knowledge.page.confirmTitle')" :description="t('knowledge.page.confirmBody')" class="mb-5">
          <template #actions>
            <UiButton size="sm" variant="primary" :icon="CircleCheckBig" :loading="ack.isPending.value" @click="confirmRead">{{ t("knowledge.page.iveRead") }}</UiButton>
          </template>
        </InlineAlert>
        <InlineAlert v-else-if="page.require_ack && page.my_ack?.current" tone="success" :title="t('knowledge.page.confirmedTitle')" :description="t('knowledge.page.confirmedBody', { v: page.my_ack.version, when: fmt.relative(page.my_ack.at) })" class="mb-5" />

        <div class="ui-card px-5 py-6 md:px-9 md:py-8">
          <PageBody v-if="page.body" :html="page.body" />
          <div v-else class="flex flex-col items-center gap-2 py-10 text-center">
            <FileText :size="26" class="text-subtle" />
            <p class="text-base font-semibold text-fg">{{ t("knowledge.page.emptyTitle") }}</p>
            <p class="text-sm text-muted">{{ canEdit ? t("knowledge.page.emptyBody") : t("knowledge.page.emptyReader") }}</p>
            <UiButton v-if="canEdit" size="sm" variant="primary" :icon="Pencil" :to="`${base}/p/${page.id}/edit`" class="mt-2">{{ t("knowledge.page.startWriting") }}</UiButton>
          </div>
        </div>

        <section v-if="page.children.length" class="mt-6" :aria-label="t('knowledge.page.subpages')">
          <h2 class="mb-2 text-sm font-semibold text-muted">{{ t("knowledge.page.subpages") }}</h2>
          <div class="grid gap-2 sm:grid-cols-2">
            <RouterLink v-for="child in page.children" :key="child.id" :to="`${base}/p/${child.id}`" class="ui-card flex items-center gap-3 px-3 py-2.5 transition-shadow hover:shadow-raised">
              <span class="text-[18px]" aria-hidden="true">{{ child.emoji || "📄" }}</span>
              <span class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{{ child.title }}</span>
              <StatusPill v-if="!child.published" size="sm" tone="neutral" :label="t('knowledge.draft')" />
              <ChevronRight :size="15" class="text-subtle" />
            </RouterLink>
          </div>
        </section>
      </div>

      <!-- The rail: readers, links, details -->
      <aside class="flex min-w-0 flex-col gap-4 xl:sticky xl:top-5 xl:self-start">
        <section v-if="showReaders" class="ui-card p-4" :aria-label="t('knowledge.readers.title')">
          <div class="flex items-center gap-3">
            <ProgressRing :value="readCount" :max="audienceTotal || 1" :size="48" tone="auto" show-value />
            <div class="min-w-0 flex-1">
              <h2 class="text-sm font-semibold text-fg">{{ t("knowledge.readers.title") }}</h2>
              <p class="text-xs text-muted">{{ readers.data.value ? t("knowledge.readers.summary", { read: readCount, total: audienceTotal }) : t("common.loading") }}</p>
            </div>
          </div>
          <div v-if="unread.length" class="mt-3 flex items-center gap-2">
            <AvatarStack :people="unread.slice(0, 6).map((row) => ({ id: row.member.id, name: row.member.name, photo_url: row.member.photo_url }))" :max="5" :size="26" />
            <span class="min-w-0 flex-1 truncate text-xs text-muted">{{ t("knowledge.readers.notYet", { n: unread.length }, unread.length) }}</span>
          </div>
          <p v-else-if="readers.data.value && audienceTotal" class="mt-3 flex items-center gap-1.5 text-xs font-semibold text-success"><CheckCheck :size="14" />{{ t("knowledge.readers.everyone") }}</p>
          <div class="mt-3 flex gap-2">
            <UiButton size="sm" block @click="openDrawer('readers')">{{ t("knowledge.readers.seeAll") }}</UiButton>
            <UiButton v-if="unread.length" size="sm" variant="soft" :icon="BellRing" block :loading="busy" @click="remind">{{ t("knowledge.readers.remind") }}</UiButton>
          </div>
        </section>

        <section v-if="page.links.length || canEdit" class="ui-card p-4" :aria-label="t('knowledge.links.title')">
          <div class="mb-2 flex items-center gap-2">
            <h2 class="flex-1 text-sm font-semibold text-fg">{{ t("knowledge.links.title") }}</h2>
            <IconButton v-if="canEdit" :icon="Link2" :label="t('knowledge.links.add')" size="sm" @click="linking = true" />
          </div>
          <p v-if="!page.links.length" class="text-xs text-muted">{{ t("knowledge.links.emptyHint") }}</p>
          <ul v-else class="flex flex-col gap-1">
            <li v-for="link in page.links" :key="link.id" class="group flex items-center gap-2 rounded-[8px] px-1.5 py-1.5 hover:bg-highlight">
              <span :class="['grid size-7 shrink-0 place-items-center rounded-[7px]', link.target_type === 'routine' ? 'bg-info-soft text-info' : 'bg-accent-soft text-accent-fg']" aria-hidden="true">
                <Repeat v-if="link.target_type === 'routine'" :size="14" />
                <ListTodo v-else :size="14" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium text-fg">{{ link.target_title || `#${link.target_id}` }}</span>
                <span class="block text-[11px] text-muted">{{ t(`knowledge.links.${link.target_type}`) }}</span>
              </span>
              <IconButton v-if="canEdit" :icon="X" :label="t('knowledge.links.remove')" size="sm" :tooltip="false" class="opacity-0 group-hover:opacity-100 focus:opacity-100" @click="unlink(link.id)" />
            </li>
          </ul>
        </section>

        <section class="ui-card p-4 text-sm" :aria-label="t('knowledge.page.details')">
          <h2 class="mb-2 text-sm font-semibold text-fg">{{ t("knowledge.page.details") }}</h2>
          <dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5">
            <dt class="text-muted">{{ t("knowledge.page.space") }}</dt>
            <dd class="truncate text-fg">{{ page.space.icon }} {{ page.space.name }}</dd>
            <template v-if="page.published_at">
              <dt class="text-muted">{{ t("knowledge.page.publishedAt") }}</dt>
              <dd class="text-fg">{{ fmt.instant(page.published_at, "date") }}</dd>
            </template>
            <dt class="text-muted">{{ t("knowledge.page.createdBy") }}</dt>
            <dd class="truncate text-fg">{{ page.created_by?.name ?? "—" }}</dd>
            <dt class="text-muted">{{ t("knowledge.page.version") }}</dt>
            <dd class="text-fg">
              <button v-if="canEdit" type="button" class="inline-flex items-center gap-1 font-medium text-accent-fg hover:underline" @click="openDrawer('history')">
                {{ page.version }} <History :size="13" />
              </button>
              <span v-else>{{ page.version }}</span>
            </dd>
          </dl>
        </section>
      </aside>

      <template v-if="canEdit">
        <HistoryDrawer :page="page" />
        <ReadersDrawer :page="page" />
        <LinkDialog v-model:open="linking" :page="page" />
        <MoveDialog v-model:open="moving" :page="page" />
      </template>
    </div>
  </div>
</template>
