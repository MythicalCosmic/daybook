import { useEffect, useRef, useState } from "react";

import { ApiError } from "./api/client";
import { useMe, useSummary } from "./api/hooks";
import { TabBar } from "./components/TabBar";
import { asLang, I18nProvider, useI18n } from "./i18n";
import { ActivityScreen } from "./screens/Activity";
import { CreateAccount } from "./screens/CreateAccount";
import { Blocked, Declined, Failure, NoAccess } from "./screens/Gate";
import { Home } from "./screens/Home";
import { Profile } from "./screens/Profile";
import { Splash } from "./screens/Splash";
import { TaskDetail } from "./screens/TaskDetail";
import { Tasks } from "./screens/Tasks";
import { Waiting } from "./screens/Waiting";
import { Sheets } from "./sheets/Sheets";
import { NavigationProvider, useNavigation } from "./state/navigation";
import { SessionProvider, useMember, useSession } from "./state/session";
import { ToastProvider } from "./state/toast";
import { initData, onThemeChange, useBackButton } from "./telegram";
import { applyTheme, savedThemeMode } from "./theme";

const SPLASH_MS = 900;

export function App() {
  const insideTelegram = Boolean(initData());
  const me = useMe({ enabled: insideTelegram });
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
              <NavigationProvider>
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
  if (!membership.is_onboarded) return <CreateAccount membership={membership} />;
  if (status === "pending" || celebrating) {
    return <Waiting membership={membership} onOpen={() => setCelebrating(false)} />;
  }
  return <MainApp />;
}

function MainApp() {
  const navigation = useNavigation();
  const member = useMember();
  const summary = useSummary(member.companyId);
  const { sheet, taskId, closeSheet, closeTask } = navigation;

  // Telegram's back button closes a sheet first, then an open task.
  useEffect(() => useBackButton(sheet ? closeSheet : taskId !== null ? closeTask : null), [sheet, taskId, closeSheet, closeTask]);

  return (
    <>
      {navigation.tab === "home" && <Home />}
      {navigation.tab === "tasks" && <Tasks />}
      {navigation.tab === "activity" && <ActivityScreen />}
      {navigation.tab === "profile" && <Profile />}
      {/* An open task covers the tabs and brings its own action bar, as in the design. */}
      {taskId === null ? (
        <TabBar unread={summary.data?.unread_activity ?? 0} />
      ) : (
        <TaskDetail key={taskId} taskId={taskId} />
      )}
      <Sheets />
    </>
  );
}
