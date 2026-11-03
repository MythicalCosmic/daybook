/**
 * States feature sheets share: what a sheet shows while its row loads, didn't load or is gone,
 * and the buzz and toast after a write.
 */
import { SearchX } from "lucide-react";
import type { ReactNode } from "react";

import { useI18n } from "../i18n";
import { errorText } from "../lib/actions";
import { useToast } from "../state/toast";
import { haptic } from "../telegram";
import { EmptyState, LoadError, ScreenSkeleton } from "../ui";
import "./states.css";

/** "Label: value" lines under a sheet's title (empty ones are left out). */
export function SheetFacts({ lines }: { lines: (ReactNode | null | false | undefined)[] }) {
  const shown = lines.filter(Boolean);
  if (!shown.length) return null;
  return (
    <ul className="ft-facts">
      {shown.map((line, index) => (
        <li key={index}>{line}</li>
      ))}
    </ul>
  );
}

/** A sheet's row hasn't come, didn't come, or isn't (or is no longer) there. */
export function SheetMissing({ pending, error, onRetry }: { pending: boolean; error: unknown; onRetry: () => void }) {
  const { t } = useI18n();
  if (pending) return <ScreenSkeleton variant="detail" delay={150} />;
  if (error) return <LoadError compact error={error} onRetry={onRetry} />;
  return <EmptyState compact icon={SearchX} tone="sage" title={t("ui.notFound.title")} body={t("ui.notFound.body")} />;
}

/** Feedback after a write: a success buzz and toast, or the server's reason with an error buzz. */
export function useFeedback() {
  const toast = useToast();
  const { t } = useI18n();
  return {
    ok: (text: string) => {
      haptic.notify("success");
      toast(text, { tone: "success" });
    },
    fail: (error: unknown) => {
      haptic.notify("error");
      toast(errorText(error, t), { tone: "error" });
    },
  };
}
