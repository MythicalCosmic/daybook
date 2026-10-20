<script setup lang="ts">
/** Kitchen: dialogs, drawers, sheets, menus, previews, lightbox, toasts, alerts, banners and states. */
import { Archive, CalendarPlus, Copy, Ellipsis, Pencil, Sparkles, Trash2 } from "@lucide/vue";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import BottomSheet from "@/components/BottomSheet.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import ConnectionPill from "@/components/ConnectionPill.vue";
import DescriptionList from "@/components/DescriptionList.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import HoverCard from "@/components/HoverCard.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PdfPreview from "@/components/PdfPreview.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import QrCode from "@/components/QrCode.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiBanner from "@/components/UiBanner.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UiPopover from "@/components/UiPopover.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { ApiError } from "@/api/http";

import KitchenSection from "./KitchenSection.vue";
import KitchenSpecimen from "./KitchenSpecimen.vue";
import { PEOPLE, photo } from "./kitchenData";

const { t } = useI18n();
const k = (key: string, params?: Record<string, unknown>) => t(`dev.kitchen.${key}`, params ?? {});
const confirm = useConfirm();

const dialog = ref(false);
const confirming = ref(false);
const drawer = ref(false);
const sheet = ref(false);
const lightbox = ref(false);
const lightboxIndex = ref(0);
const decided = ref<"approved" | "rejected" | null>(null);
const lastAnswer = ref("");

const photos = [
  { src: photo("Z-report", 28, 1), caption: "CHL-1042 · Z-report" },
  { src: photo("Terminal", 200, 2), caption: "CHL-1042 · card terminal" },
  { src: photo("Fridge +4°C", 160, 3), caption: "Fridge temperature · 08:57" },
  { src: photo("Front shelves", 40, 4), caption: "Stock count · front shelves" },
];

const menu: MenuEntry[] = [
  { label: k("edit"), icon: Pencil, shortcut: "e", onSelect: () => toast.info(k("edit")) },
  { label: k("duplicate"), icon: Copy, onSelect: () => toast.info(k("duplicate")) },
  { label: k("schedule"), icon: CalendarPlus, description: k("scheduleHint"), onSelect: () => undefined },
  { type: "separator" },
  { label: k("archive"), icon: Archive, onSelect: () => undefined },
  { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => undefined },
];

