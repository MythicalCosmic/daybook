<script setup lang="ts">
/**
 * Who's here now: a face for everyone still checked in, grouped by location when there are
 * several, with the check-in time under each (amber ring: came late). A face opens the person.
 */
import { UsersRound } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import FaceThumb from "./FaceThumb.vue";
import type { BoardRow } from "./overviewApi";

const props = withDefaults(defineProps<{ rows: BoardRow[]; photos: Map<number, string>; loading?: boolean; limit?: number }>(), { loading: false, limit: 30 });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const groups = computed(() => {
  const byBranch = new Map<string, { key: string; name: string; rows: BoardRow[] }>();
  for (const row of props.rows.slice(0, props.limit)) {
    const key = String(row.branch?.id ?? "none");
    const group = byBranch.get(key) ?? { key, name: row.branch?.name ?? "", rows: [] };
    group.rows.push(row);
    byBranch.set(key, group);
  }
  return [...byBranch.values()];
});
const more = computed(() => Math.max(0, props.rows.length - props.limit));
const firstName = (name: string) => name.split(/\s+/)[0] ?? name;
const link = (row: BoardRow) => `/c/${company.currentId}/team/${row.member.id}`;
</script>

<template>
  <section class="rounded-[18px] border border-line bg-surface" :aria-label="t('davomat.overview.here.title')" data-testid="here-now">
    <header class="flex items-center justify-between gap-3 border-b border-line px-4 py-3.5 md:px-5">
      <h2 class="text-md font-semibold tracking-[-0.01em] text-fg">{{ t("davomat.overview.here.title") }}</h2>
      <span v-if="!loading" class="rounded-full bg-success-soft px-2.5 py-0.5 text-xs font-semibold tabular-nums text-success">{{ t("davomat.overview.here.count", { n: rows.length }, rows.length) }}</span>
    </header>
    <div v-if="loading && !rows.length" class="grid grid-cols-4 gap-x-2 gap-y-4 p-4 sm:grid-cols-5" aria-hidden="true">
      <div v-for="n in 10" :key="n" class="flex flex-col items-center gap-2">
        <SkeletonBlock circle width="48px" height="48px" />
        <SkeletonBlock width="70%" height="10px" />
      </div>
    </div>
    <EmptyState v-else-if="!rows.length" class="py-10" size="sm" tone="neutral" :icon="UsersRound" :title="t('davomat.overview.here.empty.title')" :description="t('davomat.overview.here.empty.body')" />
    <div v-else class="flex flex-col gap-4 p-4">
      <div v-for="group in groups" :key="group.key">
        <p v-if="groups.length > 1 && group.name" class="mb-2.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ group.name }}</p>
        <ul class="grid grid-cols-4 gap-x-1 gap-y-3 sm:grid-cols-5 lg:grid-cols-4 xl:grid-cols-5">
          <li v-for="row in group.rows" :key="row.member.id">
            <RouterLink :to="link(row)" class="pressable group flex flex-col items-center gap-1.5 rounded-[12px] px-1 py-1.5 text-center hover:bg-highlight" :title="row.member.name">
              <FaceThumb :src="row.member.photo_url ?? photos.get(row.member.id)" :name="row.member.name" :size="48" :tone="row.state === 'late' ? 'warning' : 'success'" />
              <span class="w-full truncate text-xs font-semibold text-fg">{{ firstName(row.member.name) }}</span>
              <span class="-mt-1 text-[11px] tabular-nums text-muted">{{ row.record?.check_in_at ? fmt.instant(row.record.check_in_at, "time") : "" }}</span>
            </RouterLink>
          </li>
        </ul>
      </div>
      <p v-if="more" class="text-center text-sm font-medium text-muted">{{ t("davomat.overview.here.more", { n: more }) }}</p>
    </div>
  </section>
</template>
