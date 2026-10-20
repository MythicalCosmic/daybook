<script setup lang="ts">
/**
 * Tills, payment methods and the sales rules on one page (the "Get started" step `sales.registers`
 * links here). The same three panels are registered as Settings panels for package A's page.
 */
import { CreditCard, SlidersHorizontal, Wallet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import PageHeader from "@/components/PageHeader.vue";
import { rs, useRouteState } from "@/lib/useRouteState";

import PaymentMethodsPanel from "../components/PaymentMethodsPanel.vue";
import RegistersPanel from "../components/RegistersPanel.vue";
import SalesSettingsPanel from "../components/SalesSettingsPanel.vue";

const { t } = useI18n();
const tab = useRouteState<"tills" | "methods" | "rules">("tab", rs.enum(["tills", "methods", "rules"] as const, "tills"));
const tabs = computed(() => [
  { id: "tills", label: t("sales.setup.tills"), icon: Wallet },
  { id: "methods", label: t("sales.setup.methods"), icon: CreditCard },
  { id: "rules", label: t("sales.setup.rules"), icon: SlidersHorizontal },
]);
</script>

<template>
  <div class="mx-auto w-full max-w-[880px]">
    <PageHeader v-model:tab="tab" :title="t('sales.setup.title')" :description="t('sales.setup.description')" :tabs="tabs" />
    <RegistersPanel v-if="tab === 'tills'" />
    <PaymentMethodsPanel v-else-if="tab === 'methods'" />
    <SalesSettingsPanel v-else />
  </div>
</template>
