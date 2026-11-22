//! Inbox: every conversation (Telegram, SMS, WhatsApp, Instagram, phone, e-mail) in one
//! messenger-style screen. Filters on the left, the thread and composer in the middle, the
//! customer's mini 360 on the right. The composer has pharmacy quick replies, a local
//! "AI" suggestion and a compliance check that blocks promoting prescription medicines.

use chrono::{Duration, NaiveDateTime};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use crm::Db;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

// ---------------------------------------------------------------- filters

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum Tab {
    #[default]
    All,
    Unread,
    Mine,
    Unassigned,
    Resolved,
}

const TABS: [(Tab, &str); 5] = [
    (Tab::All, "common.all"),
    (Tab::Unread, "inbox.tab_unread"),
    (Tab::Mine, "inbox.mine"),
    (Tab::Unassigned, "inbox.tab_free"),
    (Tab::Resolved, "inbox.tab_closed"),
];

#[derive(Clone, Debug, Default, PartialEq)]
struct Filter {
    tab: Tab,
    channel: Option<Channel>,
    query: String,
}

/// Kept across threads, so opening a conversation doesn't reset the list.
static FILTER: GlobalSignal<Filter> = Signal::global(Filter::default);

fn tab_match(c: &Conversation, tab: Tab, me: Id) -> bool {
    let open = c.status != ConvStatus::Resolved;
    match tab {
        Tab::All => open,
        Tab::Unread => open && c.unread > 0,
        Tab::Mine => open && c.assigned_to == Some(me),
        Tab::Unassigned => open && c.assigned_to.is_none(),
        Tab::Resolved => !open,
    }
}

#[derive(Clone, Debug, PartialEq)]
struct Row {
    id: Id,
    title: String,
    last: String,
    last_kind: MsgKind,
    outbound: bool,
    at: Option<NaiveDateTime>,
    unread: u16,
    waiting: Option<i64>,
    channel: Channel,
    starred: bool,
    lead: bool,
}

fn channel_tone(c: Channel) -> &'static str {
    match c {
        Channel::Telegram => "info",
        Channel::WhatsApp => "success",
        Channel::Instagram => "accent",
        Channel::Sms => "warning",
        _ => "muted",
    }
}

/// "waiting 45 min" in the interface language.
fn wait_label(mins: i64, l: Lang) -> String {
    let (n, unit) = if mins < 60 {
        (mins, 0)
    } else if mins < 60 * 24 {
        (mins / 60, 1)
    } else {
        (mins / 60 / 24, 2)
    };
    match l {
        Lang::Ru => format!("ждёт {n} {}", ["мин", "ч", "дн."][unit]),
        Lang::En => format!("waiting {n} {}", ["min", "h", "d"][unit]),
        _ => uz(format!("{n} {} kutmoqda", ["daqiqadan beri", "soatdan beri", "kundan beri"][unit])),
    }
}

fn minutes_short(mins: i64, l: Lang) -> String {
    match l {
        Lang::Ru => format!("{mins} мин"),
        Lang::En => format!("{mins} min"),
        _ => uz(format!("{mins} daq.")),
    }
}

// ---------------------------------------------------------------- text matching (shared with campaigns)

fn is_cyrillic(c: char) -> bool {
    ('\u{0400}'..='\u{04FF}').contains(&c)
}

/// Lower-case Latin spelling of any text (Russian or Uzbek Cyrillic transliterated, apostrophes
/// unified), so "Инсулин гларгин" finds "Insulin glargin".
pub fn latinize(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 8);
    for ch in s.chars().flat_map(|c| c.to_lowercase()) {
        let rep: &str = match ch {
            'а' => "a",
            'б' => "b",
            'в' => "v",
            'г' => "g",
            'д' => "d",
            'е' => "e",
            'ё' => "yo",
            'ж' => "j",
            'з' => "z",
            'и' => "i",
            'й' => "y",
            'к' => "k",
            'л' => "l",
            'м' => "m",
            'н' => "n",
            'о' => "o",
            'п' => "p",
            'р' => "r",
            'с' => "s",
            'т' => "t",
            'у' => "u",
            'ф' => "f",
            'х' => "x",
            'ц' => "ts",
            'ч' => "ch",
            'ш' | 'щ' => "sh",
            'ъ' | 'ь' => "",
            'ы' => "i",
            'э' => "e",
            'ю' => "yu",
            'я' => "ya",
            'ў' => "o‘",
            'қ' => "q",
            'ғ' => "g‘",
            'ҳ' => "h",
            '\'' | 'ʻ' | '`' | '’' | 'ʼ' => "‘",
            _ => {
                out.push(ch);
                continue;
            }
        };
        out.push_str(rep);
    }
    out
}

fn contains_word(hay: &str, w: &str) -> bool {
    let mut start = 0;
    while let Some(pos) = hay[start..].find(w) {
        let a = start + pos;
        let b = a + w.len();
        let before = hay[..a].chars().next_back().map_or(true, |c| !c.is_alphanumeric());
        let after = hay[b..].chars().next().map_or(true, |c| !c.is_alphanumeric());
        if before && after {
            return true;
        }
        start = a + w.len().max(1);
        if start >= hay.len() {
            break;
        }
    }
    false
}

const NAME_STOP: &[&str] = &["bolalar", "tibbiy", "elektron", "sezgir", "quyoshdan", "kompressorli"];

/// "10 mg" from "amlodipin 10 mg №30".
fn strength(name_lat: &str) -> Option<String> {
    let toks: Vec<&str> = name_lat.split_whitespace().collect();
    for w in toks.windows(2) {
        let starts_digit = w[0].chars().next().map_or(false, |c| c.is_ascii_digit());
        let unit: String = w[1].chars().take_while(|c| c.is_alphabetic()).collect();
        if starts_digit && ["mg", "mkg", "me", "tb", "ml", "g"].contains(&unit.as_str()) {
            return Some(format!("{} {}", w[0], unit));
        }
    }
    None
}

/// How strongly a (latinized) text names a product: 0 = not at all.
fn product_score(p: &Product, lat: &str) -> u32 {
    let g = latinize(&p.generic);
    let first_g = g.split(|c: char| !c.is_alphanumeric() && c != '‘').next().unwrap_or("");
    let n = latinize(&p.name);
    let first_n = n.split_whitespace().next().unwrap_or("");
    let n_ok = {
        let k = first_n.chars().count();
        (k >= 6 && !NAME_STOP.contains(&first_n)) || (k >= 2 && first_n.chars().any(|c| c.is_ascii_digit()))
    };
    let mut s = if g.chars().count() >= 5 && lat.contains(&g) {
        4
    } else if first_g.chars().count() >= 5 && lat.contains(first_g) {
        2
    } else if n_ok && contains_word(lat, first_n) {
        2
    } else {
        0
    };
    if s > 0 {
        if let Some(st) = strength(&n) {
            if lat.contains(&st) || lat.contains(&st.replace(' ', "")) {
                s += 2;
            }
        }
    }
    s
}

fn find_product<'a>(db: &'a Db, lat: &str) -> Option<&'a Product> {
    let mut best: Option<(&Product, u32)> = None;
    for p in &db.products {
        let s = product_score(p, lat);
        if s >= 2 && best.map_or(true, |(_, b)| s > b) {
            best = Some((p, s));
        }
    }
    best.map(|(p, _)| p)
}

const PROMO: &[&str] = &[
    "aksiya", "aktsiya", "chegirma", "skidk", "sale", "discount", "promo", "rasprodaj", "arzonlash", "bonus", "baravar", "1+1", "2+1",
    "kupon",
];

/// The prescription-only medicine a text promotes, if it does (name + a promo word).
pub fn rx_promo(db: &Db, text: &str) -> Option<String> {
    let lat = latinize(text);
    if !PROMO.iter().any(|w| lat.contains(w)) {
        return None;
    }
    db.products
        .iter()
        .filter(|p| p.rx)
        .map(|p| (p, product_score(p, &lat)))
        .filter(|(_, s)| *s >= 2)
        .max_by_key(|(_, s)| *s)
        .map(|(p, _)| p.name.clone())
}

/// Infant formula named in marketing text (banned from promotion).
pub fn infant_formula(db: &Db, text: &str) -> Option<String> {
    let lat = latinize(text);
    let words = ["aralashma", "smes", "formula", "detskoe pitanie"];
    db.products
        .iter()
        .filter(|p| p.no_bonus && p.category == ProductCategory::Baby)
        .find(|p| product_score(p, &lat) >= 2 || words.iter().any(|w| lat.contains(w)))
        .map(|p| p.name.clone())
}

fn mentioned_branch(db: &Db, lat: &str) -> Option<Id> {
    db.branches
        .iter()
        .find(|b| {
            let key: String = latinize(&b.name).chars().take(5).collect();
            key.chars().count() == 5 && lat.split(|c: char| !c.is_alphanumeric() && c != '‘').any(|w| w.starts_with(&key))
        })
        .map(|b| b.id)
}

fn quantity(lat: &str) -> u32 {
    let toks: Vec<&str> = lat.split_whitespace().collect();
    for w in toks.windows(2) {
        let n: String = w[0].chars().filter(|c| c.is_ascii_digit()).collect();
        if !n.is_empty() && n.len() <= 2 && w[0].chars().all(|c| c.is_ascii_digit()) {
            if ["ta", "dona", "upak", "sht", "pachka", "qadoq"].iter().any(|u| w[1].starts_with(u)) {
                return n.parse().unwrap_or(1).clamp(1, 20);
            }
        }
    }
    1
}

