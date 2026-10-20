import { Component, Suspense, type ErrorInfo, type ReactNode } from "react";

import { useSummary } from "../api/hooks";
import { useI18n } from "../i18n";
import { CORE, useNavigation, type Navigation, type Params } from "../state/navigation";
import { useMember } from "../state/session";
import { EmptyState } from "../ui/EmptyState";
import { Screen } from "../ui/Layout";
import { ScreenSkeleton } from "../ui/Skeleton";
import {
  features,
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
  return <EmptyState title={t("ui.notFound.title")} body={t("ui.notFound.body")} action={{ label: t("ui.notFound.back"), onClick: onBack }} />;
}

/** A feature page on the navigation stack: its own layer, a skeleton while the code loads. */
export function FeaturePage({ feature, page, params }: { feature: string; page: string; params: Params }) {
  const navigation = useNavigation();
  const Page = findPage(features, { feature, page });
  return (
    <div className="detail-layer">
      {Page ? (
        <FeatureBoundary
          name={`${feature}.${page}`}
          fallback={
            <Screen variant="detail">
              <NotFound onBack={navigation.pop} />
            </Screen>
          }
        >
          <Suspense
            fallback={
              <Screen variant="detail">
                <ScreenSkeleton variant="detail" delay={150} />
              </Screen>
            }
          >
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
  const Body = findSheet(features, feature, sheet);
  if (!Body) return <EmptyState compact title={t("ui.notFound.title")} body={t("ui.notFound.body")} />;
  return (
    <FeatureBoundary name={`${feature}.${sheet}`}>
      <Suspense fallback={<ScreenSkeleton variant="detail" delay={150} />}>
        <Body params={params} close={navigation.closeSheet} />
      </Suspense>
    </FeatureBoundary>
  );
}
