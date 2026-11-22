//! Defektura (waitlist): what customers asked for and we didn't have. Every request is tracked
//! to the shelf and back to the customer, and the demand we're losing is shown in money.

use std::collections::HashMap;

use chrono::{Duration, NaiveDate};
use crm::fmt;
use crm::i18n::Entry;
use crm::model::*;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

#[derive(Clone, PartialEq)]
struct Item {
    w: WaitItem,
    customer: String,
    tier: Tier,
    branch: String,
    /// Stock at the request's branch right now (catalogue products only).
    stock: Option<u32>,
}

const BOARD: [(WaitStatus, &str); 5] = [
    (WaitStatus::Waiting, "var(--c-warning)"),
    (WaitStatus::Arrived, "var(--c-success)"),
    (WaitStatus::Notified, "var(--c-info)"),
    (WaitStatus::Reserved, "var(--c-primary)"),
    (WaitStatus::PickedUp, "var(--c-chart-2)"),
];

fn status_tone(s: WaitStatus) -> &'static str {
    match s {
        WaitStatus::Waiting => "warning",
        WaitStatus::Arrived => "success",
        WaitStatus::Notified => "info",
        WaitStatus::Reserved => "accent",
        WaitStatus::PickedUp => "success",
        WaitStatus::Cancelled => "",
    }
}

