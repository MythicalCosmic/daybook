<script setup lang="ts">
/**
 * ⌘K (plan §6.5): a reka-ui Combobox in a Dialog. "Jump to" (allowed pages, fuzzy over the titles in
 * uz, ru and en at once), "Results" (server search, 150 ms debounce, rendered by module components
 * when they provide one), "Actions" (module commands and the shell's own), "Switch company", and
 * "Ask AI: …" as the last row when the assistant is available.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import {
  ArrowRight,
  Building2,
  Clock3,
  CornerDownLeft,
  FileText,
  Inbox,
  Keyboard,
  LayoutGrid,
  Link2,
  LogOut,
  Monitor,
  Moon,
  PanelLeft,
  Plus,
  Rows3,
  Search,
  Sparkles,
  Sun,
} from "@lucide/vue";
import { refDebounced } from "@vueuse/core";
import Fuse from "fuse.js";
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxLabel,
  ComboboxRoot,
  ComboboxViewport,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
  VisuallyHidden,
} from "reka-ui";
import { computed, onBeforeUnmount, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { pathInCompany } from "@/app/navigation";
import { changeLanguage } from "@/app/providers";
import { switchTheme } from "@/app/theme";
import { keys } from "@/api/keys";
import { shellApi } from "@/api/shell";
import { LANGUAGES, type SearchHit } from "@/api/types";
import CompanyLogo from "@/components/CompanyLogo.vue";
import { iconForKind } from "@/components/kindIcons";
import KbdKey from "@/components/KbdKey.vue";
import UiSpinner from "@/components/UiSpinner.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { allowed, isModuleVisible } from "@/core/access";
import { hasExtension } from "@/core/extensions";
import { modules, type Command, type CommandCtx } from "@/core/modules";
import type { NavGroup } from "@/core/nav";
import { allLanguages, loadAllLanguages, loadModuleTitles } from "@/i18n";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useCompanyStore } from "@/stores/company";
import { usePaletteStore } from "@/stores/palette";
import { useUiStore } from "@/stores/ui";

import { searchTypeKey } from "./searchTypes";

const props = defineProps<{ groups: NavGroup[]; aiAvailable: boolean }>();
const emit = defineEmits<{ openInbox: []; signOut: [] }>();

const { t, te, locale } = useI18n();
// Titles match in any of the three languages: the other two shell dictionaries and every module's
// titles (one small chunk, not their whole dictionaries) load now.
void Promise.all([loadAllLanguages(), loadModuleTitles()]).catch(() => undefined);
const { isPhone } = useBreakpoints();
const route = useRoute();
const router = useRouter();
const palette = usePaletteStore();
const company = useCompanyStore();
const ui = useUiStore();

type Section = "recent" | "jump" | "results" | "actions" | "companies" | "ai";

interface Item {
  id: string;
  section: Section;
  title: string;
  subtitle?: string;
  icon?: Component;
  logo?: { name: string; src: string | null };
  /** People results show the person's avatar instead of an icon. */
  person?: string;
  keywords: string[];
  shortcut?: string;
  /** Jump items: the page path, and whether it is a module's first page. */
  path?: string;
  head?: boolean;
  hit?: SearchHit;
  renderer?: Component;
  run: () => unknown;
}

const query = ref("");
const debounced = refDebounced(query, 150);
const trimmed = computed(() => query.value.trim());

/**
 * Keys typed between ⌘K and the field taking focus (the dialog mounts and focuses a frame later)
 * would be lost, and "CHL-8" would search "HL-8": while the palette is open and its field isn't
 * focused yet, printable keys go into the query and focus moves to the field.
 */
function catchEarlyKeys(event: KeyboardEvent): void {
  if (!palette.open || event.defaultPrevented || event.isComposing) return;
  if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
  const input = document.querySelector<HTMLInputElement>("[data-palette-input]");
  if (input && document.activeElement === input) return;
  event.preventDefault();
  query.value += event.key;
  input?.focus();
}

watch(
  () => palette.open,
  (open) => {
    if (open) {
      query.value = palette.initialQuery;
      window.addEventListener("keydown", catchEarlyKeys, true);
    } else {
      window.removeEventListener("keydown", catchEarlyKeys, true);
    }
  },
  { immediate: true },
);
onBeforeUnmount(() => window.removeEventListener("keydown", catchEarlyKeys, true));

