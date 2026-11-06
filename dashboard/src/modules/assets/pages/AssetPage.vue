<script setup lang="ts">
/**
 * One asset: what it is worth today and why. KPIs (cost, depreciation so far, book value, this
 * month's, months left), its book value over the whole life (posted solid, planned dashed), the
 * schedule by year (each month: old books, posted, in Finance or planned), the tax book and its
 * difference, details and upkeep with days left, who held it when, photos and documents, the
 * timeline of everything that happened, and a QR label to stick on it. Every step is in the
 * actions menu; each answers with the page, so it updates at once.
 */
import {
  ArrowLeftRight,
  BadgeCheck,
  ChevronDown,
  CirclePause,
  CirclePlay,
  Gauge,
  HandHelping,
  ImagePlus,
  MoreHorizontal,
  PackageMinus,
  PackagePlus,
  Pencil,
  Sparkles,
  Tag,
  Trash2,
  TrendingDown,
  Undo2,
  Wrench,
} from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DescriptionList from "@/components/DescriptionList.vue";
import DropdownMenu from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import LineChart from "@/components/LineChart.vue";
import type { MenuEntry } from "@/components/menuTypes";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import QrCode from "@/components/QrCode.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { assetsApi, useItem, useRefresh } from "../api";
import AssetActionDialog from "../components/AssetActionDialog.vue";
import AssetFormDialog from "../components/AssetFormDialog.vue";
import { bookValueSeries, categoryIcon, daysUntil, EVENT_ICONS, EVENT_TONES, STATUS_TONES, UPKEEP_ICONS, upkeepTone, yearsOf } from "../lib";
import type { ActionKind, AssetEvent, UpkeepKind } from "../types";

const { t, te } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const id = computed(() => Number(route.params.assetId));
const item = useItem(id);
const page = computed(() => item.data.value);
const asset = computed(() => page.value?.asset);
const canManage = computed(() => company.can("assets.manage"));
const live = computed(() => asset.value && asset.value.status !== "disposed");
const today = useCompanyToday();

const editing = ref(false);
const action = ref<ActionKind | null>(null);
const actionOpen = ref(false);
function act(kind: ActionKind): void {
  action.value = kind;
  actionOpen.value = true;
}

const menu = computed<MenuEntry[]>(() => {
  const current = page.value;
  if (!current || !canManage.value) return [];
  const entries: MenuEntry[] = [{ label: t("assets.item.edit"), icon: Pencil, onSelect: () => (editing.value = true) }];
  if (live.value) {
    entries.push({ type: "separator" });
    if (!current.asset.in_service_on) entries.push({ label: t("assets.action.in-service.title"), icon: CirclePlay, onSelect: () => act("in-service") });
    entries.push({ label: t("assets.action.move.title"), icon: ArrowLeftRight, onSelect: () => act("move") });
    entries.push(
      current.asset.custodian
        ? { label: t("assets.action.return.title"), icon: Undo2, onSelect: () => act("return") }
        : { label: t("assets.action.issue.title"), icon: HandHelping, onSelect: () => act("issue") },
    );
    entries.push({ type: "separator" });
    entries.push({ label: t("assets.action.service.title"), icon: Sparkles, onSelect: () => act("service") });
    if (current.verify_months || current.next_verification_on) entries.push({ label: t("assets.action.verification.title"), icon: BadgeCheck, onSelect: () => act("verification") });
    entries.push({ label: t("assets.action.repair.title"), icon: Wrench, onSelect: () => act("repair") });
    if (current.asset.status !== "suspended") entries.push({ label: t("assets.action.status.title"), icon: Wrench, onSelect: () => act("status") });
    if (current.asset.category_kind !== "low_value") {
      entries.push({ type: "separator" });
      entries.push({ label: t("assets.action.addition.title"), icon: PackagePlus, onSelect: () => act("addition") });
      entries.push({ label: t("assets.action.write-down.title"), icon: TrendingDown, onSelect: () => act("write-down") });
      entries.push({ label: t("assets.action.estimate.title"), icon: Gauge, onSelect: () => act("estimate") });
      if (current.method === "units") entries.push({ label: t("assets.action.usage.title"), icon: Gauge, onSelect: () => act("usage") });
      entries.push(
        current.asset.status === "suspended"
          ? { label: t("assets.action.resume.title"), icon: CirclePlay, onSelect: () => act("resume") }
          : { label: t("assets.action.suspend.title"), icon: CirclePause, onSelect: () => act("suspend") },
      );
    }
    entries.push({ type: "separator" });
    entries.push({ label: t("assets.action.dispose.title"), icon: PackageMinus, danger: true, onSelect: () => act("dispose") });
  }
  if (!current.booked) entries.push({ label: t("assets.item.delete"), icon: Trash2, danger: true, onSelect: () => void remove() });
  return entries;
});

