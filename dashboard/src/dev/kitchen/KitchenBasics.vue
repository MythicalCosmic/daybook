<script setup lang="ts">
/** Kitchen: tokens, type, buttons, badges, pills, avatars, keys. */
import { ArrowRight, Bell, Download, Ellipsis, Plus, Settings, Sparkles, Trash2 } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import AvatarStack from "@/components/AvatarStack.vue";
import DeltaBadge from "@/components/DeltaBadge.vue";
import IconButton from "@/components/IconButton.vue";
import KbdKey from "@/components/KbdKey.vue";
import MoneyText from "@/components/MoneyText.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiSpinner from "@/components/UiSpinner.vue";
import UserAvatar from "@/components/UserAvatar.vue";

import KitchenSection from "./KitchenSection.vue";
import KitchenSpecimen from "./KitchenSpecimen.vue";
import { PEOPLE } from "./kitchenData";

const { t } = useI18n();
const k = (key: string, params?: Record<string, unknown>) => t(`dev.kitchen.${key}`, params ?? {});

const SURFACES = ["canvas", "surface", "surface-2", "surface-3", "accent-soft"];
const INK = ["text", "muted", "subtle", "primary", "success", "warning", "danger", "info"];
const minutesAgo = (n: number) => new Date(Date.now() - n * 60_000).toISOString();
</script>

