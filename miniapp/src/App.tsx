import { useQueryClient } from "@tanstack/react-query";
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError } from "./api/client";
import { OfflineBanner } from "./components/OfflineBanner";
import { prefetchHome, refreshWork, useMe, useSummary } from "./api/hooks";
import { isSuspended } from "./api/membership";
import type { Membership } from "./api/types";
import { TabBar } from "./components/TabBar";
import { FeatureBoundary, FeaturePage } from "./features/hosts";
import { features, suspendedGate, visibleFeatures } from "./features/registry";
import { asLang, I18nProvider, useI18n } from "./i18n";
import { lazyScreen, whenIdle } from "./lib/lazy";
import { closeUnlessDraft } from "./lib/useDraftGuard";
import { ActivityScreen } from "./screens/Activity";
import { Blocked, Declined, Failure, Left, NoAccess, Suspended } from "./screens/Gate";
import { Home } from "./screens/Home";
import { Splash } from "./screens/Splash";
import { Tasks } from "./screens/Tasks";
import { Sheets } from "./sheets/Sheets";
import { readScreenLink, resolveScreen, type ScreenLink } from "./state/deeplink";
import { CORE, NavigationProvider, useNavigation, type NavigationInit, type PageRef } from "./state/navigation";
import { SessionProvider, startingCompany, useMember, useSession } from "./state/session";
import { ToastProvider } from "./state/toast";
import { initData, onActivated, onThemeChange, openedWithoutSignIn, useBackButton } from "./telegram";
import { applyTheme, savedThemeMode } from "./theme";
import { Screen, ScreenSkeleton } from "./ui";

const SPLASH_MS = 900;
const LAST_LANGUAGE = "daybook.lang";

// Loaded when first opened, so Home's code comes first: the task screen and Me are fetched as
// soon as the browser is idle (a task from a bot link at once), the rest when someone opens them.
const TaskDetail = lazyScreen(() => import("./screens/TaskDetail").then((m) => ({ default: m.TaskDetail })));
const Profile = lazyScreen(() => import("./screens/Profile").then((m) => ({ default: m.Profile })));
const Team = lazyScreen(() => import("./screens/Team").then((m) => ({ default: m.Team })));
const MyTeam = lazyScreen(() => import("./screens/MyTeam").then((m) => ({ default: m.MyTeam })));
const TeamPerson = lazyScreen(() => import("./screens/TeamPerson").then((m) => ({ default: m.TeamPerson })));
const CreateAccount = lazyScreen(() => import("./screens/CreateAccount").then((m) => ({ default: m.CreateAccount })));
const Waiting = lazyScreen(() => import("./screens/Waiting").then((m) => ({ default: m.Waiting })));

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
  // A link from the bot ("Open in app" on a task) goes straight there: no splash to sit through,
  // and the task screen's code is fetched while the app signs in.
  const [splashOver, setSplashOver] = useState(() => {
    if (launch?.name === "task") void TaskDetail.preload();
    return launch !== null;
  });
  useEffect(() => {
    if (splashOver) return;
    const timer = window.setTimeout(() => setSplashOver(true), SPLASH_MS);
    return () => window.clearTimeout(timer);
    // Only at launch.
  }, []);
  useEffect(() => onThemeChange(() => applyTheme(savedThemeMode())), []);
  // Home's numbers and lists start loading while the splash is still up (it opens with them);
  // a launch link opens another screen first, which fetches its own.
  const client = useQueryClient();
  const homeCompany = me.data && !launch ? startingCompany(me.data) : null;
  useEffect(() => {
    if (homeCompany !== null) prefetchHome(client, homeCompany);
  }, [client, homeCompany]);
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
            <Problem kind={launchFailure(me.error)} retry={() => void me.refetch()} />
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

type ProblemKind = "outside" | "unsigned" | "expired" | "network" | "server";

/** Why signing in failed: the session ran out, the server answered with an error, or nothing came back. */
function launchFailure(error: unknown): ProblemKind {
  if (!(error instanceof ApiError)) return "network";
  return error.status === 401 ? "expired" : "server";
}

function Problem({ kind, retry }: { kind: ProblemKind; retry?: () => void }) {
  return <Failure kind={kind} onRetry={kind === "network" || kind === "server" ? retry : undefined} />;
}

