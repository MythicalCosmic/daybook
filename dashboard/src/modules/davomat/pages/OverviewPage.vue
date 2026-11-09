<script setup lang="ts">
/**
 * The Overview, Davomat's home (v8 F bar, docs/DAVOMAT.md): a greeting with the day and the time,
 * the KPI strip (in the building now with a ring of today's expected, late today with the minutes,
 * not in yet, on leave, terminals online), the live feed of scans with their snapshots, who's here
 * now as faces, and who needs a look. The branch filter narrows everything. It reads attendance's
 * day board and Face ID's scans and terminal status through the API; every scan and check-in moves
 * it (pulse), and the feed also polls every few seconds.
 */
import { Clock3, DoorOpen, MapPin, Palmtree, ScanFace, UserPlus, UserRoundX } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import UiButton from "@/components/UiButton.vue";
import { findModule } from "@/core/modules";
import { connection } from "@/core/pulse";
import { dayPart } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore, useCompanyToday } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import AttentionList from "../components/overview/AttentionList.vue";
import HereNow from "../components/overview/HereNow.vue";
import KpiTile from "../components/overview/KpiTile.vue";
import LiveFeed from "../components/overview/LiveFeed.vue";
import { attentionOf, insideNow, kpisOf, useBoard, useTerminalStatus, useTodayScans } from "../components/overview/overviewApi";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const session = useSessionStore();
const today = useCompanyToday();
const now = useNow();
const canManage = useCan("attendance.manage");
const canAddPeople = useCan("members.manage");

const branches = computed(() => company.current?.branches ?? []);
const filter = computed<number[]>({ get: () => company.branchFilter, set: (ids) => company.setBranchFilter(ids) });

const board = useBoard(filter, today);
const status = useTerminalStatus();
const scans = useTodayScans(computed(() => ({ date: today.value, branch: filter.value })));

const kpis = computed(() => kpisOf(board.data.value));
const boardLoading = computed(() => board.isPending.value);
type Focus = "late" | "notIn" | "leave" | null;
const focus = ref<Focus>(null);
const toggle = (next: Exclude<Focus, null>) => (focus.value = focus.value === next ? null : next);

const inside = computed(() => insideNow(board.data.value));
const attention = computed(() => attentionOf(board.data.value, focus.value));
const attentionTitle = computed(() =>
  focus.value === "late" ? t("davomat.overview.kpi.late") : focus.value === "notIn" ? t("davomat.overview.kpi.notIn") : focus.value === "leave" ? t("davomat.overview.kpi.leave") : t("davomat.overview.attention.title"),
);

/** The newest snapshot of each person today: their face in "Who's here" when they have no photo. */
const photos = computed(() => {
  const map = new Map<number, string>();
  for (const scan of scans.data.value?.results ?? []) if (scan.member && scan.photo_url && !map.has(scan.member.id)) map.set(scan.member.id, scan.photo_url);
  return map;
});

const terminals = computed(() => status.data.value ?? null);
const terminalSub = computed(() => {
  const s = terminals.value;
  if (!s || s.total === 0) return t("davomat.overview.kpi.terminalsNone");
  if (s.online === s.total) return t("davomat.overview.kpi.terminalsAll");
  if (s.quiet > 0) return t("davomat.overview.kpi.terminalsQuiet", { n: s.quiet }, s.quiet);
  return t("davomat.overview.kpi.terminalsNever", { n: s.never }, s.never);
});
const terminalPulse = computed(() => {
  const s = terminals.value;
  if (!s || s.total === 0) return null;
  return s.online === s.total ? "success" : "warning";
});
const noTerminals = computed(() => status.isSuccess.value && (terminals.value?.total ?? 0) === 0);
/** Terminals are added but none has sent anything yet: the address still has to go into the device. */
const notConnected = computed(() => {
  const s = terminals.value;
  return !!s && s.total > 0 && s.online === 0 && s.quiet === 0 && s.never > 0;
});

const base = computed(() => `/c/${company.currentId}`);
const faceid = computed(() => !!findModule("faceid"));
const attendanceLink = computed(() => (findModule("attendance") ? `${base.value}/attendance` : null));
const terminalsLink = computed(() => (faceid.value ? `${base.value}/faceid/terminals` : undefined));

const greeting = computed(() => {
  const part = dayPart(company.timezone, now.value);
  const key = part === "night" ? "evening" : part;
  const name = session.me?.user.first_name;
  return name ? `${t(`davomat.overview.greeting.${key}`)}, ${name}` : t(`davomat.overview.greeting.${key}`);
});
const dateLine = computed(() => fmt.day(today.value, "long"));
const clock = computed(() => fmt.instant(new Date(now.value), "time"));
</script>

