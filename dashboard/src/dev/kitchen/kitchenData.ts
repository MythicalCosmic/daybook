/**
 * Demo data for the component kitchen (dev only): a shop's people, transactions, tasks, projects
 * and numbers, deterministic so screenshots compare run to run.
 */
import type { BranchRef } from "@/api/types";
import type { CalendarItem } from "@/components/calendarItems";
import type { GanttRow } from "@/components/gantt";
import type { KanbanColumn } from "@/components/kanban";
import type { PersonOption, PositionOption } from "@/components/pickers";
import type { TreeNode } from "@/components/tree";
import { addDays, startOfWeek } from "@/lib/dates";

/** A small deterministic random generator. */
export function seeded(seed: number): () => number {
  let state = seed % 2147483647;
  if (state <= 0) state += 2147483646;
  return () => (state = (state * 16807) % 2147483647) / 2147483647;
}

export const PEOPLE: PersonOption[] = [
  { id: 11, name: "Dilnoza Karimova", subtitle: "Owner · Office" },
  { id: 12, name: "Bekzod Mirzayev", subtitle: "Shift lead · Chilonzor" },
  { id: 13, name: "Alisher Valiyev", subtitle: "Sales floor · Chilonzor" },
  { id: 14, name: "Madina Saidova", subtitle: "Cashier · Chilonzor" },
  { id: 15, name: "Jasur Ergashev", subtitle: "Warehouse · Sergeli" },
  { id: 16, name: "Nigora Tursunova", subtitle: "Delivery · Yunusobod" },
  { id: 31, name: "Aziz Karimov", subtitle: "Cashier · Yunusobod" },
  { id: 32, name: "G‘ayrat Ro‘ziyev", subtitle: "Barista · Mirobod" },
  { id: 33, name: "Shahzoda Yusupova", subtitle: "Barista · Mirobod" },
  { id: 34, name: "Sardor Rahimov", subtitle: "Cashier · Sergeli" },
];

export const POSITIONS: PositionOption[] = [
  { id: 1, name: "Cashier", color: "var(--c-chart-1)" },
  { id: 2, name: "Shift lead", color: "var(--c-chart-3)" },
  { id: 3, name: "Sales floor", color: "var(--c-chart-4)" },
  { id: 4, name: "Warehouse", color: "var(--c-chart-5)" },
  { id: 5, name: "Delivery", color: "var(--c-chart-6)" },
  { id: 6, name: "Barista", color: "var(--c-chart-2)" },
];

export const BRANCHES: BranchRef[] = [
  { id: 1, name: "Chilonzor", code: "CHL" },
  { id: 2, name: "Yunusobod", code: "YUN" },
  { id: 3, name: "Sergeli", code: "SRG" },
];

export interface DemoTransaction {
  id: number;
  date: string;
  description: string;
  person: PersonOption;
  category: string;
  branch: string;
  amount: string;
  status: "posted" | "pending" | "void";
}

const CATEGORIES = ["Rent", "Supplies", "Salaries", "Utilities", "Delivery", "Marketing", "Repairs"];
const DESCRIPTIONS = ["Korzinka · supplies", "Electricity · October", "Shift CHL-1042 cash", "Packaging from Makro", "Fuel for delivery", "Instagram ads", "Fridge repair", "Card terminal payout", "Water and coffee", "Advance · Nigora"];

export function transactions(count: number, today: string): DemoTransaction[] {
  const random = seeded(42);
  return Array.from({ length: count }, (_, i) => {
    const income = random() < 0.35;
    const whole = Math.round((income ? 400_000 + random() * 9_000_000 : 40_000 + random() * 2_400_000) / 1000) * 1000;
    return {
      id: 7000 + i,
      date: addDays(today, -Math.floor(i / 6)),
      description: DESCRIPTIONS[Math.floor(random() * DESCRIPTIONS.length)]!,
      person: PEOPLE[Math.floor(random() * PEOPLE.length)]!,
      category: income ? "Sales" : CATEGORIES[Math.floor(random() * CATEGORIES.length)]!,
      branch: BRANCHES[Math.floor(random() * BRANCHES.length)]!.name,
      amount: `${income ? "" : "-"}${whole}.00`,
      status: random() < 0.08 ? "void" : random() < 0.2 ? "pending" : "posted",
    };
  });
}

