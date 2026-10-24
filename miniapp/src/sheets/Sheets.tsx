import { Camera, Check } from "lucide-react";
import { useId, useRef, useState } from "react";

import { useRequestTimeOff, useSetLanguage, useTask, useTaskAction } from "../api/hooks";
import type { Task } from "../api/types";
import { FeatureSheet } from "../features/hosts";
import { LANGUAGES, translate, useI18n, type Key, type Lang } from "../i18n";
import { errorText, useDoneToast } from "../lib/actions";
import { addDays, dayKey } from "../lib/time";
import { useDraftGuard } from "../lib/useDraftGuard";
import { useNavigation } from "../state/navigation";
import { useMember, useSession } from "../state/session";
import { useToast } from "../state/toast";
import { haptic } from "../telegram";
import { Sheet } from "../ui/Sheet";
import { useObjectUrl } from "../ui/useObjectUrl";
import { AddSheet } from "./AddSheet";
import { BlockerSheet, DueSheet, EditSheet, ExtensionSheet, ReassignSheet, SnoozeSheet, TaskMenuSheet } from "./TaskSheets";

export function Sheets() {
  const navigation = useNavigation();
  const sheet = navigation.sheet;
  if (!sheet) return null;
  return (
    <Sheet onClose={navigation.closeSheet}>
      {sheet.kind === "complete" && <CompleteSheet taskId={sheet.taskId} />}
      {sheet.kind === "return" && <ReturnSheet taskId={sheet.taskId} />}
      {sheet.kind === "snooze" && <SnoozeSheet taskId={sheet.taskId} />}
      {sheet.kind === "blocker" && <BlockerSheet taskId={sheet.taskId} />}
      {sheet.kind === "extension" && <ExtensionSheet taskId={sheet.taskId} />}
      {sheet.kind === "reassign" && <ReassignSheet taskId={sheet.taskId} />}
      {sheet.kind === "due" && <DueSheet taskId={sheet.taskId} resolve={sheet.resolve} />}
      {sheet.kind === "edit" && <EditSheet taskId={sheet.taskId} />}
      {sheet.kind === "taskMenu" && <TaskMenuSheet taskId={sheet.taskId} />}
      {sheet.kind === "add" && <AddSheet />}
      {sheet.kind === "language" && <LanguageSheet />}
      {sheet.kind === "company" && <CompanySheet />}
      {sheet.kind === "timeOff" && <TimeOffSheet />}
      {sheet.kind === "feature" && <FeatureSheet feature={sheet.feature} sheet={sheet.sheet} params={sheet.params ?? {}} />}
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
  const doneToast = useDoneToast();
  const [photo, setPhoto] = useState<File | null>(null);
  // Sent back: the report that went with it is the starting point, not a blank box (audit M-12).
  const [note, setNote] = useState(task.status === "returned" ? task.proof_text : "");
  const picker = useRef<HTMLInputElement>(null);
  const preview = useObjectUrl(photo);
  useDraftGuard(Boolean(photo) || note.trim() !== (task.status === "returned" ? task.proof_text.trim() : ""));

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
          doneToast(done);
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
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

const RETURN_REASONS = ["photo", "unfinished", "wrong", "other"] as const;
type ReturnReason = (typeof RETURN_REASONS)[number];

/**
 * Send it back (R2 T30): a reason in one tap, what to fix in a few words after it. The reason
 * goes out as text in the reviewer's language: "Фото нечёткое. Переснимите при дневном свете".
 */
function ReturnSheet({ taskId }: { taskId: number }) {
  const { t } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const action = useTaskAction(member.companyId);
  const toast = useToast();
  const id = useId();
  const [reason, setReason] = useState<ReturnReason | null>(null);
  const [note, setNote] = useState("");
  useDraftGuard(Boolean(reason || note.trim()));
  const needsNote = reason === null || reason === "other";
  const text = [reason && reason !== "other" ? t(`return.reason.${reason}`) : "", note.trim()].filter(Boolean).join(". ");
  const ready = needsNote ? Boolean(note.trim()) : true;
  const submit = () => {
    if (!ready || !text || action.isPending) return;
    action.mutate(
      { taskId, action: "return", reason: text },
      {
        onSuccess: () => {
          haptic();
          navigation.closeSheet();
          toast(t("toast.sentBack"));
        },
        onError: (error) => toast(errorText(error, t), { tone: "error" }),
      },
    );
  };
  return (
    <>
      <div className="heading title-sm">{t("return.title")}</div>
      <div className="field">
        <span className="field-label" id={`${id}-why`}>{t("return.why")}</span>
        <div className="ui-chips" role="radiogroup" aria-labelledby={`${id}-why`}>
          {RETURN_REASONS.map((option) => (
            <button
              key={option}
              type="button"
              className="ui-chip"
              role="radio"
              aria-checked={reason === option}
              aria-pressed={reason === option}
              onClick={() => {
                haptic.select();
                setReason(reason === option ? null : option);
              }}
            >
              <span>{t(`return.reason.${option}`)}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="return-reason">{needsNote ? t("return.label") : t("return.noteOptional")}</label>
        <textarea id="return-reason" className="input" placeholder={t("return.placeholder")} value={note} maxLength={2000} onChange={(event) => setNote(event.target.value)} />
      </div>
      <button className="btn btn-primary btn-lg btn-block" disabled={!ready || !text || action.isPending} onClick={submit}>
        {t("return.send")}
      </button>
    </>
  );
}

function TimeOffSheet() {
  const { t } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const request = useRequestTimeOff(member.companyId);
  const toast = useToast();
  const today = dayKey(new Date(), member.timeZone);
  const [first, setFirst] = useState(addDays(today, 1));
  const [last, setLast] = useState(addDays(today, 1));
  const [reason, setReason] = useState("");
  const valid = first >= today && last >= first;

  const submit = () => {
    if (!valid || request.isPending) return;
    request.mutate(
      { first_day: first, last_day: last, reason: reason.trim() },
      {
        onSuccess: (created) => {
          haptic("success");
          navigation.closeSheet();
          toast(t(created.status === "approved" ? "timeOff.toastTaken" : "timeOff.toastSent"));
        },
        onError: (error) => toast(errorText(error, t)),
      },
    );
  };

  return (
    <>
      <div className="heading title-sm">{t("timeOff.title")}</div>
      <div style={{ display: "flex", gap: "var(--space-2)" }}>
        <div className="field" style={{ flex: 1, minWidth: 0 }}>
          <label htmlFor="off-first">{t("timeOff.first")}</label>
          <input
            id="off-first"
            className="input num"
            type="date"
            min={today}
            value={first}
            onChange={(event) => {
              const day = event.target.value || first;
              setFirst(day);
              if (last < day) setLast(day);
            }}
          />
        </div>
        <div className="field" style={{ flex: 1, minWidth: 0 }}>
          <label htmlFor="off-last">{t("timeOff.last")}</label>
          <input id="off-last" className="input num" type="date" min={first} value={last} onChange={(event) => setLast(event.target.value || last)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="off-reason">{t("timeOff.reason")}</label>
        <textarea id="off-reason" className="input" placeholder={t("timeOff.reasonPlaceholder")} value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)} />
      </div>
      <div className="muted" style={{ fontSize: 14 }}>{t("timeOff.note")}</div>
      <button className="btn btn-primary btn-lg btn-block" disabled={!valid || request.isPending} onClick={submit}>
        {t("timeOff.send")}
      </button>
    </>
  );
}

/**
 * The language: the app switches the moment it's tapped, the server saves it and relabels the
 * bot's chat (menu, commands, keyboard), and the toast says so in the new language.
 */
function LanguageSheet() {
  const { t, lang } = useI18n();
  const navigation = useNavigation();
  const setLanguage = useSetLanguage();
  const toast = useToast();
  const pick = (code: Lang) => {
    haptic.select();
    navigation.closeSheet();
    if (code === lang) return;
    setLanguage.mutate(code, {
      onSuccess: () => toast(translate(code, "lang.changed" satisfies Key), { tone: "success" }),
      onError: (error) => toast(errorText(error, t), { tone: "error" }),
    });
  };
  return (
    <>
      <div className="heading title-sm">{t("lang.title")}</div>
      <div role="radiogroup" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {LANGUAGES.map((language) => (
          <button key={language.code} className="choice" role="radio" aria-checked={lang === language.code} lang={language.code} onClick={() => pick(language.code)}>
            <span>{language.name}</span>
            <span className="dot" />
          </button>
        ))}
      </div>
      <p className="sheet-note sheet-note--muted">{t("lang.note")}</p>
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
