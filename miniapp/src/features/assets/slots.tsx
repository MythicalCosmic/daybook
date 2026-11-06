/** What "My equipment" puts on Home and Me: a card while something waits to be confirmed. */
import { Package } from "lucide-react";

import { Banner } from "../../ui";
import type { MeItemStatus, SlotProps } from "../registry";
import { useFeatureOpen } from "../useFeatureOpen";
import { toConfirm, useMine } from "./api";
import { useMineT } from "./text";

export function MineCard({ member }: SlotProps) {
  const t = useMineT();
  const go = useFeatureOpen("assets");
  const mine = useMine(member.companyId);
  const first = toConfirm(mine.data)[0];
  if (!first) return null;
  return <Banner size="lg" iconTone="accent" icon={Package} title={t("home.title")} body={t("home.body", { name: first.name })} wrap onClick={() => go.page("home")} />;
}

export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const mine = useMine(member.companyId);
  return { badge: toConfirm(mine.data).length || null };
}
