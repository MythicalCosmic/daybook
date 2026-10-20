import { ArrowLeft, SearchX, TriangleAlert } from "lucide-react";
import { Component, Suspense, type ErrorInfo, type ReactNode } from "react";

import { useSummary } from "../api/hooks";
import { useI18n } from "../i18n";
import { CORE, useNavigation, type Navigation, type Params } from "../state/navigation";
import { useMember } from "../state/session";
import { EmptyState } from "../ui/EmptyState";
import { Screen } from "../ui/Layout";
import { ScreenSkeleton } from "../ui/Skeleton";
import {
  featureVisible,
  features,
  findFeature,
  findPage,
  findSheet,
  replacedEntries,
  type BuiltIn,
  type Feature,
  type FeatureContext,
  type Open,
} from "./registry";

/** Keeps one feature's crash inside its own box: the rest of the screen carries on. */
export class FeatureBoundary extends Component<{ name: string; fallback?: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error(`Feature "${this.props.name}" failed`, error, info.componentStack);
  }

  render(): ReactNode {
    return this.state.failed ? (this.props.fallback ?? null) : this.props.children;
  }
}

/** The person and today's numbers, as every slot receives them. */
export function useFeatureContext(): FeatureContext {
  const member = useMember();
  const summary = useSummary(member.companyId);
  return { member, summary: summary.data };
}

const NONE: ReadonlySet<BuiltIn> = new Set();

/**
 * Built-in entries a visible feature takes over for this person. With no feature folders the
 * answer is fixed, so screens pay nothing (the branch is on a module constant).
 */
export function useReplacedEntries(): ReadonlySet<BuiltIn> {
  // Calling a hook after this early return is safe: `features` never changes at runtime.
  if (features.length === 0) return NONE;
  return useReplacedFromFeatures();
}

function useReplacedFromFeatures(): ReadonlySet<BuiltIn> {
  const context = useFeatureContext();
  return replacedEntries(features, context);
}

/** The app's own sheets a feature may open by name (`{feature: "core", sheet: "add"}`). */
const CORE_SHEETS = ["add", "language", "company", "timeOff"] as const;

/** Open where a Me row or (+) action leads: the feature's own page or sheet, or any other one. */
export function openTarget(navigation: Navigation, feature: Feature, open: Open<string, string>): void {
  const owner = open.feature ?? feature.id;
  if ("page" in open) {
    navigation.push({ feature: owner, page: open.page, params: open.params });
    return;
  }
  const core = CORE_SHEETS.find((kind) => kind === open.sheet);
  if (owner === CORE && core) navigation.openSheet({ kind: core });
  else navigation.openSheet({ kind: "feature", feature: owner, sheet: open.sheet, params: open.params });
}

function NotFound({ onBack }: { onBack: () => void }) {
  const { t } = useI18n();
  return (
    <div className="ui-page-center">
      <EmptyState
        icon={SearchX}
        tone="sage"
        title={t("ui.notFound.title")}
        body={t("ui.notFound.body")}
        action={{ label: t("ui.notFound.back"), onClick: onBack, icon: ArrowLeft }}
      />
    </div>
  );
}

/** What a feature's page or sheet shows when its code crashed ("not found" would mislead). */
function Failed({ onBack }: { onBack?: () => void }) {
  const { t } = useI18n();
  const state = (
    <EmptyState
      icon={TriangleAlert}
      compact={!onBack}
      title={t("ui.failed.title")}
      body={t("ui.failed.body")}
      action={onBack ? { label: t("ui.notFound.back"), onClick: onBack, icon: ArrowLeft } : undefined}
    />
  );
  return onBack ? <div className="ui-page-center">{state}</div> : state;
}

type Access = "open" | "hidden" | "checking";

/**
 * Whether this person may see a feature's pages and sheets: the same `visible` rule that hides
 * its rows and cards, so a deep link or another feature's button can't open a page that isn't
 * theirs (someone else's till, a module the company switched off). A rule that reads today's
 * numbers can't say no before they arrive, so that wait shows a skeleton.
 */
function useFeatureAccess(id: string): Access {
  const member = useMember();
  const summary = useSummary(member.companyId);
  const feature = findFeature(features, id);
  if (!feature) return "hidden";
  if (featureVisible(feature, { member, summary: summary.data })) return "open";
  return summary.isPending ? "checking" : "hidden";
}

/** A feature page on the navigation stack: its own layer, a skeleton while the code loads. */
export function FeaturePage({ feature, page, params }: { feature: string; page: string; params: Params }) {
  const navigation = useNavigation();
  const access = useFeatureAccess(feature);
  const Page = findPage(features, { feature, page });
  const loading = (
    <Screen variant="detail">
      <ScreenSkeleton variant="detail" delay={150} />
    </Screen>
  );
  return (
    <div className="detail-layer">
      {access === "checking" ? (
        loading
      ) : Page && access === "open" ? (
        <FeatureBoundary
          name={`${feature}.${page}`}
          fallback={
            <Screen variant="detail">
              <Failed onBack={navigation.pop} />
            </Screen>
          }
        >
          <Suspense fallback={loading}>
            <Page params={params} />
          </Suspense>
        </FeatureBoundary>
      ) : (
        <Screen variant="detail">
          <NotFound onBack={navigation.pop} />
        </Screen>
      )}
    </div>
  );
}

/** A feature sheet inside the shared bottom sheet. */
export function FeatureSheet({ feature, sheet, params }: { feature: string; sheet: string; params: Params }) {
  const navigation = useNavigation();
  const { t } = useI18n();
  const access = useFeatureAccess(feature);
  const Body = findSheet(features, feature, sheet);
  if (access === "checking") return <ScreenSkeleton variant="detail" delay={150} />;
  if (!Body || access === "hidden") return <EmptyState compact icon={SearchX} tone="sage" title={t("ui.notFound.title")} body={t("ui.notFound.body")} />;
  return (
    <FeatureBoundary name={`${feature}.${sheet}`} fallback={<Failed />}>
      <Suspense fallback={<ScreenSkeleton variant="detail" delay={150} />}>
        <Body params={params} close={navigation.closeSheet} />
      </Suspense>
    </FeatureBoundary>
  );
}
