<script setup lang="ts">
/**
 * Add students to an unchangeable list: Daybook staff picked from a search (approved, in the
 * manager's branches, not on the list yet), or names typed in with a note ("intern, pharmacy
 * college") for people outside Daybook. Several of each at once.
 */
import { Plus, UserRound, UsersRound, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import type { OptionSource } from "@/components/options";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { learningApi, useApplyList } from "../api";
import type { StudyListDetail, StudyStudentsInput } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ list: StudyListDetail }>();

const { t } = useI18n();
const cid = useCompanyId();
const apply = useApplyList();

const way = ref<"staff" | "names">("staff");
const memberIds = ref<number[]>([]);
const names = ref<{ key: number; name: string; note: string }[]>([]);
const formError = ref<string | null>(null);
const busy = ref(false);
let nextKey = 1;

const blank = () => ({ key: nextKey++, name: "", note: "" });
watch(open, (value) => {
  if (!value) return;
  way.value = "staff";
  memberIds.value = [];
  names.value = [blank()];
  formError.value = null;
});

const source: OptionSource<number> = async (query, signal) => {
  const found = await learningApi.listCandidates(cid.value, props.list.id, query, signal);
  return found.map((person) => ({
    value: person.id,
    label: person.name,
    description: [person.position, person.branch].filter(Boolean).join(" · ") || undefined,
    avatar: { name: person.name },
  }));
};

const typed = computed(() => names.value.map((row) => ({ name: row.name.trim(), note: row.note.trim() })).filter((row) => row.name));
const total = computed(() => memberIds.value.length + typed.value.length);
const ways = computed(() => [
  { value: "staff" as const, label: t("learning.lists.students.fromStaff"), icon: UsersRound, count: memberIds.value.length || undefined },
  { value: "names" as const, label: t("learning.lists.students.typed"), icon: UserRound, count: typed.value.length || undefined },
]);

function addRow(): void {
  names.value = [...names.value, blank()];
}
function removeRow(key: number): void {
  names.value = names.value.length > 1 ? names.value.filter((row) => row.key !== key) : [blank()];
}

async function save(): Promise<void> {
  if (busy.value || !total.value) return;
  busy.value = true;
  formError.value = null;
  const input: StudyStudentsInput = {};
  if (memberIds.value.length) input.member_ids = memberIds.value;
  if (typed.value.length) input.names = typed.value.map((row) => (row.note ? row : { name: row.name }));
  try {
    apply(await learningApi.addStudents(cid.value, props.list.id, input));
    toast.success(t("learning.lists.students.added", { n: total.value }, total.value));
    open.value = false;
  } catch (error) {
    formError.value = isApiError(error) ? unshownFieldError(error) : null;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('learning.lists.students.title')" :description="t('learning.lists.students.description')" size="md">
    <div class="flex flex-col gap-4">
      <SegmentedControl v-model="way" :options="ways" block :aria-label="t('learning.lists.students.title')" />
      <InlineAlert v-if="formError" tone="danger" :description="formError" />

      <FormField v-if="way === 'staff'" :label="t('learning.lists.students.staff')" :hint="t('learning.lists.students.staffHint')">
        <MultiSelect
          v-model="memberIds"
          :source="source"
          :placeholder="t('learning.lists.students.pick')"
          :search-placeholder="t('common.picker.searchPeople')"
          :empty-text="t('learning.lists.students.nobody')"
          display="chips"
          :max-chips="6"
        />
      </FormField>

      <div v-else class="flex flex-col gap-2.5" data-testid="students-names">
        <div v-for="(row, index) in names" :key="row.key" class="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <FormField :label="index === 0 ? t('learning.lists.students.name') : undefined" class="max-sm:col-span-1">
            <TextInput v-model="row.name" :maxlength="200" :autofocus="index === names.length - 1" :placeholder="t('learning.lists.students.namePlaceholder')" />
          </FormField>
          <FormField :label="index === 0 ? t('learning.lists.students.note') : undefined" class="max-sm:order-3 max-sm:col-span-2">
            <TextInput v-model="row.note" :maxlength="200" :placeholder="t('learning.lists.students.notePlaceholder')" />
          </FormField>
          <IconButton :icon="X" :label="t('learning.lists.students.removeRow')" class="mb-0.5" @click="removeRow(row.key)" />
        </div>
        <div>
          <UiButton size="sm" variant="ghost" :icon="Plus" @click="addRow">{{ t("learning.lists.students.addRow") }}</UiButton>
        </div>
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="busy" :disabled="!total" data-testid="students-save" @click="save">
        {{ total ? t("learning.lists.students.submit", { n: total }, total) : t("learning.lists.students.submitEmpty") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
