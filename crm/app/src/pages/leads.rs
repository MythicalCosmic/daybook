//! Leads: an amoCRM-style "unsorted" inbox for incoming requests from Telegram, Instagram, the
//! website and phone calls. Status tabs, the one-hour response SLA, a score with its reasons,
//! owner assignment and one-click conversion into a customer or a B2B deal.

use chrono::{Duration, NaiveDateTime};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

const STATUSES: &[LeadStatus] = &[LeadStatus::New, LeadStatus::Contacted, LeadStatus::Qualified, LeadStatus::Converted, LeadStatus::Junk];

fn channel_tone(c: Channel) -> &'static str {
    match c {
        Channel::Telegram => "info",
        Channel::Instagram => "accent",
        Channel::Web => "success",
        Channel::Phone => "warning",
        Channel::Email => "muted",
        Channel::Sms | Channel::WhatsApp => "success",
    }
}

fn score_bar_tone(s: u8) -> &'static str {
    match s {
        0..=39 => "danger",
        40..=69 => "warning",
        _ => "success",
    }
}

/// "45 daq" / "1 soat 20 daq" / "3 kun" for a wait.
fn wait_text(mins: i64, l: Lang) -> String {
    let (m, h, d) = match l {
        Lang::Ru => ("мин", "ч", "дн."),
        Lang::En => ("min", "h", "d"),
        _ => ("daq", "soat", "kun"),
    };
    let s = if mins < 60 {
        format!("{} {m}", mins.max(1))
    } else if mins < 24 * 60 {
        let rest = mins % 60;
        if rest == 0 {
            format!("{} {h}", mins / 60)
        } else {
            format!("{} {h} {rest} {m}", mins / 60)
        }
    } else {
        format!("{} {d}", mins / (24 * 60))
    };
    if l == Lang::UzCyrl {
        crm::i18n::to_cyrillic(&s)
    } else {
        s
    }
}

/// Simulated first-response time for a lead that has been handled: hot leads get answered faster.
fn response_minutes(l: &Lead) -> i64 {
    3 + (100 - l.score.min(100) as i64) * 35 / 100 + (l.id as i64 % 5)
}

const INTENT_WORDS: &[&str] = &[
    "kerak", "har oy", "oylik", "doimiy", "ta’minot", "hamkorlik", "korporativ", "taklif", "kishi", "yetkazib", "bron",
    "нужн", "ежемесяч", "доставк", "сотрудничеств", "корпоратив", "человек", "need", "monthly", "supply",
];
const QUESTION_WORDS: &[&str] = &["narx", "qancha", "bormi", "bor mi", "цена", "есть ли", "сколько", "price"];
const JUNK_WORDS: &[&str] = &["seo", "spam", "uzildi", "reklama"];

/// The parts of the score: (label, detail, raw points). Scaled to the lead's score by the caller.
fn score_parts(lead: &Lead, l: Lang) -> Vec<(String, String, f64)> {
    let msg = lead.message.to_lowercase();
    let ch = match lead.channel {
        Channel::Web => 18.0,
        Channel::Email | Channel::Phone => 16.0,
        Channel::Telegram => 14.0,
        Channel::WhatsApp => 12.0,
        Channel::Instagram | Channel::Sms => 8.0,
    };
    let hits: Vec<&str> = INTENT_WORDS.iter().copied().filter(|w| msg.contains(w)).collect();
    let questions = QUESTION_WORDS.iter().filter(|w| msg.contains(**w)).count();
    let junk = JUNK_WORDS.iter().any(|w| msg.contains(w));
    let intent = if junk { 0.5 } else { (hits.len() as f64 * 7.0 + questions as f64 * 4.0).min(32.0).max(3.0) };
    let est = match lead.estimate {
        e if e >= 20_000_000 => 30.0,
        e if e >= 5_000_000 => 24.0,
        e if e >= 1_000_000 => 18.0,
        e if e >= 200_000 => 10.0,
        e if e > 0 => 6.0,
        _ => 1.0,
    };
    let channel_name = crate::state::t(lead.channel.key());
    let intent_detail = if junk {
        pick3(l, "Reklama yoki uzilgan qo‘ng‘iroq", "Реклама или сорвавшийся звонок", "Spam or a dropped call")
    } else if hits.is_empty() {
        pick3(l, "Narx yoki mavjudlik haqida savol", "Вопрос о цене или наличии", "A question about price or stock")
    } else {
        hits.join(", ")
    };
    let mut v = vec![
        (pick3(l, "Kanal", "Канал", "Channel"), channel_name, ch),
        (pick3(l, "Xabar mazmuni", "Смысл сообщения", "Message intent"), intent_detail, intent),
        (pick3(l, "Taxminiy summa", "Ожидаемая сумма", "Estimate"), if lead.estimate > 0 { money(lead.estimate) } else { "—".into() }, est),
    ];
    if let Some(c) = &lead.company_name {
        v.push((pick3(l, "Tashkilot", "Организация", "Company"), c.clone(), 12.0));
    }
    v
}

