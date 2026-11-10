<script setup lang="ts">
/**
 * AI › Maslahatchi, the business advisor: the latest business review (weekly, or monthly) with
 * what went well, what went wrong and three things to do, the reviews before it, and
 * "Maslahatchidan so‘rang" beside it: a chat that knows every number ("can I afford a second
 * pharmacy?", "where is my money going?"). On phones the review and the chat are two tabs. The
 * review is written every Monday at 08:00 (Settings: day, time, who gets it); "Write again" has it
 * written now (Claude, when it writes them here, on its way in a minute). A reader sees only the
 * reviews of what they may see; without Claude the templates write them from the same numbers.
 */
import { BarChart3, Bot, CalendarClock, History, MessagesSquare, Newspaper, PenLine, Settings2, Sparkles } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { emptyKey, nextReviewText, periodLabel, writerKey } from "../advisor";
import { useAiStatus, useCompanyId } from "../api";
import { briefingKeys, briefingsApi, useBriefing, useBriefings, useLatestBriefing, type BriefingKind } from "../briefings";
import AdvisorChat from "../components/AdvisorChat.vue";
import AgentChibi from "../components/AgentChibi.vue";
import BriefingReview from "../components/BriefingReview.vue";
import BriefingSettingsForm from "../components/BriefingSettingsForm.vue";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const client = useQueryClient();
const { isPhone } = useBreakpoints();

const KINDS = ["weekly", "monthly"] as const;
const kind = useRouteState("kind", rs.enum<BriefingKind>(KINDS, "weekly"));
const reviewId = useRouteState("review", rs.optionalNumber());
const view = useRouteState("view", rs.enum(["review", "chat"] as const, "review"));

// "Write again" with Claude: the latest is asked for until the new one is in (90 s at most).
const waiting = ref(false);
const rewriting = ref(false);
let waitedFrom: string | null = null;
let giveUp: ReturnType<typeof setTimeout> | null = null;

const latest = useLatestBriefing(kind, waiting);
const history = useBriefings(kind);
const picked = useBriefing(reviewId);
const status = useAiStatus();
const meta = computed(() => latest.data.value ?? null);
const review = computed(() => (reviewId.value ? (picked.data.value ?? null) : (meta.value?.review ?? null)));
const loading = computed(() => (reviewId.value ? picked.isPending.value : latest.isPending.value));
const failure = computed(() => (reviewId.value ? picked.error.value : latest.error.value));
const advisorOn = computed(() => meta.value?.advisor_on ?? false);
const agentName = computed(() => t("ai.advisor.title"));
const agentLink = computed(() => ({ name: "ai.agent", params: { companyId: company.currentId ?? 0, key: "advisor" } }));
const nextText = computed(() => nextReviewText(meta.value, company.timezone, fmt.lang.value));
const nextFor = computed(() => {
  const next = meta.value?.next[kind.value];
  return next ? fmt.instant(next, "short") : null;
});
const empty = computed(() => emptyKey(meta.value));
const chatShown = computed(() => !!meta.value?.chat);
const chatTeaser = computed(() => !!meta.value && !meta.value.chat && company.can("ai.use"));
const older = computed(() => (history.data.value ?? []).filter((row) => row.id !== review.value?.id));

const kindOptions = computed(() => KINDS.map((value) => ({ value, label: t(`ai.advisor.kind.${value}`) })));
const viewOptions = computed(() => [
  { value: "review" as const, label: t("ai.advisor.tab.review"), icon: Newspaper },
  { value: "chat" as const, label: t("ai.advisor.tab.chat"), icon: MessagesSquare },
]);

function pick(id: number | null): void {
  reviewId.value = id;
  if (isPhone.value) window.scrollTo({ top: 0, behavior: "smooth" });
}

watch(kind, () => (reviewId.value = null));

async function regenerate(): Promise<void> {
  if (rewriting.value || waiting.value) return;
  rewriting.value = true;
  try {
    const answer = await briefingsApi.regenerate(cid.value, kind.value);
    if ("queued" in answer) {
      waitedFrom = meta.value?.review?.written_at ?? null;
      waiting.value = true;
      toast.info(t("ai.advisor.rewriteQueued"));
      giveUp = setTimeout(() => (waiting.value = false), 90_000);
    } else {
      reviewId.value = null;
      await Promise.all([
        client.invalidateQueries({ queryKey: briefingKeys.latest(cid.value, kind.value) }),
        client.invalidateQueries({ queryKey: briefingKeys.list(cid.value, kind.value) }),
      ]);
      toast.success(t("ai.advisor.rewritten"));
    }
  } catch {
    // The reason (the day's limit, nothing to review) is a toast from the HTTP layer.
  } finally {
    rewriting.value = false;
  }
}

