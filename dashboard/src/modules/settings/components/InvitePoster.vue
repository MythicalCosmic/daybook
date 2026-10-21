<script setup lang="ts">
/**
 * The A4 poster for the wall at work: the company, a big QR code of the invite link and three steps,
 * in the company's language plus Russian (or Uzbek). Printed alone: everything else on the page is
 * hidden while it prints.
 */
import { computed, defineAsyncComponent } from "vue";
import { useI18n } from "vue-i18n";

import CompanyLogo from "@/components/CompanyLogo.vue";
import type { Language } from "@/api/types";

import type { Invite } from "../types";

const QrCode = defineAsyncComponent(() => import("@/components/QrCode.vue"));

const props = defineProps<{ invite: Invite; language: Language; preview?: boolean }>();

const { t } = useI18n();
const languages = computed<Language[]>(() => [props.language, props.language === "ru" ? "uz" : "ru"]);
const say = (key: string, locale: Language) => t(key, {}, { locale });
</script>

<template>
  <div data-theme="light" :class="['invite-poster mx-auto flex aspect-[210/297] w-full flex-col items-center bg-surface text-center text-fg', preview ? 'max-w-[420px] rounded-[10px] p-[6%] shadow-drawer' : 'p-[8%]']">
    <CompanyLogo :name="invite.company.name" :src="invite.company.logo" :size="preview ? 52 : 96" />
    <p :class="['mt-[3%] font-semibold leading-tight', preview ? 'text-[20px]' : 'text-[40px]']">{{ invite.company.name }}</p>
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
    <div class="mt-[5%]">
      <QrCode :value="invite.link" :size="preview ? 150 : 360" level="Q" />
    </div>
    <ol :class="['mt-[5%] grid w-full gap-[3%] text-left', preview ? 'text-[10px]' : 'text-[20px]']">
      <li v-for="step in [1, 2, 3]" :key="step" class="flex gap-[3%]">
        <span :class="['grid shrink-0 place-items-center rounded-full bg-primary font-bold text-on-primary', preview ? 'size-5 text-[10px]' : 'size-11 text-[22px]']">{{ step }}</span>
        <span class="min-w-0">
          <span class="block font-semibold">{{ say(`settings.invite.poster.step${step}`, languages[0]!) }}</span>
          <span class="block opacity-65">{{ say(`settings.invite.poster.step${step}`, languages[1]!) }}</span>
        </span>
      </li>
    </ol>
    <p v-if="invite.bot_username" :class="['mt-auto pt-[3%] font-mono opacity-60', preview ? 'text-[9px]' : 'text-[18px]']">t.me/{{ invite.bot_username }}</p>
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
