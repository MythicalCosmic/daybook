//! Refill radar: regular medicines that run out in the next two weeks (or already ran out),
//! grouped by urgency. One tap reminds on Telegram, reserves a pack, plans a call or snoozes.

use std::collections::{HashMap, HashSet};

use chrono::{Datelike, Duration, NaiveDateTime};
use crm::analytics::{self, RefillDue};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

/// One line on the radar, with everything the row shows already looked up.
#[derive(Clone, PartialEq)]
struct Row {
    r: RefillDue,
    name: String,
    tier: Tier,
    product: String,
    dose: String,
    branch: String,
    telegram: bool,
    /// Telegram or SMS consent: can we message them at all?
    reachable: bool,
    outcome: Option<String>,
    reminded: bool,
    held: Option<WaitStatus>,
    call_planned: bool,
}

const GROUPS: [(&str, &str, &str); 4] = [
    ("overdue", "circle-alert", "danger"),
    ("soon", "alarm-clock", "warning"),
    ("week", "calendar-days", "accent"),
    ("later", "calendar-clock", "info"),
];

fn group_of(days_left: i64) -> &'static str {
    match days_left {
        d if d < 0 => "overdue",
        0 | 1 => "soon",
        2..=7 => "week",
        _ => "later",
    }
}

const PER_GROUP: usize = 25;

