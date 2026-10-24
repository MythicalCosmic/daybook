/**
 * Quick add: the (+) sheet asks the server what the typed text says about when, how often and how
 * urgently ("Kassani sanash ertaga 18:00" → tomorrow 18:00). The server parses in the company's
 * timezone with the company's words for it; the phone's clock is never trusted. Nothing is saved:
 * the sheet shows what was read and sends the deadline itself, so no deadline is ever set silently.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { isMissingEndpoint } from "../api/hooks";
import type { QuickAdd } from "../api/types";

/** How long typing has to pause before the text is read. */
export const PARSE_DELAY_MS = 250;

let unavailable = false;

/** Whether this backend reads dates in titles (false once it answered that it can't). */
export function quickAddAvailable(): boolean {
  return !unavailable;
}

/** For tests: forget that the backend lacked the endpoint. */
export function resetQuickAdd(): void {
  unavailable = false;
}

/** What the server reads in `text`, or null when it can't say (no endpoint, no network). */
export async function parseTask(company: number, text: string): Promise<QuickAdd | null> {
  if (unavailable || !text.trim()) return null;
  try {
    return await api<QuickAdd>(`/companies/${company}/tasks/parse/`, { json: { text } });
  } catch (error) {
    // A backend from before quick add: stop asking, the sheet works as it always did.
    if (isMissingEndpoint(error)) unavailable = true;
    return null;
  }
}

/** A deadline, urgency or a repeat: something worth showing back to the person. */
export function recognised(result: QuickAdd | null): result is QuickAdd {
  return Boolean(result && (result.due_at || (result.priority && result.priority !== "normal") || result.repeat));
}

const plain = (text: string) => text.toLocaleLowerCase().replace(/\s+/g, " ").trim();

/**
 * The server took words out of the title yet set nothing from them: a moment that has already
 * passed ("bugun 01:00" typed at 03:00, "bugun" after the day's default time). The answer has
 * no `past` flag, so this is how the sheet can say why no deadline was read.
 */
export function readPassed(text: string, result: QuickAdd | null): boolean {
  return Boolean(result && !recognised(result) && text.trim() && plain(result.title) !== plain(text));
}

/** What was read, apart from the title: dismissing "Not a date" holds while this stays the same. */
export function readSignature(result: QuickAdd): string {
  return [result.due_at ?? "", result.priority ?? "", result.repeat ?? ""].join("|");
}

type Parsed = { text: string; result: QuickAdd | null };

/**
 * The last reading of `text`, refreshed a moment after typing stops. While a newer reading is on
 * its way the last one stays on screen (no flicker); `stale` says so, and `flush` reads the text
 * now (the person pressed Add before the pause was over).
 */
export function useQuickAdd(company: number, text: string) {
  const [parsed, setParsed] = useState<Parsed>({ text: "", result: null });
  const latest = useRef(text);
  latest.current = text;

  useEffect(() => {
    if (!text.trim() || unavailable) {
      setParsed((old) => (old.text === text && old.result === null ? old : { text, result: null }));
      return;
    }
    const timer = window.setTimeout(() => {
      void parseTask(company, text).then((result) => {
        if (latest.current === text) setParsed({ text, result });
      });
    }, PARSE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [company, text]);

  const flush = useCallback(async (): Promise<QuickAdd | null> => {
    const now = latest.current;
    if (parsed.text === now) return parsed.result;
    const result = await parseTask(company, now);
    if (latest.current === now) setParsed({ text: now, result });
    return result;
  }, [company, parsed]);

  return { result: parsed.result, stale: parsed.text !== text, flush };
}
