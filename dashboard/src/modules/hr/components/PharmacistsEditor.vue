<script setup lang="ts">
/**
 * Who counts as a pharmacist on duty (the setup step `hr.pharmacists`, plan §14.9): each position
 * is a head of pharmacy, a senior pharmacist (provizor), a pharmacist (farmatsevt) or none. Saving
 * asks a position with no documents yet for the standard set of its kind; documents changed by hand
 * stay ("its own documents"). Required documents are never guessed from a position's name.
 */
import { BadgeCheck } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import type { SelectOption } from "@/components/options";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { hrApi, usePharmacists, useRefresh } from "../api";
import type { PharmacistPosition, PharmacistRole } from "../types";

type Choice = PharmacistRole | "none";

const { t } = useI18n();
const companyId = useCompanyId();
const refresh = useRefresh();
const query = usePharmacists();
const choices = ref<Record<number, Choice>>({});
const saving = ref(false);

watch(
  () => query.data.value,
  (value) => {
    if (value) choices.value = Object.fromEntries(value.positions.map((row) => [row.position.id, row.role ?? "none"]));
  },
  { immediate: true },
);

const rows = computed(() => query.data.value?.positions ?? []);
const changed = computed(() => rows.value.filter((row) => (choices.value[row.position.id] ?? "none") !== (row.role ?? "none")));
const counting = computed(() => rows.value.filter((row) => (choices.value[row.position.id] ?? "none") !== "none").length);

function options(row: PharmacistPosition): SelectOption<Choice>[] {
  const list: SelectOption<Choice>[] = [
    { value: "none", label: t("hr.pharmacists.role.none") },
    { value: "head", label: t("hr.pharmacists.role.head"), description: t("hr.pharmacists.roleHint.head") },
    { value: "senior", label: t("hr.pharmacists.role.senior"), description: t("hr.pharmacists.roleHint.senior") },
    { value: "pharmacist", label: t("hr.pharmacists.role.pharmacist"), description: t("hr.pharmacists.roleHint.pharmacist") },
  ];
  if (row.role === "custom") list.push({ value: "custom", label: t("hr.pharmacists.role.custom"), description: t("hr.pharmacists.roleHint.custom") });
  return list;
}

function documentLabel(item: PharmacistPosition["required"][number]): string {
  const name = item.level ? `${t(`hr.kind.${item.kind}`)} (${t(`hr.level.${item.level}`)})` : t(`hr.kind.${item.kind}`);
  const others = item.alternatives.map((kind) => t(`hr.kind.${kind}`));
  return others.length ? t("hr.pharmacists.orOthers", { name, others: others.join(", ") }) : name;
}

async function save(): Promise<void> {
  if (!changed.value.length) return;
  saving.value = true;
  try {
    await hrApi.savePharmacists(
      companyId.value,
      changed.value.map((row) => {
        const choice = choices.value[row.position.id] ?? "none";
        return { id: row.position.id, role: choice === "none" ? null : choice };
      }),
    );
    toast.success(t("hr.pharmacists.saved"));
    refresh();
  } catch {
    // The HTTP layer said why.
  } finally {
    saving.value = false;
  }
}

function reset(): void {
  for (const row of rows.value) choices.value[row.position.id] = row.role ?? "none";
}
</script>

<template>
  <div class="flex flex-col" data-pharmacists>
    <div v-if="query.isPending.value" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 3" :key="n" height="44px" /></div>
    <ErrorState v-else-if="query.isError.value" compact class="m-4" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="!rows.length" size="sm" tone="neutral" :icon="BadgeCheck" :title="t('hr.pharmacists.noPositions')" :description="t('hr.pharmacists.noPositionsBody')" />
    <template v-else>
      <ul class="flex flex-col divide-y divide-line">
        <li v-for="row in rows" :key="row.position.id" class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start sm:gap-6 md:px-5" :data-position="row.position.id">
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-fg">{{ row.position.name }}</p>
            <p class="mt-0.5 text-xs text-muted">{{ t("hr.pharmacists.people", { n: row.people }, row.people) }}</p>
            <p v-if="row.role && row.required.length" class="mt-1 text-xs text-muted">
              {{ t("hr.pharmacists.asks") }} {{ row.required.map(documentLabel).join(" · ") }}
            </p>
            <p v-else-if="row.role" class="mt-1 text-xs text-warning">{{ t("hr.pharmacists.asksNothing") }}</p>
          </div>
          <div class="w-full shrink-0 sm:w-64">
            <SelectBox v-model="choices[row.position.id]" :options="options(row)" :aria-label="t('hr.pharmacists.choose', { position: row.position.name })" />
          </div>
        </li>
      </ul>
      <footer class="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3 md:px-5">
        <p class="flex-1 text-xs text-muted">{{ counting ? t("hr.pharmacists.counting", { n: counting }, counting) : t("hr.pharmacists.noneCounting") }}</p>
        <UiButton v-if="changed.length" variant="ghost" size="sm" @click="reset">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" size="sm" :disabled="!changed.length" :loading="saving" data-save-pharmacists @click="save">{{ t("common.save") }}</UiButton>
      </footer>
    </template>
  </div>
</template>
