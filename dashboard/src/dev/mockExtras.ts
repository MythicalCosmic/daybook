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

export function auditRecords(language: Language) {
  const text = (l: Localized) => l[language];
  return [
    {
      id: 5,
      created_at: minutesAgo(8),
      actor: { id: 11, name: "Dilnoza Karimova", photo_url: null },
      action: "finance.transaction.updated",
      action_label: text(L("changed the transaction", "изменила операцию", "operatsiyani o‘zgartirdi")),
      changes: [
        { field: "category", label: text(L("Category", "Категория", "Toifa")), old: "Other", new: "Supplies" },
        { field: "amount", label: text(L("Amount", "Сумма", "Summa")), old: "400 000", new: "450 000" },
      ],
    },
    {
      id: 4,
      created_at: minutesAgo(60 * 3),
      actor: { id: 12, name: "Bekzod Mirzayev", photo_url: null },
      action: "finance.transaction.receipt",
      action_label: text(L("attached a receipt", "приложил чек", "chek biriktirdi")),
      summary: "korzinka-14-10.jpg",
    },
    {
      id: 3,
      created_at: minutesAgo(60 * 27),
      actor: { id: 12, name: "Bekzod Mirzayev", photo_url: null },
      action: "finance.transaction.updated",
      action_label: text(L("changed the counterparty", "изменил контрагента", "kontragentni o‘zgartirdi")),
      changes: [
        { field: "counterparty", label: text(L("Counterparty", "Контрагент", "Kontragent")), old: null, new: "Korzinka" },
        { field: "card", label: text(L("Card number", "Номер карты", "Karta raqami")), old: "•••", new: "•••" },
      ],
    },
    {
      id: 2,
      created_at: minutesAgo(60 * 28),
      actor: null,
      action: "finance.transaction.created",
      action_label: text(L("Recorded from the bot", "Записано из бота", "Botdan kiritildi")),
      summary: text(L("Expense · Cash desk · Chilonzor", "Расход · Касса · Чиланзар", "Xarajat · Kassa · Chilonzor")),
    },
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
  created_at: minutesAgo(minutes as number),
  read_at: index % 3 === 0 ? null : minutesAgo((minutes as number) - 30),
  acted_at: null,
  actor: null,
  actions: [],
  data: {},
}));

// Exports: ready on the second poll, with a small CSV made in the browser.
const exportsState = new Map<number, number>();
let exportId = 40;

export function createExport(): { id: number } {
  exportId += 1;
  exportsState.set(exportId, 0);
  return { id: exportId };
}

export function exportStatus(id: number): Record<string, unknown> {
  const polls = (exportsState.get(id) ?? 0) + 1;
  exportsState.set(id, polls);
  if (polls < 2) return { id, kind: "mock", format: "xlsx", status: "running", rows: null, file_url: null };
  const url = URL.createObjectURL(new Blob(["date,amount\n2026-10-20,450000.00\n"], { type: "text/csv" }));
  return { id, kind: "mock", format: "csv", status: "ready", rows: 1, file_url: url };
}
