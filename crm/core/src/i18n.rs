//! Languages and the translation catalogue.
//!
//! Strings live in tables of `(key, uz, ru, en)`. Uzbek Cyrillic is generated from the
//! Uzbek Latin text, so every table only carries three columns. Each screen keeps its own
//! table next to its code; the app registers all tables in one [`Catalog`].
//! In Uzbek text, ‘ (U+2018) is used for o‘ / g‘ and ’ (U+2019) for the apostrophe.

use std::borrow::Cow;
use std::collections::HashMap;

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Lang {
    #[default]
    Uz,
    UzCyrl,
    Ru,
    En,
}

impl Lang {
    pub const ALL: &'static [Lang] = &[Lang::Uz, Lang::UzCyrl, Lang::Ru, Lang::En];

    pub fn code(self) -> &'static str {
        match self {
            Lang::Uz => "uz",
            Lang::UzCyrl => "uz-Cyrl",
            Lang::Ru => "ru",
            Lang::En => "en",
        }
    }
    pub fn native_name(self) -> &'static str {
        match self {
            Lang::Uz => "O‘zbekcha",
            Lang::UzCyrl => "Ўзбекча",
            Lang::Ru => "Русский",
            Lang::En => "English",
        }
    }
    pub fn short(self) -> &'static str {
        match self {
            Lang::Uz => "UZ",
            Lang::UzCyrl => "ЎЗ",
            Lang::Ru => "RU",
            Lang::En => "EN",
        }
    }
    pub fn from_code(code: &str) -> Option<Lang> {
        match code {
            "uz" => Some(Lang::Uz),
            "uz-Cyrl" | "uz-cyrl" | "cyrl" => Some(Lang::UzCyrl),
            "ru" => Some(Lang::Ru),
            "en" => Some(Lang::En),
            _ => None,
        }
    }
    pub fn is_uzbek(self) -> bool {
        matches!(self, Lang::Uz | Lang::UzCyrl)
    }
}

/// `(key, uz, ru, en)`
pub type Entry = (&'static str, &'static str, &'static str, &'static str);

pub struct Catalog {
    map: HashMap<&'static str, (&'static str, &'static str, &'static str)>,
    duplicates: Vec<&'static str>,
}

impl Catalog {
    pub fn new(tables: &[&'static [Entry]]) -> Self {
        let mut map = HashMap::new();
        let mut duplicates = Vec::new();
        for table in tables {
            for (k, uz, ru, en) in table.iter() {
                if map.insert(*k, (*uz, *ru, *en)).is_some() {
                    duplicates.push(*k);
                }
            }
        }
        Catalog { map, duplicates }
    }

    /// The text for `key`; the key itself when it's missing (visible, never a crash).
    pub fn get(&self, lang: Lang, key: &str) -> Cow<'static, str> {
        match self.map.get(key) {
            Some((uz, ru, en)) => pick(lang, uz, ru, en),
            None => Cow::Owned(key.to_string()),
        }
    }

    pub fn has(&self, key: &str) -> bool {
        self.map.contains_key(key)
    }

    pub fn duplicates(&self) -> &[&'static str] {
        &self.duplicates
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }

    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }
}