const companyId = computed(() => company.currentId);
const base = computed(() => (companyId.value === null ? "" : `/c/${companyId.value}`));

function go(to: string): void {
  void router.push(to.startsWith("/") ? to : `${base.value}/${to.replace(/^\/+/, "")}`);
}

/** Pages the person can open, with their titles in all three languages for matching. */
const jumpItems = computed<Item[]>(() => {
  void locale.value;
  const items: Item[] = [];
  for (const group of props.groups) {
    const groupWords = Object.values(allLanguages(`shell.group.${group.id}`));
    for (const module of group.modules) {
      const moduleWords = Object.values(allLanguages(module.title));
      const entries = module.children.length ? module.children : [module];
      entries.forEach((entry, index) => {
        const isHead = module.children.length === 0 || index === 0;
        const title = isHead && module.children.length ? t(module.title) : t(entry.title);
        items.push({
          id: `jump:${entry.key}`,
          section: "jump",
          title,
          subtitle: isHead ? (group.id === "overview" ? undefined : t(`shell.group.${group.id}`)) : t(module.title),
          icon: module.icon,
          keywords: [...Object.values(allLanguages(entry.title)), ...moduleWords, ...groupWords],
          shortcut: isHead && module.hotkey ? `g ${module.hotkey}` : undefined,
          path: entry.path,
          head: isHead,
          run: () => {
            if (companyId.value !== null) palette.remember(companyId.value, { path: entry.path, title: isHead ? module.title : entry.title, moduleId: module.moduleId });
            go(entry.path);
          },
        });
      });
    }
  }
  return items;
});

const recentItems = computed<Item[]>(() => {
  if (companyId.value === null) return [];
  return palette
    .recent(companyId.value)
    .map((page) => jumpItems.value.find((item) => item.path === page.path))
    .filter((item): item is Item => item !== undefined)
    .map((item) => ({ ...item, id: `recent:${item.path}`, section: "recent" as const, icon: Clock3 }))
    .slice(0, 4);
});

const commandCtx = computed<CommandCtx | null>(() => {
  const current = company.current;
  if (!current) return null;
  return {
    companyId: current.id,
    company: current,
    router,
    t: (key, params) => (params ? t(key, params) : t(key)),
    can: (perm) => company.can(perm),
    go,
  };
});

const moduleCommands = computed<Item[]>(() => {
  const ctx = commandCtx.value;
  if (!ctx) return [];
  return modules
    .filter((m) => m.commands && isModuleVisible(m, ctx.company))
    .flatMap((m) => m.commands!(ctx).filter((c: Command) => allowed(ctx.company, { perm: c.perm })))
    .map((c) => ({
      id: `cmd:${c.id}`,
      section: "actions" as const,
      title: c.title,
      subtitle: c.subtitle,
      icon: c.icon ?? ArrowRight,
      keywords: c.keywords ?? [],
      shortcut: c.shortcut?.join("+"),
      run: c.run,
    }));
});

