<script setup lang="ts">
/**
 * One Telegram group: what the bot posts there (task events, then each module's), and whose news
 * it gets (positions, branches; empty means everyone). Every switch saves at once.
 */
import { EllipsisVertical, Link2Off, MessagesSquare, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import CompanyLogo from "@/components/CompanyLogo.vue";
import DropdownMenu from "@/components/DropdownMenu.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import StatusPill from "@/components/StatusPill.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";

import { useGroupMutations } from "../api";
import type { GroupEvent, GroupEventKey, GroupsList, TelegramGroup } from "../types";

const props = defineProps<{ group: TelegramGroup; options: GroupsList["options"]; personEvents: GroupEventKey[] }>();

const { t, te } = useI18n();
const fmt = useFormat();
const confirm = useConfirm();
const mutations = useGroupMutations();

const taskEvents = computed(() => props.group.events.filter((e) => !e.feature));
const moduleEvents = computed(() => props.group.events.filter((e) => e.feature));
const on = computed(() => props.group.events.filter((e) => e.on).map((e) => e.key));
const narrowsPeople = computed(() => props.group.events.some((e) => e.on && props.personEvents.includes(e.key)));

const eventTitle = (event: GroupEvent) => (te(`groups.event.${event.key}.title`) ? t(`groups.event.${event.key}.title`) : event.label);
const eventBody = (event: GroupEvent) => (te(`groups.event.${event.key}.body`) ? t(`groups.event.${event.key}.body`) : "");

const positionOptions = computed(() => props.options.positions.map((p) => ({ value: p.id, label: p.name })));
const branchOptions = computed(() => props.options.branches.map((b) => ({ value: b.id, label: b.name })));
const positions = computed({
  get: () => props.group.positions.map((p) => p.id),
  set: (ids: number[]) => save({ position_ids: ids }),
});
const branches = computed({
  get: () => props.group.branches.map((b) => b.id),
  set: (ids: number[]) => save({ branch_ids: ids }),
});

function save(patch: Parameters<typeof mutations.update.mutate>[0]["patch"]): void {
  mutations.update.mutate({ id: props.group.id, patch });
}

function flip(event: GroupEvent, value: boolean): void {
  const next = value ? [...on.value, event.key] : on.value.filter((key) => key !== event.key);
  save({ events: next });
}

async function disconnect(): Promise<void> {
  const answer = await confirm({
    title: t("groups.disconnectTitle", { title: props.group.title }),
    message: t("groups.disconnectBody"),
    confirmLabel: t("groups.disconnect"),
    tone: "danger",
  });
  if (!answer) return;
  await mutations.disconnect.mutateAsync(props.group.id);
  toast.success(t("groups.disconnected", { title: props.group.title }));
}

const menu = computed(() => [{ label: t("groups.disconnect"), icon: Link2Off, danger: true, onSelect: () => void disconnect() }]);
</script>

<template>
  <article class="ui-card overflow-hidden">
    <header class="flex items-center gap-3 border-b border-line px-4 py-3.5 md:px-5">
      <CompanyLogo :name="group.title || String(group.chat_id)" :size="40" />
      <div class="min-w-0 flex-1">
        <h3 class="flex items-center gap-2 truncate text-md font-semibold text-fg">
          {{ group.title || t("groups.untitled") }}
        </h3>
        <p class="truncate text-sm text-muted">
          <template v-if="group.linked_by">{{ t("groups.connectedBy", { name: group.linked_by.name, date: fmt.instant(group.connected_at, "date") }) }}</template>
          <template v-else>{{ t("groups.connectedOn", { date: fmt.instant(group.connected_at, "date") }) }}</template>
        </p>
      </div>
      <StatusPill tone="success" size="sm" :label="t('groups.connected')" class="max-sm:hidden" />
      <DropdownMenu :items="menu">
        <template #trigger><IconButton :icon="EllipsisVertical" :label="t('groups.actions')" size="sm" /></template>
      </DropdownMenu>
    </header>

    <div class="grid gap-6 p-4 md:p-5 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div class="flex flex-col gap-5">
        <section>
          <p class="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle"><MessagesSquare :size="13" />{{ t("groups.taskEvents") }}</p>
          <ul class="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <li v-for="event in taskEvents" :key="event.key">
              <ToggleSwitch :model-value="event.on" layout="row" size="sm" :label="eventTitle(event)" :description="eventBody(event)" @update:model-value="(v: boolean) => flip(event, v)" />
            </li>
          </ul>
        </section>
        <section v-if="moduleEvents.length">
          <p class="mb-2 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("groups.moduleEvents") }}</p>
          <ul class="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <li v-for="event in moduleEvents" :key="event.key">
              <ToggleSwitch
                :model-value="event.on"
                layout="row"
                size="sm"
                :disabled="!event.available && !event.on"
                :label="eventTitle(event)"
                :description="event.available ? eventBody(event) : t('groups.moduleOff')"
                @update:model-value="(v: boolean) => flip(event, v)"
              />
            </li>
          </ul>
        </section>
      </div>

      <aside class="flex flex-col gap-4 rounded-[12px] bg-surface-2 p-4">
        <p class="flex items-center gap-1.5 text-sm font-semibold text-fg"><Users :size="15" />{{ t("groups.whose") }}</p>
        <FormField :label="t('groups.positions')" :hint="narrowsPeople ? t('groups.positionsHint') : t('groups.positionsIdle')">
          <MultiSelect v-model="positions" :options="positionOptions" :placeholder="t('groups.everyone')" :empty-text="t('groups.noPositions')" :max-chips="3" />
        </FormField>
        <FormField :label="t('groups.branches')" :hint="t('groups.branchesHint')">
          <MultiSelect v-model="branches" :options="branchOptions" :placeholder="t('groups.everyBranch')" :max-chips="3" />
        </FormField>
      </aside>
    </div>
  </article>
</template>
