import { ExternalLink, FileText } from "lucide-react";
import { useState, type ReactNode } from "react";

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

  const open = async () => {
    if (opening) return;
    haptic();
    if (typeof href === "string") {
      openLink(href);
      return;
    }
    setOpening(true);
    try {
      openLink(await href());
    } catch (error) {
      toast(errorText(error, t), { tone: "error" });
    } finally {
      setOpening(false);
    }
  };

  const trailing = opening ? <Spinner size={18} /> : <ExternalLink size={18} strokeWidth={2.4} aria-hidden />;
  if (variant === "inset") {
    return (
      <button type="button" className={cx("list-item", subtitle && "list-item--two-line", className)} onClick={open} aria-busy={opening || undefined}>
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
    <button type="button" className={cx("row ui-pdf", className)} onClick={open} aria-busy={opening || undefined}>
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
