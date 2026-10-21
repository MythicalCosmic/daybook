import { BookOpenCheck } from "lucide-react";

import type { SlotProps } from "../registry";
import { useFeatureT } from "../../i18n/feature";
import { useNavigation } from "../../state/navigation";
import { haptic } from "../../telegram";
import { Banner } from "../../ui";
import { useKbHome } from "./api";
import { messages } from "./messages";

/** Home: "2 pages to read" while the person has pages to confirm; nothing otherwise. */
export function ToReadCard({ member }: SlotProps) {
  const t = useFeatureT(messages);
  const navigation = useNavigation();
  const home = useKbHome(member.companyId);
  const pages = home.data?.to_read ?? [];
  if (!pages.length) return null;
  const open = () => {
    haptic.select();
    if (pages.length === 1) navigation.push({ feature: "knowledge", page: "page", params: { id: pages[0]!.id } });
    else navigation.push({ feature: "knowledge", page: "home" });
  };
  return (
    <Banner
      tone="accent"
      size="lg"
      icon={BookOpenCheck}
      title={t("card.title", { count: pages.length })}
      body={pages.length === 1 ? `${pages[0]!.emoji} ${pages[0]!.title}`.trim() : t("card.body")}
      onClick={open}
    />
  );
}
