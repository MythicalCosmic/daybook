//! Tickets: complaints, returns, quality issues and adverse reactions with SLA timers.
//! A ticket about a product knows who else bought the same product lately (batch recall),
//! and adverse reactions get a pharmacovigilance form with the 4-hour rule.

use std::collections::HashMap;

use chrono::{Duration, NaiveDateTime};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

/// "35 min", "5 h", "3 d" in the interface language.
fn dur(mins: i64, l: Lang) -> String {
    let m = mins.abs();
    if m < 60 {
        match l {
            Lang::Ru => format!("{m} мин"),
            Lang::En => format!("{m} min"),
            _ => uz(format!("{m} daqiqa")),
        }
    } else if m < 48 * 60 {
        let h = m / 60;
        match l {
            Lang::Ru => format!("{h} ч"),
            Lang::En => format!("{h} h"),
            _ => uz(format!("{h} soat")),
        }
    } else {
        let d = m / 1440;
        match l {
            Lang::Ru => format!("{d} дн."),
            Lang::En => format!("{d} d"),
            _ => uz(format!("{d} kun")),
        }
    }
}

/// SLA text and tone for a ticket.
fn sla(tk: &Ticket, now: NaiveDateTime, l: Lang) -> (String, &'static str, &'static str) {
    if tk.is_open() {
        let mins = (tk.due - now).num_minutes();
        if mins < 0 {
            (t("tickets.sla_breached").replace("{t}", &dur(mins, l)), "danger", "triangle-alert")
        } else {
            (t("tickets.sla_left").replace("{t}", &dur(mins, l)), if mins < 120 { "warning" } else { "" }, "timer")
        }
    } else if let Some(r) = tk.resolved {
        (t("tickets.sla_resolved").replace("{t}", &dur((r - tk.created).num_minutes(), l)), "success", "circle-check")
    } else {
        (t(tk.status.key()), "", "circle-check")
    }
}

fn status_tone(s: TicketStatus) -> &'static str {
    match s {
        TicketStatus::New => "accent",
        TicketStatus::InProgress => "info",
        TicketStatus::Waiting => "warning",
        TicketStatus::Resolved => "success",
        TicketStatus::Closed => "",
    }
}

fn priority_tone(p: Priority) -> &'static str {
    match p {
        Priority::Urgent => "danger",
        Priority::High => "warning",
        Priority::Normal => "",
        Priority::Low => "outline",
    }
}

#[derive(Clone, PartialEq)]
struct Row {
    tk: Ticket,
    customer: String,
    branch: String,
    assignee: String,
    assignee_hue: u16,
}

