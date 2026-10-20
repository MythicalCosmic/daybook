import { Check, ChevronRight, Flame } from "lucide-react";
import { useState } from "react";

import { useSummary } from "../api/hooks";
import type { Day } from "../api/types";
import { LANGUAGES, useI18n } from "../i18n";
import { weekdayShort } from "../lib/time";
import { useNavigation } from "../state/navigation";
import { initials, useMember, useSession } from "../state/session";
import { close, haptic } from "../telegram";
import { applyTheme, saveThemeMode, savedThemeMode, type ThemeMode } from "../theme";

export function Profile() {
  const { t, lang, locale } = useI18n();
  const member = useMember();
  const { companies } = useSession();
  const navigation = useNavigation();
  const summary = useSummary(member.companyId);
  const [theme, setTheme] = useState<ThemeMode>(savedThemeMode);
  const numbers = summary.data;

  const pickTheme = (mode: ThemeMode) => {
    haptic();
    setTheme(mode);
    saveThemeMode(mode);
    applyTheme(mode);
  };

  return (
    <div className="screen fade-in">
      <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "0 4px var(--space-2)" }}>
        <div className="avatar" style={{ width: 64, height: 64, fontSize: 22 }}>
          {initials(member.first_name, member.last_name)}
        </div>
        <div style={{ minWidth: 0 }}>
          <h1 className="heading" style={{ fontSize: 26, lineHeight: 1.1 }}>
            {member.first_name} {member.last_name}
          </h1>
          <div className="muted" style={{ fontSize: 14, marginTop: 4 }}>
            {[member.position?.name, member.company.name].filter(Boolean).join(" · ")}
          </div>
        </div>
      </div>

      <div className="card" style={{ padding: 18, gap: 16, background: "var(--color-accent-100)", color: "var(--color-accent-900)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span className="circle" style={{ width: 44, height: 44, background: "var(--color-accent)", color: "var(--color-bg)" }}>
            <Flame size={22} strokeWidth={2.4} />
          </span>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: 19, fontWeight: 700 }}>
              {numbers && numbers.streak_days > 0
                ? t("profile.streak", { count: numbers.streak_days })
                : t("profile.streakStart")}
            </span>
            {numbers && numbers.streak_days > 0 && <span style={{ fontSize: 14 }}>{t("profile.streakBody")}</span>}
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          {(numbers?.week ?? []).map((day) => (
            <WeekDot key={day.date} day={day} label={day.state === "today" ? t("week.today") : weekdayShort(`${day.date}T12:00:00Z`, "UTC", locale)} />
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
        <div className="card" style={{ padding: 16, gap: 4 }}>
          <span className="heading num" style={{ fontSize: 32, lineHeight: 1 }}>
            {numbers?.month_on_time_percent ?? "—"}
            {numbers?.month_on_time_percent != null && "%"}
          </span>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{t("profile.onTime")}</span>
        </div>
        <div className="card" style={{ padding: 16, gap: 4 }}>
          <span className="heading num" style={{ fontSize: 32, lineHeight: 1 }}>{numbers?.month_done ?? "—"}</span>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{t("profile.doneMonth")}</span>
        </div>
      </div>

      <div className="section-head section-head--small">{t("profile.settings")}</div>
      <div className="card list-card">
        {companies.length > 1 && (
          <button className="list-item" onClick={() => navigation.openSheet({ kind: "company" })}>
            <span>{t("profile.company")}</span>
            <span className="list-item-value">
              {member.company.name}
              <ChevronRight size={18} strokeWidth={2.5} />
            </span>
          </button>
        )}
        <button className="list-item" onClick={() => navigation.openSheet({ kind: "language" })}>
          <span>{t("profile.language")}</span>
          <span className="list-item-value">
            {LANGUAGES.find((language) => language.code === lang)?.name}
            <ChevronRight size={18} strokeWidth={2.5} />
          </span>
        </button>
        <div className="list-item" style={{ minHeight: 58 }}>
          <span>{t("profile.theme")}</span>
          <div className="seg seg--small">
            {(["auto", "light", "dark"] as const).map((mode) => (
              <button key={mode} className="seg-opt" aria-pressed={theme === mode} onClick={() => pickTheme(mode)}>
                {t(`theme.${mode}`)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <button className="btn btn-secondary btn-block" style={{ minHeight: 52, fontSize: 17, marginTop: "var(--space-3)" }} onClick={close}>
        {t("profile.close")}
      </button>
    </div>
  );
}

function WeekDot({ day, label }: { day: Day; label: string }) {
  const dot = {
    done: (
      <span className="circle" style={{ width: 32, height: 32, background: "var(--color-accent-2)", color: "var(--color-bg)" }}>
        <Check size={16} strokeWidth={3} />
      </span>
    ),
    missed: (
      <span className="circle" style={{ width: 32, height: 32, background: "color-mix(in srgb, var(--color-accent) 22%, transparent)" }} />
    ),
    free: (
      <span style={{ width: 32, height: 32, borderRadius: "50%", border: "2px dashed color-mix(in srgb, var(--color-accent-900) 25%, transparent)" }} />
    ),
    today: (
      <span style={{ width: 32, height: 32, borderRadius: "50%", background: "var(--color-bg)", boxShadow: "inset 0 0 0 3px var(--color-accent)" }} />
    ),
  }[day.state];
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, width: 40 }}>
      {dot}
      <span style={{ fontSize: 12.5, fontWeight: 700 }}>{label}</span>
    </div>
  );
}