async function remove(): Promise<void> {
  const current = asset.value;
  if (!current) return;
  const answer = await confirm({
    title: t("assets.item.deleteTitle", { name: current.name }),
    message: t("assets.item.deleteBody"),
    confirmLabel: t("assets.item.delete"),
    tone: "danger",
    onConfirm: () => assetsApi.remove(company.currentId ?? 0, current.id),
  });
  if (answer) {
    toast.success(t("assets.item.deleted"));
    refresh();
    void router.push(`/c/${company.currentId}/assets/items`);
  }
}

const kpis = computed(() => {
  const values = page.value?.values;
  if (!values) return [];
  return [
    { id: "cost", label: t("assets.item.kpiCost"), value: values.cost, format: "money" as const, hint: Number(values.added) ? t("assets.item.addedHint", { amount: fmt.money(values.added, undefined, { decimals: "never" }) }) : undefined },
    { id: "accumulated", label: t("assets.item.kpiAccumulated"), value: values.accumulated, format: "money" as const },
    { id: "book", label: t("assets.item.kpiBook"), value: values.book, format: "money" as const, hint: Number(values.salvage_value) ? t("assets.item.salvageHint", { amount: fmt.money(values.salvage_value, undefined, { decimals: "never" }) }) : undefined },
    { id: "month", label: t("assets.item.kpiMonth"), value: values.monthly_now, format: "money" as const },
    {
      id: "left",
      label: t("assets.item.kpiLeft"),
      value: values.months_left,
      format: "number" as const,
      hint: values.end_month ? t("assets.item.endHint", { month: fmt.day(values.end_month, "monthYear") }) : undefined,
    },
  ];
});

const chart = computed(() => bookValueSeries(page.value?.schedule ?? []));
const years = computed(() => yearsOf(page.value?.schedule ?? []));
const openYear = ref<number | null>(null);
const shownYear = computed(() => openYear.value ?? years.value.find((group) => group.year === Number(today.value.slice(0, 4)))?.year ?? years.value[0]?.year ?? null);

const details = computed(() => {
  const current = page.value;
  if (!current) return [];
  const rows = [
    { key: "category", label: t("assets.field.category"), value: current.asset.category.name },
    { key: "method", label: t("assets.field.method"), value: t(`assets.method.${current.method}`) },
    { key: "life", label: t("assets.field.life"), value: current.life_months ? t("assets.item.lifeValue", { months: current.life_months, years: fmt.number(current.life_months / 12, 1) }) : "—" },
    { key: "purchased", label: t("assets.field.purchasedOn"), value: current.purchased_on ? fmt.day(current.purchased_on, "medium") : "—" },
    { key: "service", label: t("assets.field.inServiceOn"), value: current.asset.in_service_on ? fmt.day(current.asset.in_service_on, "medium") : t("assets.item.notInService") },
    { key: "serial", label: t("assets.field.serial"), value: current.serial || "—" },
    { key: "model", label: t("assets.field.model"), value: current.asset.model || "—" },
    { key: "supplier", label: t("assets.field.supplier"), value: current.supplier?.name || current.supplier_name || "—" },
    { key: "responsible", label: t("assets.field.responsible"), value: current.responsible?.name ?? "—" },
    { key: "books", label: t("assets.field.books"), value: current.books_depreciation ? t("assets.item.booksYes") : t("assets.item.booksNo") },
  ];
  if (current.opening_accumulated) rows.push({ key: "opening", label: t("assets.field.opening"), value: fmt.money(current.opening_accumulated, undefined, { decimals: "never" }) });
  if (current.disposed_on) {
    rows.push({ key: "disposed", label: t("assets.item.disposedOn"), value: `${fmt.day(current.disposed_on, "medium")} · ${current.disposal ? t(`assets.disposal.${current.disposal}`) : ""}` });
    if (current.disposal_amount) rows.push({ key: "sold", label: t("assets.action.dispose.amount"), value: fmt.money(current.disposal_amount, undefined, { decimals: "never" }) });
  }
  return rows;
});

