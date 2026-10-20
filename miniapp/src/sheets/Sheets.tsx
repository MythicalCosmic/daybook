import { Camera, Check } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useCreateTask, useSetLanguage, useTask, useTaskAction } from "../api/hooks";
import type { Repeat, Task } from "../api/types";
import { Sheet } from "../components/Sheet";
import { LANGUAGES, useI18n } from "../i18n";
import { errorText } from "../lib/actions";
import { addDays, dayKey, hourIn, zonedInstant } from "../lib/time";
import { useNavigation } from "../state/navigation";
import { useMember, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { haptic } from "../telegram";

export function Sheets() {
  const navigation = useNavigation();
  const sheet = navigation.sheet;
  if (!sheet) return null;
  return (
    <Sheet onClose={navigation.closeSheet}>
      {sheet.kind === "complete" && <CompleteSheet taskId={sheet.taskId} />}
      {sheet.kind === "return" && <ReturnSheet taskId={sheet.taskId} />}
      {sheet.kind === "add" && <AddSheet />}
      {sheet.kind === "language" && <LanguageSheet />}
      {sheet.kind === "company" && <CompanySheet />}
    </Sheet>
  );
}

function CompleteSheet({ taskId }: { taskId: number }) {
  const member = useMember();
  const task = useTask(member.companyId, taskId);
  return task.data ? <CompleteForm task={task.data} /> : <div className="skeleton" style={{ height: 220 }} />;
}

function CompleteForm({ task }: { task: Task }) {
  const { t } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const action = useTaskAction(member.companyId);
  const toast = useToast();
  const [photo, setPhoto] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const picker = useRef<HTMLInputElement>(null);
  const preview = useMemo(() => (photo ? URL.createObjectURL(photo) : null), [photo]);
  useEffect(() => () => (preview ? URL.revokeObjectURL(preview) : undefined), [preview]);

  const wantsPhoto = task.proof === "photo" || task.proof === "any";
  const missing =
    (task.proof === "photo" && !photo) ||
    (task.proof === "text" && !note.trim()) ||
    (task.proof === "any" && !photo && !note.trim());

  const submit = () => {
    if (missing || action.isPending) return;
    action.mutate(
      { taskId: task.id, action: "complete", proofText: note, photo },
      {
        onSuccess: (done) => {
          haptic("success");
          navigation.closeSheet();
          toast(done.status === "review" ? t("toast.sentForCheck") : t("toast.done"));
        },
        onError: (error) => toast(errorText(error, t)),
      },
    );
  };

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-accent-700)" }}>{t("complete.kicker")}</div>
        <div className="heading title-sm">{task.title}</div>
      </div>
      {wantsPhoto && (
        <div className="field">
          <span className="field-label">{task.proof === "photo" ? t("complete.photo") : t("complete.photoOptional")}</span>
          <input
            ref={picker}
            type="file"
            accept="image/*"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0] ?? null;
              if (file) haptic();
              setPhoto(file);
            }}
          />
          {photo && preview ? (
            <div style={{ display: "flex", alignItems: "center", gap: 14, padding: 10, borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
              <img src={preview} alt="" style={{ flex: "none", width: 64, height: 64, borderRadius: "var(--radius-sm)", objectFit: "cover" }} />
              <div style={{ flex: 1, minWidth: 0, fontSize: 15 }}>
                <div style={{ fontWeight: 700 }}>{t("complete.photoAdded")}</div>
                <div className="muted" style={{ fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{photo.name}</div>
              </div>
              <button className="btn btn-ghost" onClick={() => setPhoto(null)}>{t("complete.remove")}</button>
            </div>
          ) : (
            <button className="photo-drop" onClick={() => picker.current?.click()}>
              <span className="circle" style={{ width: 46, height: 46, background: "var(--color-accent-100)", color: "var(--color-accent-700)" }}>
                <Camera size={22} strokeWidth={2.4} />
              </span>
              <span>{t("complete.addPhoto")}</span>
            </button>
          )}
        </div>
      )}
      <div className="field">
        <label htmlFor="proof-note">{task.proof === "text" ? t("complete.noteNeeded") : t("complete.note")}</label>
        <textarea id="proof-note" className="input" placeholder={t("complete.notePlaceholder")} value={note} maxLength={2000} onChange={(event) => setNote(event.target.value)} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <button className="btn btn-primary btn-lg btn-block" disabled={missing || action.isPending} onClick={submit}>
          {task.needs_confirmation ? t("complete.send") : t("complete.markDone")}
        </button>
        <div className="muted" style={{ fontSize: 14, textAlign: "center" }}>{t("complete.hint")}</div>
      </div>
    </>
  );
}

