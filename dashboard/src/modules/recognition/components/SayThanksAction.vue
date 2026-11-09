<script setup lang="ts">
/** Person 360's header (`people.profile.actions`): "Say thanks" to someone who works here now. */
import { HeartHandshake } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

import KudosDialog from "./KudosDialog.vue";

interface ProfileContext {
  memberId: number;
  person: { id: number; name: string; status: string } | null;
}

const props = defineProps<{ context: ProfileContext }>();
const { t } = useI18n();
const company = useCompanyStore();
const open = ref(false);
const person = computed(() => props.context.person);
// Not oneself, and only someone working here now.
const shown = computed(() => !!person.value && person.value.status === "approved" && person.value.id !== company.current?.membership_id);
</script>

<template>
  <template v-if="shown && person">
    <UiButton :icon="HeartHandshake" data-testid="say-thanks" @click="open = true">{{ t("recognition.kudos.button") }}</UiButton>
    <KudosDialog v-model:open="open" :person="{ id: person.id, name: person.name }" />
  </template>
</template>
