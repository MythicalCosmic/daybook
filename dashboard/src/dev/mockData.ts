/**
 * Demo data for the VITE_MOCK dev server: two companies of the demo owner (Dilnoza Karimova,
 * Telegram 1001, as seed_demo creates her), with queue items, notifications and search hits.
 * Text the backend would send already translated comes in uz, ru and en.
 */
import type { Company, Language, Me, Notification, QueueItem, QueueKind, SearchHit } from "@/api/types";
import { PERMS } from "@/core/perms";

export type Localized = Record<Language, string>;
export const L = (en: string, ru: string, uz: string): Localized => ({ en, ru, uz });

const OWNER_ROLE = L("Owner", "Владелец", "Egasi");

export interface MockCompany extends Omit<Company, "role"> {
  roleName: Localized;
}

export const companies: MockCompany[] = [
  {
    id: 1,
    name: "Demo Shop",
    logo: null,
    timezone: "Asia/Tashkent",
    base_currency: "UZS",
    language: "uz",
    features: ["finance", "sales", "stock", "attendance", "hr", "payroll", "ai", "projects", "knowledge", "calendar", "crm"],
    membership_id: 11,
    roleName: OWNER_ROLE,
    permissions: [...PERMS],
    branch_scope: null,
    branches: [
      { id: 1, name: "Chilonzor", code: "CHL" },
      { id: 2, name: "Yunusobod", code: "YUN" },
      { id: 3, name: "Sergeli", code: "SRG" },
    ],
    pending: 7,
    alerts: 1,
  },
  {
    id: 2,
    name: "Bahor Café",
    logo: null,
    timezone: "Asia/Tashkent",
    base_currency: "UZS",
    language: "uz",
    features: ["sales", "attendance", "hr"],
    membership_id: 21,
    roleName: OWNER_ROLE,
    permissions: [...PERMS],
    branch_scope: null,
    branches: [
      { id: 4, name: "Mirobod", code: "MRB" },
      { id: 5, name: "Shayxontohur", code: "SHX" },
    ],
    pending: 2,
    alerts: 0,
  },
];

export function meFor(language: Language): Me {
  return {
    user: {
      id: 7,
      telegram_id: 1001,
      first_name: "Dilnoza",
      last_name: "Karimova",
      full_name: "Dilnoza Karimova",
      username: "dilnoza_k",
      photo_url: null,
    },
    language,
    is_platform_admin: false,
    companies: companies.map(({ roleName, ...company }) => ({
      ...company,
      role: { id: company.id * 10, name: roleName[language], is_owner: true },
    })),
  };
}

export const pulseCounters: Record<number, Record<string, number>> = {
  1: {
    "queue.total": 7,
    "inbox.unread": 4,
    "inbox.critical": 1,
    "tasks.review": 2,
    "tasks.late_now": 3,
    "members.pending": 1,
    "timeoff.pending": 1,
    "sales.to_verify": 1,
    "finance.claims": 1,
    "finance.overdue": 2,
    "payroll.pending": 1,
    "hr.expiring": 3,
    "stock.low": 6,
    "attendance.not_in": 2,
    "insights.open": 3,
    "lifecycle.requested": 1,
  },
  2: {
    "queue.total": 2,
    "inbox.unread": 1,
    "inbox.critical": 0,
    "tasks.review": 1,
    "members.pending": 1,
    "attendance.not_in": 1,
  },
};

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

interface MockQueueItem extends Omit<QueueItem, "title" | "subtitle" | "actions"> {
  title: Localized;
  subtitle: Localized;
  actions: Array<Omit<QueueItem["actions"][number], "label"> & { label: Localized }>;
}

const approve = (endpoint: string) => ({ key: "approve", label: L("Approve", "Одобрить", "Tasdiqlash"), style: "primary" as const, method: "POST" as const, endpoint, needs_reason: false });
const reject = (endpoint: string) => ({ key: "reject", label: L("Reject", "Отклонить", "Rad etish"), style: "danger" as const, method: "POST" as const, endpoint, needs_reason: true });

export const queueKinds: Record<string, Localized> = {
  "members.join": L("Join requests", "Заявки на вступление", "Qo‘shilish so‘rovlari"),
  "sales.verify": L("Shifts to verify", "Смены на проверку", "Tekshiriladigan smenalar"),
  "tasks.review": L("Waiting for your check", "Ждут вашей проверки", "Tekshiruvingizni kutmoqda"),
  "finance.claims": L("Expense claims", "Авансовые отчёты", "Xarajat so‘rovlari"),
  "timeoff.request": L("Time off", "Отпуска", "Ta’tillar"),
  "payroll.advances": L("Advances", "Авансы", "Avanslar"),
};