#[component]
pub fn Tickets() -> Element {
    let l = lang();
    let now = now();
    let rows = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let mut v: Vec<Row> = db
            .tickets
            .iter()
            .map(|tk| {
                let s = tk.assigned_to.and_then(|a| db.staff_member(a));
                Row {
                    tk: tk.clone(),
                    customer: db.customer_name(tk.customer_id),
                    branch: db.branch_name(tk.branch_id),
                    assignee: s.map(|s| s.name.clone()).unwrap_or_default(),
                    assignee_hue: s.map(|s| s.hue).unwrap_or(24),
                }
            })
            .collect();
        // breached first, then open by deadline, then the rest newest first
        v.sort_by(|a, b| {
            let ka = (!a.tk.breached(now), !a.tk.is_open());
            let kb = (!b.tk.breached(now), !b.tk.is_open());
            ka.cmp(&kb).then_with(|| if a.tk.is_open() { a.tk.due.cmp(&b.tk.due) } else { b.tk.created.cmp(&a.tk.created) })
        });
        v
    });
    let mut kind = use_signal(|| None::<TicketKind>);
    let mut status = use_signal(|| "open".to_string());
    let mut prio = use_signal(|| "all".to_string());
    let mut q = use_signal(String::new);

    let all = rows();
    let open = all.iter().filter(|r| r.tk.is_open()).count();
    let breached = all.iter().filter(|r| r.tk.breached(now)).count();
    let resolved: Vec<i64> = all.iter().filter_map(|r| r.tk.resolved.map(|x| (x - r.tk.created).num_minutes())).collect();
    let avg_res = if resolved.is_empty() { 0 } else { resolved.iter().sum::<i64>() / resolved.len() as i64 };
    let csats: Vec<u8> = all.iter().filter_map(|r| r.tk.csat).collect();
    let csat = if csats.is_empty() { 0.0 } else { csats.iter().map(|x| *x as f64).sum::<f64>() / csats.len() as f64 };
    let csat_text = if l == Lang::En { format!("{csat:.1} / 5") } else { format!("{csat:.1} / 5").replace('.', ",") };
    let adverse_open = all.iter().filter(|r| r.tk.is_open() && r.tk.kind == TicketKind::AdverseReaction).count();
    let breached_foot = if adverse_open > 0 {
        t("tickets.adverse_open").replace("{n}", &fmt::plural(adverse_open as i64, l, "ta nojo‘ya ta’sir|реакция|реакции|реакций|adverse reaction|adverse reactions"))
    } else { t("tickets.breached_foot") };

    let ql = q().trim().to_lowercase();
    let base: Vec<&Row> = all
        .iter()
        .filter(|r| match status().as_str() {
            "all" => true,
            "open" => r.tk.is_open(),
            s => r.tk.status.slug() == s,
        })
        .filter(|r| prio() == "all" || r.tk.priority.slug() == prio())
        .filter(|r| ql.is_empty() || r.tk.subject.to_lowercase().contains(&ql) || r.tk.number.to_lowercase().contains(&ql) || r.customer.to_lowercase().contains(&ql))
        .collect();
    let kind_counts: Vec<(TicketKind, usize)> =
        TicketKind::ALL.iter().map(|k| (*k, base.iter().filter(|r| r.tk.kind == *k).count())).filter(|x| x.1 > 0).collect();
    let shown: Vec<Row> = base.iter().filter(|r| kind().map_or(true, |k| r.tk.kind == k)).map(|r| (*r).clone()).collect();
    let avg_text = dur(avg_res, l);

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.tickets"), subtitle: t("tickets.sub"),
                button { class: "btn primary", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Ticket),
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("palette.new_ticket")} }
                }
            }

            div { class: "grid-4",
                Kpi { label: t("tickets.kpi_open"), value: fmt::num(open as i64), icon: "life-buoy", foot: t("tickets.kpi_open_foot") }
                Kpi { label: t("tickets.kpi_breached"), value: fmt::num(breached as i64), icon: "triangle-alert", tone: "danger", foot: breached_foot,
                    onclick: move |_| status.set("open".into()),
                }
                Kpi { label: t("tickets.kpi_resolution"), value: avg_text, icon: "timer", tone: "info", foot: t("tickets.kpi_resolution_foot") }
                Kpi { label: t("tickets.kpi_csat"), value: csat_text, icon: "star", tone: "success", foot: fmt::plural(csats.len() as i64, l, "ta baho|оценка|оценки|оценок|rating|ratings") }
            }

            div { class: "toolbar",
                div { class: "search",
                    Icon { name: "search", size: 16 }
                    input { class: "input", value: "{q}", placeholder: t("tickets.search"), oninput: move |e| q.set(e.value()) }
                }
                select { class: "select", style: "width: auto; min-width: 160px", onchange: move |e| status.set(e.value()),
                    option { value: "open", selected: status() == "open", {t("tickets.only_open")} }
                    option { value: "all", selected: status() == "all", {t("tickets.all_statuses")} }
                    for s in TicketStatus::ALL.iter().copied() {
                        option { key: "{s.slug()}", value: "{s.slug()}", selected: status() == s.slug(), {t(s.key())} }
                    }
                }
                select { class: "select", style: "width: auto; min-width: 150px", onchange: move |e| prio.set(e.value()),
                    option { value: "all", selected: prio() == "all", {t("tickets.all_priorities")} }
                    for p in Priority::ALL.iter().rev().copied() {
                        option { key: "{p.slug()}", value: "{p.slug()}", selected: prio() == p.slug(), {t(p.key())} }
                    }
                }
            }
            div { class: "chips",
                button { class: if kind().is_none() { "chip on" } else { "chip" }, onclick: move |_| kind.set(None),
                    {t("common.all")}
                    span { class: "count", "{base.len()}" }
                }
                for (k, n) in kind_counts {
                    button {
                        key: "{k.slug()}",
                        class: if kind() == Some(k) { "chip on" } else { "chip" },
                        onclick: move |_| kind.set(if kind() == Some(k) { None } else { Some(k) }),
                        Icon { name: crm::db::ticket_icon(k), size: 14 }
                        {t(k.key())}
                        span { class: "count", "{n}" }
                    }
                }
            }

            div { class: "card",
                if shown.is_empty() {
                    Empty { icon: "life-buoy", title: t("tickets.empty"), text: t("tickets.empty_text") }
                } else {
                    div { class: "table-wrap",
                        table { class: "table responsive",
                            thead {
                                tr {
                                    th { {t("common.ticket")} }
                                    th { class: "m-hide", {t("common.customer")} }
                                    th { class: "m-hide", {t("common.branch")} }
                                    th { class: "m-hide", {t("tickets.priority")} }
                                    th { "SLA" }
                                    th { class: "m-hide", {t("common.status")} }
                                    th { class: "m-hide", {t("tickets.assignee")} }
                                }
                            }
                            tbody {
                                for r in shown {
                                    {
                                        let id = r.tk.id;
                                        let (sla_text, sla_tone, sla_icon) = sla(&r.tk, now, l);
                                        let kind_tone: &'static str = if r.tk.kind == TicketKind::AdverseReaction { "danger" } else if r.tk.kind == TicketKind::Praise { "success" } else { "muted" };
                                        let kicon = crm::db::ticket_icon(r.tk.kind);
                                        let klabel = t(r.tk.kind.key());
                                        let st = t(r.tk.status.key());
                                        let stone = status_tone(r.tk.status);
                                        let pr = t(r.tk.priority.key());
                                        let ptone = priority_tone(r.tk.priority);
                                        let when = fmt::relative(r.tk.created, now, l);
                                        rsx! {
                                            tr { key: "{id}", class: "click", onclick: move |_| go(&format!("/tickets/{id}")),
                                                td {
                                                    div { class: "row gap-12",
                                                        span { class: "ic {kind_tone} sm", Icon { name: kicon, size: 15 } }
                                                        div { style: "min-width: 0",
                                                            div { class: "strong small", "{r.tk.subject}" }
                                                            div { class: "xs muted", "{r.tk.number} · {klabel} · {when}" }
                                                        }
                                                    }
                                                }
                                                td { class: "m-hide",
                                                    div { class: "row gap-8",
                                                        Avatar { name: r.customer.clone(), size: "xs" }
                                                        span { class: "small truncate", "{r.customer}" }
                                                    }
                                                }
                                                td { class: "m-hide small muted", "{r.branch}" }
                                                td { class: "m-hide", Badge { text: pr, tone: ptone } }
                                                td {
                                                    span { class: "badge {sla_tone}", Icon { name: sla_icon, size: 12 } "{sla_text}" }
                                                }
                                                td { class: "m-hide", Badge { text: st, tone: stone, dot: true } }
                                                td { class: "m-hide",
                                                    if !r.assignee.is_empty() {
                                                        Avatar { name: r.assignee.clone(), hue: r.assignee_hue, size: "sm" }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- ticket page

#[component]
pub fn TicketDetail(id: u32) -> Element {
    let mut resolving = use_signal(|| false);
    let Some(tk) = DB.read().ticket(id).cloned() else {
        return rsx! {
            div { class: "page",
                div { class: "card",
                    Empty { icon: "life-buoy", title: t("tickets.not_found"),
                        Link { to: Route::Tickets {}, class: "btn primary", Icon { name: "arrow-left", size: 16 } {t("tickets.back")} }
                    }
                }
            }
        };
    };
    let l = lang();
    let now = now();
    let staff: Vec<(Id, String)> = DB
        .read()
        .staff
        .iter()
        .filter(|s| s.active && matches!(s.role, Role::Pharmacist | Role::Manager | Role::CallAgent | Role::Owner))
        .map(|s| (s.id, s.name.clone()))
        .collect();
    let (sla_text, sla_tone, sla_icon) = sla(&tk, now, l);
    let klabel = t(tk.kind.key());
    let kicon = crm::db::ticket_icon(tk.kind);
    let adverse = tk.kind == TicketKind::AdverseReaction;
    let kind_tone: &'static str = if adverse { "danger" } else { "" };
    let created = fmt::datetime(tk.created, now, l);
    let due = fmt::datetime(tk.due, now, l);
    let subtitle = format!("{} · {}", tk.number, t("tickets.opened").replace("{t}", &fmt::relative(tk.created, now, l)));
    let is_open = tk.is_open();
    let csat_text = tk.csat.map(|c| "★".repeat(c as usize) + &"☆".repeat(5 - (c as usize).min(5)));
    let sla_style = match sla_tone {
        "danger" => "background: var(--c-danger-soft); color: var(--c-danger)",
        "warning" => "background: var(--c-warning-soft); color: var(--c-warning)",
        "success" => "background: var(--c-success-soft); color: var(--c-success)",
        _ => "background: var(--c-surface-2)",
    };

    rsx! {
        div { class: "page",
            div { class: "row between wrap gap-8",
                Link { to: Route::Tickets {}, class: "btn ghost sm", Icon { name: "arrow-left", size: 15 } {t("tickets.back")} }
                span { class: "small muted num", "{tk.number}" }
            }
            PageHeader { title: tk.subject.clone(), subtitle,
                if is_open {
                    button {
                        class: "btn",
                        onclick: move |_| {
                            set_status(id, TicketStatus::Closed);
                            toast(t("tickets.closed_toast"), "archive", "");
                        },
                        Icon { name: "archive", size: 16 }
                        span { class: "label-text", {t("tickets.close")} }
                    }
                    button { class: "btn success keep", style: "color: var(--c-on-primary)", onclick: move |_| resolving.set(true), Icon { name: "circle-check", size: 16 } span { class: "label-text", {t("tickets.resolve")} } }
                } else {
                    button {
                        class: "btn",
                        onclick: move |_| {
                            set_status(id, TicketStatus::InProgress);
                            toast(t("tickets.reopened"), "rotate-ccw", "");
                        },
                        Icon { name: "rotate-ccw", size: 16 }
                        span { class: "label-text", {t("tickets.reopen")} }
                    }
                }
            }

            div { class: "card pad", style: "display: flex; flex-wrap: wrap; gap: 16px 24px; align-items: flex-end",
                div { class: "stack gap-4",
                    span { class: "xs muted upper", {t("tickets.kind")} }
                    span { class: "badge {kind_tone}", style: "height: 30px; padding: 0 12px", Icon { name: kicon, size: 14 } "{klabel}" }
                }
                div { class: "field", style: "flex: 1 1 160px",
                    span { class: "xs muted upper", {t("common.status")} }
                    select {
                        class: "select sm",
                        onchange: move |e| {
                            if let Some(s) = TicketStatus::from_slug(&e.value()) {
                                set_status(id, s);
                                toast(t("common.saved"), "check", "success");
                            }
                        },
                        for s in TicketStatus::ALL.iter().copied() {
                            option { key: "{s.slug()}", value: "{s.slug()}", selected: s == tk.status, {t(s.key())} }
                        }
                    }
                }
                div { class: "field", style: "flex: 1 1 140px",
                    span { class: "xs muted upper", {t("tickets.priority")} }
                    select {
                        class: "select sm",
                        onchange: move |e| {
                            if let Some(p) = Priority::from_slug(&e.value()) {
                                mutate(|db| {
                                    if let Some(x) = db.ticket_mut(id) {
                                        x.priority = p;
                                    }
                                });
                            }
                        },
                        for p in Priority::ALL.iter().rev().copied() {
                            option { key: "{p.slug()}", value: "{p.slug()}", selected: p == tk.priority, {t(p.key())} }
                        }
                    }
                }
                div { class: "field", style: "flex: 1 1 180px",
                    span { class: "xs muted upper", {t("tickets.assignee")} }
                    select {
                        class: "select sm",
                        onchange: move |e| {
                            let sid: Id = e.value().parse().unwrap_or(0);
                            let mut name = String::new();
                            mutate(|db| {
                                name = db.staff_name(Some(sid));
                                if let Some(x) = db.ticket_mut(id) {
                                    x.assigned_to = if sid == 0 { None } else { Some(sid) };
                                    if x.status == TicketStatus::New && sid != 0 {
                                        x.status = TicketStatus::InProgress;
                                    }
                                }
                            });
                            toast(format!("{} · {name}", t("tickets.assigned")), "user-check", "success");
                        },
                        option { value: "0", selected: tk.assigned_to.is_none(), {t("common.unassigned")} }
                        for (sid, name) in staff {
                            option { key: "{sid}", value: "{sid}", selected: Some(sid) == tk.assigned_to, "{name}" }
                        }
                    }
                }
                div { class: "stack gap-4", style: "margin-left: auto",
                    span { class: "xs muted upper", "SLA" }
                    div { class: "row gap-8", style: "padding: 6px 12px; border-radius: 10px; font-weight: 700; {sla_style}",
                        Icon { name: sla_icon, size: 16 }
                        span { class: "num", "{sla_text}" }
                    }
                }
            }

            div { class: "grid-main",
                div { class: "stack gap-16",
                    if adverse {
                        PharmacovigilanceCard { id }
                    }
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "file-text", size: 16, class: "subtle" } {t("common.description")} }
                            span { class: "xs muted", "{created}" }
                        }
                        div { class: "card-body",
                            p { style: "white-space: pre-wrap; line-height: 1.6", "{tk.description}" }
                        }
                    }
                    if tk.product_id.is_some() {
                        BatchCard { id }
                    }
                    CommentsCard { id }
                }
                div { class: "stack gap-16",
                    TicketCustomer { id }
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "info", size: 16, class: "subtle" } {t("common.details")} }
                        }
                        div { class: "card-body",
                            KeyValues {
                                items: vec![
                                    (t("common.created"), created.clone()),
                                    (t("tickets.deadline"), due.clone()),
                                    (t("common.branch"), DB.read().branch_name(tk.branch_id)),
                                    (t("tickets.csat"), csat_text.clone().unwrap_or_else(|| "—".into())),
                                ],
                            }
                        }
                    }
                    TicketTasks { id }
                }
            }
        }

        if resolving() {
            ResolveModal { id, onclose: move |_| resolving.set(false) }
        }
    }
}

fn set_status(id: Id, s: TicketStatus) {
    mutate(|db| {
        let now = now();
        if let Some(x) = db.ticket_mut(id) {
            x.status = s;
            match s {
                TicketStatus::Resolved | TicketStatus::Closed => {
                    if x.resolved.is_none() {
                        x.resolved = Some(now);
                    }
                }
                _ => x.resolved = None,
            }
        }
    });
}

/// Adds a comment by the signed-in user.
fn add_comment(id: Id, text: String, internal: bool) {
    mutate(|db| {
        let me = db.settings.me;
        let now = now();
        if let Some(x) = db.ticket_mut(id) {
            x.comments.push(Comment { at: now, author_id: Some(me), text, internal });
            if x.status == TicketStatus::New {
                x.status = TicketStatus::InProgress;
            }
        }
    });
}

#[component]
fn TicketCustomer(id: Id) -> Element {
    let (c, product, batch) = {
        let db = DB.read();
        let tk = db.ticket(id);
        (
            tk.and_then(|x| x.customer_id).and_then(|c| db.customer(c)).cloned(),
            tk.and_then(|x| x.product_id).and_then(|p| db.product(p)).cloned(),
            tk.and_then(|x| x.batch.clone()),
        )
    };
    rsx! {
        if let Some(c) = c {
            {
                let cid = c.id;
                let tel = phone(&c.phone);
                let href = crm::fmt::tel_href(&c.phone);
                let allergies = c.allergies.join(", ");
                let spent = money_short(c.total_spent);
                rsx! {
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "user", size: 16, class: "subtle" } {t("common.customer")} }
                            Link { to: Route::ContactDetail { id: cid }, class: "btn ghost sm", {t("common.see")} Icon { name: "arrow-right", size: 14 } }
                        }
                        div { class: "card-body stack gap-12",
                            div { class: "row gap-12",
                                Avatar { name: c.name(), size: "lg" }
                                div { class: "grow",
                                    div { class: "strong", "{c.name()}" }
                                    div { class: "xs muted num", "{tel}" }
                                }
                                TierBadge { tier: c.tier }
                            }
                            div { class: "row gap-8",
                                a { class: "btn sm", href: "{href}", Icon { name: "phone", size: 14 } {t("common.call")} }
                                button { class: "btn sm", onclick: move |_| go("/inbox"), Icon { name: "message-circle", size: 14 } {t("common.write")} }
                                span { class: "spacer" }
                                span { class: "xs muted num", "{spent}" }
                            }
                            if !allergies.is_empty() {
                                div { class: "callout danger", Icon { name: "triangle-alert", size: 15 } span { {t("tickets.allergies")} ": {allergies}" } }
                            }
                        }
                    }
                }
            }
        }
        if let Some(p) = product {
            {
                let pid = p.id;
                let cat_icon = crm::db::category_icon(p.category);
                let batch_text = batch.unwrap_or_else(|| "—".into());
                rsx! {
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "pill", size: 16, class: "subtle" } {t("common.product")} }
                            button { class: "btn ghost sm", onclick: move |_| go(&format!("/products?id={pid}")), {t("common.see")} Icon { name: "arrow-right", size: 14 } }
                        }
                        div { class: "card-body stack gap-8",
                            div { class: "row gap-12",
                                IconTile { icon: cat_icon, tone: "accent" }
                                div { class: "grow",
                                    div { class: "strong small", "{p.name}" }
                                    div { class: "xs muted", "{p.generic} · {p.maker}" }
                                }
                            }
                            div { class: "row between small", style: "padding: 8px 10px; border-radius: 10px; background: var(--c-surface-2)",
                                span { class: "muted", {t("tickets.batch")} }
                                span { class: "strong num", "{batch_text}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn BatchCard(id: Id) -> Element {
    let l = lang();
    let now = now();
    let mut show_all = use_signal(|| false);
    let (others, product, batch, number, connected) = {
        let db = DB.read();
        let Some(tk) = db.ticket(id) else { return rsx! {} };
        let Some(pid) = tk.product_id else { return rsx! {} };
        let since = now - Duration::days(60);
        let mut by: HashMap<Id, (NaiveDateTime, Id, u32)> = HashMap::new();
        for p in db.purchases.iter().filter(|p| p.at >= since && Some(p.customer_id) != tk.customer_id) {
            let n: u32 = p.items.iter().filter(|i| i.product_id == pid).map(|i| i.qty).sum();
            if n > 0 {
                let e = by.entry(p.customer_id).or_insert((p.at, p.branch_id, 0));
                e.2 += n;
                if p.at > e.0 {
                    e.0 = p.at;
                    e.1 = p.branch_id;
                }
            }
        }
        let mut v: Vec<(Id, String, NaiveDateTime, String, u32, bool)> = by
            .into_iter()
            .filter_map(|(cid, (at, b, n))| db.customer(cid).map(|c| (cid, c.name(), at, db.branch_name(Some(b)), n, c.consent.telegram || c.consent.sms)))
            .collect();
        v.sort_by(|a, b| b.2.cmp(&a.2));
        (v, db.product_name(Some(pid)), tk.batch.clone().unwrap_or_default(), tk.number.clone(), db.settings.daybook.connected)
    };
    let count = others.len();
    let reachable = others.iter().filter(|o| o.5).count();
    let shown: Vec<_> = if show_all() { others.clone() } else { others.iter().take(6).cloned().collect() };
    let hidden = count.saturating_sub(shown.len());
    let title = t("tickets.batch_title").replace("{n}", &count.to_string());
    let notify_label = t("tickets.notify_them").replace("{n}", &reachable.to_string());
    let more = t("tickets.show_more").replace("{n}", &hidden.to_string());
    let no_consent = t("tickets.no_consent");
    let product2 = product.clone();
    let batch2 = batch.clone();
    let notify = move |_| {
        let text = format!("Partiya bo‘yicha ogohlantirish: {product} {batch} oxirgi 60 kunda olgan {reachable} ta mijozga yuborildi.");
        add_comment(id, text, true);
        mutate(|db| db.log(crate::state::now(), format!("{number}: partiya bo‘yicha {reachable} ta mijozga xabar"), false));
        toast(t("tickets.notified").replace("{n}", &reachable.to_string()), "send", "success");
    };
    let quarantine = move |_| {
        mutate(|db| {
            let now = crate::state::now();
            let (branch, num) = db.ticket(id).map(|x| (x.branch_id, x.number.clone())).unwrap_or((None, String::new()));
            let owner = branch.and_then(|b| db.branch(b)).and_then(|b| b.manager_id).unwrap_or(db.settings.me);
            db.add_activity(Activity {
                id: 0,
                kind: ActivityKind::Task,
                title: format!("Karantin: {product2} {batch2}"),
                notes: format!("{num}: partiyani sotuvdan olib, javonlarni tekshirish"),
                due: now + Duration::hours(2),
                done: false,
                done_at: None,
                owner_id: owner,
                customer_id: None,
                company_id: None,
                deal_id: None,
                ticket_id: Some(id),
                priority: Priority::Urgent,
                outcome: None,
                duration_min: 30,
                daybook_task: if connected { Some(0) } else { None },
            });
        });
        add_comment(id, "Daybook’da karantin vazifasi ochildi: partiya sotuvdan olinadi.".into(), true);
        toast(t("tickets.quarantine_done"), "shield-alert", "success");
    };
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "scan-barcode", size: 16, class: "tone-warning" } "{title}" }
            }
            div { class: "card-body stack gap-12",
                div { class: "small muted", {t("tickets.batch_hint")} }
                if others.is_empty() {
                    div { class: "callout success", Icon { name: "circle-check", size: 15 } span { {t("tickets.batch_none")} } }
                }
            }
            div { class: "list",
                for (cid, name, at, branch, n, ok) in shown {
                    {
                        let when = fmt::relative(at, now, l);
                        rsx! {
                            div { key: "{cid}", class: "list-row click", onclick: move |_| go(&format!("/contacts/{cid}")),
                                Avatar { name: name.clone(), size: "sm" }
                                div { class: "meta",
                                    span { class: "title small truncate", "{name}" }
                                    span { class: "sub", "{when} · {branch}" }
                                }
                                span { class: "small num muted", "×{n}" }
                                if !ok {
                                    span { class: "badge sm", title: "{no_consent}", Icon { name: "bell-off", size: 11 } }
                                }
                            }
                        }
                    }
                }
            }
            if hidden > 0 {
                div { class: "card-foot", style: "justify-content: center",
                    button { class: "btn ghost sm", onclick: move |_| show_all.set(true), Icon { name: "chevron-down", size: 14 } "{more}" }
                }
            }
            div { class: "card-foot", style: "flex-wrap: wrap",
                button { class: "btn soft sm", disabled: reachable == 0, onclick: notify, Icon { name: "send", size: 14 } "{notify_label}" }
                button { class: "btn sm", onclick: quarantine, Icon { name: "shield-alert", size: 14 } {t("tickets.quarantine")} }
            }
        }
    }
}