const shellCommands = computed<Item[]>(() => {
  void locale.value;
  const words = (key: string) => Object.values(allLanguages(key));
  const items: Item[] = [
    { id: "shell:inbox", section: "actions", title: t("shell.cmd.inbox"), icon: Inbox, keywords: words("shell.cmd.inbox"), shortcut: "g i", run: () => emit("openInbox") },
    { id: "shell:light", section: "actions", title: t("shell.cmd.themeLight"), icon: Sun, keywords: words("shell.cmd.themeLight"), run: () => switchTheme("light") },
    { id: "shell:dark", section: "actions", title: t("shell.cmd.themeDark"), icon: Moon, keywords: words("shell.cmd.themeDark"), run: () => switchTheme("dark") },
    { id: "shell:system", section: "actions", title: t("shell.cmd.themeSystem"), icon: Monitor, keywords: words("shell.cmd.themeSystem"), run: () => switchTheme("system") },
    ...LANGUAGES.filter((l) => l !== locale.value).map<Item>((l) => ({
      id: `shell:lang:${l}`,
      section: "actions",
      title: t("shell.cmd.language", { language: t(`shell.language.${l}`) }),
      icon: FileText,
      keywords: [...words("shell.topbar.language"), t(`shell.language.${l}`), l],
      run: () => changeLanguage(l),
    })),
    ...(isPhone.value
      ? []
      : [{ id: "shell:sidebar", section: "actions" as const, title: t("shell.cmd.toggleSidebar"), icon: PanelLeft, keywords: words("shell.cmd.toggleSidebar"), shortcut: "[", run: () => ui.toggleSidebar() }]),
    { id: "shell:density", section: "actions", title: t("shell.cmd.density"), icon: Rows3, keywords: words("shell.cmd.density"), run: () => ui.toggleDensity() },
    ...(isPhone.value
      ? []
      : [{ id: "shell:shortcuts", section: "actions" as const, title: t("shell.cmd.shortcuts"), icon: Keyboard, keywords: words("shell.cmd.shortcuts"), shortcut: "?", run: () => (ui.shortcutsOpen = true) }]),
    {
      id: "shell:copy",
      section: "actions",
      title: t("shell.cmd.copyLink"),
      icon: Link2,
      keywords: words("shell.cmd.copyLink"),
      run: async () => {
        try {
          await navigator.clipboard.writeText(window.location.href);
          toast.success(t("common.copied"));
        } catch {
          toast.error(t("common.error.generic"));
        }
      },
    },
  ];
  if (router.hasRoute("portfolio")) {
    items.push({ id: "shell:portfolio", section: "actions", title: t("shell.cmd.portfolio"), icon: LayoutGrid, keywords: words("shell.company.portfolio"), run: () => void router.push({ name: "portfolio" }) });
  }
  if (hasExtension("shell.company.create", company.current)) {
    items.push({ id: "shell:new-company", section: "actions", title: t("shell.cmd.newCompany"), icon: Plus, keywords: words("shell.company.new"), run: () => (ui.newCompanyOpen = true) });
  }
  items.push({ id: "shell:signout", section: "actions", title: t("shell.cmd.signOut"), icon: LogOut, keywords: words("shell.cmd.signOut"), run: () => emit("signOut") });
  return items;
});

const companyItems = computed<Item[]>(() =>
  company.companies
    .filter((c) => c.id !== company.currentId)
    .map((c) => ({
      id: `company:${c.id}`,
      section: "companies" as const,
      title: t("shell.palette.switchTo", { name: c.name }),
      subtitle: c.role?.name,
      logo: { name: c.name, src: c.logo },
      icon: Building2,
      keywords: [c.name],
      run: () => void router.push(pathInCompany(router, route, c.id)),
    })),
);

const localItems = computed(() => [...jumpItems.value, ...moduleCommands.value, ...shellCommands.value, ...companyItems.value]);
const fuse = computed(
  () =>
    new Fuse(localItems.value, {
      keys: [
        { name: "title", weight: 2 },
        { name: "keywords", weight: 1 },
      ],
      threshold: 0.3,
      ignoreLocation: true,
      minMatchCharLength: 1,
    }),
);

const search = useQuery({
  queryKey: computed(() => keys.search(companyId.value ?? 0, debounced.value.trim())),
  queryFn: ({ signal }) => shellApi.search(companyId.value!, debounced.value.trim(), signal),
  enabled: computed(() => palette.open && companyId.value !== null && debounced.value.trim().length >= 2),
  staleTime: 30_000,
  placeholderData: keepPreviousData,
});
const searching = computed(() => trimmed.value.length >= 2 && (search.isFetching.value || debounced.value !== query.value));

const rendererFor = (type: string): Component | undefined => {
  for (const m of modules) {
    const renderer = m.searchResults?.[type];
    if (renderer && isModuleVisible(m, company.current)) return renderer;
  }
  return undefined;
};

const resultItems = computed<Item[]>(() => {
  if (trimmed.value.length < 2) return [];
  const hits = search.data.value?.results ?? [];
  return hits.map((hit) => ({
    id: `hit:${hit.type}:${hit.id}`,
    section: "results" as const,
    title: hit.title,
    subtitle: hit.subtitle,
    icon: iconForKind(hit.type, FileText),
    // People hits ("members.people", "people") show the person's initials.
    person: isPersonHit(hit.type) ? hit.title : undefined,
    keywords: [],
    hit,
    renderer: rendererFor(hit.type),
    run: () => go(hit.url),
  }));
});

const isPersonHit = (type: string) => type === "people" || type.endsWith(".people") || type === "members";

const typeLabel = (type: string) => {
  const key = searchTypeKey(type, (candidate) => te(candidate));
  if (key) return t(key);
  const module = modules.find((m) => m.id === type.split(".")[0]);
  return module ? t(module.title) : t("shell.searchType.other");
};

