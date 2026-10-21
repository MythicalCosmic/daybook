/** A policy as the form edits it, and back to what the API takes. */
import type { PolicyDraft } from "./components/PolicyForm.vue";
import { clock, parseClock } from "./schedule";
import type { Policy, PolicyInput } from "./types";

export function emptyDraft(name = ""): PolicyDraft {
  return {
    name,
    heads_up_minutes: 15,
    repeat_every_minutes: 20,
    max_reminders: 12,
    escalate_after: 3,
    quiet: true,
    quiet_from: "22:00",
    quiet_until: "08:00",
    quiet_days: [],
    snooze_minutes: 30,
    max_snoozes: 1,
    replace_previous: false,
    texts: [],
  };
}

const short = (value: string | null) => {
  const minutes = parseClock(value);
  return minutes === null ? null : clock(minutes);
};

export function toDraft(policy: Policy): PolicyDraft {
  return {
    name: policy.name,
    heads_up_minutes: policy.heads_up_minutes,
    repeat_every_minutes: policy.repeat_every_minutes,
    max_reminders: policy.max_reminders,
    escalate_after: policy.escalate_after,
    quiet: policy.quiet_from !== null && policy.quiet_until !== null,
    quiet_from: short(policy.quiet_from) ?? "22:00",
    quiet_until: short(policy.quiet_until) ?? "08:00",
    quiet_days: [...policy.quiet_days],
    snooze_minutes: policy.snooze_minutes,
    max_snoozes: policy.max_snoozes,
    replace_previous: policy.replace_previous,
    texts: policy.texts.map((text) => ({ ...text })),
  };
}

export function toInput(draft: PolicyDraft): PolicyInput {
  return {
    name: draft.name.trim(),
    heads_up_minutes: draft.heads_up_minutes,
    repeat_every_minutes: draft.repeat_every_minutes,
    max_reminders: draft.max_reminders,
    escalate_after: draft.escalate_after,
    quiet_from: draft.quiet ? draft.quiet_from : null,
    quiet_until: draft.quiet ? draft.quiet_until : null,
    quiet_days: draft.quiet_days,
    snooze_minutes: draft.snooze_minutes,
    max_snoozes: draft.max_snoozes,
    replace_previous: draft.replace_previous,
    texts: draft.texts.map((text) => ({ from_step: text.from_step, text: text.text.trim() })).filter((text) => text.text),
  };
}

/** One line about what a policy does: "15 min heads-up · every 20 min · manager at #3 · stops after #12". */
export function summary(policy: Pick<Policy, "heads_up_minutes" | "repeat_every_minutes" | "max_reminders" | "escalate_after">, t: (key: string, params?: Record<string, unknown>) => string): string {
  const parts: string[] = [];
  if (policy.heads_up_minutes) parts.push(t("reminders.summary.headsUp", { n: policy.heads_up_minutes }));
  parts.push(t("reminders.summary.every", { n: policy.repeat_every_minutes }));
  if (policy.escalate_after) parts.push(t("reminders.summary.escalate", { n: policy.escalate_after }));
  parts.push(policy.max_reminders ? t("reminders.summary.stops", { n: policy.max_reminders }) : t("reminders.summary.untilDone"));
  return parts.join(" · ");
}