#[component]
fn CommentsCard(id: Id) -> Element {
    let l = lang();
    let now = now();
    let mut text = use_signal(String::new);
    let mut internal = use_signal(|| false);
    let comments: Vec<(Comment, String, u16)> = {
        let db = DB.read();
        db.ticket(id)
            .map(|x| {
                x.comments
                    .iter()
                    .map(|c| {
                        let s = c.author_id.and_then(|a| db.staff_member(a));
                        (c.clone(), s.map(|s| s.name.clone()).unwrap_or_default(), s.map(|s| s.hue).unwrap_or(24))
                    })
                    .collect()
            })
            .unwrap_or_default()
    };
    let valid = !text().trim().is_empty();
    let send = move |_| {
        let body = text().trim().to_string();
        if body.is_empty() {
            return;
        }
        let inner = internal();
        add_comment(id, body, inner);
        text.set(String::new());
        toast(if inner { t("tickets.note_saved") } else { t("tickets.reply_sent") }, if inner { "sticky-note" } else { "send" }, "success");
    };
    let send_label = if internal() { t("tickets.save_note") } else { t("tickets.send_reply") };
    let send_icon: &'static str = if internal() { "sticky-note" } else { "send" };
    let internal_label = t("tickets.internal");
    rsx! {
        div { class: "card",
            div { class: "card-head line",
                div { class: "card-title", Icon { name: "message-square-text", size: 16, class: "tone-info" } {t("tickets.thread")} }
                span { class: "badge", "{comments.len()}" }
            }
            div { class: "thread", style: "max-height: 420px; min-height: 120px",
                if comments.is_empty() {
                    div { class: "day-sep", {t("tickets.no_comments")} }
                }
                for (i, (c, author, hue)) in comments.into_iter().enumerate() {
                    {
                        let when = fmt::datetime(c.at, now, l);
                        rsx! {
                            if c.internal {
                                div { key: "{i}", class: "bubble note",
                                    div { class: "row gap-4 xs strong", style: "margin-bottom: 2px", Icon { name: "lock", size: 11 } "{author} · {internal_label}" }
                                    div { style: "white-space: pre-wrap", "{c.text}" }
                                    div { class: "xs", style: "opacity: .7; margin-top: 2px", "{when}" }
                                }
                            } else {
                                div { key: "{i}", class: "row top gap-8", style: "align-self: flex-end; max-width: 86%",
                                    div { class: "bubble out", style: "max-width: 100%",
                                        div { style: "white-space: pre-wrap", "{c.text}" }
                                        span { class: "time", "{when}" }
                                    }
                                    Avatar { name: author.clone(), hue, size: "xs" }
                                }
                            }
                        }
                    }
                }
            }
            div { class: "composer",
                textarea {
                    placeholder: if internal() { t("tickets.note_hint") } else { t("tickets.reply_hint") },
                    value: "{text}",
                    oninput: move |e| text.set(e.value()),
                }
                div { class: "row between gap-8",
                    label { class: "row gap-8 small muted", style: "cursor: pointer",
                        Switch { on: internal(), onchange: move |v| internal.set(v) }
                        Icon { name: "lock", size: 13 }
                        {t("tickets.internal_toggle")}
                    }
                    button { class: if internal() { "btn sm" } else { "btn primary sm" }, disabled: !valid, onclick: send,
                        Icon { name: send_icon, size: 14 }
                        "{send_label}"
                    }
                }
            }
        }
    }
}

