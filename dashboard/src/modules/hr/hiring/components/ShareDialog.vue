<script setup lang="ts">
/**
 * Share a vacancy: its QR code to print or show (download as PNG; applicants who scan it are
 * counted apart from the link's), and the bot link to copy, open or send in Telegram. A vacancy
 * that takes no applications says so first, with "Open it" for a draft or a paused one.
 */
import { Check, Copy, ExternalLink, Printer, Send } from "@lucide/vue";
import { computed, defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";

import InlineAlert from "@/components/InlineAlert.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { salaryText, vacancyState } from "../lib";
import type { Vacancy } from "../types";

const QrCode = defineAsyncComponent(() => import("@/components/QrCode.vue"));

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ vacancy: Vacancy | null }>();
const emit = defineEmits<{ publish: [vacancy: Vacancy] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const copied = ref(false);

const state = computed(() => (props.vacancy ? vacancyState(props.vacancy, today.value) : "draft"));
const closedNote = computed(() => (props.vacancy && !props.vacancy.accepting ? t(`hr.hiring.share.closed.${state.value}`) : null));
const shareUrl = computed(() => {
  const vacancy = props.vacancy;
  if (!vacancy?.link) return "";
  const text = `${vacancy.title} · ${company.current?.name ?? ""}`;
  return `https://t.me/share/url?url=${encodeURIComponent(vacancy.link)}&text=${encodeURIComponent(text)}`;
});
const filename = computed(() => `${props.vacancy?.title ?? "vacancy"}-qr`);
const salaryLine = computed(() => (props.vacancy ? (salaryText(props.vacancy, fmt.money, t) ?? "") : ""));

async function copy(): Promise<void> {
  const link = props.vacancy?.link;
  if (!link) return;
  try {
    await navigator.clipboard.writeText(link);
    copied.value = true;
    toast.success(t("common.copied"));
    window.setTimeout(() => (copied.value = false), 2000);
  } catch {
    // No clipboard (an old browser, or not allowed): the link is selectable right there.
    toast.info(t("hr.hiring.share.copyByHand"));
  }
}

const escape = (text: string) => text.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!);

/** An A4 poster for the pharmacy door: the company, the job, the pay, a large QR code. */
async function printPoster(): Promise<void> {
  const vacancy = props.vacancy;
  if (!vacancy?.qr_link) return;
  const QR = await import("qrcode");
  const image = await QR.toDataURL(vacancy.qr_link, { width: 1100, margin: 2, errorCorrectionLevel: "Q", color: { dark: "#201e1d", light: "#ffffff" } });
  const sheet = window.open("", "_blank");
  if (!sheet) {
    toast.info(t("hr.hiring.share.popupBlocked"));
    return;
  }
  const meta = [vacancy.branch?.name, salaryLine.value].filter(Boolean).map((part) => escape(part!)).join(" · ");
  sheet.document.write(`<!doctype html><html lang="${fmt.lang.value}"><head><meta charset="utf-8"><title>${escape(vacancy.title)}</title><style>
@page { size: A4; margin: 16mm; }
body { margin: 0; font-family: Figtree, system-ui, sans-serif; color: #201e1d; text-align: center; }
.company { margin-top: 6mm; font-size: 22px; color: #6b6359; }
.hiring { margin-top: 12mm; font-size: 18px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: #a85a27; }
h1 { margin: 4mm 0 3mm; font-size: 56px; line-height: 1.1; }
.meta { font-size: 22px; color: #6b6359; }
img { display: block; width: 118mm; height: 118mm; margin: 12mm auto 6mm; }
.scan { font-size: 26px; font-weight: 600; }
.link { margin-top: 4mm; font-size: 13px; color: #8c857a; word-break: break-all; }
</style></head><body>
<div class="company">${escape(company.current?.name ?? "")}</div>
<div class="hiring">${escape(t("hr.hiring.poster.hiring"))}</div>
<h1>${escape(vacancy.title)}</h1>
<div class="meta">${meta}</div>
<img src="${image}" alt="">
<div class="scan">${escape(t("hr.hiring.poster.scan"))}</div>
<div class="link">${escape(vacancy.qr_link)}</div>
</body></html>`);
  sheet.document.close();
  sheet.focus();
  window.setTimeout(() => sheet.print(), 300);
}
</script>

<template>
  <UiDialog v-model:open="open" size="lg" :title="t('hr.hiring.share.title')" :description="vacancy ? t('hr.hiring.share.description', { title: vacancy.title }) : undefined">
    <div v-if="vacancy" class="flex flex-col gap-4" data-share>
      <InlineAlert v-if="!vacancy.link" tone="warning" :title="t('hr.hiring.share.noBot')" :description="t('hr.hiring.share.noBotBody')" />
      <template v-else>
        <InlineAlert v-if="closedNote" tone="info" :description="closedNote" data-share-closed>
          <template v-if="vacancy.status === 'draft' || vacancy.status === 'paused'" #actions>
            <UiButton size="sm" variant="primary" @click="emit('publish', vacancy)">{{ t("hr.hiring.action.open") }}</UiButton>
          </template>
        </InlineAlert>
        <div class="grid grid-cols-1 items-center gap-5 sm:grid-cols-[auto_minmax(0,1fr)]">
          <div class="flex justify-center">
            <QrCode :value="vacancy.qr_link" :size="196" level="Q" downloadable :filename="filename" :label="t('hr.hiring.share.scan')" />
          </div>
          <div class="flex min-w-0 flex-col gap-3">
            <div>
              <p class="mb-1.5 text-sm font-semibold text-fg">{{ t("hr.hiring.share.link") }}</p>
              <div class="flex items-center gap-2 rounded-[10px] border border-line bg-surface-2/60 py-1 pl-3 pr-1 dark:bg-surface-2">
                <span class="min-w-0 flex-1 select-all truncate font-mono text-sm text-fg" data-share-link :title="vacancy.link">{{ vacancy.link }}</span>
                <UiButton size="sm" :variant="copied ? 'secondary' : 'primary'" :icon="copied ? Check : Copy" data-share-copy @click="copy">{{ copied ? t("common.copied") : t("common.copy") }}</UiButton>
              </div>
            </div>
            <div class="flex flex-wrap gap-2">
              <UiButton size="sm" :icon="Send" :href="shareUrl" target="_blank">{{ t("hr.hiring.share.telegram") }}</UiButton>
              <UiButton size="sm" variant="ghost" :icon="ExternalLink" :href="vacancy.link" target="_blank">{{ t("hr.hiring.share.openBot") }}</UiButton>
              <UiButton size="sm" variant="ghost" :icon="Printer" class="max-sm:hidden" data-poster @click="printPoster">{{ t("hr.hiring.share.print") }}</UiButton>
            </div>
            <ul class="flex flex-col gap-1.5 rounded-[10px] bg-surface-2/60 p-3 text-sm text-muted dark:bg-surface-2">
              <li>{{ t("hr.hiring.share.tipPoster") }}</li>
              <li>{{ t("hr.hiring.share.tipCount", { n: vacancy.link_opens }, vacancy.link_opens) }}</li>
            </ul>
          </div>
        </div>
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.close") }}</UiButton>
    </template>
  </UiDialog>
</template>
