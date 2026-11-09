<script setup lang="ts">
/**
 * Face ID › People: everyone the terminals know (each number seen in the last 90 days), with the
 * latest snapshot, the number and name as the terminal shows them, and who that is in Daybook, or
 * "Not in Daybook" with the people whose names come closest as one-tap links (the terminal often
 * holds a first name only, in Cyrillic or Latin). A number linked automatically says so and is one
 * tap to relink; a number that isn't a person (a guard, a visitor's card) can be set aside.
 */
import { EyeOff, Link2, Unlink, UserRoundX, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useIgnore, useLink, usePeople, useUnlink } from "../api";
import LinkDialog from "../components/LinkDialog.vue";
import Snapshot from "../components/Snapshot.vue";
import type { KnownPerson } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const confirm = useConfirm();

const SHOW = ["all", "unlinked", "linked"] as const;
const show = useRouteState("show", rs.enum(SHOW, "all"));
const search = useRouteState("q", rs.string(""));
const people = usePeople(() => (show.value === "unlinked" ? "0" : show.value === "linked" ? "1" : undefined));
const skeleton = useDelayedPending(computed(() => people.isPending.value));
const link = useLink();
const unlink = useUnlink();
const ignore = useIgnore();
const canManage = computed(() => company.can("attendance.manage"));

const linking = ref<KnownPerson | null>(null);
const dialogOpen = computed({ get: () => linking.value !== null, set: (value: boolean) => (linking.value = value ? linking.value : null) });

const rows = computed(() => {
  const query = search.value.trim().toLocaleLowerCase();
  const all = people.data.value ?? [];
  if (!query) return all;
  return all.filter((row) => [row.employee_no, row.name_on_device, row.member?.name ?? ""].some((value) => value.toLocaleLowerCase().includes(query)));
});
const counts = computed(() => {
  const all = people.data.value ?? [];
  return { linked: all.filter((row) => row.member).length, unlinked: all.filter((row) => !row.member && !row.link?.ignored).length };
});
const tabs = computed(() => [
  { value: "all" as const, label: t("faceid.people.all"), icon: Users },
  { value: "unlinked" as const, label: t("faceid.people.notInDaybook"), icon: UserRoundX, count: show.value === "all" ? counts.value.unlinked || undefined : undefined },
  { value: "linked" as const, label: t("faceid.people.inDaybook"), icon: Link2 },
]);

async function quickLink(row: KnownPerson, memberId: number, name: string): Promise<void> {
  await link.mutateAsync({ employeeNo: row.employee_no, memberId });
  toast.success(t("faceid.people.linkedTo", { name }));
}

async function remove(row: KnownPerson): Promise<void> {
  if (!row.link) return;
  const answer = await confirm({
    title: t("faceid.people.unlinkTitle", { number: row.employee_no }),
    message: t("faceid.people.unlinkBody", { name: row.member?.name ?? "" }),
    confirmLabel: t("faceid.people.unlink"),
  });
  if (!answer) return;
  await unlink.mutateAsync(row.link);
  toast.success(t("faceid.people.unlinked"));
}

