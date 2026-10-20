<script setup lang="ts">
/**
 * A branch in a drawer (`?branch=12`, or `?branch=new`): name and code, address and phone, the
 * place and check-in circle on a map, opening hours and days, the manager and the cash limit.
 * Closing a branch keeps its history; its audit trail is at the bottom.
 */
import { Archive, ArchiveRestore, History, MapPin } from "@lucide/vue";
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { z } from "zod";

import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import type { PersonOption } from "@/components/pickers";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import WeekdayPicker from "@/components/WeekdayPicker.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useForm } from "@/lib/useForm";
import { closeQueryKey } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useBranchMutations, useManagers } from "../api";
import type { Branch, BranchInput } from "../types";
import MapPicker from "./MapPicker.vue";

const AuditTrail = defineAsyncComponent(() => import("@/components/AuditTrail.vue"));

const props = defineProps<{ branches: Branch[]; canEdit: boolean }>();

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const mutations = useBranchMutations();

const value = computed(() => {
  const raw = route.query.branch;
  return (Array.isArray(raw) ? raw[0] : raw) ?? null;
});
const isNew = computed(() => value.value === "new");
const branch = computed(() => (isNew.value ? null : (props.branches.find((b) => String(b.id) === value.value) ?? null)));
const managers = useManagers(computed(() => value.value !== null && props.canEdit));
const people = computed<PersonOption[]>(() =>
  (managers.data.value ?? []).map((m) => ({ id: m.id, name: m.name, photo_url: m.photo_url, subtitle: [m.position, m.branch].filter(Boolean).join(" · ") || undefined })),
);
const showHistory = ref(false);

const schema = z
  .object({
    name: z.string().trim().min(1, "common.form.required").max(100, "common.form.tooLong"),
    code: z.string().trim().max(8, "common.form.tooLong").regex(/^[A-Za-z0-9]*$/, "settings.branch.codeInvalid"),
    address: z.string().max(255, "common.form.tooLong"),
    phone: z.string().max(20, "common.form.tooLong"),
    latitude: z.string().nullable(),
    longitude: z.string().nullable(),
    geofence_m: z.number({ message: "common.form.number" }).int().min(25, "settings.branch.radiusRange").max(5000, "settings.branch.radiusRange"),
    opens_at: z.string().nullable(),
    closes_at: z.string().nullable(),
    open_weekdays: z.array(z.number().int().min(0).max(6)),
    manager_id: z.number().nullable(),
    cash_limit: z.string().nullable(),
  })
  .refine((v) => (v.opens_at === null) === (v.closes_at === null), { path: ["closes_at"], message: "settings.branch.bothTimes" });

type Values = z.input<typeof schema>;

function valuesOf(source: Branch | null): Values {
  return {
    name: source?.name ?? "",
    code: source?.code ?? "",
    address: source?.address ?? "",
    phone: source?.phone ?? "",
    latitude: source?.latitude ?? null,
    longitude: source?.longitude ?? null,
    geofence_m: source?.geofence_m ?? 150,
    opens_at: source?.opens_at ?? "09:00",
    closes_at: source?.closes_at ?? "21:00",
    open_weekdays: [...(source?.open_weekdays ?? [0, 1, 2, 3, 4, 5, 6])],
    manager_id: source?.manager?.id ?? null,
    cash_limit: source?.cash_limit ?? null,
  };
}

const form = useForm(schema, valuesOf(null), {
  onSubmit: async (values) => {
    const input: Partial<BranchInput> = { ...values, code: values.code.toUpperCase() };
    if (isNew.value) {
      const created = await mutations.create.mutateAsync(input);
      toast.success(t("settings.branch.created", { name: created.name }));
    } else if (branch.value) {
      await mutations.update.mutateAsync({ id: branch.value.id, input });
      toast.success(t("settings.branch.saved"));
    }
    close();
  },
});

watch(
  [value, branch],
  ([next, current], [previous]) => {
    if (next !== previous || (current && !form.dirty.value)) {
      form.reset(valuesOf(current));
      showHistory.value = false;
    }
  },
  { immediate: true },
);

const radii = [50, 100, 150, 300, 500];
const radiusOptions = computed(() => radii.map((m) => ({ value: m, label: `${m} m` })));
const radiusChoice = computed({
  get: () => (radii.includes(form.values.geofence_m) ? form.values.geofence_m : (null as unknown as number)),
  set: (metres: number) => (form.values.geofence_m = metres),
});

function close(): void {
  closeQueryKey(router, "branch");
}

async function toggleActive(): Promise<void> {
  const current = branch.value;
  if (!current) return;
  if (current.is_active) {
    const answer = await confirm({
      title: t("settings.branch.closeTitle", { name: current.name }),
      message: t("settings.branch.closeBody"),
      confirmLabel: t("settings.branch.close"),
      tone: "danger",
    });
    if (!answer) return;
    await mutations.deactivate.mutateAsync(current.id);
    toast.success(t("settings.branch.closed", { name: current.name }));
  } else {
    await mutations.activate.mutateAsync(current.id);
    toast.success(t("settings.branch.reopened", { name: current.name }));
  }
}

const title = computed(() => (isNew.value ? t("settings.branch.new") : (branch.value?.name ?? t("settings.panel.branches"))));
const company_ = computed(() => company.current);
</script>