fn pick3(l: Lang, uz: &'static str, ru: &'static str, en: &'static str) -> String {
    crm::i18n::pick(l, uz, ru, en).into_owned()
}

fn source_of(c: Channel) -> Source {
    match c {
        Channel::Telegram => Source::Telegram,
        Channel::Instagram => Source::Instagram,
        Channel::Web | Channel::Email => Source::Website,
        Channel::Phone | Channel::Sms | Channel::WhatsApp => Source::Call,
    }
}

fn org_kind_guess(name: &str) -> OrgKind {
    let n = name.to_lowercase();
    if ["klinik", "markaz", "med", "poliklinika", "shifoxona", "клиник"].iter().any(|w| n.contains(w)) {
        OrgKind::Clinic
    } else if ["maktab", "школ"].iter().any(|w| n.contains(w)) {
        OrgKind::School
    } else if ["jamiyat", "общество"].iter().any(|w| n.contains(w)) {
        OrgKind::Government
    } else {
        OrgKind::Corporate
    }
}

fn set_status(id: Id, status: LeadStatus) {
    let msg = match status {
        LeadStatus::Contacted => t("leads.done_contacted"),
        LeadStatus::Qualified => t("leads.done_qualified"),
        LeadStatus::Junk => t("leads.done_junk"),
        _ => t("leads.done_new"),
    };
    let icon = match status {
        LeadStatus::Junk => "trash-2",
        LeadStatus::Qualified => "badge-check",
        _ => "phone-outgoing",
    };
    mutate(|db| {
        let me = db.settings.me;
        if let Some(l) = db.lead_mut(id) {
            l.status = status;
            if l.owner_id.is_none() && status != LeadStatus::Junk {
                l.owner_id = Some(me);
            }
        }
    });
    toast(msg, icon, "success");
}

