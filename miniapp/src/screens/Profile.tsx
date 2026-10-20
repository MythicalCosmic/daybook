import { BarChart3, Check, ChevronRight, Flame, PartyPopper, TreePalm } from "lucide-react";
import { useState } from "react";

import { useCancelTimeOff, useHolidays, useSummary, useTimeOff } from "../api/hooks";
import { FeatureSlot } from "../features/FeatureSlot";
import { useReplacedEntries } from "../features/hosts";
import type { Day } from "../api/types";
import { LANGUAGES, useI18n } from "../i18n";
import { errorText } from "../lib/actions";
import { cancellable, current, STATUS_TAG } from "../lib/timeOff";
import { dayKey, dayMonth, weekdayShort } from "../lib/time";
import { useToast } from "../state/toast";
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
  const timeOff = useTimeOff(member.companyId);
  const holidays = useHolidays(member.companyId);
  const cancelTimeOff = useCancelTimeOff(member.companyId);
  const toast = useToast();
  const [theme, setTheme] = useState<ThemeMode>(savedThemeMode);
  // Feature folders can take over these built-in sections (the leave feature replaces time off).
  const replaced = useReplacedEntries();
  const numbers = summary.data;
  const today = dayKey(new Date(), member.timeZone);
  // Dates without a time: read them at noon UTC so no timezone moves the day.
  const day = (date: string) => dayMonth(`${date}T12:00:00Z`, "UTC", locale);
  const span = (first: string, last: string) => (first === last ? day(first) : `${day(first)} – ${day(last)}`);

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

      {!replaced.has("me.work") && numbers?.quiet_from && numbers.quiet_until && (
        <>
          <div className="section-head section-head--small">{t("profile.work")}</div>
          <div className="card list-card">
            <div className="list-item">
              <span>{t("profile.quietHours")}</span>
              <span className="list-item-value">
                {numbers.quiet_from.slice(0, 5)}–{numbers.quiet_until.slice(0, 5)}
              </span>
            </div>
          </div>
          <div className="muted" style={{ fontSize: 14, padding: "0 4px" }}>{t("profile.quietNote")}</div>
        </>
      )}

      {!replaced.has("me.timeOff") && (
        <>
          <div className="section-head section-head--small">{t("timeOff.section")}</div>
          <div className="card list-card">
            {current(timeOff.data ?? [], today).map((item) => (
              <div key={item.id} className="list-item" style={{ minHeight: 58 }}>
                <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                  <span className="num" style={{ fontWeight: 600 }}>{span(item.first_day, item.last_day)}</span>
                  {item.reason && <span className="muted" style={{ fontSize: 13.5 }}>{item.reason}</span>}
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: 6, flex: "none" }}>
                  <span className={`tag tag-small ${STATUS_TAG[item.status]}`}>{t(`timeOff.status.${item.status}`)}</span>
                  {cancellable(item, today) && (
                    <button
                      className="btn btn-ghost"
                      style={{ padding: "6px 8px", minHeight: 0, fontSize: 14 }}
                      disabled={cancelTimeOff.isPending}
                      onClick={() =>
                        cancelTimeOff.mutate(item.id, {
                          onSuccess: () => toast(t("timeOff.toastCancelled")),
                          onError: (error) => toast(errorText(error, t)),
                        })
                      }
                    >
                      {t("timeOff.cancel")}
                    </button>
                  )}
                </span>
              </div>
            ))}
            {(holidays.data ?? []).slice(0, 3).map((holiday) => (
              <div key={`holiday-${holiday.id}`} className="list-item">
                <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <PartyPopper size={18} strokeWidth={2.4} />
                  {holiday.name}
                </span>
                <span className="list-item-value num">{day(holiday.date)}</span>
              </div>
            ))}
            <button className="list-item" onClick={() => navigation.openSheet({ kind: "timeOff" })}>
              <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <TreePalm size={20} strokeWidth={2.4} />
                {t("timeOff.request")}
              </span>
              <span className="list-item-value">
                <ChevronRight size={18} strokeWidth={2.5} />
              </span>
            </button>
          </div>
        </>
      )}

      {/* Feature rows on Me, grouped; the built-in Team results row leads the team group. */}
      <FeatureSlot
        name="me.items"
        builtIns={{
          team: member.permissions.includes("reports.view") && !replaced.has("me.team") && (
            <button className="list-item" onClick={() => navigation.openPage("team")}>
              <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <BarChart3 size={20} strokeWidth={2.4} />
                {t("profile.team")}
              </span>
              <span className="list-item-value">
                <ChevronRight size={18} strokeWidth={2.5} />
              </span>
            </button>
          ),
        }}
      />

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
