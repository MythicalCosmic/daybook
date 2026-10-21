<script setup lang="ts">
/**
 * Writing a page (new or existing). The title and emoji on top, the rich editor below, and on the
 * side the page's settings: must readers confirm it, "ask everyone to read it again", a note for
 * the version, Telegram news on publish. ⌘/Ctrl+S saves; leaving with unsaved changes asks first.
 * Saving checks the version the editor started from, so two editors never overwrite each other.
 */
import { ArrowLeft, Check, CircleAlert, Eye, Save, Send } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import type { SelectOption } from "@/components/options";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, usePage, usePutPage, useRefresh, useSpaces, useTree } from "../api";
import EmojiPicker from "../components/EmojiPicker.vue";
import RichEditor from "../components/editor/RichEditor.vue";
import { flatten } from "../lib";
import type { PageDetail } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const putPage = usePutPage();
const cid = computed(() => company.currentId ?? 0);
const base = computed(() => `/c/${cid.value}/knowledge`);

const pageId = computed(() => (route.params.pageId ? Number(route.params.pageId) : null));
const isNew = computed(() => pageId.value === null);
const query = usePage(pageId);
const spaces = useSpaces();

const draft = reactive({ title: "", emoji: "", body: "", requireAck: false, note: "", reread: false, notify: true, space: 0, parent: 0 });
const baseline = ref("");
const loaded = ref(false);
const saving = ref(false);
const savedAt = ref<string | null>(null);
const titleEl = ref<HTMLTextAreaElement | null>(null);

const snapshot = () => JSON.stringify([draft.title, draft.emoji, draft.body, draft.requireAck]);
const dirty = computed(() => loaded.value && snapshot() !== baseline.value);
const page = computed<PageDetail | null>(() => query.data.value ?? null);
const published = computed(() => !!page.value?.published);

function load(from: PageDetail | null): void {
  if (from) {
    draft.title = from.title;
    draft.emoji = from.emoji;
    draft.body = from.body;
    draft.requireAck = from.require_ack;
    draft.space = from.space.id;
    draft.parent = from.parent_id ?? 0;
  } else {
    draft.title = "";
    draft.emoji = "";
    draft.body = "";
    draft.requireAck = false;
    draft.space = Number(route.query.space) || spaces.data.value?.[0]?.id || 0;
    draft.parent = Number(route.query.parent) || 0;
  }
  draft.note = "";
  draft.reread = false;
  baseline.value = snapshot();
  loaded.value = true;
  void nextTick(resizeTitle);
}

watch(
  () => [query.data.value?.id, isNew.value] as const,
  () => {
    if (isNew.value) load(null);
    else if (query.data.value && (!loaded.value || !dirty.value)) load(query.data.value);
  },
  { immediate: true },
);
watch(
  () => spaces.data.value,
  (list) => {
    if (isNew.value && !draft.space && list?.length) draft.space = Number(route.query.space) || list[0]!.id;
  },
  { immediate: true },
);

// Where a new page goes.
const tree = useTree(computed(() => (isNew.value && draft.space ? draft.space : null)));
const spaceOptions = computed<SelectOption<number>[]>(() => (spaces.data.value ?? []).map((space) => ({ value: space.id, label: `${space.icon} ${space.name}`.trim() })));
const parentOptions = computed<SelectOption<number>[]>(() => [
  { value: 0, label: t("knowledge.move.top") },
  ...flatten(tree.data.value ?? [])
    .filter(({ depth }) => depth < 3)
    .map(({ node, depth }) => ({ value: node.id, label: `${depth ? "↳ ".padStart(depth * 2 + 2, " ") : ""}${node.emoji} ${node.title}`.trim() })),
]);
watch(
  () => draft.space,
  (next, previous) => {
    if (previous && next !== previous) draft.parent = 0;
  },
);

