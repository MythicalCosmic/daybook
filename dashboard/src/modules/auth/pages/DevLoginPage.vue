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

import { DEMO_COMPANIES, DEMO_STRANGERS } from "../demoPeople";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const session = useSessionStore();

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

      <p class="mt-6 text-xs font-medium text-muted">{{ t("auth.dev.presets") }}</p>
      <section v-for="demo in DEMO_COMPANIES" :key="demo.name" class="mt-3" :aria-label="demo.name" data-demo-company>
        <h2 class="mb-1.5 text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ demo.name }}</h2>
        <div class="flex flex-col gap-1">
          <button
            v-for="person in demo.people"
            :key="person.id"
            type="button"
            class="pressable group flex items-center gap-3 rounded-[10px] border border-line px-3 py-1.5 text-left hover:border-line-strong hover:bg-surface-2"
            :disabled="form.submitting.value"
            :data-telegram-id="person.id"
            @click="pick(person.id)"
          >
            <UserAvatar :name="person.name" :size="28" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold text-fg">{{ person.name }}</span>
              <span class="block truncate text-xs text-muted">{{ t(person.role) }} · {{ person.id }}</span>
            </span>
            <ArrowRight :size="15" class="text-subtle transition-transform group-hover:translate-x-0.5" />
          </button>
        </div>
      </section>
      <section class="mt-3" :aria-label="t('auth.dev.strangers')">
        <h2 class="mb-1.5 text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("auth.dev.strangers") }}</h2>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="person in DEMO_STRANGERS"
            :key="person.id"
            type="button"
            class="pressable rounded-full border border-line px-2.5 py-1 text-xs font-medium text-muted hover:border-line-strong hover:bg-surface-2 hover:text-fg"
            :disabled="form.submitting.value"
            :data-telegram-id="person.id"
            @click="pick(person.id)"
          >
            {{ t(person.role) }} · <span class="tabular-nums">{{ person.id }}</span>
          </button>
        </div>
      </section>

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
