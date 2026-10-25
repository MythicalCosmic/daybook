import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError } from "./api/client";
import { OfflineBanner } from "./components/OfflineBanner";
import { useMe, useSummary } from "./api/hooks";
import { isSuspended } from "./api/membership";
import type { Membership } from "./api/types";
import { TabBar } from "./components/TabBar";
import { FeatureBoundary, FeaturePage } from "./features/hosts";
import { features, suspendedGate, visibleFeatures } from "./features/registry";
import { asLang, I18nProvider, useI18n } from "./i18n";
import { ActivityScreen } from "./screens/Activity";
import { CreateAccount } from "./screens/CreateAccount";
import { Blocked, Declined, Failure, Left, NoAccess, Suspended } from "./screens/Gate";
import { Home } from "./screens/Home";
import { Profile } from "./screens/Profile";
import { Splash } from "./screens/Splash";
import { TaskDetail } from "./screens/TaskDetail";
import { Tasks } from "./screens/Tasks";
import { Team } from "./screens/Team";
import { Waiting } from "./screens/Waiting";
import { Sheets } from "./sheets/Sheets";
import { readScreenLink, resolveScreen, type ScreenLink } from "./state/deeplink";
import { CORE, NavigationProvider, useNavigation, type NavigationInit, type PageRef } from "./state/navigation";
import { SessionProvider, useMember, useSession } from "./state/session";
import { ToastProvider } from "./state/toast";
import { initData, onActivated, onThemeChange, openedWithoutSignIn, useBackButton } from "./telegram";
import { applyTheme, savedThemeMode } from "./theme";

const SPLASH_MS = 900;
const LAST_LANGUAGE = "daybook.lang";

/**
 * The language the person last used the app in. A screen without a sign-in (an old keyboard
 * button opened the app) knows nobody, so it speaks that rather than the phone's language.
 */
function lastLanguage(): string | undefined {
  try {
    return window.localStorage.getItem(LAST_LANGUAGE) ?? undefined;
  } catch {
    return undefined;
  }
}

export function App() {
  const signedIn = Boolean(initData());
  const me = useMe({ enabled: signedIn });
  // Read once at launch: `?screen=payslip:12` or a startapp parameter picks the first screen.
  const [launch] = useState<ScreenLink | null>(() => readScreenLink());
  // A link from the bot ("Open in app" on a task) goes straight there: no splash to sit through.
  const [splashOver, setSplashOver] = useState(() => launch !== null);
  useEffect(() => {
    if (splashOver) return;
    const timer = window.setTimeout(() => setSplashOver(true), SPLASH_MS);
    return () => window.clearTimeout(timer);
    // Only at launch.
  }, []);
  useEffect(() => onThemeChange(() => applyTheme(savedThemeMode())), []);
  const chosen = me.data?.language;
  useEffect(() => {
    if (!chosen) return;
    try {
      window.localStorage.setItem(LAST_LANGUAGE, chosen);
    } catch {
      // Only a convenience for the screen without a sign-in.
    }
  }, [chosen]);

  // Uzbek first: before `me` says otherwise, the language last used here, else Uzbek (never the
  // phone's or Telegram's language, which a new account doesn't take either).
  const language = asLang(chosen ?? lastLanguage() ?? "uz");
  // The page says which language it's in: screen readers, hyphenation and the time picker's
  // 24-hour clock follow it (audit M-4).
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);
  return (
    <I18nProvider lang={language}>
      <div className="app">
        <ToastProvider>
          {!signedIn ? (
            // Inside Telegram without a sign-in, a keyboard button opened the app: say which
            // button does sign in. Outside Telegram (a browser), say where the app lives.
            <Problem kind={openedWithoutSignIn() ? "unsigned" : "outside"} />
          ) : me.isError ? (
            <Problem kind={me.error instanceof ApiError && me.error.status === 401 ? "expired" : "network"} retry={() => void me.refetch()} />
          ) : !me.data || !splashOver ? (
            <SplashScreen />
          ) : (
            <SessionProvider me={me.data}>
              <LaunchNavigation link={launch}>
                <Gatekeeper />
              </LaunchNavigation>
            </SessionProvider>
          )}
        </ToastProvider>
      </div>
    </I18nProvider>
  );
}

/**
 * The navigation, started where the launch link points. It resolves once the membership is
 * known, so only features this person sees can take a built-in link over (§9.1 `replaces`).
 */
function LaunchNavigation({ link, children }: { link: ScreenLink | null; children: ReactNode }) {
  const { membership } = useSession();
  const [initial] = useState<NavigationInit | null>(() => {
    if (!link) return null;
    const member = membership && { ...membership, timeZone: membership.company.timezone, companyId: membership.company.id };
    return resolveScreen(link, features, member ? visibleFeatures(features, { member, summary: undefined }) : features);
  });
  return <NavigationProvider initial={initial}>{children}</NavigationProvider>;
}