/** Daily series for charts: `count` days ending today. */
export function dailySeries(today: string, count: number, base: number, swing: number, seed: number): { days: string[]; values: string[] } {
  const random = seeded(seed);
  const days: string[] = [];
  const values: string[] = [];
  for (let i = count - 1; i >= 0; i--) {
    const day = addDays(today, -i);
    const weekday = new Date(`${day}T00:00:00Z`).getUTCDay();
    const weekend = weekday === 0 || weekday === 6 ? 1.25 : 1;
    days.push(day);
    values.push(`${Math.round(((base + (random() - 0.4) * swing) * weekend) / 1000) * 1000}.00`);
  }
  return { days, values };
}

export interface DemoCard {
  id: number;
  key: string;
  title: string;
  list: string;
  assignee: PersonOption;
  due: string;
  labels: Array<{ name: string; color: string }>;
  checklist: [number, number];
  /** Columns this card may move to (the server's `actions`). */
  allowed: string[];
}

export const BOARD_COLUMNS: KanbanColumn[] = [
  { id: "backlog", title: "Backlog", color: "var(--c-chart-8)" },
  { id: "todo", title: "To do", color: "var(--c-chart-3)" },
  { id: "doing", title: "In progress", color: "var(--c-chart-1)", wipLimit: 3 },
  { id: "review", title: "Review", color: "var(--c-chart-4)", wipLimit: 2 },
  { id: "done", title: "Done", color: "var(--c-chart-2)" },
];

export function boardCards(today: string): DemoCard[] {
  const label = (name: string, n: number) => ({ name, color: `var(--c-chart-${n})` });
  const all = ["backlog", "todo", "doing", "review", "done"];
  const card = (id: number, title: string, list: string, person: number, due: number, labels: DemoCard["labels"], checklist: [number, number], allowed = all) => ({
    id,
    key: `RENO-${id}`,
    title,
    list,
    assignee: PEOPLE[person]!,
    due: addDays(today, due),
    labels,
    checklist,
    allowed,
  });
  return [
    card(11, "Order signage for the new branch", "backlog", 0, 12, [label("Design", 5)], [0, 3]),
    card(12, "Get the fire safety certificate", "backlog", 1, 20, [label("Legal", 3)], [1, 4]),
    card(14, "Hire two cashiers", "todo", 0, 6, [label("Hiring", 4)], [2, 5]),
    card(15, "Install the card terminal", "todo", 4, 3, [label("Equipment", 6)], [0, 2]),
    card(16, "Paint the sales floor", "doing", 2, 1, [label("Fit-out", 1)], [3, 6]),
    card(17, "Shelving and fridges", "doing", 4, -1, [label("Fit-out", 1), label("Equipment", 6)], [5, 8], ["doing", "review"]),
    card(18, "Opening day stock list", "doing", 3, 4, [label("Stock", 2)], [1, 1]),
    card(19, "Opening announcement for the team", "review", 1, 2, [label("Comms", 4)], [2, 2], ["doing", "review", "done"]),
    card(20, "Lease agreement signed", "done", 0, -9, [label("Legal", 3)], [4, 4]),
  ];
}

export function calendarItems(today: string): CalendarItem[] {
  const monday = startOfWeek(today);
  const at = (day: string, time: string) => `${day}T${time}:00+05:00`;
  return [
    { id: "h1", kind: "holiday", title: "Teachers’ day", start: addDays(today, 11), all_day: true, color: "var(--c-danger)" },
    { id: "l1", kind: "leave", title: "Madina · leave", start: addDays(monday, 2), end: addDays(monday, 4), all_day: true, color: "var(--c-chart-6)" },
    { id: "p1", kind: "payroll", title: "October payroll", start: addDays(today, 10), all_day: true, color: "var(--c-chart-5)" },
    { id: "t1", kind: "tax", title: "VAT return due", start: addDays(today, 5), all_day: true, color: "var(--c-chart-4)" },
    { id: "m1", kind: "meeting", title: "Branch managers", start: at(addDays(monday, 0), "09:30"), end: at(addDays(monday, 0), "10:30"), subtitle: "Office" },
    { id: "m2", kind: "meeting", title: "Supplier: Makro", start: at(addDays(monday, 1), "11:00"), end: at(addDays(monday, 1), "12:00"), subtitle: "Chilonzor" },
    { id: "m3", kind: "interview", title: "Interview · cashier", start: at(addDays(monday, 1), "11:30"), end: at(addDays(monday, 1), "12:15"), subtitle: "Bekzod" },
    { id: "m4", kind: "milestone", title: "Soft launch", start: at(addDays(monday, 3), "15:00"), end: at(addDays(monday, 3), "17:00"), subtitle: "RENO" },
    { id: "m5", kind: "meeting", title: "Inventory count", start: at(addDays(monday, 4), "08:00"), end: at(addDays(monday, 4), "10:00"), subtitle: "Sergeli" },
    { id: "m6", kind: "training", title: "Card terminal training", start: at(addDays(today, -6), "14:00"), end: at(addDays(today, -6), "15:00") },
    { id: "m7", kind: "meeting", title: "Accountant", start: at(addDays(today, -2), "10:00"), end: at(addDays(today, -2), "11:00") },
    { id: "m8", kind: "delivery", title: "Coca-Cola delivery", start: at(addDays(today, 1), "07:30"), end: at(addDays(today, 1), "08:00") },
  ];
}

