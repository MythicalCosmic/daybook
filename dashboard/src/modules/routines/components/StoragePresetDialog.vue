<script setup lang="ts">
/**
 * "Set up storage readings" (PLAN-OWNER §14.10): one dialog makes a branch's temperature and
 * humidity journal as routines. For each reading time, a readings routine per fridge (2–8 °C,
 * critical) and one for the room (temperature and humidity), from Settings → Routines; then daily
 * wet cleaning, weekly disinfection and the dispensing camera check. They're shared ("one of us
 * does it"): the first person to finish closes everyone else's copy. Running it again adds only
 * what the branch doesn't have yet.
 */
import { Plus, Settings2, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useApplyPreset, usePlanOptions, usePresetDefaults } from "../api";
import { rangeText } from "../readings";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ done: [created: number] }>();

const MAX_TIMES = 4;
const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const options = usePlanOptions();
const apply = useApplyPreset();

const branches = computed(() => company.current?.branches ?? []);
const branch = ref<number | null>(null);
const defaults = usePresetDefaults(branch);
const fridges = ref<number | null>(1);
const times = ref<string[]>([]);
const positions = ref<number[]>([]);
const adding = ref<string | null>(null);

watch(
  open,
  (value) => {
    if (!value) return;
    if (branch.value === null && branches.value.length) branch.value = branches.value[0]!.id;
  },
  { immediate: true },
);
// A branch's defaults: the company's times, every position at the branch.
watch(
  () => defaults.data.value,
  (value) => {
    if (!value) return;
    fridges.value = value.fridges;
    times.value = [...value.times];
    positions.value = value.positions.map((position) => position.id);
  },
  { immediate: true },
);

const ranges = computed(() => {
  const value = defaults.data.value;
  if (!value) return [];
  const lang = fmt.lang.value;
  return [
    { id: "fridge", label: t("routines.preset.fridge"), range: rangeText(value.fridge.min, value.fridge.max, "°C", lang) },
    { id: "room", label: t("routines.preset.room"), range: rangeText(value.room.min, value.room.max, "°C", lang) },
    { id: "humidity", label: t("routines.preset.humidity"), range: rangeText(null, value.humidity_max, "%", lang) },
  ];
});

/** What it makes, as the dialog stands. */
const plan = computed(() => {
  const count = fridges.value ?? 0;
  const perTime = [...Array.from({ length: count }, (_, index) => t("routines.preset.fridgeN", { n: index + 1 })), t("routines.preset.roomRow")];
  return {
    readings: times.value.map((time) => ({ time, rows: perTime })),
    others: [t("routines.preset.cleaning"), t("routines.preset.disinfection"), t("routines.preset.camera")],
  };
});

function addTime(): void {
  const value = adding.value;
  if (!value || times.value.includes(value) || times.value.length >= MAX_TIMES) return;
  times.value = [...times.value, value].sort();
  adding.value = null;
}
function removeTime(value: string): void {
  times.value = times.value.filter((time) => time !== value);
}

const ready = computed(() => !!branch.value && times.value.length > 0 && positions.value.length > 0 && fridges.value !== null);

async function submit(): Promise<void> {
  if (!ready.value || branch.value === null) return;
  try {
    const result = await apply.mutateAsync({ branch: branch.value, fridges: fridges.value ?? 0, positions: positions.value, times: times.value });
    const made = result.created.length;
    if (made) toast.success(t("routines.preset.made", { n: made }, made), { description: t("routines.preset.madeHint") });
    else toast.info(t("routines.preset.nothingNew"), { description: t("routines.preset.nothingNewHint") });
    open.value = false;
    emit("done", made);
  } catch {
    // the HTTP layer showed why
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('routines.preset.title')" :description="t('routines.preset.description')" size="lg">
    <form class="flex flex-col gap-4" data-testid="storage-preset" @submit.prevent="submit">
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('routines.preset.branch')" required>
          <BranchPicker v-model="branch" />
        </FormField>
        <FormField :label="t('routines.preset.fridges')" :hint="t('routines.preset.fridgesHint')">
          <NumberInput v-model="fridges" :min="0" :max="5" steppers />
        </FormField>
      </div>

      <FormField :label="t('routines.preset.times')" :hint="t('routines.preset.timesHint')" required>
        <div class="flex flex-wrap items-center gap-2">
          <span v-for="time in times" :key="time" class="inline-flex items-center gap-1 rounded-full bg-surface-2 py-0.5 pl-2.5 pr-1 text-sm font-medium tabular-nums">
            {{ time }}
            <button type="button" class="grid size-5 place-items-center rounded-full text-muted hover:bg-surface hover:text-fg" :aria-label="t('routines.preset.removeTime', { time })" @click="removeTime(time)">
              <X :size="12" aria-hidden="true" />
            </button>
          </span>
          <template v-if="times.length < MAX_TIMES">
            <TimePicker v-model="adding" :step="15" size="sm" class="w-[110px]" />
            <UiButton size="sm" variant="ghost" :icon="Plus" :disabled="!adding" @click="addTime">{{ t("routines.preset.addTime") }}</UiButton>
          </template>
        </div>
      </FormField>

      <FormField :label="t('routines.preset.positions')" :hint="t('routines.preset.positionsHint')" required>
        <PositionPicker v-model="positions" multiple :positions="options.data.value?.positions ?? []" />
      </FormField>

      <div class="rounded-[10px] border border-line bg-surface-2/40 p-3 text-sm">
        <p class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span class="font-medium text-fg">{{ t("routines.preset.ranges") }}</span>
          <span v-for="item in ranges" :key="item.id" class="text-muted">{{ item.label }}: <span class="font-medium tabular-nums text-fg">{{ item.range }}</span></span>
        </p>
        <RouterLink :to="`/c/${company.currentId}/settings/routines`" class="mt-1 inline-flex items-center gap-1 text-sm font-medium text-accent-fg hover:underline" @click="open = false">
          <Settings2 :size="14" aria-hidden="true" />{{ t("routines.preset.changeRanges") }}
        </RouterLink>
        <p class="mt-1 text-xs text-muted">{{ t("routines.preset.confirmLaw") }}</p>
      </div>

      <div class="text-sm" data-testid="preset-plan">
        <p class="font-medium text-fg">{{ t("routines.preset.makes") }}</p>
        <ul class="mt-1 list-disc pl-5 text-muted">
          <li v-for="slot in plan.readings" :key="slot.time"><span class="tabular-nums">{{ slot.time }}</span>: {{ slot.rows.join(", ") }}</li>
          <li>{{ plan.others.join(", ") }}</li>
        </ul>
        <p class="mt-2 text-xs text-muted">{{ t("routines.preset.shared") }}</p>
        <p v-if="defaults.data.value?.existing" class="mt-1 text-xs text-muted">{{ t("routines.preset.again", { n: defaults.data.value.existing }, defaults.data.value.existing) }}</p>
      </div>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :disabled="!ready" :loading="apply.isPending.value" @click="submit">{{ t("routines.preset.apply") }}</UiButton>
    </template>
  </UiDialog>
</template>
