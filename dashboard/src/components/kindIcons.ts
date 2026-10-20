/**
 * One icon per app, for things that carry an app-prefixed key ("timeoff.requests",
 * "members.people", "sales.cash_difference"): queue items, search hits, notifications and stream
 * rows. A key matches its full name first, then its last segment, then its app.
 */
import {
  Award,
  Banknote,
  BellRing,
  BookOpen,
  Boxes,
  CalendarDays,
  ClipboardCheck,
  Download,
  FileText,
  FolderKanban,
  Handshake,
  IdCard,
  Landmark,
  Lightbulb,
  ListTodo,
  MapPinCheck,
  Megaphone,
  MessagesSquare,
  Network,
  Receipt,
  Repeat,
  ScrollText,
  Sparkles,
  Store,
  TreePalm,
  UserPlus,
  Users,
} from "@lucide/vue";
import type { Component } from "vue";

const ICONS: Record<string, Component> = {
  // apps
  members: Users,
  tasks: ListTodo,
  routines: Repeat,
  reminders: BellRing,
  timeoff: TreePalm,
  attendance: MapPinCheck,
  hr: IdCard,
  lifecycle: Network,
  recognition: Award,
  sales: Store,
  inventory: Boxes,
  stock: Boxes,
  finance: Landmark,
  payroll: Banknote,
  crm: Handshake,
  announcements: Megaphone,
  groups: MessagesSquare,
  agenda: CalendarDays,
  knowledge: BookOpen,
  projects: FolderKanban,
  reports: ClipboardCheck,
  insights: Lightbulb,
  briefings: ScrollText,
  ai: Sparkles,
  exports: Download,
  inbox: BellRing,
  // common last segments
  people: Users,
  join: UserPlus,
  join_requests: UserPlus,
  requests: UserPlus,
  review: ClipboardCheck,
  claims: Receipt,
  invoices: Receipt,
  transactions: Banknote,
  shifts: Store,
  customers: Users,
  counterparties: Landmark,
  documents: FileText,
  policies: ScrollText,
  pages: BookOpen,
  deals: Handshake,
  advances: Banknote,
};

/** The icon for an app-prefixed key; `fallback` when nothing matches. */
export function iconForKind(key: string, fallback: Component = BellRing): Component {
  if (ICONS[key]) return ICONS[key];
  const parts = key.split(".");
  const last = parts[parts.length - 1] ?? "";
  return ICONS[last] ?? ICONS[parts[0] ?? ""] ?? fallback;
}
