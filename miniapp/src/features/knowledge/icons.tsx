import { FileText, Folder } from "lucide-react";

/**
 * A page's or a space's own emoji, as its owner picked it; without one, a plain icon. The app
 * itself adds no emoji of its own (lucide icons only).
 */
export function PageIcon({ emoji }: { emoji: string }) {
  return (
    <span className="kbm-emoji" aria-hidden>
      {emoji || <FileText size={19} strokeWidth={2.4} />}
    </span>
  );
}

export function SpaceIcon({ icon }: { icon: string }) {
  return (
    <span className="kbm-space-icon" aria-hidden>
      {icon || <Folder size={19} strokeWidth={2.4} />}
    </span>
  );
}
