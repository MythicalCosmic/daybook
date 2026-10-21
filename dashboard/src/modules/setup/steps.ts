/**
 * How a "Get started" step looks: an icon per step (by its key, then by its module), and the
 * title and one-line reason in the person's language (this module's dictionary knows the common
 * steps; any other step shows the label its module registered on the server).
 */
import {
  Banknote,
  Briefcase,
  CalendarDays,
  CircleCheck,
  Clock,
  IdCard,
  LayoutGrid,
  MapPin,
  MessagesSquare,
  ShoppingCart,
  Sparkles,
  UserPlus,
  Wallet,
  type LucideIcon,
} from "@lucide/vue";

import type { SetupStep } from "./types";

const BY_KEY: Record<string, LucideIcon> = {
  "companies.branches": MapPin,
  "companies.invite": UserPlus,
  "companies.modules": LayoutGrid,
  "groups.connect": MessagesSquare,
};

const BY_APP: Record<string, LucideIcon> = {
  members: Briefcase,
  finance: Wallet,
  sales: ShoppingCart,
  attendance: Clock,
  payroll: Banknote,
  timeoff: CalendarDays,
  ai: Sparkles,
  hr: IdCard,
};

export function stepIcon(step: Pick<SetupStep, "key">): LucideIcon {
  return BY_KEY[step.key] ?? BY_APP[step.key.split(".")[0]!] ?? CircleCheck;
}

type Translate = { t: (key: string) => string; te: (key: string) => boolean };

/** The dictionary key of a step ("companies.branches" → "setup.step.companies_branches"). */
const local = (step: SetupStep, part: "title" | "body") => `setup.step.${step.key.replace(/\./g, "_")}.${part}`;

export function stepTitle(step: SetupStep, { t, te }: Translate): string {
  return te(local(step, "title")) ? t(local(step, "title")) : step.label;
}

export function stepBody(step: SetupStep, { t, te }: Translate): string {
  return te(local(step, "body")) ? t(local(step, "body")) : step.description;
}
