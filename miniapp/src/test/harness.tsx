/**
 * Rendering a screen or sheet the way the app does (query cache, language, toasts, the signed-in
 * person, navigation and the sheets layer), for tests that mock `api` from `../api/client`.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

import type { Me, Membership, Task } from "../api/types";
import { I18nProvider, LOCALES, translate, type Lang } from "../i18n";
import type { ViewContext } from "../lib/taskView";
import { Sheets } from "../sheets/Sheets";
import { NavigationProvider, useNavigation, type NavigationInit } from "../state/navigation";
import { SessionProvider } from "../state/session";
import { ToastProvider } from "../state/toast";

export const NOW = new Date("2026-10-21T10:00:00+05:00");

export function ctxFor(lang: Lang = "en", now: Date = NOW): ViewContext {
  return { t: (key, vars) => translate(lang, key, vars), timeZone: "Asia/Tashkent", locale: LOCALES[lang], now };
}

export function membership(fields: Partial<Membership> & { companyId?: number; companyName?: string } = {}): Membership {
  const { companyId = 1, companyName = "Demo Dorixona", ...rest } = fields;
  return {
    id: 7,
    company: { id: companyId, name: companyName, timezone: "Asia/Tashkent" },
    status: "approved",
    first_name: "Alisher",
    last_name: "Valiyev",
    position: null,
    role: "Employee",
    permissions: [],
    is_onboarded: true,
    onboarded_at: "2026-01-01T00:00:00Z",
    decided_at: null,
    rejoin_available_at: null,
    ...rest,
  } as unknown as Membership;
}

export function person(memberships: Membership[] = [membership()], language: Lang = "en"): Me {
  return {
    id: 1,
    telegram_id: 4242,
    telegram_username: "",
    first_name: memberships[0]?.first_name ?? "Alisher",
    last_name: memberships[0]?.last_name ?? "Valiyev",
    phone: "",
    language,
    memberships,
  } as unknown as Me;
}

let ids = 500;

export function makeTask(fields: Partial<Task> = {}): Task {
  ids += 1;
  return {
    id: ids,
    kind: "assigned",
    routine: null,
    title: "Count the till",
    description: "",
    status: "todo",
    priority: "normal",
    due_at: "2026-10-21T18:00:00+05:00",
    for_date: null,
    proof: "none",
    needs_confirmation: false,
    proof_text: "",
    proof_photo: null,
    proof_thumb: null,
    reward: null,
    assignee: { id: 7, name: "Alisher Valiyev", position: null },
    created_by: { id: 3, name: "Bekzod Mirzayev", position: "Head" },
    checklist: [],
    card: null,
    reminder: null,
    repeat_weekdays: null,
    started_at: null,
    completed_at: null,
    confirmed_at: null,
    confirmed_by: null,
    is_overdue: false,
    actions: ["start", "complete"],
    created_at: "2026-10-21T08:00:00+05:00",
    ...fields,
  } as unknown as Task;
}

/** Shows where navigation is, for assertions ("the sheet that opened"). */
export function NavigationProbe() {
  const navigation = useNavigation();
  return (
    <div data-testid="navigation" hidden>
      {JSON.stringify({ tab: navigation.tab, tasksTab: navigation.tasksTab, sheet: navigation.sheet, stack: navigation.stack })}
    </div>
  );
}

export function renderApp(
  node: ReactNode,
  options: { me?: Me; lang?: Lang; init?: NavigationInit; seed?: (client: QueryClient) => void } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } } });
  options.seed?.(client);
  const result = render(
    <QueryClientProvider client={client}>
      <I18nProvider lang={options.lang ?? "en"}>
        <ToastProvider>
          <SessionProvider me={options.me ?? person()}>
            <NavigationProvider initial={options.init ?? null}>
              {node}
              <Sheets />
              <NavigationProbe />
            </NavigationProvider>
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { client, ...result };
}

export function navigationState(container: HTMLElement = document.body): {
  tab: string;
  tasksTab: string;
  sheet: unknown;
  stack: { feature: string; page: string; params?: Record<string, unknown> }[];
} {
  return JSON.parse(container.querySelector('[data-testid="navigation"]')?.textContent ?? "{}");
}
