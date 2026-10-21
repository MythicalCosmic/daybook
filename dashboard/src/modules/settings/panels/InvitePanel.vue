<script setup lang="ts">
/**
 * Settings › Invite staff (plan §1.4, §4.4): the employee bot's invite link as a big QR code,
 * copy and share, a printable poster for the wall at work, and "Make a new link" (the old link and
 * printed posters stop working). People who use it appear in join requests.
 */
import { Check, Copy, Link2, Printer, RefreshCw, Send, ShieldAlert, UserCheck, UserPlus, Users } from "@lucide/vue";
import { computed, defineAsyncComponent, nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { useInvite, useRegenerateInvite, useSettings } from "../api";
import InvitePoster from "../components/InvitePoster.vue";
import PanelHeader from "../components/PanelHeader.vue";

const QrCode = defineAsyncComponent(() => import("@/components/QrCode.vue"));

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const invite = useInvite();
const settings = useSettings();
const regenerate = useRegenerateInvite();
const confirm = useConfirm();
const showSkeleton = useDelayedPending(() => invite.isPending.value);

const copied = ref(false);
const posterOpen = ref(false);
const printing = ref(false);

const language = computed(() => settings.data.value?.default_language ?? "uz");
const shareUrl = computed(() => {
  const data = invite.data.value;
  if (!data?.link) return "";
  const text = t("settings.invite.shareText", { company: data.company.name });
  return `https://t.me/share/url?url=${encodeURIComponent(data.link)}&text=${encodeURIComponent(text)}`;
});
const requestsPath = computed(() => {
  const path = `/c/${company.currentId}/people/requests`;
  return router.resolve(path).name !== "company-not-found" ? path : null;
});

async function copy(): Promise<void> {
  const link = invite.data.value?.link;
  if (!link) return;
  try {
    await navigator.clipboard.writeText(link);
    copied.value = true;
    toast.success(t("settings.invite.copied"));
    setTimeout(() => (copied.value = false), 1800);
  } catch {
    toast.error(t("settings.invite.copyFailed"));
  }
}

async function renew(): Promise<void> {
  const answer = await confirm({
    title: t("settings.invite.renewTitle"),
    message: t("settings.invite.renewBody"),
    confirmLabel: t("settings.invite.renew"),
    tone: "danger",
    icon: ShieldAlert,
  });
  if (!answer) return;
  await regenerate.mutateAsync();
  toast.success(t("settings.invite.renewed"));
}

async function print(): Promise<void> {
  printing.value = true;
  document.body.classList.add("printing-poster");
  await nextTick();
  // QR codes are drawn asynchronously; give the poster a moment to finish.
  setTimeout(() => {
    window.print();
    document.body.classList.remove("printing-poster");
    printing.value = false;
  }, 400);
}
</script>

<template>
  <div>
    <PanelHeader :title="t('settings.panel.invite')" :description="t('settings.invite.description')" />

    <ErrorState v-if="invite.isError.value" :error="invite.error.value" :retry="() => invite.refetch()" :retrying="invite.isFetching.value" />

    <div v-else-if="showSkeleton || !invite.data.value" class="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_300px]" aria-busy="true">
      <div class="ui-card flex flex-col items-center gap-4 p-6"><SkeletonBlock width="224px" height="224px" radius="14px" /><SkeletonBlock width="70%" height="36px" /></div>
      <div class="ui-card flex flex-col gap-3 p-5"><SkeletonBlock :lines="5" /></div>
    </div>

    <EmptyState v-else-if="!invite.data.value.link" :title="t('settings.invite.noBotTitle')" :description="t('settings.invite.noBotBody')" :icon="Link2" tone="neutral" />

    <div v-else class="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
      <!-- The link -->
      <section class="ui-card flex flex-col items-center p-6 text-center md:p-8">
        <QrCode :value="invite.data.value.link" :size="208" level="Q" downloadable :filename="`invite-${invite.data.value.company.name}`" />
        <p class="mt-5 text-md font-semibold text-fg">{{ t("settings.invite.scanTitle") }}</p>
        <p class="mt-1 max-w-[380px] text-sm text-muted">{{ t("settings.invite.scanBody") }}</p>

        <div class="mt-5 flex w-full max-w-[520px] items-center gap-2 rounded-[10px] border border-line bg-surface-2 p-1.5 pl-3">
          <Link2 :size="15" class="shrink-0 text-subtle" />
          <span class="min-w-0 flex-1 truncate text-left font-mono text-sm text-fg" :title="invite.data.value.link">{{ invite.data.value.link }}</span>
          <UiButton size="sm" :variant="copied ? 'soft' : 'secondary'" :icon="copied ? Check : Copy" @click="copy">{{ copied ? t("common.copied") : t("common.copy") }}</UiButton>
        </div>

        <div class="mt-4 flex flex-wrap justify-center gap-2">
          <UiButton variant="primary" :icon="Send" :href="shareUrl" target="_blank">{{ t("settings.invite.share") }}</UiButton>
          <UiButton :icon="Printer" @click="posterOpen = true">{{ t("settings.invite.poster.open") }}</UiButton>
          <UiButton variant="ghost" :icon="RefreshCw" :loading="regenerate.isPending.value" @click="renew">{{ t("settings.invite.renew") }}</UiButton>
        </div>
      </section>

      <!-- How it works and who joined -->
      <aside class="flex flex-col gap-4">
        <div class="ui-card p-5">
          <p class="text-base font-semibold text-fg">{{ t("settings.invite.howTitle") }}</p>
          <ol class="mt-3 flex flex-col gap-3">
            <li v-for="step in [1, 2, 3]" :key="step" class="flex gap-3 text-sm text-muted">
              <span class="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-fg">{{ step }}</span>
              <span class="pt-0.5">{{ t(`settings.invite.how${step}`) }}</span>
            </li>
          </ol>
        </div>
        <div class="ui-card grid grid-cols-2 divide-x divide-line">
          <div class="flex flex-col gap-1 p-4">
            <span class="inline-flex items-center gap-1.5 text-xs font-medium text-muted"><Users :size="13" />{{ t("settings.invite.team") }}</span>
            <span class="text-xl font-semibold tabular-nums text-fg">{{ invite.data.value.members.approved }}</span>
          </div>
          <div class="flex flex-col gap-1 p-4">
            <span class="inline-flex items-center gap-1.5 text-xs font-medium text-muted"><UserPlus :size="13" />{{ t("settings.invite.waiting") }}</span>
            <span :class="['text-xl font-semibold tabular-nums', invite.data.value.members.pending ? 'text-primary' : 'text-fg']">{{ invite.data.value.members.pending }}</span>
          </div>
        </div>
        <UiButton v-if="requestsPath && invite.data.value.members.pending" :to="requestsPath" variant="soft" block :icon="UserCheck">{{ t("settings.invite.review") }}</UiButton>
        <InlineAlert tone="neutral" size="sm" :description="t('settings.invite.safety')" />
      </aside>
    </div>

    <UiDialog v-model:open="posterOpen" :title="t('settings.invite.poster.dialogTitle')" :description="t('settings.invite.poster.hint')" size="lg">
      <div v-if="invite.data.value" class="flex flex-col items-center gap-4">
        <InvitePoster :invite="invite.data.value" :language="language" preview />
        <div class="flex w-full justify-end gap-2">
          <UiButton variant="ghost" @click="posterOpen = false">{{ t("common.close") }}</UiButton>
          <UiButton variant="primary" :icon="Printer" :loading="printing" @click="print">{{ t("settings.invite.poster.print") }}</UiButton>
        </div>
      </div>
    </UiDialog>

    <!-- What actually prints: the full-size poster, off screen until then. -->
    <Teleport to="body">
      <div v-if="invite.data.value?.link" class="invite-poster-print hidden" aria-hidden="true">
        <InvitePoster :invite="invite.data.value" :language="language" />
      </div>
    </Teleport>
  </div>
</template>