export const queueItems: Record<number, MockQueueItem[]> = {
  1: [
    {
      kind: "sales.verify",
      id: 1042,
      title: L("Shift CHL-1042 · difference −15 000 so‘m", "Смена CHL-1042 · разница −15 000 сум", "CHL-1042 smena · farq −15 000 so‘m"),
      subtitle: L("Chilonzor · closed by Aziz Karimov at 22:07", "Чиланзар · закрыл Азиз Каримов в 22:07", "Chilonzor · Aziz Karimov 22:07 da yopdi"),
      created_at: minutesAgo(14),
      url: "sales/shifts/1042",
      actor: { id: 31, name: "Aziz Karimov", photo_url: null },
      actions: [
        { key: "verify", label: L("Verify", "Подтвердить", "Tasdiqlash"), style: "primary", method: "POST", endpoint: "/api/v1/owner/companies/1/sales/shifts/1042/verify/", needs_reason: false },
        { key: "dispute", label: L("Dispute", "Оспорить", "E’tiroz bildirish"), style: "danger", method: "POST", endpoint: "/api/v1/owner/companies/1/sales/shifts/1042/dispute/", needs_reason: true },
      ],
    },
    {
      kind: "members.join",
      id: 41,
      title: L("Sardor Rahimov wants to join", "Сардор Рахимов хочет присоединиться", "Sardor Rahimov qo‘shilmoqchi"),
      subtitle: L("Cashier · +998 90 412 33 21", "Кассир · +998 90 412 33 21", "Kassir · +998 90 412 33 21"),
      created_at: minutesAgo(38),
      url: "people/requests",
      actor: { id: 41, name: "Sardor Rahimov", photo_url: null },
      actions: [approve("/api/v1/owner/companies/1/join-requests/41/approve/"), reject("/api/v1/owner/companies/1/join-requests/41/reject/")],
    },
    {
      kind: "tasks.review",
      id: 345,
      title: L("Stock count: front shelves", "Пересчёт: передние полки", "Sanoq: old javonlar"),
      subtitle: L("Alisher Valiyev sent a photo · due 18:00", "Алишер Валиев прислал фото · срок 18:00", "Alisher Valiyev rasm yubordi · muddat 18:00"),
      created_at: minutesAgo(52),
      url: "tasks?task=345",
      actor: { id: 13, name: "Alisher Valiyev", photo_url: null },
      actions: [
        { key: "confirm", label: L("Accept", "Принять", "Qabul qilish"), style: "primary", method: "POST", endpoint: "/api/v1/owner/companies/1/tasks/345/confirm/", needs_reason: false },
        { key: "return", label: L("Send back", "Вернуть", "Qaytarish"), style: "danger", method: "POST", endpoint: "/api/v1/owner/companies/1/tasks/345/return/", needs_reason: true },
      ],
    },
    {
      kind: "tasks.review",
      id: 351,
      title: L("Fridge temperature check", "Проверка температуры холодильника", "Muzlatkich haroratini tekshirish"),
      subtitle: L("Madina Saidova · +4 °C, photo attached", "Мадина Саидова · +4 °C, фото приложено", "Madina Saidova · +4 °C, rasm ilova qilingan"),
      created_at: minutesAgo(75),
      url: "tasks?task=351",
      actor: { id: 14, name: "Madina Saidova", photo_url: null },
      actions: [
        { key: "confirm", label: L("Accept", "Принять", "Qabul qilish"), style: "primary", method: "POST", endpoint: "/api/v1/owner/companies/1/tasks/351/confirm/", needs_reason: false },
        { key: "return", label: L("Send back", "Вернуть", "Qaytarish"), style: "danger", method: "POST", endpoint: "/api/v1/owner/companies/1/tasks/351/return/", needs_reason: true },
      ],
    },
    {
      kind: "finance.claims",
      id: 88,
      title: L("Bekzod Mirzayev · 450 000 so‘m · Supplies", "Бекзод Мирзаев · 450 000 сум · Хозтовары", "Bekzod Mirzayev · 450 000 so‘m · Xo‘jalik mollari"),
      subtitle: L("Korzinka receipt, paid from his own money", "Чек Korzinka, оплачено из своих", "Korzinka cheki, o‘z pulidan to‘langan"),
      created_at: minutesAgo(130),
      url: "finance/claims?claim=88",
      actor: { id: 12, name: "Bekzod Mirzayev", photo_url: null },
      actions: [approve("/api/v1/owner/companies/1/finance/claims/88/approve/"), reject("/api/v1/owner/companies/1/finance/claims/88/reject/")],
    },
    {
      kind: "timeoff.request",
      id: 19,
      title: L("Madina Saidova · 24–26 Oct", "Мадина Саидова · 24–26 окт.", "Madina Saidova · 24–26-oktabr"),
      subtitle: L("Family wedding in Samarkand", "Свадьба в семье, Самарканд", "Samarqandda oilaviy to‘y"),
      created_at: minutesAgo(190),
      url: "time-off",
      actor: { id: 14, name: "Madina Saidova", photo_url: null },
      actions: [approve("/api/v1/owner/companies/1/time-off/19/approve/"), reject("/api/v1/owner/companies/1/time-off/19/reject/")],
    },
    {
      kind: "payroll.advances",
      id: 7,
      title: L("Nigora Tursunova asks 1 000 000 so‘m", "Нигора Турсунова просит 1 000 000 сум", "Nigora Tursunova 1 000 000 so‘m so‘ramoqda"),
      subtitle: L("Advance · cap 1 400 000 so‘m", "Аванс · лимит 1 400 000 сум", "Avans · chegara 1 400 000 so‘m"),
      created_at: minutesAgo(260),
      url: "payroll/advances",
      actor: { id: 16, name: "Nigora Tursunova", photo_url: null },
      actions: [approve("/api/v1/owner/companies/1/payroll/advances/7/approve/"), reject("/api/v1/owner/companies/1/payroll/advances/7/reject/")],
    },
  ],
  2: [
    {
      kind: "members.join",
      id: 61,
      title: L("Shahzoda Yusupova wants to join", "Шахзода Юсупова хочет присоединиться", "Shahzoda Yusupova qo‘shilmoqchi"),
      subtitle: L("Barista · +998 93 220 14 09", "Бариста · +998 93 220 14 09", "Barista · +998 93 220 14 09"),
      created_at: minutesAgo(22),
      url: "people/requests",
      actor: { id: 61, name: "Shahzoda Yusupova", photo_url: null },
      actions: [approve("/api/v1/owner/companies/2/join-requests/61/approve/"), reject("/api/v1/owner/companies/2/join-requests/61/reject/")],
    },
    {
      kind: "tasks.review",
      id: 512,
      title: L("Clean the coffee machine", "Почистить кофемашину", "Qahva mashinasini tozalash"),
      subtitle: L("Javohir Nazarov sent a photo", "Жавохир Назаров прислал фото", "Javohir Nazarov rasm yubordi"),
      created_at: minutesAgo(64),
      url: "tasks?task=512",
      actor: { id: 62, name: "Javohir Nazarov", photo_url: null },
      actions: [
        { key: "confirm", label: L("Accept", "Принять", "Qabul qilish"), style: "primary", method: "POST", endpoint: "/api/v1/owner/companies/2/tasks/512/confirm/", needs_reason: false },
        { key: "return", label: L("Send back", "Вернуть", "Qaytarish"), style: "danger", method: "POST", endpoint: "/api/v1/owner/companies/2/tasks/512/return/", needs_reason: true },
      ],
    },
  ],
};