/// Picks one of three inline translations (for one-off strings that don't need a key).
pub fn pick(lang: Lang, uz: &'static str, ru: &'static str, en: &'static str) -> Cow<'static, str> {
    match lang {
        Lang::Uz => Cow::Borrowed(uz),
        Lang::UzCyrl => Cow::Owned(to_cyrillic(uz)),
        Lang::Ru => Cow::Borrowed(ru),
        Lang::En => Cow::Borrowed(en),
    }
}

/// Words that stay in Latin letters inside Uzbek Cyrillic text.
const KEEP: &[&str] = &[
    "Daybook", "CRM", "SMS", "AI", "QR", "PDF", "CSV", "Excel", "Telegram", "Instagram", "WhatsApp",
    "Email", "Haiku", "Sonnet", "Claude", "B2B", "NPS", "RFM", "LTV", "SLA", "ID", "OTC", "Rx", "UZS",
    "Ctrl", "Windows", "Android", "iPhone", "iOS", "Wi", "Fi", "Face", "Click", "Payme", "Uzum",
];

/// Uzbek Latin -> Uzbek Cyrillic. Leaves `{placeholders}`, brands and abbreviations alone.
pub fn to_cyrillic(src: &str) -> String {
    let chars: Vec<char> = src.chars().collect();
    let mut out = String::with_capacity(src.len() * 2);
    let is_apos = |c: Option<char>| matches!(c, Some('‘') | Some('\'') | Some('ʻ') | Some('`'));
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '{' {
            if let Some(len) = chars[i..].iter().position(|&x| x == '}') {
                out.extend(&chars[i..=i + len]);
                i += len + 1;
                continue;
            }
        }
        let word_start = i == 0 || !chars[i - 1].is_alphanumeric();
        if c.is_alphabetic() && word_start {
            let end = chars[i..].iter().position(|x| !x.is_alphanumeric()).map(|p| i + p).unwrap_or(chars.len());
            let word: String = chars[i..end].iter().collect();
            let abbrev = word.chars().count() <= 4 && word.chars().all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit());
            if KEEP.contains(&word.as_str()) || (abbrev && word.chars().count() > 1) {
                out.push_str(&word);
                i = end;
                continue;
            }
        }
        let next = chars.get(i + 1).copied();
        let next_l = next.map(|n| n.to_ascii_lowercase());
        let upper = c.is_uppercase();
        let lc = c.to_lowercase().next().unwrap_or(c);
        let (cyr, adv): (&str, usize) = match lc {
            'o' if is_apos(next) => ("ў", 2),
            'g' if is_apos(next) => ("ғ", 2),
            's' if next_l == Some('h') => ("ш", 2),
            'c' if next_l == Some('h') => ("ч", 2),
            'y' if next_l == Some('o') && !is_apos(chars.get(i + 2).copied()) => ("ё", 2),
            'y' if next_l == Some('u') => ("ю", 2),
            'y' if next_l == Some('a') => ("я", 2),
            'y' if next_l == Some('e') => ("е", 2),
            'e' if word_start => ("э", 1),
            'a' => ("а", 1),
            'b' => ("б", 1),
            'c' => ("с", 1),
            'd' => ("д", 1),
            'e' => ("е", 1),
            'f' => ("ф", 1),
            'g' => ("г", 1),
            'h' => ("ҳ", 1),
            'i' => ("и", 1),
            'j' => ("ж", 1),
            'k' => ("к", 1),
            'l' => ("л", 1),
            'm' => ("м", 1),
            'n' => ("н", 1),
            'o' => ("о", 1),
            'p' => ("п", 1),
            'q' => ("қ", 1),
            'r' => ("р", 1),
            's' => ("с", 1),
            't' => ("т", 1),
            'u' => ("у", 1),
            'v' => ("в", 1),
            'w' => ("в", 1),
            'x' => ("х", 1),
            'y' => ("й", 1),
            'z' => ("з", 1),
            '’' | 'ʼ' => ("ъ", 1),
            _ => {
                out.push(c);
                i += 1;
                continue;
            }
        };
        if upper {
            out.push_str(&cyr.to_uppercase());
        } else {
            out.push_str(cyr);
        }
        i += adv;
    }
    out
}