function ReturnSheet({ taskId }: { taskId: number }) {
  const { t } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const action = useTaskAction(member.companyId);
  const toast = useToast();
  const [reason, setReason] = useState("");
  const submit = () => {
    if (!reason.trim() || action.isPending) return;
    action.mutate(
      { taskId, action: "return", reason },
      {
        onSuccess: () => {
          haptic();
          navigation.closeSheet();
          toast(t("toast.sentBack"));
        },
        onError: (error) => toast(errorText(error, t)),
      },
    );
  };
  return (
    <>
      <div className="heading title-sm">{t("return.title")}</div>
      <div className="field">
        <label htmlFor="return-reason">{t("return.label")}</label>
        <textarea id="return-reason" className="input" placeholder={t("return.placeholder")} value={reason} maxLength={2000} onChange={(event) => setReason(event.target.value)} autoFocus />
      </div>
      <button className="btn btn-primary btn-lg btn-block" disabled={!reason.trim() || action.isPending} onClick={submit}>
        {t("return.send")}
      </button>
    </>
  );
}

const REPEATS: Repeat[] = ["none", "daily", "weekdays", "weekly"];

function AddSheet() {
  const { t } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const create = useCreateTask(member.companyId);
  const toast = useToast();
  const now = new Date();
  const hour = hourIn(now, member.timeZone);
  // Default to the next full hour today, or tomorrow morning when the day is nearly over.
  const [day, setDay] = useState<"today" | "tomorrow">(hour < 22 ? "today" : "tomorrow");
  const [time, setTime] = useState(hour < 22 ? `${String(hour + 1).padStart(2, "0")}:00` : "09:00");
  const [title, setTitle] = useState("");
  const [repeat, setRepeat] = useState<Repeat>("none");

  const submit = () => {
    if (!title.trim() || create.isPending) return;
    const today = dayKey(now, member.timeZone);
    const due = zonedInstant(day === "today" ? today : addDays(today, 1), time, member.timeZone);
    create.mutate(
      { title: title.trim(), due_at: due.toISOString(), repeat },
      {
        onSuccess: () => {
          haptic("success");
          navigation.goTo("tasks", "personal");
          toast(t("toast.added"));
        },
        onError: (error) => toast(errorText(error, t)),
      },
    );
  };

  return (
    <>
      <div className="heading title-sm">{t("add.title")}</div>
      <div className="field">
        <label htmlFor="add-title">{t("add.what")}</label>
        <input id="add-title" className="input" placeholder={t("add.placeholder")} value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => event.key === "Enter" && submit()} />
      </div>
      <div className="field">
        <span className="field-label">{t("add.when")}</span>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <div className="seg" style={{ flex: 1 }}>
            {(["today", "tomorrow"] as const).map((option) => (
              <button key={option} className="seg-opt" aria-pressed={day === option} onClick={() => setDay(option)}>
                {t(option === "today" ? "day.today" : "day.tomorrow")}
              </button>
            ))}
          </div>
          <input className="input num" type="time" aria-label={t("add.time")} value={time} onChange={(event) => setTime(event.target.value || time)} style={{ flex: "none", width: "auto", minWidth: 128, minHeight: 52, fontSize: 16 }} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="add-repeat">{t("add.repeat")}</label>
        <select id="add-repeat" className="input" value={repeat} onChange={(event) => setRepeat(event.target.value as Repeat)}>
          {REPEATS.map((option) => (
            <option key={option} value={option}>{t(`add.repeat.${option}`)}</option>
          ))}
        </select>
      </div>
      <button className="btn btn-primary btn-lg btn-block" disabled={!title.trim() || create.isPending} onClick={submit}>
        {t("add.submit")}
      </button>
    </>
  );
}

function LanguageSheet() {
  const { t, lang } = useI18n();
  const navigation = useNavigation();
  const setLanguage = useSetLanguage();
  const toast = useToast();
  return (
    <>
      <div className="heading title-sm">{t("lang.title")}</div>
      <div role="radiogroup" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {LANGUAGES.map((language) => (
          <button
            key={language.code}
            className="choice"
            role="radio"
            aria-checked={lang === language.code}
            onClick={() => {
              haptic();
              setLanguage.mutate(language.code, {
                onSuccess: navigation.closeSheet,
                onError: (error) => toast(errorText(error, t)),
              });
            }}
          >
            <span>{language.name}</span>
            <span className="dot" />
          </button>
        ))}
      </div>
    </>
  );
}

function CompanySheet() {
  const { t } = useI18n();
  const { companies, switchCompany, membership } = useSession();
  const navigation = useNavigation();
  return (
    <>
      <div className="heading title-sm">{t("profile.company")}</div>
      <div role="radiogroup" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {companies.map((company) => (
          <button
            key={company.company.id}
            className="choice"
            role="radio"
            aria-checked={membership?.company.id === company.company.id}
            onClick={() => {
              haptic();
              switchCompany(company.company.id);
              navigation.goTo("home");
            }}
          >
            <span>{company.company.name}</span>
            {membership?.company.id === company.company.id ? <Check size={20} strokeWidth={3} /> : <span className="dot" />}
          </button>
        ))}
      </div>
    </>
  );
}