function resizeTitle(): void {
  const el = titleEl.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

async function upload(file: File) {
  return knowledgeApi.upload(cid.value, file, pageId.value);
}

async function save(options: { quiet?: boolean } = {}): Promise<PageDetail | null> {
  if (!draft.title.trim()) {
    toast.error(t("knowledge.editor.needTitle"));
    titleEl.value?.focus();
    return null;
  }
  saving.value = true;
  try {
    let result: PageDetail;
    if (isNew.value) {
      if (!draft.space) {
        toast.error(t("knowledge.editor.needSpace"));
        return null;
      }
      result = await knowledgeApi.createPage(cid.value, {
        space: draft.space,
        parent: draft.parent || null,
        title: draft.title.trim(),
        emoji: draft.emoji,
        body: draft.body,
        require_ack: draft.requireAck,
      });
    } else {
      result = await knowledgeApi.savePage(cid.value, pageId.value!, {
        title: draft.title.trim(),
        emoji: draft.emoji,
        body: draft.body,
        require_ack: draft.requireAck,
        note: draft.note,
        base_version: page.value?.version ?? null,
        reread: published.value && draft.requireAck && draft.reread,
        notify: draft.notify,
      });
    }
    putPage(result);
    draft.note = "";
    draft.reread = false;
    baseline.value = snapshot();
    savedAt.value = new Date().toISOString();
    void refresh();
    if (!options.quiet) toast.success(t("knowledge.editor.saved"));
    if (isNew.value) await router.replace(`${base.value}/p/${result.id}/edit`);
    return result;
  } catch {
    // The HTTP layer showed why (a newer version, a missing title…).
    return null;
  } finally {
    saving.value = false;
  }
}

async function publish(): Promise<void> {
  const result = dirty.value || isNew.value ? await save({ quiet: true }) : page.value;
  if (!result) return;
  saving.value = true;
  try {
    const done = await knowledgeApi.publish(cid.value, result.id, draft.notify);
    putPage(done);
    void refresh();
    toast.success(t("knowledge.page.published"), { description: draft.notify ? t("knowledge.editor.notified") : undefined });
    baseline.value = snapshot();
    await router.push(`${base.value}/p/${done.id}`);
  } catch {
    // Shown by the HTTP layer.
  } finally {
    saving.value = false;
  }
}

async function done(): Promise<void> {
  if (dirty.value && !(await save({ quiet: true }))) return;
  void router.push(pageId.value ? `${base.value}/p/${pageId.value}` : base.value);
}

const backTo = computed(() => (pageId.value ? `${base.value}/p/${pageId.value}` : draft.space ? `${base.value}/s/${draft.space}` : base.value));

useHotkey("mod+s", () => void save(), { allowInInputs: true, description: "knowledge.hotkey.save", group: "page" });

onBeforeRouteLeave(async (to) => {
  if (!dirty.value || saving.value) return true;
  // Saving a new page moves to its edit address: that isn't leaving.
  if (to.name === "knowledge.edit" && isNew.value) return true;
  const answer = await confirm({
    title: t("common.unsaved"),
    message: t("knowledge.editor.leaveBody"),
    confirmLabel: t("common.discard"),
    tone: "danger",
  });
  return !!answer;
});

function beforeUnload(event: BeforeUnloadEvent): void {
  if (!dirty.value) return;
  event.preventDefault();
}
onMounted(() => window.addEventListener("beforeunload", beforeUnload));
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));

const status = computed(() => {
  if (saving.value) return { tone: "info" as const, text: t("knowledge.editor.saving") };
  if (dirty.value) return { tone: "warning" as const, text: t("knowledge.editor.unsaved") };
  if (savedAt.value) return { tone: "success" as const, text: t("knowledge.editor.savedAt", { time: fmt.instant(savedAt.value, "time") }) };
  return null;
});
</script>

