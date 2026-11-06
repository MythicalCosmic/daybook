<script setup lang="ts">
/**
 * Expense claims (plan §1.6 "expense claims from staff: paid from my money or company cash I
 * hold"; §6.2 "claims inbox (receipt beside fields, … 'Paid from own money / held cash' badge)"):
 * tabs by status (waiting first), each claim with the person, the amount, the category, the day,
 * what it was for, where the money came from and the receipts (photos in the lightbox, PDFs in a
 * new tab), and the decisions the server allows the viewer: approve or reject with a reason
 * (`can_decide`; nobody decides their own) and pay back in cash (`can_pay`).
 */
import { ChevronLeft, ChevronRight, FileText, ReceiptText, Wallet } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import ImageLightbox, { type LightboxImage } from "@/components/ImageLightbox.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { usePulseCount } from "@/core/pulse";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyId } from "@/stores/company";

import { financeApi, useClaims, useRefresh } from "../api";
import ClaimPayDialog from "../components/ClaimPayDialog.vue";
import { CLAIM_TONES, colorFor, dayStyle } from "../lib";
import type { Claim, ClaimReceipt } from "../types";

const PAGE_SIZE = 20;
const TABS = ["submitted", "approved", "paid", "rejected", "all"] as const;
type ClaimTab = (typeof TABS)[number];

const { t } = useI18n();
const fmt = useFormat();
const cid = useCompanyId();
const refresh = useRefresh();
const waiting = usePulseCount("finance.claims");

const status = useRouteState<ClaimTab>("status", rs.enum(TABS, "submitted"));
const page = useRouteState("page", rs.number(1));
watch(status, () => (page.value = 1));
const query = useClaims(() => ({ status: status.value, page: page.value, page_size: PAGE_SIZE }));
const claims = computed(() => query.data.value?.results ?? []);
const total = computed(() => query.data.value?.count ?? 0);
// The server's own page size wins: the range counts what came, the arrows follow next/previous.
const first = computed(() => (page.value - 1) * PAGE_SIZE + 1);
const hasNext = computed(() => !!query.data.value?.next);
const hasPrevious = computed(() => page.value > 1);

const tabs = computed(() =>
  TABS.map((id) => ({ id, label: t(`finance.claims.tab.${id}`), ...(id === "submitted" && waiting.value ? { count: waiting.value } : {}) })),
);

// Decisions ----------------------------------------------------------------------------------

async function approve(claim: Claim): Promise<void> {
  await financeApi.approveClaim(cid.value, claim.id);
  toast.success(t("finance.claims.approvedToast", { name: claim.member.name }));
  refresh();
}
async function reject(claim: Claim, reason: string): Promise<void> {
  await financeApi.rejectClaim(cid.value, claim.id, reason);
  toast.success(t("finance.claims.rejectedToast"));
  refresh();
}

const paying = ref<Claim | null>(null);
const payOpen = ref(false);
function pay(claim: Claim): void {
  paying.value = claim;
  payOpen.value = true;
}

// Receipts -----------------------------------------------------------------------------------

const lightbox = ref<{ open: boolean; index: number; images: LightboxImage[] }>({ open: false, index: 0, images: [] });
function openReceipt(claim: Claim, receipt: ClaimReceipt): void {
  if (!receipt.is_image) {
    window.open(receipt.url, "_blank", "noopener");
    return;
  }
  const images = claim.receipts.filter((row) => row.is_image).map((row) => ({ src: row.url, thumb: row.thumb_url ?? row.url, alt: t("finance.tx.receipt"), caption: `${claim.member.name} · ${fmt.money(claim.amount, claim.currency)}` }));
  lightbox.value = { open: true, index: Math.max(0, images.findIndex((image) => image.src === receipt.url)), images };
}

function decidedLine(claim: Claim): string | null {
  if (!claim.decided_by || !claim.decided_at) return null;
  const key = claim.status === "rejected" ? "finance.claims.rejectedBy" : "finance.claims.approvedBy";
  return t(key, { name: claim.decided_by.name, date: fmt.instant(claim.decided_at, "short") });
}
function sourceLabel(claim: Claim): string {
  if (claim.paid_from === "held_cash") return t("finance.claims.from.held_cash");
  if (claim.reimburse_via === "payroll") return t("finance.claims.from.own_payroll");
  if (claim.reimburse_via === "cash") return t("finance.claims.from.own_cash");
  return t("finance.claims.from.own_money");
}
const emptyTitle = computed(() => (status.value === "submitted" ? t("finance.claims.emptyWaiting") : t("finance.claims.emptyTitle")));
</script>

