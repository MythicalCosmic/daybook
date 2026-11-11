<script setup lang="ts">
/**
 * "Link my Telegram" for whoever is signed in (docs/DAVOMAT.md §1.5): the one-time link and QR of
 * their own account (`users/{own membership}/telegram-link/`, open to every user, no roles.manage
 * needed). Opening it in the bot links this Telegram and counts as pressing Start, so the bot's
 * messages (arrivals with the photo, their own scans included) and its Davomat button come at
 * once. Closing the dialog reads the account again to show whether it worked.
 */
import { Send } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import { useCompanyId, useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { userTelegramLink } from "../../api";
import TelegramLinkDialog from "./TelegramLinkDialog.vue";

const props = withDefaults(defineProps<{ linked: boolean; variant?: "primary" | "secondary" | "ghost" }>(), { variant: undefined });
const emit = defineEmits<{ closed: [] }>();

const { t } = useI18n();
const cid = useCompanyId();
const company = useCompanyStore();
const session = useSessionStore();

const open = ref(false);
const create = () => userTelegramLink(cid.value, company.current?.membership_id ?? 0);

watch(open, (isOpen) => {
  if (isOpen) return;
  // Back from the dialog: the person may have linked; show it.
  void session.loadMe().catch(() => undefined);
  emit("closed");
});
</script>

<template>
  <UiButton :variant="props.variant ?? (props.linked ? 'ghost' : 'primary')" :icon="Send" data-link-me @click="open = true">
    {{ props.linked ? t("davomat.telegram.me.relink") : t("davomat.telegram.me.link") }}
  </UiButton>
  <TelegramLinkDialog
    v-model:open="open"
    :title="t('davomat.telegram.me.dialogTitle')"
    :description="props.linked ? undefined : t('davomat.telegram.me.dialogHint')"
    :linked="false"
    :create="create"
  />
</template>