<template>
  <div class="pb-10">
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <!-- Sticky bar -->
      <div class="sticky top-[calc(var(--topbar-h)+var(--safe-top))] z-20 -mx-4 mb-6 flex items-center gap-2 border-b border-line bg-canvas/90 px-4 py-2.5 backdrop-blur md:top-0 md:-mx-8 md:-mt-7 md:bg-surface/90 md:px-8">
        <IconButton :icon="ArrowLeft" :label="t('common.back')" :to="backTo" variant="ghost" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-fg">{{ isNew ? t("knowledge.editor.newTitle") : draft.title || t("knowledge.editor.untitled") }}</p>
          <p class="flex items-center gap-1.5 text-xs text-muted">
            <template v-if="status">
              <Check v-if="status.tone === 'success'" :size="12" class="text-success" />
              <CircleAlert v-else-if="status.tone === 'warning'" :size="12" class="text-warning" />
              {{ status.text }}
            </template>
            <template v-else>{{ isNew ? t("knowledge.editor.newHint") : published ? t("knowledge.editor.liveHint") : t("knowledge.editor.draftHint") }}</template>
          </p>
        </div>
        <StatusPill v-if="!isNew" size="sm" class="hidden sm:inline-flex" :tone="published ? 'success' : 'neutral'" :label="published ? t('knowledge.page.live') : t('knowledge.draft')" />
        <UiButton v-if="!isNew" variant="ghost" :icon="Eye" class="hidden md:inline-flex" @click="done">{{ t("knowledge.editor.done") }}</UiButton>
        <UiButton :variant="published ? 'primary' : 'secondary'" :icon="Save" :loading="saving && published" :disabled="saving || (!dirty && !isNew)" @click="save()">
          {{ t("common.save") }}
        </UiButton>
        <UiButton v-if="!published" variant="primary" :icon="Send" :loading="saving" @click="publish">{{ t("knowledge.page.publish") }}</UiButton>
      </div>

      <div v-if="!isNew && !page" class="mx-auto flex max-w-[760px] flex-col gap-4">
        <SkeletonBlock width="60%" height="40px" />
        <SkeletonBlock height="40px" radius="10px" />
        <SkeletonBlock :lines="8" />
      </div>

      <div v-else class="mx-auto grid max-w-[1160px] gap-8 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div class="min-w-0 xl:pl-6">
          <div class="mb-4 flex items-start gap-3">
            <EmojiPicker v-model="draft.emoji" size="lg" :label="t('knowledge.emoji.pick')" />
            <textarea
              ref="titleEl"
              v-model="draft.title"
              rows="1"
              maxlength="200"
              :placeholder="t('knowledge.editor.titlePlaceholder')"
              :aria-label="t('knowledge.editor.titleLabel')"
              class="min-w-0 flex-1 resize-none overflow-hidden border-0 bg-transparent p-0 pt-1.5 text-xl font-semibold tracking-[-0.015em] text-fg outline-none placeholder:text-subtle md:text-2xl"
              @input="resizeTitle"
              @keydown.enter.prevent
            />
          </div>
          <RichEditor v-model="draft.body" :upload="upload" :autofocus="!isNew" style="--kb-toolbar-top: 60px" />
        </div>

        <aside class="flex min-w-0 flex-col gap-4 xl:sticky xl:top-[76px] xl:self-start">
          <section class="ui-card flex flex-col gap-4 p-4" :aria-label="t('knowledge.editor.settings')">
            <h2 class="text-sm font-semibold text-fg">{{ t("knowledge.editor.settings") }}</h2>
            <template v-if="isNew">
              <FormField :label="t('knowledge.move.space')">
                <SelectBox v-model="draft.space" :options="spaceOptions" />
              </FormField>
              <FormField :label="t('knowledge.move.under')">
                <SelectBox v-model="draft.parent" :options="parentOptions" />
              </FormField>
            </template>
            <ToggleSwitch v-model="draft.requireAck" layout="row" :label="t('knowledge.editor.requireAck')" :description="t('knowledge.editor.requireAckHint')" />
            <template v-if="published">
              <ToggleSwitch v-if="draft.requireAck" v-model="draft.reread" layout="row" :label="t('knowledge.editor.reread')" :description="t('knowledge.editor.rereadHint')" />
              <FormField :label="t('knowledge.editor.note')" :hint="t('knowledge.editor.noteHint')" optional>
                <TextInput v-model="draft.note" :maxlength="200" :placeholder="t('knowledge.editor.notePlaceholder')" />
              </FormField>
            </template>
            <ToggleSwitch v-if="!published || draft.reread" v-model="draft.notify" layout="row" :label="t('knowledge.editor.notify')" :description="t('knowledge.editor.notifyHint')" />
          </section>
          <InlineAlert v-if="published && draft.requireAck && draft.reread" tone="info" size="sm" :description="t('knowledge.editor.rereadNote')" />
          <section class="ui-card p-4 text-xs text-muted">
            <p class="mb-1.5 font-semibold text-fg">{{ t("knowledge.editor.tipsTitle") }}</p>
            <ul class="flex list-disc flex-col gap-1 pl-4">
              <li>{{ t("knowledge.editor.tip1") }}</li>
              <li>{{ t("knowledge.editor.tip2") }}</li>
              <li>{{ t("knowledge.editor.tip3") }}</li>
            </ul>
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>