/// Converts a lead: a B2B deal (with its company) when the lead names a company, otherwise a customer.
fn convert(id: Id) {
    let Some(lead) = DB.peek().lead(id).cloned() else { return };
    let now = now();
    let today = now.date();
    if let Some(company) = lead.company_name.clone() {
        let next_step = t("leads.next_step");
        let mut deal_id = 0;
        mutate(|db| {
            let me = db.settings.me;
            let owner = lead.owner_id.unwrap_or(me);
            let existing = db.companies.iter().find(|c| c.name.eq_ignore_ascii_case(&company)).map(|c| c.id);
            let co_id = match existing {
                Some(c) => c,
                None => {
                    let cid = db.new_id();
                    let contact_name = if lead.name.eq_ignore_ascii_case(&company) { String::new() } else { lead.name.clone() };
                    db.companies.push(Company {
                        id: cid,
                        name: company.clone(),
                        kind: org_kind_guess(&company),
                        tin: String::new(),
                        district: String::new(),
                        address: String::new(),
                        phone: lead.phone.clone(),
                        email: String::new(),
                        owner_id: Some(owner),
                        credit_limit: 0,
                        terms_days: 30,
                        receivable: 0,
                        tags: vec![],
                        created: today,
                        employees: 0,
                        contacts: if contact_name.is_empty() {
                            vec![]
                        } else {
                            vec![ContactPerson { name: contact_name, position: String::new(), phone: lead.phone.clone(), telegram: None, primary: true }]
                        },
                        notes: lead.message.clone(),
                        health: 70,
                        daybook_id: None,
                    });
                    cid
                }
            };
            let (pipeline, stage) = db.pipelines.first().map(|p| (p.id, p.stages.first().map(|s| s.id).unwrap_or(0))).unwrap_or((0, 0));
            let did = db.new_id();
            deal_id = did;
            db.deals.push(Deal {
                id: did,
                title: format!("{company} · {}", lead.interest),
                pipeline_id: pipeline,
                stage_id: stage,
                company_id: Some(co_id),
                customer_id: None,
                value: lead.estimate,
                owner_id: owner,
                created: now,
                stage_since: now,
                last_activity: now,
                expected_close: today + Duration::days(30),
                status: DealStatus::Open,
                lost_reason: None,
                lines: vec![],
                source: source_of(lead.channel),
                tags: vec![],
                next_step,
                closed_at: None,
                priority: if lead.score >= 80 { Priority::High } else { Priority::Normal },
            });
            if let Some(l) = db.lead_mut(id) {
                l.status = LeadStatus::Converted;
                l.converted_deal = Some(did);
                l.owner_id = Some(owner);
            }
            db.log(now, format!("{} → {}", lead.name, company), false);
        });
        toast(t("leads.converted_deal"), "square-kanban", "success");
        go(&format!("/deals/{deal_id}"));
    } else {
        let welcome_note = t("leads.welcome_note");
        let digits: String = lead.phone.chars().filter(|c| c.is_ascii_digit()).collect();
        let mut cust_id = 0;
        mutate(|db| {
            let me = db.settings.me;
            let owner = lead.owner_id.unwrap_or(me);
            let existing = if digits.len() >= 9 { db.customers.iter().find(|c| c.phone == digits).map(|c| c.id) } else { None };
            let cid = match existing {
                Some(c) => c,
                None => {
                    let cid = db.new_id();
                    let mut parts = lead.name.split_whitespace();
                    let first = parts.next().unwrap_or("").to_string();
                    let last: Vec<&str> = parts.filter(|w| !w.eq_ignore_ascii_case("aka") && !w.eq_ignore_ascii_case("opa")).collect();
                    let lower = first.to_lowercase();
                    let female = lower.ends_with('a') || lower.ends_with('o') || lead.name.to_lowercase().contains(" opa");
                    let cyrillic = lead.message.chars().any(|c| ('а'..='я').contains(&c.to_lowercase().next().unwrap_or(c)));
                    let home = db.branches.first().map(|b| b.id).unwrap_or(0);
                    let bonus = db.settings.loyalty.welcome_bonus;
                    db.customers.insert(
                        0,
                        Customer {
                            id: cid,
                            first_name: first,
                            last_name: last.join(" "),
                            gender: if female { Gender::Female } else { Gender::Male },
                            phone: digits.clone(),
                            telegram: None,
                            birth_date: None,
                            district: String::new(),
                            home_branch: home,
                            owner_id: Some(owner),
                            tags: vec![],
                            tier: Tier::Bronze,
                            points: 0,
                            card_no: format!("7801 {:04} {:04}", cid % 10_000, (cid * 7) % 10_000),
                            source: source_of(lead.channel),
                            consent: Consent { sms: false, telegram: lead.channel == Channel::Telegram, health_data: false, given_on: Some(today) },
                            regimens: vec![],
                            allergies: vec![],
                            company_id: None,
                            created: today,
                            lang: if cyrillic { Lang::Ru } else { Lang::Uz },
                            notes: lead.message.clone(),
                            nps: None,
                            total_spent: 0,
                            orders: 0,
                            first_purchase: None,
                            last_purchase: None,
                            archived: false,
                            referred_by: None,
                        },
                    );
                    if bonus > 0 {
                        db.give_points(cid, bonus, TxKind::Bonus, welcome_note, now);
                    }
                    cid
                }
            };
            cust_id = cid;
            if let Some(l) = db.lead_mut(id) {
                l.status = LeadStatus::Converted;
                l.converted_customer = Some(cid);
                l.owner_id = Some(owner);
            }
            db.log(now, format!("{} → CRM", lead.name), false);
        });
        toast(t("leads.converted_customer"), "user-check", "success");
        go(&format!("/contacts/{cust_id}"));
    }
}

fn assign(id: Id, owner: Id) {
    let name = DB.peek().staff_name(Some(owner));
    mutate(|db| {
        if let Some(l) = db.lead_mut(id) {
            l.owner_id = if owner == 0 { None } else { Some(owner) };
        }
    });
    if owner != 0 {
        toast(format!("{}: {name}", t("leads.assigned")), "user-check", "success");
    }
}

