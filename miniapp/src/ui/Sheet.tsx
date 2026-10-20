import type { ReactNode } from "react";

/**
 * The bottom sheet: a dimmed backdrop (tap to close), a handle, and the content. Telegram's back
 * button closes navigation sheets through `useNavigation().closeSheet`.
 */
export function Sheet({
  onClose,
  children,
  title,
  label,
}: {
  onClose: () => void;
  children: ReactNode;
  /** A Caprasimo heading as the first line (or use SheetTitle for one with a kicker). */
  title?: ReactNode;
  /** Name for screen readers when there is no visible title. */
  label?: string;
}) {
  return (
    <div className="sheet-layer">
      <div className="sheet-backdrop" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={label}>
        <div className="sheet-handle" />
        {title !== undefined && <div className="heading title-sm">{title}</div>}
        {children}
      </div>
    </div>
  );
}

/** A sheet heading, optionally with a small terracotta line above ("Finish task"). */
export function SheetTitle({ kicker, children }: { kicker?: ReactNode; children: ReactNode }) {
  if (!kicker) return <div className="heading title-sm">{children}</div>;
  return (
    <div className="ui-sheet-title">
      <div className="ui-kicker">{kicker}</div>
      <div className="heading title-sm">{children}</div>
    </div>
  );
}
