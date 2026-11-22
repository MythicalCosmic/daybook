//! "Ask your pharmacy": the AI assistant panel. Questions in Uzbek, Russian or English become
//! segments, lists and numbers straight from the CRM's data. In the demo the understanding is
//! done on the device (keywords); connected to Daybook it goes through the company's Claude
//! Haiku budget. Each answer is counted against that budget, so the cost stays visible.

use crm::analytics::{self, RefillDue};
use crm::i18n::{Entry, Lang};
use crm::model::*;
use crm::Db;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

#[derive(Clone, PartialEq)]
enum Answer {
    Segment { rules: Vec<Rule>, ids: Vec<Id> },
    Refills(Vec<RefillDue>),
    Branches(Vec<(String, Money)>),
    Tasks(Vec<(Id, String, String)>),
    Top(Vec<(Id, String, Money, Tier)>),
    Revenue { month: Money, delta: f64, basket: Money, orders: u32 },
    Help,
}

#[derive(Clone, PartialEq)]
struct Turn {
    q: String,
    a: Answer,
}

fn has(q: &str, words: &[&str]) -> bool {
    words.iter().any(|w| q.contains(w))
}

fn first_number(q: &str) -> Option<i64> {
    let mut num = String::new();
    for ch in q.chars() {
        if ch.is_ascii_digit() {
            num.push(ch);
        } else if !num.is_empty() {
            break;
        }
    }
    num.parse().ok()
}

fn rule(field: Field, op: Op, value: impl Into<String>) -> Rule {
    Rule { field, op, value: value.into() }
}

