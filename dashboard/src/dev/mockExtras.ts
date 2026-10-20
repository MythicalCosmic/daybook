/**
 * More VITE_MOCK answers (dev only), for the design system and the inbox page: audit history,
 * exports, people and positions for the pickers, saved views, and a longer notification list.
 */
import type { Language, Notification } from "@/api/types";

import { L, type Localized } from "./mockData";

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

export const PEOPLE = [
  { id: 11, full_name: "Dilnoza Karimova", photo_url: null, position: { id: 7, name: "Owner" }, home_branch: { id: 1, name: "Office" } },
  { id: 12, full_name: "Bekzod Mirzayev", photo_url: null, position: { id: 2, name: "Shift lead" }, home_branch: { id: 1, name: "Chilonzor" } },
  { id: 13, full_name: "Alisher Valiyev", photo_url: null, position: { id: 3, name: "Sales floor" }, home_branch: { id: 1, name: "Chilonzor" } },
  { id: 14, full_name: "Madina Saidova", photo_url: null, position: { id: 1, name: "Cashier" }, home_branch: { id: 1, name: "Chilonzor" } },
  { id: 15, full_name: "Jasur Ergashev", photo_url: null, position: { id: 4, name: "Warehouse" }, home_branch: { id: 3, name: "Sergeli" } },
  { id: 16, full_name: "Nigora Tursunova", photo_url: null, position: { id: 5, name: "Delivery" }, home_branch: { id: 2, name: "Yunusobod" } },
  { id: 31, full_name: "Aziz Karimov", photo_url: null, position: { id: 1, name: "Cashier" }, home_branch: { id: 2, name: "Yunusobod" } },
];

export const POSITIONS = [
  { id: 1, name: "Cashier", color: "#c67139" },
  { id: 2, name: "Shift lead", color: "#4a6a8a" },
  { id: 3, name: "Sales floor", color: "#d1a040" },
  { id: 4, name: "Warehouse", color: "#8a5a7a" },
  { id: 5, name: "Delivery", color: "#3f8a83" },
];

/** `GET audit/records/`: rows as apps.audit.owner_api sends them (`details.changes` is {field: [old, new]}). */
export function auditRecords(language: Language) {
  const text = (l: Localized) => l[language];
  const row = (id: number, minutes: number, actor: { id: number | null; name: string } | null, action: string, label: Localized, details: Record<string, unknown>) => ({
    id,
    created_at: minutesAgo(minutes),
    action,
    action_label: text(label),
    actor,
    target_type: "transaction",
    target_id: 7002,
    target: "Korzinka · supplies",
    details,
  });
  return [
    row(5, 8, { id: 11, name: "Dilnoza Karimova" }, "finance.transaction_changed", L("Changed a transaction", "Изменила операцию", "Operatsiyani o‘zgartirdi"), {
      changes: { category: ["Other", "Supplies"], amount: ["400000.00", "450000.00"] },
    }),
    row(4, 60 * 3, { id: 12, name: "Bekzod Mirzayev" }, "finance.receipt_attached", L("Attached a receipt", "Приложил чек", "Chek biriktirdi"), {
      file: "korzinka-14-10.jpg",
    }),
    row(3, 60 * 27, { id: 12, name: "Bekzod Mirzayev" }, "finance.transaction_changed", L("Changed a transaction", "Изменил операцию", "Operatsiyani o‘zgartirdi"), {
      changes: { counterparty: [null, "Korzinka"], card_number: ["•••", "•••"] },
      reason: text(L("The shop was missing on the receipt", "На чеке не было магазина", "Chekda do‘kon nomi yo‘q edi")),
    }),
    row(2, 60 * 28, null, "finance.transaction_recorded", L("Recorded from the bot", "Записано из бота", "Botdan kiritildi"), {
      branch: "Chilonzor",
      account: text(L("Cash desk", "Касса", "Kassa")),
    }),
  ];
}

