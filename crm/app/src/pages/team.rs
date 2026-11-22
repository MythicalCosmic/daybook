//! Team and goals. The team comes from Daybook (branches and staff sync in, "on shift" comes from
//! Daybook's Face ID attendance; simulated from opening hours in the demo) with this month's
//! numbers. Goals show branch and staff targets with pace, a leaderboard with medals and badges.

use std::collections::HashMap;

use chrono::{Datelike, NaiveDateTime, Timelike, Weekday};
use crm::analytics::{self, add_months, month_start, Leader};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use crm::Db;
use dioxus::prelude::*;

use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

fn parse_hours(s: &str) -> Option<(u32, u32)> {
    let mut it = s.split(['–', '-']);
    let a = it.next()?.trim();
    let b = it.next()?.trim();
    let h = |x: &str| x.split(':').next().and_then(|h| h.parse::<u32>().ok());
    Some((h(a)?, h(b)?))
}

/// Simulated attendance: Some(shift hours) when the person is at work now.
fn shift(db: &Db, s: &Staff, now: NaiveDateTime) -> (bool, String) {
    let hour = now.hour();
    let weekend = matches!(now.weekday(), Weekday::Sun);
    let office = !matches!(now.weekday(), Weekday::Sat | Weekday::Sun);
    let branch = s.branch_id.and_then(|b| db.branch(b));
    let (from, to, works) = match (s.role, branch) {
        (Role::Owner | Role::SalesRep | Role::Marketer, _) => (9, 18, office),
        (Role::CallAgent, _) => (8, 20, !weekend),
        (Role::Courier, _) => (10, 20, !weekend),
        (Role::Manager, _) => (9, 18, !weekend),
        (_, Some(b)) if b.open_hours.contains("24") => (0, 24, true),
        (_, Some(b)) => parse_hours(&b.open_hours).map(|(a, z)| (a, z, true)).unwrap_or((9, 18, true)),
        _ => (9, 18, office),
    };
    let on = works && hour >= from && hour < to;
    let hours = if (from, to) == (0, 24) { "24/7".to_string() } else { format!("{from:02}:00–{to:02}:00") };
    (on, hours)
}

#[derive(Clone, Debug, PartialEq)]
struct Member {
    id: Id,
    name: String,
    hue: u16,
    role: Role,
    branch: Option<Id>,
    branch_name: String,
    phone: String,
    telegram: String,
    on: bool,
    hours: String,
    lead: Option<Leader>,
    open_tasks: usize,
}

// ---------------------------------------------------------------- team