<template>
  <div>
    <PageHeader v-model:tab="status" :title="t('finance.nav.claims')" :description="t('finance.claims.description')" :tabs="tabs" />

    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.isPending.value" class="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <SkeletonBlock v-for="n in 4" :key="n" height="180px" radius="12px" />
    </div>
    <div v-else-if="!claims.length" class="ui-card">
      <EmptyState :icon="ReceiptText" :tone="status === 'submitted' ? 'success' : 'primary'" :title="emptyTitle" :description="t('finance.claims.emptyBody')" />
    </div>
    <template v-else>
      <div :class="['grid grid-cols-1 gap-3 xl:grid-cols-2', query.isFetching.value && 'opacity-80 transition-opacity']">
        <article v-for="claim in claims" :key="claim.id" class="ui-card flex min-w-0 flex-col gap-3 p-4" :data-claim="claim.id">
          <header class="flex items-start gap-3">
            <UserAvatar :name="claim.member.name" :src="claim.member.photo_url" :size="36" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg" :title="claim.member.name">{{ claim.member.name }}</p>
              <p class="truncate text-xs text-muted">
                <template v-if="claim.branch">{{ claim.branch.name }} · </template>{{ t("finance.claims.sent", { date: fmt.instant(claim.created_at, "short") }) }}
              </p>
            </div>
            <div class="flex shrink-0 flex-col items-end gap-1">
              <p class="text-lg font-semibold tabular-nums text-fg"><MoneyText :value="claim.amount" :currency="claim.currency" decimals="never" /></p>
              <StatusPill :tone="CLAIM_TONES[claim.status]" size="sm" :label="claim.status_label || t(`finance.claims.status.${claim.status}`)" />
            </div>
          </header>

          <div class="flex min-w-0 gap-3">
            <ul v-if="claim.receipts.length" class="flex shrink-0 gap-1.5" :aria-label="t('finance.tx.receipts')">
              <li v-for="receipt in claim.receipts.slice(0, 3)" :key="receipt.id">
                <button
                  type="button"
                  class="block size-16 overflow-hidden rounded-[9px] border border-line bg-surface-2 transition hover:border-line-strong"
                  :aria-label="t('finance.claims.openReceipt')"
                  data-receipt
                  @click="openReceipt(claim, receipt)"
                >
                  <img v-if="receipt.is_image" :src="receipt.thumb_url ?? receipt.url" :alt="t('finance.tx.receipt')" class="size-full object-cover" loading="lazy" />
                  <span v-else class="flex size-full flex-col items-center justify-center gap-0.5 text-muted"><FileText :size="18" /><span class="text-[10px] font-semibold">PDF</span></span>
                </button>
              </li>
              <li v-if="claim.receipts.length > 3" class="grid size-16 place-items-center rounded-[9px] bg-surface-2 text-sm font-semibold text-muted">+{{ claim.receipts.length - 3 }}</li>
            </ul>
            <div class="flex min-w-0 flex-1 flex-col gap-1.5">
              <p class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <span class="inline-flex min-w-0 items-center gap-1.5 text-fg">
                  <span class="size-2 shrink-0 rounded-full" :style="{ background: colorFor(claim.category.id, claim.category.color) }" aria-hidden="true" />
                  <span class="truncate">{{ claim.category.name }}</span>
                </span>
                <span class="text-muted">· {{ t("finance.claims.spentOn", { date: fmt.day(claim.spent_on, dayStyle(claim.spent_on)) }) }}</span>
              </p>
              <p v-if="claim.description" class="line-clamp-2 text-sm text-fg" :title="claim.description">{{ claim.description }}</p>
              <p class="flex flex-wrap items-center gap-1.5">
                <StatusPill :tone="claim.paid_from === 'held_cash' ? 'neutral' : 'warning'" size="sm" variant="outline" :icon="Wallet" :label="sourceLabel(claim)" />
                <span v-if="!claim.receipts.length" class="text-xs text-subtle">{{ t("finance.claims.noReceipt") }}</span>
              </p>
            </div>
          </div>

          <p v-if="claim.status === 'rejected' && claim.reject_reason" class="rounded-[10px] bg-danger-soft/60 px-3 py-2 text-sm text-fg">{{ t("finance.claims.reason", { reason: claim.reject_reason }) }}</p>
          <p v-if="decidedLine(claim)" class="text-xs text-muted">{{ decidedLine(claim) }}</p>

          <footer v-if="claim.can_decide || claim.can_pay" class="mt-auto flex flex-wrap items-center justify-end gap-2 border-t border-line pt-3">
            <UiButton v-if="claim.can_pay" size="sm" variant="primary" :icon="Wallet" data-pay-claim-open @click="pay(claim)">{{ t("finance.claims.pay") }}</UiButton>
            <ApproveRejectButtons
              v-if="claim.can_decide"
              :on-approve="() => approve(claim)"
              :on-reject="(reason: string) => reject(claim, reason)"
              :reject-title="t('finance.claims.rejectTitle', { name: claim.member.name })"
            />
          </footer>
        </article>
      </div>

      <nav v-if="hasNext || hasPrevious" class="mt-4 flex items-center justify-end gap-2" :aria-label="t('finance.claims.pages')">
        <span class="text-sm tabular-nums text-muted">{{ t("common.table.range", { from: first, to: first + claims.length - 1, total }) }}</span>
        <IconButton :icon="ChevronLeft" :label="t('common.table.prev')" size="sm" variant="secondary" :disabled="!hasPrevious" @click="page -= 1" />
        <IconButton :icon="ChevronRight" :label="t('common.table.next')" size="sm" variant="secondary" :disabled="!hasNext" @click="page += 1" />
      </nav>
    </template>

    <ClaimPayDialog v-if="paying" v-model:open="payOpen" :claim="paying" />
    <ImageLightbox v-model:open="lightbox.open" v-model:index="lightbox.index" :images="lightbox.images" :title="t('finance.tx.receipts')" />
  </div>
</template>