function SplashScreen() {
  const { t } = useI18n();
  return <Splash tagline={t("app.tagline")} />;
}

function Problem({ kind, retry }: { kind: "outside" | "unsigned" | "expired" | "network"; retry?: () => void }) {
  return <Failure kind={kind} onRetry={kind === "network" ? retry : undefined} />;
}

/** Decides what the person may see: account creation, the waiting room, or the app. */
function Gatekeeper() {
  const { membership } = useSession();
  const status = membership?.status;
  const waiting = status === "pending" && membership?.is_onboarded === true;
  useMe({ poll: waiting }); // the approval lands without a reload
  const [celebrating, setCelebrating] = useState(false);
  const wasWaiting = useRef(waiting);
  useEffect(() => {
    if (wasWaiting.current && status === "approved") setCelebrating(true);
    wasWaiting.current = waiting;
  }, [status, waiting]);

  if (!membership) return <NoAccess />;
  if (status === "left") return <Left membership={membership} />;
  if (status === "rejected") return <Declined membership={membership} />;
  if (status === "blocked") return <Blocked />;
  if (isSuspended(membership)) return <PausedApp membership={membership} />;
  if (!membership.is_onboarded) return <CreateAccount membership={membership} />;
  if (status === "pending" || celebrating) {
    return <Waiting membership={membership} onOpen={() => setCelebrating(false)} />;
  }
  return <MainApp />;
}

/** Telegram's back button closes a sheet first, then the page on top (an open task, a page). */
function useStackBackButton() {
  const { sheet, stack, closeSheet, pop } = useNavigation();
  const back = sheet ? closeSheet : stack.length ? pop : null;
  useEffect(() => useBackButton(back), [back]);
}

/**
 * Back in the app after a while in the chat (Telegram's "activated"), everything shown is fetched
 * again: a manager's confirm or return made meanwhile shows at once (audit M-14).
 */
function useRefreshOnReturn(company: number) {
  const client = useQueryClient();
  useEffect(
    () =>
      onActivated(() => {
        void client.invalidateQueries({ queryKey: ["tasks", company] });
        void client.invalidateQueries({ queryKey: ["summary", company] });
        void client.invalidateQueries({ queryKey: ["activity", company] });
      }),
    [client, company],
  );
}

function MainApp() {
  const navigation = useNavigation();
  const member = useMember();
  const summary = useSummary(member.companyId);
  useStackBackButton();
  useRefreshOnReturn(member.companyId);

  return (
    <>
      <OfflineBanner />
      {navigation.tab === "home" && <Home />}
      {navigation.tab === "tasks" && <Tasks />}
      {navigation.tab === "activity" && <ActivityScreen />}
      {navigation.tab === "profile" && <Profile />}
      {/* Pages cover the tabs, each over the last; an open task brings its own action bar. */}
      <StackPages />
      {navigation.stack.length === 0 && <TabBar unread={summary.data?.unread_activity ?? 0} />}
      <Sheets />
    </>
  );
}

/**
 * A suspended person: the lifecycle feature's "Access paused" screen when it exists (it may open
 * the pages they keep, such as pay and documents), otherwise a calm built-in message.
 */
function PausedApp({ membership }: { membership: Membership }) {
  const Gate = suspendedGate(features);
  useStackBackButton();
  return (
    <>
      {Gate ? (
        <FeatureBoundary name="gates.suspended" fallback={<Suspended membership={membership} />}>
          <Gate membership={membership} />
        </FeatureBoundary>
      ) : (
        <Suspended membership={membership} />
      )}
      <StackPages />
      <Sheets />
    </>
  );
}

function StackPages() {
  const { stack } = useNavigation();
  return (
    <>
      {stack.map((page, index) => (
        <StackPage key={pageKey(page, index)} page={page} />
      ))}
    </>
  );
}

function pageKey({ feature, page, params }: PageRef, index: number): string {
  return `${index}:${feature}:${page}:${params ? JSON.stringify(params) : ""}`;
}

/** One page of the navigation stack: the app's own (a task, team results) or a feature's. */
function StackPage({ page }: { page: PageRef }) {
  const { membership } = useSession();
  if (page.feature === CORE) {
    if (page.page === "task") return <TaskDetail taskId={Number(page.params?.id)} />;
    // Me shows team results only with reports.view; a deep link must not get around that.
    if (page.page === "team" && membership?.permissions.includes("reports.view")) return <Team />;
    return <FeaturePage feature={page.feature} page={page.page} params={page.params ?? {}} />;
  }
  return <FeaturePage feature={page.feature} page={page.page} params={page.params ?? {}} />;
}