/// Turns a question into an answer using the CRM's own data.
fn understand(question: &str, db: &Db) -> Answer {
    let q = question.to_lowercase().replace(['‘', '’', '\''], "");
    let now = now();
    let today = now.date();

    // a segment: conditions, age, gender, tier, inactivity, consent, branch
    let mut rules = Vec::new();
    let conditions: &[(&[&str], Condition)] = &[
        (&["diabet", "диабет", "сахар", "qand"], Condition::Diabetes),
        (&["gipertoni", "qon bosim", "давлен", "гипертон", "hypertens", "blood pressure"], Condition::Hypertension),
        (&["xolesterin", "холестерин", "cholesterol", "statin"], Condition::Cholesterol),
        (&["astma", "астм", "asthma"], Condition::Asthma),
        (&["qalqonsimon", "щитовид", "thyroid"], Condition::Thyroid),
        (&["homilador", "беремен", "pregnan"], Condition::Pregnancy),
        (&["yurak", "сердц", "heart"], Condition::Heart),
    ];
    for (words, c) in conditions {
        if has(&q, words) {
            rules.push(rule(Field::Condition, Op::Eq, c.slug()));
        }
    }
    let n = first_number(&q);
    if has(&q, &["nafaqa", "пенсион", "pension", "keksa", "пожил", "elderly"]) {
        rules.push(rule(Field::Age, Op::Gt, "59"));
    } else if let Some(age) = n.filter(|_| has(&q, &["yosh", "лет", "year", "age", "возраст", "старше", "младше", "older", "younger", "over ", "under ", "katta", "kichik"])) {
        if has(&q, &["kichik", "младше", "under", "below", "gacha", "до "]) {
            rules.push(rule(Field::Age, Op::Lt, (age + 1).to_string()));
        } else {
            rules.push(rule(Field::Age, Op::Gt, (age - 1).to_string()));
        }
    }
    if has(&q, &["ayol", "женщин", "women", "female", "onalar", "мам"]) {
        rules.push(rule(Field::Gender, Op::Eq, "female"));
    } else if has(&q, &["erkak", "мужчин", " men", "male"]) {
        rules.push(rule(Field::Gender, Op::Eq, "male"));
    }
    if has(&q, &["vip", "oltin", "platina", "золот", "платин", "gold", "platinum"]) {
        let gold = db.settings.loyalty.tiers.iter().find(|t| t.tier == Tier::Gold).map(|t| t.min_spent).unwrap_or(3_000_000);
        rules.push(rule(Field::TotalSpent, Op::Gt, (gold - 1).to_string()));
    }
    if has(&q, &["kelmagan", "kelmay", "не приход", "не покуп", "давно", "inactive", "havent", "lapsed", "yo‘qol", "yoqol", "uzoq"]) {
        let days = n.filter(|d| *d >= 7 && *d <= 400 && !has(&q, &["yosh", "лет", "year"])).unwrap_or(db.settings.inactive_days as i64);
        rules.push(rule(Field::DaysSinceLast, Op::Gt, days.to_string()));
    }
    if has(&q, &["telegram"]) {
        rules.push(rule(Field::ConsentTelegram, Op::IsTrue, ""));
    }
    for b in &db.branches {
        let key: String = b.name.to_lowercase().chars().take(5).collect();
        if key.chars().count() >= 4 && q.contains(&key) {
            rules.push(rule(Field::Branch, Op::Eq, b.id.to_string()));
        }
    }
    let asks_refills = has(&q, &["tugay", "tugash", "заканчива", "закончи", "run out", "refill", "dori radar"]);
    if !rules.is_empty() && !asks_refills {
        let seg = Segment { id: 0, name: String::new(), description: String::new(), rules: rules.clone(), match_all: true, hue: 265, system: false, icon: "sparkles".into() };
        let mut ids = db.segment_members(&seg, today);
        ids.sort_by_key(|id| std::cmp::Reverse(db.customer(*id).map(|c| c.total_spent).unwrap_or(0)));
        return Answer::Segment { rules, ids };
    }
    if asks_refills {
        return Answer::Refills(analytics::refills(db, today, 7));
    }
    if has(&q, &["filial", "филиал", "branch"]) {
        let rows = analytics::revenue_by_branch(db, analytics::month_start(today));
        return Answer::Branches(rows.into_iter().map(|(id, v)| (db.branch_name(Some(id)), v)).collect());
    }
    if has(&q, &["vazifa", "задач", "task", "bugun nima", "мои дела", "my day"]) {
        let me = db.settings.me;
        let mut v: Vec<&Activity> = db.activities.iter().filter(|a| a.owner_id == me && !a.done && a.due.date() <= today).collect();
        v.sort_by_key(|a| a.due);
        return Answer::Tasks(v.into_iter().take(8).map(|a| (a.id, a.title.clone(), crm::fmt::time(a.due))).collect());
    }
    if has(&q, &["eng yaxshi", "eng ko‘p", "eng kop", "лучш", "best", "top", "топ", "sodiq", "лояльн", "loyal"]) {
        let mut v: Vec<&Customer> = db.customers.iter().filter(|c| !c.archived).collect();
        v.sort_by_key(|c| std::cmp::Reverse(c.total_spent));
        return Answer::Top(v.into_iter().take(8).map(|c| (c.id, c.name(), c.total_spent, c.tier)).collect());
    }
    if has(&q, &["tushum", "savdo", "выручк", "продаж", "revenue", "sales", "pul", "dene"]) {
        let k = analytics::kpis(db, now);
        return Answer::Revenue { month: k.revenue_mtd, delta: k.revenue_delta(), basket: k.avg_basket_mtd, orders: k.orders_mtd };
    }
    Answer::Help
}

/// A rule as a short natural phrase: "60+ yosh", "Qandli diabet", "90+ kun kelmagan".
fn rule_text(r: &Rule, db: &Db) -> String {
    let n: i64 = r.value.trim().parse().unwrap_or(0);
    match (r.field, r.op) {
        (Field::Condition, _) => Condition::from_slug(&r.value).map(|c| t(c.key())).unwrap_or_default(),
        (Field::Gender, _) => Gender::from_slug(&r.value).map(|g| t(g.key())).unwrap_or_default(),
        (Field::Branch, _) => db.branch_name(r.value.parse().ok()),
        (Field::Age, Op::Gt) => match lang() {
            Lang::Ru => format!("старше {n} лет"),
            Lang::En => format!("over {n}"),
            _ => uz(format!("{}+ yosh", n + 1)),
        },
        (Field::Age, _) => match lang() {
            Lang::Ru => format!("младше {n} лет"),
            Lang::En => format!("under {n}"),
            _ => uz(format!("{} yoshgacha", n - 1)),
        },
        (Field::DaysSinceLast, _) => match lang() {
            Lang::Ru => format!("не приходил {n}+ дн."),
            Lang::En => format!("no visit for {n}+ days"),
            _ => uz(format!("{n}+ kun kelmagan")),
        },
        (Field::TotalSpent, _) => format!("VIP · {}+", money_short(n + 1)),
        (Field::ConsentTelegram, _) => tr("Telegramga roziligi bor", "есть согласие на Telegram", "Telegram consent"),
        _ => format!("{} {} {}", t(r.field.key()), t(r.op.key()), r.value),
    }
}

