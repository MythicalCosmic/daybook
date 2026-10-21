/**
 * Who may run a till, checked before any till page or sheet loads: someone without
 * `sales.operate` who opens a Kassa link (the bot's menu button, an old notification) sees why
 * at once, and the app never asks the server for a till it would refuse. Cash handed to them
 * still shows on the Kassa page, because answering it needs no permission.
 */
import { Lock } from "lucide-react";
import type { ComponentType } from "react";

import { can } from "../../api/permissions";
import { useNavigation } from "../../state/navigation";
import { useMember, type Member } from "../../state/session";
import { EmptyState, PageHeader, Screen } from "../../ui";
import type { PageProps, SheetProps } from "../registry";
import { useKassaT } from "./lib";
import { ReceivedList } from "./Received";

/** The till itself: cashiers and whoever else may run one. */
export const runsTill = (member: Member) => can(member, "sales.operate");

function NoTill({ compact = false }: { compact?: boolean }) {
  const t = useKassaT();
  return <EmptyState compact={compact} icon={Lock} tone="sage" title={t("denied.title")} body={t("denied.body")} />;
}

function NoTillPage({ withReceived }: { withReceived: boolean }) {
  const t = useKassaT();
  const navigation = useNavigation();
  return (
    <Screen variant="detail">
      <PageHeader title={t("kassa")} onBack={navigation.pop} />
      {withReceived && <ReceivedList />}
      <NoTill />
    </Screen>
  );
}

/** A till page, shown only to people who run a till; `withReceived` keeps cash handed to them. */
export function tillPage(Page: ComponentType<PageProps>, { withReceived = false } = {}): ComponentType<PageProps> {
  return function TillPage(props: PageProps) {
    const member = useMember();
    return runsTill(member) ? <Page {...props} /> : <NoTillPage withReceived={withReceived} />;
  };
}

/** A till sheet (payout, handover…), shown only to people who run a till. */
export function tillSheet(Sheet: ComponentType<SheetProps>): ComponentType<SheetProps> {
  return function TillSheet(props: SheetProps) {
    const member = useMember();
    return runsTill(member) ? <Sheet {...props} /> : <NoTill compact />;
  };
}
