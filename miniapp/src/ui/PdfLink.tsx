import { ExternalLink, FileText } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { errorText } from "../lib/actions";
import { useI18n } from "../i18n";
import { useToast } from "../state/toast";
import { haptic, openLink } from "../telegram";
import { Spinner } from "./Button";
import { cx } from "./cx";

/**
 * A payslip, contract or invoice PDF. Private files come as signed URLs that expire after a few
 * minutes, so `href` may be a function that asks the API for a fresh one on tap. Telegram opens
 * it with `openLink` (its own viewer or the browser), which works where a download link doesn't.
 */
export function PdfLink({
  href,
  title,
  subtitle,
  variant = "card",
  className,
}: {
  href: string | (() => Promise<string>);
  title: ReactNode;
  /** "Contract · 12 Oct", "2 pages", a file size. */
  subtitle?: ReactNode;
  /** card: a surface row with a document icon; inset: a line inside a ListCard. */
  variant?: "card" | "inset";
  className?: string;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [opening, setOpening] = useState(false);
  // The signed URL is asked for as the finger lands, so it is usually back by the time the tap
  // ends: Telegram opens links most reliably straight from the tap.
  const early = useRef<{ url: Promise<string>; at: number } | null>(null);
  const prefetch = () => {
    if (typeof href !== "function") return;
    // A press that turned into a scroll leaves one behind: signed URLs expire, so only reuse a fresh one.
    if (early.current && Date.now() - early.current.at < 60_000) return;
    const url = href();
    url.catch(() => undefined); // a failure is reported by the tap that uses it
    early.current = { url, at: Date.now() };
  };

  const open = async () => {
    if (opening) return;
    haptic();
    if (typeof href === "string") {
      openLink(href);
      return;
    }
    setOpening(true);
    try {
      const fresh = early.current && Date.now() - early.current.at < 60_000 ? early.current.url : null;
      const url = await (fresh ?? href());
      if (!openLink(url)) toast(t("error.generic"), { tone: "error" });
    } catch (error) {
      toast(errorText(error, t), { tone: "error" });
    } finally {
      early.current = null;
      setOpening(false);
    }
  };

  const trailing = opening ? <Spinner size={18} /> : <ExternalLink size={18} strokeWidth={2.4} aria-hidden />;
  if (variant === "inset") {
    return (
      <button type="button" className={cx("list-item", subtitle && "list-item--two-line", className)} onPointerDown={prefetch} onClick={open} aria-busy={opening || undefined}>
        <span className="list-item-label">
          <FileText size={20} strokeWidth={2.4} aria-hidden />
          {subtitle ? (
            <span className="list-item-text">
              <span>{title}</span>
              <span className="list-item-sub">{subtitle}</span>
            </span>
          ) : (
            title
          )}
        </span>
        <span className="list-item-value">{trailing}</span>
      </button>
    );
  }
  return (
    <button type="button" className={cx("row ui-pdf", className)} onPointerDown={prefetch} onClick={open} aria-busy={opening || undefined}>
      <span className="circle ui-row-icon ui-row-icon--accent">
        <FileText size={19} strokeWidth={2.4} aria-hidden />
        <span className="ui-pdf-tag">PDF</span>
      </span>
      <span className="row-main">
        <span className="row-title">{title}</span>
        {subtitle && <span className="row-meta">{subtitle}</span>}
      </span>
      <span className="ui-row-chevron">{trailing}</span>
    </button>
  );
}