<template>
  <KitchenSection id="foundations" :title="k('section.foundations')" :description="k('section.foundationsHint')">
    <KitchenSpecimen name="tokens.css" :note="k('colors')" wide>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <div v-for="token in SURFACES" :key="token" class="overflow-hidden rounded-[10px] border border-line">
          <div class="h-12" :style="{ background: `var(--c-${token})` }" />
          <p class="px-2 py-1.5 font-mono text-[11px] text-muted">--c-{{ token }}</p>
        </div>
      </div>
      <div class="mt-3 grid grid-cols-4 gap-3 sm:grid-cols-8">
        <div v-for="token in INK" :key="token" class="flex flex-col items-center gap-1.5">
          <span class="size-9 rounded-full ring-1 ring-line" :style="{ background: `var(--c-${token})` }" />
          <span class="font-mono text-[10px] text-muted">{{ token }}</span>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap gap-1.5">
        <span v-for="n in [1, 3, 4, 5, 6, 2, 7, 8]" :key="n" class="flex items-center gap-1.5 rounded-full border border-line py-0.5 pl-1 pr-2 text-[11px] text-muted">
          <span class="size-3.5 rounded-full" :style="{ background: `var(--c-chart-${n})` }" />chart-{{ n }}
        </span>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="Figtree" :note="k('type')">
      <div class="flex flex-col gap-1.5">
        <p class="font-display text-2xl text-fg">Daybook</p>
        <p class="text-2xl font-semibold tracking-[-0.02em] text-fg">48 120 000 so‘m</p>
        <p class="text-xl font-semibold text-fg">{{ k("typeHeading") }}</p>
        <p class="text-lg font-semibold text-fg">{{ k("typeSub") }}</p>
        <p class="text-md text-fg">{{ k("typeBody") }}</p>
        <p class="text-base text-muted">{{ k("typeBase") }}</p>
        <p class="text-sm text-muted">{{ k("typeSmall") }}</p>
        <p class="text-xs text-subtle">{{ k("typeCaption") }}</p>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="Depth & radii" :note="k('depth')" canvas>
      <div class="grid grid-cols-2 gap-3">
        <div class="ui-card p-3 text-sm text-muted">ui-card · 12px</div>
        <div class="rounded-[12px] bg-surface p-3 text-sm text-muted shadow-pop">shadow-pop</div>
        <div class="rounded-drawer bg-surface p-3 text-sm text-muted shadow-drawer">shadow-drawer · 16px</div>
        <div class="rounded-input border border-line-strong bg-surface p-3 text-sm text-muted">input · 6px</div>
      </div>
    </KitchenSpecimen>
  </KitchenSection>

  <KitchenSection id="actions" :title="k('section.actions')" :description="k('section.actionsHint')">
    <KitchenSpecimen name="UiButton.vue" :note="k('variants')">
      <div class="flex flex-wrap items-center gap-2">
        <UiButton variant="primary" :icon="Plus">{{ k("newTask") }}</UiButton>
        <UiButton>{{ k("secondary") }}</UiButton>
        <UiButton variant="soft" :icon="Sparkles">{{ k("askAi") }}</UiButton>
        <UiButton variant="ghost" :icon-right="ArrowRight">{{ k("ghost") }}</UiButton>
        <UiButton variant="danger" :icon="Trash2">{{ t("common.delete") }}</UiButton>
        <UiButton variant="link">{{ k("link") }}</UiButton>
      </div>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <UiButton size="sm" variant="primary">{{ k("small") }}</UiButton>
        <UiButton size="lg" variant="primary" kbd="mod+enter">{{ t("common.save") }}</UiButton>
        <UiButton loading variant="primary">{{ t("common.save") }}</UiButton>
        <UiButton disabled :icon="Download">{{ t("common.export") }}</UiButton>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="IconButton.vue · KbdKey.vue · UiSpinner.vue">
      <div class="flex flex-wrap items-center gap-2">
        <IconButton :icon="Bell" :label="t('shell.topbar.inbox')" :badge="7" />
        <IconButton :icon="Bell" :label="t('shell.topbar.inbox')" badge />
        <IconButton :icon="Settings" :label="t('common.settings')" variant="secondary" />
        <IconButton :icon="Plus" :label="t('common.create')" variant="primary" />
        <IconButton :icon="Ellipsis" :label="t('common.more')" variant="soft" />
        <IconButton :icon="Settings" :label="t('common.settings')" loading />
        <span class="mx-2 h-6 w-px bg-line" />
        <KbdKey keys="mod+k" />
        <KbdKey :keys="['g', 't']" size="md" />
        <UiSpinner :size="18" class="text-primary" />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="StatusPill.vue · UiBadge.vue · DeltaBadge.vue">
      <div class="flex flex-wrap items-center gap-2">
        <StatusPill tone="success" :label="k('opened', { time: '08:57' })" />
        <StatusPill tone="danger" live :label="k('notOpened')" />
        <StatusPill tone="warning" :label="k('late')" />
        <StatusPill tone="info" variant="outline" :label="k('review')" />
        <StatusPill tone="neutral" size="sm" :label="k('draft')" />
      </div>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <UiBadge :count="7" tone="primary" />
        <UiBadge :count="140" tone="danger" variant="solid" />
        <UiBadge tone="success">{{ k("new") }}</UiBadge>
        <UiBadge tone="info" variant="outline" size="md">{{ k("beta") }}</UiBadge>
        <DeltaBadge :value="8.2" />
        <DeltaBadge :value="-12" />
        <DeltaBadge :value="4.5" inverse />
        <DeltaBadge :value="null" />
        <DeltaBadge :value="3.1" points variant="text" :suffix="k('vsLastMonth')" />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="UserAvatar.vue · AvatarStack.vue · PersonCell.vue">
      <div class="flex flex-wrap items-center gap-3">
        <UserAvatar :name="PEOPLE[0]!.name" :size="40" status="in" />
        <UserAvatar :name="PEOPLE[3]!.name" :size="32" status="late" />
        <UserAvatar :name="PEOPLE[4]!.name" :size="28" status="off" shape="rounded" />
        <AvatarStack :people="PEOPLE" :max="5" :size="28" />
      </div>
      <div class="mt-4 grid gap-3 sm:grid-cols-2">
        <PersonCell :person="PEOPLE[3]!" :subtitle="PEOPLE[3]!.subtitle" link preview />
        <PersonCell :person="PEOPLE[1]!" :subtitle="PEOPLE[1]!.subtitle" size="lg" status="in" />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="MoneyText.vue · RelativeTime.vue">
      <div class="flex flex-col gap-2 text-base">
        <p><MoneyText value="1250000.00" currency="UZS" /></p>
        <p><MoneyText value="48120000" compact /></p>
        <p><MoneyText value="1240.50" currency="USD" :approx="{ value: '15624000', currency: 'UZS' }" /></p>
        <p><MoneyText value="-15000.00" colored /> · <MoneyText value="450000" sign="always" colored /> · <MoneyText value="0" hidden /></p>
        <p class="text-sm text-muted"><RelativeTime :value="minutesAgo(0.2)" /> · <RelativeTime :value="minutesAgo(14)" /> · <RelativeTime :value="minutesAgo(60 * 26)" /> · <RelativeTime :value="minutesAgo(60 * 24 * 9)" /></p>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="ProgressBar.vue · ProgressRing.vue">
      <div class="flex flex-col gap-3">
        <ProgressBar :value="38" :max="52" show-value :label="k('tasksDone')" />
        <ProgressBar :value="84" tone="auto" show-value :label="k('budgetUsed')" :target="100" />
        <ProgressBar :segments="[{ value: 62, label: 'Cash' }, { value: 31, label: 'Card' }, { value: 7, label: 'Transfer' }]" size="md" :label="k('paymentMix')" />
        <ProgressBar indeterminate size="xs" />
      </div>
      <div class="mt-4 flex items-center gap-4">
        <ProgressRing :value="82" show-value :size="52" tone="success" />
        <ProgressRing :value="45" show-value :size="52" tone="auto" />
        <ProgressRing :value="12" :size="40" tone="danger" />
        <ProgressRing :value="64" :size="40"><span class="text-[10px] font-bold text-fg">7/11</span></ProgressRing>
      </div>
    </KitchenSpecimen>
  </KitchenSection>
</template>
