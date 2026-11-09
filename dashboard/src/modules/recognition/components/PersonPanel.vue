<script setup lang="ts">
/**
 * Learning's person page (`learning.person.panels`, PLAN-LEARNING §11): their points, level,
 * streak and badges, with the whole story one click away.
 */
import { Flame, Trophy } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";

import { useProfile } from "../api";
import Medal from "./Medal.vue";
import PersonDrawer from "./PersonDrawer.vue";

const props = defineProps<{ context: { companyId?: number | null; memberId: number } }>();
const { t } = useI18n();
const fmt = useFormat();
const profile = useProfile(() => props.context.memberId);
const data = computed(() => profile.data.value);
const drawer = ref(false);
</script>

<template>
  <section class="ui-card flex flex-col gap-4 p-4" data-testid="recognition-person-panel">
    <div class="flex items-center justify-between gap-3">
      <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><Trophy :size="16" aria-hidden="true" />{{ t("recognition.panel.title") }}</h3>
      <UiButton size="sm" variant="ghost" @click="drawer = true">{{ t("recognition.panel.open") }}</UiButton>
    </div>
    <SkeletonBlock v-if="profile.isPending.value" height="72px" radius="10px" />
    <p v-else-if="!data" class="text-sm text-muted">{{ t("recognition.panel.none") }}</p>
    <template v-else>
      <div class="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-accent-fg">{{ t("recognition.level", { number: data.level.number }) }}</p>
          <p class="text-lg font-semibold text-fg">{{ data.level.name }}</p>
        </div>
        <div>
          <p class="text-xs text-muted">{{ t("recognition.person.total") }}</p>
          <p class="text-lg font-semibold tabular-nums">{{ fmt.number(data.points) }}</p>
        </div>
        <div>
          <p class="text-xs text-muted">{{ t("recognition.period.week") }}</p>
          <p class="text-lg font-semibold tabular-nums">{{ fmt.number(data.week_points) }}</p>
        </div>
        <div>
          <p class="flex items-center gap-1 text-xs text-muted"><Flame :size="13" aria-hidden="true" />{{ t("recognition.person.streak") }}</p>
          <p class="text-lg font-semibold tabular-nums">{{ data.streak }}</p>
        </div>
      </div>
      <ul v-if="data.badges.length" class="flex flex-wrap gap-2">
        <li v-for="badge in data.badges.slice(0, 10)" :key="`${badge.key}:${badge.ref}`" :title="`${badge.name}: ${badge.description}`">
          <Medal :icon="badge.icon" :tier="badge.tier" :size="34" />
        </li>
      </ul>
    </template>
    <PersonDrawer v-model:open="drawer" :member-id="context.memberId" />
  </section>
</template>
