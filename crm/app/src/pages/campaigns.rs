//! Campaigns: Telegram and SMS broadcasts to segments that gave consent. A composer with a live
//! phone preview and personal variables, a compliance check (no prescription-medicine promotion,
//! no infant-formula marketing, an opt-out line for SMS), scheduling, and results with a funnel,
//! revenue and ROI.

use chrono::{Duration, NaiveDateTime};
use crm::analytics::month_start;
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use crm::Db;
use dioxus::prelude::*;

use crate::pages::inbox::{infant_formula, latinize, rx_promo};
use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

const SMS_PRICE: Money = 85;

fn status_tone(s: CampaignStatus) -> &'static str {
    match s {
        CampaignStatus::Draft => "",
        CampaignStatus::Scheduled => "info",
        CampaignStatus::Running => "accent",
        CampaignStatus::Done => "success",
        CampaignStatus::Paused => "warning",
    }
}

fn channel_tone(c: Channel) -> &'static str {
    match c {
        Channel::Telegram => "info",
        Channel::Sms => "warning",
        Channel::WhatsApp => "success",
        Channel::Instagram => "accent",
        _ => "muted",
    }
}

/// Can this customer get a broadcast on this channel (consent and a handle)?
fn reachable(c: &Customer, ch: Channel) -> bool {
    match ch {
        Channel::Telegram => c.consent.telegram && c.telegram.is_some(),
        Channel::Sms | Channel::WhatsApp => c.consent.sms,
        _ => c.consent.telegram || c.consent.sms,
    }
}

/// (characters, SMS parts, unicode)
fn sms_parts(text: &str) -> (usize, usize, bool) {
    let n = text.chars().count();
    let gsm = text.chars().all(|c| c == '\n' || (' '..='~').contains(&c));
    let (one, many) = if gsm { (160, 153) } else { (70, 67) };
    let parts = if n == 0 {
        0
    } else if n <= one {
        1
    } else {
        n.div_ceil(many)
    };
    (n, parts, !gsm)
}

fn has_opt_out(text: &str) -> bool {
    let l = latinize(text);
    ["stop", "otkaz", "obunani bekor", "otpis", "unsubscribe"].iter().any(|w| l.contains(w))
}

/// The message with {ism}, {ball}, {filial}, {dori} and {daraja} filled for one customer.
fn fill(db: &Db, text: &str, c: Option<&Customer>) -> String {
    let Some(c) = c else { return text.to_string() };
    let product = c.regimens.first().map(|r| db.product_name(Some(r.product_id))).unwrap_or_default();
    text.replace("{ism}", &c.first_name)
        .replace("{ball}", &fmt::num(c.points))
        .replace("{filial}", &db.branch_name(Some(c.home_branch)))
        .replace("{dori}", &product)
        .replace("{daraja}", &crate::state::t(c.tier.key()))
}

fn roi_text(revenue: Money, cost: Money) -> Option<String> {
    if cost <= 0 {
        return None;
    }
    let r = revenue as f64 / cost as f64;
    Some(if r >= 10.0 { format!("×{}", fmt::num(r.round() as i64)) } else { format!("×{:.1}", r) })
}

fn pct_of(part: u32, whole: u32) -> f64 {
    if whole == 0 {
        0.0
    } else {
        part as f64 / whole as f64 * 100.0
    }
}

fn starter_message() -> String {
    match lang() {
        Lang::Ru => "Здравствуйте, {ism}! Ждём вас в филиале {filial}: на вашем счёте {ball} баллов, ими можно оплатить до 30% покупки.".into(),
        _ => "Assalomu alaykum, {ism}! {filial} filialimizda sizni kutamiz: hisobingizda {ball} ball bor, xaridning 30% gacha qismini ular bilan to‘lashingiz mumkin.".into(),
    }
}

/// A new draft (optionally for a segment); returns its id.
fn create_draft(segment: Option<Id>) -> Id {
    let now = crate::state::now();
    let base = t("campaigns.new_name");
    let message = starter_message();
    let mut new = 0;
    mutate(|db| {
        let id = db.new_id();
        new = id;
        let seg = segment
            .filter(|s| db.segment(*s).is_some())
            .or_else(|| db.segments.iter().find(|s| s.rules.iter().any(|r| r.field == Field::ConsentTelegram)).map(|s| s.id))
            .or_else(|| db.segments.first().map(|s| s.id))
            .unwrap_or(0);
        let name = match (segment, db.segment(seg)) {
            (Some(_), Some(s)) => format!("{base}: {}", s.name),
            _ => base.clone(),
        };
        let me = db.settings.me;
        db.campaigns.insert(
            0,
            Campaign {
                id,
                name,
                channel: Channel::Telegram,
                segment_id: seg,
                message,
                status: CampaignStatus::Draft,
                scheduled: None,
                created: now,
                owner_id: me,
                audience: 0,
                sent: 0,
                delivered: 0,
                read: 0,
                clicked: 0,
                converted: 0,
                revenue: 0,
                cost: 0,
                bonus_points: 0,
            },
        );
    });
    new
}

// ---------------------------------------------------------------- list