/**
 * Fuse scores "fin" in "Briefings" like "fin" in "Finance"; people expect the word that starts with
 * what they typed first. Stable: Fuse's order is kept inside each bucket.
 */
function rankByPrefix(items: Item[], q: string): Item[] {
  const needle = q.toLocaleLowerCase();
  const bucket = (item: Item) => {
    const words = [item.title, ...item.keywords].map((w) => w.toLocaleLowerCase());
    if (words.some((w) => w.startsWith(needle))) return 0;
    if (words.some((w) => w.split(/[\s·:,()/-]+/).some((part) => part.startsWith(needle)))) return 1;
    return 2;
  };
  return items.map((item, index) => ({ item, index, rank: bucket(item) })).sort((a, b) => a.rank - b.rank || a.index - b.index).map((x) => x.item);
}


interface SectionView {
  id: string;
  label: string;
  items: Item[];
}

const sections = computed<SectionView[]>(() => {
  const q = trimmed.value;
  const out: SectionView[] = [];
  if (!q) {
    if (recentItems.value.length) out.push({ id: "recent", label: t("shell.palette.recent"), items: recentItems.value });
    out.push({ id: "jump", label: t("shell.palette.jump"), items: jumpItems.value.filter((i) => i.head && !recentItems.value.some((r) => r.path === i.path)).slice(0, 7) });
    out.push({ id: "actions", label: t("shell.palette.actions"), items: [...moduleCommands.value.slice(0, 4), ...shellCommands.value.slice(0, 3)] });
    if (companyItems.value.length) out.push({ id: "companies", label: t("shell.palette.companies"), items: companyItems.value.slice(0, 4) });
    return out.filter((s) => s.items.length);
  }
  const matched = rankByPrefix(fuse.value.search(q).map((r) => r.item), q);
  const jump = matched.filter((i) => i.section === "jump").slice(0, 6);
  const actions = matched.filter((i) => i.section === "actions").slice(0, 5);
  const companies = matched.filter((i) => i.section === "companies").slice(0, 4);
  if (jump.length) out.push({ id: "jump", label: t("shell.palette.jump"), items: jump });
  const byType = new Map<string, Item[]>();
  for (const item of resultItems.value) {
    const list = byType.get(item.hit!.type) ?? [];
    list.push(item);
    byType.set(item.hit!.type, list);
  }
  for (const [type, items] of byType) out.push({ id: `results:${type}`, label: typeLabel(type), items });
  if (actions.length) out.push({ id: "actions", label: t("shell.palette.actions"), items: actions });
  if (companies.length) out.push({ id: "companies", label: t("shell.palette.companies"), items: companies });
  if (props.aiAvailable) {
    out.push({
      id: "ai",
      label: "",
      items: [{ id: "ai:ask", section: "ai", title: t("shell.palette.askAi", { q }), subtitle: t("shell.palette.askAiHint"), icon: Sparkles, keywords: [], run: () => ui.askAi(q) }],
    });
  }
  return out;
});

const byId = computed(() => new Map(sections.value.flatMap((s) => s.items).map((item) => [item.id, item])));

async function select(value: unknown): Promise<void> {
  if (typeof value !== "string") return;
  const item = byId.value.get(value);
  if (!item) return;
  palette.hide();
  await item.run();
}

function onOpenChange(open: boolean): void {
  if (!open) palette.hide();
}
</script>