#[component]
pub fn AssistantPanel() -> Element {
    let mut turns = use_signal(Vec::<Turn>::new);
    let mut input = use_signal(String::new);
    let ai = DB.read().settings.ai.clone();
    let examples: Vec<String> = vec![
        tr("60 yoshdan katta diabetik ayollar", "Женщины старше 60 с диабетом", "Diabetic women over 60"),
        tr("Bu hafta kimning dorisi tugaydi?", "У кого на неделе заканчиваются лекарства?", "Who runs out of medicine this week?"),
        tr("90 kun kelmagan VIP mijozlar", "VIP-клиенты, не приходившие 90 дней", "VIP customers who haven’t come in 90 days"),
        tr("Qaysi filial ko‘proq sotdi?", "Какой филиал продал больше?", "Which branch sold the most?"),
        tr("Bugungi vazifalarim", "Мои задачи на сегодня", "My tasks for today"),
    ];
    let mut ask = move |q: String| {
        let q = q.trim().to_string();
        if q.is_empty() {
            return;
        }
        let a = understand(&q, &DB.peek());
        turns.write().push(Turn { q, a });
        input.set(String::new());
        mutate(|db| {
            db.settings.ai.requests += 1;
            db.settings.ai.spent_usd += 0.0009;
        });
    };
    use_effect(move || {
        if let Some(q) = crate::storage::url_param("ask") {
            if turns.peek().is_empty() {
                ask(q);
            }
        }
    });
    let list = turns();
    rsx! {
        Drawer { title: t("assistant.title"), icon: "sparkles", onclose: move |_| UI.write().ai_panel = false,
            div { class: "drawer-body",
                div { class: "ai-panel row gap-12",
                    span { class: "ic accent", Icon { name: "sparkles", size: 17 } }
                    div { class: "grow",
                        div { class: "strong", {t("assistant.hello")} }
                        div { class: "small muted", {t("assistant.hint")} }
                    }
                }
                if list.is_empty() {
                    div { class: "stack gap-8",
                        span { class: "upper subtle", {t("assistant.try")} }
                        for ex in examples {
                            button { key: "{ex}", class: "chip", style: "justify-content: flex-start; height: auto; padding: 8px 12px; white-space: normal; text-align: left", onclick: move |_| ask(ex.clone()),
                                Icon { name: "sparkles", size: 13 } "{ex}"
                            }
                        }
                    }
                }
                for (i, turn) in list.into_iter().enumerate() {
                    div { key: "{i}", class: "stack gap-8",
                        div { class: "bubble out", style: "align-self: flex-end", "{turn.q}" }
                        AnswerCard { answer: turn.a.clone(), question: turn.q.clone() }
                    }
                }
            }
            div { class: "drawer-foot", style: "flex-direction: column; align-items: stretch; gap: 8px",
                div { class: "row gap-8",
                    input {
                        class: "input",
                        value: "{input}",
                        placeholder: t("assistant.placeholder"),
                        oninput: move |e| input.set(e.value()),
                        onkeydown: move |e: KeyboardEvent| {
                            if e.key() == Key::Enter {
                                ask(input());
                            }
                        },
                        onmounted: move |e| async move {
                            let _ = e.set_focus(true).await;
                        },
                    }
                    button { class: "btn primary", onclick: move |_| ask(input()), Icon { name: "send-horizontal", size: 16 } }
                }
                div { class: "row between xs muted",
                    span { class: "ai-chip", Icon { name: "sparkles", size: 11 } "Claude Haiku 5.5" }
                    span { class: "num", {format!("${:.2} / ${:.0} · {}", ai.spent_usd, ai.monthly_cap_usd, t("assistant.local"))} }
                }
            }
        }
    }
}