// ---------------------------------------------------------------- reply context, templates, AI

struct Ctx<'a> {
    first: String,
    branch: Option<&'a Branch>,
    product: Option<&'a Product>,
    points: Option<i64>,
    ru: bool,
    qty: u32,
}

fn context<'a>(db: &'a Db, c: &Conversation) -> Ctx<'a> {
    let recent: Vec<&Message> = c.messages.iter().rev().filter(|m| m.inbound && m.kind == MsgKind::Text).take(4).collect();
    let text: String = recent.iter().rev().map(|m| m.text.as_str()).collect::<Vec<_>>().join(" \n ");
    let lat = latinize(&text);
    let cust = c.customer_id.and_then(|id| db.customer(id));
    let ru = if recent.is_empty() { cust.map(|x| x.lang == Lang::Ru).unwrap_or(false) } else { text.chars().any(is_cyrillic) };
    let first = cust
        .map(|x| x.first_name.clone())
        .unwrap_or_else(|| c.title.split_whitespace().next().unwrap_or("").to_string());
    let branch = mentioned_branch(db, &lat)
        .and_then(|b| db.branch(b))
        .or_else(|| cust.and_then(|x| db.branch(x.home_branch)))
        .or_else(|| db.branches.first());
    Ctx { first, branch, product: find_product(db, &lat), points: cust.map(|x| x.points), ru, qty: quantity(&lat) }
}

const TEMPLATES: [(&str, &str); 5] = [
    ("inbox.tpl_available", "package-check"),
    ("inbox.tpl_delivery", "truck"),
    ("inbox.tpl_price", "tag"),
    ("inbox.tpl_rx", "camera"),
    ("inbox.tpl_hours", "clock"),
];

fn template_text(i: usize, x: &Ctx) -> String {
    let lang = if x.ru { Lang::Ru } else { Lang::Uz };
    let money = |v: Money| fmt::money(v, lang);
    let b = x.branch.map(|b| b.name.clone()).unwrap_or_default();
    match (i, x.ru) {
        (0, false) => match x.product {
            Some(p) => format!("Ha, {} {} filialida bor, narxi {}. Siz uchun bron qilib qo‘yaymi? Bron 24 soat saqlanadi.", p.name, b, money(p.price)),
            None => format!("Ha, bu dori {b} filialida bor. Siz uchun bron qilib qo‘yaymi? Bron 24 soat saqlanadi."),
        },
        (0, true) => match x.product {
            Some(p) => format!("Да, {} есть в филиале {}, цена {}. Забронировать для вас? Бронь держим 24 часа.", p.name, b, money(p.price)),
            None => format!("Да, этот препарат есть в филиале {b}. Забронировать для вас? Бронь держим 24 часа."),
        },
        (1, false) => "Toshkent bo‘ylab 2 soat ichida yetkazib beramiz: 150 000 so‘mdan ortiq buyurtma bepul, undan kami 15 000 so‘m. Retseptli dorilar retsept ko‘rsatilganda topshiriladi.".into(),
        (1, true) => "Доставим по Ташкенту за 2 часа: заказ от 150 000 сум бесплатно, до этой суммы 15 000 сум. Рецептурные препараты передаём при предъявлении рецепта.".into(),
        (2, false) => {
            let price = match x.product {
                Some(p) => format!("{} narxi {}.", p.name, money(p.price)),
                None => "Narxini aniqlab, bir daqiqada yozaman.".to_string(),
            };
            match x.points {
                Some(pt) if pt > 0 => format!("{price} Hisobingizda {} ball bor: xaridning 30% gacha qismini ball bilan to‘lashingiz mumkin.", fmt::num(pt)),
                _ => price,
            }
        }
        (2, true) => {
            let price = match x.product {
                Some(p) => format!("{} стоит {}.", p.name, money(p.price)),
                None => "Уточню цену и напишу через минуту.".to_string(),
            };
            match x.points {
                Some(pt) if pt > 0 => format!("{price} На вашем счёте {} баллов: ими можно оплатить до 30% покупки.", fmt::num(pt)),
                _ => price,
            }
        }
        (3, false) => "Bu dori retsept bo‘yicha beriladi. Iltimos, retsept rasmini shu yerga yuboring: farmatsevtimiz tekshirib, siz uchun bron qilib qo‘yadi.".into(),
        (3, true) => "Этот препарат отпускается по рецепту. Пришлите, пожалуйста, фото рецепта сюда: фармацевт проверит его и забронирует для вас.".into(),
        (_, ru) => match x.branch {
            Some(br) if !ru => format!("{} filiali {} ishlaydi. Manzil: {}. Telefon: {}.", br.name, br.open_hours, br.address, br.phone),
            Some(br) => format!("Филиал {} работает {}. Адрес: {}. Телефон: {}.", br.name, br.open_hours, br.address, br.phone),
            None => String::new(),
        },
    }
}

/// The rule-based suggestion ("AI · Haiku" in the UI; computed locally in the demo).
fn suggest(db: &Db, c: &Conversation) -> Option<String> {
    let last = c.messages.iter().rev().find(|m| m.kind != MsgKind::Note && m.kind != MsgKind::System)?;
    if !last.inbound {
        return None;
    }
    let x = context(db, c);
    let lang = if x.ru { Lang::Ru } else { Lang::Uz };
    let money = |v: Money| fmt::money(v, lang);
    let b = x.branch.map(|b| b.name.clone()).unwrap_or_default();
    let ru = x.ru;
    if last.kind == MsgKind::Photo {
        return Some(match (x.product, ru) {
            (Some(p), false) if p.rx => format!(
                "Rahmat, retsept qabul qilindi! {} × {} {} filialida siz uchun bron qilindi: jami {}. Bron 24 soat saqlanadi.",
                p.name, x.qty, b, money(p.price * x.qty as Money)
            ),
            (Some(p), true) if p.rx => format!(
                "Спасибо, рецепт получили! {} × {} забронирован для вас в филиале {}: итого {}. Бронь держим 24 часа.",
                p.name, x.qty, b, money(p.price * x.qty as Money)
            ),
            (Some(p), false) => format!(
                "Rasm uchun rahmat! {} mos keladi: {}, {} filialida bor. Farmatsevtimiz rasmni ko‘rib, qo‘shimcha tavsiya beradi.",
                p.name, money(p.price), b
            ),
            (Some(p), true) => format!("Спасибо за фото! Подойдёт {}: {}, есть в филиале {}. Фармацевт посмотрит фото и даст рекомендации.", p.name, money(p.price), b),
            (None, false) => "Rasm uchun rahmat! Farmatsevtimiz uni ko‘rib chiqib, 5 daqiqa ichida javob beradi.".into(),
            (None, true) => "Спасибо за фото! Фармацевт посмотрит его и ответит в течение 5 минут.".into(),
        });
    }
    if last.kind == MsgKind::Voice {
        return Some(if ru { "Получили ваше голосовое сообщение: фармацевт сейчас перезвонит.".into() } else { "Ovozli xabaringizni oldik: farmatsevtimiz hozir qayta qo‘ng‘iroq qiladi.".into() });
    }
    let lat = latinize(&last.text);
    let has = |words: &[&str]| words.iter().any(|w| lat.contains(w));
    if has(&["toshma", "allerg", "nojo‘ya", "otek", "qichish"]) {
        return Some(if ru {
            "Пожалуйста, пока не принимайте препарат. Провизор перезвонит вам в течение 10 минут; при отёке или затруднённом дыхании сразу звоните 103.".into()
        } else {
            "Iltimos, dorini hozircha ichmang. Provizorimiz 10 daqiqa ichida qo‘ng‘iroq qiladi; shish yoki nafas qisishi bo‘lsa, darhol 103 ga qo‘ng‘iroq qiling.".into()
        });
    }
    if has(&["rahmat", "raxmat", "spasibo", "tashakkur", "blagodar"]) {
        return Some(if ru {
            format!("Пожалуйста, {}! Будьте здоровы. Если появятся вопросы, пишите сюда: фармацевт на связи.", x.first)
        } else {
            format!("Arzimaydi, {}! Sog‘ bo‘ling. Savollar bo‘lsa, shu yerga yozing: farmatsevtimiz doim aloqada.", x.first)
        });
    }
    if let Some(p) = x.product {
        let here = x.branch.map(|br| p.stock_at(br.id)).unwrap_or(0);
        let rx = match (p.rx, ru) {
            (true, false) => " Retsept bilan beriladi.",
            (true, true) => " Отпускается по рецепту.",
            _ => "",
        };
        if here > 0 {
            return Some(if ru {
                format!("Да, {} есть в филиале {}: {}, {} шт.{} Забронировать? Можно забрать сегодня или заказать доставку за 2 часа.", p.name, b, money(p.price), here, rx)
            } else {
                format!("Ha, {} {} filialida bor: {}, {} dona.{} Bron qilib qo‘yaymi? Bugun olib ketishingiz yoki 2 soatda yetkazib berishimiz mumkin.", p.name, b, money(p.price), here, rx)
            });
        }
        let other = p.stock.iter().filter(|s| s.qty > 0).max_by_key(|s| s.qty).and_then(|s| db.branch(s.branch_id).map(|br| (br.name.clone(), s.qty)));
        return Some(match (other, ru) {
            (Some((ob, n)), false) => format!(
                "{} hozir {} filialida tugagan, lekin {} filialida {} dona bor: {}. O‘sha yerda bron qilaymi yoki ertaga {} filialiga keltirib beraylikmi?",
                p.name, b, ob, n, money(p.price), b
            ),
            (Some((ob, n)), true) => format!("{} сейчас закончился в филиале {}, но в филиале {} есть {} шт.: {}. Забронировать там или привезти в {} завтра?", p.name, b, ob, n, money(p.price), b),
            (None, false) => format!("{} hozir omborda yo‘q. Sizni defekturaga yozib qo‘ydim: kelishi bilan birinchi bo‘lib xabar beramiz.", p.name),
            (None, true) => format!("{} сейчас нет в наличии. Записали вас в дефектуру: сообщим первыми, как только поступит.", p.name),
        });
    }
    if has(&["bonus", "ball", "karta", "kart"]) {
        if let Some(pt) = x.points {
            return Some(if ru {
                format!("На вашем счёте {} баллов. Ими можно оплатить до 30% следующей покупки.", fmt::num(pt))
            } else {
                format!("Hisobingizda {} ball bor. Keyingi xaridning 30% gacha qismini ball bilan to‘lashingiz mumkin.", fmt::num(pt))
            });
        }
    }
    if has(&["yetkaz", "dostav", "kuryer", "kurer"]) {
        return Some(template_text(1, &x));
    }
    if has(&["buyurtma", "zakaz", "ro‘yxat", "spisok"]) {
        return Some(if ru {
            format!("Конечно! Напишите список препаратов сюда или пришлите фото рецепта. Фармацевт посчитает сумму, а забрать можно в филиале {b} или заказать доставку за 2 часа.")
        } else {
            format!("Albatta! Kerakli dorilar ro‘yxatini shu yerga yozing yoki retsept rasmini yuboring. Farmatsevt summani hisoblab beradi: {b} filialidan olib ketasiz yoki 2 soatda yetkazib beramiz.")
        });
    }
    if has(&["ish vaqt", "soat nechada", "manzil", "adres", "rabota"]) {
        return Some(template_text(4, &x));
    }
    Some(if ru {
        format!("Здравствуйте, {}! Спасибо за обращение. Фармацевт ответит вам в течение нескольких минут.", x.first)
    } else {
        format!("Assalomu alaykum, {}! Murojaatingiz uchun rahmat. Farmatsevtimiz bir necha daqiqada aniq javob beradi.", x.first)
    })
}

