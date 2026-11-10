<script setup lang="ts">
/**
 * Person 360's "Equipment" tab: what they hold now (with the photo taken when it was given, whether
 * they confirmed it in the app, and what to do with it), and what they were given before: when it
 * came back and in what state, lost or written off, the deduction proposed.
 */
import { HandCoins, HandHelping, History, PackageCheck, PackageX } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ImageLightbox, { type LightboxImage } from "@/components/ImageLightbox.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useAssetsOn, useEquipmentPerson } from "./api";
import DeductionDialog from "./DeductionDialog.vue";
import IssueDialog from "./IssueDialog.vue";
import { categoryIcon, confirmation, OUTCOME_TONES, returnOptions } from "./lib";
import ReturnDialog from "./ReturnDialog.vue";
import type { HeldItem, HistoryItem } from "./types";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const assetsOn = useAssetsOn();
const page = useEquipmentPerson(() => props.memberId);
const data = computed(() => page.data.value ?? null);
const past = computed(() => (data.value?.history ?? []).filter((row) => row.outcome !== "held"));
const current = computed(() => data.value?.holder.person.status === "approved" || data.value?.holder.person.status === "suspended");

let key = 0;
const giving = ref<number | null>(null);
const returning = ref<{ item: HeldItem; start: "returned" | "lost"; key: number } | null>(null);
const deducting = ref<{ item: HeldItem; key: number } | null>(null);
const giveOpen = computed({ get: () => giving.value !== null, set: (value: boolean) => !value && (giving.value = null) });
const returnOpen = computed({ get: () => returning.value !== null, set: (value: boolean) => !value && (returning.value = null) });
const deductOpen = computed({ get: () => deducting.value !== null, set: (value: boolean) => !value && (deducting.value = null) });

const photos = ref<LightboxImage[]>([]);
const lightbox = ref(false);
function show(row: HistoryItem | HeldItem): void {
  const list: LightboxImage[] = [];
  if (row.photo_url) list.push({ src: row.photo_url, alt: t("lifecycle.equipment.photo.given") });
  if ("photo_in_url" in row && row.photo_in_url) list.push({ src: row.photo_in_url, alt: t("lifecycle.equipment.photo.back") });
  photos.value = list;
  lightbox.value = list.length > 0;
}
const outcomeLabel = (row: HistoryItem) =>
  row.outcome === "returned" ? t("lifecycle.equipment.history.returned", { date: fmt.day(row.returned_on!, "medium") }) : t(`lifecycle.equipment.history.${row.outcome}`, { date: row.returned_on ? fmt.day(row.returned_on, "medium") : "" });
</script>