const upkeep = computed(() => {
  const current = page.value;
  if (!current) return [];
  const rows: { what: UpkeepKind; day: string | null; every: number | null }[] = [
    { what: "service", day: current.next_service_on, every: current.service_months },
    { what: "verification", day: current.next_verification_on, every: current.verify_months },
    { what: "warranty", day: current.warranty_until, every: null },
    { what: "insurance", day: current.insurance_until, every: null },
  ];
  return rows.filter((row) => row.day || row.every);
});

function eventTitle(event: AssetEvent): string {
  const base = t(`assets.event.${event.kind}`);
  if (event.kind === "moved") return `${base}: ${event.from_branch?.name ?? t("assets.form.companyLevel")} → ${event.to_branch?.name ?? t("assets.form.companyLevel")}`;
  if ((event.kind === "issued" || event.kind === "returned") && event.person) return `${base}: ${event.person.name}`;
  if (event.kind === "disposed" && typeof event.details.kind === "string") return `${base}: ${t(`assets.disposal.${event.details.kind}`)}`;
  return base;
}

function eventBody(event: AssetEvent): string {
  const parts: string[] = [];
  if (event.amount && Number(event.amount)) parts.push(fmt.money(event.amount, undefined, { decimals: "never" }));
  if (event.units) parts.push(`${fmt.number(event.units, 2)} ${page.value?.unit ?? ""}`.trim());
  if (event.kind === "estimate") {
    const next = (event.details.new ?? {}) as Record<string, unknown>;
    if (next.life_months) parts.push(t("assets.event.newLife", { months: String(next.life_months) }));
    if (next.salvage_value) parts.push(t("assets.event.newSalvage", { amount: fmt.money(String(next.salvage_value), undefined, { decimals: "never" }) }));
    if (next.method && te(`assets.method.${String(next.method)}`)) parts.push(t(`assets.method.${String(next.method)}`));
  }
  if (event.kind === "disposed" && typeof event.details.result === "string") {
    const result = Number(event.details.result);
    parts.push(result >= 0 ? t("assets.event.gain", { amount: fmt.money(event.details.result, undefined, { decimals: "never" }) }) : t("assets.event.loss", { amount: fmt.money(String(-result), undefined, { decimals: "never" }) }));
  }
  if (event.kind === "repair" && event.details.improves) parts.push(t("assets.event.improves"));
  if (event.note) parts.push(event.note);
  return parts.join(" · ");
}

const timeline = computed<TimelineEvent[]>(() =>
  (page.value?.events ?? []).map((event) => ({
    key: event.id,
    at: event.kind === "created" ? event.created_at : `${event.on}T12:00:00`,
    title: eventTitle(event),
    body: eventBody(event) || undefined,
    icon: EVENT_ICONS[event.kind],
    tone: EVENT_TONES[event.kind] ?? "neutral",
    actor: event.by ? { name: event.by } : null,
  })),
);

const photos = computed(() => (page.value?.files ?? []).filter((file) => file.kind === "photo"));
const documents = computed(() => (page.value?.files ?? []).filter((file) => file.kind === "document"));
const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
async function upload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || !asset.value) return;
  uploading.value = true;
  try {
    await assetsApi.upload(company.currentId ?? 0, asset.value.id, file, file.type.startsWith("image/") ? "photo" : "document");
    toast.success(t("assets.item.uploaded"));
    refresh();
  } finally {
    uploading.value = false;
  }
}
async function removeFile(fileId: number): Promise<void> {
  await assetsApi.removeFile(company.currentId ?? 0, fileId);
  refresh();
}

