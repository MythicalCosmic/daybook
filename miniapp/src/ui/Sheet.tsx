import { useEffect, useId, useLayoutEffect, useRef, type ReactNode } from "react";

/**
 * The bottom sheet: a dimmed backdrop (tap to close), a handle, and the content. Telegram's back
 * button closes navigation sheets through `useNavigation().closeSheet`; Escape closes it too.
 *
 * For keyboards and screen readers it is a named dialog: it takes focus when it opens (unless a
 * field inside already did, through `autoFocus`), gives it back to the button that opened it when
 * it closes, and is named by `title`, `label`, or else the first heading inside it.
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
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = onClose;

  // Name the dialog after the heading its content brings (the content changes while it stays open).
  useLayoutEffect(() => {
    const element = dialog.current;
    if (!element || title !== undefined || label) return;
    const heading = element.querySelector<HTMLElement>(".heading");
    if (!heading) {
      element.removeAttribute("aria-labelledby");
      return;
    }
    heading.id ||= `${titleId}-heading`;
    element.setAttribute("aria-labelledby", heading.id);
  });

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    // Only a keyboard user (whose opener shows a focus ring) gets focus handed back: on a phone,
    // moving focus to the + button after typing would light its ring up for no reason.
    const active = document.activeElement;
    const opener = active instanceof HTMLElement && active !== document.body && matchesFocusVisible(active) ? active : null;
    if (!element.contains(document.activeElement)) element.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
      } else if (event.key === "Tab") {
        // Keep Tab inside the sheet: the page behind it is covered and inert to the eye.
        const stops = [...element.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
          (node) => node.tabIndex >= 0 && !node.closest("[hidden], [inert]"),
        );
        const first = stops[0];
        const last = stops.at(-1);
        const active = document.activeElement;
        if (!first || !last) {
          event.preventDefault();
          element.focus({ preventScroll: true });
        } else if (event.shiftKey && (active === first || active === element || !element.contains(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (active === last || active === element || !element.contains(active))) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      // Back to the button that opened the sheet; never to a field, which would pop the keyboard up.
      const isField = opener instanceof HTMLInputElement || opener instanceof HTMLTextAreaElement || opener instanceof HTMLSelectElement;
      const focusLost = document.activeElement === null || document.activeElement === document.body || element.contains(document.activeElement);
      if (opener?.isConnected && !isField && focusLost) opener.focus({ preventScroll: true });
    };
  }, []);

  return (
    <div className="sheet-layer">
      <div className="sheet-backdrop" onClick={onClose} />
      <div
        ref={dialog}
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label={label}
        aria-labelledby={title !== undefined && !label ? titleId : undefined}
        tabIndex={-1}
      >
        <div className="sheet-handle" />
        {title !== undefined && (
          <div className="heading title-sm" id={titleId}>
            {title}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function matchesFocusVisible(element: Element): boolean {
  try {
    return element.matches(":focus-visible");
  } catch {
    // An engine without :focus-visible: hand focus back, as a dialog should.
    return true;
  }
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