<template>
  <div class="flex flex-col gap-5 md:gap-6" data-testid="overview">
    <!-- Greeting, the day and the time; the branch filter -->
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <h1 class="text-[26px] font-bold leading-tight tracking-[-0.025em] text-fg md:text-[30px]">{{ greeting }}</h1>
        <p class="mt-1 flex flex-wrap items-center gap-x-2 text-base text-muted">
          <span class="capitalize">{{ dateLine }}</span>
          <span aria-hidden="true" class="text-subtle">·</span>
          <span class="inline-flex items-center gap-1 tabular-nums"><Clock3 :size="14" aria-hidden="true" />{{ clock }}</span>
          <template v-if="company.current">
            <span aria-hidden="true" class="text-subtle">·</span>
            <span class="truncate">{{ company.current.name }}</span>
          </template>
        </p>
      </div>
      <div v-if="branches.length > 1" class="w-full sm:w-[260px]">
        <BranchPicker v-model="filter" multiple :branches="branches" :placeholder="t('davomat.overview.branches.all')" data-testid="overview-branches" />
      </div>
    </header>

    <!-- The numbers -->
    <div class="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-5" data-testid="overview-kpis">
      <KpiTile
        class="col-span-2 lg:col-span-1"
        :label="t('davomat.overview.kpi.inside')"
        :value="boardLoading ? null : kpis.inside"
        :total="kpis.expected || null"
        :share="kpis.expected ? kpis.inside / kpis.expected : null"
        :sub="kpis.expected ? t('davomat.overview.kpi.insideOf', { n: kpis.expected }) : t('davomat.overview.kpi.insideNone')"
        :icon="DoorOpen"
        tone="success"
        :loading="boardLoading"
        data-testid="kpi-inside"
        @select="focus = null"
      />
      <KpiTile
        :label="t('davomat.overview.kpi.late')"
        :value="boardLoading ? null : kpis.late"
        :sub="kpis.late ? t('davomat.overview.kpi.lateMinutes', { n: kpis.lateMinutes }) : t('davomat.overview.kpi.lateNone')"
        :icon="Clock3"
        tone="warning"
        :active="focus === 'late'"
        :loading="boardLoading"
        data-testid="kpi-late"
        @select="toggle('late')"
      />
      <KpiTile
        :label="t('davomat.overview.kpi.notIn')"
        :value="boardLoading ? null : kpis.notIn"
        :sub="kpis.notIn ? t('davomat.overview.kpi.notInHint') : t('davomat.overview.kpi.notInNone')"
        :icon="UserRoundX"
        tone="danger"
        :active="focus === 'notIn'"
        :loading="boardLoading"
        data-testid="kpi-not-in"
        @select="toggle('notIn')"
      />
      <KpiTile
        :label="t('davomat.overview.kpi.leave')"
        :value="boardLoading ? null : kpis.leave"
        :sub="t('davomat.overview.kpi.leaveHint')"
        :icon="Palmtree"
        tone="info"
        :active="focus === 'leave'"
        :loading="boardLoading"
        data-testid="kpi-leave"
        @select="toggle('leave')"
      />
      <KpiTile
        :label="t('davomat.overview.kpi.terminals')"
        :value="status.isPending.value ? null : (terminals?.online ?? 0)"
        :total="terminals?.total || null"
        :sub="terminalSub"
        :icon="ScanFace"
        tone="primary"
        :pulse="terminalPulse"
        :to="terminalsLink"
        :loading="status.isPending.value"
        data-testid="kpi-terminals"
      />
    </div>

    <!-- No terminal yet, or none connected yet: the next thing to do -->
    <section v-if="noTerminals || notConnected" class="hero relative overflow-hidden rounded-[20px] border border-line p-6 md:p-8" data-testid="overview-setup">
      <div class="relative flex flex-col gap-5 md:flex-row md:items-center">
        <span class="grid size-14 shrink-0 place-items-center rounded-[16px] bg-primary text-on-primary shadow-pop"><ScanFace :size="28" /></span>
        <div class="min-w-0 flex-1">
          <h2 class="text-lg font-bold tracking-[-0.015em] text-fg">{{ noTerminals ? t("davomat.overview.setup.title") : t("davomat.overview.connect.title") }}</h2>
          <p class="mt-1 max-w-[620px] text-base text-muted">{{ noTerminals ? t("davomat.overview.setup.body") : t("davomat.overview.connect.body") }}</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <template v-if="noTerminals">
            <UiButton v-if="faceid && canManage" variant="primary" size="lg" :icon="ScanFace" :to="`${base}/faceid/terminals?add=1`">{{ t("davomat.overview.setup.action") }}</UiButton>
            <UiButton v-if="canAddPeople" variant="secondary" size="lg" :icon="UserPlus" :to="`${base}/team?employee=new`">{{ t("davomat.overview.setup.team") }}</UiButton>
          </template>
          <UiButton v-else-if="faceid && canManage" variant="primary" size="lg" :icon="ScanFace" :to="`${base}/faceid/terminals`">{{ t("davomat.overview.connect.action") }}</UiButton>
        </div>
      </div>
    </section>

    <!-- The live feed; who's here and who needs a look -->
    <div class="grid grid-cols-1 gap-5 md:gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(340px,1fr)]">
      <LiveFeed
        class="order-2 lg:order-1"
        :scans="scans.data.value?.results ?? []"
        :loading="scans.isPending.value"
        :error="scans.error.value"
        :offline="connection !== 'online'"
        :retry="() => scans.refetch()"
      />
      <div class="order-1 flex min-w-0 flex-col gap-5 md:gap-6 lg:order-2">
        <AttentionList :rows="attention" :title="attentionTitle" :photos="photos" :loading="boardLoading" :attendance-link="attendanceLink" />
        <HereNow :rows="inside" :photos="photos" :loading="boardLoading" />
      </div>
    </div>

    <p v-if="board.data.value?.holiday" class="flex items-center gap-2 text-sm text-muted"><MapPin :size="14" aria-hidden="true" />{{ board.data.value.holiday }}</p>
  </div>
</template>

<style scoped>
.hero {
  background:
    radial-gradient(28rem 16rem at 0% 0%, color-mix(in srgb, var(--c-primary) 14%, transparent), transparent 70%),
    radial-gradient(24rem 14rem at 100% 100%, color-mix(in srgb, var(--c-chart-2) 12%, transparent), transparent 70%),
    var(--c-surface);
}
</style>
