<script setup lang="ts">
/**
 * Team › Departments: the groups reports add up by (sales, warehouse, office…), with how many
 * people are in each. Add, rename and delete here; who is in which one is set on each employee.
 */
import { Network } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import PageHeader from "@/components/PageHeader.vue";
import { useFormat } from "@/lib/useFormat";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { createDepartment, deleteDepartment, renameDepartment, useDepartments, useRefresh } from "../api";
import NameList, { type NameItem } from "../components/team/NameList.vue";
import { useTeamTabs } from "../components/team/tabs";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const tabs = useTeamTabs();
const refresh = useRefresh();
const query = useDepartments();
const canManage = useCan("members.manage");

const cid = () => company.currentId ?? 0;
const canEdit = computed(() => canManage.value && (query.data.value ?? []).every((d) => d.can_edit));

const items = computed<NameItem[] | undefined>(() =>
  query.data.value?.map((d) => ({
    id: d.id,
    name: d.name,
    count: d.total_count ?? d.member_count,
    subtitle: d.path.length > 1 ? d.path.slice(0, -1).join(" › ") : d.head ? t("davomat.departments.head", { name: d.head.name }) : undefined,
    to: `/c/${company.currentId}/team?department=${d.id}`,
  })),
);

async function create(name: string): Promise<void> {
  await createDepartment(cid(), name);
  refresh();
}

async function rename(id: number, name: string): Promise<void> {
  await renameDepartment(cid(), id, name);
  refresh();
}

async function remove(id: number): Promise<void> {
  await deleteDepartment(cid(), id);
  refresh();
}
</script>

<template>
  <div>
    <PageHeader :title="t('davomat.nav.team')" :description="t('davomat.departments.description')" :tabs="tabs" />
    <div class="mx-auto max-w-[760px]">
      <NameList
        :items="items"
        :loading="query.isPending.value"
        :error="query.error.value"
        :retry="() => query.refetch()"
        :can-edit="canEdit"
        :icon="Network"
        :placeholder="t('davomat.departments.placeholder')"
        :empty-title="t('davomat.departments.empty.title')"
        :empty-body="t('davomat.departments.empty.body')"
        :count-label="(n) => t('davomat.team.list.people', { n: fmt.number(n) }, n)"
        :delete-title="(name) => t('davomat.departments.deleteTitle', { name })"
        :delete-body="t('davomat.departments.deleteBody')"
        :on-create="create"
        :on-rename="rename"
        :on-remove="remove"
      />
    </div>
  </div>
</template>
