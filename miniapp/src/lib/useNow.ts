import { useEffect, useState } from "react";

import { baseCurrency } from "../api/membership";
import { useI18n } from "../i18n";
import { useMember } from "../state/session";
import type { ViewContext } from "./taskView";

/** The current time, refreshed every half minute so "late by" labels keep up. */
export function useNow(intervalMs = 30_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

export function useViewContext(): ViewContext {
  const { t, locale } = useI18n();
  const member = useMember();
  const now = useNow();
  return { t, locale, timeZone: member.timeZone, now, currency: baseCurrency(member) };
}
