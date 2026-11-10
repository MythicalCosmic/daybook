<script setup lang="ts">
/**
 * Set the partners and their shares from a day on: each a person of the company or just a name,
 * the shares adding up to exactly 100 % (the total shows as you type). The shares before that day
 * stay in the history, so earlier profit is still split the way it was owned then.
 */
import { Plus, Trash2, UserRound, UsersRound } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import NumberInput from "@/components/NumberInput.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";

import { ownerMoneyApi, sharesTotal, useOwnerMoneyWrite, type PartnerRowInput, type Partners } from "../../ownerMoney";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ partners: Partners; today: string; firstDay: string }>();

const { t } = useI18n();
interface Row {
  key: number;
  kind: "member" | "name";
  member: number | null;
  name: string;
  share: number | null;
}
let counter = 0;
const rows = ref<Row[]>([]);
const form = reactive({ effective_on: props.today as string | null });
const error = ref<string | null>(null);
const total = computed(() => sharesTotal(rows.value));
const people = computed(() => props.partners.people.map((person) => ({ value: person.id, label: person.name })));
const first = computed(() => !props.partners.current.length);
const minDay = computed(() => props.partners.since ?? null);

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    error.value = null;
    form.effective_on = first.value ? props.firstDay : props.today;
    rows.value = props.partners.current.length
      ? props.partners.current.map((row) => ({ key: ++counter, kind: row.member ? "member" : "name", member: row.member?.id ?? null, name: row.member ? "" : row.name, share: Number(row.share) }))
      : [{ key: ++counter, kind: "member", member: null, name: "", share: 100 }];
  },
  { immediate: true },
);

function addRow(kind: Row["kind"]): void {
  const left = Math.max(0, Math.round((100 - total.value.total) * 100) / 100);
  rows.value.push({ key: ++counter, kind, member: null, name: "", share: left || null });
}
function removeRow(key: number): void {
  rows.value = rows.value.filter((row) => row.key !== key);
}

const write = useOwnerMoneyWrite(ownerMoneyApi.setPartners);
const ready = computed(() => total.value.exact && rows.value.length > 0 && rows.value.every((row) => (row.kind === "member" ? row.member !== null : row.name.trim()) && (row.share ?? 0) > 0));

async function save(): Promise<void> {
  error.value = null;
  if (!ready.value) {
    error.value = total.value.exact ? t("finance.partners.fillEveryRow") : t("finance.partners.mustBe100");
    return;
  }
  const partners: PartnerRowInput[] = rows.value.map((row) => (row.kind === "member" ? { member: row.member, share: String(row.share) } : { name: row.name.trim(), share: String(row.share) }));
  try {
    await write.mutateAsync({ effective_on: form.effective_on ?? props.today, partners });
    toast.success(t("finance.partners.saved"));
    open.value = false;
  } catch (failure) {
    if (!isApiError(failure)) throw failure;
    error.value = failure.detail ?? Object.values(failure.fieldErrors)[0]?.[0] ?? t("finance.myMoney.failed");
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="first ? t('finance.partners.addTitle') : t('finance.partners.changeTitle')" :description="t('finance.partners.dialogDescription')" size="lg">
    <div class="flex flex-col gap-4">
      <ul class="flex flex-col gap-2" data-partner-rows>
        <li v-for="row in rows" :key="row.key" class="grid grid-cols-[minmax(0,1fr)_112px_auto] items-center gap-2" :data-row="row.key">
          <SelectBox v-if="row.kind === 'member'" v-model="row.member" :options="people" :placeholder="t('finance.partners.pickPerson')" />
          <TextInput v-else v-model="row.name" :maxlength="200" :placeholder="t('finance.partners.namePlaceholder')" :icon="UserRound" />
          <NumberInput v-model="row.share" :min="0" :max="100" :decimals="2" :steppers="false" suffix="%" :aria-label="t('finance.partners.share')" />
          <IconButton :icon="Trash2" :label="t('finance.partners.removeRow')" size="sm" :disabled="rows.length === 1" @click="removeRow(row.key)" />
        </li>
      </ul>
      <div class="flex flex-wrap items-center gap-2">
        <UiButton size="sm" variant="ghost" :icon="Plus" data-add-member @click="addRow('member')">{{ t("finance.partners.addMember") }}</UiButton>
        <UiButton size="sm" variant="ghost" :icon="UsersRound" data-add-name @click="addRow('name')">{{ t("finance.partners.addOutside") }}</UiButton>
        <span
          class="ms-auto rounded-full px-2.5 py-1 text-sm font-semibold tabular-nums"
          :class="total.exact ? 'bg-success-soft text-success' : 'bg-warning-soft text-warning'"
          data-total
        >
          {{ t("finance.partners.total", { n: total.total }) }}
        </span>
      </div>
      <FormField :label="t('finance.partners.effectiveOn')" :hint="first ? t('finance.partners.effectiveFirstHint') : t('finance.partners.effectiveHint')">
        <DatePicker v-model="form.effective_on" :min="minDay" />
      </FormField>
      <p v-if="error" class="rounded-[8px] bg-danger-soft px-3 py-2 text-sm text-danger" role="alert" data-error>{{ error }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="write.isPending.value" :disabled="!total.exact" data-save @click="save">{{ t("common.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
