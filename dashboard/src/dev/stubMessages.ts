/**
 * Titles for the dev placeholder modules (one per catalog entry) and the placeholder pages' own
 * strings ("dev." keys). Real modules bring their own dictionaries; these never ship.
 */
import type { Messages, ModuleMessages } from "@/core/modules";

type Triple = [en: string, ru: string, uz: string];

export const STUB_TITLES: Record<string, { title: Triple; pages: Record<string, Triple> }> = {
  overview: { title: ["Overview", "Обзор", "Umumiy ko‘rinish"], pages: { today: ["Today", "Сегодня", "Bugun"] } },
  inbox: { title: ["Inbox", "Входящие", "Kiruvchilar"], pages: { inbox: ["Inbox", "Входящие", "Kiruvchilar"] } },
  tasks: {
    title: ["Tasks", "Задачи", "Vazifalar"],
    pages: { all: ["All tasks", "Все задачи", "Barcha vazifalar"], reviews: ["Reviews", "На проверке", "Tekshiruvda"], photos: ["Photo wall", "Фотостена", "Foto devor"] },
  },
  projects: {
    title: ["Projects", "Проекты", "Loyihalar"],
    pages: { all: ["All projects", "Все проекты", "Barcha loyihalar"], roadmap: ["Roadmap", "Дорожная карта", "Yo‘l xaritasi"] },
  },
  routines: { title: ["Routines", "Регламенты", "Kundalik ishlar"], pages: { all: ["Routines", "Регламенты", "Kundalik ishlar"] } },
  reminders: { title: ["Reminders", "Напоминания", "Eslatmalar"], pages: { policies: ["Reminder policies", "Правила напоминаний", "Eslatma qoidalari"] } },
  people: {
    title: ["Team", "Команда", "Jamoa"],
    pages: {
      team: ["Directory", "Сотрудники", "Xodimlar"],
      requests: ["Join requests", "Заявки", "So‘rovlar"],
      roles: ["Roles", "Роли", "Rollar"],
      positions: ["Positions", "Должности", "Lavozimlar"],
    },
  },
  attendance: {
    title: ["Attendance", "Посещаемость", "Davomat"],
    pages: {
      today: ["Today", "Сегодня", "Bugun"],
      timesheet: ["Timesheet", "Табель", "Tabel"],
      roster: ["Roster", "График смен", "Smena jadvali"],
      schedules: ["Schedules", "Расписания", "Ish tartiblari"],
      swaps: ["Swaps", "Обмены сменами", "Smena almashuvlari"],
      corrections: ["Corrections", "Исправления", "Tuzatishlar"],
    },
  },
  timeoff: {
    title: ["Time off", "Отпуска", "Ta’tillar"],
    pages: {
      calendar: ["Calendar", "Календарь", "Kalendar"],
      holidays: ["Holidays", "Праздники", "Bayramlar"],
      balances: ["Balances", "Остатки", "Qoldiqlar"],
      types: ["Leave types", "Виды отпусков", "Ta’til turlari"],
    },
  },
  hr: {
    title: ["HR", "Кадры", "Kadrlar"],
    pages: {
      documents: ["Documents", "Документы", "Hujjatlar"],
      contracts: ["Contracts", "Договоры", "Shartnomalar"],
      templates: ["Contract templates", "Шаблоны договоров", "Shartnoma shablonlari"],
      policies: ["Policies", "Правила", "Qoidalar"],
      celebrations: ["Celebrations", "Поздравления", "Tabriklar"],
      hiring: ["Hiring", "Найм", "Ishga olish"],
    },
  },
  lifecycle: {
    title: ["Lifecycle", "Кадровые события", "Kadrlar harakati"],
    pages: {
      org: ["Org chart", "Оргструктура", "Tashkiliy tuzilma"],
      discipline: ["Discipline", "Взыскания", "Intizom"],
      suspensions: ["Suspensions", "Отстранения", "Chetlatishlar"],
      terminations: ["Terminations", "Увольнения", "Ishdan bo‘shatishlar"],
      changes: ["Job changes", "Кадровые изменения", "Lavozim o‘zgarishlari"],
      equipment: ["Equipment", "Оборудование", "Jihozlar"],
      reviews: ["Reviews", "Оценка", "Baholash"],
    },
  },
  recognition: { title: ["Recognition", "Признание", "E’tirof"], pages: { kudos: ["Kudos", "Благодарности", "Rahmatlar"] } },
  sales: {
    title: ["Sales", "Продажи", "Savdo"],
    pages: {
      overview: ["Overview", "Обзор", "Umumiy"],
      shifts: ["Shifts", "Смены", "Smenalar"],
      cash: ["Cash", "Наличные", "Naqd pul"],
      entries: ["Entries", "Записи", "Yozuvlar"],
      targets: ["Targets", "Планы", "Rejalar"],
      invoices: ["Invoices", "Счета", "Hisob-fakturalar"],
      customers: ["Customers", "Клиенты", "Mijozlar"],
    },
  },
  stock: {
    title: ["Stock", "Склад", "Ombor"],
    pages: {
      products: ["Products", "Товары", "Mahsulotlar"],
      levels: ["Stock levels", "Остатки", "Qoldiqlar"],
      receipts: ["Goods receipts", "Приходы", "Kirimlar"],
      counts: ["Stock counts", "Инвентаризации", "Inventarizatsiya"],
    },
  },
  finance: {
    title: ["Finance", "Финансы", "Moliya"],
    pages: {
      overview: ["Overview", "Обзор", "Umumiy"],
      accounts: ["Accounts", "Счета", "Hisoblar"],
      transactions: ["Transactions", "Операции", "Operatsiyalar"],
      debts: ["Debts", "Долги", "Qarzlar"],
      counterparties: ["Counterparties", "Контрагенты", "Kontragentlar"],
      reports: ["Reports", "Отчёты", "Hisobotlar"],
      budgets: ["Budgets", "Бюджеты", "Byudjetlar"],
      recurring: ["Recurring bills", "Регулярные платежи", "Doimiy to‘lovlar"],
      calendar: ["Payment calendar", "Платёжный календарь", "To‘lov kalendari"],
      claims: ["Expense claims", "Авансовые отчёты", "Xarajat so‘rovlari"],
    },
  },
  payroll: {
    title: ["Payroll", "Зарплата", "Ish haqi"],
    pages: {
      runs: ["Payroll runs", "Расчёты", "Hisob-kitoblar"],
      pay: ["Pay setups", "Оклады", "Maosh sozlamalari"],
      adjustments: ["Bonuses & fines", "Премии и штрафы", "Mukofot va jarimalar"],
      rules: ["Rules", "Правила", "Qoidalar"],
      advances: ["Advances", "Авансы", "Avanslar"],
    },
  },
  crm: { title: ["CRM", "CRM", "CRM"], pages: { deals: ["Deals", "Сделки", "Bitimlar"] } },
  comms: { title: ["Announcements", "Объявления", "E’lonlar"], pages: { announcements: ["Announcements", "Объявления", "E’lonlar"] } },
  groups: { title: ["Groups", "Группы", "Guruhlar"], pages: { groups: ["Groups", "Группы", "Guruhlar"] } },
  agenda: { title: ["Calendar", "Календарь", "Kalendar"], pages: { calendar: ["Calendar", "Календарь", "Kalendar"] } },
  knowledge: { title: ["Knowledge", "База знаний", "Bilimlar bazasi"], pages: { spaces: ["Knowledge", "База знаний", "Bilimlar bazasi"] } },
  reports: {
    title: ["Reports", "Отчёты", "Hisobotlar"],
    pages: { team: ["Team KPIs", "Показатели команды", "Jamoa ko‘rsatkichlari"], routines: ["Routine compliance", "Выполнение регламентов", "Kundalik ishlar ijrosi"] },
  },
  insights: {
    title: ["Insights", "Инсайты", "Kuzatuvlar"],
    pages: { insights: ["Insights", "Инсайты", "Kuzatuvlar"], briefings: ["Briefings", "Сводки", "Brifinglar"] },
  },
  ai: { title: ["AI assistant", "ИИ-ассистент", "AI yordamchi"], pages: { assistant: ["Assistant", "Ассистент", "Yordamchi"] } },
  settings: { title: ["Settings", "Настройки", "Sozlamalar"], pages: { panels: ["Settings", "Настройки", "Sozlamalar"] } },
  exports: { title: ["Exports", "Выгрузки", "Eksportlar"], pages: { list: ["My exports", "Мои выгрузки", "Eksportlarim"] } },
  audit: { title: ["Audit log", "Журнал действий", "Harakatlar jurnali"], pages: { log: ["Audit log", "Журнал действий", "Harakatlar jurnali"] } },
};

