<script setup lang="ts">
/**
 * The A4 poster for the wall at work: the company, a big QR code of a link and three steps, in the
 * company's language plus Russian (or Uzbek). The main invite link's poster says the manager
 * approves; a team link that adds people straight away says they are on the team at once, and
 * names its branch. Printed alone: everything else on the page is hidden while it prints.
 */
import { MapPin } from "@lucide/vue";
import { computed, defineAsyncComponent } from "vue";
import { useI18n } from "vue-i18n";

import CompanyLogo from "@/components/CompanyLogo.vue";
import type { Language } from "@/api/types";

import type { PosterTarget } from "../types";

const QrCode = defineAsyncComponent(() => import("@/components/QrCode.vue"));

const props = defineProps<{ target: PosterTarget; language: Language; preview?: boolean }>();

const { t } = useI18n();
const languages = computed<Language[]>(() => [props.language, props.language === "ru" ? "uz" : "ru"]);
const say = (key: string, locale: Language) => t(key, {}, { locale });
const stepKey = (step: number) => (step === 3 && props.target.autoApprove ? "settings.invite.poster.step3Auto" : `settings.invite.poster.step${step}`);
</script>

<template>
  <div data-theme="light" :class="['invite-poster mx-auto flex aspect-[210/297] w-full flex-col items-center bg-surface text-center text-fg', preview ? 'max-w-[420px] rounded-[10px] p-[6%] shadow-drawer' : 'p-[8%]']">
    <CompanyLogo :name="target.company.name" :src="target.company.logo" :size="preview ? 52 : 96" />
    <p :class="['mt-[3%] font-semibold leading-tight', preview ? 'text-[20px]' : 'text-[40px]']">{{ target.company.name }}</p>
    <p v-if="target.branch" :class="['mt-[1%] inline-flex items-center gap-[0.3em] font-medium opacity-70', preview ? 'text-[12px]' : 'text-[24px]']">
      <MapPin :size="preview ? 12 : 24" aria-hidden="true" />{{ target.branch }}
    </p>
    <div class="mt-[4%] flex flex-col gap-[1%]">
      <p
        v-for="(lang, index) in languages"
        :key="lang"
        :lang="lang"
        :class="[
          'leading-tight',
          lang === 'ru' ? 'font-sans font-bold tracking-[-0.02em]' : 'font-display',
          index === 0 ? (preview ? 'text-[24px]' : 'text-[56px]') : preview ? 'text-[15px] opacity-70' : 'text-[32px] opacity-70',
        ]"
      >
        {{ say("settings.invite.poster.title", lang) }}
      </p>
    </div>
    <div :class="target.branch ? 'mt-[4%]' : 'mt-[5%]'">
      <QrCode :value="target.link" :size="preview ? 150 : 360" level="Q" />
    </div>
    <ol :class="['mt-[5%] grid w-full gap-[3%] text-left', preview ? 'text-[10px]' : 'text-[20px]']">
      <li v-for="step in [1, 2, 3]" :key="step" class="flex gap-[3%]">
        <span :class="['grid shrink-0 place-items-center rounded-full bg-primary font-bold text-on-primary', preview ? 'size-5 text-[10px]' : 'size-11 text-[22px]']">{{ step }}</span>
        <span class="min-w-0">
          <span class="block font-semibold">{{ say(stepKey(step), languages[0]!) }}</span>
          <span class="block opacity-65">{{ say(stepKey(step), languages[1]!) }}</span>
        </span>
      </li>
    </ol>
    <p v-if="target.bot" :class="['mt-auto pt-[3%] font-mono opacity-60', preview ? 'text-[9px]' : 'text-[18px]']">t.me/{{ target.bot }}</p>
  </div>
</template>

<style>
/* While printing, only the poster is on the page (the dialog that holds it is teleported to body). */
@media print {
  @page {
    size: A4 portrait;
    margin: 0;
  }
  /* Everything else leaves the layout (not just hidden), so the poster is one page, not one
     page plus blank pages as tall as the app. */
  body.printing-poster > *:not(.invite-poster-print) {
    display: none !important;
  }
  body.printing-poster .invite-poster-print {
    display: block !important;
    width: 210mm;
    height: 297mm;
    overflow: hidden;
    break-inside: avoid;
  }
}
</style>
