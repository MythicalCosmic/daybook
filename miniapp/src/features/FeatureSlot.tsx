import { Fragment, Suspense, type ReactNode } from "react";

import { useI18n, type Key } from "../i18n";
import { featureText } from "../i18n/feature";
import { useNavigation } from "../state/navigation";
import { haptic } from "../telegram";
import { renderIcon } from "../ui/icon";
import { ListRow } from "../ui/ListRow";
import { FeatureBoundary, openTarget, useFeatureContext } from "./hosts";
import {
  features,
  homeSlots,
  meItemsByGroup,
  ME_GROUPS,
  plusActions,
  type Feature,
  type FeatureContext,
  type MeGroup,
  type MeItem,
  type MeItemStatus,
  type Placed,
  type PlusAction,
} from "./registry";

type Props =
  | { name: "home.hero" | "home.cards" }
  /** `builtIns`: the app's own rows for a group (Team results); feature rows follow them. */
  | { name: "me.items"; builtIns?: Partial<Record<MeGroup, ReactNode>> }
  | { name: "plus.actions" };

const GROUP_LABEL: Record<MeGroup, Key> = {
  money: "me.group.money",
  work: "me.group.work",
  documents: "me.group.documents",
  team: "profile.teamSection",
};

const NO_ITEMS = Object.fromEntries(ME_GROUPS.map((group) => [group, []])) as unknown as Record<
  MeGroup,
  Placed<MeItem<string, string, string>>[]
>;

/**
 * Where feature folders appear: `home.hero` (top of Home), `home.cards` (after Home's banners),
 * `me.items` (grouped rows on Me) and `plus.actions` (quick actions in the + sheet). With no
 * feature folders it renders only the built-in rows it was given, exactly as before.
 */
export function FeatureSlot(props: Props) {
  // Branching on a module constant keeps the hook order stable.
  if (features.length === 0) return props.name === "me.items" ? <MeGroups builtIns={props.builtIns} placed={NO_ITEMS} /> : null;
  return <FeatureSlotHost {...props} />;
}

function FeatureSlotHost(props: Props) {
  const context = useFeatureContext();
  switch (props.name) {
    case "home.hero":
    case "home.cards":
      return (
        <>
          {homeSlots(features, props.name, context).map(({ feature, item }) => (
            <FeatureBoundary key={`${feature.id}.${item.id}`} name={`${feature.id}.${item.id}`}>
              <Suspense fallback={null}>
                <item.component member={context.member} summary={context.summary} />
              </Suspense>
            </FeatureBoundary>
          ))}
        </>
      );
    case "me.items":
      return <MeGroups builtIns={props.builtIns} placed={meItemsByGroup(features, context)} context={context} />;
    case "plus.actions":
      return <PlusActions placed={plusActions(features, context)} />;
  }
}

function MeGroups({
  builtIns = {},
  placed,
  context,
}: {
  builtIns?: Partial<Record<MeGroup, ReactNode>>;
  placed: Record<MeGroup, Placed<MeItem<string, string, string>>[]>;
  context?: FeatureContext;
}) {
  const { t } = useI18n();
  return (
    <>
      {ME_GROUPS.map((group) => {
        const builtIn = builtIns[group];
        const items = placed[group];
        if (!builtIn && !items.length) return null;
        return (
          <Fragment key={group}>
            <div className="section-head section-head--small">{t(GROUP_LABEL[group])}</div>
            <div className="card list-card">
              {builtIn}
              {context &&
                items.map(({ feature, item }) => (
                  <FeatureBoundary key={`${feature.id}.${item.id}`} name={`${feature.id}.${item.id}`}>
                    <MeRow feature={feature} item={item} context={context} />
                  </FeatureBoundary>
                ))}
            </div>
          </Fragment>
        );
      })}
    </>
  );
}

const noStatus = (): MeItemStatus => ({});

function MeRow({ feature, item, context }: { feature: Feature; item: MeItem<string, string, string>; context: FeatureContext }) {
  const { lang } = useI18n();
  const navigation = useNavigation();
  // Each row is its own component, so a feature's status hook always runs in the same place.
  const useStatus = item.useStatus ?? noStatus;
  const status = useStatus(context);
  return (
    <ListRow
      icon={item.icon}
      title={featureText(feature.messages, lang, item.label)}
      value={status.value}
      badge={status.badge}
      onClick={() => openTarget(navigation, feature, item.to)}
    />
  );
}

function PlusActions({ placed }: { placed: Placed<PlusAction<string, string, string>>[] }) {
  const { t, lang } = useI18n();
  const navigation = useNavigation();
  if (!placed.length) return null;
  return (
    <div className="field">
      <span className="field-label">{t("plus.title")}</span>
      <div className="ui-plus-actions">
        {placed.map(({ feature, item }) => (
          <button
            key={`${feature.id}.${item.id}`}
            type="button"
            className="ui-plus-action"
            onClick={() => {
              haptic();
              openTarget(navigation, feature, item.to);
            }}
          >
            <span className="circle">{renderIcon(item.icon, 21)}</span>
            <span>{featureText(feature.messages, lang, item.label)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
