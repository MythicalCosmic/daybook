import { BookOpenCheck, CheckCheck } from "lucide-react";
import { useMemo } from "react";

import type { PageProps } from "../registry";
import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Badge, Banner, BottomBar, ListCard, ListRow, PageHeader, Screen, ScreenSkeleton, SectionHead } from "../../ui";
import { useAcknowledge, useKbPage } from "./api";
import "./knowledge.css";
import { messages } from "./messages";
import { safeHtml } from "./safeHtml";

/** Reading a page, and confirming it with "I've read it" when the page asks for it. */
export function PageReader({ params }: PageProps) {
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const id = Number(params.id);
  const page = useKbPage(member.companyId, id);
  const ack = useAcknowledge(member.companyId, id);
  const body = useMemo(() => safeHtml(page.data?.body ?? ""), [page.data?.body]);

  if (!page.data) {
    return (
      <Screen variant="detail">
        <ScreenSkeleton variant="detail" delay={150} />
      </Screen>
    );
  }
  const data = page.data;
  const mustConfirm = data.require_ack && !data.my_ack?.current;
  const confirm = () =>
    ack.mutate(undefined, {
      onSuccess: () => {
        haptic.notify("success");
        toast(t("read.done"), { tone: "success" });
      },
      onError: () => {
        haptic.notify("error");
        toast(t("read.failed"), { tone: "error" });
      },
    });

  return (
    <>
      <Screen variant="detail">
        <PageHeader
          kicker={`${data.space.icon} ${data.space.name}`.trim()}
          title={`${data.emoji ? `${data.emoji} ` : ""}${data.title}`}
          subtitle={
            <span className="kbm-meta">
              {data.require_ack && <Badge tone="accent" size="small">{t("mustRead")}</Badge>}
              <span>
                {t("version", { version: data.version })} · {t("updated", { date: dayMonth(data.updated_at, member.timeZone, locale) })}
              </span>
            </span>
          }
          onBack={navigation.pop}
        />
        {mustConfirm ? (
          <Banner tone="accent" icon={BookOpenCheck} title={t("read.ask")} />
        ) : data.require_ack && data.my_ack ? (
          <Banner tone="sage" icon={CheckCheck} title={t("read.confirmed", { version: data.my_ack.version })} />
        ) : null}
        {/* Cleaned by the server's allow-list, then again by safeHtml. */}
        <article className="kbm-article" dangerouslySetInnerHTML={{ __html: body }} />
        {data.children.length > 0 && (
          <>
            <SectionHead size="small">{t("subpages")}</SectionHead>
            <ListCard>
              {data.children.map((child) => (
                <ListRow
                  key={child.id}
                  icon={<span className="kbm-emoji">{child.emoji || "📄"}</span>}
                  title={child.title}
                  onClick={() => {
                    haptic.select();
                    navigation.push({ feature: "knowledge", page: "page", params: { id: child.id } });
                  }}
                />
              ))}
            </ListCard>
          </>
        )}
      </Screen>
      {/* Outside the scrolling screen, so it stays at the bottom however far one reads. */}
      {mustConfirm && <BottomBar primary={{ text: t("read.button"), onClick: confirm, loading: ack.isPending, icon: CheckCheck, shine: true }} />}
    </>
  );
}
