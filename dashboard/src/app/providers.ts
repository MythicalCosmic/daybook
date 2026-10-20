/**
 * Everything the app needs before it mounts: pinia, i18n, vue-query, the HTTP layer's hooks
 * (token, language, session end, error toasts), theme and motion.
 */
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { watch, type App } from "vue";
import type { Router } from "vue-router";

import { ApiError, configureHttp, isApiError } from "@/api/http";
import { shellApi } from "@/api/shell";
import { toast } from "@/components/useToast";
import { currentLanguage, i18n, isLanguage, setLanguage, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

import { installTheme } from "./theme";

/** A sentence for any API failure, in the person's language. */
export function errorMessage(error: unknown): string {
  if (!isApiError(error)) return t("common.error.generic");
  if (error.isNetwork) return t("common.error.network");
  if (error.detail) return error.detail;
  if (error.status === 401) return t("common.error.session");
  if (error.status === 403) return t("common.error.forbidden");
  if (error.status === 404) return t("common.error.notFound");
  if (error.status === 400) return t("common.error.validation");
  if (error.status >= 500) return t("common.error.server");
  return t("common.error.generic");
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: true,
        // Retry only what can succeed later: the network and server errors, twice.
        retry: (failures, error) => failures < 2 && (!(error instanceof ApiError) || error.isNetwork || error.status >= 500),
      },
      mutations: { retry: false },
    },
  });
}

export function installProviders(app: App, router: Router): QueryClient {
  const pinia = createPinia();
  app.use(pinia);
  app.use(i18n);
  const queryClient = createQueryClient();
  app.use(VueQueryPlugin, { queryClient });

  const session = useSessionStore();
  configureHttp({
    getToken: () => session.accessToken,
    setToken: (token) => session.setAccess(token),
    getLanguage: () => currentLanguage(),
    onSessionEnded: () => {
      session.endSession();
      queryClient.clear();
      const current = router.currentRoute.value;
      if (!current.meta.public) void router.replace({ path: "/login", query: { next: current.fullPath } });
    },
    onError: (error) => {
      toast.error(errorMessage(error), { id: `api-${error.status}-${error.detail ?? ""}` });
    },
  });

  // The person's language from `me` wins over the browser guess; changing it is saved back.
  watch(
    () => session.me?.language,
    (language) => {
      if (isLanguage(language) && language !== currentLanguage()) setLanguage(language);
    },
    { immediate: true },
  );
  document.documentElement.lang = currentLanguage();

  installTheme();
  return queryClient;
}

/** Switches the UI language now and saves it on the account. */
export async function changeLanguage(language: string): Promise<void> {
  if (!isLanguage(language)) return;
  setLanguage(language);
  const session = useSessionStore();
  session.setLanguage(language);
  try {
    await shellApi.setLanguage(language);
  } catch {
    // Kept for this browser; the account keeps its old language until the next successful save.
  }
}
