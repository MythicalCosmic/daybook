<script setup lang="ts">
/**
 * Something comes back, or doesn't: handed back in a condition (with a photo and a note; damaged,
 * it can be written off at once), or lost (written off as lost). Either way a deduction from their
 * pay can go to payroll with it, which payroll's managers approve as usual. What was written down
 * when it was given is shown first, so the two can be compared.
 */
import { HandCoins, PackageCheck, PackageX, Undo2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import ImageLightbox, { type LightboxImage } from "@/components/ImageLightbox.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { equipmentApi, useEquipmentMutation } from "./api";
import { categoryIcon, confirmation, returnErrors, returnOptions, returnPayload, type ReturnErrors, type ReturnForm } from "./lib";
import PhotoField from "./PhotoField.vue";
import type { Condition, EquipmentCan, HeldItem, Holder, ReturnInput } from "./types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ holder: Pick<Holder, "person">; item: HeldItem; can: EquipmentCan; start?: "returned" | "lost" | "deduct" }>(), { start: "returned" });
const emit = defineEmits<{ saved: [holder: Holder] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const options = computed(() => returnOptions(props.holder, props.item, props.can));
const blank = (): ReturnForm => ({
  outcome: props.start === "lost" ? "lost" : "returned",
  on: today.value,
  condition: props.item.condition_out === "new" ? "good" : props.item.condition_out,
  note: "",
  photo: null,
  writeOff: false,
  deduct: props.start === "deduct" && options.value.deduct,
  amount: props.item.value,
  reason: "",
});
const form = ref<ReturnForm>(blank());
const errors = ref<ReturnErrors>({});
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    form.value = blank();
    errors.value = {};
  },
  { immediate: true },
);

const outcomes = computed(() => [
  { value: "returned" as const, label: t("lifecycle.equipment.return.returned"), description: t("lifecycle.equipment.return.returnedHint"), icon: PackageCheck },
  { value: "lost" as const, label: t("lifecycle.equipment.return.lost"), description: t("lifecycle.equipment.return.lostHint"), icon: PackageX, disabled: !options.value.writeOff },
]);
const conditions = computed(() => (["new", "good", "worn", "damaged"] as Condition[]).map((value) => ({ value, label: t(`lifecycle.equipment.condition.${value}`) })));
const damaged = computed(() => form.value.outcome === "returned" && form.value.condition === "damaged");
const lossOrDamage = computed(() => form.value.outcome === "lost" || damaged.value);
const confirmed = computed(() => confirmation(props.item, today.value));

const photos = computed<LightboxImage[]>(() => (props.item.photo_url ? [{ src: props.item.photo_url, alt: props.item.name }] : []));
const lightbox = ref(false);

const message = (key: string | undefined) => (key ? t(`lifecycle.equipment.error.${key}`) : null);
const save = useEquipmentMutation((cid, input: ReturnInput) => equipmentApi.giveBack(cid, props.item.assignment_id, input));

async function submit(): Promise<void> {
  errors.value = returnErrors(form.value, today.value);
  if (Object.keys(errors.value).length) return;
  try {
    const holder = await save.mutateAsync(returnPayload(form.value));
    const key = form.value.outcome === "lost" ? "lostDone" : form.value.writeOff && damaged.value ? "writtenOffDone" : "returnedDone";
    toast.success(t(`lifecycle.equipment.return.${key}`, { item: props.item.name, name: props.holder.person.name }));
    if (form.value.deduct) toast.info(t("lifecycle.equipment.deduction.sent"));
    emit("saved", holder);
    open.value = false;
  } catch {
    // The HTTP layer showed why.
  }
}
</script>

