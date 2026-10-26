<script setup lang="ts">
/**
 * Approve several join requests at once (People › Join requests): who (compact), one role for all
 * or "as their link says" (the start when every selected person came through a team link with a
 * role), the branches and home branch (their shared link branch to start with; required when some
 * came without one and there are branches to choose from), and the position: theirs, or one for
 * all. The page sends it and handles the answer.
 */
import { Check } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import AvatarStack from "@/components/AvatarStack.vue";
import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import { useScopedBranches } from "@/components/pickers";
import SelectBox from "@/components/SelectBox.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";

import { usePositions, useRoles } from "../api";
import { AS_LINK, bulkApproveBody, bulkStart, namesLine } from "../bulk";
import type { BulkDecisionInput, JoinRequest } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ requests: JoinRequest[]; busy?: boolean }>();
const emit = defineEmits<{ approve: [body: BulkDecisionInput] }>();

const { t } = useI18n();
const roles = useRoles();
const positions = usePositions();
const branches = useScopedBranches();

const severalBranches = computed(() => branches.value.length > 1);
const start = computed(() => bulkStart(props.requests, roles.data.value ?? [], branches.value));
const defaultRole = computed(() => roles.data.value?.find((role) => role.is_default) ?? null);

const roleId = ref<number | null>(null);
const positionId = ref<number | null>(null);
const branchIds = ref<number[]>([...start.value.branchIds]);
const homeId = ref<number | null>(start.value.homeId);

// The role starts once the roles are here (the default role's id comes with them).
watch(
  () => roles.data.value,
  (list) => {
    if (list && roleId.value === null) roleId.value = start.value.role;
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

const roleOptions = computed(() => {
  const options: Array<{ value: number; label: string; description?: string }> = [];
  if (start.value.linkRoles !== "none") {
    options.push({
      value: AS_LINK,
      label: t("people.bulk.asLink"),
      description: start.value.linkRoles === "some" && defaultRole.value ? t("people.bulk.asLinkOthers", { role: defaultRole.value.name }) : undefined,
    });
  }
  const list = (roles.data.value ?? []).filter((role) => (role.is_default || role.can_assign) && !role.is_owner).sort((a, b) => Number(b.is_default) - Number(a.is_default));
  for (const role of list) options.push({ value: role.id, label: role.is_default ? t("people.approve.defaultRole", { name: role.name }) : role.name });
  return options;
});
const positionOptions = computed(() => (positions.data.value ?? []).filter((p) => p.is_active).map((p) => ({ value: p.id, label: p.name })));
const homeOptions = computed(() => branches.value.filter((b) => branchIds.value.includes(b.id)).map((b) => ({ value: b.id, label: b.name })));

const names = computed(() => namesLine(props.requests.map((row) => row.name), t));
const people = computed(() => props.requests.map((row) => ({ id: row.id, name: row.name, photo_url: row.photo_url })));
const branchMissing = computed(() => severalBranches.value && start.value.branchRequired && !branchIds.value.length);

function submit(): void {
  if (branchMissing.value) return;
  emit(
    "approve",
    bulkApproveBody(
      props.requests.map((row) => row.id),
      { role: roleId.value, positionId: positionId.value, branchIds: branchIds.value, homeId: homeId.value },
      severalBranches.value,
    ),
  );
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('people.bulk.title', { n: requests.length }, requests.length)" size="md">
    <div class="flex flex-col gap-4">
      <div class="flex items-center gap-3 rounded-[12px] bg-surface-2/70 p-3 dark:bg-surface-2" data-bulk-who>
        <AvatarStack :people="people" :max="5" :size="30" />
        <p class="min-w-0 flex-1 text-sm text-fg">{{ names }}</p>
      </div>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('people.col.role')" :hint="t('people.approve.roleHint')">
          <SelectBox v-model="roleId" :options="roleOptions" />
        </FormField>
        <FormField :label="t('people.col.position')">
          <SelectBox v-model="positionId" :options="positionOptions" :placeholder="t('people.bulk.positionKeep')" clearable />
        </FormField>
      </div>
      <div v-if="severalBranches" class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('people.field.branches')" :error="branchMissing ? t('people.bulk.branchRequired') : undefined" :required="start.branchRequired">
          <BranchPicker v-model="branchIds" multiple :placeholder="start.everyoneHasBranch ? t('people.bulk.asLink') : undefined" />
        </FormField>
        <FormField :label="t('people.field.homeBranch')" :hint="t('people.edit.homeHint')">
          <SelectBox v-model="homeId" :options="homeOptions" :disabled="!homeOptions.length" :placeholder="start.everyoneHasBranch && !homeOptions.length ? t('people.bulk.asLink') : undefined" />
        </FormField>
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Check" :loading="busy" :disabled="branchMissing" data-bulk-confirm @click="submit">{{ t("people.bulk.confirm", { n: requests.length }) }}</UiButton>
    </template>
  </UiDialog>
</template>
