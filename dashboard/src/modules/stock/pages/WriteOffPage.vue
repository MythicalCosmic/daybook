<script setup lang="ts">
/**
 * One write-off: its series, expiry and quantities, the value at cost (finance.view), the photos
 * and documents, and its steps. Approval takes the goods off stock at their batches' cost (no
 * ledger row: the cost was booked as a purchase). Unfit goods then wait for destruction by a
 * commission before `destroy_by`; recording it makes the act ("Yo‘q qilish dalolatnomasi" /
 * "Акт уничтожения"), printable in Uzbek or Russian.
 */
import { Ban, Check, FileText, Flame, ImagePlus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { isApiError } from "@/api/http";
import DescriptionList from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useRefresh, useWriteoff } from "../api";
import DestroyDialog from "../components/DestroyDialog.vue";
import { daysUntil, packsAndParts, WRITEOFF_TONES } from "../lib";
import type { WriteOffFileKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const route = useRoute();
const today = useCompanyToday();
const refresh = useRefresh();
const confirm = useConfirm();

const id = computed(() => Number(route.params.writeoffId ?? 0));
const query = useWriteoff(id);
const writeoff = computed(() => query.data.value?.writeoff ?? null);
const lines = computed(() => query.data.value?.lines ?? []);
const files = computed(() => query.data.value?.files ?? []);
const photos = computed(() => files.value.filter((row) => row.kind === "photo" || row.kind === "video").length);
const canManage = computed(() => company.can("stock.manage"));
const canOperate = computed(() => company.can(["stock.manage", "stock.operate"]));
const destroying = ref(false);
const busy = ref(false);
// The act is printed in Uzbek or Russian (the reader's language when it is one of them).
const actLanguage = ref<"uz" | "ru">(fmt.lang.value === "ru" ? "ru" : "uz");

const title = computed(() => (writeoff.value?.number ? t("stock.writeoff.titleNumber", { number: writeoff.value.number }) : t("stock.writeoff.proposal", { id: id.value })));
const facts = computed(() => {
  const row = writeoff.value;
  if (!row) return [];
  return [
    { key: "reason", label: t("stock.writeoff.reason"), value: t(`stock.reason.${row.reason}`) },
    { key: "branch", label: t("stock.field.branch"), value: row.branch.name },
    { key: "proposed", label: t("stock.writeoff.proposedBy"), value: row.proposed_by ? `${row.proposed_by.name} · ${fmt.instant(row.created_at, "short")}` : fmt.instant(row.created_at, "short") },
    { key: "approved", label: t("stock.writeoff.approvedBy"), value: row.approved_by ? `${row.approved_by.name}${row.approved_at ? ` · ${fmt.instant(row.approved_at, "short")}` : ""}` : "—" },
    ...(row.destroy_by ? [{ key: "destroyBy", label: t("stock.writeoff.destroyBy"), value: fmt.day(row.destroy_by) }] : []),
    ...(row.destroyed_at
      ? [
          { key: "destroyed", label: t("stock.destroy.day"), value: fmt.instant(row.destroyed_at) },
          { key: "method", label: t("stock.destroy.method"), value: row.method ? t(`stock.method.${row.method}`) : "—" },
          { key: "place", label: t("stock.destroy.place"), value: row.place },
          { key: "responsible", label: t("stock.destroy.responsible"), value: `${row.responsible}${row.order_number ? ` · ${t("stock.writeoff.order", { number: row.order_number })}` : ""}` },
        ]
      : []),
  ];
});

async function run(action: () => Promise<unknown>, done: string): Promise<void> {
  busy.value = true;
  try {
    await action();
    toast.success(done);
    refresh();
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  } finally {
    busy.value = false;
  }
}
const cid = () => company.currentId ?? 0;
const approve = () => run(() => stockApi.approveWriteoff(cid(), id.value), t("stock.writeoff.approvedToast", { number: "" }));

async function voidIt(): Promise<void> {
  await confirm({
    title: t("stock.writeoff.voidTitle"),
    tone: "danger",
    reason: "required",
    confirmLabel: t("stock.writeoff.void"),
    onConfirm: async (reason) => {
      await stockApi.voidWriteoff(cid(), id.value, reason);
      toast.success(t("stock.writeoff.voidedToast"));
      refresh();
    },
  });
}

const fileInput = ref<HTMLInputElement | null>(null);
const uploadKind = ref<WriteOffFileKind>("photo");
function pick(kind: WriteOffFileKind): void {
  uploadKind.value = kind;
  fileInput.value?.click();
}
async function upload(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  await run(() => stockApi.uploadWriteoffFile(cid(), id.value, file, uploadKind.value), t("stock.writeoff.fileSaved"));
  if (fileInput.value) fileInput.value.value = "";
}

async function openAct(): Promise<void> {
  try {
    const link = await stockApi.act(cid(), id.value, actLanguage.value);
    window.open(link.url, "_blank", "noopener");
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  }
}
</script>

<template>
  <div>
    <ErrorState v-if="query.error.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.isPending.value" class="flex flex-col gap-3"><SkeletonBlock class="h-16" /><SkeletonBlock class="h-48" /></div>
    <template v-else-if="writeoff">
      <PageHeader :title="title" :back="`/c/${company.currentId}/stock/write-offs`">
        <template #meta><StatusPill :tone="WRITEOFF_TONES[writeoff.status]" :label="t(`stock.writeoffStatus.${writeoff.status}`)" /></template>
        <template #actions>
          <UiButton v-if="writeoff.status === 'proposed' && canManage" variant="ghost" :icon="Ban" @click="voidIt">{{ t("stock.writeoff.void") }}</UiButton>
          <UiButton v-if="writeoff.status === 'proposed' && canManage" variant="primary" :icon="Check" :loading="busy" data-testid="writeoff-approve" @click="approve">{{ t("stock.writeoff.approve") }}</UiButton>
          <UiButton v-if="writeoff.status === 'approved' && writeoff.needs_destruction && canManage" variant="primary" :icon="Flame" data-testid="writeoff-destroy" @click="destroying = true">{{ t("stock.writeoff.recordDestruction") }}</UiButton>
          <template v-if="writeoff.status === 'approved' || writeoff.status === 'destroyed'">
            <SegmentedControl
              v-model="actLanguage"
              size="sm"
              :options="[
                { value: 'uz', label: 'O‘zb' },
                { value: 'ru', label: 'Рус' },
              ]"
            />
            <UiButton variant="secondary" :icon="FileText" data-testid="writeoff-act" @click="openAct">{{ t("stock.writeoff.act") }}</UiButton>
          </template>
        </template>
      </PageHeader>

      <InlineAlert v-if="writeoff.status === 'approved' && writeoff.needs_destruction && writeoff.destroy_by" class="mb-4" :tone="daysUntil(writeoff.destroy_by, today) <= 10 ? 'danger' : 'warning'">
        {{ t("stock.writeoff.destroyNote", { day: fmt.day(writeoff.destroy_by) }) }}
      </InlineAlert>
      <InlineAlert v-if="writeoff.status === 'void'" class="mb-4" tone="neutral">{{ t("stock.writeoff.voidNote", { reason: writeoff.void_reason }) }}</InlineAlert>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <PageSection :title="t('stock.writeoff.lines')" :count="lines.length" variant="card" flush>
          <ul class="divide-y divide-line">
            <li v-for="line in lines" :key="line.id" class="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-sm">
              <span class="min-w-0 flex-1">
                <span class="block font-medium text-fg">{{ line.product.name }}</span>
                <span class="block text-xs text-muted">{{ t("stock.batch.series", { series: line.series }) }} · {{ t("stock.batch.until", { day: fmt.day(line.expires_on) }) }}</span>
              </span>
              <span class="tabular-nums text-fg">{{ packsAndParts(line.quantity, line.units_per_pack, "", t) }}</span>
              <span v-if="line.value !== undefined" class="w-32 text-end font-medium"><MoneyText :value="line.value" decimals="never" /></span>
            </li>
          </ul>
          <div v-if="writeoff.value !== undefined" class="flex items-center justify-between border-t border-line px-4 py-3 text-sm">
            <span class="text-muted">{{ t("stock.writeoff.valueAtCost") }}</span>
            <span class="font-semibold text-fg"><MoneyText :value="writeoff.value" /></span>
          </div>
        </PageSection>

        <div class="flex flex-col gap-4">
          <PageSection :title="t('stock.writeoff.facts')" variant="card">
            <DescriptionList :items="facts" layout="rows" />
            <p v-if="writeoff.note" class="mt-2 text-sm text-muted">{{ writeoff.note }}</p>
          </PageSection>
          <PageSection v-if="writeoff.commission.length" :title="t('stock.writeoff.commission')" variant="card">
            <ul class="flex flex-col gap-1 text-sm">
              <li v-for="(member, index) in writeoff.commission" :key="index">
                <span class="text-fg">{{ member.name }}</span>
                <span class="text-muted"> · {{ [member.organisation, member.role].filter(Boolean).join(", ") }}</span>
              </li>
            </ul>
          </PageSection>
          <PageSection :title="t('stock.writeoff.files')" :count="files.length" variant="card">
            <ul class="mb-2 flex flex-col gap-1 text-sm">
              <li v-for="row in files" :key="row.id">
                <a class="text-accent-fg hover:underline" :href="row.url" target="_blank" rel="noopener">{{ t(`stock.fileKind.${row.kind}`) }} · {{ fmt.instant(row.at, "short") }}</a>
              </li>
              <li v-if="!files.length" class="text-muted">{{ t("stock.writeoff.noFiles") }}</li>
            </ul>
            <template v-if="writeoff.status !== 'void' && canOperate">
              <input ref="fileInput" type="file" class="hidden" accept="image/*,.pdf" @change="upload" />
              <div class="flex flex-wrap gap-2">
                <UiButton size="sm" variant="secondary" :icon="ImagePlus" @click="pick('photo')">{{ t("stock.writeoff.addPhoto") }}</UiButton>
                <UiButton v-if="writeoff.status === 'destroyed'" size="sm" variant="secondary" :icon="FileText" @click="pick('signed_act')">{{ t("stock.writeoff.addSignedAct") }}</UiButton>
              </div>
            </template>
          </PageSection>
        </div>
      </div>

      <DestroyDialog v-model:open="destroying" :writeoff-id="writeoff.id" :commission-min="query.data.value?.commission_min ?? 5" :photos="photos" />
    </template>
  </div>
</template>
