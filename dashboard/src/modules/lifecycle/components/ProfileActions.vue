<script setup lang="ts">
/**
 * Person 360's header actions from this module (`people.profile.actions`): issue a warning
 * (hr.discipline) and suspend (hr.suspend, for someone who works here now and whom the server lets
 * the viewer suspend). One button when only one applies, a small menu when both do.
 */
import { ChevronDown, Gavel, Pause } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

import { lifecycleAccess } from "../lib";
import RecordFormDrawer from "./RecordFormDrawer.vue";
import SuspendDialog from "./SuspendDialog.vue";

/** What Person 360 passes to its header slot (the person as `people/{id}/` returns them). */
interface ProfileContext {
  memberId: number;
  person: { id: number; name: string; status: string; can?: { suspend?: boolean } } | null;
}

const props = defineProps<{ context: ProfileContext }>();

const { t } = useI18n();
const company = useCompanyStore();
const access = computed(() => lifecycleAccess((perm) => company.can(perm)));

const person = computed(() => props.context.person);
const member = computed(() => (person.value ? { id: person.value.id, name: person.value.name } : null));
const canWarn = computed(() => !!person.value && access.value.discipline && ["approved", "suspended"].includes(person.value.status));
const canSuspend = computed(() => !!person.value && access.value.suspend && person.value.status === "approved" && person.value.can?.suspend !== false);

const warning = ref(false);
const suspending = ref(false);
const menu = computed<MenuEntry[]>(() => [
  ...(canWarn.value ? [{ label: t("lifecycle.person.warn"), description: t("lifecycle.person.warnHint"), icon: Gavel, onSelect: () => (warning.value = true) }] : []),
  ...(canSuspend.value ? [{ label: t("lifecycle.suspend.button"), description: t("lifecycle.person.suspendHint"), icon: Pause, onSelect: () => (suspending.value = true) }] : []),
]);
</script>

<template>
  <div v-if="menu.length" class="contents" data-lifecycle-actions>
    <DropdownMenu v-if="menu.length > 1" :items="menu" align="end">
      <template #trigger>
        <UiButton :icon="Gavel" :icon-right="ChevronDown">{{ t("lifecycle.person.discipline") }}</UiButton>
      </template>
    </DropdownMenu>
    <UiButton v-else-if="canWarn" :icon="Gavel" @click="warning = true">{{ t("lifecycle.person.warn") }}</UiButton>
    <UiButton v-else :icon="Pause" @click="suspending = true">{{ t("lifecycle.suspend.button") }}</UiButton>

    <RecordFormDrawer v-if="canWarn" v-model:open="warning" :member="member" />
    <SuspendDialog v-if="canSuspend" v-model:open="suspending" :member="member" />
  </div>
</template>
