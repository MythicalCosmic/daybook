<script setup lang="ts">
/**
 * Approve a join request with a role, a position, the branches they will work in and their home
 * branch (plan §4.6). The role list holds the default role and the roles the approver may give
 * (rule 3); with one branch there is nothing to choose.
 */
import { Check } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import { useScopedBranches } from "@/components/pickers";
import SelectBox from "@/components/SelectBox.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { formatPhone } from "@/lib/format";
import { useCompanyStore } from "@/stores/company";

import { usePositions, useRoles } from "../api";
import type { ApproveInput, JoinRequest } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ request: JoinRequest; busy?: boolean }>();
const emit = defineEmits<{ approve: [body: ApproveInput] }>();

const { t } = useI18n();
const company = useCompanyStore();
const roles = useRoles();
const positions = usePositions();
const branches = useScopedBranches();

const roleId = ref<number | null>(null);
const positionId = ref<number | null>(props.request.position?.id ?? null);
const branchIds = ref<number[]>([]);
const homeId = ref<number | null>(null);

const roleOptions = computed(() =>
  (roles.data.value ?? [])
    .filter((role) => role.is_default || role.can_assign)
    .sort((a, b) => Number(b.is_default) - Number(a.is_default))
    .map((role) => ({ value: role.id, label: role.is_default ? t("people.approve.defaultRole", { name: role.name }) : role.name })),
);
watch(
  () => roles.data.value,
  (list) => {
    if (roleId.value === null && list) roleId.value = list.find((role) => role.is_default)?.id ?? null;
  },
  { immediate: true },
);
const positionOptions = computed(() => (positions.data.value ?? []).filter((p) => p.is_active).map((p) => ({ value: p.id, label: p.name })));
const severalBranches = computed(() => branches.value.length > 1);
const homeOptions = computed(() => branches.value.filter((b) => branchIds.value.includes(b.id)).map((b) => ({ value: b.id, label: b.name })));

// Start from the approver's own branch (where most approvals go).
watch(
  branches,
  (list) => {
    if (branchIds.value.length || !list.length) return;
    const mine = company.current?.home_branch?.id;
    const first = list.find((b) => b.id === mine) ?? list[0]!;
    branchIds.value = [first.id];
  },
  { immediate: true },
);
watch(
  branchIds,
  (ids) => {
    if (!ids.length) homeId.value = null;
    else if (homeId.value === null || !ids.includes(homeId.value)) homeId.value = ids[0]!;
  },
  { immediate: true },
);

const valid = computed(() => !severalBranches.value || branchIds.value.length > 0);
const summary = computed(() => {
  const role = roles.data.value?.find((r) => r.id === roleId.value)?.name ?? "—";
  const home = branches.value.find((b) => b.id === homeId.value)?.name;
  return home ? t("people.approve.summary", { name: props.request.first_name || props.request.name, role, branch: home }) : t("people.approve.summaryNoBranch", { name: props.request.first_name || props.request.name, role });
});

function submit(): void {
  const body: ApproveInput = { role_id: roleId.value, position_id: positionId.value };
  if (severalBranches.value) {
    body.branch_ids = branchIds.value;
    body.home_branch_id = homeId.value;
  }
  emit("approve", body);
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('people.approve.title')" size="md">
    <div class="flex flex-col gap-4">
      <div class="flex items-center gap-3 rounded-[12px] bg-surface-2/70 p-3 dark:bg-surface-2">
        <UserAvatar :name="request.name" :src="request.photo_url" :size="40" />
        <div class="min-w-0">
          <p class="truncate text-base font-semibold text-fg">{{ request.name }}</p>
          <p class="truncate text-sm text-muted">{{ [request.position?.name, formatPhone(request.phone)].filter(Boolean).join(" · ") }}</p>
        </div>
      </div>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('people.col.role')" :hint="t('people.approve.roleHint')">
          <SelectBox v-model="roleId" :options="roleOptions" />
        </FormField>
        <FormField :label="t('people.col.position')">
          <SelectBox v-model="positionId" :options="positionOptions" :placeholder="t('people.noPosition')" clearable />
        </FormField>
      </div>
      <div v-if="severalBranches" class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('people.field.branches')" :error="!branchIds.length ? t('people.approve.branchRequired') : undefined" required>
          <BranchPicker v-model="branchIds" multiple />
        </FormField>
        <FormField :label="t('people.field.homeBranch')" :hint="t('people.edit.homeHint')">
          <SelectBox v-model="homeId" :options="homeOptions" :disabled="!homeOptions.length" />
        </FormField>
      </div>
      <p class="text-sm text-muted">{{ summary }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Check" :loading="busy" :disabled="!valid" @click="submit">{{ t("people.approve.confirm") }}</UiButton>
    </template>
  </UiDialog>
</template>