#[component]
pub fn Waitlist() -> Element {
    let l = lang();
    let now = now();
    let items = use_memo(move || {
        let db = DB.read();
        let mut v: Vec<Item> = db
            .waitlist
            .iter()
            .map(|w| {
                let c = db.customer(w.customer_id);
                Item {
                    w: w.clone(),
                    customer: c.map(|c| c.name()).unwrap_or_else(|| "—".into()),
                    tier: c.map(|c| c.tier).unwrap_or(Tier::Bronze),
                    branch: db.branch_name(Some(w.branch_id)),
                    stock: w.product_id.and_then(|p| db.product(p)).map(|p| p.stock_at(w.branch_id)),
                }
            })
            .collect();
        v.sort_by(|a, b| b.w.at.cmp(&a.w.at));
        v
    });
    let mut view = use_signal(|| "board".to_string());
    let mut q = use_signal(String::new);
    let mut branch = use_signal(|| 0u32);
    let mut adding = use_signal(|| false);

    let branches: Vec<(Id, String)> = DB.read().branches.iter().map(|b| (b.id, b.name.clone())).collect();
    let all = items();

    // numbers for the whole list
    let waiting: Vec<&Item> = all.iter().filter(|i| i.w.status == WaitStatus::Waiting).collect();
    let waiting_value: Money = waiting.iter().map(|i| i.w.value).sum();
    let waiting_people = waiting.iter().map(|i| i.w.customer_id).collect::<std::collections::HashSet<_>>().len();
    let arrived = all.iter().filter(|i| i.w.status == WaitStatus::Arrived).count();
    let picked = all.iter().filter(|i| i.w.status == WaitStatus::PickedUp).count();
    let conv = if all.is_empty() { 0.0 } else { picked as f64 / all.len() as f64 * 100.0 };
    let lost_value: Money = all.iter().filter(|i| i.w.status == WaitStatus::Cancelled).map(|i| i.w.value).sum();
    let saved_value: Money = all.iter().filter(|i| i.w.status == WaitStatus::PickedUp).map(|i| i.w.value).sum();
    let avg_wait = if waiting.is_empty() { 0 } else { waiting.iter().map(|i| (now - i.w.at).num_days()).sum::<i64>() / waiting.len() as i64 };

    // "most wanted": what is still missing, by value
    let mut wanted: HashMap<String, (String, usize, u32, Money)> = HashMap::new();
    for i in &waiting {
        let e = wanted.entry(i.w.product_name.to_lowercase()).or_insert_with(|| (i.w.product_name.clone(), 0, 0, 0));
        e.1 += 1;
        e.2 += i.w.qty;
        e.3 += i.w.value;
    }
    let mut wanted: Vec<(String, usize, u32, Money)> = wanted.into_values().collect();
    wanted.sort_by(|a, b| b.3.cmp(&a.3).then(b.1.cmp(&a.1)));
    let wanted_max = wanted.first().map(|w| w.3).unwrap_or(1).max(1);
    let order_lines = wanted.len();

    // the board and list follow the search and branch filter
    let ql = q().trim().to_lowercase();
    let shown: Vec<Item> = all
        .iter()
        .filter(|i| branch() == 0 || i.w.branch_id == branch())
        .filter(|i| ql.is_empty() || i.w.product_name.to_lowercase().contains(&ql) || i.customer.to_lowercase().contains(&ql))
        .cloned()
        .collect();

    let mut by_branch: Vec<(String, Money)> = {
        let mut m: HashMap<String, Money> = HashMap::new();
        for i in &waiting {
            *m.entry(i.branch.clone()).or_default() += i.w.value;
        }
        m.into_iter().collect()
    };
    by_branch.sort_by(|a, b| b.1.cmp(&a.1));
    by_branch.truncate(3);
    let branch_max = by_branch.first().map(|b| b.1).unwrap_or(1).max(1);
    let hero_text = t("waitlist.hero_text").replace("{n}", &waiting_people.to_string());
    let waiting_foot = t("waitlist.kpi_waiting_foot").replace("{n}", &fmt::plural(waiting_people as i64, l, "ta mijoz|клиент|клиента|клиентов|customer|customers"));
    let conv_foot = t("waitlist.kpi_conv_foot").replace("{n}", &picked.to_string()).replace("{m}", &all.len().to_string());
    let avg_wait_text = fmt::days(avg_wait, l);
    let is_board = view() == "board";

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.waitlist"), subtitle: t("waitlist.sub"),
                button { class: "btn primary", onclick: move |_| adding.set(true),
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("waitlist.new")} }
                }
            }

            div { class: "grid-4",
                Kpi { label: t("waitlist.kpi_waiting"), value: fmt::num(waiting.len() as i64), icon: "hourglass", tone: "warning", foot: waiting_foot }
                Kpi { label: t("waitlist.kpi_value"), value: money_short(waiting_value), icon: "trending-down", tone: "danger", foot: t("waitlist.kpi_value_foot") }
                Kpi { label: t("waitlist.kpi_arrived"), value: fmt::num(arrived as i64), icon: "package-check", tone: "success", foot: t("waitlist.kpi_arrived_foot") }
                Kpi { label: t("waitlist.kpi_conv"), value: fmt::pct(conv, l), icon: "chart-pie", tone: "info", foot: conv_foot }
            }

            div { class: "grid-2",
                div { class: "card hero", style: "padding: 22px 22px 20px; display: flex; flex-direction: column; gap: 14px",
                    div { class: "row gap-8",
                        span { class: "ic", style: "background: rgb(255 255 255 / .16); color: #fff", Icon { name: "trending-down", size: 17 } }
                        span { class: "strong", {t("waitlist.hero_title")} }
                    }
                    div {
                        div { class: "num", style: "font-size: 40px; font-weight: 750; letter-spacing: -0.02em; line-height: 1.05", "{money(waiting_value)}" }
                        p { class: "muted", style: "margin-top: 8px; max-width: 460px", "{hero_text}" }
                    }
                    if !by_branch.is_empty() {
                        div { class: "stack gap-8",
                            div { class: "xs muted upper", {t("waitlist.hero_where")} }
                            for (name, v) in by_branch {
                                {
                                    let w = v as f64 / branch_max as f64 * 100.0;
                                    rsx! {
                                        div { key: "{name}", class: "row gap-12 small",
                                            span { class: "truncate", style: "width: 120px", "{name}" }
                                            div { class: "grow", style: "height: 8px; border-radius: 99px; background: rgb(255 255 255 / .14); overflow: hidden",
                                                div { style: "height: 100%; width: {w:.1}%; border-radius: 99px; background: rgb(255 255 255 / .85)" }
                                            }
                                            span { class: "num strong nowrap", style: "width: 84px; text-align: right", "{money_short(v)}" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "grid-3", style: "gap: 10px; margin-top: auto; grid-template-columns: repeat(3, minmax(0, 1fr))",
                        div { style: "padding: 10px 12px; border-radius: 12px; background: rgb(255 255 255 / .1)",
                            div { class: "xs muted", {t("waitlist.hero_lost")} }
                            div { class: "strong num nowrap", style: "font-size: clamp(12px, 3.3vw, 14px)", "{money_short(lost_value)}" }
                        }
                        div { style: "padding: 10px 12px; border-radius: 12px; background: rgb(255 255 255 / .1)",
                            div { class: "xs muted", {t("waitlist.hero_saved")} }
                            div { class: "strong num nowrap", style: "font-size: clamp(12px, 3.3vw, 14px)", "{money_short(saved_value)}" }
                        }
                        div { style: "padding: 10px 12px; border-radius: 12px; background: rgb(255 255 255 / .1)",
                            div { class: "xs muted", {t("waitlist.hero_wait")} }
                            div { class: "strong num nowrap", style: "font-size: clamp(12px, 3.3vw, 14px)", "{avg_wait_text}" }
                        }
                    }
                }
                div { class: "card",
                    div { class: "card-head",
                        div { class: "card-title", Icon { name: "flame", size: 16, class: "tone-warning" } {t("waitlist.most_wanted")} }
                        span { class: "badge", "{order_lines}" }
                    }
                    div { class: "card-body stack gap-12",
                        if wanted.is_empty() {
                            Empty { icon: "circle-check", title: t("waitlist.nothing_missing") }
                        }
                        for (name, n, qty, value) in wanted.iter().take(5).cloned() {
                            {
                                let pct = value as f64 / wanted_max as f64 * 100.0;
                                let meta = format!("{} · {}", fmt::plural(n as i64, l, "so‘rov|заявка|заявки|заявок|request|requests"), fmt::plural(qty as i64, l, "dona|шт.|шт.|шт.|pc|pcs"));
                                rsx! {
                                    div { key: "{name}", class: "stack gap-4",
                                        div { class: "row between gap-12",
                                            span { class: "small strong truncate", "{name}" }
                                            span { class: "small num strong nowrap", "{money_short(value)}" }
                                        }
                                        Progress { pct, tone: "warning", thin: true }
                                        span { class: "xs muted", "{meta}" }
                                    }
                                }
                            }
                        }
                    }
                    if !wanted.is_empty() {
                        div { class: "card-foot",
                            span { class: "row gap-4 xs muted", Icon { name: "link-2", size: 13 } "Daybook" }
                            button {
                                class: "btn soft sm",
                                onclick: move |_| {
                                    mutate(|db| db.log(crate::state::now(), format!("Daybook xarid bo‘limiga defektura ro‘yxati: {order_lines} pozitsiya"), false));
                                    toast(t("waitlist.order_sent").replace("{n}", &order_lines.to_string()), "send", "success");
                                },
                                Icon { name: "send", size: 14 }
                                {t("waitlist.send_order")}
                            }
                        }
                    }
                }
            }

            div { class: "toolbar",
                div { class: "search",
                    Icon { name: "search", size: 16 }
                    input { class: "input", value: "{q}", placeholder: t("waitlist.search"), oninput: move |e| q.set(e.value()) }
                }
                select { class: "select", style: "width: auto; min-width: 170px", onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                    option { value: "0", selected: branch() == 0, {t("common.all_branches")} }
                    for (id, name) in branches {
                        option { key: "{id}", value: "{id}", selected: id == branch(), "{name}" }
                    }
                }
                span { class: "spacer" }
                Segmented {
                    options: vec![("board".into(), t("waitlist.board")), ("list".into(), t("waitlist.list"))],
                    value: view(),
                    onchange: move |v| view.set(v),
                }
            }

            if shown.is_empty() {
                div { class: "card",
                    Empty { icon: "hourglass", title: t("waitlist.empty"), text: t("waitlist.empty_text"),
                        button { class: "btn primary sm", onclick: move |_| adding.set(true), Icon { name: "plus", size: 14 } {t("waitlist.new")} }
                    }
                }
            } else if is_board {
                div { class: "kanban",
                    for (st, color) in BOARD {
                        {
                            let col: Vec<Item> = shown.iter().filter(|i| i.w.status == st).cloned().collect();
                            let n = col.len();
                            let value: Money = col.iter().map(|i| i.w.value).sum();
                            let label = t(st.key());
                            let ids: Vec<Id> = col.iter().map(|i| i.w.id).collect();
                            let notify_label = t("waitlist.notify_all").replace("{n}", &n.to_string());
                            rsx! {
                                div { class: "kanban-col", key: "{st.slug()}", style: "flex: 1 0 min(84vw, max(200px, calc(1100px - 100vw))); min-width: 0",
                                    div { class: "kanban-head",
                                        span { style: "width: 8px; height: 8px; border-radius: 99px; background: {color}; flex: 0 0 8px" }
                                        span { class: "strong small truncate", "{label}" }
                                        span { class: "badge sm", style: "margin-left: auto", "{n}" }
                                    }
                                    div { class: "xs subtle num", style: "padding: 0 6px; margin-top: -6px", "{money_short(value)}" }
                                    if col.is_empty() {
                                        div { class: "xs subtle center", style: "padding: 18px 6px; border: 1px dashed var(--c-border-strong); border-radius: 10px", {t("waitlist.empty_col")} }
                                    }
                                    for it in col {
                                        WaitCard { key: "{it.w.id}", item: it }
                                    }
                                    if st == WaitStatus::Arrived && n > 1 {
                                        button { class: "btn primary sm", onclick: move |_| notify_all(&ids),
                                            Icon { name: "send", size: 14 }
                                            "{notify_label}"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                div { class: "card",
                    div { class: "table-wrap",
                        table { class: "table responsive",
                            thead {
                                tr {
                                    th { {t("common.product")} }
                                    th { {t("common.customer")} }
                                    th { {t("common.branch")} }
                                    th { class: "num", {t("waitlist.qty")} }
                                    th { class: "num", {t("common.value")} }
                                    th { {t("waitlist.requested")} }
                                    th { {t("common.status")} }
                                    th {}
                                }
                            }
                            tbody {
                                for it in shown {
                                    WaitRow { key: "{it.w.id}", item: it }
                                }
                            }
                        }
                    }
                }
            }
        }

        if adding() {
            NewRequest { onclose: move |_| adding.set(false) }
        }
    }
}

/// The next steps a request can take from its status.
fn actions(s: WaitStatus) -> Vec<(WaitStatus, &'static str, &'static str, &'static str)> {
    // (target, label key, icon, button class)
    match s {
        WaitStatus::Waiting => vec![(WaitStatus::Arrived, "waitlist.act_arrived", "package-check", "btn sm soft")],
        WaitStatus::Arrived => vec![
            (WaitStatus::Notified, "waitlist.act_notify", "send", "btn sm primary"),
            (WaitStatus::Reserved, "waitlist.act_reserve", "bookmark", "btn sm"),
        ],
        WaitStatus::Notified => vec![
            (WaitStatus::Reserved, "waitlist.act_reserve", "bookmark", "btn sm"),
            (WaitStatus::PickedUp, "waitlist.act_picked", "shopping-bag", "btn sm soft"),
        ],
        WaitStatus::Reserved => vec![(WaitStatus::PickedUp, "waitlist.act_picked", "shopping-bag", "btn sm success")],
        _ => vec![],
    }
}

/// Moves a request on, with what each step means in real life (message, reservation, sale).
fn advance(id: Id, to: WaitStatus) {
    // what happened, worked out inside the change and worded after it (no translations while writing)
    let mut sold: Option<Money> = None;
    let mut by_sms = false;
    mutate(|db| {
        let now = now();
        let Some(w) = db.wait_item(id).cloned() else { return };
        let (tg, sms) = db.customer(w.customer_id).map(|c| (c.consent.telegram, c.consent.sms)).unwrap_or((false, false));
        match to {
            WaitStatus::Notified => {
                by_sms = !tg && sms;
                let me = db.settings.me;
                db.add_activity(Activity {
                    id: 0,
                    kind: ActivityKind::Message,
                    title: format!("{} keldi", w.product_name),
                    notes: String::new(),
                    due: now,
                    done: true,
                    done_at: Some(now),
                    owner_id: me,
                    customer_id: Some(w.customer_id),
                    company_id: None,
                    deal_id: None,
                    ticket_id: None,
                    priority: Priority::Normal,
                    outcome: Some(if by_sms { "SMS" } else { "Telegram" }.into()),
                    duration_min: 1,
                    daybook_task: None,
                });
            }
            WaitStatus::PickedUp => {
                if let Some(pid) = w.product_id {
                    let price = db.product(pid).map(|p| p.price).unwrap_or(w.value / w.qty.max(1) as Money);
                    let cashier = db.staff.iter().find(|s| s.branch_id == Some(w.branch_id) && s.role == Role::Pharmacist).map(|s| s.id);
                    db.add_purchase(Purchase {
                        id: 0,
                        customer_id: w.customer_id,
                        branch_id: w.branch_id,
                        at: now,
                        items: vec![LineItem { product_id: pid, qty: w.qty.max(1), price, discount_pct: 0 }],
                        total: 0,
                        points_earned: 0,
                        points_used: 0,
                        channel: SaleChannel::Pickup,
                        cashier_id: cashier,
                    });
                    sold = Some(price * w.qty.max(1) as Money);
                }
            }
            _ => {}
        }
        if let Some(x) = db.wait_item_mut(id) {
            x.status = to;
            if to == WaitStatus::Notified {
                x.notified_at = Some(now);
            }
        }
        db.log(now, format!("Defektura: {} → {}", w.product_name, to.slug()), false);
    });
    match to {
        WaitStatus::Arrived => toast(t("waitlist.toast_arrived"), "package-check", "success"),
        WaitStatus::Notified if by_sms => toast(t("waitlist.toast_notified_sms"), "message-square-text", "success"),
        WaitStatus::Notified => toast(t("waitlist.toast_notified"), "send", "success"),
        WaitStatus::Reserved => toast(t("waitlist.toast_reserved"), "bookmark", "success"),
        WaitStatus::PickedUp => match sold {
            Some(sum) => toast(t("waitlist.toast_sold").replace("{v}", &money(sum)), "shopping-bag", "success"),
            None => toast(t("waitlist.toast_picked"), "shopping-bag", "success"),
        },
        WaitStatus::Cancelled => toast(t("waitlist.toast_cancelled"), "circle-x", ""),
        WaitStatus::Waiting => {}
    }
}

/// Tells every customer whose medicine has arrived, in one go.
fn notify_all(ids: &[Id]) {
    let mut n = 0usize;
    mutate(|db| {
        let now = now();
        let me = db.settings.me;
        for id in ids {
            let Some(w) = db.wait_item(*id).cloned() else { continue };
            if w.status != WaitStatus::Arrived {
                continue;
            }
            let (tg, sms) = db.customer(w.customer_id).map(|c| (c.consent.telegram, c.consent.sms)).unwrap_or((false, false));
            db.add_activity(Activity {
                id: 0,
                kind: ActivityKind::Message,
                title: format!("{} keldi", w.product_name),
                notes: String::new(),
                due: now,
                done: true,
                done_at: Some(now),
                owner_id: me,
                customer_id: Some(w.customer_id),
                company_id: None,
                deal_id: None,
                ticket_id: None,
                priority: Priority::Normal,
                outcome: Some(if !tg && sms { "SMS" } else { "Telegram" }.into()),
                duration_min: 1,
                daybook_task: None,
            });
            if let Some(x) = db.wait_item_mut(*id) {
                x.status = WaitStatus::Notified;
                x.notified_at = Some(now);
            }
            n += 1;
        }
        if n > 0 {
            db.log(now, format!("Defektura: {n} ta mijozga xabar"), false);
        }
    });
    toast(t("waitlist.notified_all").replace("{n}", &n.to_string()), "send", "success");
}

#[component]
fn WaitCard(item: Item) -> Element {
    let l = lang();
    let now = now();
    let today = now.date();
    let w = item.w.clone();
    let id = w.id;
    let cid = w.customer_id;
    let requested = fmt::relative(w.at, now, l);
    let eta = w.eta.map(|d| fmt::due_in(d, today, l));
    let notified = w.notified_at.map(|d| t("waitlist.notified_ago").replace("{t}", &fmt::relative(d, now, l)));
    let in_stock_now = w.status == WaitStatus::Waiting && item.stock.map(|s| s > 0).unwrap_or(false);
    let stock_text = t("waitlist.in_stock_now").replace("{n}", &item.stock.unwrap_or(0).to_string());
    let acts = actions(w.status);
    let cancellable = !matches!(w.status, WaitStatus::PickedUp | WaitStatus::Cancelled);
    let done = w.status == WaitStatus::PickedUp;
    let cancel_title = t("waitlist.act_cancel");
    let tier_slug = item.tier.slug();
    let tier_label = t(item.tier.key());
    rsx! {
        div { class: "kanban-card", style: "cursor: default",
            div { class: "row top between gap-8",
                span { class: "strong small clamp-2", "{w.product_name}" }
                span { class: "badge sm outline num", "×{w.qty}" }
            }
            div { class: "row gap-8", style: "cursor: pointer", onclick: move |_| go(&format!("/contacts/{cid}")),
                Avatar { name: item.customer.clone(), size: "xs" }
                span { class: "small truncate grow", "{item.customer}" }
                if item.tier >= Tier::Gold {
                    span { class: "tier {tier_slug}", style: "padding: 0 6px", title: "{tier_label}", Icon { name: "crown", size: 12 } }
                }
            }
            div { class: "stack gap-4 xs muted",
                span { class: "row gap-4", Icon { name: "store", size: 12 } span { class: "truncate", "{item.branch}" } }
                span { class: "row gap-4", Icon { name: "clock", size: 12 } "{requested}" }
                if let Some(e) = eta {
                    span { class: "row gap-4", Icon { name: "truck", size: 12 } {t("waitlist.eta")} ": {e}" }
                }
                if let Some(n) = notified {
                    span { class: "row gap-4 tone-info", Icon { name: "send", size: 12 } "{n}" }
                }
            }
            if in_stock_now {
                div { class: "xs row gap-4 tone-success strong", Icon { name: "circle-check", size: 12 } "{stock_text}" }
            }
            if !w.note.is_empty() {
                div { class: "xs subtle", style: "font-style: italic", "“{w.note}”" }
            }
            div { class: "stack gap-8", style: "padding-top: 8px; border-top: 1px solid var(--c-border)",
                div { class: "row between gap-8",
                    span { class: "strong num small nowrap", "{money_short(w.value)}" }
                    if done {
                        Badge { text: t("wait_status.picked_up"), tone: "success", icon: "check" }
                    }
                    if cancellable {
                        button { class: "icon-btn sm", title: "{cancel_title}", onclick: move |_| advance(id, WaitStatus::Cancelled), Icon { name: "x", size: 14 } }
                    }
                }
                if !acts.is_empty() {
                    div { class: "row gap-4 wrap",
                        for (to, key, icon, cls) in acts {
                            button {
                                key: "{key}",
                                class: cls,
                                style: if cls.contains("success") { "flex: 1 1 auto; color: var(--c-on-primary)" } else { "flex: 1 1 auto" },
                                onclick: move |_| advance(id, to),
                                Icon { name: icon, size: 13 }
                                {t(key)}
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn WaitRow(item: Item) -> Element {
    let l = lang();
    let now = now();
    let w = item.w.clone();
    let id = w.id;
    let cid = w.customer_id;
    let requested = fmt::relative(w.at, now, l);
    let acts = actions(w.status);
    let status = t(w.status.key());
    let tone = status_tone(w.status);
    let cancellable = !matches!(w.status, WaitStatus::PickedUp | WaitStatus::Cancelled);
    let cancel_title = t("waitlist.act_cancel");
    rsx! {
        tr {
            td {
                div { class: "strong small", "{w.product_name}" }
                div { class: "xs muted only-mobile", "{item.customer} · {item.branch}" }
            }
            td { class: "m-hide",
                div { class: "cell-main", style: "cursor: pointer", onclick: move |_| go(&format!("/contacts/{cid}")),
                    Avatar { name: item.customer.clone(), size: "sm" }
                    span { class: "small truncate", "{item.customer}" }
                }
            }
            td { class: "m-hide small muted", "{item.branch}" }
            td { class: "num m-hide", "{w.qty}" }
            td { class: "num", span { class: "strong nowrap", "{money_short(w.value)}" } }
            td { class: "m-hide small muted nowrap", "{requested}" }
            td { Badge { text: status, tone, dot: true } }
            td {
                div { class: "row gap-4 end",
                    for (to, key, icon, cls) in acts {
                        button {
                            key: "{key}",
                            class: cls,
                            style: if cls.contains("success") { "color: var(--c-on-primary)" } else { "" },
                            onclick: move |_| advance(id, to),
                            Icon { name: icon, size: 13 }
                            span { class: "hide-mobile", {t(key)} }
                        }
                    }
                    if cancellable {
                        button { class: "icon-btn sm", title: "{cancel_title}", onclick: move |_| advance(id, WaitStatus::Cancelled), Icon { name: "x", size: 14 } }
                    }
                }
            }
        }
    }
}

#[component]
fn NewRequest(onclose: EventHandler<()>) -> Element {
    let today = today();
    let mut find = use_signal(String::new);
    let mut customer = use_signal(|| 0u32);
    let mut from_catalogue = use_signal(|| "catalogue".to_string());
    let mut product = use_signal(|| 0u32);
    let mut free_name = use_signal(String::new);
    let mut free_price = use_signal(String::new);
    let mut branch = use_signal(|| DB.peek().branches.first().map(|b| b.id).unwrap_or(0));
    let mut qty = use_signal(|| "1".to_string());
    let mut eta = use_signal(move || (today + Duration::days(3)).format("%Y-%m-%d").to_string());
    let mut note = use_signal(String::new);

    let (customers, products, branches) = {
        let db = DB.read();
        let cs = match_customers(&db, &find());
        let ps: Vec<(Id, String, Money)> = db.products.iter().map(|p| (p.id, p.name.clone(), p.price)).collect();
        let bs: Vec<(Id, String)> = db.branches.iter().map(|b| (b.id, b.name.clone())).collect();
        (cs, ps, bs)
    };
    let n: u32 = qty().trim().parse().unwrap_or(0);
    let catalogue = from_catalogue() == "catalogue";
    let price_each: Money = if catalogue {
        products.iter().find(|p| p.0 == product()).map(|p| p.2).unwrap_or(0)
    } else {
        free_price().chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0)
    };
    let value = price_each * n as Money;
    let named = if catalogue { product() != 0 } else { !free_name().trim().is_empty() };
    let valid = customer() != 0 && named && n > 0;
    let value_text = money(value);

    let save = move |_| {
        if !valid {
            return;
        }
        let now = now();
        let eta_date = NaiveDate::parse_from_str(&eta(), "%Y-%m-%d").ok();
        mutate(|db| {
            let id = db.new_id();
            let (pid, name) = if from_catalogue() == "catalogue" {
                (Some(product()), db.product_name(Some(product())))
            } else {
                (None, free_name().trim().to_string())
            };
            db.waitlist.insert(
                0,
                WaitItem {
                    id,
                    customer_id: customer(),
                    product_id: pid,
                    product_name: name.clone(),
                    branch_id: branch(),
                    qty: n,
                    at: now,
                    status: WaitStatus::Waiting,
                    eta: eta_date,
                    note: note().trim().to_string(),
                    notified_at: None,
                    value,
                },
            );
            db.log(now, format!("Defekturaga: {name}"), false);
        });
        toast(t("waitlist.toast_added"), "hourglass", "success");
        onclose.call(());
    };

    rsx! {
        Modal { title: t("waitlist.new_title"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("common.customer")} }
                    div { class: "search",
                        Icon { name: "search", size: 16 }
                        input {
                            class: "input",
                            value: "{find}",
                            placeholder: t("waitlist.find_customer"),
                            oninput: move |e| {
                                let v = e.value();
                                let found = match_customers(&DB.peek(), &v);
                                if found.len() == 1 {
                                    customer.set(found[0].0);
                                    branch.set(found[0].2);
                                }
                                find.set(v);
                            },
                            onmounted: move |e| async move {
                                let _ = e.set_focus(true).await;
                            },
                        }
                    }
                    select {
                        class: "select",
                        onchange: move |e| {
                            let id: Id = e.value().parse().unwrap_or(0);
                            customer.set(id);
                            if let Some(c) = DB.peek().customer(id) {
                                branch.set(c.home_branch);
                            }
                        },
                        option { value: "0", selected: customer() == 0, {t("waitlist.pick_customer")} }
                        for (id, name, _) in customers {
                            option { key: "{id}", value: "{id}", selected: id == customer(), "{name}" }
                        }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("common.product")} }
                    Segmented {
                        options: vec![("catalogue".into(), t("waitlist.from_catalogue")), ("free".into(), t("waitlist.free_text"))],
                        value: from_catalogue(),
                        onchange: move |v| from_catalogue.set(v),
                    }
                    if catalogue {
                        select { class: "select", onchange: move |e| product.set(e.value().parse().unwrap_or(0)),
                            option { value: "0", selected: product() == 0, "—" }
                            for (id, name, _) in products {
                                option { key: "{id}", value: "{id}", selected: id == product(), "{name}" }
                            }
                        }
                    } else {
                        div { class: "grid-2",
                            input { class: "input", value: "{free_name}", placeholder: t("waitlist.product_name"), oninput: move |e| free_name.set(e.value()) }
                            input { class: "input num", inputmode: "numeric", value: "{free_price}", placeholder: t("waitlist.price_each"), oninput: move |e| free_price.set(e.value()) }
                        }
                    }
                }
                div { class: "grid-3",
                    div { class: "field",
                        label { class: "label", {t("common.branch")} }
                        select { class: "select", onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                            for (id, name) in branches {
                                option { key: "{id}", value: "{id}", selected: id == branch(), "{name}" }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("waitlist.qty")} }
                        input { class: "input num", r#type: "number", min: "1", value: "{qty}", oninput: move |e| qty.set(e.value()) }
                    }
                    div { class: "field",
                        label { class: "label", {t("waitlist.eta")} }
                        input { class: "input", r#type: "date", value: "{eta}", oninput: move |e| eta.set(e.value()) }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("waitlist.note")} }
                    input { class: "input", value: "{note}", placeholder: t("waitlist.note_hint"), oninput: move |e| note.set(e.value()) }
                }
                div { class: "callout accent",
                    Icon { name: "bell-ring", size: 16 }
                    div {
                        if value > 0 {
                            div { class: "strong", "{value_text}" }
                        }
                        div { class: "small", {t("waitlist.new_hint")} }
                    }
                }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
            }
        }
    }
}

/// Customers matching a name or phone search (first 60, by name).
fn match_customers(db: &crm::Db, q: &str) -> Vec<(Id, String, Id)> {
    let fq = q.trim().to_lowercase();
    let digits: String = fq.chars().filter(|c| c.is_ascii_digit()).collect();
    let mut cs: Vec<(Id, String, Id)> = db
        .customers
        .iter()
        .filter(|c| !c.archived)
        .filter(|c| fq.is_empty() || c.name().to_lowercase().contains(&fq) || (digits.len() >= 3 && c.phone.contains(&digits)))
        .map(|c| (c.id, c.name(), c.home_branch))
        .collect();
    cs.sort_by(|a, b| a.1.cmp(&b.1));
    cs.truncate(60);
    cs
}

pub const STRINGS: &[Entry] = &[
    ("waitlist.sub", "Mijoz so‘ragan, bizda bo‘lmagan dorilar: har bir so‘rov javondan mijozgacha kuzatiladi", "Чего не оказалось в наличии: ведём каждую заявку до выдачи клиенту", "What customers asked for and we didn’t have, tracked to the shelf and back"),
    ("waitlist.new", "Yangi so‘rov", "Новая заявка", "New request"),
    ("waitlist.board", "Doska", "Доска", "Board"),
    ("waitlist.list", "Ro‘yxat", "Список", "List"),
    ("waitlist.kpi_waiting", "Kutilayotgan so‘rovlar", "Ждут поступления", "Waiting requests"),
    ("waitlist.kpi_waiting_foot", "{n} kutmoqda", "ждут: {n}", "{n} waiting"),
    ("waitlist.kpi_value", "Kutilayotgan talab", "Спрос в ожидании", "Demand waiting"),
    ("waitlist.kpi_value_foot", "keltirilmasa, savdo yo‘qoladi", "потерянные продажи, если не привезти", "lost sales if not fixed"),
    ("waitlist.kpi_arrived", "Keldi, xabar berilmagan", "Поступило, клиент не знает", "Arrived, not notified"),
    ("waitlist.kpi_arrived_foot", "bugunoq xabar bering", "сообщите сегодня", "let them know today"),
    ("waitlist.kpi_conv", "Konversiya", "Конверсия", "Conversion"),
    ("waitlist.kpi_conv_foot", "{n} / {m} so‘rov olib ketildi", "выкуплено {n} из {m}", "{n} of {m} picked up"),
    ("waitlist.hero_title", "Biz yo‘qotayotgan talab", "Спрос, который мы теряем", "Demand we’re losing"),
    ("waitlist.hero_text", "{n} ta mijoz bizda yo‘q dorini kutmoqda. Boshqa dorixonadan olsa, bu savdo butunlay yo‘qoladi.", "Клиентов, которые ждут лекарство, которого у нас нет: {n}. Купят в другой аптеке, и продажа потеряна.", "{n} customers are waiting for medicines we don’t have. If they buy elsewhere, the sale is gone."),
    ("waitlist.hero_where", "Qaysi filialda ko‘proq", "Где больше всего", "Where it piles up"),
    ("waitlist.hero_lost", "Allaqachon yo‘qotildi", "Уже потеряно", "Already lost"),
    ("waitlist.hero_saved", "Qaytarib olindi", "Возвращено", "Won back"),
    ("waitlist.hero_wait", "O‘rtacha kutish", "Среднее ожидание", "Average wait"),
    ("waitlist.most_wanted", "Eng ko‘p so‘ralayotgan", "Чаще всего спрашивают", "Most wanted"),
    ("waitlist.nothing_missing", "Hamma so‘ralgan dorilar bor", "Всё, что спрашивали, есть в наличии", "Everything asked for is in stock"),
    ("waitlist.send_order", "Daybook xaridiga yuborish", "Отправить в закупки Daybook", "Send to Daybook purchasing"),
    ("waitlist.order_sent", "Buyurtma ro‘yxati Daybook xarid bo‘limiga yuborildi: {n} ta pozitsiya", "Список отправлен в закупки Daybook: позиций {n}", "Order list sent to Daybook purchasing: {n} items"),
    ("waitlist.search", "Dori yoki mijoz…", "Лекарство или клиент…", "Medicine or customer…"),
    ("waitlist.requested", "So‘ralgan", "Запрошено", "Requested"),
    ("waitlist.eta", "Keladi", "Ожидается", "ETA"),
    ("waitlist.qty", "Soni", "Кол-во", "Qty"),
    ("waitlist.act_arrived", "Keldi", "Поступило", "Arrived"),
    ("waitlist.act_notify", "Xabar berish", "Уведомить", "Notify"),
    ("waitlist.act_reserve", "Bron", "Бронь", "Reserve"),
    ("waitlist.act_picked", "Olib ketdi", "Выкуплено", "Picked up"),
    ("waitlist.act_cancel", "So‘rovni bekor qilish", "Отменить заявку", "Cancel request"),
    ("waitlist.toast_arrived", "Keldi deb belgilandi: endi mijozga xabar bering", "Отмечено как поступившее: сообщите клиенту", "Marked as arrived: now let the customer know"),
    ("waitlist.toast_notified", "Mijozga Telegramda xabar yuborildi", "Клиенту отправлено сообщение в Telegram", "Telegram message sent to the customer"),
    ("waitlist.toast_notified_sms", "Mijozga SMS yuborildi", "Клиенту отправлено SMS", "SMS sent to the customer"),
    ("waitlist.toast_reserved", "Mijoz uchun 3 kunga bron qilindi", "Отложено для клиента на 3 дня", "Held for the customer for 3 days"),
    ("waitlist.toast_sold", "Savdo yozildi: {v}", "Продажа записана: {v}", "Sale recorded: {v}"),
    ("waitlist.toast_picked", "Mijoz olib ketdi", "Клиент забрал заказ", "Picked up by the customer"),
    ("waitlist.toast_cancelled", "So‘rov bekor qilindi", "Заявка отменена", "Request cancelled"),
    ("waitlist.toast_added", "Defekturaga yozildi", "Добавлено в дефектуру", "Added to the waitlist"),
    ("waitlist.notify_all", "Hammasiga xabar berish ({n})", "Уведомить всех ({n})", "Notify all ({n})"),
    ("waitlist.notified_all", "{n} ta mijozga xabar yuborildi", "Уведомлено клиентов: {n}", "{n} customers notified"),
    ("waitlist.notified_ago", "xabar berildi: {t}", "уведомлён: {t}", "notified {t}"),
    ("waitlist.in_stock_now", "Omborga keldi: {n} dona", "Уже в наличии: {n} шт.", "In stock now: {n}"),
    ("waitlist.empty_col", "Bo‘sh", "Пусто", "Empty"),
    ("waitlist.empty", "Bu yerda so‘rovlar yo‘q", "Здесь нет заявок", "No requests here"),
    ("waitlist.empty_text", "Mijoz so‘ragan dori bo‘lmasa, shu yerga yozing: kelganda xabar beramiz.", "Если лекарства нет в наличии, запишите клиента: сообщим, когда поступит.", "When a medicine is out of stock, add the customer here and we’ll tell them when it arrives."),
    ("waitlist.new_title", "Defekturaga yozish", "Записать в дефектуру", "Add to the waitlist"),
    ("waitlist.find_customer", "Ism yoki telefon…", "Имя или телефон…", "Name or phone…"),
    ("waitlist.pick_customer", "Mijozni tanlang", "Выберите клиента", "Choose a customer"),
    ("waitlist.from_catalogue", "Katalogdan", "Из каталога", "From the catalogue"),
    ("waitlist.free_text", "Katalogda yo‘q", "Нет в каталоге", "Not in the catalogue"),
    ("waitlist.product_name", "Dori nomi", "Название лекарства", "Medicine name"),
    ("waitlist.price_each", "Taxminiy narx, dona", "Примерная цена за шт.", "Estimated price each"),
    ("waitlist.note", "Izoh", "Комментарий", "Note"),
    ("waitlist.note_hint", "Masalan: kelishi bilan qo‘ng‘iroq qiling", "Например: позвонить, как только поступит", "e.g. call as soon as it arrives"),
    ("waitlist.new_hint", "Dori kelganda mijozga Telegramda avtomatik xabar boradi.", "Когда лекарство поступит, клиент получит сообщение в Telegram.", "When it arrives, the customer gets a Telegram message automatically."),
];