#[component]
pub fn Campaigns() -> Element {
    // A link such as "/campaigns?segment=12" from Segments starts a draft for that segment.
    use_effect(move || {
        if let Some(h) = take_hint() {
            if let Some(seg) = h.strip_prefix("segment=").and_then(|v| v.parse::<u32>().ok()) {
                let id = create_draft(Some(seg));
                go(&format!("/campaigns/{id}"));
            }
        }
    });
    let mut status = use_signal(|| None::<CampaignStatus>);
    let mut query = use_signal(String::new);
    let stats = use_memo(move || {
        let db = DB.read();
        let m0 = month_start(crate::state::today());
        let month: Vec<&Campaign> = db.campaigns.iter().filter(|c| c.sent > 0 && c.scheduled.unwrap_or(c.created).date() >= m0).collect();
        let sent: u32 = month.iter().map(|c| c.sent).sum();
        let delivered: u32 = month.iter().map(|c| c.delivered).sum();
        let tg: Vec<&&Campaign> = month.iter().filter(|c| c.channel != Channel::Sms).collect();
        let tg_sent: u32 = tg.iter().map(|c| c.sent).sum();
        let tg_read: u32 = tg.iter().map(|c| c.read).sum();
        let clicked: u32 = month.iter().map(|c| c.clicked).sum();
        let converted: u32 = month.iter().map(|c| c.converted).sum();
        let revenue: Money = month.iter().map(|c| c.revenue).sum();
        let cost: Money = month.iter().map(|c| c.cost).sum();
        (sent, delivered, pct_of(tg_read, tg_sent), clicked, converted, revenue, cost)
    });
    let (sent, delivered, read_rate, clicked, converted, revenue, cost) = stats();
    let l = lang();
    let all: Vec<Campaign> = DB.read().campaigns.clone();
    let counts: Vec<(CampaignStatus, usize)> = CampaignStatus::ALL.iter().map(|s| (*s, all.iter().filter(|c| c.status == *s).count())).filter(|x| x.1 > 0).collect();
    let q = query().trim().to_lowercase();
    let shown: Vec<Campaign> = all
        .iter()
        .filter(|c| status().map_or(true, |s| c.status == s))
        .filter(|c| q.is_empty() || c.name.to_lowercase().contains(&q) || c.message.to_lowercase().contains(&q))
        .cloned()
        .collect();
    let running = all.iter().filter(|c| c.status == CampaignStatus::Running).count();
    let scheduled = all.iter().filter(|c| c.status == CampaignStatus::Scheduled).count();
    let subtitle = match l {
        Lang::Ru => format!("{} рассылок · идёт: {} · запланировано: {}", all.len(), running, scheduled),
        Lang::En => format!("{} campaigns · {} sending · {} scheduled", all.len(), running, scheduled),
        _ => uz(format!("{} ta kampaniya · {} tasi yuborilmoqda · {} tasi rejalashtirilgan", all.len(), running, scheduled)),
    };
    let delivered_foot = format!("{} {}", fmt::pct(pct_of(delivered, sent), l), t("campaigns.delivered_lc"));
    let clicks_foot = format!("{} {}", fmt::num(clicked as i64), t("campaigns.clicks_lc"));
    let conv_foot = format!("{} {}", fmt::pct(pct_of(converted, sent), l), t("campaigns.of_sent"));
    let rev_foot = if cost > 0 { format!("{} {}", t("campaigns.sms_spent"), money_short(cost)) } else { t("campaigns.free_channel") };
    let cur = status();
    let total = all.len();

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.campaigns"), subtitle,
                button {
                    class: "btn primary",
                    onclick: move |_| {
                        let id = create_draft(None);
                        go(&format!("/campaigns/{id}"));
                    },
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("campaigns.new")} }
                }
            }
            div { class: "grid-4",
                Kpi { label: t("campaigns.sent_month"), value: fmt::num(sent as i64), icon: "send", foot: delivered_foot }
                Kpi { label: t("campaigns.read_rate"), value: fmt::pct(read_rate, l), icon: "eye", tone: "info", foot: clicks_foot }
                Kpi { label: t("campaigns.conversions"), value: fmt::num(converted as i64), icon: "shopping-bag", tone: "success", foot: conv_foot }
                Kpi { label: t("campaigns.revenue"), value: money_short(revenue), icon: "wallet", tone: "warning", foot: rev_foot }
            }
            div { class: "toolbar",
                div { class: "chips grow",
                    button { class: if cur.is_none() { "chip on" } else { "chip" }, onclick: move |_| status.set(None), {t("common.all")} span { class: "count", "{total}" } }
                    for (s, n) in counts {
                        button {
                            key: "{s.slug()}",
                            class: if cur == Some(s) { "chip on" } else { "chip" },
                            onclick: move |_| status.set(if status() == Some(s) { None } else { Some(s) }),
                            {t(s.key())}
                            span { class: "count", "{n}" }
                        }
                    }
                }
                div { class: "search",
                    Icon { name: "search", size: 16 }
                    input { class: "input", value: "{query}", placeholder: t("campaigns.search"), oninput: move |e| query.set(e.value()) }
                }
            }
            if shown.is_empty() {
                div { class: "card",
                    Empty { icon: "megaphone", title: t("campaigns.empty"), text: t("campaigns.empty_text"),
                        button {
                            class: "btn primary",
                            onclick: move |_| {
                                let id = create_draft(None);
                                go(&format!("/campaigns/{id}"));
                            },
                            Icon { name: "plus", size: 16 }
                            {t("campaigns.new")}
                        }
                    }
                }
            }
            div { class: "grid-2",
                for c in shown {
                    CampaignCard { key: "{c.id}", c: c.clone() }
                }
            }
        }
    }
}