<template>
  <div class="flex flex-col gap-4" data-equipment-tab>
    <div v-if="!assetsOn" class="ui-card">
      <EmptyState size="sm" tone="neutral" :title="t('lifecycle.equipment.off.title')" :description="t('lifecycle.equipment.off.body')" />
    </div>
    <div v-else-if="page.isPending.value" class="flex flex-col gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="76px" radius="14px" /></div>
    <ErrorState v-else-if="page.isError.value" class="ui-card" :error="page.error.value" :retry="() => page.refetch()" />
    <template v-else-if="data">
      <section class="ui-card overflow-hidden">
        <header class="flex items-center gap-3 border-b border-line px-4 py-3">
          <div class="min-w-0 flex-1">
            <h2 class="text-md font-semibold text-fg">{{ t("lifecycle.equipment.tabNow") }}</h2>
            <p class="text-xs text-muted">
              {{ t("lifecycle.equipment.itemsCount", { n: data.holder.items.length }, data.holder.items.length) }}
              <template v-if="data.can.values && data.holder.items.length"> · <MoneyText :value="data.holder.value" :currency="company.currency" /></template>
            </p>
          </div>
          <UiButton v-if="current" size="sm" variant="primary" :icon="HandHelping" data-tab-give @click="giving = ++key">{{ t("lifecycle.equipment.give") }}</UiButton>
        </header>
        <ul v-if="data.holder.items.length" class="divide-y divide-[var(--c-border)]">
          <li v-for="item in data.holder.items" :key="item.assignment_id" class="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center" :data-tab-item="item.assignment_id">
            <div class="flex min-w-0 flex-1 items-center gap-3">
              <button v-if="item.photo_url" type="button" class="shrink-0 overflow-hidden rounded-[10px] ring-1 ring-line" :aria-label="t('lifecycle.equipment.photo.open')" @click="show(item)">
                <img :src="item.photo_url" alt="" class="size-12 object-cover" />
              </button>
              <span v-else class="grid size-12 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted dark:bg-surface-3"><component :is="categoryIcon(item.category.icon)" :size="18" aria-hidden="true" /></span>
              <div class="min-w-0 flex-1">
                <p class="truncate text-base font-medium text-fg">{{ item.model ? `${item.name} · ${item.model}` : item.name }}</p>
                <p class="truncate text-xs text-muted">{{ [item.number, item.category.name, item.notes].filter(Boolean).join(" · ") }}</p>
                <div class="mt-1 flex flex-wrap items-center gap-1.5">
                  <span class="text-xs text-muted">{{ t("lifecycle.equipment.givenOn", { date: fmt.day(item.issued_on, "medium") }) }}</span>
                  <StatusPill size="sm" :tone="confirmation(item, data.today).tone" :label="item.acknowledged_at ? t('lifecycle.equipment.confirmedAt', { date: fmt.instant(item.acknowledged_at, 'datetime') }) : t('lifecycle.equipment.notConfirmed')" />
                  <StatusPill v-if="item.deduction" size="sm" tone="info" :icon="HandCoins" :label="t(`lifecycle.equipment.deduction.status.${item.deduction.status}`)" />
                </div>
              </div>
            </div>
            <div class="flex shrink-0 flex-wrap gap-1.5 sm:justify-end">
              <UiButton size="sm" variant="secondary" :icon="PackageCheck" @click="returning = { item, start: 'returned', key: ++key }">{{ t("lifecycle.equipment.action.returnedShort") }}</UiButton>
              <UiButton v-if="item.may_write_off" size="sm" variant="ghost" :icon="PackageX" @click="returning = { item, start: 'lost', key: ++key }">{{ t("lifecycle.equipment.action.lostShort") }}</UiButton>
              <UiButton v-if="returnOptions(data.holder, item, data.can).deduct" size="sm" variant="ghost" :icon="HandCoins" @click="deducting = { item, key: ++key }">{{ t("lifecycle.equipment.action.deductShort") }}</UiButton>
            </div>
          </li>
        </ul>
        <EmptyState v-else size="sm" tone="neutral" :icon="HandHelping" :title="t('lifecycle.equipment.holdsNothing')" :description="current ? t('lifecycle.equipment.tabEmpty') : undefined" />
      </section>

      <section v-if="past.length" class="ui-card overflow-hidden">
        <header class="flex items-center gap-2 border-b border-line px-4 py-3">
          <History :size="16" class="text-subtle" aria-hidden="true" />
          <h2 class="text-md font-semibold text-fg">{{ t("lifecycle.equipment.tabBefore") }}</h2>
        </header>
        <ul class="divide-y divide-[var(--c-border)]">
          <li v-for="row in past" :key="row.assignment_id" class="flex items-start gap-3 px-4 py-3" :data-history="row.assignment_id">
            <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted dark:bg-surface-3"><component :is="categoryIcon(row.category.icon)" :size="16" aria-hidden="true" /></span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <p class="min-w-0 truncate text-sm font-medium text-fg">{{ row.name }}</p>
                <StatusPill size="sm" variant="outline" :tone="OUTCOME_TONES[row.outcome]" :label="outcomeLabel(row)" />
              </div>
              <p class="truncate text-xs text-muted">
                {{ t("lifecycle.equipment.givenOn", { date: fmt.day(row.issued_on, "medium") }) }}
                <template v-if="row.condition_in"> · {{ t("lifecycle.equipment.history.cameBack", { condition: t(`lifecycle.equipment.condition.${row.condition_in}`).toLocaleLowerCase() }) }}</template>
                <template v-if="row.note_in"> · «{{ row.note_in }}»</template>
              </p>
              <p v-if="row.deduction" class="mt-0.5 text-xs text-info">
                {{ t(`lifecycle.equipment.deduction.status.${row.deduction.status}`) }}<template v-if="row.deduction.amount">: <MoneyText :value="row.deduction.amount" :currency="company.currency" /></template>
              </p>
            </div>
            <button v-if="row.photo_url || row.photo_in_url" type="button" class="shrink-0 text-xs font-semibold text-primary hover:underline" @click="show(row)">{{ t("lifecycle.equipment.photo.see") }}</button>
          </li>
        </ul>
      </section>
    </template>

    <IssueDialog v-if="giving !== null && data" :key="giving" v-model:open="giveOpen" :person="{ id: data.holder.person.id, name: data.holder.person.name }" />
    <ReturnDialog v-if="returning && data" :key="returning.key" v-model:open="returnOpen" :holder="data.holder" :item="returning.item" :can="data.can" :start="returning.start" />
    <DeductionDialog v-if="deducting && data" :key="deducting.key" v-model:open="deductOpen" :holder="data.holder" :item="deducting.item" />
    <ImageLightbox v-if="lightbox" v-model:open="lightbox" :images="photos" />
  </div>
</template>
