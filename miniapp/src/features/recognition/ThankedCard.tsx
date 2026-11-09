/**
 * Home's card when a colleague thanked the person today (PLAN-LEARNING §12.2): who, for what, the
 * note; with several, how many and from whom. It opens the thanks; once seen there it goes.
 */
import { HeartHandshake } from "lucide-react";

import { useNavigation } from "../../state/navigation";
import { Banner } from "../../ui";
import type { SlotProps } from "../registry";
import { useRecognitionMe } from "./api";
import { useRecognitionT } from "./parts";

export function ThankedCard({ member }: SlotProps) {
  const t = useRecognitionT();
  const navigation = useNavigation();
  const me = useRecognitionMe(member.companyId);
  const fresh = (me.data?.kudos_today ?? []).filter((row) => !row.seen);
  if (!fresh.length) return null;
  const first = fresh[0];
  const open = () => navigation.push({ feature: "recognition", page: "kudos" });
  if (fresh.length === 1) {
    const reason = t(`kudos.badge.${first.badge}`);
    return (
      <Banner
        size="lg"
        iconTone="sage"
        icon={HeartHandshake}
        title={t("card.one", { name: first.from.name.split(" ")[0] })}
        body={first.message ? `${reason} · «${first.message}»` : reason}
        onClick={open}
      />
    );
  }
  const names = [...new Set(fresh.map((row) => row.from.name.split(" ")[0]))].join(", ");
  return <Banner size="lg" iconTone="sage" icon={HeartHandshake} title={t("card.many", { count: fresh.length })} body={t("card.body", { names })} onClick={open} />;
}
