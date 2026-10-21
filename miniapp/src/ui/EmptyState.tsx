import { ArrowLeft, RotateCw, SearchX, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { useI18n } from "../i18n";
import { Button } from "./Button";
import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

/**
 * Nothing to show, said kindly: the brand's sun and pebble with an icon, a Caprasimo line, a
 * sentence and at most one action ("Nothing due today. Enjoy it" + Add a personal task).
 */
export function EmptyState({
  title,
  body,
  icon,
  action,
  tone = "accent",
  compact = false,
}: {
  title: ReactNode;
  body?: ReactNode;
  icon?: IconLike;
  action?: { label: ReactNode; onClick: () => void; icon?: IconLike };
  /** accent: terracotta sun (default); sage: a calm, all-done look. */
  tone?: "accent" | "sage";
  compact?: boolean;
}) {
  return (
    <div className={cx("ui-empty", compact && "ui-empty--compact", tone === "sage" && "ui-empty--sage")}>
      <span className="ui-empty-art" aria-hidden>
        <span className="ui-empty-sun">
          {renderIcon(icon, compact ? 22 : 28, 2.4) ?? (
            <svg viewBox="0 0 24 24" className="ui-empty-check">
              <path d="M5 12.5 10 17.5 19 7.5" />
            </svg>
          )}
        </span>
        <span className="ui-empty-pebble" />
      </span>
      <div className="heading ui-empty-title">{title}</div>
      {body && <p className="ui-empty-body">{body}</p>}
      {action && (
        <Button variant="secondary" icon={action.icon} onClick={action.onClick} className="ui-empty-action">
          {action.label}
        </Button>
      )}
    </div>
  );
}

/**
 * What a page shows when its data didn't load, instead of a skeleton that never ends: "This page
 * isn't here" for a refusal or a missing record (with Back), "This part didn't open" with Try
 * again for anything else (a lost signal, a server hiccup). `compact` for a block inside a page.
 */
export function LoadError({
  error,
  onRetry,
  onBack,
  compact = false,
}: {
  error: unknown;
  onRetry?: () => void;
  onBack?: () => void;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const missing = error instanceof ApiError && (error.status === 403 || error.status === 404);
  const state = missing ? (
    <EmptyState
      compact={compact}
      icon={SearchX}
      tone="sage"
      title={t("ui.notFound.title")}
      body={t("ui.notFound.body")}
      action={onBack ? { label: t("ui.notFound.back"), onClick: onBack, icon: ArrowLeft } : undefined}
    />
  ) : (
    <EmptyState
      compact={compact}
      icon={WifiOff}
      title={t("ui.failed.title")}
      body={error instanceof ApiError ? t("ui.failed.body") : t("error.network")}
      action={onRetry ? { label: t("common.retry"), onClick: onRetry, icon: RotateCw } : undefined}
    />
  );
  return compact ? state : <div className="ui-page-center">{state}</div>;
}