#[component]
fn TicketTasks(id: Id) -> Element {
    let l = lang();
    let now = now();
    let tasks: Vec<(Activity, String)> = {
        let db = DB.read();
        db.activities.iter().filter(|a| a.ticket_id == Some(id)).map(|a| (a.clone(), db.staff_name(Some(a.owner_id)))).collect()
    };
    if tasks.is_empty() {
        return rsx! {};
    }
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "square-check", size: 16, class: "subtle" } {t("nav.tasks")} }
            }
            div { class: "list", style: "margin-top: 8px",
                for (a, owner) in tasks {
                    {
                        let aid = a.id;
                        let when = fmt::datetime(a.due, now, l);
                        let check_cls = if a.done { "check-circle on" } else { "check-circle" };
                        rsx! {
                            div { key: "{aid}", class: "list-row",
                                button { class: check_cls, onclick: move |_| mutate(|db| db.complete_activity(aid, crate::state::now())), Icon { name: "check", size: 13 } }
                                div { class: "meta",
                                    span { class: "title small", "{a.title}" }
                                    span { class: "sub", "{owner} · {when}" }
                                }
                                if a.daybook_task.is_some() {
                                    span { class: "badge sm accent", "Daybook" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

const SEVERITY: &[&str] = &["mild", "moderate", "severe", "life_threatening"];
const OUTCOME: &[&str] = &["recovering", "recovered", "not_recovered", "unknown"];

#[component]
fn PharmacovigilanceCard(id: Id) -> Element {
    let l = lang();
    let now = now();
    let mut reaction = use_signal(move || DB.peek().ticket(id).map(|x| x.description.clone()).unwrap_or_default());
    let mut onset = use_signal(move || {
        DB.peek().ticket(id).map(|x| (x.created - Duration::hours(10)).format("%Y-%m-%dT%H:%M").to_string()).unwrap_or_default()
    });
    let mut severity = use_signal(|| "moderate".to_string());
    let mut outcome = use_signal(|| "recovering".to_string());
    let (created, reported, product, batch) = {
        let db = DB.read();
        let Some(tk) = db.ticket(id) else { return rsx! {} };
        (tk.created, tk.reported_to_regulator, db.product_name(tk.product_id), tk.batch.clone().unwrap_or_default())
    };
    let deadline = created + Duration::hours(4);
    let left = (deadline - now).num_minutes();
    let (deadline_text, tone): (String, &'static str) = if reported {
        (t("tickets.pv_reported"), "success")
    } else if left >= 0 {
        (t("tickets.pv_left").replace("{t}", &dur(left, l)), "warning")
    } else {
        (t("tickets.pv_late").replace("{t}", &dur(left, l)), "danger")
    };
    let save = move |_| {
        let text = format!(
            "Farmakonazorat shakli: {}. Boshlangan: {}. Og‘irligi: {}. Natija: {}. Dori: {} {}.",
            reaction().trim(),
            onset().replace('T', " "),
            severity(),
            outcome(),
            product,
            batch
        );
        add_comment(id, text, true);
        toast(t("tickets.pv_saved"), "file-check", "success");
    };
    rsx! {
        div { class: "card", style: "border-color: color-mix(in srgb, var(--c-danger) 35%, var(--c-border))",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "triangle-alert", size: 16, class: "tone-danger" } {t("tickets.pv_title")} }
                span { class: "badge {tone}", Icon { name: "timer", size: 12 } "{deadline_text}" }
            }
            div { class: "card-body stack gap-12",
                div { class: "callout danger", Icon { name: "shield-alert", size: 16 } span { {t("tickets.pv_rule")} } }
                div { class: "field",
                    label { class: "label", {t("tickets.pv_reaction")} }
                    textarea { class: "textarea", style: "min-height: 70px", value: "{reaction}", oninput: move |e| reaction.set(e.value()) }
                }
                div { class: "grid-3",
                    div { class: "field",
                        label { class: "label", {t("tickets.pv_onset")} }
                        input { class: "input", r#type: "datetime-local", value: "{onset}", oninput: move |e| onset.set(e.value()) }
                    }
                    div { class: "field",
                        label { class: "label", {t("tickets.pv_severity")} }
                        select { class: "select", onchange: move |e| severity.set(e.value()),
                            for s in SEVERITY.iter().copied() {
                                option { key: "{s}", value: "{s}", selected: severity() == s, {t(&format!("tickets.sev.{s}"))} }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("tickets.pv_outcome")} }
                        select { class: "select", onchange: move |e| outcome.set(e.value()),
                            for o in OUTCOME.iter().copied() {
                                option { key: "{o}", value: "{o}", selected: outcome() == o, {t(&format!("tickets.out.{o}"))} }
                            }
                        }
                    }
                }
                div { class: "row between wrap gap-12", style: "padding: 10px 12px; border-radius: 12px; background: var(--c-surface-2)",
                    div { class: "row gap-12",
                        Switch {
                            on: reported,
                            onchange: move |v: bool| {
                                mutate(|db| {
                                    if let Some(x) = db.ticket_mut(id) {
                                        x.reported_to_regulator = v;
                                    }
                                    db.log(crate::state::now(), format!("Farmakonazorat: {}", if v { "xabar berildi" } else { "bekor qilindi" }), true);
                                });
                                if v {
                                    toast(t("tickets.pv_reported_toast"), "shield-check", "success");
                                }
                            },
                        }
                        div {
                            div { class: "small strong", {t("tickets.pv_regulator")} }
                            div { class: "xs muted", {t("tickets.pv_regulator_hint")} }
                        }
                    }
                    button { class: "btn primary sm", onclick: save, Icon { name: "file-check", size: 14 } {t("tickets.pv_save")} }
                }
            }
        }
    }
}

#[component]
fn ResolveModal(id: Id, onclose: EventHandler<()>) -> Element {
    let mut csat = use_signal(|| 5u8);
    let mut text = use_signal(String::new);
    let save = move |_| {
        let score = csat();
        let note = text().trim().to_string();
        if !note.is_empty() {
            add_comment(id, note, false);
        }
        mutate(|db| {
            let now = crate::state::now();
            if let Some(x) = db.ticket_mut(id) {
                x.status = TicketStatus::Resolved;
                x.resolved = Some(now);
                x.csat = Some(score);
            }
        });
        toast(t("tickets.resolved_toast"), "circle-check", "success");
        onclose.call(());
    };
    rsx! {
        Modal { title: t("tickets.resolve_title"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("tickets.resolution")} }
                    textarea {
                        class: "textarea",
                        placeholder: t("tickets.resolution_hint"),
                        value: "{text}",
                        oninput: move |e| text.set(e.value()),
                        onmounted: move |e| async move {
                            let _ = e.set_focus(true).await;
                        },
                    }
                }
                div { class: "field",
                    label { class: "label", {t("tickets.csat_question")} }
                    div { class: "row gap-4",
                        for n in 1..=5u8 {
                            button {
                                key: "{n}",
                                class: "icon-btn",
                                style: if n <= csat() { "color: var(--c-warning); font-size: 26px; width: 42px; height: 42px" } else { "color: var(--c-border-strong); font-size: 26px; width: 42px; height: 42px" },
                                onclick: move |_| csat.set(n),
                                "★"
                            }
                        }
                        span { class: "small muted", style: "margin-left: 8px", {t(&format!("tickets.csat_{}", csat()))} }
                    }
                }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn success", style: "color: var(--c-on-primary)", onclick: save, Icon { name: "circle-check", size: 16 } {t("tickets.resolve")} }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("tickets.sub", "Shikoyatlar, qaytarishlar, sifat va nojo‘ya ta’sirlar: hammasi muddat nazoratida", "Жалобы, возвраты, качество и нежелательные реакции под контролем сроков", "Complaints, returns, quality and adverse reactions, all on the clock"),
    ("tickets.kpi_open", "Ochiq murojaatlar", "Открытые обращения", "Open tickets"),
    ("tickets.kpi_open_foot", "hal qilinmagan", "ещё не решены", "not resolved yet"),
    ("tickets.kpi_breached", "Muddati o‘tgan", "Просрочено", "Past SLA"),
    ("tickets.breached_foot", "SLA buzilgan", "нарушен SLA", "SLA breached"),
    ("tickets.adverse_open", "{n} ochiq", "открыто: {n}", "{n} open"),
    ("tickets.kpi_resolution", "O‘rtacha hal qilish", "Среднее время решения", "Avg resolution"),
    ("tickets.kpi_resolution_foot", "yopilgan murojaatlar bo‘yicha", "по решённым обращениям", "across resolved tickets"),
    ("tickets.kpi_csat", "Mijoz bahosi", "Оценка клиентов", "Customer rating"),
    ("tickets.search", "Raqam, mavzu yoki mijoz…", "Номер, тема или клиент…", "Number, subject or customer…"),
    ("tickets.only_open", "Faqat ochiqlar", "Только открытые", "Open only"),
    ("tickets.all_statuses", "Barcha holatlar", "Все статусы", "All statuses"),
    ("tickets.all_priorities", "Barcha muhimlik", "Любой приоритет", "Any priority"),
    ("tickets.priority", "Muhimlik", "Приоритет", "Priority"),
    ("tickets.assignee", "Mas’ul xodim", "Исполнитель", "Assignee"),
    ("tickets.sla_left", "{t} qoldi", "осталось {t}", "{t} left"),
    ("tickets.sla_breached", "{t} kechikdi", "просрочено на {t}", "breached by {t}"),
    ("tickets.sla_resolved", "{t} da hal qilindi", "решено за {t}", "resolved in {t}"),
    ("tickets.empty", "Murojaatlar yo‘q", "Обращений нет", "No tickets here"),
    ("tickets.empty_text", "Filtrlarni o‘zgartiring yoki yangi murojaat oching.", "Измените фильтры или создайте обращение.", "Change the filters or open a new ticket."),
    ("tickets.not_found", "Murojaat topilmadi", "Обращение не найдено", "Ticket not found"),
    ("tickets.back", "Murojaatlarga qaytish", "К обращениям", "Back to tickets"),
    ("tickets.opened", "ochilgan: {t}", "открыто {t}", "opened {t}"),
    ("tickets.kind", "Turi", "Тип", "Type"),
    ("tickets.close", "Yopish", "Закрыть", "Close"),
    ("tickets.closed_toast", "Murojaat yopildi", "Обращение закрыто", "Ticket closed"),
    ("tickets.resolve", "Hal qilindi", "Решено", "Resolve"),
    ("tickets.reopen", "Qayta ochish", "Открыть снова", "Reopen"),
    ("tickets.reopened", "Murojaat qayta ochildi", "Обращение снова открыто", "Ticket reopened"),
    ("tickets.assigned", "Biriktirildi", "Назначено", "Assigned"),
    ("tickets.deadline", "Muddat (SLA)", "Срок (SLA)", "Deadline (SLA)"),
    ("tickets.csat", "Baho", "Оценка", "Rating"),
    ("tickets.allergies", "Allergiya", "Аллергия", "Allergies"),
    ("tickets.batch", "Partiya", "Партия", "Batch"),
    ("tickets.batch_title", "Shu dorini olgan boshqa mijozlar: {n}", "Другие покупатели этого товара: {n}", "Other customers who bought it: {n}"),
    ("tickets.batch_hint", "Oxirgi 60 kunda shu mahsulotni olganlar. Partiyada muammo bo‘lsa, ularni ogohlantiring va partiyani karantinga oling.", "Купили этот товар за последние 60 дней. Если с партией проблема, предупредите их и поместите партию в карантин.", "Bought this product in the last 60 days. If the batch is faulty, warn them and quarantine the batch."),
    ("tickets.batch_none", "Boshqa hech kim olmagan", "Больше никто не покупал", "No one else bought it"),
    ("tickets.notify_them", "Ularga xabar berish ({n})", "Предупредить ({n})", "Notify them ({n})"),
    ("tickets.notified", "{n} ta mijozga ogohlantirish yuborildi", "Предупреждение отправлено клиентам: {n}", "Warning sent to {n} customers"),
    ("tickets.quarantine", "Daybook’da karantin vazifasi", "Задача на карантин в Daybook", "Quarantine task in Daybook"),
    ("tickets.quarantine_done", "Karantin vazifasi ochildi va filial mudiriga biriktirildi", "Задача на карантин создана и назначена заведующему", "Quarantine task opened for the branch manager"),
    ("tickets.no_consent", "Xabar olishga rozilik yo‘q", "Нет согласия на сообщения", "No consent for messages"),
    ("tickets.show_more", "Yana {n} ta", "Ещё {n}", "{n} more"),
    ("tickets.thread", "Yozishma va izohlar", "Переписка и заметки", "Replies and notes"),
    ("tickets.no_comments", "Hali izoh yo‘q", "Пока нет комментариев", "No replies yet"),
    ("tickets.internal", "ichki izoh", "внутренняя заметка", "internal note"),
    ("tickets.internal_toggle", "Ichki izoh (mijoz ko‘rmaydi)", "Внутренняя заметка (клиент не видит)", "Internal note (customer won’t see it)"),
    ("tickets.note_hint", "Hamkasblar uchun izoh…", "Заметка для коллег…", "A note for colleagues…"),
    ("tickets.reply_hint", "Mijozga javob…", "Ответ клиенту…", "Reply to the customer…"),
    ("tickets.save_note", "Izohni saqlash", "Сохранить заметку", "Save note"),
    ("tickets.send_reply", "Javob yuborish", "Отправить ответ", "Send reply"),
    ("tickets.note_saved", "Ichki izoh saqlandi", "Заметка сохранена", "Internal note saved"),
    ("tickets.reply_sent", "Javob mijozga yuborildi", "Ответ отправлен клиенту", "Reply sent to the customer"),
    ("tickets.pv_title", "Farmakonazorat shakli", "Форма фармаконадзора", "Pharmacovigilance report"),
    ("tickets.pv_rule", "Nojo‘ya ta’sir 4 soat ichida ko‘rib chiqilishi va farmakonazorat organiga xabar qilinishi shart.", "Нежелательную реакцию нужно разобрать за 4 часа и сообщить в фармаконадзор.", "An adverse reaction must be reviewed and reported to pharmacovigilance within 4 hours."),
    ("tickets.pv_left", "xabar berishga {t} qoldi", "до сообщения {t}", "{t} left to report"),
    ("tickets.pv_late", "{t} kechikdi", "опоздание {t}", "{t} late"),
    ("tickets.pv_reported", "Xabar berilgan", "Сообщено", "Reported"),
    ("tickets.pv_reaction", "Reaksiya tavsifi", "Описание реакции", "Reaction"),
    ("tickets.pv_onset", "Boshlangan vaqti", "Время начала", "Onset"),
    ("tickets.pv_severity", "Og‘irligi", "Тяжесть", "Severity"),
    ("tickets.pv_outcome", "Natija", "Исход", "Outcome"),
    ("tickets.sev.mild", "Yengil", "Лёгкая", "Mild"),
    ("tickets.sev.moderate", "O‘rtacha", "Средняя", "Moderate"),
    ("tickets.sev.severe", "Og‘ir", "Тяжёлая", "Severe"),
    ("tickets.sev.life_threatening", "Hayot uchun xavfli", "Угрожает жизни", "Life-threatening"),
    ("tickets.out.recovering", "Tuzalmoqda", "Выздоравливает", "Recovering"),
    ("tickets.out.recovered", "Tuzaldi", "Выздоровел", "Recovered"),
    ("tickets.out.not_recovered", "Yaxshilanish yo‘q", "Без улучшения", "Not recovered"),
    ("tickets.out.unknown", "Noma’lum", "Неизвестно", "Unknown"),
    ("tickets.pv_regulator", "Farmakonazoratga xabar berildi", "Сообщено в фармаконадзор", "Reported to the regulator"),
    ("tickets.pv_regulator_hint", "Yuborilgan xabarnoma raqamini izohga yozing", "Номер извещения укажите в заметке", "Put the notice number in a note"),
    ("tickets.pv_reported_toast", "Farmakonazoratga xabar berildi deb belgilandi", "Отмечено: сообщено в фармаконадзор", "Marked as reported to the regulator"),
    ("tickets.pv_save", "Shaklni saqlash", "Сохранить форму", "Save the form"),
    ("tickets.pv_saved", "Shakl murojaatga ichki izoh sifatida saqlandi", "Форма сохранена как внутренняя заметка", "Form saved to the ticket as an internal note"),
    ("tickets.resolve_title", "Murojaatni yopish", "Решение обращения", "Resolve the ticket"),
    ("tickets.resolution", "Qanday hal qilindi", "Как решили", "How it was resolved"),
    ("tickets.resolution_hint", "Masalan: dori almashtirildi, mijoz rozi", "Например: товар заменили, клиент доволен", "e.g. replaced the pack, the customer is happy"),
    ("tickets.csat_question", "Mijoz bahosi", "Оценка клиента", "Customer rating"),
    ("tickets.csat_1", "Juda yomon", "Очень плохо", "Very poor"),
    ("tickets.csat_2", "Yomon", "Плохо", "Poor"),
    ("tickets.csat_3", "O‘rtacha", "Нормально", "Okay"),
    ("tickets.csat_4", "Yaxshi", "Хорошо", "Good"),
    ("tickets.csat_5", "A’lo", "Отлично", "Excellent"),
    ("tickets.resolved_toast", "Murojaat hal qilindi", "Обращение решено", "Ticket resolved"),
];
