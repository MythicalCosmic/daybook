<script setup lang="ts">
/**
 * Person 360's header actions from this module (`people.profile.actions`): issue a warning
 * (hr.discipline), suspend (hr.suspend, for someone who works here now and whom the server lets the
 * viewer suspend), change their job (hr.manage) and start their leaving (hr.terminate). One button
 * when only one applies, a small menu when several do. Nobody gets them on their own page.
 */
import { CalendarClock, ChevronDown, Gavel, Pause, Shuffle, UserCog } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

import { changeAccess, leavingAccess, lifecycleAccess } from "../lib";
import type { JobChange, Leaving } from "../types";
import ProposeChangeDialog from "./ProposeChangeDialog.vue";
import RecordFormDrawer from "./RecordFormDrawer.vue";
import StartLeavingDialog from "./StartLeavingDialog.vue";
import SuspendDialog from "./SuspendDialog.vue";

/** What Person 360 passes to its header slot (the person as `people/{id}/` returns them). */
interface ProfileContext {
  memberId: number;
  person: { id: number; name: string; status: string; can?: { suspend?: boolean } } | null;
}

const props = defineProps<{ context: ProfileContext }>();

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const access = computed(() => lifecycleAccess((perm) => company.can(perm)));
const leaving = computed(() => leavingAccess((perm) => company.can(perm)));
const changes = computed(() => changeAccess((perm) => company.can(perm)));

const person = computed(() => props.context.person);
const member = computed(() => (person.value ? { id: person.value.id, name: person.value.name } : null));
const works = computed(() => !!person.value && ["approved", "suspended"].includes(person.value.status));
const canWarn = computed(() => works.value && access.value.discipline);
const canSuspend = computed(() => !!person.value && access.value.suspend && person.value.status === "approved" && person.value.can?.suspend !== false);
const canChange = computed(() => works.value && changes.value.propose);
const canLeave = computed(() => works.value && leaving.value.manage);

const warning = ref(false);
const suspending = ref(false);
const changing = ref(false);
const starting = ref(false);
const menu = computed<MenuEntry[]>(() => [
  ...(canWarn.value ? [{ label: t("lifecycle.person.warn"), description: t("lifecycle.person.warnHint"), icon: Gavel, onSelect: () => (warning.value = true) }] : []),
  ...(canSuspend.value ? [{ label: t("lifecycle.suspend.button"), description: t("lifecycle.person.suspendHint"), icon: Pause, onSelect: () => (suspending.value = true) }] : []),
  ...(canChange.value ? [{ label: t("lifecycle.person.changeJob"), description: t("lifecycle.person.changeJobHint"), icon: Shuffle, onSelect: () => (changing.value = true) }] : []),
  ...(canLeave.value ? [{ label: t("lifecycle.person.startLeaving"), description: t("lifecycle.person.startLeavingHint"), icon: CalendarClock, onSelect: () => (starting.value = true) }] : []),
]);

/** Their Career tab, with what was just made open in its panel. */
const career = () => `/c/${company.currentId}/people/${props.context.memberId}/career`;
function openChange(change: JobChange): void {
  void router.push({ path: career(), query: { change: String(change.id) } });
}
function openLeaving(row: Leaving): void {
  void router.push({ path: career(), query: { termination: String(row.id) } });
}
</script>

<template>
  <div v-if="menu.length" class="contents" data-lifecycle-actions>
    <DropdownMenu v-if="menu.length > 1" :items="menu" align="end">
      <template #trigger>
        <UiButton :icon="UserCog" :icon-right="ChevronDown">{{ t("lifecycle.person.actions") }}</UiButton>
      </template>
    </DropdownMenu>
    <UiButton v-else-if="canWarn" :icon="Gavel" @click="warning = true">{{ t("lifecycle.person.warn") }}</UiButton>
    <UiButton v-else-if="canSuspend" :icon="Pause" @click="suspending = true">{{ t("lifecycle.suspend.button") }}</UiButton>
    <UiButton v-else-if="canChange" :icon="Shuffle" @click="changing = true">{{ t("lifecycle.person.changeJob") }}</UiButton>
    <UiButton v-else :icon="CalendarClock" @click="starting = true">{{ t("lifecycle.person.startLeaving") }}</UiButton>

    <RecordFormDrawer v-if="canWarn" v-model:open="warning" :member="member" />
    <SuspendDialog v-if="canSuspend" v-model:open="suspending" :member="member" />
    <ProposeChangeDialog v-if="canChange" v-model:open="changing" :member="member" @saved="openChange" />
    <StartLeavingDialog v-if="canLeave" v-model:open="starting" :member="member" @saved="openLeaving" />
  </div>
</template>