#[component]
pub fn Refills() -> Element {
    let l = lang();
    let today = today();
    let rows = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let today = now.date();
        let list = analytics::refills(&db, today, 14);
        let mut last_call: HashMap<Id, (NaiveDateTime, String)> = HashMap::new();
        let mut reminded: HashSet<Id> = HashSet::new();
        let mut planned: HashSet<Id> = HashSet::new();
        for a in &db.activities {
            let Some(c) = a.customer_id else { continue };
            match a.kind {
                ActivityKind::Call if a.done => {
                    if let Some(o) = &a.outcome {
                        let at = a.done_at.unwrap_or(a.due);
                        let e = last_call.entry(c).or_insert_with(|| (at, o.clone()));
                        if at > e.0 {
                            *e = (at, o.clone());
                        }
                    }
                }
                ActivityKind::Call => {
                    planned.insert(c);
                }
                ActivityKind::Message if a.done && a.done_at.map(|d| d.date() == today).unwrap_or(false) => {
                    reminded.insert(c);
                }
                _ => {}
            }
        }
        let mut held: HashMap<(Id, Id), WaitStatus> = HashMap::new();
        for w in &db.waitlist {
            if let Some(p) = w.product_id {
                if matches!(w.status, WaitStatus::Waiting | WaitStatus::Arrived | WaitStatus::Notified | WaitStatus::Reserved) {
                    held.insert((w.customer_id, p), w.status);
                }
            }
        }
        list.into_iter()
            .filter_map(|r| {
                let c = db.customer(r.customer_id)?;
                let dose = c.regimens.iter().find(|g| g.product_id == r.product_id).map(|g| g.dose.clone()).unwrap_or_default();
                Some(Row {
                    name: c.name(),
                    tier: c.tier,
                    product: db.product_name(Some(r.product_id)),
                    dose,
                    branch: db.branch_name(Some(r.branch_id)),
                    telegram: c.consent.telegram,
                    reachable: c.consent.telegram || c.consent.sms,
                    outcome: last_call.get(&c.id).map(|x| x.1.clone()),
                    reminded: reminded.contains(&c.id),
                    held: held.get(&(c.id, r.product_id)).copied(),
                    call_planned: planned.contains(&c.id),
                    r,
                })
            })
            .collect::<Vec<Row>>()
    });
    let adherence = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let (mut on, mut late) = (0u32, 0u32);
        for c in db.customers.iter().filter(|c| !c.archived && c.consent.health_data) {
            for g in c.regimens.iter().filter(|g| g.remind) {
                if g.days_left(today) >= -2 {
                    on += 1;
                } else {
                    late += 1;
                }
            }
        }
        (on, late)
    });

    let mut branch = use_signal(|| 0u32);
    let mut cond = use_signal(|| None::<Condition>);
    let mut day = use_signal(|| None::<i64>);
    let mut more = use_signal(HashSet::<&'static str>::new);

    let branches: Vec<(Id, String)> = DB.read().branches.iter().map(|b| (b.id, b.name.clone())).collect();
    let lead_days = DB.read().settings.refill_lead_days as i64;

    let all = rows();
    let base: Vec<Row> = all.iter().filter(|x| branch() == 0 || x.r.branch_id == branch()).cloned().collect();
    let mut cond_counts: Vec<(Condition, usize)> =
        Condition::ALL.iter().map(|c| (*c, base.iter().filter(|x| x.r.condition == *c).count())).filter(|x| x.1 > 0).collect();
    cond_counts.sort_by(|a, b| b.1.cmp(&a.1));
    let base: Vec<Row> = base.into_iter().filter(|x| cond().map_or(true, |c| x.r.condition == c)).collect();
    let shown: Vec<Row> = base
        .iter()
        .filter(|x| match day() {
            None => true,
            Some(-1) => x.r.days_left < 0,
            Some(d) => x.r.days_left == d,
        })
        .cloned()
        .collect();

    // KPIs follow the branch and condition filters, not the day.
    let due_today = base.iter().filter(|x| x.r.days_left == 0).count();
    let due_tomorrow = base.iter().filter(|x| x.r.days_left == 1).count();
    let week = base.iter().filter(|x| (0..=7).contains(&x.r.days_left)).count();
    let later = base.iter().filter(|x| x.r.days_left > 7).count();
    let overdue = base.iter().filter(|x| x.r.days_left < 0).count();
    let upcoming: Money = base.iter().filter(|x| x.r.days_left >= 0).map(|x| x.r.price).sum();
    let people: HashSet<Id> = base.iter().map(|x| x.r.customer_id).collect();
    let reach: HashSet<Id> = base.iter().filter(|x| x.telegram).map(|x| x.r.customer_id).collect();
    let reach_pct = if people.is_empty() { 0.0 } else { reach.len() as f64 / people.len() as f64 * 100.0 };

    let subtitle = t("refills.sub").replace("{n}", &fmt::num(people.len() as i64)).replace("{v}", &money_short(upcoming));

    // the 14-day strip (plus the "already ran out" cell first)
    let mut cells: Vec<(i64, usize)> = vec![(-1, overdue)];
    for i in 0..14 {
        cells.push((i, base.iter().filter(|x| x.r.days_left == i).count()));
    }
    let cell_max = cells.iter().map(|c| c.1).max().unwrap_or(0).max(1);

    let (on_time, late) = adherence();
    let adh_total = (on_time + late).max(1);
    let on_pct = on_time as f64 / adh_total as f64 * 100.0;
    let reminded_today = all.iter().filter(|x| x.reminded).map(|x| x.r.customer_id).collect::<HashSet<_>>().len();

    let mut needed: HashMap<Id, (String, usize, Money)> = HashMap::new();
    for x in &base {
        let e = needed.entry(x.r.product_id).or_insert_with(|| (x.product.clone(), 0, 0));
        e.1 += 1;
        e.2 += x.r.price;
    }
    let mut needed: Vec<(String, usize, Money)> = needed.into_values().collect();
    needed.sort_by(|a, b| b.1.cmp(&a.1).then(b.2.cmp(&a.2)));
    let needed_items: Vec<(String, f64, String)> = needed
        .iter()
        .take(6)
        .map(|(name, n, _)| (name.clone(), *n as f64, format!("{} {}", n, t("refills.packs"))))
        .collect();

    let packs_total: usize = needed.iter().map(|x| x.1).sum();
    let packs_text = t("refills.packs_total").replace("{n}", &packs_total.to_string()).replace("{v}", &money_short(needed.iter().map(|x| x.2).sum()));
    // the reminder the next customer gets, shown as it looks on their phone
    let preview: Option<Row> = base.iter().find(|x| x.r.days_left >= 0 && x.telegram).cloned();
    let due_pairs: Vec<(Id, Id)> =
        base.iter().filter(|x| x.r.days_left >= 0 && x.r.days_left <= lead_days).map(|x| (x.r.customer_id, x.r.product_id)).collect();
    let no_due = due_pairs.is_empty();
    let remind_due_label = t("refills.remind_due").replace("{n}", &lead_days.to_string());
    let auto_note = t("refills.auto_note").replace("{n}", &lead_days.to_string());
    let tomorrow_foot = t("refills.kpi_tomorrow_foot").replace("{n}", &due_tomorrow.to_string());
    let week_foot = t("refills.kpi_week_foot").replace("{n}", &later.to_string());
    let reach_foot = t("refills.kpi_reach_foot").replace("{n}", &reach.len().to_string()).replace("{m}", &people.len().to_string());

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.refills"), subtitle,
                button { class: "btn", onclick: move |_| go("/automations"),
                    Icon { name: "workflow", size: 16 }
                    span { class: "label-text", {t("nav.automations")} }
                }
                button {
                    class: "btn primary keep",
                    disabled: no_due,
                    onclick: move |_| remind_many(&due_pairs),
                    Icon { name: "send", size: 16 }
                    span { class: "label-text", "{remind_due_label}" }
                }
            }

            div { class: "grid", style: "grid-template-columns: repeat(auto-fit, minmax(170px, 1fr))",
                Kpi { label: t("refills.kpi_today"), value: fmt::num(due_today as i64), icon: "alarm-clock", tone: "warning", foot: tomorrow_foot,
                    onclick: move |_| day.set(Some(0)),
                }
                Kpi { label: t("refills.kpi_week"), value: fmt::num(week as i64), icon: "calendar-days", foot: week_foot }
                Kpi { label: t("refills.kpi_overdue"), value: fmt::num(overdue as i64), icon: "circle-alert", tone: "danger", foot: t("refills.kpi_overdue_foot"),
                    onclick: move |_| day.set(Some(-1)),
                }
                Kpi { label: t("refills.kpi_value"), value: money_short(upcoming), icon: "wallet", tone: "success", foot: t("refills.kpi_value_foot") }
                Kpi { label: t("refills.kpi_reach"), value: fmt::pct(reach_pct, l), icon: "send", tone: "info", foot: reach_foot }
            }

            div { class: "grid-main",
                div { class: "card",
                    div { class: "card-head",
                        div {
                            div { class: "card-title", Icon { name: "calendar-clock", size: 16, class: "tone-accent" } {t("refills.strip_title")} }
                            div { class: "xs muted", style: "margin-top: 2px", {t("refills.strip_hint")} }
                        }
                        if day().is_some() {
                            button { class: "btn ghost sm", onclick: move |_| day.set(None), Icon { name: "x", size: 14 } {t("refills.all_days")} }
                        }
                    }
                    div { class: "card-body",
                        div { style: "overflow-x: auto; margin: 0 -4px; padding: 0 4px",
                            div { style: "display: grid; grid-template-columns: repeat(15, minmax(34px, 1fr)); gap: 6px; min-width: 540px",
                                for (d, n) in cells {
                                    {
                                        let selected = day() == Some(d);
                                        let is_today = d == 0;
                                        let h = if n == 0 { 4.0 } else { 10.0 + n as f64 / cell_max as f64 * 58.0 };
                                        let bar = if d < 0 {
                                            if selected { "var(--c-danger)" } else { "color-mix(in srgb, var(--c-danger) 55%, var(--c-surface-3))" }
                                        } else if n == 0 {
                                            "var(--c-surface-3)"
                                        } else if selected || (day().is_none() && is_today) {
                                            "var(--c-primary)"
                                        } else {
                                            "color-mix(in srgb, var(--c-chart-1) 45%, var(--c-surface-3))"
                                        };
                                        let border = if selected { "var(--c-primary)" } else if is_today { "var(--c-border-strong)" } else { "transparent" };
                                        let bg = if selected { "var(--c-accent-soft)" } else if is_today { "var(--c-surface-2)" } else { "transparent" };
                                        let date = today + Duration::days(d.max(0));
                                        let top = if d < 0 { t("refills.group.overdue") } else { fmt::weekday_short(date.weekday().num_days_from_monday(), l) };
                                        let bottom = if d < 0 { "≤ −1".to_string() } else { date.day().to_string() };
                                        let top_cls = if is_today { "xs strong tone-accent truncate" } else if d < 0 { "xs strong tone-danger truncate" } else { "xs muted truncate" };
                                        let num_cls = if n == 0 { "xs subtle num" } else { "xs strong num" };
                                        rsx! {
                                            button {
                                                key: "{d}",
                                                style: "display:flex; flex-direction:column; align-items:center; justify-content:flex-end; gap:5px; height:132px; padding:8px 2px 7px; border-radius:12px; border:1px solid {border}; background:{bg}; cursor:pointer; min-width:0; transition: background .12s, border-color .12s",
                                                onclick: move |_| day.set(if day() == Some(d) { None } else { Some(d) }),
                                                span { class: num_cls, "{n}" }
                                                span { style: "width: 70%; max-width: 26px; height: {h:.0}px; border-radius: 7px; background: {bar}; transition: height .4s var(--ease)" }
                                                if d < 0 {
                                                    span { class: "tone-danger", title: "{top}", style: "line-height: 0", Icon { name: "circle-alert", size: 14 } }
                                                } else {
                                                    span { class: top_cls, style: "max-width: 100%", "{top}" }
                                                }
                                                span { class: "xs subtle num", "{bottom}" }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "card-foot",
                        div { class: "row gap-8 small muted", style: "min-width: 0",
                            span { class: "ic accent sm", Icon { name: "workflow", size: 14 } }
                            span { class: "clamp-2", "{auto_note}" }
                        }
                        button { class: "btn ghost sm", onclick: move |_| go("/automations"), {t("refills.open_automation")} Icon { name: "arrow-right", size: 14 } }
                    }
                }

                div { class: "card",
                    div { class: "card-head",
                        div { class: "card-title", Icon { name: "heart-pulse", size: 16, class: "tone-success" } {t("refills.adherence")} }
                    }
                    div { class: "card-body stack gap-12",
                        Donut {
                            slices: vec![
                                Slice { label: t("refills.on_time"), value: on_time as f64, color: "var(--c-success)".into() },
                                Slice { label: t("refills.late"), value: late as f64, color: "var(--c-danger)".into() },
                            ],
                            center: fmt::pct(on_pct, l),
                            caption: t("refills.on_time").to_lowercase(),
                            size: 128,
                        }
                        div { class: "xs muted center", {t("refills.adherence_hint")} }
                        div {
                            div { class: "stat-line small",
                                span { class: "muted", {t("refills.on_time")} }
                                span { class: "num strong", "{on_time}" }
                            }
                            div { class: "stat-line small",
                                span { class: "muted", {t("refills.late")} }
                                span { class: "num strong tone-danger", "{late}" }
                            }
                            div { class: "stat-line small",
                                span { class: "muted", {t("refills.reminded_today")} }
                                span { class: "num strong tone-success", "{reminded_today}" }
                            }
                        }
                    }
                }
            }

            div { class: "toolbar",
                select {
                    class: "select sm",
                    style: "width: auto; min-width: 170px",
                    onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                    option { value: "0", selected: branch() == 0, {t("common.all_branches")} }
                    for (id, name) in branches {
                        option { key: "{id}", value: "{id}", selected: id == branch(), "{name}" }
                    }
                }
                div { class: "chips grow",
                    button { class: if cond().is_none() { "chip on" } else { "chip" }, onclick: move |_| cond.set(None),
                        {t("common.all")}
                    }
                    for (c, n) in cond_counts {
                        button {
                            key: "{c.slug()}",
                            class: if cond() == Some(c) { "chip on" } else { "chip" },
                            onclick: move |_| cond.set(if cond() == Some(c) { None } else { Some(c) }),
                            {t(c.key())}
                            span { class: "count", "{n}" }
                        }
                    }
                }
            }

            if shown.is_empty() {
                div { class: "card",
                    Empty { icon: "circle-check", title: t("refills.empty"), text: t("refills.empty_text"),
                        if day().is_some() || cond().is_some() || branch() != 0 {
                            button { class: "btn soft sm", onclick: move |_| { day.set(None); cond.set(None); branch.set(0); }, Icon { name: "rotate-ccw", size: 14 } {t("refills.reset_filters")} }
                        }
                    }
                }
            }

            for (g, icon, tone) in GROUPS {
                {
                    let items: Vec<Row> = shown.iter().filter(|x| group_of(x.r.days_left) == g).cloned().collect();
                    let count = items.len();
                    let value: Money = items.iter().map(|x| x.r.price).sum();
                    let value_text = money_short(value);
                    let pairs: Vec<(Id, Id)> = items.iter().map(|x| (x.r.customer_id, x.r.product_id)).collect();
                    let open = more.read().contains(g);
                    let visible: Vec<Row> = if open { items.clone() } else { items.iter().take(PER_GROUP).cloned().collect() };
                    let hidden = count.saturating_sub(visible.len());
                    let more_label = t("refills.show_more").replace("{n}", &hidden.to_string());
                    let title = t(&format!("refills.group.{g}"));
                    rsx! {
                        if count > 0 {
                            div { class: "card", key: "{g}",
                                div { class: "card-head",
                                    div { class: "card-title",
                                        span { class: "ic {tone} sm", Icon { name: icon, size: 15 } }
                                        "{title}"
                                        span { class: "badge", "{count}" }
                                    }
                                    div { class: "row gap-12",
                                        span { class: "small muted num hide-mobile", "{value_text}" }
                                        button { class: "btn soft sm", onclick: move |_| remind_many(&pairs),
                                            Icon { name: "send", size: 14 }
                                            {t("refills.remind_group")}
                                        }
                                    }
                                }
                                div { class: "list", style: "margin-top: 10px",
                                    for x in visible {
                                        RefillItem { key: "{x.r.customer_id}-{x.r.product_id}", row: x }
                                    }
                                }
                                if hidden > 0 {
                                    div { class: "card-foot", style: "justify-content: center",
                                        button { class: "btn ghost sm", onclick: move |_| { more.write().insert(g); }, Icon { name: "chevron-down", size: 14 } "{more_label}" }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if !needed_items.is_empty() || preview.is_some() {
                div { class: "grid-2",
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "pill-bottle", size: 16, class: "subtle" } {t("refills.most_needed")} }
                            span { class: "xs muted", {t("refills.kpi_value_foot")} }
                        }
                        div { class: "card-body",
                            if needed_items.is_empty() {
                                Empty { icon: "circle-check", title: t("refills.empty") }
                            } else {
                                HBars { items: needed_items }
                            }
                        }
                        if packs_total > 0 {
                            div { class: "card-foot",
                                span { class: "small muted", "{packs_text}" }
                                button {
                                    class: "btn soft sm",
                                    onclick: move |_| {
                                        mutate(|db| db.log(crate::state::now(), format!("Daybook xarid so‘rovi: dori radari, {packs_total} qadoq"), false));
                                        toast(t("products.purchasing_sent"), "send", "success");
                                    },
                                    Icon { name: "send", size: 14 }
                                    {t("products.to_purchasing")}
                                }
                            }
                        }
                    }
                    if let Some(p) = preview {
                        TelegramPreview { row: p }
                    }
                }
            }
        }
    }
}

#[component]
fn RefillItem(row: Row) -> Element {
    let l = lang();
    let today = today();
    let r = row.r.clone();
    let cid = r.customer_id;
    let pid = r.product_id;
    let bid = r.branch_id;
    let price = r.price;
    let due_text = fmt::due_in(r.due, today, l);
    let tone = if r.days_left < 0 {
        "danger"
    } else if r.days_left <= 1 {
        "warning"
    } else if r.days_left <= 7 {
        "accent"
    } else {
        ""
    };
    let (stock_cls, stock_text) = if r.in_stock { ("tone-success", t("refills.in_stock")) } else { ("tone-danger", t("refills.out_stock")) };
    let outcome = row.outcome.clone().unwrap_or_else(|| t("refills.no_calls"));
    let outcome_cls = if row.outcome.is_some() { "small clamp-2" } else { "small subtle" };
    let held = row.held.map(|s| if s == WaitStatus::Reserved { t("refills.held_reserved") } else { t("refills.held_waiting") });
    let name = row.name.clone();
    let product = row.product.clone();
    let product2 = row.product.clone();
    let product3 = row.product.clone();
    let no_consent = t("refills.toast_no_consent");
    let condition = t(r.condition.key());
    let overdue = r.days_left < 0;
    let reminded = row.reminded;
    let remind_label = if reminded { t("refills.reminded") } else { t("refills.remind") };
    let remind_cls = if reminded { "btn sm ghost tone-success" } else { "btn sm soft" };
    let remind_icon: &'static str = if reminded { "check" } else { "send" };
    let call_title = if row.call_planned { t("refills.call_planned") } else { t("common.call") };
    let call_cls = if row.call_planned { "icon-btn sm bordered tone-success" } else { "icon-btn sm bordered" };
    let reserve_title = t("refills.reserve");
    let snooze_title = t("refills.snooze");
    rsx! {
        div { class: "list-row", style: "flex-wrap: wrap; row-gap: 10px",
            div { class: "row gap-12 grow", style: "min-width: 200px; flex-basis: 220px; cursor: pointer", onclick: move |_| go(&format!("/contacts/{cid}")),
                Avatar { name: name.clone() }
                div { class: "meta",
                    div { class: "row gap-8",
                        span { class: "title truncate", "{name}" }
                        TierBadge { tier: row.tier }
                    }
                    div { class: "sub row gap-4", style: "min-width: 0",
                        Icon { name: "pill", size: 12 }
                        span { class: "truncate", "{product}" }
                    }
                    div { class: "row gap-8 wrap only-mobile", style: "margin-top: 4px",
                        Badge { text: due_text.clone(), tone, dot: true }
                        span { class: "xs {stock_cls}", "{stock_text}" }
                        if let Some(h) = held.clone() {
                            span { class: "badge success sm", Icon { name: "package-check", size: 12 } "{h}" }
                        }
                    }
                }
            }
            div { class: "hide-mobile stack gap-4", style: "width: 150px; align-items: flex-start",
                Badge { text: condition, tone: "info" }
                if !row.dose.is_empty() {
                    span { class: "xs subtle truncate", style: "max-width: 100%", "{row.dose}" }
                }
            }
            div { class: "hide-mobile row gap-4 small muted", style: "width: 118px",
                Icon { name: "store", size: 13 }
                span { class: "truncate", "{row.branch}" }
            }
            div { class: "hide-mobile stack gap-4", style: "width: 136px; align-items: flex-start",
                Badge { text: due_text, tone, dot: true }
                span { class: "xs row gap-4 {stock_cls}",
                    span { style: "width: 6px; height: 6px; border-radius: 99px; background: currentColor; display: inline-block" }
                    "{stock_text}"
                }
                if let Some(h) = held {
                    span { class: "badge success sm", Icon { name: "package-check", size: 12 } "{h}" }
                }
            }
            div { class: "hide-mobile stack gap-4", style: "width: 160px",
                span { class: "xs subtle upper", {t("refills.last_call")} }
                span { class: outcome_cls, "{outcome}" }
            }
            div { class: "row gap-4", style: "margin-left: auto; min-width: 206px; justify-content: flex-end",
                if row.reachable {
                    button {
                        class: remind_cls,
                        title: "{remind_label}",
                        onclick: move |_| remind_many(&[(cid, pid)]),
                        Icon { name: remind_icon, size: 14 }
                        span { "{remind_label}" }
                    }
                } else {
                    button {
                        class: "btn sm soft",
                        title: "{no_consent}",
                        onclick: move |_| plan_call(cid, &product3, overdue),
                        Icon { name: "phone-call", size: 14 }
                        span { {t("common.call")} }
                    }
                }
                button {
                    class: "icon-btn sm bordered",
                    title: "{reserve_title}",
                    disabled: row.held.is_some(),
                    onclick: move |_| reserve(cid, pid, bid, price),
                    Icon { name: "package-check", size: 15 }
                }
                button {
                    class: call_cls,
                    title: "{call_title}",
                    onclick: move |_| plan_call(cid, &product2, overdue),
                    Icon { name: "phone-call", size: 15 }
                }
                button {
                    class: "icon-btn sm bordered",
                    title: "{snooze_title}",
                    onclick: move |_| snooze(cid, pid),
                    Icon { name: "alarm-clock", size: 15 }
                }
            }
        }
    }
}

const TG_BUTTON: &str = "flex: 1; text-align: center; padding: 8px 6px; border-radius: 10px; background: rgb(255 255 255 / .78); color: #2b79c2; font-size: 12.5px; font-weight: 650";

/// The refill reminder exactly as the customer reads it in Telegram, in their own language.
#[component]
fn TelegramPreview(row: Row) -> Element {
    let today = today();
    let (first, clang, company) = {
        let db = DB.read();
        let c = db.customer(row.r.customer_id);
        (c.map(|c| c.first_name.clone()).unwrap_or_default(), c.map(|c| c.lang).unwrap_or(Lang::Uz), db.settings.company_name.clone())
    };
    let when = fmt::due_in(row.r.due, today, clang);
    let product = row.product.clone();
    let branch = row.branch.clone();
    let uz_msg = format!("Assalomu alaykum, {first}! {product} {when} tugaydi. {company} {branch} filialida siz uchun qadoq tayyor. Bron qilib qo‘yaylikmi?");
    let (msg, b1, b2): (String, String, String) = match clang {
        Lang::Ru => (
            format!("Здравствуйте, {first}! {product} закончится {when}. В аптеке {company} ({branch}) для вас уже готова упаковка. Забронировать?"),
            "Забронировать".into(),
            "Доставить домой".into(),
        ),
        Lang::En => (
            format!("Hello {first}! Your {product} runs out {when}. A pack is waiting for you at {company} {branch}. Shall we hold it?"),
            "Hold it for me".into(),
            "Deliver it".into(),
        ),
        Lang::UzCyrl => (crm::i18n::to_cyrillic(&uz_msg), crm::i18n::to_cyrillic("Bron qilish"), crm::i18n::to_cyrillic("Uyga yetkazish")),
        Lang::Uz => (uz_msg.clone(), "Bron qilish".into(), "Uyga yetkazish".into()),
    };
    let lang_name = clang.native_name();
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "send", size: 16, class: "tone-info" } {t("refills.preview_title")} }
                span { class: "badge info", Icon { name: "languages", size: 12 } "{lang_name}" }
            }
            div { class: "card-body stack gap-12", style: "align-items: center",
                div { class: "phone-mock",
                    div { class: "phone-screen", style: "min-height: 360px",
                        div { class: "row gap-8", style: "padding-bottom: 10px; border-bottom: 1px solid rgb(0 0 0 / .07); color: #1c1916",
                            div { class: "brand-mark", style: "width: 30px; height: 30px; border-radius: 99px", Icon { name: "heart-pulse", size: 15 } }
                            div {
                                div { class: "small strong", "{company}" }
                                div { class: "xs", style: "opacity: .55", "Telegram bot" }
                            }
                        }
                        span { class: "spacer" }
                        div { class: "tg-bubble", "{msg}" }
                        div { class: "row gap-4", style: "width: 92%",
                            span { style: TG_BUTTON, "{b1}" }
                            span { style: TG_BUTTON, "{b2}" }
                        }
                    }
                }
                div { class: "xs muted center", style: "max-width: 340px", {t("refills.preview_hint")} }
            }
        }
    }
}

/// Telegram (or SMS) reminders for (customer, product) pairs; skips people without consent.
fn remind_many(pairs: &[(Id, Id)]) {
    if pairs.is_empty() {
        return;
    }
    let (mut tg, mut sms, mut skipped) = (0usize, 0usize, 0usize);
    mutate(|db| {
        let now = now();
        let me = db.settings.me;
        for (cid, pid) in pairs {
            let Some(c) = db.customer(*cid) else { continue };
            let channel = if c.consent.telegram {
                tg += 1;
                "Telegram"
            } else if c.consent.sms {
                sms += 1;
                "SMS"
            } else {
                skipped += 1;
                continue;
            };
            let product = db.product_name(Some(*pid));
            db.add_activity(Activity {
                id: 0,
                kind: ActivityKind::Message,
                title: format!("{product}: dori eslatmasi"),
                notes: String::new(),
                due: now,
                done: true,
                done_at: Some(now),
                owner_id: me,
                customer_id: Some(*cid),
                company_id: None,
                deal_id: None,
                ticket_id: None,
                priority: Priority::Normal,
                outcome: Some(channel.into()),
                duration_min: 1,
                daybook_task: None,
            });
        }
        if tg + sms > 0 {
            db.log(now, format!("Dori eslatmalari: Telegram {tg}, SMS {sms}"), false);
        }
    });
    if pairs.len() == 1 {
        if tg == 1 {
            toast(t("refills.toast_reminded"), "send", "success");
        } else if sms == 1 {
            toast(t("refills.toast_sms"), "message-square-text", "success");
        } else {
            toast(t("refills.toast_no_consent"), "phone-call", "warning");
        }
    } else {
        let mut text = t("refills.toast_bulk").replace("{n}", &(tg + sms).to_string());
        if skipped > 0 {
            text = format!("{text} · {}", t("refills.toast_bulk_skipped").replace("{n}", &skipped.to_string()));
        }
        toast(text, "send", if tg + sms > 0 { "success" } else { "warning" });
    }
}

/// Holds a pack at the customer's branch, or puts the medicine on the waitlist when it's out.
fn reserve(cid: Id, pid: Id, branch: Id, price: Money) {
    let mut in_stock = false;
    mutate(|db| {
        let now = now();
        let Some((name, stock)) = db.product(pid).map(|p| (p.name.clone(), p.stock_at(branch))) else { return };
        in_stock = stock > 0;
        let id = db.new_id();
        db.waitlist.insert(
            0,
            WaitItem {
                id,
                customer_id: cid,
                product_id: Some(pid),
                product_name: name.clone(),
                branch_id: branch,
                qty: 1,
                at: now,
                status: if in_stock { WaitStatus::Reserved } else { WaitStatus::Waiting },
                eta: if in_stock { None } else { Some(now.date() + Duration::days(3)) },
                note: "Dori radari".into(),
                notified_at: None,
                value: price,
            },
        );
        db.log(now, format!("Bron: {name}"), false);
    });
    if in_stock {
        toast(t("refills.toast_reserved"), "package-check", "success");
    } else {
        toast(t("refills.toast_waitlisted"), "hourglass", "warning");
    }
}

/// A call task for the call centre.
fn plan_call(cid: Id, product: &str, urgent: bool) {
    let mut agent_name = String::new();
    mutate(|db| {
        let now = now();
        let agent = db.staff.iter().find(|s| s.role == Role::CallAgent && s.active).map(|s| s.id).unwrap_or(db.settings.me);
        agent_name = db.staff_name(Some(agent));
        let name = db.customer_name(Some(cid));
        db.add_activity(Activity {
            id: 0,
            kind: ActivityKind::Call,
            title: format!("{name}: {product}"),
            notes: String::new(),
            due: now + Duration::minutes(30),
            done: false,
            done_at: None,
            owner_id: agent,
            customer_id: Some(cid),
            company_id: None,
            deal_id: None,
            ticket_id: None,
            priority: if urgent { Priority::High } else { Priority::Normal },
            outcome: None,
            duration_min: 5,
            daybook_task: None,
        });
    });
    toast(format!("{} · {agent_name}", t("refills.toast_call")), "phone-call", "success");
}

/// "Remind me again in 3 days": the pack now runs out three days from today (or later).
fn snooze(cid: Id, pid: Id) {
    mutate(|db| {
        let today = now().date();
        if let Some(c) = db.customer_mut(cid) {
            for g in c.regimens.iter_mut().filter(|g| g.product_id == pid) {
                let due = g.next_due().max(today) + Duration::days(3);
                g.last_bought = due - Duration::days(g.pack_days as i64);
            }
        }
    });
    toast(t("refills.toast_snoozed"), "alarm-clock", "");
}

pub const STRINGS: &[Entry] = &[
    ("refills.sub", "{n} ta mijoz · keyingi 14 kunda {v} savdo", "Клиентов: {n} · {v} продаж за 14 дней", "{n} customers · {v} of sales in the next 14 days"),
    ("refills.remind_due", "{n} kunda tugaydiganlarga eslatish", "Напомнить, у кого кончится за {n} дн.", "Remind everyone due in {n} days"),
    ("refills.kpi_today", "Bugun tugaydi", "Заканчивается сегодня", "Run out today"),
    ("refills.kpi_tomorrow_foot", "ertaga yana {n} ta", "завтра ещё {n}", "{n} more tomorrow"),
    ("refills.kpi_week", "7 kun ichida", "В ближайшие 7 дней", "Within 7 days"),
    ("refills.kpi_week_foot", "yana {n} ta 8–14 kunda", "ещё {n} через 8–14 дней", "{n} more in 8–14 days"),
    ("refills.kpi_overdue", "Dori tugab qolgan", "Лекарство закончилось", "Already ran out"),
    ("refills.kpi_overdue_foot", "oxirgi 14 kunda, hali olinmagan", "за 14 дней, ещё не купили", "in the last 14 days, not refilled"),
    ("refills.kpi_value", "Kutilayotgan savdo", "Ожидаемые продажи", "Upcoming refill sales"),
    ("refills.kpi_value_foot", "keyingi 14 kun", "ближайшие 14 дней", "next 14 days"),
    ("refills.kpi_reach", "Telegramda yetib boriladi", "Доступны в Telegram", "Reachable on Telegram"),
    ("refills.kpi_reach_foot", "{n} / {m} mijoz rozi", "{n} из {m} дали согласие", "{n} of {m} gave consent"),
    ("refills.strip_title", "Keyingi 14 kun", "Ближайшие 14 дней", "Next 14 days"),
    ("refills.strip_hint", "Kunni bosing: ro‘yxat shu kunga saralanadi", "Нажмите на день, чтобы отфильтровать список", "Tap a day to filter the list"),
    ("refills.all_days", "Barcha kunlar", "Все дни", "All days"),
    ("refills.reset_filters", "Filtrlarni tozalash", "Сбросить фильтры", "Clear filters"),
    ("refills.group.overdue", "Dori tugab qolgan", "Лекарство уже закончилось", "Already ran out"),
    ("refills.group.soon", "Bugun va ertaga", "Сегодня и завтра", "Today and tomorrow"),
    ("refills.group.week", "2–7 kun ichida", "Через 2–7 дней", "In 2–7 days"),
    ("refills.group.later", "Keyinroq, 14 kungacha", "Позже, до 14 дней", "Later, up to 14 days"),
    ("refills.remind_group", "Guruhga eslatish", "Напомнить группе", "Remind group"),
    ("refills.remind", "Eslatish", "Напомнить", "Remind"),
    ("refills.reminded", "Eslatildi", "Напомнили", "Reminded"),
    ("refills.reserve", "Qadoqni bron qilish", "Забронировать упаковку", "Reserve a pack"),
    ("refills.snooze", "3 kunga qoldirish", "Отложить на 3 дня", "Snooze for 3 days"),
    ("refills.in_stock", "Omborda bor", "В наличии", "In stock"),
    ("refills.out_stock", "Omborda yo‘q", "Нет в наличии", "Out of stock"),
    ("refills.last_call", "Oxirgi qo‘ng‘iroq", "Последний звонок", "Last call"),
    ("refills.no_calls", "Hali qo‘ng‘iroq qilinmagan", "Ещё не звонили", "Not called yet"),
    ("refills.held_reserved", "Bron qilingan", "Забронировано", "Reserved"),
    ("refills.held_waiting", "Defekturada", "В дефектуре", "On waitlist"),
    ("refills.call_planned", "Qo‘ng‘iroq rejalashtirilgan", "Звонок запланирован", "Call planned"),
    ("refills.toast_reminded", "Telegram eslatma yuborildi", "Напоминание отправлено в Telegram", "Telegram reminder sent"),
    ("refills.toast_sms", "SMS eslatma yuborildi", "Напоминание отправлено по SMS", "SMS reminder sent"),
    ("refills.toast_no_consent", "Xabar yuborishga rozilik yo‘q: qo‘ng‘iroq qiling", "Нет согласия на сообщения: лучше позвонить", "No consent for messages: call instead"),
    ("refills.toast_bulk", "Eslatmalar yuborildi: {n}", "Отправлено напоминаний: {n}", "Reminders sent: {n}"),
    ("refills.toast_bulk_skipped", "rozilik yo‘q: {n}", "без согласия: {n}", "no consent: {n}"),
    ("refills.toast_reserved", "Qadoq mijoz uchun bron qilindi", "Упаковка отложена для клиента", "A pack is reserved for the customer"),
    ("refills.toast_waitlisted", "Omborda yo‘q: defekturaga yozildi", "Нет в наличии: добавлено в дефектуру", "Out of stock: added to the waitlist"),
    ("refills.toast_call", "Qo‘ng‘iroq vazifasi yaratildi", "Задача на звонок создана", "Call task created"),
    ("refills.toast_snoozed", "3 kundan keyin yana eslatamiz", "Напомним снова через 3 дня", "We’ll bring it back in 3 days"),
    ("refills.adherence", "Davolanishga rioya", "Соблюдение терапии", "Adherence"),
    ("refills.on_time", "O‘z vaqtida", "Вовремя", "On time"),
    ("refills.late", "Kechikkan", "С опозданием", "Late"),
    ("refills.adherence_hint", "Dori tugaganidan keyin 2 kun ichida qayta olinganlar ulushi", "Доля курсов, продлённых не позже 2 дней после окончания", "Share of therapies refilled within 2 days of running out"),
    ("refills.reminded_today", "Bugun eslatilgan mijozlar", "Напомнили сегодня", "Reminded today"),
    ("refills.auto_note", "Avtomatlashtirish dori tugashidan {n} kun oldin Telegramda o‘zi eslatadi. Bu yerda esa qo‘lda nazorat qilasiz.", "Автоматизация сама напоминает в Telegram за {n} дн. до конца лекарства. Здесь вы контролируете вручную.", "An automation reminds on Telegram {n} days before a medicine runs out. The radar is for hands-on follow-up."),
    ("refills.open_automation", "Sozlash", "Настроить", "Set up"),
    ("refills.preview_title", "Mijozga boradigan xabar", "Что получит клиент", "What the customer receives"),
    ("refills.preview_hint", "Mijozning o‘z tilida: avtomatlashtirish yoki «Eslatish» tugmasi yuboradi", "На языке клиента: отправит автоматизация или кнопка «Напомнить»", "In the customer’s own language, sent by the automation or the Remind button"),
    ("refills.most_needed", "Eng ko‘p kerak bo‘ladigan dorilar", "Самые нужные лекарства", "Most needed medicines"),
    ("refills.packs", "qadoq", "уп.", "packs"),
    ("refills.packs_total", "Jami {n} qadoq · {v}", "Всего {n} уп. · {v}", "{n} packs in total · {v}"),
    ("refills.empty", "Bu filtrlar bo‘yicha hech kimning dorisi tugamayapti", "По этим фильтрам ни у кого не заканчиваются лекарства", "No one runs out of medicine with these filters"),
    ("refills.empty_text", "Boshqa kun, kasallik yoki filialni tanlang.", "Выберите другой день, заболевание или филиал.", "Pick another day, condition or branch."),
    ("refills.show_more", "Yana {n} ta ko‘rsatish", "Показать ещё {n}", "Show {n} more"),
];
