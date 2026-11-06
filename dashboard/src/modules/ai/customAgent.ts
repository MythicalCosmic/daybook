/**
 * The agents an owner makes in their own words (briefs/v6-k.md), the New agent dialog's logic free
 * of Vue and the network: a form from a template, from an agent, or a fresh one; what the form
 * checks before it sends (the server checks again and says the same in the reader's language);
 * what it sends; and how its schedule reads on a template's card.
 */
import type { Translate } from "./agentPage";
import type { Agent, CustomAgentForm, CustomAgentInfo, CustomAgentTemplate, CustomDomainOption, CustomFrequency } from "./types";

/** The server's limits (apps.ai.agents.custom, apps.ai.models.CustomAgent.MAX_LIVE). */
export const CUSTOM_NAME_MAX = 60;
export const CUSTOM_JOB_MIN = 10;
export const CUSTOM_JOB_MAX = 2000;
export const CUSTOM_PEOPLE_MAX = 20;
export const CUSTOM_MAX = 10;

export const FREQUENCIES: readonly CustomFrequency[] = ["daily", "weekdays", "weekly", "monthly"];
export const MONTH_DAYS = Array.from({ length: 28 }, (_, index) => index + 1);
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

/** The domains the person may choose (what their own rights open). */
function readable(domains: readonly CustomDomainOption[]): Set<string> {
  return new Set(domains.filter((domain) => domain.available).map((domain) => domain.key));
}

/** A form written from scratch: every workday at 20:00, to me, reading the tasks (or the first it may). */
export function freshForm(domains: readonly CustomDomainOption[]): CustomAgentForm {
  const open = [...readable(domains)];
  return {
    name: "",
    job: "",
    color: "sky",
    template: "",
    frequency: "weekdays",
    at: "20:00",
    weekday: 0,
    month_day: 1,
    recipients: "me",
    people: [],
    group: null,
    domains: open.includes("tasks") ? ["tasks"] : open.slice(0, 1),
  };
}

/** A template's job in the form, reading only what the person may read of it. */
export function formFromTemplate(template: CustomAgentTemplate, domains: readonly CustomDomainOption[]): CustomAgentForm {
  const open = readable(domains);
  return {
    name: template.name.slice(0, CUSTOM_NAME_MAX),
    job: template.job,
    color: template.color,
    template: template.key,
    frequency: template.frequency,
    at: template.at,
    weekday: template.weekday ?? 0,
    month_day: template.month_day ?? 1,
    recipients: "me",
    people: [],
    group: null,
    domains: template.domains.filter((key) => open.has(key)),
  };
}

/** An agent as the form edits it. */
export function formFromAgent(agent: Pick<Agent, "name"> & { custom: CustomAgentInfo }): CustomAgentForm {
  const custom = agent.custom;
  return {
    name: agent.name,
    job: custom.job,
    color: custom.color,
    template: custom.template,
    frequency: custom.frequency,
    at: custom.at,
    weekday: custom.weekday ?? 0,
    month_day: custom.month_day ?? 1,
    recipients: custom.recipients,
    people: custom.people.map((person) => person.id),
    group: custom.group?.id ?? null,
    domains: custom.domains.map((domain) => domain.key),
  };
}

/** What is sent: the day only where the frequency has one, the people or the group only where they are who gets it. */
export function payload(form: CustomAgentForm): CustomAgentForm {
  return {
    ...form,
    name: form.name.trim(),
    job: form.job.trim(),
    weekday: form.frequency === "weekly" ? form.weekday : null,
    month_day: form.frequency === "monthly" ? form.month_day : null,
    people: form.recipients === "people" ? [...new Set(form.people)] : [],
    group: form.recipients === "group" ? form.group : null,
  };
}

export type CustomFormErrors = Partial<Record<keyof CustomAgentForm, string>>;

/** What the form says before it sends: i18n keys per field (none: it may go). */
export function checkForm(form: CustomAgentForm): CustomFormErrors {
  const errors: CustomFormErrors = {};
  const name = form.name.trim();
  const job = form.job.trim();
  if (!name) errors.name = "ai.custom.error.name";
  else if (name.length > CUSTOM_NAME_MAX) errors.name = "ai.custom.error.nameLong";
  if (job.length < CUSTOM_JOB_MIN) errors.job = "ai.custom.error.job";
  else if (job.length > CUSTOM_JOB_MAX) errors.job = "ai.custom.error.jobLong";
  if (!TIME.test(form.at)) errors.at = "ai.custom.error.at";
  if (form.frequency === "weekly" && (form.weekday === null || form.weekday < 0 || form.weekday > 6)) errors.weekday = "ai.custom.error.weekday";
  if (form.frequency === "monthly" && (form.month_day === null || form.month_day < 1 || form.month_day > 28)) errors.month_day = "ai.custom.error.monthDay";
  if (form.recipients === "people" && !form.people.length) errors.people = "ai.custom.error.people";
  else if (form.recipients === "people" && form.people.length > CUSTOM_PEOPLE_MAX) errors.people = "ai.custom.error.peopleMany";
  if (form.recipients === "group" && form.group === null) errors.group = "ai.custom.error.group";
  if (!form.domains.length) errors.domains = "ai.custom.error.domains";
  return errors;
}

/** When it runs, in a few words for a card: "Workdays · 20:00", "Mondays · 09:00", "Day 1 · 09:00". */
export function whenText(form: Pick<CustomAgentForm, "frequency" | "at" | "weekday" | "month_day">, t: Translate): string {
  if (form.frequency === "weekly") return t("ai.custom.when.weekly", { day: t(`common.weekday.long.${form.weekday ?? 0}`), time: form.at });
  if (form.frequency === "monthly") return t("ai.custom.when.monthly", { day: form.month_day ?? 1, time: form.at });
  return t(`ai.custom.when.${form.frequency}`, { time: form.at });
}

/** How many more of its own agents the company may have. */
export function agentsLeft(agents: readonly Pick<Agent, "custom">[] | undefined): number {
  return Math.max(0, CUSTOM_MAX - (agents ?? []).filter((agent) => agent.custom).length);
}