const label = computed(() => {
  const current = asset.value;
  if (!current) return "";
  return `${window.location.origin}/dashboard/c/${company.currentId}/assets/items/${current.id}`;
});

function monthName(month: string): string {
  return fmt.day(month, "monthYear");
}
</script>

<template>
  <div>
    <ErrorState v-if="item.isError.value" :error="item.error.value" :retry="() => item.refetch()" />
    <template v-else>
      <PageHeader :title="asset ? `${asset.number} · ${asset.name}` : t('assets.item.title')" :back="{ name: 'assets.items' }" :back-label="t('assets.nav.items')">
        <template #actions>
          <UiButton v-if="canManage && live && !asset?.custodian" variant="secondary" :icon="HandHelping" @click="act('issue')">{{ t("assets.action.issue.title") }}</UiButton>
          <DropdownMenu v-if="menu.length" :items="menu" width="260px">
            <template #trigger>
              <UiButton variant="secondary" :icon="MoreHorizontal" :aria-label="t('assets.item.more')">{{ t("assets.item.actions") }}</UiButton>
            </template>
          </DropdownMenu>
        </template>
      </PageHeader>

      <div v-if="asset" class="mb-4 flex flex-wrap items-center gap-2">
        <StatusPill :tone="STATUS_TONES[asset.status]" :label="t(`assets.status.${asset.status}`)" />
        <UiBadge><component :is="categoryIcon(asset.icon)" :size="13" aria-hidden="true" class="mr-1 inline" />{{ asset.category.name }}</UiBadge>
        <UiBadge v-if="asset.branch">{{ asset.branch.name }}</UiBadge>
        <UiBadge v-if="asset.custodian" tone="primary">{{ t("assets.item.heldBy", { name: asset.custodian.name }) }}</UiBadge>
        <UiBadge>{{ t(`assets.condition.${asset.condition}`) }}</UiBadge>
        <UiBadge v-if="page?.purchase" tone="success">{{ t("assets.item.fromPurchase") }}</UiBadge>
      </div>

      <KpiStrip class="mb-4" :items="kpis" :loading="item.isPending.value" :columns="5" phone="grid" />

      <div v-if="item.isPending.value" class="grid gap-4">
        <SkeletonBlock height="260px" radius="12px" />
        <SkeletonBlock height="200px" radius="12px" />
      </div>

      <div v-else-if="page" class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div class="flex min-w-0 flex-col gap-4">
          <PageSection v-if="page.schedule.length" variant="card" :title="t('assets.item.chartTitle')" :description="t('assets.item.chartBody')">
            <LineChart
              :categories="chart.categories"
              :series="[
                { name: t('assets.item.posted'), data: chart.posted },
                { name: t('assets.item.planned'), data: chart.planned, dashed: true },
              ]"
              value-format="money"
              x-format="month"
              height="240px"
              legend
            />
          </PageSection>

          <PageSection v-if="years.length" variant="card" :title="t('assets.item.scheduleTitle')" :description="t('assets.item.scheduleBody')" flush>
            <ul class="divide-y divide-line" data-testid="asset-schedule">
              <li v-for="group in years" :key="group.year">
                <button type="button" class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-2/60" :aria-expanded="shownYear === group.year" @click="openYear = shownYear === group.year ? -1 : group.year">
                  <span class="w-14 font-semibold tabular-nums text-fg">{{ group.year }}</span>
                  <span class="flex-1 text-sm text-muted">{{ group.planned ? t("assets.item.yearPlanned") : t("assets.item.yearMonths", { n: group.months.length }) }}</span>
                  <span class="text-sm tabular-nums text-fg"><MoneyText :value="String(group.total)" decimals="never" /></span>
                  <span class="hidden w-36 text-right text-sm tabular-nums text-muted sm:block">{{ t("assets.item.endsAt") }} <MoneyText :value="group.closing" decimals="never" /></span>
                  <ChevronDown :size="16" class="shrink-0 text-subtle transition-transform" :class="{ 'rotate-180': shownYear === group.year }" aria-hidden="true" />
                </button>
                <div v-if="shownYear === group.year" class="overflow-x-auto px-4 pb-3">
                  <table class="w-full min-w-[520px] text-sm">
                    <thead>
                      <tr class="text-left text-xs text-muted">
                        <th class="py-1.5 font-medium">{{ t("assets.item.month") }}</th>
                        <th class="py-1.5 text-right font-medium">{{ t("assets.item.opening") }}</th>
                        <th class="py-1.5 text-right font-medium">{{ t("assets.item.amount") }}</th>
                        <th class="py-1.5 text-right font-medium">{{ t("assets.item.closing") }}</th>
                        <th class="py-1.5 pl-3 font-medium">{{ t("assets.item.state") }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in group.months" :key="row.month" class="border-t border-line/60" :class="{ 'text-muted': row.state === 'planned' }">
                        <td class="py-1.5 capitalize">{{ monthName(row.month) }}</td>
                        <td class="py-1.5 text-right tabular-nums"><MoneyText :value="row.opening" decimals="never" /></td>
                        <td class="py-1.5 text-right font-medium tabular-nums"><MoneyText :value="row.amount" decimals="never" /></td>
                        <td class="py-1.5 text-right tabular-nums"><MoneyText :value="row.closing" decimals="never" /></td>
                        <td class="py-1.5 pl-3">
                          <StatusPill size="sm" variant="plain" :tone="row.state === 'booked' ? 'success' : row.state === 'planned' ? 'neutral' : 'info'" :label="t(`assets.state.${row.state}`)" />
                          <span v-for="note in row.notes.filter((n) => te(`assets.note.${n}`))" :key="note" class="ml-1 text-xs text-muted">· {{ t(`assets.note.${note}`) }}</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </li>
            </ul>
          </PageSection>

          <PageSection variant="card" :title="t('assets.item.timeline')">
            <TimelineList :events="timeline" dense />
          </PageSection>
        </div>

        <aside class="flex min-w-0 flex-col gap-4">
          <PageSection v-if="page.tax" variant="card" :title="t('assets.item.taxTitle')" :description="t('assets.item.taxBody', { rate: page.tax.rate, group: page.tax.group })">
            <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt class="text-muted">{{ t("assets.item.taxMonthly") }}</dt>
              <dd class="text-right tabular-nums"><MoneyText :value="page.tax.monthly" decimals="never" /></dd>
              <dt class="text-muted">{{ t("assets.item.taxSoFar") }}</dt>
              <dd class="text-right tabular-nums"><MoneyText :value="page.tax.accumulated" decimals="never" /></dd>
              <dt class="text-muted">{{ t("assets.item.taxBook") }}</dt>
              <dd class="text-right tabular-nums"><MoneyText :value="page.tax.book" decimals="never" /></dd>
              <dt class="text-muted">{{ t("assets.item.taxDifference") }}</dt>
              <dd class="text-right font-semibold tabular-nums"><MoneyText :value="page.tax.difference" decimals="never" sign="always" /></dd>
            </dl>
            <p class="mt-2 text-xs text-muted">{{ t("assets.item.taxHint") }}</p>
          </PageSection>

          <PageSection v-if="upkeep.length" variant="card" :title="t('assets.item.upkeepTitle')">
            <ul class="flex flex-col gap-2.5">
              <li v-for="row in upkeep" :key="row.what" class="flex items-center gap-3">
                <span class="grid size-8 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-muted"><component :is="UPKEEP_ICONS[row.what]" :size="16" aria-hidden="true" /></span>
                <span class="min-w-0 flex-1">
                  <span class="block text-sm font-medium text-fg">{{ t(`assets.upkeep.${row.what}`) }}</span>
                  <span class="block text-xs text-muted">{{ row.every ? t("assets.item.every", { months: row.every }) : "" }}</span>
                </span>
                <StatusPill
                  v-if="row.day"
                  size="sm"
                  :tone="upkeepTone(row.day, today)"
                  :label="daysUntil(row.day, today) < 0 ? t('assets.item.overdue', { day: fmt.day(row.day, 'medium') }) : `${fmt.day(row.day, 'medium')} · ${t('assets.item.inDays', { n: daysUntil(row.day, today) })}`"
                />
              </li>
            </ul>
          </PageSection>

          <PageSection variant="card" :title="t('assets.item.detailsTitle')">
            <DescriptionList :items="details" layout="rows" :columns="1" />
            <RouterLink v-if="page.purchase && company.can('finance.view')" :to="`/c/${company.currentId}/finance/transactions?txn=${page.purchase.id}`" class="mt-2 inline-block text-sm font-medium text-primary hover:underline">
              {{ t("assets.item.purchaseLink", { day: fmt.day(page.purchase.occurred_on, "medium") }) }}
            </RouterLink>
          </PageSection>

          <PageSection v-if="page.assignments.length" variant="card" :title="t('assets.item.holders')">
            <ul class="flex flex-col gap-2">
              <li v-for="row in page.assignments" :key="row.id" class="text-sm">
                <span class="font-medium text-fg">{{ row.person.name }}</span>
                <span class="text-muted"> · {{ fmt.day(row.issued_on, "medium") }} → {{ row.returned_on ? fmt.day(row.returned_on, "medium") : t("assets.item.now") }}</span>
                <StatusPill v-if="!row.returned_on" class="ml-1" size="sm" variant="plain" :tone="row.acknowledged_at ? 'success' : 'warning'" :label="row.acknowledged_at ? t('assets.item.confirmed') : t('assets.item.notConfirmed')" />
              </li>
            </ul>
          </PageSection>

          <PageSection variant="card" :title="t('assets.item.files')">
            <div v-if="photos.length" class="mb-3 grid grid-cols-3 gap-2">
              <div v-for="photo in photos" :key="photo.id" class="group relative">
                <a :href="photo.url" target="_blank" rel="noopener"><img :src="photo.url" :alt="photo.label || asset?.name" class="aspect-square w-full rounded-[10px] object-cover" loading="lazy" /></a>
                <button v-if="canManage" type="button" class="absolute right-1 top-1 hidden rounded-full bg-surface/90 p-1 text-danger group-hover:block" :aria-label="t('assets.item.removeFile')" @click="removeFile(photo.id)"><Trash2 :size="13" /></button>
              </div>
            </div>
            <ul v-if="documents.length" class="mb-3 flex flex-col gap-1.5 text-sm">
              <li v-for="doc in documents" :key="doc.id" class="flex items-center gap-2">
                <a :href="doc.url" target="_blank" rel="noopener" class="min-w-0 flex-1 truncate font-medium text-primary hover:underline">{{ doc.label || t("assets.item.document") }}</a>
                <button v-if="canManage" type="button" class="text-subtle hover:text-danger" :aria-label="t('assets.item.removeFile')" @click="removeFile(doc.id)"><Trash2 :size="14" /></button>
              </li>
            </ul>
            <p v-if="!photos.length && !documents.length" class="mb-3 text-sm text-muted">{{ t("assets.item.noFiles") }}</p>
            <template v-if="canManage">
              <input ref="fileInput" type="file" class="sr-only" accept="image/*,application/pdf" @change="upload" />
              <UiButton size="sm" variant="secondary" :icon="ImagePlus" :loading="uploading" @click="fileInput?.click()">{{ t("assets.item.addFile") }}</UiButton>
            </template>
          </PageSection>

          <PageSection v-if="asset" variant="card" :title="t('assets.item.labelTitle')" :description="t('assets.item.labelBody')">
            <div class="flex flex-col items-center gap-2">
              <QrCode :value="label" :size="168" :label="asset.number" downloadable :filename="`${asset.number}.png`" />
              <p class="flex items-center gap-1.5 font-mono text-sm font-semibold text-fg"><Tag :size="14" aria-hidden="true" />{{ asset.number }}</p>
            </div>
          </PageSection>
        </aside>
      </div>
    </template>

    <AssetFormDialog v-if="page" v-model:open="editing" :asset="page" />
    <AssetActionDialog v-if="page" v-model:open="actionOpen" :asset="page" :kind="action" />
  </div>
</template>