fn assignable() -> Vec<(Id, String, u16)> {
    DB.read()
        .staff
        .iter()
        .filter(|s| s.active && matches!(s.role, Role::CallAgent | Role::SalesRep | Role::Manager | Role::Pharmacist | Role::Owner))
        .map(|s| (s.id, s.name.clone(), s.hue))
        .collect()
}

#[component]
pub fn Leads() -> Element {
    let mut status = use_signal(|| LeadStatus::New);
    let mut query = use_signal(String::new);
    let mut sort = use_signal(|| "new".to_string());
    let mut open = use_signal(|| None::<Id>);
    let now = now();
    let today = now.date();
    let l = lang();

    let (all, staff_count) = {
        let db = DB.read();
        (db.leads.clone(), db.staff.len())
    };
    let _ = staff_count;
    let count_of = |s: LeadStatus| all.iter().filter(|x| x.status == s).count();
    let new_today = all.iter().filter(|x| x.at.date() == today).count();
    let waiting_new = all.iter().filter(|x| x.status == LeadStatus::New).count();
    let breached = all.iter().filter(|x| x.status == LeadStatus::New && (now - x.at).num_minutes() > 60).count();
    let handled: Vec<&Lead> = all.iter().filter(|x| matches!(x.status, LeadStatus::Contacted | LeadStatus::Qualified | LeadStatus::Converted)).collect();
    let avg_resp = if handled.is_empty() { 0 } else { handled.iter().map(|x| response_minutes(x)).sum::<i64>() / handled.len() as i64 };
    let in_sla = handled.iter().filter(|x| response_minutes(x) <= 60).count();
    let processed = all.iter().filter(|x| x.status != LeadStatus::New).count();
    let converted = count_of(LeadStatus::Converted);
    let conv_rate = if processed == 0 { 0.0 } else { converted as f64 / processed as f64 * 100.0 };
    let potential: Money = all.iter().filter(|x| matches!(x.status, LeadStatus::New | LeadStatus::Contacted | LeadStatus::Qualified)).map(|x| x.estimate).sum();
    let open_n = all.iter().filter(|x| matches!(x.status, LeadStatus::New | LeadStatus::Contacted | LeadStatus::Qualified)).count();

    let tabs: Vec<(LeadStatus, String, usize)> = STATUSES.iter().map(|s| (*s, t(s.key()), count_of(*s))).collect();
    let cur = status();
    let q = query().trim().to_lowercase();
    let mut list: Vec<Lead> = all
        .iter()
        .filter(|x| x.status == cur)
        .filter(|x| {
            q.is_empty()
                || x.name.to_lowercase().contains(&q)
                || x.message.to_lowercase().contains(&q)
                || x.interest.to_lowercase().contains(&q)
                || x.company_name.as_deref().map(|c| c.to_lowercase().contains(&q)).unwrap_or(false)
                || (q.len() >= 3 && x.phone.contains(&q))
        })
        .cloned()
        .collect();
    if sort() == "score" {
        list.sort_by(|a, b| b.score.cmp(&a.score));
    } else {
        list.sort_by(|a, b| b.at.cmp(&a.at));
    }
    let staff = assignable();
    let resp_s = wait_text(avg_resp.max(1), l);
    let sla_foot = format!("{} · {}/{}", t("leads.sla_hint"), in_sla, handled.len());
    let breached_text = t("leads.breached").replace("{n}", &breached.to_string());

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.leads"), subtitle: t("leads.subtitle"),
                button { class: "btn primary", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Lead),
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("palette.new_lead")} }
                }
            }

            div { class: "grid-4",
                Kpi { label: t("leads.new_today"), value: fmt::num(new_today as i64), icon: "magnet", tone: "accent",
                    foot: format!("{} · {}", t("leads.waiting_now"), waiting_new),
                    onclick: move |_| status.set(LeadStatus::New),
                }
                Kpi { label: t("leads.first_response"), value: resp_s, icon: "timer", tone: "info", foot: sla_foot }
                Kpi { label: t("leads.conversion"), value: fmt::pct(conv_rate, l), icon: "trending-up", tone: "success",
                    foot: format!("{} / {} {}", converted, processed, t("leads.processed")),
                }
                Kpi { label: t("leads.potential"), value: money_short(potential), icon: "wallet", tone: "warning",
                    foot: fmt::plural(open_n as i64, l, "ochiq lid|открытый лид|открытых лида|открытых лидов|open lead|open leads"),
                }
            }

            if breached > 0 && cur == LeadStatus::New {
                div { class: "callout danger",
                    Icon { name: "flame", size: 16 }
                    span { class: "grow", "{breached_text}" }
                }
            }

            div { class: "card",
                div { class: "tabs", style: "padding: 0 12px",
                    for (s, label, n) in tabs {
                        button { key: "{s.slug()}", class: if cur == s { "tab on" } else { "tab" }, onclick: move |_| status.set(s),
                            "{label}"
                            span { class: "count num", "{n}" }
                        }
                    }
                }
                div { class: "card-body stack gap-12",
                    div { class: "toolbar",
                        div { class: "search",
                            Icon { name: "search", size: 16 }
                            input { class: "input", r#type: "search", placeholder: t("leads.search"), value: "{query}", oninput: move |e| query.set(e.value()) }
                        }
                        span { class: "spacer" }
                        Segmented {
                            options: vec![("new".into(), t("leads.sort_new")), ("score".into(), t("leads.sort_score"))],
                            value: sort(),
                            onchange: move |v| sort.set(v),
                        }
                    }
                    if list.is_empty() {
                        Empty { icon: "inbox", title: t("leads.empty"), text: t("leads.empty_text") }
                    }
                    div { class: "grid-2",
                        for lead in list {
                            LeadCard { key: "{lead.id}", lead: lead.clone(), staff: staff.clone(), onopen: move |id| open.set(Some(id)) }
                        }
                    }
                }
            }

            if let Some(id) = open() {
                LeadDrawer { id, staff: staff.clone(), onclose: move |_| open.set(None) }
            }
        }
    }
}

