/**
 * The late card on a task: who heard about it once the reminders ran out. Without a name the
 * sentence and the caption under the last dot read on their own ("Your manager has been told.").
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ReminderInfo, Task } from "../api/types";
import { LOCALES, translate, type Lang } from "../i18n";
import type { ViewContext } from "../lib/taskView";
import { LateCard } from "./Reminders";

const NOW = new Date("2026-10-21T16:40:00+05:00");

function ctx(lang: Lang = "en"): ViewContext {
  return { t: (key, vars) => translate(lang, key, vars), timeZone: "Asia/Tashkent", locale: LOCALES[lang], now: NOW };
}

const task = {
  id: 1,
  kind: "daily",
  title: "Fridge temperature",
  status: "todo",
  due_at: "2026-10-21T09:00:00+05:00",
  actions: ["complete"],
} as unknown as Task;

function reminder(fields: Partial<ReminderInfo> = {}): ReminderInfo {
  return {
    every_minutes: 10,
    sent: 2,
    max_reminders: 0,
    escalate_after: 2,
    next_at: null,
    escalated_at: "2026-10-21T09:50:00+05:00",
    escalate_to: null,
    snooze_minutes: 10,
    snoozes_left: 1,
    snoozed_until: null,
    sent_times: [],
    ...fields,
  };
}

const show = (info: ReminderInfo, lang: Lang = "en") =>
  render(<LateCard task={task} reminder={info} ctx={ctx(lang)} onSnooze={() => undefined} snoozing={false} onAskHelp={() => undefined} />);

afterEach(cleanup);

describe("the late card's escalation", () => {
  it("starts the sentence with a capital when nobody is named", () => {
    const { container } = show(reminder());
    expect(container.textContent).toContain("until it's done. Your manager has been told.");
    expect(screen.getByText("Manager")).toBeTruthy();
    expect(container.textContent).not.toMatch(/\. your manager/);
  });

  it("names the person who was told when there is one", () => {
    const { container } = show(reminder({ escalate_to: "Bekzod Mirzayev" }));
    expect(container.textContent).toContain("Bekzod Mirzayev has been told.");
    expect(screen.getByText("Bekzod")).toBeTruthy();
  });

  it.each([
    ["uz", "Rahbaringiz xabardor qilindi.", "Rahbar"],
    ["ru", "Руководитель уже в курсе.", "Руководитель"],
  ] as const)("reads right in %s too", (lang, sentence, caption) => {
    const { container } = show(reminder(), lang);
    expect(container.textContent).toContain(sentence);
    expect(screen.getByText(caption)).toBeTruthy();
  });

  it("keeps the manager inside the sentence before it happens", () => {
    const { container } = show(reminder({ sent: 1, escalated_at: null, next_at: "2026-10-21T16:50:00+05:00" }));
    // The manager hears with the second reminder, due at the next one's time.
    expect(container.textContent).toContain("If it's still not done at 16:50, your manager gets a message.");
  });
});
