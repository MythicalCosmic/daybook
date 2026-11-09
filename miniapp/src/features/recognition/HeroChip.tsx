/**
 * Home's chip under the greeting (PLAN-LEARNING §12.2): the level in a ring that fills towards the
 * next one, the points of this week and the learning streak's flame. One tap opens My
 * achievements. When the app opens with a new level or badge waiting (`unseen`), it opens the
 * celebration once per session.
 */
import { ChevronRight, Flame } from "lucide-react";
import { useEffect } from "react";

import { useNavigation } from "../../state/navigation";
import type { SlotProps } from "../registry";
import { useRecognitionMe } from "./api";
import { LevelRing, levelShare, useRecognitionT } from "./parts";
import "./recognition.css";

/** Shown once per app session, whatever the server says until it hears "seen". */
let celebrationOpened = false;

export function resetCelebrationForTests(): void {
  celebrationOpened = false;
}

export function HeroChip({ member }: SlotProps) {
  const t = useRecognitionT();
  const navigation = useNavigation();
  const me = useRecognitionMe(member.companyId);
  const data = me.data;
  const waiting = (data?.unseen.length ?? 0) > 0;

  useEffect(() => {
    if (!waiting || celebrationOpened || navigation.sheet) return;
    celebrationOpened = true;
    navigation.openSheet({ kind: "feature", feature: "recognition", sheet: "celebrate" });
  }, [waiting, navigation]);

  if (!data || !data.enabled) return null;
  const { level } = data;
  const open = () => navigation.push({ feature: "recognition", page: "achievements" });
  return (
    <button
      type="button"
      className="rcg-chip"
      onClick={open}
      aria-label={t("hero.label", { number: level.number, name: level.name, points: data.week_points })}
      data-testid="recognition-chip"
    >
      <LevelRing number={level.number} share={levelShare(data.points, level)} />
      <span className="rcg-chip-text">
        <span className="rcg-chip-name">{level.name}</span>
        <span className="rcg-chip-week num">{t("hero.week", { points: data.week_points })}</span>
      </span>
      {data.streak > 0 && (
        <span className="rcg-chip-flame" title={t("hero.streak", { count: data.streak })}>
          <Flame size={16} strokeWidth={2.6} aria-hidden />
          <span className="num">{data.streak}</span>
        </span>
      )}
      <ChevronRight size={18} strokeWidth={2.4} className="rcg-chip-chevron" aria-hidden />
    </button>
  );
}