async function setAside(row: KnownPerson): Promise<void> {
  await ignore.mutateAsync(row.employee_no);
  toast.success(t("faceid.people.ignored", { number: row.employee_no }));
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('faceid.people.title')" :description="t('faceid.people.description')" />

    <div class="flex flex-wrap items-center gap-2">
      <div class="no-scrollbar max-w-full overflow-x-auto">
        <SegmentedControl v-model="show" size="sm" :options="tabs" />
      </div>
      <span class="flex-1" />
      <TextInput v-model="search" type="search" size="sm" class="w-64 max-sm:w-full" clearable :placeholder="t('faceid.people.search')" />
    </div>

    <div v-if="skeleton" class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <SkeletonBlock v-for="n in 6" :key="n" height="150px" radius="14px" />
    </div>
    <ErrorState v-else-if="people.isError.value" :error="people.error.value" :retry="() => people.refetch()" />
    <div v-else-if="!rows.length" class="ui-card">
      <EmptyState
        :icon="show === 'unlinked' ? Link2 : Users"
        :tone="show === 'unlinked' ? 'success' : 'neutral'"
        :title="search ? t('faceid.people.noMatch') : show === 'unlinked' ? t('faceid.people.allLinked') : t('faceid.people.emptyTitle')"
        :description="search ? undefined : show === 'unlinked' ? t('faceid.people.allLinkedBody') : t('faceid.people.emptyBody')"
      />
    </div>
    <TransitionGroup v-else tag="ul" name="faceid-card" class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <li v-for="row in rows" :key="row.employee_no" class="ui-card flex min-w-0 flex-col gap-3 p-4">
        <div class="flex items-start gap-3">
          <Snapshot :src="row.photo_url" :name="row.name_on_device || row.employee_no" :size="64" :ring="row.member ? 'var(--c-success)' : row.link?.ignored ? 'var(--c-line)' : 'var(--c-warning)'" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-fg">{{ row.name_on_device || t("faceid.people.noName") }}</p>
            <p class="truncate text-xs tabular-nums text-muted">{{ t("faceid.feed.number", { number: row.employee_no }) }} · {{ row.device.name }}</p>
            <p class="mt-1 text-xs text-subtle">
              {{ t("faceid.people.scans", { n: row.scans }, row.scans) }} · <RelativeTime :value="row.last_at" />
            </p>
          </div>
        </div>

        <!-- In Daybook -->
        <div v-if="row.member" class="flex items-center gap-2.5 rounded-[10px] bg-surface-2/70 px-3 py-2">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="28" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-fg">{{ row.member.name }}</p>
            <p class="truncate text-xs text-muted">{{ row.member.position?.name ?? "" }}</p>
          </div>
          <StatusPill v-if="row.link?.auto" size="sm" tone="info" :label="t('faceid.people.auto')" />
          <IconButton v-if="canManage" size="sm" :icon="Unlink" :label="t('faceid.people.unlink')" @click="remove(row)" />
        </div>

        <!-- Set aside -->
        <div v-else-if="row.link?.ignored" class="flex items-center gap-2 rounded-[10px] bg-surface-2/70 px-3 py-2 text-sm text-muted">
          <EyeOff :size="15" aria-hidden="true" />
          <span class="flex-1">{{ t("faceid.people.setAside") }}</span>
          <UiButton v-if="canManage" size="sm" variant="ghost" @click="remove(row)">{{ t("faceid.people.undo") }}</UiButton>
        </div>

        <!-- Not in Daybook -->
        <div v-else class="flex flex-col gap-2">
          <StatusPill class="self-start" size="sm" tone="warning" :label="t('faceid.people.notInDaybook')" />
          <template v-if="canManage">
            <div v-if="row.suggestions.length" class="flex flex-wrap gap-1.5">
              <button
                v-for="suggestion in row.suggestions.slice(0, 3)"
                :key="suggestion.member.id"
                type="button"
                class="pressable inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-surface py-1 pl-1 pr-2.5 text-xs font-medium text-fg transition-colors duration-150 hover:border-[var(--c-primary)] hover:bg-accent-soft"
                :disabled="link.isPending.value"
                @click="quickLink(row, suggestion.member.id, suggestion.member.name)"
              >
                <UserAvatar :name="suggestion.member.name" :src="suggestion.member.photo_url" :size="20" />
                <span class="truncate">{{ t("faceid.people.linkTo", { name: suggestion.member.name }) }}</span>
              </button>
            </div>
            <div class="flex flex-wrap gap-2">
              <UiButton size="sm" variant="secondary" :icon="Link2" @click="linking = row">{{ t("faceid.people.linkOther") }}</UiButton>
              <UiButton size="sm" variant="ghost" :icon="EyeOff" :loading="ignore.isPending.value && ignore.variables.value === row.employee_no" @click="setAside(row)">{{ t("faceid.people.ignore") }}</UiButton>
            </div>
          </template>
        </div>
      </li>
    </TransitionGroup>

    <LinkDialog
      v-if="linking"
      v-model:open="dialogOpen"
      :employee-no="linking.employee_no"
      :name-on-device="linking.name_on_device"
      :photo-url="linking.photo_url"
      :suggestions="linking.suggestions"
    />
  </div>
</template>

<style scoped>
.faceid-card-move,
.faceid-card-enter-active,
.faceid-card-leave-active {
  transition:
    transform 220ms var(--ease-out),
    opacity 180ms var(--ease-out);
}
.faceid-card-enter-from,
.faceid-card-leave-to {
  opacity: 0;
  transform: scale(0.98);
}
.faceid-card-leave-active {
  position: absolute;
}
@media (prefers-reduced-motion: reduce) {
  .faceid-card-move,
  .faceid-card-enter-active,
  .faceid-card-leave-active {
    transition: none;
  }
}
</style>
