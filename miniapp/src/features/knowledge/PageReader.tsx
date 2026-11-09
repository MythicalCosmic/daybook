import { BookOpenCheck, CheckCheck } from "lucide-react";
import { useMemo, useRef } from "react";

import type { PageProps } from "../registry";
import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { dayMonth } from "../../lib/time";
import { samePage, useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Badge, Banner, BottomBar, ListCard, ListRow, LoadError, PageHeader, Screen, ScreenSkeleton, SectionHead } from "../../ui";
import { useAcknowledge, useKbPage } from "./api";
import { useFollowLink } from "./links";
import "./knowledge.css";
import { messages } from "./messages";
import { safeHtml } from "./safeHtml";
import { PageIcon } from "./icons";
import { usePageViews } from "./views";

/**
 * Reading a page, and confirming it with "I've read it" when the page asks for it, or when it is
 * a step of a course (`params.course`): there the confirmation finishes the step, whatever the
 * page's own setting. While it is in front, it reports the reading time and how far down
 * (docs/PLAN-LEARNING.md §4.1).
 */
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
  const followLink = useFollowLink();
  const article = useRef<HTMLElement>(null);
  const inFront = samePage(navigation.top ?? undefined, { feature: "knowledge", page: "page", params });
  usePageViews(member.companyId, id, { ready: Boolean(page.data), active: inFront, inside: article });

  if (!page.data) {
    return (
      <Screen variant="detail">
        {page.isError ? (
          <LoadError error={page.error} onRetry={() => void page.refetch()} onBack={navigation.pop} />
        ) : (
          <ScreenSkeleton variant="detail" delay={150} />
        )}
      </Screen>
    );
  }
  const data = page.data;
  // A course step is done once the page is confirmed, so the reader asks for it there too.
  const asks = data.require_ack || Boolean(params.course);
  const mustConfirm = asks && !data.my_ack?.current;
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
        ) : asks && data.my_ack ? (
          <Banner tone="sage" icon={CheckCheck} title={t("read.confirmed", { version: data.my_ack.version })} />
        ) : null}
        {/* Cleaned by the server's allow-list, then again by safeHtml. Its links open through the
            app: one into the app opens that screen here, others in Telegram's browser. */}
        <article
          ref={article}
          className="kbm-article"
          onClick={(event) => {
            const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
            if (anchor && followLink(anchor.getAttribute("href") ?? "")) {
              event.preventDefault();
              haptic.select();
            }
          }}
          dangerouslySetInnerHTML={{ __html: body }}
        />
        {data.children.length > 0 && (
          <>
            <SectionHead size="small">{t("subpages")}</SectionHead>
            <ListCard>
              {data.children.map((child) => (
                <ListRow
                  key={child.id}
                  icon={<PageIcon emoji={child.emoji} />}
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
