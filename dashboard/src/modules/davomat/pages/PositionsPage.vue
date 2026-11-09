<script setup lang="ts">
/**
 * Team › Positions: the job titles employees hold (cashier, driver, manager…), with how many hold
 * each. Add, rename and delete here; a title someone still holds can't be deleted, only hidden
 * from new choices, and a hidden one can be shown again below.
 */
import { BriefcaseBusiness, Eye } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import PageHeader from "@/components/PageHeader.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { createPosition, deletePosition, renamePosition, usePositions, useRefresh } from "../api";
import NameList, { type NameItem } from "../components/team/NameList.vue";
import { useTeamTabs } from "../components/team/tabs";
import { setPositionActive } from "../components/team/teamApi";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const tabs = useTeamTabs();
const refresh = useRefresh();
const query = usePositions();
const canEdit = useCan("positions.manage");

const cid = () => company.currentId ?? 0;
const sorted = computed(() => [...(query.data.value ?? [])].sort((a, b) => a.order - b.order || a.name.localeCompare(b.name)));
const items = computed<NameItem[] | undefined>(() =>
  query.data.value
    ? sorted.value.filter((p) => p.is_active).map((p) => ({ id: p.id, name: p.name, count: p.members_count, to: `/c/${company.currentId}/team?position=${p.id}` }))
    : undefined,
);
const hidden = computed(() => sorted.value.filter((p) => !p.is_active));
const showing = ref<number | null>(null);

async function create(name: string): Promise<void> {
  await createPosition(cid(), name);
  refresh();
}

async function rename(id: number, name: string): Promise<void> {
  await renamePosition(cid(), id, name);
  refresh();
}

async function remove(id: number): Promise<void> {
  await deletePosition(cid(), id);
  refresh();
}

async function show(id: number, name: string): Promise<void> {
  showing.value = id;
  try {
    await setPositionActive(cid(), id, true);
    toast.success(t("davomat.positions.shown", { name }));
    refresh();
  } catch {
    toast.error(t("common.error.generic"));
  } finally {
    showing.value = null;
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('davomat.nav.team')" :description="t('davomat.positions.description')" :tabs="tabs" />
    <div class="mx-auto flex max-w-[760px] flex-col gap-5">
      <NameList
        :items="items"
        :loading="query.isPending.value"
        :error="query.error.value"
        :retry="() => query.refetch()"
        :can-edit="canEdit"
        :icon="BriefcaseBusiness"
        :placeholder="t('davomat.positions.placeholder')"
        :empty-title="t('davomat.positions.empty.title')"
        :empty-body="t('davomat.positions.empty.body')"
        :count-label="(n) => t('davomat.team.list.people', { n: fmt.number(n) }, n)"
        :delete-title="(name) => t('davomat.positions.deleteTitle', { name })"
        :delete-body="t('davomat.positions.deleteBody')"
        :on-create="create"
        :on-rename="rename"
        :on-remove="remove"
      />

      <section v-if="hidden.length" class="flex flex-col gap-2" data-hidden-positions>
        <h2 class="px-1 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("davomat.positions.hidden") }}</h2>
        <ul class="ui-card divide-y divide-line">
          <li v-for="position in hidden" :key="position.id" class="flex items-center gap-3 px-4 py-2.5">
            <span class="min-w-0 flex-1 truncate text-base text-muted">{{ position.name }}</span>
            <span class="shrink-0 text-xs tabular-nums text-subtle">{{ t("davomat.team.list.people", { n: fmt.number(position.members_count) }, position.members_count) }}</span>
            <UiButton v-if="canEdit" size="sm" variant="ghost" :icon="Eye" :loading="showing === position.id" @click="show(position.id, position.name)">{{ t("davomat.positions.show") }}</UiButton>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
