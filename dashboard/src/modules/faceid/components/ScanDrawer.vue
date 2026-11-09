<script setup lang="ts">
/**
 * One scan in a drawer (`?scan=`): the snapshot large, who and where, what it did and why (the
 * flags in words), the attendance it made, and for managers the link to a Daybook person when the
 * number isn't linked yet.
 */
import { CircleAlert, Link2, UserRound } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { ACTION_TONES, actionChip, clockOf, RING_COLORS, scanName } from "../lib";
import type { Scan } from "../types";
import LinkDialog from "./LinkDialog.vue";
import Snapshot from "./Snapshot.vue";

const props = defineProps<{ scans: Scan[] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const lightbox = ref(false);
const linking = ref(false);

const canManage = computed(() => company.can("attendance.manage"));
const NOTED = ["clock_off", "delivered_late", "auto_linked", "other_branch", "missed_entry", "late_check_out", "already_in", "out_of_order", "break", "not_approved", "ignored_number", "refused"];

function find(value: string | number | null): Scan | undefined {
  return props.scans.find((scan) => String(scan.id) === String(value));
}

function facts(scan: Scan): DescriptionItem[] {
  const items: DescriptionItem[] = [
    { key: "time", label: t("faceid.scan.time"), value: `${fmt.day(scan.event_at.slice(0, 10), "weekday")} · ${clockOf(scan.event_at)}` },
    { key: "terminal", label: t("faceid.scan.terminal"), value: `${scan.device.name} · ${scan.branch.name}` },
  ];
  if (scan.employee_no) items.push({ key: "number", label: t("faceid.scan.number"), value: scan.employee_no, copy: true });
  if (scan.name_on_device) items.push({ key: "device_name", label: t("faceid.scan.nameOnDevice"), value: scan.name_on_device });
  items.push({ key: "method", label: t("faceid.scan.method"), value: t(`faceid.method.${scan.method || "face"}`) });
  if (scan.record?.check_in_at) {
    const out = scan.record.check_out_at ? ` – ${clockOf(scan.record.check_out_at)}` : "";
    items.push({ key: "record", label: t("faceid.scan.record"), value: `${clockOf(scan.record.check_in_at)}${out}` });
  }
  return items;
}
</script>

<template>
  <UiDrawer query-key="scan" size="md" :title="t('faceid.scan.title')">
    <template #default="{ value }">
      <div v-if="find(value)" class="flex flex-col gap-5 p-5">
        <template v-for="scan in [find(value)!]" :key="scan.id">
          <button type="button" class="group relative mx-auto block" :aria-label="t('faceid.feed.photo', { name: scanName(scan) })" @click="scan.photo_url && (lightbox = true)">
            <Snapshot :src="scan.photo_url" :name="scanName(scan)" :size="168" :ring="RING_COLORS[scan.action]" />
          </button>
          <div class="text-center">
            <p class="text-lg font-semibold text-fg">{{ scan.member?.name || scan.name_on_device || t("faceid.feed.unknown") }}</p>
            <p class="mt-0.5 text-sm text-muted">
              <template v-if="scan.member">{{ scan.member.position?.name || t("faceid.scan.inDaybook") }}</template>
              <template v-else-if="scan.kind === 'stranger'">{{ t("faceid.feed.strangerHint") }}</template>
              <template v-else>{{ t("faceid.feed.number", { number: scan.employee_no }) }}</template>
            </p>
            <div class="mt-3 flex flex-wrap justify-center gap-1.5">
              <StatusPill :tone="ACTION_TONES[scan.action]" :label="t(actionChip(scan).key, { d: actionChip(scan).minutes ? fmt.duration(actionChip(scan).minutes!) : '' })" />
              <StatusPill v-if="scan.flags.includes('auto_linked')" tone="info" :icon="Link2" :label="t('faceid.flag.auto_linked')" size="sm" />
            </div>
          </div>

          <DescriptionList :items="facts(scan)" :columns="2" />

          <ul v-if="scan.flags.some((flag) => NOTED.includes(flag) && flag !== 'auto_linked')" class="flex flex-col gap-2">
            <li v-for="flag in scan.flags.filter((flag) => NOTED.includes(flag) && flag !== 'auto_linked')" :key="flag" class="flex items-start gap-2 rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-fg">
              <CircleAlert :size="15" class="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
              <span>{{ t(`faceid.flagHint.${flag}`) }}</span>
            </li>
          </ul>

          <div v-if="canManage && !scan.member && scan.kind === 'person' && scan.employee_no" class="rounded-[12px] border border-line p-4">
            <p class="text-sm font-semibold text-fg">{{ t("faceid.people.whoIs", { number: scan.employee_no }) }}</p>
            <p class="mt-1 text-sm text-muted">{{ t("faceid.people.whoIsBody") }}</p>
            <UiButton class="mt-3" variant="primary" size="sm" :icon="UserRound" @click="linking = true">{{ t("faceid.people.link") }}</UiButton>
            <LinkDialog v-model:open="linking" :employee-no="scan.employee_no" :name-on-device="scan.name_on_device" :photo-url="scan.photo_url" />
          </div>

          <ImageLightbox v-if="scan.photo_url" v-model:open="lightbox" :images="[{ src: scan.photo_url, alt: scanName(scan) }]" />
        </template>
      </div>
      <p v-else class="p-5 text-sm text-muted">{{ t("faceid.scan.gone") }}</p>
    </template>
  </UiDrawer>
</template>
