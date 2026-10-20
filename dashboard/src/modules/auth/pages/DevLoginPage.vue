<script setup lang="ts">
/**
 * Development sign-in (plan §4.3, §7.3): `POST /owner/auth/dev-login/ {telegram_id}` against a DEBUG
 * backend with DASHBOARD_DEV_LOGIN on. The auth module routes it only when `import.meta.env.DEV`,
 * so a production build doesn't contain it.
 */
import { ArrowRight } from "@lucide/vue";
import { z } from "zod";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AuthLayout from "@/components/AuthLayout.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { safeNext } from "@/lib/links";
import { useForm } from "@/lib/useForm";
import { useSessionStore } from "@/stores/session";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const session = useSessionStore();

/** People `seed_demo` creates (backend/apps/core/management/commands/seed_demo.py) and the owner's own account (plan §13.0). */
const presets = [
  { id: 1001, name: "Dilnoza Karimova", role: "auth.dev.owner" },
  { id: 1002, name: "Bekzod Mirzayev", role: "auth.dev.manager" },
  { id: 2001, name: "Sardor Qodirov", role: "auth.dev.cafeManager" },
  { id: 6589960007, name: "6589960007", role: "auth.dev.you" },
];

const schema = z.object({
  telegramId: z.string().trim().regex(/^\d{3,15}$/, "auth.dev.invalidId"),
});

const form = useForm(schema, { telegramId: "1001" }, {
  onSubmit: async ({ telegramId }) => {
    await session.devLogin(Number(telegramId));
    await router.replace(safeNext(route.query.next));
  },
});

function pick(id: number): void {
  form.values.telegramId = String(id);
  void form.submit();
}
</script>

<template>
  <AuthLayout>
    <form class="flex flex-col" novalidate @submit="form.submit">
      <h1 class="text-lg font-semibold text-fg">{{ t("auth.dev.title") }}</h1>
      <p class="mt-1.5 text-sm text-muted">{{ t("auth.dev.body") }}</p>

      <p class="mb-2 mt-6 text-xs font-medium text-muted">{{ t("auth.dev.presets") }}</p>
      <div class="flex flex-col gap-1.5">
        <button
          v-for="preset in presets"
          :key="preset.id"
          type="button"
          class="pressable flex items-center gap-3 rounded-[10px] border border-line px-3 py-2 text-left hover:border-line-strong hover:bg-surface-2"
          :disabled="form.submitting.value"
          @click="pick(preset.id)"
        >
          <UserAvatar :name="preset.name" :size="32" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-base font-semibold text-fg">{{ preset.name }}</span>
            <span class="block text-xs text-muted">{{ t(preset.role) }} · {{ preset.id }}</span>
          </span>
          <ArrowRight :size="16" class="text-subtle" />
        </button>
      </div>

      <label for="dev-telegram-id" class="mb-1.5 mt-6 text-sm font-medium text-fg">{{ t("auth.dev.telegramId") }}</label>
      <input
        id="dev-telegram-id"
        v-model="form.values.telegramId"
        inputmode="numeric"
        autocomplete="off"
        :aria-invalid="!!form.errors.telegramId"
        :class="[
          'h-10 rounded-input border bg-surface px-3 text-md text-fg outline-none transition-shadow',
          form.errors.telegramId ? 'border-danger focus:shadow-[0_0_0_3px_var(--c-danger-soft)]' : 'border-line focus:border-primary focus:shadow-[0_0_0_3px_var(--c-accent-soft)]',
        ]"
        @blur="form.touch('telegramId')"
      />
      <p v-if="form.errors.telegramId" class="mt-1.5 text-sm text-danger">{{ form.errors.telegramId }}</p>
      <p v-if="form.formError.value" class="mt-3 rounded-[8px] bg-danger-soft px-3 py-2 text-sm text-danger">{{ form.formError.value }}</p>

      <UiButton class="mt-5" variant="primary" size="lg" type="submit" block :loading="form.submitting.value">{{ t("auth.dev.submit") }}</UiButton>
    </form>
  </AuthLayout>
</template>
