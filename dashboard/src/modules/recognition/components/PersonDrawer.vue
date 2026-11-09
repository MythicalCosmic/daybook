<script setup lang="ts">
/**
 * One person's recognition: level and points (this week, this month, all time), the learning
 * streak, badges, thanks, the latest points, and the owner's correction (± points with a note
 * the person sees, recognition.manage).
 */
import { Flame, HeartHandshake, Minus, Plus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { recognitionApi, useProfile, useRefresh } from "../api";
import { MANAGE } from "../lib";
import Medal from "./Medal.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ memberId: number | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const profile = useProfile(() => (open.value ? props.memberId : null));
const data = computed(() => profile.data.value);
const canManage = computed(() => company.can(MANAGE));

const points = ref<number | null>(null);
const note = ref("");
const error = ref<string | null>(null);
const saving = ref(false);
watch(open, (value) => {
  if (!value) return;
  points.value = null;
  note.value = "";
  error.value = null;
});

async function adjust(sign: 1 | -1): Promise<void> {
  error.value = null;
  if (!points.value || !note.value.trim() || !props.memberId) {
    error.value = t("recognition.adjust.missing");
    return;
  }
  saving.value = true;
  try {
    await recognitionApi.adjust(company.currentId ?? 0, props.memberId, { points: sign * Math.abs(points.value), note: note.value.trim() });
    toast.success(t("recognition.adjust.saved"));
    points.value = null;
    note.value = "";
    refresh();
  } catch (failure) {
    error.value = isApiError(failure) ? (Object.values(failure.fieldErrors)[0]?.[0] ?? failure.message) : t("recognition.adjust.failed");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDrawer v-model:open="open" :title="data?.member.name ?? t('recognition.person.title')" size="md">
    <div v-if="profile.isPending.value" class="flex flex-col gap-3">
      <SkeletonBlock height="96px" radius="12px" />
      <SkeletonBlock height="160px" radius="12px" />
    </div>
    <div v-else-if="data" class="flex flex-col gap-5" data-testid="recognition-person">
      <div class="flex items-center gap-4">
        <UserAvatar :name="data.member.name" :src="data.member.avatar_url" :size="56" />
        <div class="min-w-0">
          <p class="text-xs font-semibold uppercase tracking-wide text-accent-fg">{{ t("recognition.level", { number: data.level.number }) }}</p>
          <p class="truncate text-lg font-semibold text-fg">{{ data.level.name }}</p>
          <p class="text-sm text-muted">
            <template v-if="data.level.next_at !== null">{{ t("recognition.person.toNext", { n: fmt.number(data.level.next_at - data.points), name: data.level.next_name ?? "" }, data.level.next_at - data.points) }}</template>
            <template v-else>{{ t("recognition.person.top") }}</template>
          </p>
        </div>
      </div>

      <dl class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div class="ui-card p-3">
          <dt class="text-xs text-muted">{{ t("recognition.person.total") }}</dt>
          <dd class="text-lg font-semibold tabular-nums">{{ fmt.number(data.points) }}</dd>
        </div>
        <div class="ui-card p-3">
          <dt class="text-xs text-muted">{{ t("recognition.period.week") }}</dt>
          <dd class="text-lg font-semibold tabular-nums">{{ fmt.number(data.week_points) }}</dd>
        </div>
        <div class="ui-card p-3">
          <dt class="text-xs text-muted">{{ t("recognition.period.month") }}</dt>
          <dd class="text-lg font-semibold tabular-nums">{{ fmt.number(data.month_points) }}</dd>
        </div>
        <div class="ui-card p-3">
          <dt class="flex items-center gap-1 text-xs text-muted"><Flame :size="13" aria-hidden="true" />{{ t("recognition.person.streak") }}</dt>
          <dd class="text-lg font-semibold tabular-nums">{{ data.streak }} <span class="text-xs font-normal text-muted">/ {{ data.best_streak }}</span></dd>
        </div>
      </dl>

      <section>
        <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("recognition.nav.badges") }} · {{ data.badges.length }}</h3>
        <p v-if="!data.badges.length" class="text-sm text-muted">{{ t("recognition.person.noBadges") }}</p>
        <ul v-else class="flex flex-wrap gap-3">
          <li v-for="badge in data.badges" :key="`${badge.key}:${badge.ref}`" class="flex w-20 flex-col items-center gap-1 text-center" :title="badge.description">
            <Medal :icon="badge.icon" :tier="badge.tier" />
            <span class="text-xs leading-tight text-fg">{{ badge.name }}</span>
          </li>
        </ul>
      </section>

      <p class="flex items-center gap-2 text-sm text-muted">
        <HeartHandshake :size="16" aria-hidden="true" />
        {{ t("recognition.person.kudos", { received: data.kudos_received, given: data.kudos_given }) }}
      </p>

      <section>
        <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("recognition.person.history") }}</h3>
        <EmptyState v-if="!data.history.length" size="sm" :title="t('recognition.person.noPoints')" />
        <ul v-else class="divide-y divide-line">
          <li v-for="row in data.history" :key="row.id" class="flex items-center gap-3 py-2">
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-fg">{{ row.label }}</p>
              <p class="truncate text-xs text-muted">{{ [row.detail, fmt.instant(row.at, "date")].filter(Boolean).join(" · ") }}</p>
            </div>
            <span class="text-sm font-semibold tabular-nums" :class="row.points > 0 ? 'text-success' : 'text-danger'">{{ row.points > 0 ? `+${row.points}` : `−${Math.abs(row.points)}` }}</span>
          </li>
        </ul>
      </section>

      <section v-if="canManage" class="ui-card flex flex-col gap-3 p-4">
        <div>
          <h3 class="text-sm font-semibold text-fg">{{ t("recognition.adjust.title") }}</h3>
          <p class="text-xs text-muted">{{ t("recognition.adjust.hint") }}</p>
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-[140px_1fr]">
          <FormField :label="t('recognition.adjust.points')">
            <NumberInput v-model="points" :min="1" :max="10000" />
          </FormField>
          <FormField :label="t('recognition.adjust.note')" :error="error ?? undefined">
            <TextInput v-model="note" :maxlength="200" :placeholder="t('recognition.adjust.notePlaceholder')" />
          </FormField>
        </div>
        <div class="flex gap-2">
          <UiButton variant="secondary" :icon="Plus" :loading="saving" @click="adjust(1)">{{ t("recognition.adjust.add") }}</UiButton>
          <UiButton variant="ghost" :icon="Minus" :loading="saving" @click="adjust(-1)">{{ t("recognition.adjust.take") }}</UiButton>
        </div>
      </section>
    </div>
  </UiDrawer>
</template>
