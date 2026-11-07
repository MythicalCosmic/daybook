<script setup lang="ts">
/**
 * One transfer in a side panel (`?transfer=<id>`): its lines with series and expiry, what was sent
 * and what arrived. A draft is sent; on the way it is received, as sent or with the quantities that
 * actually arrived (less than sent makes it disputed and tells both heads); a dispute is resolved
 * as lost on the way (written off as a shortage), found at the receiving pharmacy, or back at the
 * sending one.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { isApiError } from "@/api/http";
import DescriptionList from "@/components/DescriptionList.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh, useTransfer } from "../api";
import { num, packsAndParts, TRANSFER_TONES } from "../lib";
import type { Resolution } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const route = useRoute();
const refresh = useRefresh();
const confirm = useConfirm();

const id = computed(() => Number(route.query.transfer ?? 0) || null);
const query = useTransfer(id);
const transfer = computed(() => query.data.value?.transfer ?? null);
const lines = computed(() => query.data.value?.lines ?? []);
const canManage = computed(() => company.can("stock.manage"));
const canReceive = computed(() => company.can(["stock.manage", "stock.operate"]));

const receiving = ref(false);
const received = reactive<Record<number, number | null>>({});
const resolveOutcome = ref<Resolution | null>(null);
const resolveNote = ref("");
const busy = ref(false);
watch(id, () => {
  receiving.value = false;
  resolveOutcome.value = null;
  resolveNote.value = "";
});

const facts = computed(() => {
  const row = transfer.value;
  if (!row) return [];
  return [
    { key: "from", label: t("stock.transfer.from"), value: row.from_branch.name },
    { key: "to", label: t("stock.transfer.to"), value: row.to_branch.name },
    { key: "sent", label: t("stock.transfer.sentAt"), value: row.sent_at ? `${fmt.instant(row.sent_at, "short")}${row.sent_by ? ` · ${row.sent_by.name}` : ""}` : "—" },
    { key: "received", label: t("stock.transfer.receivedAt"), value: row.received_at ? `${fmt.instant(row.received_at, "short")}${row.received_by ? ` · ${row.received_by.name}` : ""}` : "—" },
    ...(row.resolution ? [{ key: "resolution", label: t("stock.transfer.resolution"), value: t(`stock.resolution.${row.resolution}`) }] : []),
  ];
});
const outcomeOptions = computed(() => (["shortage", "found", "returned"] as const).map((value) => ({ value, label: t(`stock.resolution.${value}`) })));

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
const send = () => run(() => stockApi.sendTransfer(cid(), id.value!), t("stock.transfer.sentToast", { number: transfer.value?.number ?? "" }));
const receiveAll = () => run(() => stockApi.receiveTransfer(cid(), id.value!), t("stock.transfer.receivedToast"));

function startPartial(): void {
  for (const line of lines.value) received[line.id] = num(line.quantity_sent);
  receiving.value = true;
}
async function receivePartial(): Promise<void> {
  const rows = lines.value.map((line) => ({ line: line.id, quantity: String(received[line.id] ?? 0) }));
  await run(() => stockApi.receiveTransfer(cid(), id.value!, rows), t("stock.transfer.receivedToast"));
  receiving.value = false;
}
async function resolve(): Promise<void> {
  if (!resolveOutcome.value) return;
  await run(() => stockApi.resolveTransfer(cid(), id.value!, resolveOutcome.value!, resolveNote.value.trim()), t("stock.transfer.resolvedToast"));
}
async function voidIt(): Promise<void> {
  await confirm({
    title: t("stock.transfer.voidTitle"),
    message: transfer.value?.status === "sent" ? t("stock.transfer.voidSent") : t("stock.transfer.voidDraft"),
    tone: "danger",
    reason: "required",
    confirmLabel: t("stock.transfer.void"),
    onConfirm: async (reason) => {
      await stockApi.voidTransfer(cid(), id.value!, reason);
      toast.success(t("stock.transfer.voidedToast"));
      refresh();
    },
  });
}
</script>

<template>
  <UiDrawer query-key="transfer" :title="transfer ? transfer.number || t('stock.transfer.draft') : t('stock.transfer.title')" size="md">
    <div v-if="query.isPending.value" class="flex flex-col gap-3"><SkeletonBlock class="h-20" /><SkeletonBlock class="h-32" /></div>
    <div v-else-if="transfer" class="flex flex-col gap-4" data-testid="transfer-drawer">
      <div class="flex items-center gap-2">
        <StatusPill :tone="TRANSFER_TONES[transfer.status]" :label="t(`stock.transferStatus.${transfer.status}`)" />
      </div>
      <DescriptionList :items="facts" layout="rows" />
      <InlineAlert v-if="transfer.status === 'disputed'" tone="danger" size="sm">{{ t("stock.transfer.disputedNote") }}</InlineAlert>

      <ul class="divide-y divide-line rounded-[12px] border border-line">
        <li v-for="line in lines" :key="line.id" class="flex flex-col gap-1 px-3 py-2.5 text-sm">
          <span class="font-medium text-fg">{{ line.product.name }}</span>
          <span class="flex flex-wrap gap-x-4 text-xs text-muted">
            <span v-if="line.series">{{ t("stock.batch.series", { series: line.series }) }}<template v-if="line.expires_on"> · {{ t("stock.batch.until", { day: fmt.day(line.expires_on) }) }}</template></span>
            <span v-else>{{ t("stock.transfer.fefo") }}</span>
            <span>{{ t("stock.transfer.sentQty", { qty: packsAndParts(line.quantity_sent, line.units_per_pack, "", t) }) }}</span>
            <span v-if="line.quantity_received !== null" :class="num(line.quantity_received) < num(line.quantity_sent) ? 'font-medium text-danger' : ''">
              {{ t("stock.transfer.receivedQty", { qty: packsAndParts(line.quantity_received, line.units_per_pack, "", t) }) }}
            </span>
          </span>
          <div v-if="receiving" class="mt-1 flex items-center gap-2">
            <span class="text-xs text-muted">{{ t("stock.transfer.arrivedParts") }}</span>
            <NumberInput v-model="received[line.id]" :min="0" :max="num(line.quantity_sent)" size="sm" class="w-28" />
          </div>
        </li>
      </ul>
      <p v-if="transfer.note" class="whitespace-pre-line text-sm text-muted">{{ transfer.note }}</p>
      <InlineAlert v-if="transfer.status === 'void'" tone="neutral" size="sm">{{ t("stock.transfer.voidNote", { reason: transfer.void_reason }) }}</InlineAlert>

      <section v-if="transfer.status === 'disputed' && canManage" class="flex flex-col gap-2 rounded-[12px] border border-line p-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("stock.transfer.resolveTitle") }}</h3>
        <FormField :label="t('stock.transfer.outcome')">
          <SelectBox v-model="resolveOutcome" :options="outcomeOptions" clearable :placeholder="t('stock.transfer.pickOutcome')" />
        </FormField>
        <FormField :label="t('stock.field.note')" optional>
          <TextArea v-model="resolveNote" :rows="2" :maxlength="1000" />
        </FormField>
        <div><UiButton variant="primary" size="sm" :disabled="!resolveOutcome" :loading="busy" @click="resolve">{{ t("stock.transfer.resolve") }}</UiButton></div>
      </section>
    </div>
    <template v-if="transfer" #footer>
      <template v-if="receiving">
        <UiButton variant="ghost" @click="receiving = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" @click="receivePartial">{{ t("stock.transfer.confirmReceived") }}</UiButton>
      </template>
      <template v-else>
        <UiButton v-if="(transfer.status === 'draft' || transfer.status === 'sent') && canManage" variant="ghost" @click="voidIt">{{ t("stock.transfer.void") }}</UiButton>
        <UiButton v-if="transfer.status === 'draft' && canManage" variant="primary" :loading="busy" @click="send">{{ t("stock.transfer.send") }}</UiButton>
        <template v-if="transfer.status === 'sent' && canReceive">
          <UiButton variant="secondary" @click="startPartial">{{ t("stock.transfer.receiveDiff") }}</UiButton>
          <UiButton variant="primary" :loading="busy" data-testid="transfer-receive" @click="receiveAll">{{ t("stock.transfer.receiveAll") }}</UiButton>
        </template>
      </template>
    </template>
  </UiDrawer>
</template>