// ---------------------------------------------------------------- screens

#[component]
pub fn Inbox() -> Element {
    rsx! { InboxScreen { selected: None } }
}

#[component]
pub fn InboxThread(id: u32) -> Element {
    rsx! { InboxScreen { selected: Some(id) } }
}

#[component]
fn InboxScreen(selected: Option<u32>) -> Element {
    let cls = if selected.is_some() { "split thread-open" } else { "split" };
    rsx! {
        div { class: "page",
            div { class: "{cls}",
                ListPane { selected }
                if let Some(id) = selected {
                    ThreadPane { key: "t{id}", id }
                    SidePane { id }
                } else {
                    Overview {}
                    OverviewSide {}
                }
            }
        }
    }
}

// ---------------------------------------------------------------- list pane

#[component]
fn ListPane(selected: Option<u32>) -> Element {
    let data = use_memo(move || {
        let db = DB.read();
        let f = FILTER.read().clone();
        let now = crate::state::now();
        let me = db.settings.me;
        let q = f.query.trim().to_lowercase();
        let mut counts = [0usize; 5];
        let mut rows = Vec::new();
        for c in &db.conversations {
            for (i, (tab, _)) in TABS.into_iter().enumerate() {
                if tab_match(c, tab, me) {
                    counts[i] += 1;
                }
            }
            if !tab_match(c, f.tab, me) || f.channel.map_or(false, |ch| ch != c.channel) {
                continue;
            }
            if !q.is_empty()
                && !(c.title.to_lowercase().contains(&q) || c.handle.to_lowercase().contains(&q) || c.messages.iter().any(|m| m.text.to_lowercase().contains(&q)))
            {
                continue;
            }
            let last = c.messages.iter().rev().find(|m| m.kind != MsgKind::System).or(c.messages.last());
            rows.push(Row {
                id: c.id,
                title: c.title.clone(),
                last: last.map(|m| m.text.clone()).unwrap_or_default(),
                last_kind: last.map(|m| m.kind).unwrap_or(MsgKind::Text),
                outbound: last.map(|m| !m.inbound).unwrap_or(false),
                at: c.last_at(),
                unread: c.unread,
                waiting: if c.status == ConvStatus::Resolved { None } else { c.waiting_min(now) },
                channel: c.channel,
                starred: c.starred,
                lead: c.customer_id.is_none() && c.lead_id.is_some(),
            });
        }
        rows.sort_by(|a, b| b.at.cmp(&a.at));
        (rows, counts)
    });
    let (rows, counts) = data();
    let f = FILTER.read().clone();
    let unread_total: u32 = DB.read().unread_inbox();
    let waiting = rows.iter().filter(|r| r.waiting.map_or(false, |m| m >= 30)).count();
    let sub = match lang() {
        Lang::Ru => format!("{} открытых · ждут ответа: {}", counts[0], waiting),
        Lang::En => format!("{} open · {} waiting for a reply", counts[0], waiting),
        _ => uz(format!("{} ta ochiq · {} ta javob kutmoqda", counts[0], waiting)),
    };
    let channel_slug = f.channel.map(|c| c.slug()).unwrap_or("");
    let tabs: Vec<(Tab, &'static str, usize)> = TABS
        .into_iter()
        .enumerate()
        .map(|(i, (tab, key))| (tab, key, if matches!(tab, Tab::Unread | Tab::Unassigned) { counts[i] } else { 0 }))
        .collect();
    let query = f.query.clone();

    rsx! {
        div { class: "pane list-pane",
            // desktop head
            div { class: "pane-head hide-mobile",
                div { class: "stack gap-8 grow",
                    div { class: "row between",
                        div { class: "row gap-8",
                            h2 { class: "section-title", {t("nav.inbox")} }
                            if unread_total > 0 { span { class: "badge accent sm", "{unread_total}" } }
                        }
                        ChannelSelect { value: channel_slug.to_string() }
                    }
                    div { class: "search",
                        Icon { name: "search", size: 15 }
                        input {
                            class: "input sm",
                            value: "{query}",
                            placeholder: t("inbox.search"),
                            oninput: move |e| FILTER.write().query = e.value(),
                        }
                    }
                }
            }
            div { class: "tabs hide-mobile", style: "padding: 0 8px; flex: 0 0 auto",
                for (tab, key, n) in tabs.iter().copied() {
                    button {
                        key: "{key}",
                        class: if f.tab == tab { "tab on" } else { "tab" },
                        style: "padding: 10px 6px; font-size: 13px",
                        onclick: move |_| FILTER.write().tab = tab,
                        {t(key)}
                        if n > 0 { span { class: "count", "{n}" } }
                    }
                }
            }
            div { class: "pane-body hide-mobile",
                ConvRows { rows: rows.clone(), selected }
            }
            // phone
            div { class: "only-mobile stack gap-12",
                PageHeader { title: t("nav.inbox"), subtitle: sub }
                div { class: "row gap-8",
                    div { class: "search grow",
                        Icon { name: "search", size: 16 }
                        input {
                            class: "input",
                            value: "{query}",
                            placeholder: t("inbox.search"),
                            oninput: move |e| FILTER.write().query = e.value(),
                        }
                    }
                    ChannelSelect { value: channel_slug.to_string() }
                }
                div { class: "chips",
                    for (tab, key, n) in tabs.iter().copied() {
                        button {
                            key: "m{key}",
                            class: if f.tab == tab { "chip on" } else { "chip" },
                            onclick: move |_| FILTER.write().tab = tab,
                            {t(key)}
                            if n > 0 { span { class: "count", "{n}" } }
                        }
                    }
                }
                div { class: "card", style: "overflow: hidden",
                    ConvRows { rows: rows.clone(), selected }
                }
            }
        }
    }
}

#[component]
fn ChannelSelect(value: String) -> Element {
    rsx! {
        select {
            class: "select sm",
            style: "width: auto; max-width: 160px",
            onchange: move |e| FILTER.write().channel = Channel::from_slug(&e.value()),
            option { value: "", selected: value.is_empty(), {t("inbox.all_channels")} }
            for ch in Channel::ALL.iter().copied() {
                option { key: "{ch.slug()}", value: "{ch.slug()}", selected: value == ch.slug(), {t(ch.key())} }
            }
        }
    }
}

#[component]
fn ConvRows(rows: Vec<Row>, selected: Option<u32>) -> Element {
    if rows.is_empty() {
        return rsx! {
            Empty { icon: "inbox", title: t("inbox.empty_tab"), text: t("inbox.empty_tab_text") }
        };
    }
    rsx! {
        div { class: "list",
            for r in rows.iter().cloned() {
                ConvRow { key: "{r.id}", active: selected == Some(r.id), r: r.clone() }
            }
        }
    }
}

#[component]
fn ConvRow(r: Row, active: bool) -> Element {
    let now = now();
    let l = lang();
    let tone = channel_tone(r.channel);
    let icon = crm::db::channel_icon(r.channel);
    let when = r.at.map(|a| fmt::relative(a, now, l)).unwrap_or_default();
    let you = if r.outbound && r.last_kind != MsgKind::Note { format!("{}: ", t("inbox.you")) } else { String::new() };
    let kind_icon = match r.last_kind {
        MsgKind::Photo => Some("image"),
        MsgKind::File => Some("paperclip"),
        MsgKind::Voice => Some("mic"),
        MsgKind::Note => Some("sticky-note"),
        _ => None,
    };
    let wait = r.waiting.filter(|m| *m >= 30).map(|m| wait_label(m, l));
    let cls = if active { "list-row click active" } else { "list-row click" };
    let id = r.id;
    let title_style = if r.unread > 0 { "font-weight: 720" } else { "" };
    let sub_style = if r.unread > 0 { "color: var(--c-text)" } else { "" };
    let lead_label = t("common.lead");
    rsx! {
        div { class: "{cls}", onclick: move |_| go(&format!("/inbox/{id}")),
            div { style: "position: relative; flex: 0 0 auto",
                Avatar { name: r.title.clone() }
                span {
                    class: "ic {tone}",
                    style: "position:absolute; right:-5px; bottom:-3px; width:17px; height:17px; border-radius:6px; box-shadow:0 0 0 2px var(--c-surface)",
                    Icon { name: icon, size: 10 }
                }
            }
            div { class: "meta",
                div { class: "row between",
                    span { class: "row gap-4", style: "min-width: 0",
                        span { class: "title truncate small", style: "{title_style}", "{r.title}" }
                        if r.starred { span { class: "tone-warning", style: "display:inline-flex", Icon { name: "star", size: 12 } } }
                        if r.lead { span { class: "badge sm info", "{lead_label}" } }
                    }
                    span { class: "xs subtle nowrap", "{when}" }
                }
                div { class: "row between",
                    span { class: "sub row gap-4", style: "{sub_style}",
                        if let Some(i) = kind_icon { Icon { name: i, size: 12 } }
                        span { class: "truncate", "{you}{r.last}" }
                    }
                    if r.unread > 0 { span { class: "badge accent sm", "{r.unread}" } }
                }
                if let Some(w) = wait {
                    span { class: "xs tone-danger row gap-4 strong", Icon { name: "clock", size: 11 } "{w}" }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- thread pane

#[derive(Clone, Debug, PartialEq)]
enum Item {
    Day(String),
    Msg(Message, String),
}

#[component]
fn ThreadPane(id: u32) -> Element {
    // Opening a thread marks it read.
    use_effect(move || {
        let has = DB.peek().conversation(id).map(|c| c.unread > 0).unwrap_or(false);
        if has {
            mutate(|db| {
                if let Some(c) = db.conversation_mut(id) {
                    c.unread = 0;
                }
            });
        }
    });
    let now = now();
    let today = now.date();
    let l = lang();
    let data = {
        let db = DB.read();
        db.conversation(id).cloned().map(|c| {
            let staff: Vec<(Id, String)> = db.staff.iter().filter(|s| s.active).map(|s| (s.id, s.name.clone())).collect();
            let mut items = Vec::new();
            let mut day = None;
            for m in &c.messages {
                let d = m.at.date();
                if day != Some(d) {
                    day = Some(d);
                    let label = match (d - today).num_days() {
                        0 => t("common.today"),
                        -1 => t("common.yesterday"),
                        _ => fmt::date(d, today, l),
                    };
                    items.push(Item::Day(label));
                }
                let author = if m.inbound { String::new() } else { db.staff_name(m.author_id).split_whitespace().next().unwrap_or("").to_string() };
                items.push(Item::Msg(m.clone(), author));
            }
            (c, staff, items)
        })
    };
    let Some((conv, staff, items)) = data else {
        return rsx! {
            div { class: "pane thread-pane",
                Empty { icon: "inbox", title: t("common.no_results"),
                    button { class: "btn", onclick: move |_| go("/inbox"), Icon { name: "arrow-left", size: 16 } {t("common.back")} }
                }
            }
        };
    };
    let channel = conv.channel;
    let handle = if matches!(channel, Channel::Sms | Channel::WhatsApp | Channel::Phone) { phone(&conv.handle) } else { conv.handle.clone() };
    let channel_name = t(channel.key());
    let channel_icon = crm::db::channel_icon(channel);
    let tone = channel_tone(channel);
    let assigned = conv.assigned_to;
    let starred = conv.starred;
    let resolved = conv.status == ConvStatus::Resolved;
    let wait = if resolved { None } else { conv.waiting_min(now).filter(|m| *m >= 30).map(|m| wait_label(m, l)) };
    let title = conv.title.clone();
    let is_lead = conv.customer_id.is_none() && conv.lead_id.is_some();
    let status_key = conv.status.key();

    let set_status = move |to: ConvStatus| {
        let now = crate::state::now();
        let text = if to == ConvStatus::Resolved { t("inbox.resolved_toast") } else { t("inbox.reopened_toast") };
        let sys = text.clone();
        mutate(move |db| {
            let me = db.settings.me;
            let mid = db.new_id();
            if let Some(c) = db.conversation_mut(id) {
                c.status = to;
                if to == ConvStatus::Resolved {
                    c.unread = 0;
                }
                c.messages.push(Message { id: mid, inbound: false, author_id: Some(me), text: sys, at: now, kind: MsgKind::System });
            }
        });
        toast(text, if to == ConvStatus::Resolved { "check-check" } else { "rotate-ccw" }, "success");
    };

    rsx! {
        div { class: "pane thread-pane",
            div { class: "pane-head",
                button { class: "icon-btn sm only-mobile", onclick: move |_| go("/inbox"), Icon { name: "arrow-left", size: 18 } }
                Avatar { name: title.clone() }
                div { class: "grow", style: "min-width: 0",
                    div { class: "row gap-8",
                        span { class: "strong truncate", "{title}" }
                        if is_lead { Badge { text: t("common.lead"), tone: "info" } }
                        if resolved { span { class: "hide-mobile", Badge { text: t(status_key), tone: "success", dot: true } } }
                    }
                    div { class: "row gap-4 xs muted", style: "margin-top: 2px; overflow: hidden",
                        span { class: "tone-{tone}", style: "display:inline-flex", Icon { name: channel_icon, size: 12 } }
                        span { class: "nowrap", "{channel_name}" }
                        span { class: "subtle", "·" }
                        span { class: "truncate", "{handle}" }
                    }
                }
                select {
                    class: "select sm hide-mobile",
                    style: "width: 132px",
                    title: t("common.assign"),
                    onchange: move |e| {
                        let v: u32 = e.value().parse().unwrap_or(0);
                        let who = if v == 0 { None } else { Some(v) };
                        let name = DB.peek().staff_name(who);
                        let now = crate::state::now();
                        let sys = format!("{}: {}", t("inbox.assigned"), if who.is_some() { name.clone() } else { t("common.unassigned") });
                        mutate(move |db| {
                            let me = db.settings.me;
                            let mid = db.new_id();
                            if let Some(c) = db.conversation_mut(id) {
                                c.assigned_to = who;
                                c.messages.push(Message { id: mid, inbound: false, author_id: Some(me), text: sys, at: now, kind: MsgKind::System });
                            }
                        });
                        if who.is_some() {
                            toast(format!("{} · {}", t("inbox.assigned"), name), "user-check", "success");
                        }
                    },
                    option { value: "0", selected: assigned.is_none(), {t("common.unassigned")} }
                    for (sid, name) in staff.iter().cloned() {
                        option { key: "{sid}", value: "{sid}", selected: assigned == Some(sid), "{name}" }
                    }
                }
                button {
                    class: if starred { "icon-btn sm tone-warning" } else { "icon-btn sm" },
                    title: t("inbox.star"),
                    onclick: move |_| mutate(|db| {
                        if let Some(c) = db.conversation_mut(id) {
                            c.starred = !c.starred;
                        }
                    }),
                    Icon { name: "star", size: 17 }
                }
                if resolved {
                    button { class: "btn sm", onclick: move |_| set_status(ConvStatus::Open),
                        Icon { name: "rotate-ccw", size: 14 }
                        span { class: "hide-mobile", {t("inbox.reopen")} }
                    }
                } else {
                    button { class: "btn sm", onclick: move |_| set_status(ConvStatus::Resolved),
                        Icon { name: "check-check", size: 14 }
                        span { class: "hide-mobile", {t("inbox.resolve")} }
                    }
                }
            }
            div { class: "thread", style: "flex-direction: column-reverse",
                if let Some(w) = wait.clone() {
                    div { class: "day-sep row gap-4", style: "padding-top: 10px; color: var(--c-danger)", Icon { name: "clock", size: 12 } "{w}" }
                }
                for (k, item) in items.into_iter().enumerate().rev() {
                    {match item {
                        Item::Day(label) => rsx! { div { key: "d{k}", class: "day-sep", "{label}" } },
                        Item::Msg(m, author) => {
                            let mid = m.id;
                            rsx! { Bubble { key: "{mid}", m, author } }
                        }
                    }}
                }
            }
            Composer { id }
        }
    }
}

#[component]
fn Bubble(m: Message, author: String) -> Element {
    let time = fmt::time(m.at);
    let text = m.text.clone();
    match m.kind {
        MsgKind::System => rsx! {
            div { class: "bubble system row gap-4", Icon { name: "info", size: 12 } span { "{text} · {time}" } }
        },
        MsgKind::Note => {
            let label = t("msg_kind.note");
            rsx! {
                div { class: "bubble note",
                    div { class: "row gap-4 xs strong", style: "margin-bottom: 2px", Icon { name: "sticky-note", size: 12 } "{label} · {author}" }
                    span { "{text}" }
                    span { class: "time", "{time}" }
                }
            }
        }
        kind => {
            let cls = if m.inbound { "bubble in" } else { "bubble out" };
            let meta = if author.is_empty() { time.clone() } else { format!("{author} · {time}") };
            let rx_photo = latinize(&text).contains("retsept");
            let photo_label = if rx_photo { t("inbox.rx_photo") } else { format!("{} · {}", t("msg_kind.photo"), text) };
            let photo_hint = t("inbox.photo_hint");
            let photo_icon: &'static str = if rx_photo { "file-check" } else { "image" };
            let voice_len = text.rsplit(' ').next().unwrap_or("").to_string();
            let voice_label = t("msg_kind.voice");
            rsx! {
                div { class: "{cls}",
                    {match kind {
                        MsgKind::Photo => rsx! {
                            div { class: "stack gap-8", style: "width: 220px; max-width: 100%",
                                div {
                                    style: "height: 132px; border-radius: 12px; display: grid; place-items: center; background: linear-gradient(135deg, var(--c-surface-2), var(--c-surface-3)); color: var(--c-muted)",
                                    div { class: "stack gap-4", style: "align-items: center",
                                        Icon { name: photo_icon, size: 30 }
                                        span { class: "xs", "JPG · 1,2 MB" }
                                    }
                                }
                                div { class: "row gap-8",
                                    Icon { name: "image", size: 15 }
                                    div { class: "stack gap-4", style: "gap: 0",
                                        span { class: "small strong", "{photo_label}" }
                                        span { class: "xs muted", "{photo_hint}" }
                                    }
                                }
                            }
                        },
                        MsgKind::File => rsx! {
                            div { class: "attachment",
                                Icon { name: "file-text", size: 18 }
                                div { class: "stack", style: "gap: 0",
                                    span { class: "small", "{text}" }
                                    span { class: "xs", style: "opacity: .7", "PDF · 214 KB" }
                                }
                                Icon { name: "download", size: 15 }
                            }
                        },
                        MsgKind::Voice => rsx! {
                            div { class: "attachment",
                                Icon { name: "circle-play", size: 20 }
                                div { class: "row", style: "gap: 2px; align-items: center",
                                    for (k, h) in [6, 12, 9, 16, 7, 14, 10, 18, 8, 12, 6, 10, 15, 7].iter().enumerate() {
                                        span { key: "{k}", style: "width: 3px; height: {h}px; border-radius: 2px; background: currentColor; opacity: .55" }
                                    }
                                }
                                span { class: "xs", "{voice_label} · {voice_len}" }
                            }
                        },
                        _ => rsx! { span { style: "white-space: pre-wrap", "{text}" } },
                    }}
                    span { class: "time row gap-4", style: "display: inline-flex",
                        "{meta}"
                        if !m.inbound { Icon { name: "check-check", size: 12 } }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- composer

/// A pack the customer asked for that their branch has: (product, name, qty, branch, branch name, total).
fn hold_for(db: &Db, id: Id) -> Option<(Id, String, u32, Id, String, Money)> {
    let c = db.conversation(id)?;
    let last = c.messages.iter().rev().find(|m| m.kind != MsgKind::Note && m.kind != MsgKind::System)?;
    if !last.inbound {
        return None;
    }
    let x = context(db, c);
    let p = x.product?;
    let b = x.branch?;
    // The asked branch if it has the pack, otherwise the branch with the most stock.
    let (bid, bname, stock) = if p.stock_at(b.id) > 0 {
        (b.id, b.name.clone(), p.stock_at(b.id))
    } else {
        let s = p.stock.iter().filter(|s| s.qty > 0).max_by_key(|s| s.qty)?;
        let br = db.branch(s.branch_id)?;
        (br.id, br.name.clone(), s.qty)
    };
    let qty = x.qty.min(stock).max(1);
    Some((p.id, p.name.clone(), qty, bid, bname, p.price * qty as Money))
}

#[component]
fn Composer(id: u32) -> Element {
    let mut draft = use_signal(String::new);
    let mut note = use_signal(|| false);
    let mut menu = use_signal(|| false);
    let mut reserved = use_signal(|| false);
    let hold = use_memo(move || hold_for(&DB.read(), id));
    let suggestion = use_memo(move || {
        let db = DB.read();
        db.conversation(id).and_then(|c| suggest(&db, c))
    });
    let violation = if note() { None } else { rx_promo(&DB.read(), &draft()) };
    let can_send = !draft().trim().is_empty() && violation.is_none();
    let tpl_ru = {
        let db = DB.read();
        db.conversation(id).map(|c| context(&db, c).ru).unwrap_or(false)
    };

    let mut send = move || {
        let text = draft().trim().to_string();
        if text.is_empty() {
            return;
        }
        let as_note = note();
        if !as_note && rx_promo(&DB.peek(), &text).is_some() {
            return;
        }
        let now = crate::state::now();
        let channel = DB.peek().conversation(id).map(|c| c.channel).unwrap_or(Channel::Telegram);
        mutate(move |db| {
            let me = db.settings.me;
            let mid = db.new_id();
            if let Some(c) = db.conversation_mut(id) {
                c.messages.push(Message {
                    id: mid,
                    inbound: false,
                    author_id: Some(me),
                    text,
                    at: now,
                    kind: if as_note { MsgKind::Note } else { MsgKind::Text },
                });
                if !as_note {
                    if c.status == ConvStatus::Resolved {
                        c.status = ConvStatus::Open;
                    }
                    if c.assigned_to.is_none() {
                        c.assigned_to = Some(me);
                    }
                }
            }
        });
        draft.set(String::new());
        if as_note {
            toast(t("inbox.note_saved"), "sticky-note", "success");
        } else {
            toast(format!("{} · {}", t("inbox.sent"), t(channel.key())), "send", "success");
        }
    };

    let templates: Vec<(usize, &'static str, String, String, String)> = if menu() {
        let db = DB.read();
        match db.conversation(id) {
            Some(c) => {
                let x = context(&db, c);
                TEMPLATES
                    .iter()
                    .enumerate()
                    .map(|(i, (key, icon))| {
                        let text = template_text(i, &x);
                        (i, *icon, t(key), text.clone(), text)
                    })
                    .filter(|x| !x.3.is_empty())
                    .collect()
            }
            None => Vec::new(),
        }
    } else {
        Vec::new()
    };
    let tpl_lang = if tpl_ru { t("inbox.tpl_lang_ru") } else { t("inbox.tpl_lang_uz") };
    let sug = suggestion().filter(|s| *s != draft());
    let composer_style = if note() { "background: var(--c-warning-soft)" } else { "" };
    let placeholder = if note() { t("inbox.note_placeholder") } else { t("inbox.placeholder") };
    let ai_note = t("inbox.ai_note");
    let send_icon: &'static str = if note() { "check" } else { "send" };
    let sug_click = sug.clone();
    let hold_v = if reserved() { None } else { hold() };
    let hold_text = hold_v.as_ref().map(|h| format!("{}: {} × {} · {} · {}", t("inbox.reservation"), h.1, h.2, h.4, money(h.5)));
    let reserve = move |_| {
        let Some((pid, _, qty, bid, _, _)) = hold.peek().clone() else { return };
        let Some(text) = hold_text.clone() else { return };
        let now = crate::state::now();
        mutate(move |db| {
            if let Some(p) = db.product_mut(pid) {
                if let Some(s) = p.stock.iter_mut().find(|s| s.branch_id == bid) {
                    s.qty = s.qty.saturating_sub(qty);
                }
            }
            let me = db.settings.me;
            let mid = db.new_id();
            if let Some(c) = db.conversation_mut(id) {
                c.messages.push(Message { id: mid, inbound: false, author_id: Some(me), text: text.clone(), at: now, kind: MsgKind::System });
            }
            db.log(now, text, false);
        });
        reserved.set(true);
        toast(t("inbox.reserved_toast"), "package-check", "success");
    };

    rsx! {
        div { class: "composer", style: "{composer_style}",
            if let Some(s) = sug.clone() {
                if !note() {
                    div { class: "row gap-8", style: "align-items: flex-start; padding: 2px 2px 6px; border-bottom: 1px dashed var(--c-border)",
                        span { class: "ai-chip", title: "{ai_note}", style: "flex: 0 0 auto", Icon { name: "sparkles", size: 12 } "AI · Haiku" }
                        div { class: "grow stack", style: "gap: 2px",
                            span { class: "small clamp-2", "{s}" }
                            span { class: "xs subtle", "{ai_note}" }
                        }
                        div { class: "stack gap-4", style: "flex: 0 0 auto",
                            button {
                                class: "btn soft sm",
                                onclick: move |_| {
                                    if let Some(x) = sug_click.clone() {
                                        draft.set(x);
                                    }
                                },
                                Icon { name: "wand-sparkles", size: 14 }
                                {t("inbox.use")}
                            }
                            if hold_v.is_some() {
                                button { class: "btn sm", onclick: reserve,
                                    Icon { name: "package-check", size: 14 }
                                    {t("inbox.reserve")}
                                }
                            }
                        }
                    }
                }
            }
            if let Some(p) = violation.clone() {
                div { class: "callout danger",
                    Icon { name: "shield-alert", size: 18 }
                    div { class: "stack", style: "gap: 2px",
                        span { class: "strong", {t("inbox.rx_block_title")} }
                        span { {t("inbox.rx_block_text").replace("{p}", &p)} }
                    }
                }
            }
            textarea {
                rows: "2",
                style: "outline: none",
                value: "{draft}",
                placeholder: "{placeholder}",
                oninput: move |e| draft.set(e.value()),
                onkeydown: move |e: KeyboardEvent| {
                    if e.key() == Key::Enter && !e.modifiers().shift() {
                        e.prevent_default();
                        send();
                    }
                },
            }
            div { class: "row between",
                div { class: "row gap-4",
                    div { class: "popover-anchor",
                        button { class: "btn ghost sm", onclick: move |_| menu.toggle(),
                            Icon { name: "zap", size: 14 }
                            span { class: "hide-mobile", {t("inbox.templates")} }
                        }
                        if menu() {
                            div { style: "position: fixed; inset: 0; z-index: 39", onclick: move |_| menu.set(false) }
                            div { class: "menu", style: "bottom: 38px; left: 0; width: min(360px, 82vw)",
                                div { class: "xs subtle upper", style: "padding: 6px 10px 4px", "{tpl_lang}" }
                                for (i, icon, label, text, fill) in templates {
                                    button {
                                        key: "{i}",
                                        class: "menu-item",
                                        style: "align-items: flex-start",
                                        onclick: move |_| {
                                            draft.set(fill.clone());
                                            menu.set(false);
                                        },
                                        Icon { name: icon, size: 16 }
                                        div { class: "stack", style: "gap: 2px; min-width: 0",
                                            span { class: "small strong", "{label}" }
                                            span { class: "xs muted clamp-2", "{text}" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    button {
                        class: if note() { "btn soft sm" } else { "btn ghost sm" },
                        onclick: move |_| note.toggle(),
                        Icon { name: "sticky-note", size: 14 }
                        span { class: "hide-mobile", {t("inbox.note")} }
                    }
                    button { class: "btn primary sm only-mobile", disabled: !can_send, onclick: move |_| send(),
                        Icon { name: send_icon, size: 14 }
                        if note() { {t("inbox.save_note")} } else { {t("inbox.send")} }
                    }
                }
                button { class: "btn primary sm hide-mobile", disabled: !can_send, onclick: move |_| send(),
                    Icon { name: send_icon, size: 14 }
                    if note() { {t("inbox.save_note")} } else { {t("inbox.send")} }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- side pane (customer 360 / lead)

#[component]
fn SidePane(id: u32) -> Element {
    let link = DB.read().conversation(id).map(|c| (c.customer_id, c.lead_id));
    rsx! {
        div { class: "pane side",
            div { class: "pane-body",
                {match link {
                    Some((Some(cid), _)) => rsx! { CustomerMini { cid } },
                    Some((None, Some(lid))) => rsx! { LeadMini { lid, conv: id } },
                    _ => rsx! { Empty { icon: "user", title: t("common.none") } },
                }}
            }
        }
    }
}

#[component]
fn MiniSection(title: String, icon: &'static str, children: Element) -> Element {
    rsx! {
        div { class: "stack gap-8",
            div { class: "row gap-8 upper subtle", Icon { name: icon, size: 13 } "{title}" }
            {children}
        }
    }
}

#[component]
fn CustomerMini(cid: u32) -> Element {
    let now = now();
    let today = now.date();
    let l = lang();
    let privacy = DB.read().settings.privacy_mode;
    let data = {
        let db = DB.read();
        db.customer(cid).cloned().map(|c| {
            let branch = db.branch_name(Some(c.home_branch));
            let regimens: Vec<(String, String, i64)> = if c.consent.health_data {
                c.regimens.iter().map(|r| (db.product_name(Some(r.product_id)), r.dose.clone(), r.days_left(today))).collect()
            } else {
                Vec::new()
            };
            let purchases: Vec<(Id, String, Money, String)> = db
                .purchases_of(cid)
                .into_iter()
                .take(3)
                .map(|p| {
                    let names: Vec<String> = p.items.iter().take(2).map(|i| db.product_name(Some(i.product_id))).collect();
                    (p.id, fmt::date(p.at.date(), today, l), p.total, names.join(", "))
                })
                .collect();
            let tickets: Vec<(Id, String, String, &'static str)> = db
                .tickets
                .iter()
                .filter(|tk| tk.customer_id == Some(cid) && tk.is_open())
                .map(|tk| (tk.id, format!("{} · {}", tk.number, tk.subject), t(tk.status.key()), if tk.kind == TicketKind::AdverseReaction { "danger" } else { "warning" }))
                .collect();
            let summary = if c.orders == 0 {
                t("inbox.summary_new").replace("{n}", &fmt::num(c.points))
            } else {
                let s = crm::analytics::customer_summary(&db, cid, now, l);
                let seg = crm::analytics::rfm(&c, today).segment;
                let label = t(seg.key());
                let cyr = crm::i18n::to_cyrillic(seg.slug());
                match s.rfind(seg.slug()).map(|p| (p, seg.slug().len())).or_else(|| s.rfind(&cyr).map(|p| (p, cyr.len()))) {
                    Some((p, n)) => format!("{}{}{}", &s[..p], label, &s[p + n..]),
                    None => s,
                }
            };
            (c, branch, regimens, purchases, tickets, summary)
        })
    };
    let Some((c, branch, regimens, purchases, tickets, summary)) = data else {
        return rsx! { Empty { icon: "user-x", title: t("common.no_results") } };
    };
    let name = c.name();
    let phone_text = phone(&c.phone);
    let last_visit = c.last_purchase.map(|d| fmt::due_in(d, today, l)).unwrap_or_else(|| "—".into());
    let stats = vec![
        (t("inbox.ltv"), money_short(c.total_spent)),
        (t("inbox.points_short"), fmt::num(c.points)),
        (t("inbox.orders"), fmt::num(c.orders as i64)),
    ];
    let health = c.consent.health_data;
    let mask = if privacy { "mask" } else { "" };
    let sub_line = format!("{branch} · {last_visit}");
    let task_title = format!("{}: {}", name, t("inbox.callback_title"));
    let callback = move |_| {
        let now = crate::state::now();
        let title = task_title.clone();
        let due = (now.date() + Duration::days(1)).and_hms_opt(10, 0, 0).unwrap_or(now);
        mutate(move |db| {
            let me = db.settings.me;
            db.add_activity(Activity {
                id: 0,
                kind: ActivityKind::Call,
                title,
                notes: String::new(),
                due,
                done: false,
                done_at: None,
                owner_id: me,
                customer_id: Some(cid),
                company_id: None,
                deal_id: None,
                ticket_id: None,
                priority: Priority::Normal,
                outcome: None,
                duration_min: 5,
                daybook_task: None,
            });
        });
        toast(t("inbox.callback_saved"), "phone-call", "success");
    };
    rsx! {
        div { class: "stack gap-16", style: "padding: 18px",
            div { class: "stack gap-8", style: "align-items: center; text-align: center",
                Avatar { name: name.clone(), size: "xl" }
                div { class: "stack gap-4", style: "align-items: center",
                    span { class: "strong", style: "font-size: 16px", "{name}" }
                    TierBadge { tier: c.tier }
                }
                span { class: "small muted num", "{phone_text}" }
                span { class: "xs subtle", "{sub_line}" }
            }
            div { class: "row", style: "gap: 8px; align-items: stretch",
                for (label, value) in stats {
                    div { key: "{label}", class: "grow stack", style: "gap: 2px; background: var(--c-surface-2); border-radius: 10px; padding: 8px 10px",
                        span { class: "xs muted truncate", "{label}" }
                        span { class: "strong num small nowrap", "{value}" }
                    }
                }
            }
            div { class: "ai-panel stack gap-8", style: "padding: 12px 14px",
                span { class: "ai-chip", style: "align-self: flex-start", Icon { name: "sparkles", size: 12 } {t("inbox.summary")} }
                p { class: "small", style: "line-height: 1.5", "{summary}" }
            }
            MiniSection { title: t("inbox.regimens"), icon: "pill",
                if !health {
                    span { class: "small muted", {t("inbox.no_health_consent")} }
                } else if regimens.is_empty() {
                    span { class: "small muted", {t("inbox.no_regimens")} }
                }
                for (k, (pname, dose, left)) in regimens.into_iter().enumerate() {
                    {
                        let tone = if left < 0 { "danger" } else if left <= 3 { "warning" } else { "success" };
                        let due = fmt::due_in(today + Duration::days(left), today, l);
                        rsx! {
                            div { key: "{k}", class: "row gap-8",
                                IconTile { icon: "repeat", tone, size: "sm" }
                                div { class: "grow stack", style: "gap: 0",
                                    span { class: "small strong truncate {mask}", "{pname}" }
                                    span { class: "xs muted truncate {mask}", "{dose}" }
                                }
                                Badge { text: due, tone }
                            }
                        }
                    }
                }
            }
            MiniSection { title: t("inbox.last_purchases"), icon: "shopping-bag",
                if purchases.is_empty() { span { class: "small muted", {t("common.none")} } }
                for (pid, date, total, names) in purchases {
                    div { key: "{pid}", class: "stack", style: "gap: 1px; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--c-border)",
                        div { class: "row between",
                            span { class: "small strong", "{date}" }
                            MoneyText { value: total }
                        }
                        span { class: "xs muted truncate", "{names}" }
                    }
                }
            }
            MiniSection { title: t("inbox.open_tickets"), icon: "life-buoy",
                if tickets.is_empty() { span { class: "small muted", {t("inbox.no_open_tickets")} } }
                for (tid, subject, status, tone) in tickets {
                    div { key: "{tid}", class: "row gap-8 click", style: "cursor: pointer", onclick: move |_| go(&format!("/tickets/{tid}")),
                        IconTile { icon: "life-buoy", tone, size: "sm" }
                        div { class: "grow stack", style: "gap: 0",
                            span { class: "small strong truncate", "{subject}" }
                            span { class: "xs muted", "{status}" }
                        }
                    }
                }
            }
            div { class: "grid-2", style: "gap: 8px",
                button { class: "btn sm", onclick: callback,
                    Icon { name: "phone-call", size: 14 }
                    {t("inbox.callback")}
                }
                button { class: "btn sm", onclick: move |_| go(&format!("/contacts/{cid}")),
                    Icon { name: "contact", size: 14 }
                    {t("inbox.open_customer")}
                }
            }
        }
    }
}

#[component]
fn LeadMini(lid: u32, conv: u32) -> Element {
    let now = now();
    let l = lang();
    let lead = DB.read().lead(lid).cloned();
    let Some(lead) = lead else {
        return rsx! { Empty { icon: "magnet", title: t("common.no_results") } };
    };
    let phone_text = phone(&lead.phone);
    let when = fmt::relative(lead.at, now, l);
    let estimate = if lead.estimate > 0 { money_short(lead.estimate) } else { "—".to_string() };
    let score = lead.score;
    let score_tone = score_tone(score);
    let status = t(lead.status.key());
    let channel = t(lead.channel.key());
    let items = vec![
        (t("common.phone"), phone_text),
        (t("inbox.interest"), lead.interest.clone()),
        (t("inbox.estimate"), estimate),
        (t("common.created"), when),
    ];
    let converted = lead.status == LeadStatus::Converted;
    let convert = move |_| {
        let now = crate::state::now();
        mutate(move |db| {
            let Some(lead) = db.lead(lid).cloned() else { return };
            let cid = db.new_id();
            let mut parts = lead.name.split_whitespace();
            let first = parts.next().unwrap_or("").to_string();
            let last = parts.collect::<Vec<_>>().join(" ");
            let lat = latinize(&lead.message);
            let branch = mentioned_branch(db, &lat).or_else(|| db.branches.first().map(|b| b.id)).unwrap_or(0);
            let handle = db.conversation(conv).map(|c| c.handle.clone()).unwrap_or_default();
            let me = db.settings.me;
            let welcome = db.settings.loyalty.welcome_bonus;
            let female = first.ends_with('a') || first.ends_with("oz") || first.ends_with("so");
            db.customers.push(Customer {
                id: cid,
                first_name: first,
                last_name: last,
                gender: if female { Gender::Female } else { Gender::Male },
                phone: lead.phone.clone(),
                telegram: if handle.starts_with('@') { Some(handle) } else { None },
                birth_date: None,
                district: String::new(),
                home_branch: branch,
                owner_id: Some(me),
                tags: Vec::new(),
                tier: Tier::Bronze,
                points: 0,
                card_no: format!("7801{cid:08}"),
                source: match lead.channel {
                    Channel::Telegram => Source::Telegram,
                    Channel::Instagram => Source::Instagram,
                    Channel::Web => Source::Website,
                    Channel::Phone => Source::Call,
                    _ => Source::WalkIn,
                },
                consent: Consent { sms: false, telegram: lead.channel == Channel::Telegram, health_data: false, given_on: Some(now.date()) },
                regimens: Vec::new(),
                allergies: Vec::new(),
                company_id: None,
                created: now.date(),
                lang: if lead.message.chars().any(is_cyrillic) { Lang::Ru } else { Lang::Uz },
                notes: lead.message.clone(),
                nps: None,
                total_spent: 0,
                orders: 0,
                first_purchase: None,
                last_purchase: None,
                archived: false,
                referred_by: None,
            });
            if welcome > 0 {
                db.give_points(cid, welcome, TxKind::Bonus, "Welcome", now);
            }
            if let Some(x) = db.lead_mut(lid) {
                x.status = LeadStatus::Converted;
                x.converted_customer = Some(cid);
            }
            if let Some(c) = db.conversation_mut(conv) {
                c.customer_id = Some(cid);
                c.tags.retain(|tg| tg != "Lid");
            }
            db.log(now, format!("Lid → mijoz: {}", lead.name), false);
        });
        toast(t("inbox.converted"), "user-check", "success");
    };
    rsx! {
        div { class: "stack gap-16", style: "padding: 18px",
            div { class: "stack gap-8", style: "align-items: center; text-align: center",
                Avatar { name: lead.name.clone(), size: "xl" }
                span { class: "strong", style: "font-size: 16px", "{lead.name}" }
                div { class: "row gap-4",
                    Badge { text: t("common.lead"), tone: "info", icon: Some("magnet") }
                    Badge { text: status, tone: "accent" }
                }
                span { class: "xs subtle", "{channel}" }
            }
            div { class: "callout accent", style: "font-size: 13px",
                Icon { name: "message-square", size: 16 }
                span { "{lead.message}" }
            }
            MiniSection { title: t("inbox.lead_info"), icon: "info",
                KeyValues { items }
            }
            MiniSection { title: t("inbox.score"), icon: "gauge",
                div { class: "row gap-8",
                    div { class: "grow", Progress { pct: score as f64, tone: score_tone } }
                    span { class: "strong num small", "{score}/100" }
                }
            }
            if !converted {
                div { class: "stack gap-8",
                    button { class: "btn primary block", onclick: convert, Icon { name: "user-plus", size: 16 } {t("inbox.convert")} }
                    span { class: "xs subtle center", {t("inbox.convert_hint")} }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- nothing selected (desktop)

#[component]
fn Overview() -> Element {
    let l = lang();
    let stats = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let open = db.conversations.iter().filter(|c| c.status != ConvStatus::Resolved).count();
        let waiting = db.conversations.iter().filter(|c| c.status != ConvStatus::Resolved && c.waiting_min(now).map_or(false, |m| m >= 30)).count();
        let mut gaps = Vec::new();
        for c in &db.conversations {
            if let Some(i) = c.messages.iter().position(|m| m.inbound) {
                if let Some(o) = c.messages[i..].iter().find(|m| !m.inbound && m.kind == MsgKind::Text) {
                    gaps.push((o.at - c.messages[i].at).num_minutes().max(1));
                }
            }
        }
        let avg = if gaps.is_empty() { 0 } else { gaps.iter().sum::<i64>() / gaps.len() as i64 };
        (open, waiting, db.unread_inbox(), avg)
    });
    let (open, waiting, unread, avg) = stats();
    let tiles = vec![
        ("clock", "danger", fmt::num(waiting as i64), t("inbox.waiting_reply")),
        ("mail", "accent", fmt::num(unread as i64), t("inbox.unread")),
        ("timer", "success", minutes_short(avg, l), t("inbox.avg_first_reply")),
    ];
    let _ = open;
    rsx! {
        div { class: "pane thread-pane",
            div { class: "pane-body", style: "display: grid; place-items: center; padding: 24px; background: var(--c-canvas)",
                div { class: "stack gap-16", style: "max-width: 440px; width: 100%; align-items: center",
                    Empty { icon: "message-circle-heart", title: t("inbox.pick"), text: t("inbox.pick_text") }
                    div { class: "grid-3", style: "width: 100%; gap: 10px",
                        for (icon, tone, value, label) in tiles {
                            div { key: "{label}", class: "card stack gap-4", style: "padding: 14px 10px; align-items: center; text-align: center",
                                IconTile { icon, tone, size: "sm" }
                                span { class: "strong num", style: "font-size: 20px", "{value}" }
                                span { class: "xs muted", "{label}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn OverviewSide() -> Element {
    let data = use_memo(move || {
        let db = DB.read();
        let mut by_channel: Vec<(Channel, usize)> = Channel::ALL
            .iter()
            .map(|ch| (*ch, db.conversations.iter().filter(|c| c.channel == *ch && c.status != ConvStatus::Resolved).count()))
            .filter(|x| x.1 > 0)
            .collect();
        by_channel.sort_by(|a, b| b.1.cmp(&a.1));
        let mut load: Vec<(String, u16, usize)> = db
            .staff
            .iter()
            .filter(|s| s.active)
            .map(|s| (s.name.clone(), s.hue, db.conversations.iter().filter(|c| c.assigned_to == Some(s.id) && c.status != ConvStatus::Resolved).count()))
            .filter(|x| x.2 > 0)
            .collect();
        load.sort_by(|a, b| b.2.cmp(&a.2));
        let unassigned = db.conversations.iter().filter(|c| c.assigned_to.is_none() && c.status != ConvStatus::Resolved).count();
        (by_channel, load, unassigned)
    });
    let (by_channel, load, unassigned) = data();
    let items: Vec<(String, f64, String)> = by_channel.iter().map(|(ch, n)| (t(ch.key()), *n as f64, fmt::num(*n as i64))).collect();
    let max = load.iter().map(|x| x.2).max().unwrap_or(1).max(1);
    let unassigned_label = t("common.unassigned");
    rsx! {
        div { class: "pane side",
            div { class: "pane-body",
                div { class: "stack gap-20", style: "padding: 18px",
                    MiniSection { title: t("inbox.by_channel"), icon: "chart-pie",
                        HBars { items }
                    }
                    MiniSection { title: t("inbox.team_load"), icon: "users",
                        for (name, hue, n) in load {
                            div { key: "{name}", class: "row gap-8",
                                Avatar { name: name.clone(), hue: Some(hue), size: "sm" }
                                div { class: "grow stack", style: "gap: 4px",
                                    div { class: "row between",
                                        span { class: "small truncate", "{name}" }
                                        span { class: "small strong num", "{n}" }
                                    }
                                    Progress { pct: n as f64 / max as f64 * 100.0, thin: true }
                                }
                            }
                        }
                        if unassigned > 0 {
                            button {
                                class: "btn soft sm",
                                style: "align-self: flex-start",
                                onclick: move |_| FILTER.write().tab = Tab::Unassigned,
                                Icon { name: "user-x", size: 14 }
                                "{unassigned_label} · {unassigned}"
                            }
                        }
                    }
                }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("inbox.unread", "O‘qilmagan", "Непрочитанные", "Unread"),
    ("inbox.mine", "Meniki", "Мои", "Mine"),
    ("inbox.tab_unread", "Yangi", "Новые", "Unread"),
    ("inbox.tab_free", "Bo‘sh", "Свободные", "Unassigned"),
    ("inbox.tab_closed", "Yopilgan", "Закрытые", "Closed"),
    ("inbox.search", "Ism, raqam yoki xabar…", "Имя, номер или текст…", "Name, number or text…"),
    ("inbox.all_channels", "Barcha kanallar", "Все каналы", "All channels"),
    ("inbox.you", "Siz", "Вы", "You"),
    ("inbox.empty_tab", "Bu yerda suhbat yo‘q", "Здесь пока нет диалогов", "No conversations here"),
    ("inbox.empty_tab_text", "Boshqa filtrni tanlang yoki qidiruvni tozalang.", "Выберите другой фильтр или очистите поиск.", "Try another filter or clear the search."),
    ("inbox.pick", "Suhbatni tanlang", "Выберите диалог", "Pick a conversation"),
    (
        "inbox.pick_text",
        "Telegram, SMS, WhatsApp va Instagram xabarlari bir joyda. Shablonlar va AI javobi bir bosishda tayyor.",
        "Telegram, SMS, WhatsApp и Instagram в одном окне. Шаблоны и ответ AI готовы в один клик.",
        "Telegram, SMS, WhatsApp and Instagram in one place. Templates and an AI reply are one click away.",
    ),
    ("inbox.waiting_reply", "Javob kutmoqda", "Ждут ответа", "Waiting for a reply"),
    ("inbox.avg_first_reply", "O‘rtacha birinchi javob", "Среднее время ответа", "Avg first reply"),
    ("inbox.by_channel", "Kanallar bo‘yicha", "По каналам", "By channel"),
    ("inbox.team_load", "Jamoa yuklamasi", "Нагрузка команды", "Team load"),
    ("inbox.star", "Muhim deb belgilash", "Отметить как важный", "Star"),
    ("inbox.resolve", "Hal qilish", "Решить", "Resolve"),
    ("inbox.reopen", "Qayta ochish", "Открыть снова", "Reopen"),
    ("inbox.resolved_toast", "Suhbat hal qilindi", "Диалог решён", "Conversation resolved"),
    ("inbox.reopened_toast", "Suhbat qayta ochildi", "Диалог снова открыт", "Conversation reopened"),
    ("inbox.assigned", "Biriktirildi", "Назначено", "Assigned"),
    ("inbox.rx_photo", "Retsept rasmi", "Фото рецепта", "Prescription photo"),
    ("inbox.photo_hint", "Farmatsevt tekshiradi", "Проверит фармацевт", "For the pharmacist to check"),
    ("inbox.templates", "Shablonlar", "Шаблоны", "Templates"),
    ("inbox.tpl_available", "Bor: bron taklifi", "Есть в наличии: бронь", "In stock: offer to reserve"),
    ("inbox.tpl_delivery", "Yetkazib berish shartlari", "Условия доставки", "Delivery terms"),
    ("inbox.tpl_price", "Narx va ballar", "Цена и баллы", "Price and points"),
    ("inbox.tpl_rx", "Retsept rasmini so‘rash", "Попросить фото рецепта", "Ask for the prescription photo"),
    ("inbox.tpl_hours", "Ish vaqti va manzil", "Часы работы и адрес", "Opening hours and address"),
    ("inbox.tpl_lang_ru", "Mijozga rus tilida", "Клиенту на русском", "In Russian for this customer"),
    ("inbox.tpl_lang_uz", "Mijozga o‘zbek tilida", "Клиенту на узбекском", "In Uzbek for this customer"),
    ("inbox.ai_note", "Demoda qurilmaning o‘zida hisoblanadi", "В демо считается прямо на устройстве", "Computed on this device in the demo"),
    ("inbox.use", "Qo‘yish", "Вставить", "Use"),
    ("inbox.reserve", "Bron qilish", "Забронировать", "Reserve"),
    ("inbox.reservation", "Bron", "Бронь", "Reserved"),
    ("inbox.reserved_toast", "Bron qilindi: 24 soat saqlanadi", "Забронировано на 24 часа", "Reserved for 24 hours"),
    ("inbox.placeholder", "Javob yozing… (Enter: yuborish)", "Напишите ответ… (Enter: отправить)", "Write a reply… (Enter to send)"),
    ("inbox.note_placeholder", "Ichki izoh: buni faqat jamoa ko‘radi", "Внутренняя заметка: её видит только команда", "Internal note: only your team sees this"),
    ("inbox.note", "Ichki izoh", "Заметка", "Note"),
    ("inbox.send", "Yuborish", "Отправить", "Send"),
    ("inbox.save_note", "Izohni saqlash", "Сохранить заметку", "Save note"),
    ("inbox.sent", "Yuborildi", "Отправлено", "Sent"),
    ("inbox.note_saved", "Izoh saqlandi", "Заметка сохранена", "Note saved"),
    ("inbox.rx_block_title", "Retseptli dorini reklama qilib bo‘lmaydi", "Рецептурный препарат нельзя рекламировать", "Prescription medicines can’t be promoted"),
    (
        "inbox.rx_block_text",
        "{p} retsept bo‘yicha beriladi: aksiya va chegirma so‘zlarini olib tashlang. Tahrirdan keyin yuborish ochiladi.",
        "{p} отпускается по рецепту: уберите слова об акции и скидке. Отправка откроется после правки.",
        "{p} is prescription-only: remove the sale and discount wording. Sending unlocks once you edit it.",
    ),
    ("inbox.ltv", "Jami xarid", "LTV", "Lifetime value"),
    ("inbox.points_short", "Ballar", "Баллы", "Points"),
    ("inbox.orders", "Xaridlar", "Покупки", "Orders"),
    ("inbox.summary", "AI xulosa", "AI-сводка", "AI summary"),
    (
        "inbox.summary_new",
        "Yangi mijoz, hali xarid qilmagan. Hisobida {n} ball bor: birinchi xaridga taklif qiling va doimiy dorilari haqida so‘rang.",
        "Новый клиент, покупок ещё не было. На счёте {n} баллов: пригласите на первую покупку и спросите о постоянных препаратах.",
        "A new customer with no purchases yet and {n} points to spend: invite them for a first purchase and ask about regular medicines.",
    ),
    ("inbox.regimens", "Doimiy dorilar", "Постоянные препараты", "Regular medicines"),
    ("inbox.no_regimens", "Doimiy dorilar yo‘q", "Постоянных препаратов нет", "No regular medicines"),
    ("inbox.no_health_consent", "Sog‘liq ma’lumotlarini saqlashga rozilik yo‘q", "Нет согласия на хранение данных о здоровье", "No consent to keep health data"),
    ("inbox.last_purchases", "Oxirgi xaridlar", "Последние покупки", "Recent purchases"),
    ("inbox.open_tickets", "Ochiq murojaatlar", "Открытые обращения", "Open tickets"),
    ("inbox.no_open_tickets", "Ochiq murojaat yo‘q", "Открытых обращений нет", "No open tickets"),
    ("inbox.open_customer", "Mijoz kartasi", "Карточка клиента", "Customer card"),
    ("inbox.callback", "Ertaga qo‘ng‘iroq", "Перезвонить завтра", "Call tomorrow"),
    ("inbox.callback_title", "qayta qo‘ng‘iroq", "перезвонить", "call back"),
    ("inbox.callback_saved", "Ertaga 10:00 ga qo‘ng‘iroq vazifasi qo‘shildi", "Задача перезвонить завтра в 10:00 добавлена", "Call-back task added for tomorrow 10:00"),
    ("inbox.lead_info", "Lid haqida", "О лиде", "About the lead"),
    ("inbox.interest", "Qiziqish", "Интерес", "Interest"),
    ("inbox.estimate", "Taxminiy summa", "Оценка суммы", "Estimate"),
    ("inbox.score", "Lid bahosi", "Оценка лида", "Lead score"),
    ("inbox.convert", "Mijozga aylantirish", "Сделать клиентом", "Convert to customer"),
    ("inbox.convert_hint", "Karta, sodiqlik hisobi va yozishma bir joyda bo‘ladi.", "Карточка, бонусный счёт и переписка будут в одном месте.", "Card, loyalty account and the chat end up in one place."),
    ("inbox.converted", "Mijoz kartasi yaratildi", "Карточка клиента создана", "Customer created"),
];