<template>
  <UiDialog v-model:open="open" size="md" :title="t('lifecycle.equipment.return.title', { item: item.name })" :description="t('lifecycle.equipment.return.description', { name: holder.person.name })">
    <div class="flex flex-col gap-4">
      <!-- What was written down when it was given. -->
      <div class="flex items-start gap-3 rounded-[12px] border border-line p-3" data-return-item>
        <button v-if="item.photo_url" type="button" class="shrink-0 overflow-hidden rounded-[9px] ring-1 ring-line" :aria-label="t('lifecycle.equipment.photo.open')" @click="lightbox = true">
          <img :src="item.photo_url" :alt="item.name" class="size-16 object-cover" />
        </button>
        <span v-else class="grid size-16 shrink-0 place-items-center rounded-[9px] bg-surface-2 text-muted dark:bg-surface-3"><component :is="categoryIcon(item.category.icon)" :size="22" aria-hidden="true" /></span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-base font-semibold text-fg">{{ item.model ? `${item.name} · ${item.model}` : item.name }}</p>
          <p class="truncate text-xs text-muted">{{ [item.number, item.serial ? t("lifecycle.equipment.serial", { serial: item.serial }) : "", item.notes].filter(Boolean).join(" · ") }}</p>
          <p class="mt-1 text-xs text-muted">
            {{ t("lifecycle.equipment.givenOn", { date: fmt.day(item.issued_on, "medium") }) }} ·
            {{ t(`lifecycle.equipment.condition.${item.condition_out}`) }}<template v-if="item.note_out"> · «{{ item.note_out }}»</template>
          </p>
          <StatusPill
            class="mt-1.5"
            size="sm"
            :tone="confirmed.tone"
            :label="item.acknowledged_at ? t('lifecycle.equipment.confirmedAt', { date: fmt.instant(item.acknowledged_at, 'datetime') }) : t('lifecycle.equipment.notConfirmed')"
          />
        </div>
      </div>

      <RadioCards v-model="form.outcome" :options="outcomes" :columns="2" />
      <p v-if="!options.writeOff" class="-mt-2 text-xs text-muted">{{ t("lifecycle.equipment.return.deviceNote") }}</p>

      <template v-if="form.outcome === 'returned'">
        <FormField :label="t('lifecycle.equipment.return.conditionIn')">
          <SegmentedControl v-model="form.condition" :options="conditions" size="sm" block :aria-label="t('lifecycle.equipment.return.conditionIn')" />
        </FormField>
        <FormField :label="t('lifecycle.equipment.field.photo')" :hint="t('lifecycle.equipment.return.photoHint')" optional>
          <PhotoField v-model="form.photo" />
        </FormField>
        <ToggleSwitch
          v-if="damaged"
          v-model="form.writeOff"
          layout="row"
          :disabled="!options.writeOff"
          :label="t('lifecycle.equipment.return.writeOff')"
          :description="options.writeOff ? t('lifecycle.equipment.return.writeOffHint') : t('lifecycle.equipment.return.deviceNote')"
          data-write-off
        />
      </template>

      <FormField :label="t('lifecycle.equipment.field.note')" optional>
        <TextArea v-model="form.note" :rows="2" :maxlength="300" :placeholder="form.outcome === 'lost' ? t('lifecycle.equipment.return.lostPlaceholder') : t('lifecycle.equipment.return.notePlaceholder')" />
      </FormField>

      <!-- A deduction, when something is lost or damaged. -->
      <section v-if="lossOrDamage || start === 'deduct'" class="flex flex-col gap-3 rounded-[12px] border border-line p-3" data-deduction>
        <ToggleSwitch v-model="form.deduct" layout="row" :disabled="!options.deduct" :label="t('lifecycle.equipment.deduction.toggle')" :description="t('lifecycle.equipment.deduction.hint')" />
        <InlineAlert v-if="options.deductWhy" tone="neutral" size="sm" :description="t(`lifecycle.equipment.deduction.why.${options.deductWhy}`)" />
        <div v-if="form.deduct" class="grid gap-3 sm:grid-cols-[minmax(0,12rem)_1fr]">
          <FormField :label="t('lifecycle.equipment.deduction.amount')" :error="message(errors.amount)" :hint="item.value ? undefined : t('lifecycle.equipment.deduction.amountHint')" required>
            <MoneyInput v-model="form.amount" :currencies="[company.currency]" :invalid="!!errors.amount" />
          </FormField>
          <FormField :label="t('lifecycle.equipment.deduction.reason')" optional>
            <TextInput v-model="form.reason" :maxlength="300" :placeholder="t('lifecycle.equipment.deduction.reasonPlaceholder', { item: item.name })" />
          </FormField>
        </div>
      </section>

      <FormField :label="t('lifecycle.equipment.field.day')" :error="message(errors.on)" required>
        <DatePicker v-model="form.on" :max="today" :invalid="!!errors.on" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton :variant="form.outcome === 'lost' ? 'danger' : 'primary'" :icon="form.outcome === 'lost' ? PackageX : form.deduct ? HandCoins : Undo2" :loading="save.isPending.value" data-return-submit @click="submit">
        {{ form.outcome === "lost" ? t("lifecycle.equipment.return.submitLost") : t("lifecycle.equipment.return.submit") }}
      </UiButton>
    </template>
    <ImageLightbox v-if="lightbox" v-model:open="lightbox" :images="photos" :title="item.name" />
  </UiDialog>
</template>