<template>
  <UiDrawer query-key="branch" :title="title" :description="isNew ? t('settings.branch.newHint') : (branch?.address || undefined)" size="lg">
    <form v-if="isNew || branch" id="branch-form" class="flex flex-col gap-6 p-5" novalidate @submit="form.submit">
      <div class="grid gap-4 sm:grid-cols-[1fr_170px]">
        <FormField :label="t('settings.branch.name')" :error="form.errors.name" required>
          <TextInput v-model="form.values.name" :maxlength="100" :disabled="!canEdit" :autofocus="isNew" :placeholder="t('settings.branch.namePlaceholder')" @blur="form.touch('name')" />
        </FormField>
        <FormField :label="t('settings.branch.code')" :hint="t('settings.branch.codeHint')" :error="form.errors.code" optional>
          <TextInput v-model="form.values.code" :maxlength="8" mono :disabled="!canEdit" placeholder="CHL" @blur="form.touch('code')" />
        </FormField>
      </div>

      <div class="grid gap-4 sm:grid-cols-[1fr_200px]">
        <FormField :label="t('settings.branch.address')" :error="form.errors.address" optional>
          <TextInput v-model="form.values.address" :icon="MapPin" :maxlength="255" :disabled="!canEdit" :placeholder="t('settings.branch.addressPlaceholder')" />
        </FormField>
        <FormField :label="t('settings.branch.phone')" :error="form.errors.phone" optional>
          <TextInput v-model="form.values.phone" type="tel" inputmode="tel" :maxlength="20" :disabled="!canEdit" placeholder="+998 71 200 01 01" />
        </FormField>
      </div>

      <section class="flex flex-col gap-3">
        <div>
          <p class="text-base font-semibold text-fg">{{ t("settings.branch.place") }}</p>
          <p class="text-sm text-muted">{{ t("settings.branch.placeHint") }}</p>
        </div>
        <MapPicker
          :latitude="form.values.latitude"
          :longitude="form.values.longitude"
          :radius="form.values.geofence_m"
          :editable="canEdit"
          @pick="(at) => { form.values.latitude = at.latitude; form.values.longitude = at.longitude; }"
        />
        <div class="flex flex-wrap items-end gap-3">
          <FormField :label="t('settings.branch.radius')" :error="form.errors.geofence_m" class="w-[170px]">
            <NumberInput v-model="form.values.geofence_m" :min="25" :max="5000" :step="25" suffix="m" :disabled="!canEdit" />
          </FormField>
          <SegmentedControl v-model="radiusChoice" :options="radiusOptions" size="sm" :disabled="!canEdit" class="mb-0.5" :aria-label="t('settings.branch.radius')" />
        </div>
        <p v-if="form.values.latitude" class="text-xs tabular-nums text-subtle">{{ form.values.latitude }}, {{ form.values.longitude }}</p>
      </section>

      <section class="flex flex-col gap-4">
        <p class="text-base font-semibold text-fg">{{ t("settings.branch.hours") }}</p>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('settings.branch.opens')" :error="form.errors.opens_at">
            <TimePicker v-model="form.values.opens_at" :step="15" :disabled="!canEdit" />
          </FormField>
          <FormField :label="t('settings.branch.closes')" :error="form.errors.closes_at">
            <TimePicker v-model="form.values.closes_at" :step="15" :disabled="!canEdit" />
          </FormField>
        </div>
        <FormField :label="t('settings.branch.days')" :hint="t('settings.branch.daysHint')">
          <WeekdayPicker v-model="form.values.open_weekdays" presets :disabled="!canEdit" />
        </FormField>
      </section>

      <section class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('settings.branch.manager')" :hint="t('settings.branch.managerHint')" optional>
          <PersonPicker v-model="form.values.manager_id" :people="people" :disabled="!canEdit" :placeholder="t('settings.branch.managerPlaceholder')" />
        </FormField>
        <FormField :label="t('settings.branch.cashLimit')" :hint="t('settings.branch.cashLimitHint')" optional>
          <MoneyInput v-model="form.values.cash_limit" :currencies="[company_?.base_currency ?? 'UZS']" :disabled="!canEdit" />
        </FormField>
      </section>

      <p v-if="form.formError.value" class="rounded-[8px] bg-danger-soft px-3 py-2 text-sm text-danger">{{ form.formError.value }}</p>

      <section v-if="branch" class="border-t border-line pt-5">
        <UiButton variant="ghost" size="sm" :icon="History" @click="showHistory = !showHistory">{{ t("settings.branch.history") }}</UiButton>
        <div v-if="showHistory" class="mt-3">
          <AuditTrail target-type="branch" :target-id="branch.id" />
        </div>
      </section>
    </form>
    <template #footer>
      <UiButton
        v-if="branch && canEdit"
        variant="ghost"
        :icon="branch.is_active ? Archive : ArchiveRestore"
        class="mr-auto"
        :loading="mutations.deactivate.isPending.value || mutations.activate.isPending.value"
        @click="toggleActive"
      >{{ branch.is_active ? t("settings.branch.close") : t("settings.branch.reopen") }}</UiButton>
      <UiButton variant="ghost" @click="close">{{ t("common.cancel") }}</UiButton>
      <UiButton v-if="canEdit" variant="primary" type="submit" form="branch-form" :loading="form.submitting.value">
        {{ isNew ? t("settings.branch.add") : t("common.save") }}
      </UiButton>
    </template>
  </UiDrawer>
</template>