#[component]
fn AnswerCard(answer: Answer, question: String) -> Element {
    let l = lang();
    let today = today();
    match answer {
        Answer::Segment { rules, ids } => {
            let (chips, people, reach): (Vec<String>, Vec<(Id, String, Money)>, usize) = {
                let db = DB.read();
                let chips = rules.iter().map(|r| rule_text(r, &db)).collect();
                let people = ids.iter().take(5).filter_map(|id| db.customer(*id)).map(|c| (c.id, c.name(), c.total_spent)).collect();
                let reach = ids.iter().filter(|id| db.customer(**id).map(|c| c.consent.telegram).unwrap_or(false)).count();
                (chips, people, reach)
            };
            let count = ids.len();
            let save_rules = rules.clone();
            let name = question.chars().take(48).collect::<String>();
            rsx! {
                div { class: "card pad stack gap-12",
                    div { class: "row between",
                        div { class: "strong", {format!("{} · {}", t("assistant.found"), crm::fmt::plural(count as i64, l, "mijoz|клиент|клиента|клиентов|customer|customers"))} }
                        span { class: "badge info", Icon { name: "send", size: 12 } {format!("{reach} Telegram")} }
                    }
                    div { class: "row wrap gap-4",
                        for c in chips { span { key: "{c}", class: "tag", "{c}" } }
                    }
                    div { class: "list", style: "margin: 0 -18px",
                        for (id, n, spent) in people {
                            div { key: "{id}", class: "list-row click", onclick: move |_| { UI.write().ai_panel = false; go(&format!("/contacts/{id}")); },
                                Avatar { name: n.clone(), size: "sm" }
                                span { class: "grow small strong truncate", "{n}" }
                                span { class: "small muted num", "{money_short(spent)}" }
                            }
                        }
                    }
                    div { class: "row wrap gap-8",
                        button {
                            class: "btn soft sm",
                            onclick: move |_| {
                                let rules = save_rules.clone();
                                let name = name.clone();
                                let mut sid = 0;
                                mutate(|db| {
                                    sid = db.new_id();
                                    db.segments.push(Segment { id: sid, name: name.clone(), description: "AI".into(), rules, match_all: true, hue: 265, system: false, icon: "sparkles".into() });
                                });
                                toast(t("assistant.saved"), "layers", "success");
                                UI.write().ai_panel = false;
                                go(&format!("/campaigns?segment={sid}"));
                            },
                            Icon { name: "megaphone", size: 14 }
                            {t("assistant.campaign")}
                        }
                        button { class: "btn ghost sm", onclick: move |_| { UI.write().ai_panel = false; go("/segments"); }, Icon { name: "layers", size: 14 } {t("nav.segments")} }
                    }
                }
            }
        }
        Answer::Refills(list) => {
            let rows: Vec<(Id, String, String, String, &'static str)> = {
                let db = DB.read();
                list.iter()
                    .take(6)
                    .map(|r| {
                        let tone: &'static str = if r.days_left <= 0 { "danger" } else if r.days_left <= 2 { "warning" } else { "accent" };
                        (r.customer_id, db.customer_name(Some(r.customer_id)), db.product_name(Some(r.product_id)), crm::fmt::due_in(r.due, today, l), tone)
                    })
                    .collect()
            };
            let total = list.len();
            rsx! {
                div { class: "card pad stack gap-8",
                    div { class: "strong", {format!("{} · {}", t("nav.refills"), crm::fmt::plural(total as i64, l, "mijoz|клиент|клиента|клиентов|customer|customers"))} }
                    for (id, n, p, due, tone) in rows {
                        div { key: "{id}-{p}", class: "row gap-8 small",
                            Avatar { name: n.clone(), size: "xs" }
                            span { class: "grow truncate", strong { "{n}" } " · {p}" }
                            Badge { text: due, tone }
                        }
                    }
                    button { class: "btn soft sm", style: "align-self: flex-start", onclick: move |_| { UI.write().ai_panel = false; go("/refills"); }, {t("common.view_all")} Icon { name: "arrow-right", size: 14 } }
                }
            }
        }
        Answer::Branches(rows) => {
            let items: Vec<(String, f64, String)> = rows.iter().map(|(n, v)| (n.clone(), *v as f64, money_short(*v))).collect();
            rsx! {
                div { class: "card pad stack gap-12",
                    div { class: "strong", {t("home.branches_month")} }
                    HBars { items }
                }
            }
        }
        Answer::Tasks(rows) => rsx! {
            div { class: "card pad stack gap-8",
                div { class: "strong", {t("home.today")} }
                if rows.is_empty() { span { class: "small muted", {t("home.free_day")} } }
                for (id, title, time) in rows {
                    div { key: "{id}", class: "row gap-8 small",
                        span { class: "num muted", style: "width: 44px", "{time}" }
                        span { class: "grow truncate", "{title}" }
                    }
                }
            }
        },
        Answer::Top(rows) => rsx! {
            div { class: "card pad stack gap-8",
                div { class: "strong", {t("assistant.top")} }
                for (id, n, spent, tier) in rows {
                    div { key: "{id}", class: "row gap-8 small click", style: "cursor: pointer", onclick: move |_| { UI.write().ai_panel = false; go(&format!("/contacts/{id}")); },
                        Avatar { name: n.clone(), size: "xs" }
                        span { class: "grow truncate strong", "{n}" }
                        TierBadge { tier }
                        span { class: "num", "{money_short(spent)}" }
                    }
                }
            }
        },
        Answer::Revenue { month, delta, basket, orders } => rsx! {
            div { class: "card pad stack gap-8",
                div { class: "row between", span { class: "strong", {t("home.revenue_mtd")} } Delta { value: delta } }
                div { class: "kpi-value", "{money_short(month)}" }
                div { class: "small muted", {format!("{}: {} · {}: {}", t("home.avg_basket"), money_short(basket), t("home.orders"), orders)} }
            }
        },
        Answer::Help => rsx! {
            div { class: "card pad small muted", {t("assistant.help")} }
        },
    }
}