#[component]
fn LeadCard(lead: Lead, staff: Vec<(Id, String, u16)>, onopen: EventHandler<Id>) -> Element {
    let now = now();
    let l = lang();
    let id = lead.id;
    let mins = (now - lead.at).num_minutes();
    let is_new = lead.status == LeadStatus::New;
    let late = is_new && mins > 60;
    let wait = wait_text(mins, l);
    let when = fmt::relative(lead.at, now, l);
    let ctone = channel_tone(lead.channel);
    let stone = score_bar_tone(lead.score);
    let est = if lead.estimate > 0 { money_short(lead.estimate) } else { "—".to_string() };
    let owner = lead.owner_id.and_then(|o| staff.iter().find(|s| s.0 == o).cloned());
    let open_status = matches!(lead.status, LeadStatus::New | LeadStatus::Contacted | LeadStatus::Qualified);
    let card_style = if late { "border-color: color-mix(in srgb, var(--c-danger) 40%, var(--c-border))" } else { "" };
    let wait_tone: &'static str = if late { "danger" } else { "warning" };
    let wait_icon: &'static str = if late { "flame" } else { "clock" };
    let sub = match &lead.company_name {
        Some(c) if !c.eq_ignore_ascii_case(&lead.name) => format!("{c} · {}", t(lead.channel.key())),
        _ => t(lead.channel.key()),
    };
    rsx! {
        div { class: "card hover pad stack gap-12", style: card_style, onclick: move |_| onopen.call(id),
            div { class: "row top gap-12",
                IconTile { icon: crm::db::channel_icon(lead.channel), tone: ctone }
                div { class: "grow stack", style: "gap: 2px; min-width: 0",
                    span { class: "strong truncate", "{lead.name}" }
                    span { class: "xs muted truncate", "{sub}" }
                }
                if is_new {
                    Badge { text: wait, tone: wait_tone, icon: wait_icon }
                } else {
                    span { class: "xs subtle nowrap", "{when}" }
                }
            }
            div { class: "small clamp-2", style: "background: var(--c-surface-2); border-radius: 12px 12px 12px 4px; padding: 9px 11px; line-height: 1.45; min-height: 42px",
                "{lead.message}"
            }
            div { class: "row between gap-12",
                div { class: "row gap-8", style: "min-width: 0",
                    if lead.interest != "—" { span { class: "tag truncate", "{lead.interest}" } }
                    span { class: "num strong small nowrap", "{est}" }
                }
                div { class: "row gap-8", style: "flex: 0 0 120px",
                    div { class: "grow", Progress { pct: lead.score as f64, tone: stone, thin: true } }
                    span { class: "num strong small", "{lead.score}" }
                }
            }
            div { class: "row wrap", style: "gap: 8px", onclick: move |e| e.stop_propagation(),
                if let Some((_, oname, ohue)) = owner {
                    div { class: "row gap-8 small muted", style: "min-width: 0; flex: 1 1 120px",
                        Avatar { name: oname.clone(), hue: ohue, size: "xs" }
                        span { class: "truncate", "{oname}" }
                    }
                } else {
                    select {
                        class: "select sm",
                        style: "flex: 1 1 120px; max-width: 180px; min-width: 0",
                        onchange: move |e| assign(id, e.value().parse().unwrap_or(0)),
                        option { value: "0", selected: true, {t("common.assign")} "…" }
                        for (sid, sname, _) in staff.iter().cloned() {
                            option { key: "{sid}", value: "{sid}", "{sname}" }
                        }
                    }
                }
                if open_status {
                    div { class: "row gap-4", style: "margin-left: auto",
                        button { class: "icon-btn sm", title: t("leads.junk"), onclick: move |_| set_status(id, LeadStatus::Junk), Icon { name: "trash-2", size: 15 } }
                        if lead.status == LeadStatus::New {
                            button { class: "btn sm", onclick: move |_| set_status(id, LeadStatus::Contacted), Icon { name: "phone-outgoing", size: 14 } {t("leads.contacted")} }
                        } else if lead.status == LeadStatus::Contacted {
                            button { class: "btn sm", onclick: move |_| set_status(id, LeadStatus::Qualified), Icon { name: "badge-check", size: 14 } {t("leads.qualify")} }
                        }
                        button { class: "btn sm primary", onclick: move |_| convert(id), Icon { name: "arrow-right", size: 14 } {t("leads.convert")} }
                    }
                } else if lead.status == LeadStatus::Junk {
                    button { class: "btn sm ghost", onclick: move |_| set_status(id, LeadStatus::New), Icon { name: "undo-2", size: 14 } {t("leads.restore")} }
                } else {
                    ConvertedLink { lead: lead.clone() }
                }
            }
        }
    }
}

