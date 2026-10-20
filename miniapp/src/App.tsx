import { useEffect, useRef, useState } from "react";

import { ApiError } from "./api/client";
import { useMe, useSummary } from "./api/hooks";
import { isSuspended } from "./api/membership";
import type { Membership } from "./api/types";
import { TabBar } from "./components/TabBar";
import { FeatureBoundary, FeaturePage } from "./features/hosts";
import { features, suspendedGate } from "./features/registry";
import { asLang, I18nProvider, useI18n } from "./i18n";
import { ActivityScreen } from "./screens/Activity";
import { CreateAccount } from "./screens/CreateAccount";
import { Blocked, Declined, Failure, NoAccess, Suspended } from "./screens/Gate";
import { Home } from "./screens/Home";
import { Profile } from "./screens/Profile";
import { Splash } from "./screens/Splash";
import { TaskDetail } from "./screens/TaskDetail";
import { Tasks } from "./screens/Tasks";
import { Team } from "./screens/Team";
import { Waiting } from "./screens/Waiting";
import { Sheets } from "./sheets/Sheets";
import { initialFromLaunch } from "./state/deeplink";
import { CORE, NavigationProvider, useNavigation, type NavigationInit, type PageRef } from "./state/navigation";
import { SessionProvider, useMember, useSession } from "./state/session";
import { ToastProvider } from "./state/toast";
import { initData, onThemeChange, useBackButton } from "./telegram";
import { applyTheme, savedThemeMode } from "./theme";

const SPLASH_MS = 900;

export function App() {
  const insideTelegram = Boolean(initData());
  const me = useMe({ enabled: insideTelegram });
  // Read once at launch: `?screen=payslip:12` or a startapp parameter picks the first screen.
  const [launch] = useState<NavigationInit | null>(() => initialFromLaunch(features));
  const [splashOver, setSplashOver] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setSplashOver(true), SPLASH_MS);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => onThemeChange(() => applyTheme(savedThemeMode())), []);

  const language = asLang(
    me.data?.language ??
      window.Telegram?.WebApp?.initDataUnsafe?.user?.language_code ??
      navigator.language.slice(0, 2),
  );
  return (
    <I18nProvider lang={language}>
      <div className="app">
        <ToastProvider>
          {!insideTelegram ? (
            <Problem kind="outside" />
          ) : me.isError ? (
            <Problem kind={me.error instanceof ApiError && me.error.status === 401 ? "expired" : "network"} retry={() => void me.refetch()} />
          ) : !me.data || !splashOver ? (
            <SplashScreen />
          ) : (
            <SessionProvider me={me.data}>
              <NavigationProvider initial={launch}>
                <Gatekeeper />
              </NavigationProvider>
            </SessionProvider>
          )}
        </ToastProvider>
      </div>
    </I18nProvider>
  );
}

function SplashScreen() {
  const { t } = useI18n();
  return <Splash tagline={t("app.tagline")} />;
}

function Problem({ kind, retry }: { kind: "outside" | "expired" | "network"; retry?: () => void }) {
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

  if (!membership || status === "left") return <NoAccess />;
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

function MainApp() {
  const navigation = useNavigation();
  const member = useMember();
  const summary = useSummary(member.companyId);
  useStackBackButton();

  return (
    <>
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
        <FeatureBoundary name="gates.suspended" fallback={<Suspended />}>
          <Gate membership={membership} />
        </FeatureBoundary>
      ) : (
        <Suspended />
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