export function ganttRows(today: string): GanttRow[] {
  return [
    {
      id: "reno",
      label: "Chilonzor-2 opening",
      sublabel: "RENO · 64%",
      color: "var(--c-chart-1)",
      bars: [{ id: "reno-1", start: addDays(today, -18), end: addDays(today, 9), label: "Fit-out", progress: 64 }],
      milestones: [{ id: "reno-m", date: addDays(today, 12), label: "Soft launch" }],
    },
    {
      id: "web",
      label: "Website relaunch",
      sublabel: "WEB · 41%",
      color: "var(--c-chart-3)",
      bars: [
        { id: "web-1", start: addDays(today, -10), end: addDays(today, 4), label: "Design", progress: 90 },
        { id: "web-2", start: addDays(today, 5), end: addDays(today, 24), label: "Build", progress: 0 },
      ],
      milestones: [{ id: "web-m", date: addDays(today, 25), label: "Go live" }],
    },
    {
      id: "crm",
      label: "Loyalty cards",
      sublabel: "LOY · 12%",
      color: "var(--c-chart-4)",
      bars: [{ id: "crm-1", start: addDays(today, -3), end: addDays(today, 30), label: "Rollout", progress: 12 }],
    },
    {
      id: "hire",
      label: "Hiring: 6 cashiers",
      sublabel: "HR",
      color: "var(--c-chart-6)",
      bars: [{ id: "hire-1", start: addDays(today, -25), end: addDays(today, -5), label: "Round 1", progress: 100 }, { id: "hire-2", start: addDays(today, 2), end: addDays(today, 16), label: "Round 2" }],
      milestones: [{ id: "hire-m", date: addDays(today, -5), label: "4 hired", done: true }],
    },
    {
      id: "inv",
      label: "Stock count",
      sublabel: "OPS",
      color: "var(--c-chart-5)",
      bars: [{ id: "inv-1", start: addDays(today, 6), end: addDays(today, 7), label: "Count" }],
    },
  ];
}

export const KNOWLEDGE: TreeNode[] = [
  {
    id: "ops",
    label: "Operations",
    badge: 12,
    children: [
      { id: "open", label: "Opening the shop", meta: "Read by 18" },
      { id: "close", label: "Closing and the cash count", children: [{ id: "z", label: "Z-report photos" }, { id: "safe", label: "Handing cash to the safe" }] },
      { id: "fridge", label: "Fridge temperatures" },
    ],
  },
  { id: "people", label: "People and HR", badge: 5, children: [{ id: "leave", label: "How to ask for leave" }, { id: "uniform", label: "Uniform" }] },
  { id: "money", label: "Money", children: [{ id: "claims", label: "Expense claims" }] },
  { id: "archive", label: "Archive", locked: true },
];

/** A soft generated photo for proofs and the lightbox (SVG data URI). */
export function photo(label: string, hue: number, seed = 1): string {
  const random = seeded(seed * 97 + hue);
  const shapes = Array.from({ length: 6 }, () => {
    const x = Math.round(random() * 400);
    const y = Math.round(random() * 300);
    const r = Math.round(30 + random() * 90);
    return `<circle cx="${x}" cy="${y}" r="${r}" fill="hsl(${hue + Math.round(random() * 40)} 45% ${55 + Math.round(random() * 20)}%)" opacity="0.55"/>`;
  }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue} 40% 82%)"/><stop offset="1" stop-color="hsl(${hue + 30} 35% 62%)"/></linearGradient></defs><rect width="400" height="300" fill="url(#g)"/>${shapes}<rect x="20" y="236" width="${label.length * 11 + 28}" height="40" rx="10" fill="rgba(20,18,16,.55)"/><text x="34" y="263" font-family="sans-serif" font-size="20" font-weight="600" fill="#fff">${label}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