export function queueFor(companyId: number, language: Language, kind?: string | null): { total: number; kinds: QueueKind[]; results: QueueItem[] } {
  const items = (queueItems[companyId] ?? []).filter((item) => !kind || item.kind === kind);
  const results: QueueItem[] = items.map((item) => ({
    ...item,
    title: item.title[language],
    subtitle: item.subtitle[language],
    actions: item.actions.map((action) => ({ ...action, label: action.label[language] })),
  }));
  const kinds: QueueKind[] = [];
  for (const item of results) {
    const found = kinds.find((k) => k.kind === item.kind);
    if (found) found.count += 1;
    else kinds.push({ kind: item.kind, label: queueKinds[item.kind]?.[language] ?? item.kind, count: 1 });
  }
  return { total: results.length, kinds, results };
}

interface MockNotification extends Omit<Notification, "title" | "body" | "actions"> {
  title: Localized;
  body: Localized;
  actions: Array<Omit<Notification["actions"][number], "label"> & { label: Localized }>;
}

export const notifications: Record<number, MockNotification[]> = {
  1: [
    {
      id: 901,
      kind: "sales.cash_difference",
      severity: "critical",
      title: L("Cash difference at Chilonzor: −15 000 so‘m", "Расхождение в кассе, Чиланзар: −15 000 сум", "Chilonzorda kassa farqi: −15 000 so‘m"),
      body: L("Shift CHL-1042 closed by Aziz Karimov. The tolerance is 10 000 so‘m.", "Смену CHL-1042 закрыл Азиз Каримов. Допуск — 10 000 сум.", "CHL-1042 smenani Aziz Karimov yopdi. Ruxsat etilgan farq 10 000 so‘m."),
      url: "sales/shifts/1042",
      created_at: minutesAgo(12),
      read_at: null,
      acted_at: null,
      actor: { id: 31, name: "Aziz Karimov", photo_url: null },
      actions: [],
      data: {},
    },
    {
      id: 902,
      kind: "sales.branch_not_opened",
      severity: "warning",
      title: L("Yunusobod hasn’t opened yet", "Юнусабад ещё не открылся", "Yunusobod hali ochilmadi"),
      body: L("No shift and no check-in 12 minutes after 09:00.", "Нет ни смены, ни отметки через 12 минут после 09:00.", "09:00 dan 12 daqiqa o‘tdi, smena ham, kelgan xodim ham yo‘q."),
      url: "attendance",
      created_at: minutesAgo(35),
      read_at: null,
      acted_at: null,
      actor: null,
      actions: [],
      data: {},
    },
    {
      id: 903,
      kind: "finance.claim",
      severity: "info",
      title: L("Expense claim: 450 000 so‘m", "Авансовый отчёт: 450 000 сум", "Xarajat so‘rovi: 450 000 so‘m"),
      body: L("Bekzod Mirzayev · Supplies · Korzinka", "Бекзод Мирзаев · Хозтовары · Korzinka", "Bekzod Mirzayev · Xo‘jalik mollari · Korzinka"),
      url: "finance/claims?claim=88",
      created_at: minutesAgo(130),
      read_at: null,
      acted_at: null,
      actor: { id: 12, name: "Bekzod Mirzayev", photo_url: null },
      actions: [
        { key: "approve", label: L("Approve", "Одобрить", "Tasdiqlash"), style: "primary" },
        { key: "reject", label: L("Reject", "Отклонить", "Rad etish"), style: "danger", needs_reason: true },
      ],
      data: {},
    },
    {
      id: 904,
      kind: "payroll.run_prepared",
      severity: "info",
      title: L("October payroll draft is ready", "Черновик зарплаты за октябрь готов", "Oktabr ish haqi qoralamasi tayyor"),
      body: L("23 people · 61 200 000 so‘m · 4 warnings", "23 человека · 61 200 000 сум · 4 предупреждения", "23 kishi · 61 200 000 so‘m · 4 ta ogohlantirish"),
      url: "payroll",
      created_at: minutesAgo(180),
      read_at: null,
      acted_at: null,
      actor: null,
      actions: [],
      data: {},
    },
    {
      id: 905,
      kind: "hr.document_expiring",
      severity: "warning",
      title: L("Medical book expires in 7 days", "Медкнижка истекает через 7 дней", "Tibbiy daftarcha muddati 7 kundan keyin tugaydi"),
      body: L("Jasur Ergashev · 27 Oct", "Жасур Эргашев · 27 окт.", "Jasur Ergashev · 27-oktabr"),
      url: "hr/documents",
      created_at: minutesAgo(60 * 26),
      read_at: minutesAgo(60 * 20),
      acted_at: null,
      actor: null,
      actions: [],
      data: {},
    },
    {
      id: 906,
      kind: "announcements.read",
      severity: "info",
      title: L("18 of 21 read “New uniform from Monday”", "18 из 21 прочитали «Новая форма с понедельника»", "21 kishidan 18 tasi “Dushanbadan yangi forma” e’lonini o‘qidi"),
      body: L("3 people haven’t opened it yet.", "3 человека ещё не открыли.", "3 kishi hali ochmadi."),
      url: "announcements",
      created_at: minutesAgo(60 * 30),
      read_at: minutesAgo(60 * 29),
      acted_at: null,
      actor: null,
      actions: [],
      data: {},
    },
  ],
  2: [
    {
      id: 951,
      kind: "attendance.no_show",
      severity: "warning",
      title: L("Javohir hasn’t checked in", "Жавохир не отметился", "Javohir kelganini belgilamadi"),
      body: L("Shift started at 08:00 at Mirobod.", "Смена началась в 08:00, Мирабад.", "Smena Mirobodda 08:00 da boshlangan."),
      url: "attendance",
      created_at: minutesAgo(40),
      read_at: null,
      acted_at: null,
      actor: null,
      actions: [],
      data: {},
    },
  ],
};

