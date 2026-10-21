/**
 * Ask for cover or a swap for one of my shifts (`params.shift`). Only colleagues the server finds
 * eligible are offered (same position, free that day, under their weekly hours); a cover can go
 * to anyone of them, a swap names a person and the shift of theirs I take in return.
 */
import { CalendarX2, SearchX, Send, UserX } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { useMember } from "../../state/session";
import { haptic } from "../../telegram";
import { Avatar, Button, EmptyState, Field, LoadError, Segmented, SheetTitle, SkeletonList, Textarea, useToast } from "../../ui";
import type { SheetProps } from "../registry";
import { useCandidates, useMyShifts, useRequestSwap } from "./api";
import { shiftDay, shiftHours, shiftLine } from "./lib";
import { usePageT } from "./pageText";
import type { Candidate, Shift } from "./types";
import "./attendance.css";

type Kind = "cover" | "swap";

export default function SwapSheet({ params, close }: SheetProps) {
  const t = usePageT();
  const member = useMember();
  const shiftId = Number(params.shift);
  const shifts = useMyShifts(member.companyId);
  const shift = shifts.data?.find((item) => item.id === shiftId);

  if (shifts.isPending) return <SkeletonList count={3} height={56} />;
  if (!shift) return <EmptyState compact icon={SearchX} tone="sage" title={t("ui.notFound.title")} body={t("ui.notFound.body")} />;
  return <SwapForm shift={shift} close={close} />;
}

function SwapForm({ shift, close }: { shift: Shift; close: () => void }) {
  const t = usePageT();
  const { locale } = useI18n();
  const member = useMember();
  const toast = useToast();
  const candidates = useCandidates(member.companyId, shift.id);
  const request = useRequestSwap(member.companyId);
  const [kind, setKind] = useState<Kind>("cover");
  const [target, setTarget] = useState<number | null>(null);
  const [other, setOther] = useState<number | null>(null);
  const [note, setNote] = useState("");

  const people = candidates.data ?? [];
  const swappable = people.filter((person) => person.shifts.length > 0);
  const chosen: Candidate | undefined = people.find((person) => person.member.id === target);
  const ready = kind === "cover" ? people.length > 0 : target !== null && other !== null;

  const pick = (next: Kind) => {
    haptic.select();
    setKind(next);
    setTarget(null);
    setOther(null);
  };

  const submit = () => {
    if (!ready || request.isPending) return;
    request.mutate(
      { shift_id: shift.id, kind, target_id: target, other_shift_id: kind === "swap" ? other : null, note: note.trim() },
      {
        onSuccess: () => {
          haptic.notify("success");
          close();
          toast(t("swap.sentToast"));
        },
        onError: (error) => {
          haptic.notify("error");
          toast(errorText(error, t));
        },
      },
    );
  };

  return (
    <div className="att-sheet">
      <SheetTitle kicker={`${shiftDay(shift, member.timeZone, locale)} · ${shiftLine(shift)}`}>{t("swapSheet.title")}</SheetTitle>
      <Segmented
        fit
        label={t("swapSheet.title")}
        value={kind}
        onChange={pick}
        options={[
          { value: "cover", label: t("kind.cover") },
          { value: "swap", label: t("kind.swap") },
        ]}
      />
      <p className="att-hint">{t(kind === "cover" ? "cover.hint" : "swap.hint")}</p>

      {candidates.isPending ? (
        <SkeletonList count={3} height={56} />
      ) : candidates.isError ? (
        <LoadError compact error={candidates.error} onRetry={() => void candidates.refetch()} />
      ) : !people.length ? (
        <EmptyState compact icon={UserX} title={t("who.none")} />
      ) : kind === "cover" ? (
        <Group label={t("who.label")}>
            <Choice checked={target === null} onPick={() => setTarget(null)} title={t("who.anyone")} />
            {people.map((person) => (
              <Choice
                key={person.member.id}
                checked={target === person.member.id}
                onPick={() => setTarget(person.member.id)}
                title={person.member.name}
                subtitle={person.member.position?.name}
                avatar={person.member}
              />
            ))}
        </Group>
      ) : !swappable.length ? (
        <EmptyState compact icon={CalendarX2} title={t("swap.noShifts")} />
      ) : (
        <>
          <Group label={t("who.label")}>
              {swappable.map((person) => (
                <Choice
                  key={person.member.id}
                  checked={target === person.member.id}
                  onPick={() => {
                    setTarget(person.member.id);
                    setOther(person.shifts.length === 1 ? person.shifts[0].id : null);
                  }}
                  title={person.member.name}
                  subtitle={person.member.position?.name}
                  avatar={person.member}
                />
              ))}
          </Group>
          {chosen && (
            <Group label={t("swap.pickShift")}>
                {chosen.shifts.map((theirs) => (
                  <Choice
                    key={theirs.id}
                    checked={other === theirs.id}
                    onPick={() => setOther(theirs.id)}
                    title={shiftDay(theirs, member.timeZone, locale)}
                    subtitle={[shiftHours(theirs), theirs.branch?.name].filter(Boolean).join(" · ")}
                  />
                ))}
            </Group>
          )}
        </>
      )}

      <Field label={t("note.label")} optional>
        <Textarea value={note} maxLength={300} placeholder={t("note.placeholder")} onChange={(event) => setNote(event.target.value)} />
      </Field>
      <Button variant="primary" size="lg" block icon={Send} disabled={!ready} loading={request.isPending} onClick={submit}>
        {t("swap.send")}
      </Button>
    </div>
  );
}

/** A labelled list of radio choices. */
function Group({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div className="field">
      <span className="field-label" id={id}>
        {label}
      </span>
      <div className="att-choices" role="radiogroup" aria-labelledby={id}>
        {children}
      </div>
    </div>
  );
}

function Choice({
  checked,
  onPick,
  title,
  subtitle,
  avatar,
}: {
  checked: boolean;
  onPick: () => void;
  title: string;
  subtitle?: string;
  avatar?: { name: string; photo_url: string | null };
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      className="choice"
      onClick={() => {
        haptic.select();
        onPick();
      }}
    >
      <span className="att-choice-main">
        {avatar && <Avatar name={avatar.name} src={avatar.photo_url} size="sm" />}
        <span className="att-choice-text">
          <span>{title}</span>
          {subtitle && <span className="att-choice-sub">{subtitle}</span>}
        </span>
      </span>
      <span className="dot" />
    </button>
  );
}