#[component]
fn ConvertedLink(lead: Lead) -> Element {
    if let Some(d) = lead.converted_deal {
        rsx! {
            button { class: "btn sm soft", onclick: move |_| go(&format!("/deals/{d}")), Icon { name: "square-kanban", size: 14 } {t("leads.open_deal")} }
        }
    } else if let Some(c) = lead.converted_customer {
        rsx! {
            button { class: "btn sm soft", onclick: move |_| go(&format!("/contacts/{c}")), Icon { name: "user", size: 14 } {t("leads.open_customer")} }
        }
    } else {
        rsx! {
            Badge { text: t("lead_status.converted"), tone: "success", icon: "check" }
        }
    }
}

#[component]
fn LeadDrawer(id: Id, staff: Vec<(Id, String, u16)>, onclose: EventHandler<()>) -> Element {
    let now = now();
    let l = lang();
    let Some(lead) = DB.read().lead(id).cloned() else { return rsx! {} };
    let mins = (now - lead.at).num_minutes();
    let late = lead.status == LeadStatus::New && mins > 60;
    let at: NaiveDateTime = lead.at;
    let received = fmt::datetime(at, now, l);
    let wait = wait_text(mins, l);
    let ph = phone(&lead.phone);
    let tel = fmt::tel_href(&lead.phone);
    let parts = score_parts(&lead, l);
    let raw: f64 = parts.iter().map(|p| p.2).sum::<f64>().max(1.0);
    let factor = lead.score as f64 / raw;
    let scaled: Vec<(String, String, i64)> = parts.into_iter().map(|(a, b, v)| (a, b, (v * factor).round() as i64)).collect();
    let max_part = scaled.iter().map(|p| p.2).max().unwrap_or(1).max(1) as f64;
    let stone = score_bar_tone(lead.score);
    let open_status = matches!(lead.status, LeadStatus::New | LeadStatus::Contacted | LeadStatus::Qualified);
    let owner_v = lead.owner_id.unwrap_or(0);
    let mut kv: Vec<(String, String)> = vec![
        (t("common.phone"), ph.clone()),
        (t("quick.channel"), t(lead.channel.key())),
        (t("leads.received"), received),
        (t("quick.interest"), lead.interest.clone()),
        (t("leads.estimate"), if lead.estimate > 0 { money(lead.estimate) } else { "—".into() }),
    ];
    if let Some(c) = &lead.company_name {
        kv.push((t("common.company"), c.clone()));
    }
    let wait_tone: &'static str = if late { "danger" } else { "warning" };
    let target = if lead.company_name.is_some() { t("leads.convert_deal_hint") } else { t("leads.convert_customer_hint") };
    let status_label = t(lead.status.key());
    rsx! {
        Drawer { title: lead.name.clone(), icon: crm::db::channel_icon(lead.channel), onclose: move |_| onclose.call(()),
            div { class: "drawer-body",
                div { class: "row wrap gap-8",
                    Badge { text: status_label, tone: "accent" }
                    if lead.status == LeadStatus::New {
                        Badge { text: wait, tone: wait_tone, icon: "clock" }
                    }
                    a { href: "{tel}", class: "btn sm", Icon { name: "phone", size: 14 } {t("common.call")} }
                }
                div { class: "bubble in", style: "max-width: 100%; align-self: stretch", "{lead.message}" }
                KeyValues { items: kv }
                div { class: "card flat pad stack gap-12", style: "background: var(--c-surface-2)",
                    div { class: "row between",
                        span { class: "strong", {t("leads.why_score")} }
                        span { class: "row gap-8",
                            span { class: "num strong", style: "font-size: 20px", "{lead.score}" }
                            span { class: "xs muted", "/ 100" }
                        }
                    }
                    Progress { pct: lead.score as f64, tone: stone }
                    for (k, (label, detail, pts)) in scaled.into_iter().enumerate() {
                        div { key: "{k}", class: "stack", style: "gap: 4px",
                            div { class: "row between small",
                                span { class: "strong", "{label}" }
                                span { class: "num muted", "+{pts}" }
                            }
                            div { class: "row gap-8",
                                div { class: "grow", Progress { pct: pts as f64 / max_part * 100.0, thin: true } }
                            }
                            span { class: "xs muted truncate", "{detail}" }
                        }
                    }
                    span { class: "xs subtle", {t("leads.score_note")} }
                }
                div { class: "field",
                    label { class: "label", {t("common.owner")} }
                    select { class: "select", onchange: move |e| assign(id, e.value().parse().unwrap_or(0)),
                        option { value: "0", selected: owner_v == 0, {t("common.unassigned")} }
                        for (sid, sname, _) in staff.iter().cloned() {
                            option { key: "{sid}", value: "{sid}", selected: owner_v == sid, "{sname}" }
                        }
                    }
                }
                if open_status {
                    div { class: "callout accent", Icon { name: "info", size: 15 } span { "{target}" } }
                }
            }
            div { class: "drawer-foot",
                if open_status {
                    button { class: "btn ghost", onclick: move |_| { set_status(id, LeadStatus::Junk); onclose.call(()); }, Icon { name: "trash-2", size: 15 } {t("leads.junk")} }
                    span { class: "spacer" }
                    if lead.status == LeadStatus::New {
                        button { class: "btn", onclick: move |_| set_status(id, LeadStatus::Contacted), Icon { name: "phone-outgoing", size: 15 } {t("leads.contacted")} }
                    }
                    if lead.status != LeadStatus::Qualified {
                        button { class: "btn", onclick: move |_| set_status(id, LeadStatus::Qualified), Icon { name: "badge-check", size: 15 } {t("leads.qualify")} }
                    }
                    button { class: "btn primary", onclick: move |_| { onclose.call(()); convert(id); }, Icon { name: "arrow-right", size: 15 } {t("leads.convert")} }
                } else if lead.status == LeadStatus::Junk {
                    button { class: "btn", onclick: move |_| set_status(id, LeadStatus::New), Icon { name: "undo-2", size: 15 } {t("leads.restore")} }
                } else {
                    ConvertedLink { lead: lead.clone() }
                }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("leads.subtitle", "Telegram, Instagram, sayt va qo‘ng‘iroqlardan kelgan saralanmagan so‘rovlar", "Неразобранные заявки из Telegram, Instagram, сайта и звонков", "Unsorted requests from Telegram, Instagram, the website and calls"),
    ("leads.new_today", "Bugun kelgan lidlar", "Новых лидов сегодня", "New leads today"),
    ("leads.waiting_now", "javob kutmoqda", "ждут ответа", "waiting for a reply"),
    ("leads.first_response", "Birinchi javobgacha", "Время первого ответа", "Avg first response"),
    ("leads.sla_hint", "1 soat ichida", "в пределах 1 часа", "within 1 h"),
    ("leads.conversion", "Mijozga aylanish", "Конверсия", "Conversion rate"),
    ("leads.processed", "ko‘rib chiqilgan", "обработанных", "processed"),
    ("leads.potential", "Ochiq lidlar salohiyati", "Потенциал открытых лидов", "Open lead potential"),
    ("leads.breached", "{n} ta yangi lid 1 soatdan beri javobsiz. Birinchi soatda bog‘lanilganlar 7 barobar ko‘proq mijozga aylanadi.", "{n} новых лидов ждут ответа больше часа. Лиды, с которыми связались в первый час, конвертируются в 7 раз чаще.", "{n} new leads have waited more than an hour. Leads contacted in the first hour convert seven times more often."),
    ("leads.search", "Ism, xabar, tashkilot yoki telefon", "Имя, сообщение, организация или телефон", "Name, message, company or phone"),
    ("leads.sort_new", "Yangilari", "Новые", "Newest"),
    ("leads.sort_score", "Eng issiq", "Самые горячие", "Hottest"),
    ("leads.empty", "Bu bo‘limda lid yo‘q", "Здесь лидов нет", "No leads here"),
    ("leads.empty_text", "Telegram bot, Instagram va saytdan kelgan so‘rovlar shu yerga tushadi.", "Сюда попадают заявки из Telegram-бота, Instagram и сайта.", "Requests from the Telegram bot, Instagram and the website land here."),
    ("leads.junk", "Keraksiz", "Нецелевой", "Junk"),
    ("leads.contacted", "Bog‘lanildi", "Связались", "Contacted"),
    ("leads.qualify", "Saralash", "Квалифицировать", "Qualify"),
    ("leads.convert", "Aylantirish", "Конвертировать", "Convert"),
    ("leads.restore", "Qaytarish", "Вернуть", "Restore"),
    ("leads.open_deal", "Bitimni ochish", "Открыть сделку", "Open deal"),
    ("leads.open_customer", "Mijozni ochish", "Открыть клиента", "Open customer"),
    ("leads.done_contacted", "Lid «Bog‘lanildi» holatiga o‘tdi", "Лид переведён в «Связались»", "Lead marked as contacted"),
    ("leads.done_qualified", "Lid saralandi", "Лид квалифицирован", "Lead qualified"),
    ("leads.done_junk", "Lid keraksizlarga o‘tkazildi", "Лид отмечен как нецелевой", "Lead moved to junk"),
    ("leads.done_new", "Lid qaytarildi", "Лид возвращён", "Lead restored"),
    ("leads.assigned", "Mas’ul tayinlandi", "Назначен ответственный", "Assigned to"),
    ("leads.converted_deal", "B2B bitim yaratildi: voronkaning birinchi bosqichida", "Создана B2B-сделка на первом этапе воронки", "B2B deal created in the first stage of the pipeline"),
    ("leads.converted_customer", "Lid mijozga aylandi, sodiqlik kartasi ochildi", "Лид стал клиентом, карта лояльности открыта", "Lead converted to a customer with a loyalty card"),
    ("leads.welcome_note", "Xush kelibsiz bonusi", "Приветственный бонус", "Welcome bonus"),
    ("leads.next_step", "Tijorat taklifini yuborish", "Отправить коммерческое предложение", "Send a quote"),
    ("leads.received", "Kelgan vaqti", "Получен", "Received"),
    ("leads.estimate", "Taxminiy summa", "Ожидаемая сумма", "Estimate"),
    ("leads.why_score", "Ball nimadan iborat", "Из чего складывается оценка", "Why this score"),
    ("leads.score_note", "Ball kanal, xabar mazmuni va summa asosida hisoblanadi.", "Оценка считается по каналу, смыслу сообщения и сумме.", "The score comes from the channel, the message intent and the estimate."),
    ("leads.convert_deal_hint", "Tashkilot nomi bor: aylantirilganda B2B voronkasida bitim va tashkilot kartasi ochiladi.", "Указана организация: при конвертации создадутся сделка в B2B-воронке и карточка организации.", "A company is named: converting creates a B2B deal and a company record."),
    ("leads.convert_customer_hint", "Aylantirilganda mijoz kartasi va sodiqlik kartasi ochiladi, xush kelibsiz bonusi beriladi.", "При конвертации создадутся карточка клиента и карта лояльности с приветственным бонусом.", "Converting creates a customer record and a loyalty card with the welcome bonus."),
];