export function notificationsFor(companyId: number, language: Language, tab: string): Notification[] {
  return (notifications[companyId] ?? [])
    .filter((n) => tab !== "unread" || n.read_at === null)
    .map((n) => ({ ...n, title: n.title[language], body: n.body[language], actions: n.actions.map((a) => ({ ...a, label: a.label[language] })) }));
}

interface MockHit extends Omit<SearchHit, "subtitle"> {
  subtitle: Localized;
}

export const searchIndex: MockHit[] = [
  { type: "people", id: 11, title: "Dilnoza Karimova", subtitle: L("Owner · Office", "Владелец · Офис", "Egasi · Ofis"), url: "people/11" },
  { type: "people", id: 12, title: "Bekzod Mirzayev", subtitle: L("Manager · Shift lead", "Менеджер · Старший смены", "Menejer · Smena boshlig‘i"), url: "people/12" },
  { type: "people", id: 13, title: "Alisher Valiyev", subtitle: L("Sales floor · Chilonzor", "Торговый зал · Чиланзар", "Savdo zali · Chilonzor"), url: "people/13" },
  { type: "people", id: 14, title: "Madina Saidova", subtitle: L("Cashier · Chilonzor", "Кассир · Чиланзар", "Kassir · Chilonzor"), url: "people/14" },
  { type: "people", id: 15, title: "Jasur Ergashev", subtitle: L("Stock & warehouse", "Склад", "Ombor"), url: "people/15" },
  { type: "people", id: 16, title: "Nigora Tursunova", subtitle: L("Delivery · Yunusobod", "Доставка · Юнусабад", "Yetkazib berish · Yunusobod"), url: "people/16" },
  { type: "people", id: 31, title: "Aziz Karimov", subtitle: L("Cashier · Chilonzor", "Кассир · Чиланзар", "Kassir · Chilonzor"), url: "people/31" },
  { type: "tasks", id: 345, title: "Stock count: front shelves", subtitle: L("Alisher Valiyev · waiting for check", "Алишер Валиев · на проверке", "Alisher Valiyev · tekshiruvda"), url: "tasks?task=345" },
  { type: "tasks", id: 351, title: "Fridge temperature check", subtitle: L("Madina Saidova · daily", "Мадина Саидова · ежедневно", "Madina Saidova · har kuni"), url: "tasks?task=351" },
  { type: "tasks", id: 360, title: "Prepare the window display", subtitle: L("Alisher Valiyev · due Friday", "Алишер Валиев · срок в пятницу", "Alisher Valiyev · muddat juma"), url: "tasks?task=360" },
  { type: "shifts", id: 1042, title: "CHL-1042", subtitle: L("Chilonzor · difference −15 000 so‘m", "Чиланзар · разница −15 000 сум", "Chilonzor · farq −15 000 so‘m"), url: "sales/shifts/1042" },
  { type: "shifts", id: 388, title: "YUN-388", subtitle: L("Yunusobod · verified", "Юнусабад · подтверждена", "Yunusobod · tasdiqlangan"), url: "sales/shifts/388" },
  { type: "transactions", id: 7001, title: "Rent · October", subtitle: L("12 000 000 so‘m · Bank", "12 000 000 сум · Банк", "12 000 000 so‘m · Bank"), url: "finance/transactions?txn=7001" },
  { type: "transactions", id: 7002, title: "Korzinka · supplies", subtitle: L("450 000 so‘m · Cash desk", "450 000 сум · Касса", "450 000 so‘m · Kassa"), url: "finance/transactions?txn=7002" },
  { type: "projects", id: 1, title: "Chilonzor branch opening", subtitle: L("At risk · 64% done", "Под угрозой · 64% готово", "Xavf ostida · 64% bajarildi"), url: "projects/1" },
  { type: "projects", id: 2, title: "Website relaunch", subtitle: L("On track · 41% done", "По плану · 41% готово", "Reja bo‘yicha · 41% bajarildi"), url: "projects/2" },
  { type: "customers", id: 501, title: "Rustam Qodirov", subtitle: L("Nasiya · owes 2 400 000 so‘m", "Насия · долг 2 400 000 сум", "Nasiya · qarzi 2 400 000 so‘m"), url: "sales/customers/501" },
];

export function search(companyId: number, language: Language, q: string): SearchHit[] {
  const needle = q.toLocaleLowerCase();
  const perType = new Map<string, number>();
  const allowedTypes = companyId === 2 ? new Set(["people", "tasks", "shifts"]) : null;
  return searchIndex
    .filter((hit) => !allowedTypes || allowedTypes.has(hit.type))
    .filter((hit) => `${hit.title} ${hit.subtitle[language]} ${hit.subtitle.en}`.toLocaleLowerCase().includes(needle))
    .filter((hit) => {
      const count = perType.get(hit.type) ?? 0;
      perType.set(hit.type, count + 1);
      return count < 5;
    })
    .map((hit) => ({ ...hit, subtitle: hit.subtitle[language] }));
}