#[component]
fn CampaignCard(c: Campaign) -> Element {
    let now = now();
    let l = lang();
    let id = c.id;
    let (segment, size) = {
        let db = DB.read();
        let s = db.segment(c.segment_id);
        (s.map(|s| s.name.clone()).unwrap_or_else(|| "—".into()), s.map(|s| db.segment_members(s, now.date()).len()).unwrap_or(0))
    };
    let audience = if c.audience > 0 { c.audience as usize } else { size };
    let sub = format!("{} · {} {}", segment, fmt::num(audience as i64), t("campaigns.people"));
    let icon = crm::db::channel_icon(c.channel);
    let tone = channel_tone(c.channel);
    let st_tone = status_tone(c.status);
    let st_label = t(c.status.key());
    let has_stats = c.sent > 0;
    let steps: Vec<(String, String, f64)> = vec![
        (t("campaigns.f_sent"), fmt::num(c.sent as i64), 100.0),
        (t("campaigns.f_read"), fmt::num(c.read as i64), pct_of(c.read, c.sent)),
        (t("campaigns.f_clicked"), fmt::num(c.clicked as i64), pct_of(c.clicked, c.sent)),
        (t("campaigns.f_converted"), fmt::num(c.converted as i64), pct_of(c.converted, c.sent)),
    ];
    let when = match (c.status, c.scheduled) {
        (CampaignStatus::Scheduled, Some(s)) => format!("{} {}", t("campaigns.planned_for"), fmt::datetime(s, now, l)),
        (_, Some(s)) => fmt::relative(s, now, l),
        _ => fmt::relative(c.created, now, l),
    };
    let roi = roi_text(c.revenue, c.cost);
    let free = t("campaigns.free");
    let revenue_label = t("campaigns.revenue_lc");
    let preview = c.message.clone();
    rsx! {
        div { class: "card hover", onclick: move |_| go(&format!("/campaigns/{id}")),
            div { class: "card-head", style: "align-items: flex-start",
                div { class: "row gap-12", style: "min-width: 0",
                    IconTile { icon, tone }
                    div { class: "stack", style: "gap: 2px; min-width: 0",
                        span { class: "strong truncate", "{c.name}" }
                        span { class: "xs muted truncate", "{sub}" }
                    }
                }
                Badge { text: st_label, tone: st_tone, dot: true }
            }
            div { class: "card-body",
                if has_stats {
                    div { class: "grid-4", style: "gap: 10px",
                        for (label, n, p) in steps {
                            div { key: "{label}", class: "stack", style: "gap: 4px",
                                span { class: "xs muted truncate", "{label}" }
                                span { class: "strong num", "{n}" }
                                Progress { pct: p, thin: true }
                            }
                        }
                    }
                } else {
                    div { class: "small muted clamp-2", style: "padding: 10px 12px; border-radius: 10px; background: var(--c-surface-2); white-space: pre-wrap", "{preview}" }
                }
            }
            div { class: "card-foot",
                div { class: "row gap-8",
                    if c.revenue > 0 {
                        span { class: "strong num", "{money_short(c.revenue)}" }
                        span { class: "xs muted", "{revenue_label}" }
                    } else {
                        span { class: "xs muted row gap-4", Icon { name: "calendar-clock", size: 13 } "{when}" }
                    }
                }
                div { class: "row gap-8",
                    if c.revenue > 0 { span { class: "xs subtle hide-mobile", "{when}" } }
                    if let Some(r) = roi {
                        Badge { text: format!("ROI {r}"), tone: "success" }
                    } else if has_stats {
                        Badge { text: free, tone: "info" }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- detail

#[component]
pub fn CampaignDetail(id: u32) -> Element {
    let c = DB.read().campaign(id).cloned();
    let Some(c) = c else {
        return rsx! {
            div { class: "page",
                PageHeader { title: t("nav.campaigns") }
                div { class: "card",
                    Empty { icon: "megaphone", title: t("common.no_results"),
                        Link { to: Route::Campaigns {}, class: "btn", Icon { name: "arrow-left", size: 16 } {t("common.back")} }
                    }
                }
            }
        };
    };
    if matches!(c.status, CampaignStatus::Draft | CampaignStatus::Scheduled) {
        rsx! { Editor { key: "{id}", c } }
    } else {
        rsx! { Results { key: "{id}", c } }
    }
}

#[component]
fn StepHead(n: u32, title: String, #[props(default)] right: String) -> Element {
    rsx! {
        div { class: "card-head",
            div { class: "card-title",
                span { class: "ic accent sm", style: "font-weight: 800; font-size: 13px", "{n}" }
                "{title}"
            }
            if !right.is_empty() { span { class: "xs muted num", "{right}" } }
        }
    }
}

#[component]
fn PhonePreview(text: String, channel: Channel, sample: String) -> Element {
    let company = DB.read().settings.company_name.clone();
    let is_sms = channel == Channel::Sms;
    let sub = if is_sms { "SMS · 4040".to_string() } else { format!("{} · bot", t(channel.key())) };
    let empty = text.trim().is_empty();
    let shown = if empty { t("campaigns.preview_empty") } else { text.clone() };
    let bubble_style = if empty { "color: #8a8a8a" } else { "" };
    let time = fmt::time(now());
    rsx! {
        div { class: "stack gap-8", style: "align-items: center",
            div { class: "phone-mock",
                div { class: "phone-screen",
                    div { class: "row gap-8", style: "padding: 0 2px 10px; border-bottom: 1px solid rgb(0 0 0 / .07); margin-bottom: 4px",
                        div { class: "brand-mark", style: "width: 32px; height: 32px; border-radius: 99px", Icon { name: "heart-pulse", size: 16 } }
                        div { class: "stack", style: "gap: 0",
                            span { class: "small strong", style: "color: #1c1916", "{company}" }
                            span { class: "xs", style: "color: #5b6b7a", "{sub}" }
                        }
                    }
                    div { class: "tg-bubble", style: "{bubble_style}",
                        "{shown}"
                        div { class: "right", style: "font-size: 10.5px; color: #8a96a3; margin-top: 4px", "{time}" }
                    }
                    if !is_sms && !empty {
                        div { class: "grid-2", style: "gap: 6px; width: 92%",
                            div { class: "center small strong", style: "background: rgb(255 255 255 / .75); color: #2f6ea5; border-radius: 10px; padding: 7px 4px", {t("campaigns.btn_reserve")} }
                            div { class: "center small strong", style: "background: rgb(255 255 255 / .75); color: #2f6ea5; border-radius: 10px; padding: 7px 4px", {t("campaigns.btn_ask")} }
                        }
                    }
                }
            }
            if !sample.is_empty() {
                span { class: "xs subtle", "{sample}" }
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
struct Audience {
    members: usize,
    reach: Vec<Id>,
    excluded: Vec<String>,
    excluded_n: usize,
    avg_basket: Money,
    health_based: bool,
}

#[component]
fn Editor(c: Campaign) -> Element {
    let id = c.id;
    let now = now();
    let l = lang();
    let mut name = use_signal(|| c.name.clone());
    let mut channel = use_signal(|| c.channel);
    let mut segment = use_signal(|| c.segment_id);
    let mut message = use_signal(|| c.message.clone());
    let mut later = use_signal(|| c.status == CampaignStatus::Scheduled);
    let mut at = use_signal(|| {
        let d = c.scheduled.unwrap_or_else(|| (crate::state::today() + Duration::days(1)).and_hms_opt(10, 0, 0).unwrap_or(crate::state::now()));
        d.format("%Y-%m-%dT%H:%M").to_string()
    });
    let mut bonus = use_signal(|| if c.bonus_points > 0 { c.bonus_points.to_string() } else { String::new() });
    let mut sample_idx = use_signal(|| 0usize);

    let segments = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        db.segments.iter().map(|s| (s.id, s.name.clone(), db.segment_members(s, today).len())).collect::<Vec<_>>()
    });
    let audience = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let ch = channel();
        let Some(s) = db.segment(segment()) else {
            return Audience { members: 0, reach: vec![], excluded: vec![], excluded_n: 0, avg_basket: 150_000, health_based: false };
        };
        let members = db.segment_members(s, today);
        let mut reach = Vec::new();
        let mut excluded = Vec::new();
        let mut excluded_n = 0;
        let (mut basket, mut buyers) = (0, 0);
        for cid in &members {
            if let Some(cu) = db.customer(*cid) {
                if reachable(cu, ch) {
                    reach.push(cu.id);
                    if cu.orders > 0 {
                        basket += cu.avg_basket();
                        buyers += 1;
                    }
                } else {
                    excluded_n += 1;
                    if excluded.len() < 4 {
                        excluded.push(format!("{} {}.", cu.first_name, cu.last_name.chars().next().unwrap_or(' ')));
                    }
                }
            }
        }
        let health_based = s.rules.iter().any(|r| matches!(r.field, Field::Condition | Field::RefillDueInDays));
        Audience { members: members.len(), reach, excluded, excluded_n, avg_basket: if buyers > 0 { basket / buyers } else { 150_000 }, health_based }
    });
    let aud = audience();
    let msg = message();
    let ch = channel();
    let (rx, formula, sample_line, preview) = {
        let db = DB.read();
        let sample = if aud.reach.is_empty() { None } else { db.customer(aud.reach[sample_idx() % aud.reach.len()]) };
        let sample_line = sample.map(|s| format!("{} {} · {}", t("campaigns.sample"), s.name(), db.branch_name(Some(s.home_branch)))).unwrap_or_default();
        (rx_promo(&db, &msg), infant_formula(&db, &msg), sample_line, fill(&db, &msg, sample))
    };
    let is_sms = ch == Channel::Sms;
    let opt_ok = !is_sms || has_opt_out(&msg);
    let (chars, parts, unicode) = sms_parts(&preview);
    let reach_n = aud.reach.len();
    let sms_cost = reach_n as Money * parts as Money * SMS_PRICE;
    let blocked = rx.is_some() || formula.is_some() || !opt_ok || msg.trim().is_empty() || reach_n == 0;
    let counter = if is_sms {
        let kind = if unicode { "Unicode" } else { "GSM" };
        format!("{} {} · {} SMS · {}", chars, t("campaigns.chars"), parts, kind)
    } else {
        format!("{} / 4096", chars)
    };
    let excluded_line = if aud.excluded_n > 0 {
        let more = aud.excluded_n.saturating_sub(aud.excluded.len());
        let names = aud.excluded.join(", ");
        if more > 0 { format!("{names} +{more}") } else { names }
    } else {
        String::new()
    };
    let reach_pct = pct_of(reach_n as u32, aud.members as u32);
    let status_label = t(c.status.key());
    let created = fmt::datetime(c.created, now, l);
    let subtitle = format!("{status_label} · {} {created}", t("common.created").to_lowercase());
    let title = if name().trim().is_empty() { t("campaigns.untitled") } else { name() };
    let segs = segments();
    let channels = [Channel::Telegram, Channel::Sms, Channel::WhatsApp];
    let send_icon: &'static str = if later() { "calendar-clock" } else { "send" };
    let send_label = if later() { t("campaigns.schedule") } else { t("campaigns.send_now") };
    let reach_label = format!("{} {}", fmt::num(reach_n as i64), t("campaigns.will_get"));
    let members_label = format!("{} {}", fmt::num(aud.members as i64), t("campaigns.in_segment"));
    let cost_line = if is_sms { format!("{} {}", t("campaigns.est_cost"), money(sms_cost)) } else { t("campaigns.free_channel") };
    let health_based = aud.health_based;
    let rx_text = match rx.clone() {
        Some(p) => t("campaigns.rx_bad").replace("{p}", &p),
        None => t("campaigns.rx_ok"),
    };
    let formula_text = match formula.clone() {
        Some(p) => t("campaigns.formula_bad").replace("{p}", &p),
        None => t("campaigns.formula_ok"),
    };
    let consent_text = t("campaigns.consent_ok").replace("{n}", &fmt::num(reach_n as i64)).replace("{x}", &fmt::num(aud.excluded_n as i64));
    let checks: Vec<(bool, &'static str, String, String)> = {
        let mut v = vec![
            (rx.is_none(), "file-check", t("campaigns.rx_title"), rx_text),
            (formula.is_none(), "baby", t("campaigns.formula_title"), formula_text),
            (true, "shield-check", t("campaigns.consent_title"), consent_text),
        ];
        if is_sms {
            v.push((opt_ok, "bell-off", t("campaigns.optout_title"), if opt_ok { t("campaigns.optout_ok") } else { t("campaigns.optout_bad") }));
        }
        v
    };
    let avg_basket = aud.avg_basket;

    let save = move |status: Option<CampaignStatus>| {
        let now = crate::state::now();
        let when = if later() { NaiveDateTime::parse_from_str(&at(), "%Y-%m-%dT%H:%M").ok() } else { None };
        let pts: i64 = bonus().trim().replace(' ', "").parse().unwrap_or(0);
        let (n, ch) = (audience.peek().reach.len() as u32, channel());
        let (_, parts, _) = sms_parts(&message());
        mutate(|db| {
            if let Some(cp) = db.campaign_mut(id) {
                cp.name = name().trim().to_string();
                cp.channel = ch;
                cp.segment_id = segment();
                cp.message = message();
                cp.bonus_points = pts.max(0);
                cp.audience = n;
                cp.scheduled = when;
                match status {
                    Some(CampaignStatus::Running) => {
                        let sms = ch == Channel::Sms;
                        cp.status = CampaignStatus::Running;
                        cp.scheduled = Some(now);
                        cp.sent = n;
                        cp.delivered = (n as f64 * if sms { 0.98 } else { 0.96 }).round() as u32;
                        cp.read = if sms { 0 } else { (n as f64 * 0.70).round() as u32 };
                        cp.clicked = if sms { 0 } else { (n as f64 * 0.16).round() as u32 };
                        cp.converted = (n as f64 * if sms { 0.05 } else { 0.07 }).round() as u32;
                        cp.revenue = cp.converted as Money * avg_basket;
                        cp.cost = if sms { n as Money * parts.max(1) as Money * SMS_PRICE } else { 0 };
                    }
                    Some(s) => cp.status = s,
                    None => {}
                }
            }
        });
        if let Some(s) = status {
            let cname = DB.peek().campaign(id).map(|c| c.name.clone()).unwrap_or_default();
            mutate(|db| db.log(now, format!("{}: {cname}", if s == CampaignStatus::Running { "Kampaniya yuborildi" } else { "Kampaniya rejalashtirildi" }), false));
        }
    };

    rsx! {
        div { class: "page",
            PageHeader { title: title.clone(), subtitle,
                Link { to: Route::Campaigns {}, class: "btn ghost", Icon { name: "arrow-left", size: 16 } span { class: "label-text", {t("common.back")} } }
                button {
                    class: "btn ghost danger",
                    onclick: move |_| {
                        mutate(|db| db.campaigns.retain(|x| x.id != id));
                        toast(t("campaigns.deleted"), "trash-2", "");
                        go("/campaigns");
                    },
                    Icon { name: "trash-2", size: 16 }
                    span { class: "label-text", {t("common.delete")} }
                }
                button {
                    class: "btn",
                    onclick: move |_| {
                        save(None);
                        toast(t("common.saved"), "save", "success");
                    },
                    Icon { name: "save", size: 16 }
                    span { class: "label-text", {t("campaigns.save_draft")} }
                }
                button {
                    class: "btn primary keep",
                    disabled: blocked,
                    onclick: move |_| {
                        if later() {
                            save(Some(CampaignStatus::Scheduled));
                            toast(t("campaigns.scheduled_toast"), "calendar-clock", "success");
                        } else {
                            save(Some(CampaignStatus::Running));
                            toast(t("campaigns.sent_toast"), "send", "success");
                        }
                    },
                    Icon { name: send_icon, size: 16 }
                    span { class: "label-text", "{send_label}" }
                }
            }
            div { class: "grid-main",
                div { class: "stack gap-16",
                    div { class: "card",
                        StepHead { n: 1, title: t("campaigns.step_audience") }
                        div { class: "card-body stack gap-12",
                            div { class: "field",
                                label { class: "label", {t("campaigns.name")} }
                                input { class: "input", value: "{name}", oninput: move |e| name.set(e.value()) }
                            }
                            div { class: "grid-2",
                                div { class: "field",
                                    label { class: "label", {t("campaigns.channel")} }
                                    div { class: "seg", style: "width: 100%",
                                        for chn in channels {
                                            button {
                                                key: "{chn.slug()}",
                                                class: if chn == ch { "on" } else { "" },
                                                style: "flex: 1; justify-content: center",
                                                onclick: move |_| channel.set(chn),
                                                Icon { name: crm::db::channel_icon(chn), size: 14 }
                                                {t(chn.key())}
                                            }
                                        }
                                    }
                                }
                                div { class: "field",
                                    label { class: "label", {t("nav.segments")} }
                                    select { class: "select", onchange: move |e| segment.set(e.value().parse().unwrap_or(0)),
                                        for (sid, sname, n) in segs {
                                            option { key: "{sid}", value: "{sid}", selected: sid == segment(), "{sname} · {n}" }
                                        }
                                    }
                                }
                            }
                            div { class: "stack gap-8", style: "padding: 12px 14px; border-radius: 12px; background: var(--c-surface-2)",
                                div { class: "row between wrap",
                                    span { class: "row gap-8", Icon { name: "users", size: 16, class: "tone-success" } span { class: "strong", "{reach_label}" } }
                                    span { class: "small muted", "{members_label}" }
                                }
                                Progress { pct: reach_pct, tone: "success" }
                                if aud.excluded_n > 0 {
                                    div { class: "row gap-8 small muted", style: "align-items: flex-start",
                                        Icon { name: "shield-alert", size: 15, class: "tone-warning" }
                                        span {
                                            b { {t("campaigns.excluded").replace("{n}", &fmt::num(aud.excluded_n as i64))} }
                                            " {excluded_line}"
                                        }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "card",
                        StepHead { n: 2, title: t("campaigns.step_message"), right: counter.clone() }
                        div { class: "card-body stack gap-12",
                            textarea { class: "textarea", rows: "5", value: "{message}", oninput: move |e| message.set(e.value()) }
                            div { class: "row wrap gap-8",
                                span { class: "xs muted", {t("campaigns.variables")} }
                                for (var, key) in [("{ism}", "campaigns.var_name"), ("{ball}", "campaigns.var_points"), ("{filial}", "campaigns.var_branch"), ("{dori}", "campaigns.var_medicine")] {
                                    button {
                                        key: "{var}",
                                        class: "chip",
                                        style: "height: 26px; font-size: 12px",
                                        title: t(key),
                                        onclick: move |_| {
                                            let mut m = message();
                                            if !m.is_empty() && !m.ends_with(' ') && !m.ends_with('\n') {
                                                m.push(' ');
                                            }
                                            m.push_str(var);
                                            message.set(m);
                                        },
                                        Icon { name: "plus", size: 12 }
                                        "{var}"
                                    }
                                }
                            }
                            if is_sms {
                                div { class: "row between small muted",
                                    span { "{cost_line}" }
                                    if unicode { span { class: "xs subtle", {t("campaigns.unicode_hint")} } }
                                }
                            }
                        }
                    }
                    div { class: "card",
                        StepHead { n: 3, title: t("campaigns.step_check") }
                        div { class: "card-body stack gap-8",
                            for (ok, icon, ctitle, text) in checks {
                                {
                                    let tone: &'static str = if ok { "success" } else { "danger" };
                                    let mark: &'static str = if ok { "circle-check" } else { "circle-x" };
                                    rsx! {
                                        div { key: "{ctitle}", class: "row gap-12", style: "align-items: flex-start; padding: 8px 0",
                                            IconTile { icon, tone, size: "sm" }
                                            div { class: "grow stack", style: "gap: 2px",
                                                span { class: "strong small", "{ctitle}" }
                                                span { class: "small muted", "{text}" }
                                            }
                                            span { class: "tone-{tone}", style: "display: inline-flex", Icon { name: mark, size: 18 } }
                                        }
                                    }
                                }
                            }
                            if !opt_ok {
                                button {
                                    class: "btn soft sm",
                                    style: "align-self: flex-start",
                                    onclick: move |_| {
                                        let m = message();
                                        let ru = m.chars().any(|c| ('\u{0400}'..='\u{04FF}').contains(&c));
                                        let line = if ru { "Отписаться: отправьте STOP на 4040." } else { "Obunani bekor qilish: STOP deb 4040 ga yozing." };
                                        message.set(format!("{}\n{}", m.trim_end(), line));
                                    },
                                    Icon { name: "plus", size: 14 }
                                    {t("campaigns.add_optout")}
                                }
                            }
                            if health_based {
                                div { class: "callout", Icon { name: "heart-pulse", size: 16 } span { {t("campaigns.health_hint")} } }
                            }
                        }
                    }
                    div { class: "card",
                        StepHead { n: 4, title: t("campaigns.step_when") }
                        div { class: "card-body stack gap-12",
                            Segmented {
                                options: vec![("now".to_string(), t("campaigns.now")), ("later".to_string(), t("campaigns.later"))],
                                value: if later() { "later".to_string() } else { "now".to_string() },
                                onchange: move |v: String| later.set(v == "later"),
                            }
                            div { class: "grid-2",
                                if later() {
                                    div { class: "field",
                                        label { class: "label", {t("campaigns.send_at")} }
                                        input { class: "input", r#type: "datetime-local", value: "{at}", oninput: move |e| at.set(e.value()) }
                                    }
                                }
                                div { class: "field",
                                    label { class: "label", {t("campaigns.bonus")} }
                                    input { class: "input num", inputmode: "numeric", placeholder: "0", value: "{bonus}", oninput: move |e| bonus.set(e.value()) }
                                    span { class: "hint", {t("campaigns.bonus_hint")} }
                                }
                            }
                        }
                    }
                }
                div { class: "stack gap-16", style: "position: sticky; top: 76px",
                    div { class: "card pad stack gap-12",
                        div { class: "row between",
                            div { class: "card-title", Icon { name: "smartphone", size: 16, class: "subtle" } {t("campaigns.preview")} }
                            if reach_n > 1 {
                                button { class: "btn ghost sm", onclick: move |_| sample_idx.set(sample_idx() + 1), Icon { name: "refresh-cw", size: 13 } {t("campaigns.next_sample")} }
                            }
                        }
                        PhonePreview { text: preview.clone(), channel: ch, sample: sample_line }
                    }
                    if blocked {
                        div { class: "callout danger", Icon { name: "shield-alert", size: 16 } span { {t("campaigns.blocked")} } }
                    } else {
                        div { class: "callout success", Icon { name: "circle-check", size: 16 } span { {t("campaigns.ready")} } }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- results

#[component]
fn Results(c: Campaign) -> Element {
    let id = c.id;
    let now = now();
    let l = lang();
    let (segment, preview, sample_line) = {
        let db = DB.read();
        let seg = db.segment(c.segment_id);
        let sample = seg.and_then(|s| db.segment_members(s, now.date()).into_iter().filter_map(|cid| db.customer(cid)).find(|cu| reachable(cu, c.channel)));
        let line = sample.map(|s| format!("{} {}", t("campaigns.sample"), s.name())).unwrap_or_default();
        (seg.map(|s| s.name.clone()).unwrap_or_else(|| "—".into()), fill(&db, &c.message, sample), line)
    };
    let is_sms = c.channel == Channel::Sms;
    let sent_at = c.scheduled.unwrap_or(c.created);
    let subtitle = format!("{} · {} · {}", t(c.status.key()), t(c.channel.key()), fmt::datetime(sent_at, now, l));
    let read_value = if is_sms { "—".to_string() } else { fmt::pct(pct_of(c.read, c.sent), l) };
    let read_foot = if is_sms { t("campaigns.sms_no_read") } else { format!("{} {}", fmt::num(c.read as i64), t("campaigns.people")) };
    let conv_foot = format!("{} {}", fmt::pct(pct_of(c.converted, c.sent), l), t("campaigns.of_sent"));
    let roi = roi_text(c.revenue, c.cost);
    let rev_foot = match roi.clone() {
        Some(r) => format!("ROI {r}"),
        None => t("campaigns.free_channel"),
    };
    let funnel: Vec<(String, u32, String, u16)> = {
        let mut v = vec![(t("campaigns.f_sent"), c.sent, "100%".to_string(), 24), (t("campaigns.f_delivered"), c.delivered, fmt::pct(pct_of(c.delivered, c.sent), l), 32)];
        if !is_sms {
            v.push((t("campaigns.f_read"), c.read, fmt::pct(pct_of(c.read, c.sent), l), 42));
            v.push((t("campaigns.f_clicked"), c.clicked, fmt::pct(pct_of(c.clicked, c.sent), l), 95));
        }
        v.push((t("campaigns.f_converted"), c.converted, fmt::pct(pct_of(c.converted, c.sent), l), 140));
        v
    };
    let weights = [0.36, 0.22, 0.14, 0.1, 0.08, 0.06, 0.04];
    let days: Vec<(String, f64)> = weights
        .iter()
        .enumerate()
        .map(|(i, w)| {
            let d = sent_at.date() + Duration::days(i as i64);
            (format!("{} {}", d.format("%d"), fmt::month_short(chrono::Datelike::month(&d), l)), (c.converted as f64 * w).round())
        })
        .collect();
    let day_labels: Vec<String> = days.iter().map(|d| d.0.clone()).collect();
    let day_values: Vec<f64> = days.iter().map(|d| d.1).collect();
    let per_conv = if c.converted > 0 && c.cost > 0 { money(c.cost / c.converted as Money) } else { "—".to_string() };
    let money_rows = vec![
        (t("campaigns.revenue"), money(c.revenue)),
        (t("campaigns.cost"), if c.cost > 0 { money(c.cost) } else { t("campaigns.free") }),
        ("ROI".to_string(), roi.clone().unwrap_or_else(|| "—".into())),
        (t("campaigns.per_conversion"), per_conv),
        (t("campaigns.bonus_given"), if c.bonus_points > 0 { format!("{} × {}", fmt::num(c.bonus_points), fmt::num(c.converted as i64)) } else { "—".into() }),
        (t("nav.segments"), segment),
    ];
    let running = c.status == CampaignStatus::Running;
    let paused = c.status == CampaignStatus::Paused;
    let title = c.name.clone();
    let st = c.status;
    let set_status = move |s: CampaignStatus| {
        mutate(|db| {
            if let Some(x) = db.campaign_mut(id) {
                x.status = s;
            }
        });
        toast(t(s.key()), "check", "success");
    };
    let duplicate = move |_| {
        let now = crate::state::now();
        let suffix = t("campaigns.copy");
        let mut new = 0;
        mutate(|db| {
            let Some(src) = db.campaign(id).cloned() else { return };
            let nid = db.new_id();
            new = nid;
            db.campaigns.insert(
                0,
                Campaign {
                    id: nid,
                    name: format!("{} ({suffix})", src.name),
                    status: CampaignStatus::Draft,
                    scheduled: None,
                    created: now,
                    audience: 0,
                    sent: 0,
                    delivered: 0,
                    read: 0,
                    clicked: 0,
                    converted: 0,
                    revenue: 0,
                    cost: 0,
                    ..src
                },
            );
        });
        toast(t("campaigns.duplicated"), "copy", "success");
        go(&format!("/campaigns/{new}"));
    };
    rsx! {
        div { class: "page",
            PageHeader { title, subtitle,
                Link { to: Route::Campaigns {}, class: "btn ghost", Icon { name: "arrow-left", size: 16 } span { class: "label-text", {t("common.back")} } }
                button { class: "btn", onclick: duplicate, Icon { name: "copy", size: 16 } span { class: "label-text", {t("campaigns.duplicate")} } }
                if running {
                    button { class: "btn", onclick: move |_| set_status(CampaignStatus::Paused), Icon { name: "pause", size: 16 } span { class: "label-text", {t("campaigns.pause")} } }
                    button { class: "btn primary", onclick: move |_| set_status(CampaignStatus::Done), Icon { name: "circle-check", size: 16 } span { class: "label-text", {t("campaigns.finish")} } }
                }
                if paused {
                    button { class: "btn primary", onclick: move |_| set_status(CampaignStatus::Running), Icon { name: "play", size: 16 } span { class: "label-text", {t("campaigns.resume")} } }
                }
            }
            div { class: "grid-4",
                Kpi { label: t("campaigns.f_sent"), value: fmt::num(c.sent as i64), icon: "send", foot: format!("{} {}", fmt::pct(pct_of(c.delivered, c.sent), l), t("campaigns.delivered_lc")) }
                Kpi { label: t("campaigns.read_rate"), value: read_value, icon: "eye", tone: "info", foot: read_foot }
                Kpi { label: t("campaigns.conversions"), value: fmt::num(c.converted as i64), icon: "shopping-bag", tone: "success", foot: conv_foot }
                Kpi { label: t("campaigns.revenue"), value: money_short(c.revenue), icon: "wallet", tone: "warning", foot: rev_foot }
            }
            div { class: "grid-main",
                div { class: "stack gap-16",
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "funnel", size: 16, class: "subtle" } {t("campaigns.funnel")} }
                            Badge { text: t(st.key()), tone: status_tone(st), dot: true }
                        }
                        div { class: "card-body", Funnel { stages: funnel } }
                    }
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "chart-column", size: 16, class: "subtle" } {t("campaigns.by_day")} }
                        }
                        div { class: "card-body", BarChart { labels: day_labels, values: day_values, height: 180, highlight: Some(0) } }
                    }
                    div { class: "card",
                        div { class: "card-head", div { class: "card-title", Icon { name: "wallet", size: 16, class: "subtle" } {t("campaigns.money")} } }
                        div { class: "card-body", KeyValues { items: money_rows } }
                    }
                }
                div { class: "card pad stack gap-12",
                    div { class: "card-title", Icon { name: "smartphone", size: 16, class: "subtle" } {t("campaigns.preview")} }
                    PhonePreview { text: preview, channel: c.channel, sample: sample_line }
                }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("campaigns.new", "Yangi kampaniya", "Новая рассылка", "New campaign"),
    ("campaigns.new_name", "Yangi kampaniya", "Новая рассылка", "New campaign"),
    ("campaigns.untitled", "Nomsiz kampaniya", "Рассылка без названия", "Untitled campaign"),
    ("campaigns.search", "Kampaniyani qidirish…", "Поиск рассылки…", "Search campaigns…"),
    ("campaigns.sent_month", "Shu oy yuborildi", "Отправлено за месяц", "Sent this month"),
    ("campaigns.delivered_lc", "yetkazildi", "доставлено", "delivered"),
    ("campaigns.read_rate", "O‘qilish darajasi", "Доля прочтений", "Read rate"),
    ("campaigns.clicks_lc", "ta bosish", "кликов", "clicks"),
    ("campaigns.conversions", "Xarid qilganlar", "Конверсии", "Conversions"),
    ("campaigns.of_sent", "yuborilganlardan", "от отправленных", "of sent"),
    ("campaigns.revenue", "Kampaniya tushumi", "Выручка рассылок", "Attributed revenue"),
    ("campaigns.revenue_lc", "tushum", "выручка", "revenue"),
    ("campaigns.free_channel", "Telegram bepul: SMS xarajati yo‘q", "Telegram бесплатно: без затрат на SMS", "Telegram is free: no SMS cost"),
    ("campaigns.free", "Bepul", "Бесплатно", "Free"),
    ("campaigns.sms_spent", "SMSga sarflandi:", "Потрачено на SMS:", "Spent on SMS:"),
    ("campaigns.people", "kishi", "чел.", "people"),
    ("campaigns.planned_for", "Rejada:", "Запланировано:", "Planned for"),
    ("campaigns.empty", "Kampaniyalar yo‘q", "Рассылок нет", "No campaigns"),
    ("campaigns.empty_text", "Segment tanlang va birinchi Telegram xabarini yuboring.", "Выберите сегмент и отправьте первую рассылку в Telegram.", "Pick a segment and send your first Telegram message."),
    ("campaigns.f_sent", "Yuborildi", "Отправлено", "Sent"),
    ("campaigns.f_delivered", "Yetkazildi", "Доставлено", "Delivered"),
    ("campaigns.f_read", "O‘qildi", "Прочитано", "Read"),
    ("campaigns.f_clicked", "Bosildi", "Клики", "Clicked"),
    ("campaigns.f_converted", "Xarid qildi", "Купили", "Bought"),
    ("campaigns.step_audience", "Auditoriya", "Аудитория", "Audience"),
    ("campaigns.step_message", "Xabar", "Сообщение", "Message"),
    ("campaigns.step_check", "Muvofiqlik tekshiruvi", "Проверка на соответствие", "Compliance check"),
    ("campaigns.step_when", "Qachon yuborish", "Когда отправить", "When to send"),
    ("campaigns.name", "Kampaniya nomi", "Название рассылки", "Campaign name"),
    ("campaigns.channel", "Kanal", "Канал", "Channel"),
    ("campaigns.will_get", "kishiga yetib boradi", "получат сообщение", "will receive it"),
    ("campaigns.in_segment", "segmentda", "в сегменте", "in the segment"),
    ("campaigns.excluded", "Roziligi yo‘q, chiqarib tashlandi: {n}.", "Без согласия, исключены: {n}.", "No consent, left out: {n}."),
    ("campaigns.chars", "belgi", "симв.", "chars"),
    ("campaigns.variables", "O‘zgaruvchilar:", "Переменные:", "Variables:"),
    ("campaigns.var_name", "Mijozning ismi", "Имя клиента", "Customer’s first name"),
    ("campaigns.var_points", "Ballar soni", "Баланс баллов", "Points balance"),
    ("campaigns.var_branch", "Mijozning filiali", "Филиал клиента", "Customer’s branch"),
    ("campaigns.var_medicine", "Doimiy dorisi", "Постоянный препарат", "Regular medicine"),
    ("campaigns.est_cost", "Taxminiy SMS xarajati:", "Примерная стоимость SMS:", "Estimated SMS cost:"),
    ("campaigns.unicode_hint", "‘ va kirill harflari SMSni 70 belgiga qisqartiradi", "Кириллица и ‘ сокращают SMS до 70 символов", "‘ and Cyrillic shorten an SMS to 70 characters"),
    ("campaigns.rx_title", "Retseptli dorilar reklama qilinmaydi", "Без рекламы рецептурных препаратов", "No prescription-medicine promotion"),
    ("campaigns.rx_ok", "Matnda retseptli dori aksiyasi yo‘q.", "В тексте нет акций на рецептурные препараты.", "No promotion of prescription medicines in the text."),
    ("campaigns.rx_bad", "{p} retsept bo‘yicha beriladi: aksiya, chegirma va bonus so‘zlarini olib tashlang.", "{p} отпускается по рецепту: уберите слова об акции, скидке и бонусах.", "{p} is prescription-only: remove the sale, discount and bonus wording."),
    ("campaigns.formula_title", "Bolalar suti aralashmasi reklamasi taqiqlangan", "Запрет рекламы детских смесей", "Infant formula marketing ban"),
    ("campaigns.formula_ok", "Bolalar suti aralashmasi tilga olinmagan.", "Детские смеси не упоминаются.", "No infant formula is mentioned."),
    ("campaigns.formula_bad", "{p}: ko‘krak suti o‘rnini bosuvchi mahsulotlarni reklama qilish mumkin emas.", "{p}: заменители грудного молока рекламировать нельзя.", "{p}: breast-milk substitutes can’t be marketed."),
    ("campaigns.consent_title", "Faqat roziligi borlarga", "Только с согласия", "Consent only"),
    ("campaigns.consent_ok", "{n} kishiga yuboriladi; roziligi yo‘q {x} kishi avtomatik chiqarildi.", "Получат {n} чел.; {x} без согласия исключены автоматически.", "{n} people get it; {x} without consent are left out automatically."),
    ("campaigns.optout_title", "SMSda obunadan chiqish satri", "Строка отписки в SMS", "SMS opt-out line"),
    ("campaigns.optout_ok", "Obunani bekor qilish yo‘li ko‘rsatilgan.", "Способ отписки указан.", "The opt-out instruction is there."),
    ("campaigns.optout_bad", "Reklama SMSida obunadan chiqish yo‘li bo‘lishi shart.", "В рекламном SMS обязателен способ отписки.", "A marketing SMS must say how to opt out."),
    ("campaigns.add_optout", "Obunadan chiqish satrini qo‘shish", "Добавить строку отписки", "Add the opt-out line"),
    ("campaigns.health_hint", "Segment sog‘liq ma’lumotlariga asoslangan: xabarda kasallik nomini yozmang.", "Сегмент построен на данных о здоровье: не называйте заболевание в тексте.", "This segment is built on health data: don’t name the condition in the message."),
    ("campaigns.now", "Hozir", "Сейчас", "Now"),
    ("campaigns.later", "Rejalashtirish", "Запланировать", "Schedule"),
    ("campaigns.send_at", "Yuborish vaqti", "Время отправки", "Send at"),
    ("campaigns.bonus", "Bonus ball (ixtiyoriy)", "Бонусные баллы (необязательно)", "Bonus points (optional)"),
    ("campaigns.bonus_hint", "Kampaniyadan keyin xarid qilganlarga beriladi", "Начислим тем, кто купит после рассылки", "Given to those who buy after the campaign"),
    ("campaigns.preview", "Ko‘rinishi", "Предпросмотр", "Preview"),
    ("campaigns.preview_empty", "Xabar matni shu yerda ko‘rinadi", "Здесь появится текст сообщения", "Your message appears here"),
    ("campaigns.sample", "Namuna:", "Пример:", "Sample:"),
    ("campaigns.next_sample", "Boshqa mijoz", "Другой клиент", "Another customer"),
    ("campaigns.btn_reserve", "Bron qilish", "Забронировать", "Reserve"),
    ("campaigns.btn_ask", "Farmatsevtga yozish", "Написать фармацевту", "Ask a pharmacist"),
    ("campaigns.blocked", "Yuborishdan oldin qizil bandlarni tuzating.", "Исправьте пункты, отмеченные красным, перед отправкой.", "Fix the items marked red before sending."),
    ("campaigns.ready", "Hammasi tayyor: yuborish mumkin.", "Всё готово к отправке.", "All set: ready to send."),
    ("campaigns.save_draft", "Qoralamani saqlash", "Сохранить черновик", "Save draft"),
    ("campaigns.send_now", "Hozir yuborish", "Отправить сейчас", "Send now"),
    ("campaigns.schedule", "Rejalashtirish", "Запланировать", "Schedule"),
    ("campaigns.sent_toast", "Kampaniya yuborilmoqda", "Рассылка отправляется", "Campaign is sending"),
    ("campaigns.scheduled_toast", "Kampaniya rejalashtirildi", "Рассылка запланирована", "Campaign scheduled"),
    ("campaigns.deleted", "Qoralama o‘chirildi", "Черновик удалён", "Draft deleted"),
    ("campaigns.duplicate", "Nusxa olish", "Дублировать", "Duplicate"),
    ("campaigns.duplicated", "Nusxa qoralama sifatida yaratildi", "Копия создана как черновик", "Copy created as a draft"),
    ("campaigns.copy", "nusxa", "копия", "copy"),
    ("campaigns.pause", "To‘xtatish", "Пауза", "Pause"),
    ("campaigns.resume", "Davom ettirish", "Возобновить", "Resume"),
    ("campaigns.finish", "Yakunlash", "Завершить", "Finish"),
    ("campaigns.sms_no_read", "SMSda o‘qilganlik ko‘rinmaydi", "У SMS нет отчёта о прочтении", "SMS has no read receipts"),
    ("campaigns.funnel", "Voronka", "Воронка", "Funnel"),
    ("campaigns.by_day", "Kunlar bo‘yicha xaridlar", "Покупки по дням", "Purchases by day"),
    ("campaigns.money", "Daromad va xarajat", "Доход и расходы", "Revenue and cost"),
    ("campaigns.cost", "Xarajat", "Расходы", "Cost"),
    ("campaigns.per_conversion", "Bitta xarid narxi", "Цена одной покупки", "Cost per purchase"),
    ("campaigns.bonus_given", "Berilgan bonus", "Начислено бонусов", "Bonus given"),
];