#[component]
pub fn Team() -> Element {
    let mut branch = use_signal(|| 0u32);
    let mut role = use_signal(String::new);
    let mut query = use_signal(String::new);
    let data = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let board: HashMap<Id, Leader> = analytics::leaderboard(&db, now.date()).into_iter().map(|l| (l.staff_id, l)).collect();
        db.staff
            .iter()
            .filter(|s| s.active)
            .map(|s| {
                let (on, hours) = shift(&db, s, now);
                Member {
                    id: s.id,
                    name: s.name.clone(),
                    hue: s.hue,
                    role: s.role,
                    branch: s.branch_id,
                    branch_name: db.branch_name(s.branch_id),
                    phone: s.phone.clone(),
                    telegram: s.telegram.clone(),
                    on,
                    hours,
                    lead: board.get(&s.id).cloned(),
                    open_tasks: db.activities.iter().filter(|a| !a.done && a.owner_id == s.id).count(),
                }
            })
            .collect::<Vec<_>>()
    });
    let all = data();
    let l = lang();
    let branches: Vec<(Id, String, usize)> = {
        let db = DB.read();
        db.branches.iter().map(|b| (b.id, b.name.clone(), all.iter().filter(|m| m.branch == Some(b.id)).count())).collect()
    };
    let (connected, last_sync) = {
        let db = DB.read();
        (db.settings.daybook.connected, db.settings.daybook.last_sync)
    };
    let q = query().trim().to_lowercase();
    let shown: Vec<Member> = all
        .iter()
        .filter(|m| branch() == 0 || m.branch == Some(branch()))
        .filter(|m| role().is_empty() || m.role.slug() == role())
        .filter(|m| q.is_empty() || m.name.to_lowercase().contains(&q) || m.telegram.to_lowercase().contains(&q))
        .cloned()
        .collect();
    let on_shift = all.iter().filter(|m| m.on).count();
    let subtitle = match l {
        Lang::Ru => format!("{} сотрудников · {} филиалов · на смене: {}", all.len(), branches.len(), on_shift),
        Lang::En => format!("{} people · {} branches · {} on shift", all.len(), branches.len(), on_shift),
        _ => uz(format!("{} xodim · {} filial · {} kishi smenada", all.len(), branches.len(), on_shift)),
    };
    let sync_text = if connected {
        format!("{} · {}", t("team.sync_live"), last_sync.map(|s| fmt::relative(s, now(), l)).unwrap_or_default())
    } else {
        t("team.sync_demo")
    };
    let cur_branch = branch();
    let total = all.len();
    let roles: Vec<Role> = Role::ALL.iter().copied().filter(|r| all.iter().any(|m| m.role == *r)).collect();
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.team"), subtitle,
                Link { to: Route::Goals {}, class: "btn", Icon { name: "trophy", size: 16 } span { class: "label-text", {t("nav.goals")} } }
                button {
                    class: "btn primary",
                    onclick: move |_| {
                        let now = crate::state::now();
                        mutate(|db| {
                            db.settings.daybook.pulled.staff = db.staff.len() as u32;
                            db.settings.daybook.pulled.branches = db.branches.len() as u32;
                            db.log(now, "Daybook: jamoa sinxronlandi", false);
                        });
                        toast(t("team.synced"), "refresh-cw", "success");
                    },
                    Icon { name: "refresh-cw", size: 16 }
                    span { class: "label-text", {t("team.sync")} }
                }
            }
            div { class: "callout",
                Icon { name: "fingerprint", size: 18 }
                div { class: "stack", style: "gap: 2px",
                    span { class: "strong", {t("team.sync_title")} }
                    span { "{sync_text}" }
                }
            }
            div { class: "toolbar",
                div { class: "chips grow",
                    button { class: if cur_branch == 0 { "chip on" } else { "chip" }, onclick: move |_| branch.set(0), {t("common.all_branches")} span { class: "count", "{total}" } }
                    for (bid, bname, n) in branches {
                        button { key: "{bid}", class: if cur_branch == bid { "chip on" } else { "chip" }, onclick: move |_| branch.set(bid), Icon { name: "store", size: 13 } "{bname}" span { class: "count", "{n}" } }
                    }
                }
                select { class: "select", style: "width: auto", onchange: move |e| role.set(e.value()),
                    option { value: "", selected: role().is_empty(), {t("team.all_roles")} }
                    for r in roles {
                        option { key: "{r.slug()}", value: "{r.slug()}", selected: role() == r.slug(), {t(r.key())} }
                    }
                }
                div { class: "search",
                    Icon { name: "search", size: 16 }
                    input { class: "input", value: "{query}", placeholder: t("team.search"), oninput: move |e| query.set(e.value()) }
                }
            }
            if shown.is_empty() {
                div { class: "card", Empty { icon: "users-round", title: t("common.no_results"), text: t("team.empty_text") } }
            }
            div { class: "grid-3",
                for m in shown {
                    MemberCard { key: "{m.id}", m: m.clone() }
                }
            }
        }
    }
}