pub const STRINGS: &[Entry] = &[
    ("assistant.title", "AI yordamchi", "AI-помощник", "AI assistant"),
    ("assistant.hello", "Dorixonangiz haqida so‘rang", "Спросите о своей аптеке", "Ask about your pharmacy"),
    ("assistant.hint", "Oddiy so‘zlar bilan yozing: segment, ro‘yxat yoki raqam tayyorlab beraman.", "Пишите обычными словами: соберу сегмент, список или цифры.", "Ask in plain words; I’ll build a segment, a list or the numbers."),
    ("assistant.try", "Masalan", "Например", "Try"),
    ("assistant.placeholder", "Savolingizni yozing…", "Напишите вопрос…", "Type a question…"),
    ("assistant.local", "demo: qurilmada", "демо: на устройстве", "demo: on device"),
    ("assistant.found", "Topildi", "Найдено", "Found"),
    ("assistant.campaign", "Segment qilib, kampaniya yuborish", "Сохранить сегмент и сделать рассылку", "Save as a segment and send a campaign"),
    ("assistant.saved", "Segment saqlandi", "Сегмент сохранён", "Segment saved"),
    ("assistant.top", "Eng sodiq mijozlar", "Самые лояльные клиенты", "Most loyal customers"),
    ("assistant.help", "Masalan: «60 yoshdan katta diabetik ayollar», «bu hafta kimning dorisi tugaydi», «qaysi filial ko‘proq sotdi», «eng yaxshi mijozlar».", "Например: «женщины старше 60 с диабетом», «у кого на неделе заканчиваются лекарства», «какой филиал продал больше», «лучшие клиенты».", "For example: “diabetic women over 60”, “who runs out of medicine this week”, “which branch sold the most”, “best customers”."),
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn understands_pharmacy_questions() {
        let db = crm::demo::generate(chrono::NaiveDate::from_ymd_opt(2026, 11, 23).unwrap().and_hms_opt(10, 0, 0).unwrap());
        match understand("60 yoshdan katta diabetik ayollar", &db) {
            Answer::Segment { rules, ids } => {
                assert_eq!(rules.len(), 3, "{rules:?}");
                assert!(!ids.is_empty());
            }
            _ => panic!("expected a segment"),
        }
        assert!(matches!(understand("У кого на неделе заканчиваются лекарства?", &db), Answer::Refills(_)));
        assert!(matches!(understand("Which branch sold the most?", &db), Answer::Branches(_)));
        let _ = Lang::Uz;
    }
}
