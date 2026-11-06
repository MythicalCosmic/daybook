<script setup lang="ts">
/**
 * One step on an asset, each with only the fields it needs: put into service, in use / in
 * storage / under repair, move, give to someone, take back, service, instrument check, repair
 * (an ordinary one or one that improves it), add to its cost, write down, change of estimate,
 * mothball, back in use, units of output, dispose of it. The answer is the asset's page, so the
 * page refreshes from it at once.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { http, isApiError, ownerPath, unshownFieldError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { assetsApi, useRefresh } from "../api";
import type { ActionKind, AssetCondition, AssetDetail, Disposal, Method } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ asset: AssetDetail; kind: ActionKind | null }>();
const emit = defineEmits<{ done: [page: AssetDetail] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const companyToday = useCompanyToday();
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});

const form = reactive({
  on: companyToday.value,
  note: "",
  status: "in_use" as "in_use" | "in_storage" | "repair",
  branch: null as number | null,
  person: null as number | null,
  condition: "good" as AssetCondition,
  amount: null as string | null,
  improves: false,
  valid_until: null as string | null,
  life_months: null as number | null,
  salvage_value: null as string | null,
  method: null as Method | null,
  units: null as number | null,
  disposal: "written_off" as Disposal,
  account: null as number | null,
});

watch(
  () => [open.value, props.kind] as const,
  ([isOpen]) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, {
      on: companyToday.value,
      note: "",
      status: props.asset.asset.status === "repair" ? "in_use" : "repair",
      branch: props.asset.asset.branch?.id ?? null,
      person: null,
      condition: props.asset.asset.condition,
      amount: null,
      improves: false,
      valid_until: null,
      life_months: props.asset.life_months,
      salvage_value: props.asset.values.salvage_value,
      method: props.asset.method,
      units: null,
      disposal: "written_off",
      account: null,
    });
  },
  { immediate: true },
);

const accounts = useQuery({
  queryKey: computed(() => [company.currentId, "assets", "finance-accounts"]),
  queryFn: () => http.get<{ accounts: { id: number; name: string; currency: string; is_active: boolean }[] }>(ownerPath(company.currentId ?? 0, "finance/accounts/")),
  enabled: computed(() => open.value && props.kind === "dispose" && company.enabled("finance") && company.can("finance.record")),
  staleTime: 60_000,
});
const accountOptions = computed(() => (accounts.data.value?.accounts ?? []).filter((row) => row.is_active).map((row) => ({ value: row.id, label: row.name, description: row.currency })));

const conditionOptions = computed(() => (["new", "good", "worn", "damaged"] as const).map((value) => ({ value, label: t(`assets.condition.${value}`) })));
const methodOptions = computed(() => (["straight_line", "declining", "sum_of_years"] as const).map((value) => ({ value, label: t(`assets.method.${value}`) })));
const disposalOptions = computed(() => (["sold", "written_off", "lost", "donated"] as const).map((value) => ({ value, label: t(`assets.disposal.${value}`) })));

const title = computed(() => (props.kind ? t(`assets.action.${props.kind}.title`) : ""));
const description = computed(() => (props.kind ? t(`assets.action.${props.kind}.body`) : ""));
const has = (...kinds: ActionKind[]) => !!props.kind && kinds.includes(props.kind);

function body(): Record<string, unknown> {
  const base: Record<string, unknown> = { on: form.on };
  if (form.note.trim() && props.kind !== "usage" && props.kind !== "dispose") base.note = form.note.trim();
  switch (props.kind) {
    case "status":
      return { ...base, status: form.status };
    case "move":
      return { ...base, branch: form.branch };
    case "issue":
      return { ...base, person: form.person, condition: form.condition };
    case "return":
      return { ...base, condition: form.condition };
    case "service":
      return { ...base, amount: form.amount || null };
    case "verification":
      return { ...base, valid_until: form.valid_until };
    case "repair":
      return { ...base, amount: form.amount || null, improves: form.improves };
    case "addition":
    case "write-down":
      return { ...base, amount: form.amount };
    case "estimate":
      return {
        ...base,
        life_months: form.life_months !== props.asset.life_months ? form.life_months : null,
        salvage_value: form.salvage_value !== props.asset.values.salvage_value ? form.salvage_value : null,
        method: form.method !== props.asset.method ? form.method : null,
      };
    case "usage":
      return { on: form.on, units: form.units };
    case "dispose":
      return { on: form.on, kind: form.disposal, amount: form.disposal === "sold" ? form.amount : null, account: form.disposal === "sold" ? form.account : null, reason: form.note.trim() };
    default:
      return base;
  }
}

async function submit(): Promise<void> {
  if (!props.kind) return;
  for (const key of Object.keys(errors)) delete errors[key];
  if (has("issue") && !form.person) errors.person = t("assets.action.errPerson");
  if (has("addition", "write-down") && !form.amount) errors.amount = t("assets.action.errAmount");
  if (has("dispose") && form.disposal === "sold" && !form.amount) errors.amount = t("assets.action.errSold");
  if (has("dispose") && form.disposal !== "sold" && !form.note.trim()) errors.note = t("assets.action.errReason");
  if (has("usage") && !form.units) errors.units = t("assets.action.errUnits");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    const page = await assetsApi.act(company.currentId ?? 0, props.asset.asset.id, props.kind, body());
    toast.success(t(`assets.action.${props.kind}.done`));
    refresh();
    emit("done", page);
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field === "reason" ? "note" : field] = messages[0];
    const unshown = unshownFieldError(error, ["person", "amount", "units", "note", "reason", "on"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="title" :description="description" size="md">
    <div class="flex flex-col gap-4">
      <FormField v-if="has('status')" :label="t('assets.action.status.label')">
        <SegmentedControl
          v-model="form.status"
          block
          :options="(['in_use', 'in_storage', 'repair'] as const).map((value) => ({ value, label: t(`assets.status.${value}`) }))"
        />
      </FormField>
      <FormField v-if="has('move')" :label="t('assets.action.move.to')">
        <BranchPicker v-model="form.branch" clearable :placeholder="t('assets.form.companyLevel')" />
      </FormField>
      <FormField v-if="has('issue')" :label="t('assets.action.issue.to')" :error="errors.person" required>
        <PersonPicker v-model="form.person" />
      </FormField>
      <FormField v-if="has('issue', 'return')" :label="t('assets.action.condition')">
        <SegmentedControl v-model="form.condition" block :options="conditionOptions" />
      </FormField>
      <FormField v-if="has('dispose')" :label="t('assets.action.dispose.how')">
        <SelectBox v-model="form.disposal" :options="disposalOptions" />
      </FormField>

      <FormField :label="has('dispose') ? t('assets.action.dispose.day') : t('assets.action.day')" :error="errors.on">
        <DatePicker v-model="form.on" :max="has('in-service') ? undefined : companyToday" />
      </FormField>

      <template v-if="has('service', 'repair', 'addition', 'write-down') || (has('dispose') && form.disposal === 'sold')">
        <FormField :label="has('dispose') ? t('assets.action.dispose.amount') : t('assets.action.amount')" :error="errors.amount" :optional="has('service', 'repair')" :required="has('addition', 'write-down') || has('dispose')">
          <MoneyInput v-model="form.amount" />
        </FormField>
      </template>
      <FormField v-if="has('dispose') && form.disposal === 'sold' && company.enabled('finance')" :label="t('assets.action.dispose.account')" :hint="t('assets.action.dispose.accountHint')" optional>
        <SelectBox v-model="form.account" :options="accountOptions" clearable :placeholder="t('assets.action.dispose.noAccount')" />
      </FormField>
      <ToggleSwitch v-if="has('repair')" v-model="form.improves" :label="t('assets.action.repair.improves')" :description="t('assets.action.repair.improvesHint')" />
      <FormField v-if="has('verification')" :label="t('assets.action.verification.until')" :hint="asset.verify_months ? t('assets.action.verification.untilHint', { months: asset.verify_months }) : undefined" optional>
        <DatePicker v-model="form.valid_until" :min="form.on" clearable />
      </FormField>

      <template v-if="has('estimate')">
        <InlineAlert tone="info">{{ t("assets.action.estimate.prospective") }}</InlineAlert>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('assets.field.life')" :hint="form.life_months ? t('assets.form.lifeYears', { years: fmt.number(form.life_months / 12, 1) }) : undefined">
            <NumberInput v-model="form.life_months" :min="1" :max="1200" :suffix="t('assets.form.months')" />
          </FormField>
          <FormField :label="t('assets.field.salvage')">
            <MoneyInput v-model="form.salvage_value" />
          </FormField>
        </div>
        <FormField v-if="asset.method !== 'units'" :label="t('assets.field.method')">
          <SelectBox v-model="form.method" :options="methodOptions" />
        </FormField>
      </template>

      <FormField v-if="has('usage')" :label="t('assets.action.usage.units', { unit: asset.unit || t('assets.action.usage.unitsDefault') })" :error="errors.units" required>
        <NumberInput v-model="form.units" :min="0" :decimals="2" />
      </FormField>

      <InlineAlert v-if="has('dispose')" tone="warning">{{ t("assets.action.dispose.warning") }}</InlineAlert>
      <InlineAlert v-if="has('write-down')" tone="warning">{{ t("assets.action.write-down.warning", { value: fmt.money(asset.values.book, undefined, { decimals: "never" }) }) }}</InlineAlert>

      <FormField
        v-if="!has('usage')"
        :label="has('dispose') ? t('assets.action.dispose.reason') : t('assets.action.note')"
        :error="errors.note"
        :optional="!has('dispose') || form.disposal === 'sold'"
      >
        <TextArea v-model="form.note" :rows="2" autosize :max-rows="5" :maxlength="has('dispose') ? 300 : 500" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton :variant="has('dispose', 'write-down') ? 'danger' : 'primary'" :loading="saving" data-testid="asset-action-submit" @click="submit">{{ t(`assets.action.${kind}.submit`) }}</UiButton>
    </template>
  </UiDialog>
</template>
