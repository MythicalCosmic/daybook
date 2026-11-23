<script setup lang="ts">
/**
 * Ko‘z › Worth a look (docs/KOZ.md §6.9): voided sales and cash taken out of a till in a minute
 * when its camera saw nobody at the counter. Each with the amount, the cashier, the camera and its
 * video. Most have a good reason; the page says so. Day and branch in the URL. `vision.video`.
 */
import { Ban, CircleCheck, HandCoins, Play, UserRoundX } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useCameras, useReview } from "../api";
import ClipPlayer from "../components/ClipPlayer.vue";
import type { ClipRequest, ReviewItem } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const branch = useRouteState("branch", rs.optionalNumber());
const day = useRouteState("day", rs.day());
const params = computed(() => ({ branch: branch.value, day: day.value ?? today.value }));
const review = useReview(params);
const items = computed(() => review.data.value?.items ?? []);
const switching = computed(() => review.isPlaceholderData.value);

const branches = computed(() => company.current?.branches ?? []);
const cameras = useCameras(null);
const branchOf = (cameraId: number | undefined) => (cameras.data.value ?? []).find((camera) => camera.id === cameraId)?.branch.name ?? null;
const branchOptions = computed(() => [{ value: 0, label: t("vision.filter.allBranches") }, ...branches.value.map((b) => ({ value: b.id, label: b.name }))]);

const clip = ref<ClipRequest | null>(null);
const context = ref("");
const clipOpen = computed({ get: () => clip.value !== null, set: (value: boolean) => (clip.value = value ? clip.value : null) });
function video(item: ReviewItem): void {
  context.value = `${t(`vision.review.kind.${item.kind}`)} · ${fmt.money(item.amount)}`;
  clip.value = item.sale_id ? { sale_id: item.sale_id } : item.camera ? { camera_id: item.camera.id, at: item.at, before_s: 10, after_s: 5 } : null;
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('vision.review.title')" :description="t('vision.review.description')">
      <template #actions>
        <SelectBox v-if="branches.length > 1" :model-value="branch ?? 0" size="sm" class="w-48 max-sm:w-full" :options="branchOptions" :aria-label="t('vision.filter.branch')" @update:model-value="branch = $event || null" />
        <DatePicker v-model="day" size="sm" :max="today" :placeholder="t('common.today')" format="weekday" class="w-56 max-sm:w-full" />
      </template>
    </PageHeader>

    <div v-if="review.isPending.value" class="flex flex-col gap-2">
      <SkeletonBlock v-for="n in 3" :key="n" height="76px" radius="12px" />
    </div>
    <ErrorState v-else-if="review.isError.value && !review.data.value" class="ui-card" :error="review.error.value" :retry="() => review.refetch()" />
    <EmptyState v-else-if="!items.length" class="ui-card py-12" :icon="CircleCheck" tone="success" :title="t('vision.review.emptyTitle')" :description="t('vision.review.emptyBody')" />
    <template v-else>
      <p class="px-1 text-sm text-muted">{{ t("vision.review.why") }}</p>
      <ul :class="['ui-card divide-y divide-line overflow-hidden transition-opacity', switching && 'opacity-60']">
        <li v-for="item in items" :key="`${item.kind}:${item.at}`" class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5" :data-review="item.kind">
          <span :class="['grid size-10 shrink-0 place-items-center rounded-[11px]', item.kind === 'void' ? 'bg-danger-soft text-danger' : 'bg-warning-soft text-warning']">
            <Ban v-if="item.kind === 'void'" :size="18" />
            <HandCoins v-else :size="18" />
          </span>
          <div class="min-w-0 flex-1 basis-48">
            <p class="flex flex-wrap items-baseline gap-x-2">
              <span class="text-sm font-semibold text-fg">{{ t(`vision.review.kind.${item.kind}`) }}</span>
              <span class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="item.amount" /></span>
            </p>
            <p class="truncate text-xs text-muted">
              {{ fmt.instant(item.at, "time") }} · {{ item.cashier?.name ?? t("vision.review.noCashier") }}<template v-if="item.camera"> · {{ [item.camera.name, !branch && branches.length > 1 ? branchOf(item.camera.id) : null].filter(Boolean).join(", ") }}</template>
            </p>
          </div>
          <span class="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-xs font-semibold text-muted dark:bg-surface-3"><UserRoundX :size="13" />{{ t("vision.review.nobody") }}</span>
          <UiButton v-if="item.camera" size="sm" :variant="item.clip?.state === 'ready' ? 'soft' : 'secondary'" :icon="Play" @click="video(item)">{{ t("vision.video") }}</UiButton>
        </li>
      </ul>
      <p class="px-1 text-xs text-subtle">{{ t("vision.review.count", { n: items.length }, items.length) }}</p>
    </template>
    <ClipPlayer v-model:open="clipOpen" :request="clip" :context="context" />
  </div>
</template>
