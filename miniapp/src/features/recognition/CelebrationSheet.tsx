/**
 * The celebration (PLAN-LEARNING §12.2, §12.3): when the app opens after a new level or badge, a
 * sheet shows each one in turn with confetti and a success buzz. Opening it tells the server they
 * were seen, so it comes once; with several, "Next" steps through them.
 */
import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useMember } from "../../state/session";
import { Button, celebrate } from "../../ui";
import type { SheetProps } from "../registry";
import { useMarkSeen, useRecognitionMe, type Unseen } from "./api";
import { Medal, useRecognitionT } from "./parts";
import "./recognition.css";

export default function CelebrationSheet({ close }: SheetProps) {
  const t = useRecognitionT();
  const member = useMember();
  const me = useRecognitionMe(member.companyId);
  const seen = useMarkSeen(member.companyId);
  // What there was to celebrate when the sheet opened: marking it seen refetches an empty list.
  const [items] = useState<Unseen[]>(() => me.data?.unseen ?? []);
  const [index, setIndex] = useState(0);
  const stage = useRef<HTMLDivElement>(null);
  const marked = useRef(false);

  useEffect(() => {
    if (marked.current || !items.length) return;
    marked.current = true;
    seen.mutate({});
  }, [items.length, seen]);

  useEffect(() => {
    // Nothing new after all (another device saw it first): nothing to show.
    if (!items.length) {
      close();
      return;
    }
    // The burst from the medal; the first one also buzzes.
    return celebrate({ from: stage.current, haptic: index === 0 ? "success" : "light" });
  }, [index, items.length, close]);

  if (!items.length) return null;
  const item = items[Math.min(index, items.length - 1)];
  const last = index >= items.length - 1;
  return (
    <div className="rcg-celebrate" data-testid="recognition-celebration">
      {items.length > 1 && <div className="rcg-celebrate-step">{t("celebrate.step", { current: index + 1, total: items.length })}</div>}
      <div className="rcg-celebrate-stage" ref={stage} key={`${item.type}-${index}`}>
        {item.type === "level" ? (
          <span className="rcg-celebrate-level num" aria-hidden>
            <Sparkles size={22} strokeWidth={2.4} className="rcg-celebrate-sparkle" />
            {item.number}
          </span>
        ) : (
          <Medal icon={item.icon} tier={item.tier} size={104} pop />
        )}
      </div>
      <div className="rcg-celebrate-kicker">{item.type === "level" ? t("celebrate.level") : t("celebrate.badge")}</div>
      <h2 className="heading rcg-celebrate-title">{item.name}</h2>
      <p className="rcg-celebrate-body">
        {item.type === "level" ? t("celebrate.levelBody", { number: item.number, name: item.name }) : item.description}
      </p>
      {item.type === "badge" && <span className={`rcg-tier rcg-tier--${item.tier}`}>{t(`tier.${item.tier}`)}</span>}
      <Button variant="primary" size="lg" block onClick={() => (last ? close() : setIndex(index + 1))}>
        {last ? t("celebrate.done") : t("celebrate.next")}
      </Button>
    </div>
  );
}
