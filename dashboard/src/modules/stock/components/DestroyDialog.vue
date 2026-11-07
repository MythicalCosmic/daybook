<script setup lang="ts">
/**
 * Record the destruction of unfit goods (§14.4 row 30): how and where, the date and time, the
 * person named by the owner's order and the order's number, the commission (at least
 * `commission_min` people: the owner and the environmental, sanitary and pharmaceutical-safety
 * authorities), and who gets a copy. Photos of the destruction are added on the page first. The
 * act PDF is made when this is saved.
 */
import { Plus, Trash2 } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { zonedIso } from "@/lib/dates";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useRefresh } from "../api";
import { DESTRUCTION_METHODS, type DestructionMethod } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ writeoffId: number; commissionMin: number; photos: number }>();

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();
const refresh = useRefresh();
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
let keys = 0;

const form = reactive({
  method: null as DestructionMethod | null,
  place: "",
  day: null as string | null,
  time: "10:00" as string | null,
  responsible: "",
  order_number: "",
  sentTo: "",
});
const members = ref<Array<{ key: number; name: string; organisation: string; role: string }>>([]);

function member(name = "", organisation = "", role = "") {
  return { key: ++keys, name, organisation, role };
}

watch(open, (value) => {
  if (!value) return;
  for (const key of Object.keys(errors)) delete errors[key];
  Object.assign(form, { method: null, place: "", day: today.value, time: "10:00", responsible: "", order_number: "", sentTo: "" });
  // The form offers the bodies the law names (confirm the list with a local pharmacist).
  members.value = [
    member("", company.current?.name ?? "", t("stock.destroy.roleOwner")),
    member("", t("stock.destroy.orgEnvironment"), t("stock.destroy.roleMember")),
    member("", t("stock.destroy.orgSanitary"), t("stock.destroy.roleMember")),
    member("", t("stock.destroy.orgPharmacy"), t("stock.destroy.roleMember")),
    member("", "", t("stock.destroy.roleMember")),
  ];
  while (members.value.length < props.commissionMin) members.value.push(member());
});

const methodOptions = computed(() => DESTRUCTION_METHODS.map((value) => ({ value, label: t(`stock.method.${value}`) })));
const named = computed(() => members.value.filter((row) => row.name.trim()).length);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.method) errors.method = t("stock.destroy.errMethod");
  if (!form.place.trim()) errors.place = t("stock.destroy.errPlace");
  if (!form.day) errors.destroyed_at = t("stock.destroy.errDay");
  if (!form.responsible.trim()) errors.responsible = t("stock.destroy.errResponsible");
  if (!form.order_number.trim()) errors.order_number = t("stock.destroy.errOrder");
  if (named.value < props.commissionMin) errors.commission = t("stock.destroy.errCommission", { n: props.commissionMin });
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    await stockApi.destroyed(company.currentId ?? 0, props.writeoffId, {
      method: form.method!,
      place: form.place.trim(),
      destroyed_at: zonedIso(form.day!, form.time || "00:00", company.timezone),
      responsible: form.responsible.trim(),
      order_number: form.order_number.trim(),
      commission: members.value.filter((row) => row.name.trim()).map((row) => ({ name: row.name.trim(), organisation: row.organisation.trim(), role: row.role.trim() })),
      sent_to: form.sentTo
        .split(/[\n;,]/)
        .map((part) => part.trim())
        .filter(Boolean),
    });
    toast.success(t("stock.destroy.saved"));
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["method", "place", "destroyed_at", "responsible", "order_number", "commission"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.destroy.title')" :description="t('stock.destroy.description')" size="lg">
    <div class="flex flex-col gap-4">
      <InlineAlert v-if="photos === 0" tone="warning" size="sm">{{ t("stock.destroy.needPhoto") }}</InlineAlert>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('stock.destroy.method')" :error="errors.method" required>
          <SelectBox v-model="form.method" :options="methodOptions" clearable :placeholder="t('stock.destroy.pickMethod')" />
        </FormField>
        <FormField :label="t('stock.destroy.place')" :error="errors.place" required>
          <TextInput v-model="form.place" :maxlength="200" />
        </FormField>
        <div class="grid grid-cols-[1fr_120px] gap-2">
          <FormField :label="t('stock.destroy.day')" :error="errors.destroyed_at" required>
            <DatePicker v-model="form.day" :max="today" />
          </FormField>
          <FormField :label="t('stock.destroy.time')">
            <TimePicker v-model="form.time" />
          </FormField>
        </div>
        <FormField :label="t('stock.destroy.orderNumber')" :hint="t('stock.destroy.orderHint')" :error="errors.order_number" required>
          <TextInput v-model="form.order_number" :maxlength="40" />
        </FormField>
        <FormField class="sm:col-span-2" :label="t('stock.destroy.responsible')" :error="errors.responsible" required>
          <TextInput v-model="form.responsible" :maxlength="150" />
        </FormField>
      </div>
      <section class="flex flex-col gap-2">
        <div class="flex items-center justify-between gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("stock.destroy.commission", { n: named, min: commissionMin }) }}</h3>
          <UiButton size="sm" variant="secondary" :icon="Plus" @click="members.push(member())">{{ t("stock.destroy.addMember") }}</UiButton>
        </div>
        <InlineAlert v-if="errors.commission" tone="danger" size="sm">{{ errors.commission }}</InlineAlert>
        <ul class="flex flex-col gap-2" data-testid="commission">
          <li v-for="row in members" :key="row.key" class="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_140px_auto]">
            <TextInput v-model="row.name" size="sm" :maxlength="150" :placeholder="t('stock.destroy.memberName')" />
            <TextInput v-model="row.organisation" size="sm" :maxlength="150" :placeholder="t('stock.destroy.memberOrg')" />
            <TextInput v-model="row.role" size="sm" :maxlength="100" :placeholder="t('stock.destroy.memberRole')" />
            <IconButton :icon="Trash2" size="sm" :label="t('common.delete')" @click="members = members.filter((item) => item.key !== row.key)" />
          </li>
        </ul>
      </section>
      <FormField :label="t('stock.destroy.sentTo')" :hint="t('stock.destroy.sentToHint')" optional>
        <TextInput v-model="form.sentTo" :maxlength="600" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" :disabled="photos === 0" data-testid="destroy-save" @click="save">{{ t("stock.destroy.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