/// Strings shared by every screen: navigation, common actions and every enum in the model.
pub const CORE: &[Entry] = &[
    // navigation
    ("nav.home", "Bosh sahifa", "Главная", "Home"),
    ("nav.inbox", "Xabarlar", "Входящие", "Inbox"),
    ("nav.tasks", "Vazifalar", "Задачи", "Tasks"),
    ("nav.calendar", "Taqvim", "Календарь", "Calendar"),
    ("nav.contacts", "Mijozlar", "Клиенты", "Customers"),
    ("nav.companies", "Tashkilotlar", "Организации", "Companies"),
    ("nav.leads", "Lidlar", "Лиды", "Leads"),
    ("nav.segments", "Segmentlar", "Сегменты", "Segments"),
    ("nav.deals", "Bitimlar", "Сделки", "Deals"),
    ("nav.quotes", "Takliflar va hisoblar", "КП и счета", "Quotes & invoices"),
    ("nav.products", "Mahsulotlar", "Товары", "Products"),
    ("nav.campaigns", "Kampaniyalar", "Рассылки", "Campaigns"),
    ("nav.automations", "Avtomatlashtirish", "Автоматизации", "Automations"),
    ("nav.loyalty", "Sodiqlik dasturi", "Лояльность", "Loyalty"),
    ("nav.refills", "Dori radari", "Радар лекарств", "Refill radar"),
    ("nav.waitlist", "Defektura", "Дефектура", "Waitlist"),
    ("nav.tickets", "Murojaatlar", "Обращения", "Tickets"),
    ("nav.reports", "Hisobotlar", "Отчёты", "Reports"),
    ("nav.goals", "Maqsadlar", "Цели", "Goals"),
    ("nav.team", "Jamoa", "Команда", "Team"),
    ("nav.settings", "Sozlamalar", "Настройки", "Settings"),
    ("nav.daybook", "Daybook ulanishi", "Подключение Daybook", "Daybook connection"),
    ("nav.more", "Yana", "Ещё", "More"),
    ("nav.group.main", "Asosiy", "Основное", "Main"),
    ("nav.group.customers", "Mijozlar", "Клиенты", "Customers"),
    ("nav.group.sales", "Savdo", "Продажи", "Sales"),
    ("nav.group.marketing", "Marketing", "Маркетинг", "Marketing"),
    ("nav.group.care", "Xizmat", "Сервис", "Care"),
    ("nav.group.insights", "Tahlil", "Аналитика", "Insights"),
    // common words and actions
    ("common.search", "Qidirish", "Поиск", "Search"),
    ("common.search_hint", "Mijoz, bitim, dori yoki buyruq…", "Клиент, сделка, лекарство или команда…", "Customer, deal, medicine or command…"),
    ("common.add", "Qo‘shish", "Добавить", "Add"),
    ("common.new", "Yangi", "Новый", "New"),
    ("common.create", "Yaratish", "Создать", "Create"),
    ("common.save", "Saqlash", "Сохранить", "Save"),
    ("common.cancel", "Bekor qilish", "Отмена", "Cancel"),
    ("common.close", "Yopish", "Закрыть", "Close"),
    ("common.delete", "O‘chirish", "Удалить", "Delete"),
    ("common.edit", "Tahrirlash", "Изменить", "Edit"),
    ("common.back", "Orqaga", "Назад", "Back"),
    ("common.next", "Keyingi", "Далее", "Next"),
    ("common.all", "Hammasi", "Все", "All"),
    ("common.filter", "Filtr", "Фильтр", "Filter"),
    ("common.filters", "Filtrlar", "Фильтры", "Filters"),
    ("common.sort", "Saralash", "Сортировка", "Sort"),
    ("common.export", "Eksport", "Экспорт", "Export"),
    ("common.import", "Import", "Импорт", "Import"),
    ("common.today", "Bugun", "Сегодня", "Today"),
    ("common.yesterday", "Kecha", "Вчера", "Yesterday"),
    ("common.tomorrow", "Ertaga", "Завтра", "Tomorrow"),
    ("common.this_week", "Shu hafta", "Эта неделя", "This week"),
    ("common.this_month", "Shu oy", "Этот месяц", "This month"),
    ("common.last_month", "O‘tgan oy", "Прошлый месяц", "Last month"),
    ("common.overdue", "Muddati o‘tgan", "Просрочено", "Overdue"),
    ("common.done", "Bajarildi", "Готово", "Done"),
    ("common.open", "Ochiq", "Открыто", "Open"),
    ("common.view_all", "Hammasini ko‘rish", "Смотреть все", "View all"),
    ("common.details", "Batafsil", "Подробнее", "Details"),
    ("common.notes", "Izohlar", "Заметки", "Notes"),
    ("common.add_note", "Izoh qo‘shish", "Добавить заметку", "Add note"),
    ("common.owner", "Mas’ul", "Ответственный", "Owner"),
    ("common.branch", "Filial", "Филиал", "Branch"),
    ("common.branches", "Filiallar", "Филиалы", "Branches"),
    ("common.all_branches", "Barcha filiallar", "Все филиалы", "All branches"),
    ("common.status", "Holat", "Статус", "Status"),
    ("common.phone", "Telefon", "Телефон", "Phone"),
    ("common.name", "Ism", "Имя", "Name"),
    ("common.total", "Jami", "Итого", "Total"),
    ("common.value", "Summa", "Сумма", "Value"),
    ("common.date", "Sana", "Дата", "Date"),
    ("common.call", "Qo‘ng‘iroq", "Позвонить", "Call"),
    ("common.write", "Yozish", "Написать", "Message"),
    ("common.more", "Yana", "Ещё", "More"),
    ("common.none", "Yo‘q", "Нет", "None"),
    ("common.yes", "Ha", "Да", "Yes"),
    ("common.no", "Yo‘q", "Нет", "No"),
    ("common.empty", "Hozircha bo‘sh", "Пока пусто", "Nothing here yet"),
    ("common.no_results", "Hech narsa topilmadi", "Ничего не найдено", "No results"),
    ("common.saved", "Saqlandi", "Сохранено", "Saved"),
    ("common.demo", "Demo", "Демо", "Demo"),
    ("common.loading", "Yuklanmoqda…", "Загрузка…", "Loading…"),
    ("common.quick_add", "Tez qo‘shish", "Быстро добавить", "Quick add"),
    ("common.notifications", "Bildirishnomalar", "Уведомления", "Notifications"),
    ("common.mark_all_read", "Hammasi o‘qildi", "Прочитать все", "Mark all read"),
    ("common.theme", "Mavzu", "Тема", "Theme"),
    ("common.language", "Til", "Язык", "Language"),
    ("common.privacy_mode", "Maxfiylik rejimi", "Режим приватности", "Privacy mode"),
    ("common.offline", "Oflayn ishlaydi", "Работает офлайн", "Works offline"),
    ("common.synced", "Sinxronlandi", "Синхронизировано", "Synced"),
    ("common.daybook_connected", "Daybook ulangan", "Daybook подключён", "Daybook connected"),
    ("common.demo_mode", "Demo rejim", "Демо-режим", "Demo mode"),
    ("common.connect_daybook", "Daybook’ga ulash", "Подключить Daybook", "Connect Daybook"),
    ("common.ai", "AI yordamchi", "AI-помощник", "AI assistant"),
    ("common.insights", "Aqlli tavsiyalar", "Умные подсказки", "Smart insights"),
    ("common.customer", "Mijoz", "Клиент", "Customer"),
    ("common.customers", "Mijozlar", "Клиенты", "Customers"),
    ("common.company", "Tashkilot", "Организация", "Company"),
    ("common.deal", "Bitim", "Сделка", "Deal"),
    ("common.task", "Vazifa", "Задача", "Task"),
    ("common.lead", "Lid", "Лид", "Lead"),
    ("common.ticket", "Murojaat", "Обращение", "Ticket"),
    ("common.product", "Mahsulot", "Товар", "Product"),
    ("common.campaign", "Kampaniya", "Рассылка", "Campaign"),
    ("common.points", "ball", "баллов", "points"),
    ("common.reset_demo", "Demo ma’lumotlarni qayta yaratish", "Пересоздать демо-данные", "Reset demo data"),
    ("common.copied", "Nusxa olindi", "Скопировано", "Copied"),
    ("common.see", "Ko‘rish", "Открыть", "Open"),
    ("common.assign", "Biriktirish", "Назначить", "Assign"),
    ("common.unassigned", "Biriktirilmagan", "Не назначено", "Unassigned"),
    ("common.tags", "Teglar", "Теги", "Tags"),
    ("common.description", "Tavsif", "Описание", "Description"),
    ("common.created", "Yaratilgan", "Создано", "Created"),
    ("common.updated", "Yangilangan", "Обновлено", "Updated"),
    ("common.per_month", "oyiga", "в месяц", "per month"),
    ("common.vs_last_month", "o‘tgan oyga nisbatan", "к прошлому месяцу", "vs last month"),
    ("common.me", "Men", "Я", "Me"),
    ("common.sign_out", "Chiqish", "Выйти", "Sign out"),
    ("common.help", "Yordam", "Помощь", "Help"),
    ("common.shortcuts", "Tezkor tugmalar", "Горячие клавиши", "Keyboard shortcuts"),
    ("lang.uz", "O‘zbekcha", "Узбекский (латиница)", "Uzbek (Latin)"),
    ("lang.uz_cyrl", "Ўзбекча", "Узбекский (кириллица)", "Uzbek (Cyrillic)"),
    ("lang.ru", "Ruscha", "Русский", "Russian"),
    ("lang.en", "Inglizcha", "Английский", "English"),
    // roles
    ("role.owner", "Egasi", "Владелец", "Owner"),
    ("role.manager", "Filial mudiri", "Заведующий", "Branch manager"),
    ("role.pharmacist", "Farmatsevt", "Фармацевт", "Pharmacist"),
    ("role.cashier", "Kassir", "Кассир", "Cashier"),
    ("role.call_agent", "Call-markaz operatori", "Оператор колл-центра", "Call agent"),
    ("role.sales_rep", "B2B menejer", "B2B-менеджер", "B2B manager"),
    ("role.courier", "Kuryer", "Курьер", "Courier"),
    ("role.marketer", "Marketolog", "Маркетолог", "Marketer"),
    // gender
    ("gender.female", "Ayol", "Женщина", "Female"),
    ("gender.male", "Erkak", "Мужчина", "Male"),
    // tiers
    ("tier.bronze", "Bronza", "Бронза", "Bronze"),
    ("tier.silver", "Kumush", "Серебро", "Silver"),
    ("tier.gold", "Oltin", "Золото", "Gold"),
    ("tier.platinum", "Platina", "Платина", "Platinum"),
    // sources
    ("source.walk_in", "Dorixonaga kelgan", "Пришёл в аптеку", "Walk-in"),
    ("source.telegram", "Telegram bot", "Telegram-бот", "Telegram bot"),
    ("source.instagram", "Instagram", "Instagram", "Instagram"),
    ("source.referral", "Tavsiya", "Рекомендация", "Referral"),
    ("source.doctor", "Shifokor yo‘llanmasi", "Направление врача", "Doctor referral"),
    ("source.website", "Veb-sayt", "Сайт", "Website"),
    ("source.call", "Qo‘ng‘iroq", "Звонок", "Phone call"),
    ("source.corporate", "Korporativ", "Корпоративный", "Corporate"),
    ("source.qr", "Dorixonadagi QR", "QR в аптеке", "In-store QR"),
    // conditions
    ("condition.hypertension", "Gipertoniya", "Гипертония", "Hypertension"),
    ("condition.diabetes", "Qandli diabet", "Сахарный диабет", "Diabetes"),
    ("condition.cholesterol", "Xolesterin", "Холестерин", "Cholesterol"),
    ("condition.thyroid", "Qalqonsimon bez", "Щитовидная железа", "Thyroid"),
    ("condition.asthma", "Astma", "Астма", "Asthma"),
    ("condition.heart", "Yurak", "Сердце", "Heart"),
    ("condition.pregnancy", "Homiladorlik", "Беременность", "Pregnancy"),
    ("condition.allergy", "Allergiya", "Аллергия", "Allergy"),
    // channels
    ("channel.telegram", "Telegram", "Telegram", "Telegram"),
    ("channel.sms", "SMS", "SMS", "SMS"),
    ("channel.whatsapp", "WhatsApp", "WhatsApp", "WhatsApp"),
    ("channel.instagram", "Instagram", "Instagram", "Instagram"),
    ("channel.phone", "Telefon", "Телефон", "Phone"),
    ("channel.email", "E-mail", "E-mail", "Email"),
    ("channel.web", "Sayt", "Сайт", "Web"),
    ("sale_channel.in_store", "Dorixonada", "В аптеке", "In store"),
    ("sale_channel.delivery", "Yetkazib berish", "Доставка", "Delivery"),
    ("sale_channel.pickup", "Bron va olib ketish", "Бронь и самовывоз", "Reserve & pick up"),
    ("sale_channel.telegram_order", "Telegram buyurtma", "Заказ в Telegram", "Telegram order"),
    // organisations
    ("org.clinic", "Klinika", "Клиника", "Clinic"),
    ("org.hospital", "Shifoxona", "Больница", "Hospital"),
    ("org.corporate", "Korporativ mijoz", "Корпоративный клиент", "Corporate"),
    ("org.insurance", "Sug‘urta", "Страховая", "Insurance"),
    ("org.distributor", "Distribyutor", "Дистрибьютор", "Distributor"),
    ("org.school", "Maktab", "Школа", "School"),
    ("org.kindergarten", "Bog‘cha", "Детский сад", "Kindergarten"),
    ("org.lab", "Laboratoriya", "Лаборатория", "Lab"),
    ("org.government", "Davlat tashkiloti", "Госучреждение", "Government"),
    // deals and leads
    ("deal_status.open", "Ochiq", "Открыта", "Open"),
    ("deal_status.won", "Yutildi", "Выиграна", "Won"),
    ("deal_status.lost", "Boy berildi", "Проиграна", "Lost"),
    ("lead_status.new", "Yangi", "Новый", "New"),
    ("lead_status.contacted", "Bog‘lanildi", "Связались", "Contacted"),
    ("lead_status.qualified", "Saralandi", "Квалифицирован", "Qualified"),
    ("lead_status.converted", "Mijozga aylandi", "Конвертирован", "Converted"),
    ("lead_status.junk", "Keraksiz", "Нецелевой", "Junk"),
    // activities
    ("activity.call", "Qo‘ng‘iroq", "Звонок", "Call"),
    ("activity.meeting", "Uchrashuv", "Встреча", "Meeting"),
    ("activity.task", "Vazifa", "Задача", "Task"),
    ("activity.message", "Xabar", "Сообщение", "Message"),
    ("activity.email", "E-mail", "E-mail", "Email"),
    ("activity.visit", "Tashrif", "Визит", "Visit"),
    ("activity.delivery", "Yetkazish", "Доставка", "Delivery"),
    ("priority.low", "Past", "Низкий", "Low"),
    ("priority.normal", "O‘rtacha", "Обычный", "Normal"),
    ("priority.high", "Yuqori", "Высокий", "High"),
    ("priority.urgent", "Shoshilinch", "Срочно", "Urgent"),
    // inbox
    ("conv_status.open", "Ochiq", "Открыт", "Open"),
    ("conv_status.pending", "Kutilmoqda", "Ожидает", "Pending"),
    ("conv_status.resolved", "Hal qilindi", "Решён", "Resolved"),
    ("msg_kind.text", "Matn", "Текст", "Text"),
    ("msg_kind.photo", "Rasm", "Фото", "Photo"),
    ("msg_kind.voice", "Ovozli xabar", "Голосовое", "Voice message"),
    ("msg_kind.file", "Fayl", "Файл", "File"),
    ("msg_kind.system", "Tizim", "Система", "System"),
    ("msg_kind.note", "Ichki izoh", "Внутренняя заметка", "Internal note"),
    // campaigns
    ("campaign_status.draft", "Qoralama", "Черновик", "Draft"),
    ("campaign_status.scheduled", "Rejalashtirilgan", "Запланирована", "Scheduled"),
    ("campaign_status.running", "Yuborilmoqda", "Идёт отправка", "Sending"),
    ("campaign_status.done", "Yakunlangan", "Завершена", "Done"),
    ("campaign_status.paused", "To‘xtatilgan", "На паузе", "Paused"),
    // catalogue
    ("category.rx", "Retsept bo‘yicha", "Рецептурные", "Prescription"),
    ("category.otc", "Retseptsiz", "Безрецептурные", "OTC"),
    ("category.vitamins", "Vitaminlar", "Витамины", "Vitamins"),
    ("category.diabetes", "Diabet uchun", "Для диабета", "Diabetes care"),
    ("category.devices", "Tibbiy asboblar", "Медтехника", "Devices"),
    ("category.baby", "Bolalar uchun", "Детское", "Baby"),
    ("category.cosmetics", "Kosmetika", "Косметика", "Cosmetics"),
    ("category.hygiene", "Gigiyena", "Гигиена", "Hygiene"),
    // waitlist
    ("wait_status.waiting", "Kutmoqda", "Ждёт", "Waiting"),
    ("wait_status.arrived", "Keldi", "Поступило", "Arrived"),
    ("wait_status.notified", "Xabar berildi", "Уведомлён", "Notified"),
    ("wait_status.reserved", "Bron qilindi", "Забронировано", "Reserved"),
    ("wait_status.picked_up", "Olib ketdi", "Выкуплено", "Picked up"),
    ("wait_status.cancelled", "Bekor qilindi", "Отменено", "Cancelled"),
    // tickets
    ("ticket_kind.complaint", "Shikoyat", "Жалоба", "Complaint"),
    ("ticket_kind.return", "Qaytarish", "Возврат", "Return"),
    ("ticket_kind.adverse_reaction", "Nojo‘ya ta’sir", "Нежелательная реакция", "Adverse reaction"),
    ("ticket_kind.quality", "Sifat", "Качество", "Quality"),
    ("ticket_kind.delivery", "Yetkazish", "Доставка", "Delivery"),
    ("ticket_kind.question", "Savol", "Вопрос", "Question"),
    ("ticket_kind.praise", "Minnatdorchilik", "Благодарность", "Praise"),
    ("ticket_status.new", "Yangi", "Новое", "New"),
    ("ticket_status.in_progress", "Jarayonda", "В работе", "In progress"),
    ("ticket_status.waiting", "Mijoz javobini kutmoqda", "Ждём клиента", "Waiting on customer"),
    ("ticket_status.resolved", "Hal qilindi", "Решено", "Resolved"),
    ("ticket_status.closed", "Yopildi", "Закрыто", "Closed"),
    // quotes
    ("quote_status.draft", "Qoralama", "Черновик", "Draft"),
    ("quote_status.sent", "Yuborildi", "Отправлено", "Sent"),
    ("quote_status.accepted", "Qabul qilindi", "Принято", "Accepted"),
    ("quote_status.rejected", "Rad etildi", "Отклонено", "Rejected"),
    ("quote_status.invoiced", "Hisob chiqarildi", "Выставлен счёт", "Invoiced"),
    ("quote_status.paid", "To‘landi", "Оплачено", "Paid"),
    ("quote_status.overdue", "Muddati o‘tdi", "Просрочено", "Overdue"),
    // loyalty
    ("tx.earn", "Keshbek", "Начисление", "Cashback"),
    ("tx.redeem", "Sarflandi", "Списание", "Redeemed"),
    ("tx.bonus", "Bonus", "Бонус", "Bonus"),
    ("tx.expire", "Muddati tugadi", "Сгорание", "Expired"),
    ("tx.adjust", "Tuzatish", "Корректировка", "Adjustment"),
    // goals
    ("metric.revenue", "Tushum", "Выручка", "Revenue"),
    ("metric.new_customers", "Yangi mijozlar", "Новые клиенты", "New customers"),
    ("metric.deals_won", "Yutilgan bitimlar", "Выигранные сделки", "Deals won"),
    ("metric.calls", "Qo‘ng‘iroqlar", "Звонки", "Calls"),
    ("metric.retention", "Qaytish darajasi", "Удержание", "Retention"),
    // segment rules
    ("field.tier", "Daraja", "Уровень", "Tier"),
    ("field.total_spent", "Jami xarid", "Сумма покупок", "Total spent"),
    ("field.orders", "Xaridlar soni", "Число покупок", "Orders"),
    ("field.days_since_last", "Oxirgi xariddan beri, kun", "Дней с последней покупки", "Days since last purchase"),
    ("field.age", "Yosh", "Возраст", "Age"),
    ("field.gender", "Jins", "Пол", "Gender"),
    ("field.branch", "Filial", "Филиал", "Branch"),
    ("field.tag", "Teg", "Тег", "Tag"),
    ("field.condition", "Surunkali kasallik", "Хроническое заболевание", "Condition"),
    ("field.source", "Manba", "Источник", "Source"),
    ("field.points", "Ballar", "Баллы", "Points"),
    ("field.consent_telegram", "Telegramga rozilik", "Согласие на Telegram", "Telegram consent"),
    ("field.consent_sms", "SMSga rozilik", "Согласие на SMS", "SMS consent"),
    ("field.birthday_in_days", "Tug‘ilgan kungacha, kun", "Дней до дня рождения", "Days to birthday"),
    ("field.refill_due_in_days", "Dori tugashiga, kun", "Дней до конца лекарства", "Days to refill"),
    ("field.corporate", "Korporativ mijoz", "Корпоративный клиент", "Corporate customer"),
    ("op.eq", "teng", "равно", "is"),
    ("op.ne", "teng emas", "не равно", "is not"),
    ("op.gt", "dan ko‘p", "больше", "more than"),
    ("op.lt", "dan kam", "меньше", "less than"),
    ("op.contains", "ichida bor", "содержит", "contains"),
    ("op.is_true", "ha", "да", "yes"),
    ("op.is_false", "yo‘q", "нет", "no"),
    // notifications
    ("notif.lead", "Yangi lid", "Новый лид", "New lead"),
    ("notif.message", "Xabar", "Сообщение", "Message"),
    ("notif.task", "Vazifa", "Задача", "Task"),
    ("notif.deal", "Bitim", "Сделка", "Deal"),
    ("notif.ticket", "Murojaat", "Обращение", "Ticket"),
    ("notif.refill", "Dori eslatmasi", "Напоминание о лекарстве", "Refill"),
    ("notif.waitlist", "Defektura", "Дефектура", "Waitlist"),
    ("notif.system", "Tizim", "Система", "System"),
    // theme
    ("theme.system", "Tizim bo‘yicha", "Как в системе", "System"),
    ("theme.light", "Yorug‘", "Светлая", "Light"),
    ("theme.dark", "Qorong‘i", "Тёмная", "Dark"),
    // automation triggers and actions
    ("trigger.birthday", "Tug‘ilgan kun", "День рождения", "Birthday"),
    ("trigger.refill_due", "Dori tugayapti", "Лекарство заканчивается", "Refill due"),
    ("trigger.inactive", "Uzoq vaqt xarid qilmadi", "Давно не покупал", "Gone quiet"),
    ("trigger.after_purchase", "Xariddan keyin", "После покупки", "After a purchase"),
    ("trigger.first_purchase", "Birinchi xarid", "Первая покупка", "First purchase"),
    ("trigger.tier_up", "Daraja oshdi", "Повышение уровня", "Tier went up"),
    ("trigger.deal_stage", "Bitim bosqichi o‘zgardi", "Сделка сменила этап", "Deal changed stage"),
    ("trigger.new_lead", "Yangi lid", "Новый лид", "New lead"),
    ("trigger.waitlist_arrived", "Kutilgan dori keldi", "Ожидаемое поступило", "Waitlist item arrived"),
    ("trigger.ticket_created", "Yangi murojaat", "Новое обращение", "New ticket"),
    ("trigger.low_nps", "Past baho", "Низкая оценка", "Low rating"),
    ("action.send_telegram", "Telegram xabar yuborish", "Отправить в Telegram", "Send a Telegram message"),
    ("action.send_sms", "SMS yuborish", "Отправить SMS", "Send an SMS"),
    ("action.create_task", "Vazifa yaratish", "Создать задачу", "Create a task"),
    ("action.add_tag", "Teg qo‘shish", "Добавить тег", "Add a tag"),
    ("action.give_bonus", "Bonus berish", "Начислить бонус", "Give bonus points"),
    ("action.notify_manager", "Mudirni ogohlantirish", "Уведомить заведующего", "Notify the manager"),
    ("action.move_deal", "Bitimni ko‘chirish", "Перевести сделку", "Move the deal"),
    ("action.wait", "Kutish", "Подождать", "Wait"),
    ("action.reserve_stock", "Dorini bron qilish", "Забронировать товар", "Reserve the stock"),
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cyrillic() {
        assert_eq!(to_cyrillic("O‘zbekcha"), "Ўзбекча");
        assert_eq!(to_cyrillic("Qo‘ng‘iroq"), "Қўнғироқ");
        assert_eq!(to_cyrillic("yo‘q"), "йўқ");
        assert_eq!(to_cyrillic("Shu hafta"), "Шу ҳафта");
        assert_eq!(to_cyrillic("Mas’ul"), "Масъул");
        assert_eq!(to_cyrillic("{n} ta Telegram xabar"), "{n} та Telegram хабар");
        assert_eq!(to_cyrillic("Eksport"), "Экспорт");
    }

    #[test]
    fn core_has_no_duplicates() {
        let c = Catalog::new(&[CORE]);
        assert!(c.duplicates().is_empty(), "{:?}", c.duplicates());
    }
}