watch(
  () => meta.value?.review?.written_at,
  (now) => {
    if (!waiting.value || !now || now === waitedFrom) return;
    waiting.value = false;
    reviewId.value = null;
    if (giveUp) clearTimeout(giveUp);
    void client.invalidateQueries({ queryKey: briefingKeys.list(cid.value, kind.value) });
    toast.success(t("ai.advisor.rewritten"));
  },
);
onBeforeUnmount(() => giveUp && clearTimeout(giveUp));

const settingsOpen = ref(false);
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4 md:gap-5">
    <PageHeader :title="t('ai.advisor.title')" :description="t('ai.advisor.description')">
      <template #actions>
        <UiButton variant="ghost" :size="isPhone ? 'lg' : 'md'" :icon="Bot" :to="agentLink" class="max-sm:flex-1" data-testid="advisor-agent-link">{{ t("ai.advisor.agentPage") }}</UiButton>
        <UiButton v-if="meta?.can_configure" :size="isPhone ? 'lg' : 'md'" :icon="Settings2" class="max-sm:flex-1" data-testid="advisor-settings" @click="settingsOpen = true">{{ t("ai.advisor.settings.button") }}</UiButton>
        <UiButton
          v-if="meta?.can_regenerate && meta.has_data"
          variant="primary"
          :size="isPhone ? 'lg' : 'md'"
          :icon="PenLine"
          :loading="rewriting || waiting"
          :disabled="meta.regenerations_left === 0"
          class="max-sm:flex-1"
          data-testid="advisor-rewrite"
          @click="regenerate"
        >
          {{ waiting ? t("ai.advisor.writing") : review ? t("ai.advisor.rewrite") : t("ai.advisor.writeNow") }}
        </UiButton>
      </template>
      <template v-if="meta" #meta>
        <StatusPill :tone="meta.writer === 'ai' ? 'primary' : 'neutral'" :icon="meta.writer === 'ai' ? Sparkles : undefined" :label="t(meta.writer === 'ai' ? 'ai.advisor.writerAi' : 'ai.advisor.writerTemplate')" data-testid="advisor-writer-pill" />
        <span v-if="nextText" class="inline-flex items-center gap-1.5 text-sm text-muted">
          <CalendarClock :size="14" aria-hidden="true" />{{ t("ai.advisor.next", { time: nextText }) }}
        </span>
      </template>
    </PageHeader>

    <SegmentedControl v-if="isPhone && chatShown" v-model="view" :options="viewOptions" block :aria-label="t('ai.advisor.title')" data-testid="advisor-tabs" />

    <div class="grid min-w-0 gap-4 md:gap-5 xl:grid-cols-[minmax(0,1fr)_400px] xl:items-start">
      <div v-show="!isPhone || view === 'review' || !chatShown" class="flex min-w-0 flex-col gap-4 md:gap-5">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <SegmentedControl v-model="kind" :options="kindOptions" size="sm" :aria-label="t('ai.advisor.kindLabel')" data-testid="advisor-kind" />
          <UiButton v-if="reviewId" size="sm" variant="ghost" :icon="History" data-testid="advisor-back-latest" @click="pick(null)">{{ t("ai.advisor.backToLatest") }}</UiButton>
        </div>

        <div v-if="loading" class="ui-card flex flex-col gap-4 p-5 md:p-6" aria-hidden="true" data-testid="advisor-loading">
          <div class="flex items-start gap-4">
            <SkeletonBlock width="76px" height="76px" radius="16px" />
            <div class="flex flex-1 flex-col gap-2"><SkeletonBlock height="14px" width="40%" /><SkeletonBlock height="26px" width="90%" /><SkeletonBlock height="26px" width="70%" /></div>
          </div>
          <div class="grid grid-cols-2 gap-3 xl:grid-cols-4"><SkeletonBlock v-for="n in 4" :key="n" height="72px" radius="10px" /></div>
          <div class="grid gap-3 md:grid-cols-2"><SkeletonBlock v-for="n in 2" :key="n" height="120px" radius="10px" /></div>
        </div>
        <ErrorState v-else-if="failure && !review" class="ui-card" :error="failure" :retry="() => (reviewId ? picked.refetch() : latest.refetch())" />
        <BriefingReview v-else-if="review" :review="review" :agent-name="agentName" :on="advisorOn || review.written_by === 'template'" />
        <section v-else class="ui-card advisor-empty flex flex-col items-center gap-4 px-5 py-10 text-center md:py-14" data-testid="advisor-empty" :data-empty="empty">
          <div class="advisor-empty-chibi grid place-items-center rounded-3xl" aria-hidden="true">
            <AgentChibi agent-key="advisor" :name="agentName" :on="empty !== 'off'" :size="72" />
          </div>
          <template v-if="empty === 'noData'">
            <h2 class="font-display text-xl text-fg">{{ t("ai.advisor.empty.noDataTitle") }}</h2>
            <p class="max-w-[520px] text-base text-muted">{{ t("ai.advisor.empty.noDataBody") }}</p>
          </template>
          <template v-else-if="empty === 'first'">
            <h2 class="font-display text-xl text-fg">{{ t("ai.advisor.empty.firstTitle") }}</h2>
            <p class="max-w-[520px] text-base text-muted">{{ nextFor ? t("ai.advisor.empty.firstBody", { time: nextFor }) : t("ai.advisor.empty.firstBodyLater") }}</p>
            <UiButton v-if="meta?.can_regenerate" variant="primary" :icon="PenLine" :loading="rewriting || waiting" @click="regenerate">{{ t("ai.advisor.writeNow") }}</UiButton>
          </template>
          <template v-else>
            <h2 class="font-display text-xl text-fg">{{ t("ai.advisor.empty.offTitle") }}</h2>
            <p class="max-w-[520px] text-base text-muted">{{ t("ai.advisor.empty.offBody") }}</p>
            <UiButton v-if="meta?.can_configure" :icon="Settings2" @click="settingsOpen = true">{{ t("ai.advisor.settings.button") }}</UiButton>
          </template>
        </section>

        <section v-if="older.length" class="ui-card" data-testid="advisor-history">
          <h3 class="flex items-center gap-2 border-b border-line px-4 py-3 text-md font-semibold text-fg md:px-5">
            <History :size="16" class="text-muted" aria-hidden="true" />{{ t("ai.advisor.history") }}
          </h3>
          <ul class="divide-y divide-line">
            <li v-for="row in older" :key="row.id">
              <button
                type="button"
                class="pressable flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-highlight md:px-5"
                :data-history="row.id"
                @click="pick(row.id)"
              >
                <span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-surface-2 text-muted dark:bg-surface-3" aria-hidden="true"><BarChart3 :size="15" /></span>
                <span class="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span class="flex flex-wrap items-center gap-2 text-sm">
                    <span class="num font-semibold text-fg">{{ periodLabel(row.period, fmt.lang.value) }}</span>
                    <UiBadge :tone="row.written_by === 'ai' ? 'primary' : 'neutral'">{{ t(writerKey(row.written_by)) }}</UiBadge>
                  </span>
                  <span class="line-clamp-2 text-sm text-muted">{{ row.headline }}</span>
                </span>
              </button>
            </li>
          </ul>
        </section>
      </div>

      <aside v-if="chatShown" v-show="!isPhone || view === 'chat'" class="min-w-0 xl:sticky xl:top-0" :aria-label="t('ai.advisor.chat.title')">
        <AdvisorChat
          :agent-name="agentName"
          :on="advisorOn"
          class="h-[calc(100dvh-var(--topbar-h)-var(--tabbar-h)-var(--safe-bottom)-11rem)] min-h-[420px] sm:h-[640px] xl:h-[calc(100dvh-var(--topbar-h)-3.5rem)] xl:max-h-[880px] xl:min-h-[520px]"
        />
      </aside>
      <aside v-else-if="chatTeaser" class="min-w-0">
        <section class="ui-card advisor-teaser flex flex-col gap-3 p-5" data-testid="advisor-chat-teaser">
          <span class="grid size-11 place-items-center rounded-full bg-accent-soft text-accent-fg" aria-hidden="true"><MessagesSquare :size="20" /></span>
          <h2 class="font-display text-lg text-fg">{{ t("ai.advisor.chat.title") }}</h2>
          <p class="text-sm text-muted">{{ t("ai.advisor.chat.teaser") }}</p>
          <p class="text-sm text-fg">{{ !status.data.value?.enabled ? t("ai.advisor.chat.teaserAiOff") : !advisorOn ? t("ai.advisor.chat.teaserAgentOff") : t("ai.advisor.chat.teaserKey") }}</p>
          <div class="flex flex-wrap gap-2">
            <UiButton v-if="!status.data.value?.enabled && status.data.value?.can_configure" variant="primary" size="sm" :icon="Sparkles" :to="{ name: 'ai.agents', params: { companyId: company.currentId ?? 0 } }">{{ t("ai.turnOn.button") }}</UiButton>
            <UiButton v-else-if="!advisorOn" size="sm" :icon="Bot" :to="agentLink">{{ t("ai.advisor.agentPage") }}</UiButton>
          </div>
        </section>
      </aside>
    </div>

    <UiDrawer v-model:open="settingsOpen" :title="t('ai.advisor.settings.title')" :description="t('ai.advisor.settings.description')" size="md">
      <BriefingSettingsForm />
    </UiDrawer>
  </div>
</template>

<style scoped>
.advisor-empty {
  background:
    radial-gradient(80% 120% at 50% 0%, color-mix(in srgb, #6b8fd6 12%, transparent) 0%, transparent 65%),
    var(--c-surface);
}
.advisor-empty-chibi {
  width: 112px;
  height: 112px;
  background: color-mix(in srgb, #6b8fd6 14%, var(--c-surface));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #6b8fd6 22%, transparent);
}
.advisor-teaser {
  background:
    radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--c-primary) 10%, transparent) 0%, transparent 55%),
    var(--c-surface);
}
</style>