interface ExtraNotification extends Omit<Notification, "title" | "body" | "actions"> {
  title: Localized;
  body: Localized;
  actions: Notification["actions"];
}

/** Older notifications so the inbox page has history to page through. */
export const MORE_NOTIFICATIONS: ExtraNotification[] = [
  ["tasks.overdue", "warning", 60 * 5, L("3 tasks are late at Sergeli", "3 задачи просрочены в Сергели", "Sergelida 3 ta vazifa kechikdi"), L("The oldest is 2 hours past due.", "Самая старая просрочена на 2 часа.", "Eng eskisi 2 soat kechikkan.")],
  ["attendance.late", "info", 60 * 7, L("Aziz checked in 18 minutes late", "Азиз отметился с опозданием на 18 минут", "Aziz 18 daqiqa kechikib keldi"), L("Yunusobod · shift from 09:00", "Юнусабад · смена с 09:00", "Yunusobod · smena 09:00 dan")],
  ["finance.budget", "warning", 60 * 9, L("Supplies budget is at 92%", "Бюджет на хозтовары израсходован на 92%", "Xo‘jalik byudjetining 92% sarflandi"), L("With 11 days left in October.", "До конца октября 11 дней.", "Oktabr tugashiga 11 kun qoldi.")],
  ["sales.target", "info", 60 * 20, L("Chilonzor passed 80% of the October target", "Чиланзар выполнил 80% плана октября", "Chilonzor oktabr rejasining 80% ini bajardi"), L("48,1 mln of 60 mln so‘m.", "48,1 млн из 60 млн сум.", "60 mln so‘mdan 48,1 mln.")],
  ["hr.contract_ending", "warning", 60 * 33, L("Jasur’s contract ends on 31 October", "Договор Жасура заканчивается 31 октября", "Jasurning shartnomasi 31-oktabrda tugaydi"), L("Keep or extend it before then.", "Продлите или завершите его до этого дня.", "Shu kungacha uzaytiring yoki yakunlang.")],
  ["stock.low", "info", 60 * 40, L("6 products are running low", "6 товаров заканчиваются", "6 ta mahsulot tugab bormoqda"), L("Milk 1 l, sugar 1 kg, cups 250 ml and 3 more.", "Молоко 1 л, сахар 1 кг, стаканы 250 мл и ещё 3.", "Sut 1 l, shakar 1 kg, stakan 250 ml va yana 3 ta.")],
  ["payroll.paid", "info", 60 * 50, L("September payroll is marked paid", "Зарплата за сентябрь выплачена", "Sentabr ish haqi to‘langan deb belgilandi"), L("23 people · 58 900 000 so‘m", "23 человека · 58 900 000 сум", "23 kishi · 58 900 000 so‘m")],
  ["lifecycle.resignation", "warning", 60 * 70, L("Nigora asked to resign", "Нигора подала заявление об уходе", "Nigora ishdan ketish arizasini berdi"), L("Wants her last day to be 15 November.", "Просит последний день 15 ноября.", "Oxirgi kuni 15-noyabr bo‘lishini so‘ramoqda.")],
  ["projects.milestone", "info", 60 * 80, L("“Fit-out” milestone is done", "Этап «Ремонт» завершён", "“Ta’mirlash” bosqichi yakunlandi"), L("Chilonzor-2 opening · 64%", "Открытие Чиланзар-2 · 64%", "Chilonzor-2 ochilishi · 64%")],
].map(([kind, severity, minutes, title, body], index) => ({
  id: 920 + index,
  kind: kind as string,
  severity: severity as Notification["severity"],
  title: title as Localized,
  body: body as Localized,
  url: "",
  app_screen: "",
  target_type: "",
  target_id: null,
  created_at: minutesAgo(minutes as number),
  read_at: index % 3 === 0 ? null : minutesAgo((minutes as number) - 30),
  acted_at: null,
  acted_by: null,
  actor: null,
  actions: [],
  data: {},
}));