/** Placeholder pages' own strings, merged as-is (not through a module namespace). */
export const DEV_MESSAGES: ModuleMessages = {
  en: {
    "dev.stub.badge": "Placeholder",
    "dev.stub.title": "Arrives with package {pkg}",
    "dev.stub.body": "The mock build shows where this page lives. The module that owns it replaces this placeholder.",
    "dev.overview.morning": "Good morning, {name}",
    "dev.overview.afternoon": "Good afternoon, {name}",
    "dev.overview.evening": "Good evening, {name}",
    "dev.overview.night": "Working late, {name}",
    "dev.overview.sales": "Sales today",
    "dev.overview.tasks": "Tasks done",
    "dev.overview.present": "Present now",
    "dev.overview.cash": "Cash now",
    "dev.overview.vsLastWeek": "vs last Tuesday",
    "dev.overview.ofTotal": "of {n}",
    "dev.overview.branches": "Branches",
    "dev.overview.opened": "Opened {time} by {name}",
    "dev.overview.notOpened": "Not opened · +{n} min",
    "dev.overview.staff": "Staff",
    "dev.overview.tills": "Tills",
    "dev.overview.needsYou": "Needs you",
    "dev.overview.activity": "Activity",
    "dev.overview.preview": "Preview of package A’s Overview",
    "dev.portfolio.title": "Portfolio",
    "dev.newCompany.name": "Company name",
    "dev.newCompany.placeholder": "e.g. Bahor Bakery",
    "dev.newCompany.note": "Package A creates the company here. In the mock build this form only closes.",
  },
  ru: {
    "dev.stub.badge": "Заглушка",
    "dev.stub.title": "Появится в пакете {pkg}",
    "dev.stub.body": "Мок-сборка показывает, где будет эта страница. Модуль-владелец заменит заглушку.",
    "dev.overview.morning": "Доброе утро, {name}",
    "dev.overview.afternoon": "Добрый день, {name}",
    "dev.overview.evening": "Добрый вечер, {name}",
    "dev.overview.night": "Работаете допоздна, {name}",
    "dev.overview.sales": "Продажи сегодня",
    "dev.overview.tasks": "Задач выполнено",
    "dev.overview.present": "На месте",
    "dev.overview.cash": "Наличные сейчас",
    "dev.overview.vsLastWeek": "к прошлому вторнику",
    "dev.overview.ofTotal": "из {n}",
    "dev.overview.branches": "Филиалы",
    "dev.overview.opened": "Открыл(а) {name} в {time}",
    "dev.overview.notOpened": "Не открыт · +{n} мин",
    "dev.overview.staff": "Сотрудники",
    "dev.overview.tills": "Кассы",
    "dev.overview.needsYou": "Ждут вас",
    "dev.overview.activity": "Лента",
    "dev.overview.preview": "Превью обзора из пакета A",
    "dev.portfolio.title": "Портфель",
    "dev.newCompany.name": "Название компании",
    "dev.newCompany.placeholder": "например, Bahor Bakery",
    "dev.newCompany.note": "Компанию здесь создаёт пакет A. В мок-сборке форма просто закрывается.",
  },
  uz: {
    "dev.stub.badge": "Vaqtinchalik",
    "dev.stub.title": "{pkg} paketida qo‘shiladi",
    "dev.stub.body": "Mock yig‘ma bu sahifa qayerda bo‘lishini ko‘rsatadi. Uning egasi bo‘lgan modul shu joyni egallaydi.",
    "dev.overview.morning": "Xayrli tong, {name}",
    "dev.overview.afternoon": "Xayrli kun, {name}",
    "dev.overview.evening": "Xayrli kech, {name}",
    "dev.overview.night": "Kechgacha ishlayapsiz, {name}",
    "dev.overview.sales": "Bugungi savdo",
    "dev.overview.tasks": "Bajarilgan vazifalar",
    "dev.overview.present": "Hozir ishda",
    "dev.overview.cash": "Naqd pul",
    "dev.overview.vsLastWeek": "o‘tgan seshanbaga nisbatan",
    "dev.overview.ofTotal": "{n} tadan",
    "dev.overview.branches": "Filiallar",
    "dev.overview.opened": "{time} da {name} ochdi",
    "dev.overview.notOpened": "Ochilmagan · +{n} daq",
    "dev.overview.staff": "Xodimlar",
    "dev.overview.tills": "Kassalar",
    "dev.overview.needsYou": "Sizni kutmoqda",
    "dev.overview.activity": "Faollik",
    "dev.overview.preview": "A paketidagi umumiy ko‘rinishning namunasi",
    "dev.portfolio.title": "Portfel",
    "dev.newCompany.name": "Kompaniya nomi",
    "dev.newCompany.placeholder": "masalan, Bahor Bakery",
    "dev.newCompany.note": "Kompaniyani bu yerda A paketi yaratadi. Mock yig‘mada forma shunchaki yopiladi.",
  },
};

export function stubMessages(id: string): ModuleMessages {
  const entry = STUB_TITLES[id];
  const out: ModuleMessages = { en: {}, ru: {}, uz: {} };
  if (!entry) return out;
  const put = (key: string, [en, ru, uz]: Triple) => {
    (out.en as Messages)[key] = en;
    (out.ru as Messages)[key] = ru;
    (out.uz as Messages)[key] = uz;
  };
  put(`${id}.title`, entry.title);
  for (const [page, triple] of Object.entries(entry.pages)) put(`${id}.nav.${page}`, triple);
  return out;
}
