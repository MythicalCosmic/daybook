/**
 * "Say thanks" (PLAN-LEARNING §7.5, §12.2), from (+), from a colleague's thanks ("Say thanks
 * back", `params.to`) or the bot's /kudos: pick a colleague from the team directory, what for,
 * and a few words. A small burst of confetti when it's sent; the colleague hears from the bot.
 */
import { Check, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { useMember } from "../../state/session";
import { Avatar, Button, Field, Input, SheetTitle, Textarea, celebrate, cx, useToast } from "../../ui";
import type { SheetProps } from "../registry";
import { useColleagues, useSendKudos, type Colleague, type KudosBadge } from "./api";
import { KUDOS_BADGES, useRecognitionT } from "./parts";
import "./recognition.css";

const NOTE_MAX = 200;

function useDebounced(value: string, ms = 250): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

export default function KudosSheet({ params, close }: SheetProps) {
  const t = useRecognitionT();
  const member = useMember();
  const toast = useToast();
  const send = useSendKudos(member.companyId);
  // The colleague a link names ("Say thanks back"): listed first even from another branch.
  const linked = typeof params.to === "number" ? params.to : Number(params.to) || null;
  const [query, setQuery] = useState("");
  const q = useDebounced(query.trim());
  const colleagues = useColleagues(member.companyId, q, linked);
  const [picked, setPicked] = useState<Colleague | null>(null);
  const [pickedId, setPickedId] = useState<number | null>(linked);
  const [badge, setBadge] = useState<KudosBadge>("thanks");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const sendButton = useRef<HTMLButtonElement>(null);

  const results = colleagues.data?.results ?? [];
  // A colleague named by the link: found in the first page of the directory.
  const chosen = useMemo(() => picked ?? results.find((person) => person.id === pickedId) ?? null, [picked, pickedId, results]);
  const left = colleagues.data?.left ?? null;
  const noneLeft = left === 0;

  const submit = () => {
    if (!chosen || send.isPending || noneLeft) return;
    setError(null);
    send.mutate(
      { to: chosen.id, badge, message: note.trim() },
      {
        onSuccess: () => {
          celebrate({ from: sendButton.current, pieces: 40, haptic: "success" });
          toast(t("kudos.sent", { name: chosen.name }), { tone: "success" });
          close();
        },
        onError: (failure: unknown) => setError(failure instanceof ApiError && failure.detail ? failure.detail : t("common.retry")),
      },
    );
  };

  return (
    <div className="rcg-kudos" data-testid="kudos-sheet">
      <SheetTitle>{t("kudos.title")}</SheetTitle>

      {chosen ? (
        <div className="rcg-kudos-chosen">
          <Avatar name={chosen.name} src={chosen.avatar_url} size="md" />
          <span className="rcg-kudos-person">
            <span className="rcg-kudos-person-name">{chosen.name}</span>
            {(chosen.position || chosen.branch) && <span className="rcg-kudos-person-sub">{[chosen.position, chosen.branch].filter(Boolean).join(" · ")}</span>}
          </span>
          <Button
            variant="ghost"
            onClick={() => {
              setPicked(null);
              setPickedId(null);
            }}
          >
            {t("kudos.change")}
          </Button>
        </div>
      ) : (
        <>
          <div className="rcg-kudos-label">{t("kudos.who")}</div>
          <div className="rcg-search">
            <Search size={18} strokeWidth={2.4} className="rcg-search-icon" aria-hidden />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("kudos.search")} aria-label={t("kudos.search")} />
          </div>
          <div className="rcg-people" role="listbox" aria-label={t("kudos.who")}>
            {results.map((person) => (
              <button
                key={person.id}
                type="button"
                role="option"
                aria-selected={false}
                className="rcg-person"
                onClick={() => {
                  setPicked(person);
                  setPickedId(person.id);
                }}
              >
                <Avatar name={person.name} src={person.avatar_url} size="md" />
                <span className="rcg-person-name">{person.name.split(" ")[0]}</span>
              </button>
            ))}
            {colleagues.isSuccess && results.length === 0 && <div className="rcg-people-none">{t("kudos.noOne")}</div>}
          </div>
        </>
      )}

      <div className="rcg-kudos-label">{t("kudos.for")}</div>
      <div className="rcg-kudos-badges" role="radiogroup" aria-label={t("kudos.for")}>
        {KUDOS_BADGES.map(({ key, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={badge === key}
            className={cx("rcg-kudos-badge", `rcg-kudos-badge--${key}`, badge === key && "rcg-kudos-badge--on")}
            onClick={() => setBadge(key)}
          >
            <Icon size={22} strokeWidth={2.3} aria-hidden />
            <span>{t(`kudos.badge.${key}`)}</span>
            {badge === key && <Check size={14} strokeWidth={3} className="rcg-kudos-badge-check" aria-hidden />}
          </button>
        ))}
      </div>

      <Field label={t("kudos.note")} hint={`${note.length}/${NOTE_MAX}`}>
        <Textarea value={note} maxLength={NOTE_MAX} rows={2} placeholder={t("kudos.notePlaceholder")} onChange={(event) => setNote(event.target.value)} />
      </Field>

      {error && (
        <p className="rcg-kudos-error" role="alert">
          {error}
        </p>
      )}
      {left !== null && <p className={cx("rcg-kudos-left", noneLeft && "rcg-kudos-left--none")}>{noneLeft ? t("kudos.noneLeft") : t("kudos.left", { count: left })}</p>}

      <Button ref={sendButton} variant="primary" size="lg" block onClick={submit} disabled={!chosen || noneLeft} loading={send.isPending}>
        {t("kudos.send")}
      </Button>
    </div>
  );
}
