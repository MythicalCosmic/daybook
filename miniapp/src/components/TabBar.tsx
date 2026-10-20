import { Bell, House, ListChecks, Plus, UserRound, type LucideIcon } from "lucide-react";

import { useI18n } from "../i18n";
import { useNavigation, type Tab } from "../state/navigation";
import { haptic } from "../telegram";

const TABS: { key: Tab; icon: LucideIcon }[] = [
  { key: "home", icon: House },
  { key: "tasks", icon: ListChecks },
  { key: "activity", icon: Bell },
  { key: "profile", icon: UserRound },
];

export function TabBar({ unread }: { unread: number }) {
  const { t } = useI18n();
  const navigation = useNavigation();
  const [first, second, third, fourth] = TABS.map(({ key, icon: Icon }) => (
    <button
      key={key}
      className="tab"
      aria-current={navigation.tab === key ? "page" : undefined}
      onClick={() => {
        haptic();
        navigation.goTo(key);
      }}
    >
      <span className="tab-pill">
        <Icon size={21} strokeWidth={2.4} />
        {key === "activity" && unread > 0 && (
          <span className="tab-badge">{unread > 99 ? "99+" : unread}</span>
        )}
      </span>
      <span>{t(`tab.${key}`)}</span>
    </button>
  ));
  return (
    <nav className="tabbar">
      {first}
      {second}
      <div style={{ flex: 1, display: "flex", justifyContent: "center" }}>
        <button
          className="btn btn-primary fab"
          aria-label={t("add.title")}
          onClick={() => {
            haptic();
            navigation.openSheet({ kind: "add" });
          }}
        >
          <Plus size={26} strokeWidth={2.75} />
        </button>
      </div>
      {third}
      {fourth}
    </nav>
  );
}
