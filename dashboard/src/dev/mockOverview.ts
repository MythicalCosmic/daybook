/**
 * VITE_MOCK answers for the Overview's W0 widgets (dev only): `branches/today/` and `stream/`, in
 * the shapes apps.console sends (contracts.SalesFacts and friends; money as strings).
 */
import type { BranchToday, Language, StreamItem } from "@/api/types";

import { L, type Localized } from "./mockData";

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

export function branchesToday(companyId: number, _language: Language): BranchToday[] {
  if (companyId === 2) {
    return [
      {
        id: 4,
        name: "Mirobod",
        code: "MRB",
        opens_at: "08:00",
        closes_at: "23:00",
        status: "open",
        sales: { opened_at: minutesAgo(190), opened_by: { id: 21, name: "Kamola Yusupova" }, open_tills: 1, net: "3120000.00", cash_in_branch: "1840000.00" },
        attendance: { rostered: 4, checked_in: 3, first_check_in: minutesAgo(200) },
      },
    ];
  }
  return [
    {
      id: 1,
      name: "Chilonzor",
      code: "CHL",
      opens_at: "09:00",
      closes_at: "21:00",
      status: "open",
      sales: { opened_at: minutesAgo(183), opened_by: { id: 11, name: "Dilnoza Karimova" }, open_tills: 2, net: "6140000.00", cash_in_branch: "4210000.00" },
      attendance: { rostered: 7, checked_in: 7, first_check_in: minutesAgo(190) },
      tasks: { done: 18, total: 22, late: 1 },
      finance: { cash: "4210000.00" },
    },
    {
      id: 2,
      name: "Yunusobod",
      code: "YNS",
      opens_at: "10:00",
      closes_at: "22:00",
      status: "not_opened",
      sales: { opened_at: null, opened_by: null, open_tills: 0, net: "0.00", cash_in_branch: "0.00" },
      attendance: { rostered: 6, checked_in: 1, first_check_in: null },
      tasks: { done: 2, total: 16, late: 3 },
      finance: { cash: "350000.00" },
    },
    {
      id: 3,
      name: "Sergeli",
      code: "SRG",
      opens_at: "08:30",
      closes_at: "20:30",
      status: "open",
      sales: { opened_at: minutesAgo(214), opened_by: { id: 12, name: "Bekzod Mirzayev" }, open_tills: 1, net: "4880000.00", cash_in_branch: "2960000.00" },
      attendance: { rostered: 5, checked_in: 5, first_check_in: minutesAgo(220) },
      tasks: { done: 14, total: 21, late: 0 },
      finance: { cash: "2960000.00" },
    },
  ];
}

const STREAM: Array<[number, string, string | null, Localized, string]> = [
  [6, "tasks.done", "Madina Saidova", L("Fridge temperature check · +4 °C", "Проверка температуры холодильника · +4 °C", "Muzlatkich harorati tekshirildi · +4 °C"), "tasks?task=351"],
  [14, "sales.shift_closed", "Aziz Karimov", L("Closed shift CHL-1042 · 14 250 000 so‘m", "Закрыл смену CHL-1042 · 14 250 000 сум", "CHL-1042 smenani yopdi · 14 250 000 so‘m"), "sales/shifts/1042"],
  [52, "tasks.done", "Alisher Valiyev", L("Stock count: front shelves", "Пересчёт: передние полки", "Sanoq: old javonlar"), "tasks?task=345"],
  [96, "attendance.check_in", "Jasur Ergashev", L("Checked in at Sergeli · 08:41", "Отметился в Сергели · 08:41", "Sergelida keldi · 08:41"), "attendance"],
  [180, "announcements.sent", "Bekzod Mirzayev", L("Announcement: New uniform from Monday", "Объявление: новая форма с понедельника", "E’lon: dushanbadan yangi forma"), "announcements"],
  [240, "finance.expense", null, L("Rent for October recorded · 12 000 000 so‘m", "Записана аренда за октябрь · 12 000 000 сум", "Oktabr ijarasi yozildi · 12 000 000 so‘m"), "finance/transactions"],
];

export function streamFor(companyId: number, language: Language): StreamItem[] {
  const rows = companyId === 2 ? STREAM.slice(0, 2) : STREAM;
  return rows.map(([minutes, kind, actor, title, url], index) => ({
    at: minutesAgo(minutes),
    kind,
    actor: actor ? { id: 30 + index, name: actor } : null,
    title: title[language],
    url,
    photo_url: null,
  }));
}