/** Decides what the person may see: account creation, the waiting room, or the app. */
function Gatekeeper() {
  const { membership } = useSession();
  const status = membership?.status;
  const waiting = status === "pending" && membership?.is_onboarded === true;
  const creating = membership != null && !membership.is_onboarded;
  const byLink = membership?.joined_by_link === true;
  useMe({ poll: waiting }); // the approval lands without a reload
  const [celebrating, setCelebrating] = useState(false);
  const wasWaiting = useRef(waiting);
  const wasCreating = useRef(creating);
  useEffect(() => {
    // Approved while waiting, or let in by a team link the moment the account was made.
    if (status === "approved" && (wasWaiting.current || (wasCreating.current && byLink))) setCelebrating(true);
    wasWaiting.current = waiting;
    wasCreating.current = creating;
  }, [status, waiting, creating, byLink]);

  if (!membership) return <NoAccess />;
  if (status === "left") return <Left membership={membership} />;
  if (status === "rejected") return <Declined membership={membership} />;
  if (status === "blocked") return <Blocked />;
  if (isSuspended(membership)) return <PausedApp membership={membership} />;
  if (!membership.is_onboarded) {
    return (
      <Suspense fallback={<SplashScreen />}>
        <CreateAccount membership={membership} />
      </Suspense>
    );
  }
  if (status === "pending" || celebrating) {
    return (
      <Suspense fallback={<SplashScreen />}>
        <Waiting membership={membership} onOpen={() => setCelebrating(false)} />
      </Suspense>
    );
  }
  return <MainApp />;
}

/** The screens a person is likely to open next, fetched once the browser is idle. */
function usePreloadNext(member: { heads?: readonly string[] | null; permissions: readonly string[] }) {
  const heads = (member.heads?.length ?? 0) > 0;
  const reports = member.permissions.includes("reports.view");
  useEffect(
    () =>
      whenIdle(() => {
        void TaskDetail.preload();
        void Profile.preload();
        if (heads) {
          void MyTeam.preload();
          void TeamPerson.preload();
        }
        if (reports) void Team.preload();
      }),
    [heads, reports],
  );
}

/**
 * Telegram's back button closes a sheet first (asking first when it holds a draft), then the page
 * on top (an open task, a page).
 */
function useStackBackButton() {
  const { sheet, stack, closeSheet, pop } = useNavigation();
  const { t } = useI18n();
  const question = t("sheet.discardAsk");
  const back = useMemo(
    () => (sheet ? () => void closeUnlessDraft(closeSheet, question) : stack.length ? pop : null),
    [sheet, stack.length, closeSheet, pop, question],
  );
  useEffect(() => useBackButton(back), [back]);
}

/**
 * Back in the app after a while in the chat (Telegram's "activated"), everything shown is fetched
 * again: a manager's confirm or return made meanwhile shows at once (audit M-14).
 */
function useRefreshOnReturn(company: number) {
  const client = useQueryClient();
  // The webview's own focus refetch may have started the same requests a moment earlier: those
  // carry on rather than being cancelled and sent again.
  useEffect(() => onActivated(() => void refreshWork(client, company, { cancelRefetch: false })), [client, company]);
}

/**
 * Whether the tab under the pages is drawn. A link that opens the app straight onto a page (a task
 * from the bot) leaves the tab out until the person goes back to it: Home's dozen requests would
 * otherwise race the one the page needs, for a screen nobody sees yet.
 */
function useTabShown(covered: boolean): boolean {
  const [shown, setShown] = useState(!covered);
  if (!shown && !covered) setShown(true);
  return shown;
}

function MainApp() {
  const navigation = useNavigation();
  const member = useMember();
  const summary = useSummary(member.companyId);
  const tabShown = useTabShown(navigation.stack.length > 0);
  useStackBackButton();
  useRefreshOnReturn(member.companyId);
  usePreloadNext(member);

  return (
    <>
      <OfflineBanner />
      {tabShown && navigation.tab === "home" && <Home />}
      {tabShown && navigation.tab === "tasks" && <Tasks />}
      {tabShown && navigation.tab === "activity" && <ActivityScreen />}
      {tabShown && navigation.tab === "profile" && (
        <Suspense fallback={<TabPlaceholder />}>
          <Profile />
        </Suspense>
      )}
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
        // A page whose code is still on its way shows the page placeholder, over the tab as usual.
        <Suspense key={pageKey(page, index)} fallback={<PagePlaceholder />}>
          <StackPage page={page} />
        </Suspense>
      ))}
    </>
  );
}

function PagePlaceholder() {
  return (
    <div className="detail-layer">
      <Screen variant="detail">
        <ScreenSkeleton variant="detail" delay={150} />
      </Screen>
    </div>
  );
}

function TabPlaceholder() {
  return (
    <Screen>
      <ScreenSkeleton variant="hero" delay={150} />
    </Screen>
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
    // A head's My team; the server checks headship again on every request.
    if (page.page === "myTeam" && (membership?.heads?.length ?? 0) > 0) return <MyTeam />;
    if (page.page === "teamPerson" && (membership?.heads?.length ?? 0) > 0) return <TeamPerson memberId={Number(page.params?.id)} />;
    return <FeaturePage feature={page.feature} page={page.page} params={page.params ?? {}} />;
  }
  return <FeaturePage feature={page.feature} page={page.page} params={page.params ?? {}} />;
}
