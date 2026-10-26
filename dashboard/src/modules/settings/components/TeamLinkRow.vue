<script setup lang="ts">
/**
 * One team link in Settings › Invite staff: its name and status, the rule in words, the places and
 * the end, and its actions: Show QR, copy, share in Telegram, and (in the menu) poster, edit, stop
 * or resume, delete. A read-only link (`can_edit: false`) keeps only what doesn't change it.
 */
import { Check, CirclePause, CirclePlay, Clock3, Copy, Ellipsis, Lock, Pencil, Printer, QrCode, Send, Trash2, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import IconButton from "@/components/IconButton.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { STATUS_TONE, endText, isEnded, placesText, ruleParts } from "../teamLinks";
import type { JoinLink } from "../types";

const props = defineProps<{ link: JoinLink; copied?: boolean; shareUrl: string }>();
const emit = defineEmits<{ show: []; copy: []; poster: []; edit: []; stop: []; resume: []; remove: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const ended = computed(() => isEnded(props.link));
const rule = computed(() => ruleParts(props.link, t).join(" · "));
const places = computed(() => placesText(props.link, t));
const end = computed(() => endText(props.link, t, company.timezone, fmt.lang.value));
/** Who made it, when that isn't the viewer (managers make links too). */
const maker = computed(() => (props.link.created_by && props.link.created_by.id !== company.current?.membership_id ? props.link.created_by.name : null));

const menu = computed<MenuEntry[]>(() => {
  const items: MenuEntry[] = [{ label: t("settings.invite.poster.open"), icon: Printer, onSelect: () => emit("poster") }];
  if (!props.link.can_edit) return items;
  items.push({ label: t("common.edit"), icon: Pencil, onSelect: () => emit("edit") });
  if (props.link.status === "stopped") items.push({ label: t("settings.teamLinks.resume"), icon: CirclePlay, onSelect: () => emit("resume") });
  else if (props.link.status !== "expired") items.push({ label: t("settings.teamLinks.stop"), icon: CirclePause, onSelect: () => emit("stop") });
  items.push({ type: "separator" }, { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => emit("remove") });
  return items;
});
</script>

<template>
  <article :class="['ui-card flex flex-col gap-3 p-4 md:flex-row md:items-center md:gap-6', ended && 'bg-surface/70']" :data-link="link.id" :data-status="link.status">
    <div class="min-w-0 flex-1">
      <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <h4 :class="['min-w-0 truncate text-md font-semibold', ended ? 'text-muted' : 'text-fg']" :title="link.name">{{ link.name }}</h4>
        <StatusPill size="sm" :tone="STATUS_TONE[link.status]" :label="t(`settings.teamLinks.status.${link.status}`)" :live="link.status === 'active'" />
        <UiTooltip v-if="!link.can_edit" :content="t('settings.teamLinks.viewOnlyHint')">
          <span class="inline-flex items-center gap-1 text-xs font-medium text-subtle" tabindex="0" data-view-only><Lock :size="12" aria-hidden="true" />{{ t("settings.teamLinks.viewOnly") }}</span>
        </UiTooltip>
      </div>
      <p class="mt-0.5 text-sm text-muted" data-rule>{{ rule }}</p>
      <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
        <span class="inline-flex min-w-0 items-center gap-2 text-fg" data-places>
          <Users :size="14" class="shrink-0 text-subtle" aria-hidden="true" />
          <span class="tabular-nums">{{ places }}</span>
          <ProgressBar v-if="link.max_uses !== null" class="w-20" size="xs" :value="link.uses" :max="link.max_uses" :tone="link.status === 'full' ? 'warning' : ended ? 'neutral' : 'success'" />
        </span>
        <span class="inline-flex items-center gap-1.5 text-muted" data-end><Clock3 :size="14" class="shrink-0 text-subtle" aria-hidden="true" />{{ end }}</span>
        <span v-if="maker" class="text-subtle">{{ t("settings.teamLinks.madeBy", { name: maker }) }}</span>
      </div>
    </div>
    <div class="flex shrink-0 items-center gap-1.5">
      <UiButton size="sm" :variant="ended ? 'secondary' : 'primary'" :icon="QrCode" class="max-md:flex-1" data-show-qr @click="emit('show')">{{ t("settings.teamLinks.showQr") }}</UiButton>
      <IconButton :icon="copied ? Check : Copy" :label="copied ? t('common.copied') : t('settings.teamLinks.copy')" variant="secondary" size="sm" data-copy @click="emit('copy')" />
      <UiButton size="sm" :icon="Send" :href="shareUrl" target="_blank" :aria-label="t('settings.invite.share')" :title="t('settings.invite.share')" data-share />
      <DropdownMenu :items="menu" width="210px">
        <template #trigger><IconButton :icon="Ellipsis" :label="t('settings.teamLinks.more')" variant="ghost" size="sm" data-more /></template>
      </DropdownMenu>
    </div>
  </article>
</template>