#[component]
fn MemberCard(m: Member) -> Element {
    let role = t(m.role.key());
    let sub = if m.branch.is_some() { format!("{role} · {}", m.branch_name) } else { role.clone() };
    let phone_text = phone(&m.phone);
    let shift_label = if m.on { format!("{} · {}", t("team.on_shift"), m.hours) } else { format!("{} · {}", t("team.off_shift"), m.hours) };
    let shift_tone: &'static str = if m.on { "success" } else { "" };
    let stats: Vec<(String, String)> = match &m.lead {
        Some(ld) => vec![
            (t("metric.calls"), fmt::num(ld.calls as i64)),
            (t("team.won"), if ld.won_value > 0 { money_short(ld.won_value) } else { fmt::num(ld.won_count as i64) }),
            (t("team.new_customers"), fmt::num(ld.customers as i64)),
        ],
        None => vec![(t("team.tasks_open"), fmt::num(m.open_tasks as i64)), (t("team.branches"), fmt::num(DB.read().branches.len() as i64)), (t("team.role"), role.clone())],
    };
    let tasks = format!("{} {}", m.open_tasks, t("team.open_tasks_lc"));
    let name = m.name.clone();
    let name2 = m.name.clone();
    let tg = m.telegram.clone();
    let tg_text = m.telegram.clone();
    rsx! {
        div { class: "card pad stack gap-16",
            div { class: "row gap-12",
                Avatar { name: name.clone(), hue: Some(m.hue), size: "lg", online: m.on }
                div { class: "grow stack", style: "gap: 2px",
                    span { class: "strong truncate", "{name}" }
                    span { class: "xs muted truncate", "{sub}" }
                }
            }
            div { class: "row wrap gap-8",
                Badge { text: shift_label, tone: shift_tone, dot: true }
                span { class: "badge", Icon { name: "fingerprint", size: 12 } "Face ID" }
            }
            div { class: "stack gap-4 small",
                span { class: "row gap-8 muted num", Icon { name: "phone", size: 14 } "{phone_text}" }
                span { class: "row gap-8 muted", Icon { name: "send", size: 14 } "{tg_text}" }
            }
            div { class: "row", style: "gap: 8px; align-items: stretch",
                for (label, value) in stats {
                    div { key: "{label}", class: "grow stack", style: "gap: 2px; background: var(--c-surface-2); border-radius: 10px; padding: 8px 10px; min-width: 0",
                        span { class: "strong num small truncate", "{value}" }
                        span { class: "xs muted truncate", "{label}" }
                    }
                }
            }
            div { class: "row between",
                button { class: "btn ghost sm", onclick: move |_| go("/tasks"), Icon { name: "list-todo", size: 14 } "{tasks}" }
                div { class: "row gap-4",
                    button { class: "icon-btn sm bordered", title: t("common.call"), onclick: move |_| toast(format!("{} · {}", t("common.call"), name2), "phone-call", ""), Icon { name: "phone", size: 15 } }
                    button { class: "icon-btn sm bordered", title: t("common.write"), onclick: move |_| toast(format!("Telegram · {}", tg), "send", ""), Icon { name: "send", size: 15 } }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- goals

#[derive(Clone, Debug, PartialEq)]
struct GoalView {
    id: Id,
    title: String,
    hue: u16,
    staff: bool,
    metric: Metric,
    actual: i64,
    target: i64,
}

fn metric_value(m: Metric, v: i64, l: Lang) -> String {
    match m {
        Metric::Revenue | Metric::DealsWon => crm::fmt::money_short(v, l),
        Metric::Retention => fmt::pct(v as f64, l),
        _ => fmt::num(v),
    }
}

#[component]
pub fn Goals() -> Element {
    let mut modal = use_signal(|| false);
    let today = today();
    let l = lang();
    let m0 = month_start(today);
    let days_in = (add_months(m0, 1) - m0).num_days() as f64;
    let elapsed = (today.day() as f64 / days_in).clamp(0.01, 1.0);
    let data = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let month = fmt::month_key(today);
        let mut v: Vec<GoalView> = db
            .goals
            .iter()
            .filter(|g| g.month == month)
            .map(|g| {
                let (actual, target) = analytics::goal_progress(&db, g, today);
                let (title, hue, staff) = match (g.staff_id.and_then(|s| db.staff_member(s)), g.branch_id.and_then(|b| db.branch(b))) {
                    (Some(s), _) => (s.name.clone(), s.hue, true),
                    (None, Some(b)) => (b.name.clone(), b.hue, false),
                    _ => (db.settings.company_name.clone(), 24, false),
                };
                GoalView { id: g.id, title, hue, staff, metric: g.metric, actual, target }
            })
            .collect();
        v.sort_by(|a, b| (b.actual as f64 / b.target.max(1) as f64).partial_cmp(&(a.actual as f64 / a.target.max(1) as f64)).unwrap_or(std::cmp::Ordering::Equal));
        v
    });
    let board = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let m0 = month_start(today);
        let rows = analytics::leaderboard(&db, today);
        // badges: refill calls, replies in the inbox, biggest wins, new customers
        let mut refill: HashMap<Id, u32> = HashMap::new();
        for a in db.activities.iter().filter(|a| a.done && a.kind == ActivityKind::Call && a.customer_id.is_some() && a.done_at.map_or(false, |d| d.date() >= m0)) {
            *refill.entry(a.owner_id).or_default() += 1;
        }
        let mut replies: HashMap<Id, u32> = HashMap::new();
        for c in &db.conversations {
            for m in c.messages.iter().filter(|m| !m.inbound && m.kind == MsgKind::Text) {
                if let Some(a) = m.author_id {
                    *replies.entry(a).or_default() += 1;
                }
            }
        }
        let top = |map: &HashMap<Id, u32>| map.iter().max_by_key(|(id, n)| (**n, std::cmp::Reverse(**id))).filter(|(_, n)| **n > 0).map(|(id, _)| *id);
        let refill_hero = top(&refill);
        let fast = top(&replies);
        let closer = rows.iter().filter(|r| r.won_value > 0).max_by_key(|r| r.won_value).map(|r| r.staff_id);
        let magnet = rows.iter().filter(|r| r.customers > 0).max_by_key(|r| r.customers).map(|r| r.staff_id);
        rows.into_iter()
            .map(|r| {
                let s = db.staff_member(r.staff_id);
                let mut badges: Vec<(&'static str, &'static str, &'static str)> = Vec::new();
                if refill_hero == Some(r.staff_id) {
                    badges.push(("team.badge_refill", "repeat", "accent"));
                }
                if fast == Some(r.staff_id) {
                    badges.push(("team.badge_fast", "zap", "info"));
                }
                if closer == Some(r.staff_id) {
                    badges.push(("team.badge_closer", "handshake", "success"));
                }
                if magnet == Some(r.staff_id) {
                    badges.push(("team.badge_magnet", "magnet", "warning"));
                }
                let role = s.map(|s| s.role).unwrap_or(Role::Pharmacist);
                (r, s.map(|s| s.name.clone()).unwrap_or_default(), s.map(|s| s.hue).unwrap_or(24), role, badges)
            })
            .collect::<Vec<_>>()
    });
    let goals = data();
    let branch_goals: Vec<GoalView> = goals.iter().filter(|g| !g.staff).cloned().collect();
    let staff_goals: Vec<GoalView> = goals.iter().filter(|g| g.staff).cloned().collect();
    let on_track = goals.iter().filter(|g| g.actual as f64 / g.target.max(1) as f64 >= elapsed - 0.05).count();
    let month_name = fmt::month_name(today.month(), l);
    let left = (add_months(m0, 1) - today).num_days() - 1;
    let subtitle = match l {
        Lang::Ru => format!("{month_name} · осталось {} · в графике {} из {}", fmt::days(left, l), on_track, goals.len()),
        Lang::En => format!("{month_name} · {} left · {} of {} on track", fmt::days(left, l), on_track, goals.len()),
        _ => uz(format!("{month_name} · {} qoldi · {} tadan {} tasi rejada", fmt::days(left, Lang::Uz), goals.len(), on_track)),
    };
    let pace_pct = fmt::pct(elapsed * 100.0, l);
    let pace_line = t("team.pace_line").replace("{p}", &pace_pct);
    let rows = board();
    let max = rows.iter().map(|r| r.0.score).max().unwrap_or(1).max(1) as f64;
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.goals"), subtitle,
                Link { to: Route::Team {}, class: "btn", Icon { name: "users-round", size: 16 } span { class: "label-text", {t("nav.team")} } }
                button { class: "btn primary", onclick: move |_| modal.set(true), Icon { name: "plus", size: 16 } span { class: "label-text", {t("team.new_goal")} } }
            }
            div { class: "card pad row gap-16 wrap",
                IconTile { icon: "calendar-clock", tone: "info" }
                div { class: "grow stack", style: "gap: 6px; min-width: 220px",
                    div { class: "row between", span { class: "strong", "{pace_line}" } span { class: "small muted num", "{pace_pct}" } }
                    Progress { pct: elapsed * 100.0, tone: "", thin: true }
                }
            }
            if goals.is_empty() {
                div { class: "card", Empty { icon: "target", title: t("team.no_goals"), text: t("team.no_goals_text"),
                    button { class: "btn primary", onclick: move |_| modal.set(true), Icon { name: "plus", size: 16 } {t("team.new_goal")} }
                } }
            }
            if !branch_goals.is_empty() {
                div { class: "section-head", div { class: "section-title", {t("team.branch_goals")} } }
                div { class: "grid-3",
                    for g in branch_goals {
                        GoalCard { key: "{g.id}", g: g.clone(), elapsed }
                    }
                }
            }
            if !staff_goals.is_empty() {
                div { class: "section-head", div { class: "section-title", {t("team.staff_goals")} } }
                div { class: "grid-3",
                    for g in staff_goals {
                        GoalCard { key: "{g.id}", g: g.clone(), elapsed }
                    }
                }
            }
            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "trophy", size: 16, class: "tone-warning" } {t("team.leaderboard")} }
                    span { class: "small muted", {t("team.leaderboard_hint")} }
                }
                div { class: "list", style: "margin-top: 8px",
                    for (i, (r, name, hue, role, badges)) in rows.into_iter().enumerate() {
                        {
                            let rank = i + 1;
                            let medal: &'static str = match rank {
                                1 => "tier gold",
                                2 => "tier silver",
                                3 => "tier bronze",
                                _ => "badge",
                            };
                            let role_label = t(role.key());
                            let pct = r.score as f64 / max * 100.0;
                            let won = if r.won_value > 0 { money_short(r.won_value) } else { "—".to_string() };
                            let line = format!("{} · {} {} · {} {}", role_label, r.calls, t("team.calls_lc"), r.customers, t("team.customers_lc"));
                            rsx! {
                                div { key: "{r.staff_id}", class: "list-row",
                                    span { class: "{medal}", style: "min-width: 38px; justify-content: center",
                                        if rank <= 3 { Icon { name: "medal", size: 12 } }
                                        "{rank}"
                                    }
                                    Avatar { name: name.clone(), hue: Some(hue) }
                                    div { class: "meta",
                                        div { class: "row gap-8 wrap",
                                            span { class: "title", "{name}" }
                                            for (key, icon, tone) in badges {
                                                Badge { key: "{key}", text: t(key), tone, icon: Some(icon) }
                                            }
                                        }
                                        span { class: "sub truncate", "{line}" }
                                    }
                                    div { class: "stack hide-mobile", style: "gap: 4px; width: 160px",
                                        div { class: "row between xs", span { class: "muted", {t("team.won")} } span { class: "strong num", "{won}" } }
                                        Progress { pct, thin: true }
                                    }
                                    div { class: "stack", style: "gap: 0; align-items: flex-end; min-width: 52px",
                                        span { class: "strong num", style: "font-size: 18px", "{r.score}" }
                                        span { class: "xs muted", {t("team.points")} }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        // Outside .page: its entry animation would pin the modal to the page box.
        if modal() {
            NewGoal { onclose: move |_| modal.set(false) }
        }
    }
}

#[component]
fn GoalCard(g: GoalView, elapsed: f64) -> Element {
    let l = lang();
    let id = g.id;
    let ratio = g.actual as f64 / g.target.max(1) as f64;
    let pct = (ratio * 100.0).round();
    let (pace_key, tone, color): (&str, &'static str, &'static str) = if ratio >= 1.0 {
        ("team.done", "accent", "var(--c-primary)")
    } else if ratio >= elapsed - 0.05 {
        ("team.on_track", "success", "var(--c-success)")
    } else {
        ("team.behind", "warning", "var(--c-warning)")
    };
    let forecast = (g.actual as f64 / elapsed) as i64;
    let forecast_text = format!("{} {}", t("team.forecast"), metric_value(g.metric, forecast, l));
    let actual = metric_value(g.metric, g.actual, l);
    let target = format!("/ {}", metric_value(g.metric, g.target, l));
    let metric = t(g.metric.key());
    let title = g.title.clone();
    rsx! {
        div { class: "card pad stack gap-16",
            div { class: "row gap-12",
                if g.staff {
                    Avatar { name: title.clone(), hue: Some(g.hue) }
                } else {
                    IconTile { icon: "store", tone: "accent", size: "sm" }
                }
                div { class: "grow stack", style: "gap: 0",
                    span { class: "strong truncate", "{title}" }
                    span { class: "xs muted", "{metric}" }
                }
                button {
                    class: "icon-btn sm",
                    title: t("common.delete"),
                    onclick: move |_| {
                        mutate(|db| db.goals.retain(|x| x.id != id));
                        toast(t("team.goal_deleted"), "trash-2", "");
                    },
                    Icon { name: "x", size: 15 }
                }
            }
            div { class: "row gap-16",
                Ring { pct: pct.min(100.0), size: 78, stroke: 8, color,
                    span { class: "strong num", style: "font-size: 15px", "{pct:.0}%" }
                }
                div { class: "grow stack", style: "gap: 6px; min-width: 0",
                    div { class: "row gap-4", style: "align-items: baseline; flex-wrap: wrap",
                        span { class: "strong num", style: "font-size: 18px", "{actual}" }
                        span { class: "small muted num", "{target}" }
                    }
                    div { Badge { text: t(pace_key), tone, dot: true } }
                    span { class: "xs muted", "{forecast_text}" }
                }
            }
        }
    }
}

#[component]
fn NewGoal(onclose: EventHandler<()>) -> Element {
    let mut metric = use_signal(|| Metric::Revenue);
    let mut scope = use_signal(|| "branch".to_string());
    let mut branch = use_signal(|| DB.peek().branches.first().map(|b| b.id).unwrap_or(0));
    let mut staff = use_signal(|| DB.peek().staff.iter().find(|s| s.role == Role::Pharmacist).map(|s| s.id).unwrap_or(0));
    let mut target = use_signal(|| "60000000".to_string());
    let (branches, people) = {
        let db = DB.read();
        (
            db.branches.iter().map(|b| (b.id, b.name.clone())).collect::<Vec<_>>(),
            db.staff.iter().filter(|s| s.active && s.role != Role::Owner).map(|s| (s.id, s.name.clone())).collect::<Vec<_>>(),
        )
    };
    let value: i64 = target().chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0);
    let valid = value > 0;
    let preview = metric_value(metric(), value, lang());
    let is_branch = scope() == "branch";
    rsx! {
        Modal { title: t("team.new_goal"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("team.metric")} }
                    select {
                        class: "select",
                        onchange: move |e| {
                            let m = Metric::from_slug(&e.value()).unwrap_or(Metric::Revenue);
                            metric.set(m);
                            target.set(match m {
                                Metric::Revenue => "60000000",
                                Metric::DealsWon => "150000000",
                                Metric::NewCustomers => "15",
                                Metric::Calls => "100",
                                Metric::Retention => "60",
                            }.to_string());
                            if matches!(m, Metric::DealsWon | Metric::Calls) {
                                scope.set("staff".to_string());
                            }
                        },
                        for m in Metric::ALL.iter().copied() {
                            option { key: "{m.slug()}", value: "{m.slug()}", selected: m == metric(), {t(m.key())} }
                        }
                    }
                }
                div { class: "row",
                    Segmented {
                        options: vec![("branch".to_string(), t("common.branch")), ("staff".to_string(), t("team.employee"))],
                        value: scope(),
                        onchange: move |v: String| scope.set(v),
                    }
                }
                if is_branch {
                    div { class: "field",
                        label { class: "label", {t("common.branch")} }
                        select { class: "select", onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                            for (id, name) in branches {
                                option { key: "{id}", value: "{id}", selected: id == branch(), "{name}" }
                            }
                        }
                    }
                } else {
                    div { class: "field",
                        label { class: "label", {t("team.employee")} }
                        select { class: "select", onchange: move |e| staff.set(e.value().parse().unwrap_or(0)),
                            for (id, name) in people {
                                option { key: "{id}", value: "{id}", selected: id == staff(), "{name}" }
                            }
                        }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("team.target")} }
                    input { class: "input num", inputmode: "numeric", value: "{target}", oninput: move |e| target.set(e.value()) }
                    span { class: "hint", "{preview}" }
                }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button {
                    class: "btn primary",
                    disabled: !valid,
                    onclick: move |_| {
                        let month = fmt::month_key(crate::state::today());
                        let (m, b, s) = (metric(), scope() == "branch", (branch(), staff()));
                        mutate(|db| {
                            let id = db.new_id();
                            db.goals.push(Goal {
                                id,
                                staff_id: if b { None } else { Some(s.1) },
                                branch_id: if b { Some(s.0) } else { None },
                                metric: m,
                                target: value,
                                month,
                            });
                        });
                        toast(t("team.goal_saved"), "target", "success");
                        onclose.call(());
                    },
                    Icon { name: "check", size: 16 }
                    {t("common.save")}
                }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("team.sync", "Daybook’dan yangilash", "Обновить из Daybook", "Sync from Daybook"),
    ("team.synced", "Jamoa Daybook bilan sinxronlandi", "Команда синхронизирована с Daybook", "Team synced with Daybook"),
    ("team.sync_title", "Jamoa va smenalar Daybook’dan keladi", "Команда и смены приходят из Daybook", "The team and shifts come from Daybook"),
    ("team.sync_live", "Face ID davomati jonli", "Учёт Face ID в реальном времени", "Face ID attendance is live"),
    (
        "team.sync_demo",
        "Xodimlar, filiallar va Face ID davomati ulanishdan keyin avtomatik keladi. Demoda smena filial ish vaqtidan hisoblanadi.",
        "Сотрудники, филиалы и учёт Face ID подтянутся после подключения. В демо смена считается по часам работы филиала.",
        "Staff, branches and Face ID attendance arrive once connected. In the demo, shifts follow branch opening hours.",
    ),
    ("team.all_roles", "Barcha lavozimlar", "Все должности", "All roles"),
    ("team.search", "Ism yoki Telegram…", "Имя или Telegram…", "Name or Telegram…"),
    ("team.empty_text", "Boshqa filial yoki lavozimni tanlang.", "Выберите другой филиал или должность.", "Pick another branch or role."),
    ("team.on_shift", "Smenada", "На смене", "On shift"),
    ("team.off_shift", "Smenada emas", "Не на смене", "Off shift"),
    ("team.won", "Yutilgan", "Выиграно", "Won"),
    ("team.new_customers", "Yangi mijoz", "Новые клиенты", "New customers"),
    ("team.tasks_open", "Ochiq vazifa", "Открытые задачи", "Open tasks"),
    ("team.branches", "Filiallar", "Филиалы", "Branches"),
    ("team.role", "Lavozim", "Должность", "Role"),
    ("team.open_tasks_lc", "ta ochiq vazifa", "открытых задач", "open tasks"),
    ("team.new_goal", "Yangi maqsad", "Новая цель", "New goal"),
    (
        "team.pace_line",
        "Oyning {p} qismi o‘tdi: rejada bo‘lish uchun maqsad kamida {p} bajarilgan bo‘lishi kerak",
        "Прошло {p} месяца: чтобы идти по плану, цель должна быть выполнена хотя бы на {p}",
        "{p} of the month is gone: to be on track, a goal should be at least {p} done",
    ),
    ("team.no_goals", "Bu oy uchun maqsad yo‘q", "Целей на этот месяц нет", "No goals for this month"),
    ("team.no_goals_text", "Filial tushumi yoki xodim natijasi uchun maqsad qo‘ying.", "Поставьте цель по выручке филиала или результату сотрудника.", "Set a goal for branch revenue or a person’s results."),
    ("team.branch_goals", "Filiallar maqsadlari", "Цели филиалов", "Branch goals"),
    ("team.staff_goals", "Xodimlar maqsadlari", "Цели сотрудников", "Staff goals"),
    ("team.done", "Bajarildi", "Выполнено", "Achieved"),
    ("team.on_track", "Rejada", "В графике", "On track"),
    ("team.behind", "Ortda qolmoqda", "Отстаёт", "Behind"),
    ("team.forecast", "Oy oxiriga prognoz:", "Прогноз на конец месяца:", "Month-end forecast:"),
    ("team.goal_deleted", "Maqsad o‘chirildi", "Цель удалена", "Goal deleted"),
    ("team.goal_saved", "Maqsad qo‘shildi", "Цель добавлена", "Goal added"),
    ("team.leaderboard", "Reyting", "Рейтинг", "Leaderboard"),
    ("team.leaderboard_hint", "shu oy: bitimlar, qo‘ng‘iroqlar, vazifalar, yangi mijozlar", "за месяц: сделки, звонки, задачи, новые клиенты", "this month: deals, calls, tasks, new customers"),
    ("team.badge_refill", "Dori radari qahramoni", "Герой напоминаний", "Refill hero"),
    ("team.badge_fast", "Tezkor javob", "Быстрый ответ", "Fast responder"),
    ("team.badge_closer", "Bitim ustasi", "Мастер сделок", "Deal closer"),
    ("team.badge_magnet", "Mijozlar magniti", "Магнит клиентов", "Customer magnet"),
    ("team.calls_lc", "qo‘ng‘iroq", "звонков", "calls"),
    ("team.customers_lc", "yangi mijoz", "новых клиентов", "new customers"),
    ("team.points", "ball", "баллов", "points"),
    ("team.metric", "Ko‘rsatkich", "Показатель", "Metric"),
    ("team.employee", "Xodim", "Сотрудник", "Employee"),
    ("team.target", "Maqsad", "Цель", "Target"),
];