async function askReason(): Promise<void> {
  const answer = await confirm({ title: k("voidTitle"), message: k("voidBody"), tone: "danger", reason: "required", confirmLabel: k("void") });
  lastAnswer.value = answer ? answer.reason : k("cancelled");
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
</script>

<template>
  <KitchenSection id="overlays" :title="k('section.overlays')" :description="k('section.overlaysHint')">
    <KitchenSpecimen name="UiDialog.vue · ConfirmDialog.vue · useConfirm()">
      <div class="flex flex-wrap gap-2">
        <UiButton @click="dialog = true">{{ k("openDialog") }}</UiButton>
        <UiButton variant="danger" @click="confirming = true">{{ k("voidTxn") }}</UiButton>
        <UiButton variant="ghost" @click="askReason">useConfirm()</UiButton>
        <span v-if="lastAnswer" class="self-center text-sm text-muted">→ “{{ lastAnswer }}”</span>
      </div>
      <UiDialog v-model:open="dialog" :title="k('newBranch')" :description="k('newBranchHint')">
        <div class="flex flex-col gap-3">
          <TextInput :model-value="'Chilonzor-2'" />
          <InlineAlert tone="info" size="sm" :description="k('geofenceHint')" />
        </div>
        <template #footer>
          <UiButton variant="ghost" @click="dialog = false">{{ t("common.cancel") }}</UiButton>
          <UiButton variant="primary" @click="dialog = false">{{ t("common.create") }}</UiButton>
        </template>
      </UiDialog>
      <ConfirmDialog
        v-model:open="confirming"
        :title="k('voidTitle')"
        :message="k('voidBody')"
        tone="danger"
        reason="required"
        :confirm-label="k('void')"
        :on-confirm="() => sleep(700)"
      />
    </KitchenSpecimen>
    <KitchenSpecimen name="UiDrawer.vue · BottomSheet.vue · DescriptionList.vue">
      <div class="flex flex-wrap gap-2">
        <UiButton @click="drawer = true">{{ k("openDrawer") }}</UiButton>
        <UiButton @click="sheet = true">{{ k("openSheet") }}</UiButton>
      </div>
      <UiDrawer v-model:open="drawer" :title="k('txnTitle')" :description="k('txnSub')">
        <div class="flex flex-col gap-5 p-5">
          <DescriptionList
            layout="rows"
            :items="[
              { key: 'amount', label: k('amount'), value: '−450 000 so‘m' },
              { key: 'category', label: k('category'), value: 'Supplies' },
              { key: 'account', label: k('account'), value: 'Cash desk · Chilonzor' },
              { key: 'by', label: k('recordedBy'), value: 'Bekzod Mirzayev' },
              { key: 'ref', label: k('reference'), value: 'TXN-7002', copy: true, mono: true },
            ]"
          >
            <template #value-category><StatusPill tone="primary" size="sm" label="Supplies" /></template>
          </DescriptionList>
          <div class="flex gap-2">
            <ProofThumb v-for="(image, index) in photos.slice(0, 3)" :key="index" :src="image.src" :images="photos" size="lg" :label="image.caption.split(' · ')[1]" />
          </div>
        </div>
        <template #footer>
          <UiButton variant="ghost" @click="drawer = false">{{ t("common.close") }}</UiButton>
          <UiButton variant="danger" :icon="Trash2">{{ k("void") }}</UiButton>
        </template>
      </UiDrawer>
      <BottomSheet v-model:open="sheet" :title="k('sheetTitle')" :description="k('sheetHint')">
        <div class="flex flex-col gap-2">
          <UiButton block variant="primary">{{ k("recordExpense") }}</UiButton>
          <UiButton block>{{ k("recordIncome") }}</UiButton>
        </div>
      </BottomSheet>
    </KitchenSpecimen>
    <KitchenSpecimen name="DropdownMenu.vue · UiPopover.vue · UiTooltip.vue · HoverCard.vue">
      <div class="flex flex-wrap items-center gap-2">
        <DropdownMenu :items="menu" width="240px" align="start">
          <template #trigger><UiButton :icon="Ellipsis">{{ k("actionsMenu") }}</UiButton></template>
        </DropdownMenu>
        <UiPopover width="260px">
          <template #trigger><UiButton>{{ k("popover") }}</UiButton></template>
          <p class="text-sm font-semibold text-fg">{{ k("popoverTitle") }}</p>
          <p class="mt-1 text-sm text-muted">{{ k("popoverBody") }}</p>
        </UiPopover>
        <UiTooltip :content="k('tooltip')" shortcut="mod+j">
          <UiButton variant="soft" :icon="Sparkles">{{ k("hoverMe") }}</UiButton>
        </UiTooltip>
        <HoverCard
          :person="{
            name: PEOPLE[3]!.name,
            subtitle: PEOPLE[3]!.subtitle,
            phone: '998901234567',
            branch: 'Chilonzor',
            status: { tone: 'success', label: k('inSince', { time: '08:57' }), live: true },
            stats: [
              { label: k('onTime'), value: '96%' },
              { label: k('tasks'), value: '7/8' },
              { label: k('streak'), value: '12 d' },
            ],
          }"
          to="/dev/login"
        >
          <a href="#" class="text-sm font-semibold text-primary underline-offset-2 hover:underline" @click.prevent>{{ PEOPLE[3]!.name }}</a>
        </HoverCard>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="ProofThumb.vue · ImageLightbox.vue · QrCode.vue">
      <div class="flex flex-wrap items-end gap-3">
        <ProofThumb v-for="(image, index) in photos" :key="index" :src="image.src" :images="photos" size="md" :label="['22:07', '22:08', '08:57', '09:12'][index]" />
        <ProofThumb src="/missing.jpg" size="md" />
        <UiButton
          variant="ghost"
          @click="
            lightboxIndex = 0;
            lightbox = true;
          "
          >{{ k("openLightbox") }}</UiButton
        >
        <ImageLightbox v-model:open="lightbox" v-model:index="lightboxIndex" :images="photos" />
      </div>
      <div class="mt-4 flex flex-wrap items-start gap-6">
        <QrCode value="https://t.me/owner_taskmanagment_bot?start=login_7Hq2xZ" :size="132" :label="k('qrLabel')" downloadable filename="sign-in" />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="PdfPreview.vue" :note="k('pdfNote')">
      <PdfPreview :src="null" loading :title="k('contractTitle')" height="260px" />
    </KitchenSpecimen>
  </KitchenSection>

  <KitchenSection id="feedback" :title="k('section.feedback')" :description="k('section.feedbackHint')">
    <KitchenSpecimen name="InlineAlert.vue">
      <div class="flex flex-col gap-2.5">
        <InlineAlert tone="info" :title="k('alertInfoTitle')" :description="k('alertInfoBody')" />
        <InlineAlert tone="warning" :title="k('alertWarnTitle')" dismissible>
          {{ k("alertWarnBody") }}
          <template #actions><UiButton size="sm">{{ k("review") }}</UiButton></template>
        </InlineAlert>
        <InlineAlert tone="danger" :title="k('alertDangerTitle')" :description="k('alertDangerBody')" />
        <InlineAlert tone="success" size="sm" :description="k('alertSuccess')" />
        <InlineAlert tone="neutral" size="sm" :description="k('alertNeutral')" />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="UiBanner.vue · ConnectionPill.vue · toasts">
      <div class="flex flex-col gap-2.5">
        <UiBanner tone="brand" :title="k('bannerAiTitle')" :message="k('bannerAiBody')" dismissible>
          <template #actions><UiButton size="sm" variant="primary">{{ k("turnOn") }}</UiButton></template>
        </UiBanner>
        <UiBanner tone="warning" :title="k('bannerLockTitle')" :message="k('bannerLockBody')" />
        <UiBanner tone="danger" :message="k('bannerDanger')" />
        <div class="flex flex-wrap items-center gap-2 pt-1">
          <ConnectionPill state="reconnecting" />
          <ConnectionPill state="offline" />
          <UiButton size="sm" @click="toast.success(k('toastSaved'))">{{ k("toastSuccess") }}</UiButton>
          <UiButton size="sm" @click="toast.info(k('toastDone'), { action: { label: t('common.undo'), onClick: () => undefined } })">{{ k("toastUndo") }}</UiButton>
          <UiButton size="sm" @click="toast.error(k('toastError'), { description: k('toastErrorBody') })">{{ k("toastFail") }}</UiButton>
        </div>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="EmptyState.vue · ErrorState.vue · SkeletonBlock.vue">
      <div class="grid gap-4 sm:grid-cols-2">
        <div class="rounded-[10px] border border-dashed border-line-strong">
          <EmptyState size="sm" :title="k('emptyTitle')" :description="k('emptyBody')"><UiButton size="sm" variant="primary">{{ k("newTask") }}</UiButton></EmptyState>
        </div>
        <div class="flex flex-col gap-3">
          <ErrorState compact :error="new ApiError(0, null)" :retry="() => undefined" />
          <ErrorState compact :error="new ApiError(403, null)" />
          <div class="flex gap-3 rounded-[10px] border border-line p-3">
            <SkeletonBlock circle height="32px" />
            <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="70%" /><SkeletonBlock :lines="2" height="10px" /></div>
          </div>
        </div>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="ApproveRejectButtons.vue · ExportButton.vue">
      <div class="flex flex-col gap-4">
        <div class="flex items-center justify-between gap-3 rounded-[10px] border border-line p-3">
          <div class="min-w-0">
            <p class="truncate text-base font-semibold text-fg">Madina Saidova · 24–26 Oct</p>
            <p class="truncate text-sm text-muted">{{ k("leaveReason") }}</p>
          </div>
          <ApproveRejectButtons :result="decided" :on-approve="() => sleep(600).then(() => (decided = 'approved'))" :on-reject="() => sleep(600).then(() => (decided = 'rejected'))" />
        </div>
        <div class="flex items-center justify-between gap-3 rounded-[10px] border border-line p-3">
          <p class="truncate text-sm text-muted">{{ k("compactApprovals") }}</p>
          <ApproveRejectButtons compact />
        </div>
        <div class="flex flex-wrap gap-2">
          <ExportButton kind="payroll.run" :params="{ run: 12 }" sensitive />
          <UiButton v-if="decided" size="sm" variant="ghost" @click="decided = null">{{ t("common.reset") }}</UiButton>
        </div>
      </div>
    </KitchenSpecimen>
  </KitchenSection>
</template>