// Exports (`exports/`, `exports/{id}/`, `exports/kinds/`): a new one is building for two polls, then ready
// with a small CSV made in the browser.
export const EXPORTERS = [
  { kind: "tasks.tasks", label: L("Tasks", "Задачи", "Vazifalar"), sensitive: false },
  { kind: "members.people", label: L("Team", "Команда", "Jamoa"), sensitive: false },
  { kind: "finance.transactions", label: L("Transactions", "Операции", "Operatsiyalar"), sensitive: false },
  { kind: "payroll.payslips", label: L("Payslips", "Расчётные листы", "Hisob varaqalari"), sensitive: true },
];

interface MockExport {
  id: number;
  kind: string;
  format: "xlsx" | "csv";
  params: Record<string, unknown>;
  deliver_telegram: boolean;
  created: number;
  polls: number;
  failed?: boolean;
}

const jobs: MockExport[] = [
  { id: 38, kind: "finance.transactions", format: "xlsx", params: { from: "2026-10-01", to: "2026-10-20" }, deliver_telegram: true, created: Date.now() - 26 * 3600_000, polls: 9 },
  { id: 39, kind: "payroll.payslips", format: "xlsx", params: { run: 3 }, deliver_telegram: false, created: Date.now() - 50 * 3600_000, polls: 9, failed: true },
  { id: 40, kind: "tasks.tasks", format: "csv", params: { status: "late" }, deliver_telegram: false, created: Date.now() - 3 * 3600_000, polls: 9 },
];
let exportId = 40;

export function exportersFor(language: Language) {
  return EXPORTERS.map((e) => ({ kind: e.kind, label: e.label[language], sensitive: e.sensitive, formats: ["xlsx", "csv"], columns: [] }));
}

export function createExport(body: Record<string, unknown> | undefined): { id: number } {
  exportId += 1;
  const format = body?.format === "csv" ? "csv" : "xlsx";
  jobs.unshift({ id: exportId, kind: String(body?.kind ?? "tasks.tasks"), format, params: (body?.params as Record<string, unknown>) ?? {}, deliver_telegram: body?.deliver_telegram === true, created: Date.now(), polls: 0 });
  return { id: exportId };
}

function serialize(job: MockExport, language: Language, poll: boolean): Record<string, unknown> {
  if (poll) job.polls += 1;
  const exporter = EXPORTERS.find((e) => e.kind === job.kind);
  const status = job.failed ? "failed" : job.polls < 3 ? (job.polls < 1 ? "pending" : "running") : "ready";
  const day = new Date(job.created).toISOString().slice(0, 10);
  const name = `${job.kind.replace(".", "-")}-${day}.${job.format}`;
  return {
    id: job.id,
    kind: job.kind,
    label: exporter?.label[language] ?? job.kind,
    format: job.format,
    params: job.params,
    status,
    rows: status === "ready" ? 120 + job.id : null,
    error: status === "failed" ? L("The run has no payslips yet.", "В расчёте ещё нет листов.", "Hisobda hali varaqalar yo‘q.")[language] : "",
    deliver_telegram: job.deliver_telegram,
    sensitive: exporter?.sensitive ?? false,
    created_at: new Date(job.created).toISOString(),
    finished_at: status === "ready" || status === "failed" ? new Date(job.created + 40_000).toISOString() : null,
    expires_at: new Date(job.created + 7 * 86400_000).toISOString(),
    file_name: status === "ready" ? name : null,
    file_url: status === "ready" ? URL.createObjectURL(new Blob(["date,amount\n2026-10-20,450000.00\n"], { type: "text/csv" })) : null,
  };
}

export function exportList(language: Language) {
  // The list is a read too: building exports move on when someone looks.
  return jobs.map((job) => serialize(job, language, job.polls < 3));
}

export function exportStatus(id: number, language: Language): Record<string, unknown> | null {
  const job = jobs.find((item) => item.id === id);
  return job ? serialize(job, language, true) : null;
}