<template>
  <DialogRoot :open="palette.open" @update:open="onOpenChange">
    <DialogPortal>
      <DialogOverlay class="anim-overlay fixed inset-0 z-[70] bg-overlay/60 backdrop-blur-[2px]" />
      <div class="pointer-events-none fixed inset-0 z-[71] flex items-start justify-center px-2 pt-2 md:px-4 md:pt-[12vh]">
        <DialogContent
          class="anim-dialog pointer-events-auto flex max-h-[min(640px,calc(100dvh-16px))] w-full max-w-[660px] flex-col overflow-hidden rounded-[18px] border border-line bg-surface shadow-palette outline-none"
          @open-auto-focus.prevent
        >
          <VisuallyHidden>
            <DialogTitle>{{ t("shell.palette.title") }}</DialogTitle>
            <DialogDescription>{{ t("shell.palette.description") }}</DialogDescription>
          </VisuallyHidden>
          <ComboboxRoot
            :open="true"
            :ignore-filter="true"
            :reset-search-term-on-blur="false"
            :reset-search-term-on-select="false"
            highlight-on-hover
            class="flex min-h-0 flex-col"
            @update:model-value="select"
            @update:open="(value: boolean) => !value && palette.hide()"
          >
            <ComboboxAnchor class="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4">
              <Search :size="18" class="shrink-0 text-muted" aria-hidden="true" />
              <ComboboxInput
                v-model="query"
                auto-focus
                data-palette-input
                class="h-full min-w-0 flex-1 bg-transparent text-md text-fg outline-none placeholder:text-subtle focus-visible:outline-none"
                :placeholder="t('shell.palette.placeholder')"
              />
              <UiSpinner v-if="searching" :size="16" class="text-muted" :label="t('shell.palette.searching')" />
              <KbdKey v-if="!isPhone" keys="esc" />
            </ComboboxAnchor>
            <ComboboxContent position="inline" class="min-h-0 flex-1 overflow-y-auto overscroll-contain">
              <ComboboxViewport class="p-2">
                <ComboboxEmpty v-if="trimmed && !searching" class="flex flex-col items-center gap-1 px-6 py-10 text-center">
                  <p class="text-base font-semibold text-fg">{{ t("shell.palette.empty", { q: trimmed }) }}</p>
                  <p class="text-sm text-muted">{{ t("shell.palette.emptyHint") }}</p>
                </ComboboxEmpty>
                <ComboboxGroup v-for="section in sections" :key="section.id" class="mb-1 last:mb-0">
                  <ComboboxLabel v-if="section.label" class="px-2.5 pb-1 pt-2 text-xs font-medium text-subtle">{{ section.label }}</ComboboxLabel>
                  <ComboboxItem
                    v-for="item in section.items"
                    :key="item.id"
                    :value="item.id"
                    :text-value="item.title"
                    class="group flex h-11 cursor-default select-none items-center gap-3 rounded-[10px] px-2.5 outline-none data-[highlighted]:bg-highlight"
                  >
                    <component :is="item.renderer" v-if="item.renderer && item.hit" :hit="item.hit" />
                    <template v-else>
                      <CompanyLogo v-if="item.logo" :name="item.logo.name" :src="item.logo.src" :size="26" />
                      <UserAvatar v-else-if="item.person" :name="item.person" :size="26" />
                      <span
                        v-else
                        :class="[
                          'grid size-[26px] shrink-0 place-items-center rounded-[7px] border border-line bg-surface text-muted shadow-xs transition-colors',
                          'group-data-[highlighted]:border-transparent group-data-[highlighted]:bg-primary group-data-[highlighted]:text-on-primary',
                          item.section === 'ai' && 'border-transparent bg-accent-soft text-accent-fg',
                        ]"
                      >
                        <component :is="item.icon" :size="15" aria-hidden="true" />
                      </span>
                      <span class="min-w-0 flex-1 truncate">
                        <span class="text-base font-medium text-fg">{{ item.title }}</span>
                        <span v-if="item.subtitle" class="ml-2 text-sm text-muted">{{ item.subtitle }}</span>
                      </span>
                      <KbdKey v-if="item.shortcut && !isPhone" :keys="item.shortcut.includes(' ') ? item.shortcut.split(' ') : item.shortcut" class="opacity-80" />
                      <CornerDownLeft :size="15" class="hidden shrink-0 text-subtle group-data-[highlighted]:block" aria-hidden="true" />
                    </template>
                  </ComboboxItem>
                </ComboboxGroup>
              </ComboboxViewport>
            </ComboboxContent>
            <footer class="hidden h-10 shrink-0 items-center gap-4 border-t border-line bg-canvas/50 px-4 text-xs text-muted md:flex">
              <span class="flex items-center gap-1.5"><KbdKey :keys="['arrowup', 'arrowdown']" />{{ t("shell.palette.navigate") }}</span>
              <span class="flex items-center gap-1.5"><KbdKey keys="enter" />{{ t("shell.palette.select") }}</span>
              <span class="flex items-center gap-1.5"><KbdKey keys="esc" />{{ t("shell.palette.close") }}</span>
              <span class="flex-1" />
              <span class="flex items-center gap-1.5"><KbdKey keys="?" />{{ t("shell.shortcuts.title") }}</span>
            </footer>
          </ComboboxRoot>
        </DialogContent>
      </div>
    </DialogPortal>
  </DialogRoot>
</template>
