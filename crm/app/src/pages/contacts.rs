//! Customers: the list (search, quick segments, filters, bulk actions) and the Customer 360
//! record: profile, AI summary, next best actions, timeline, purchases, medicines (health data,
//! every view audited), loyalty, care, notes and consent.

use std::collections::HashSet;

use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime};
use crm::analytics::{self, RfmSegment};
use crm::db::TimelineItem;
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

const PAGE: usize = 60;

// ---------------------------------------------------------------- helpers

fn short_date(d: NaiveDate, today: NaiveDate, l: Lang) -> String {
    let days = (today - d).num_days();
    if (0..=30).contains(&days) {
        fmt::due_in(d, today, l)
    } else {
        fmt::date(d, today, l)
    }
}

fn parse_dt(v: &str) -> Option<NaiveDateTime> {
    NaiveDateTime::parse_from_str(v, "%Y-%m-%dT%H:%M").ok()
}

fn parse_num(v: &str) -> i64 {
    let s = v.trim();
    let neg = s.starts_with('-') || s.starts_with('−');
    let digits: String = s.chars().filter(|c| c.is_ascii_digit()).collect();
    let n = digits.parse::<i64>().unwrap_or(0);
    if neg {
        -n
    } else {
        n
    }
}

fn risk_color(r: u8) -> &'static str {
    match r {
        0..=39 => "var(--c-success)",
        40..=69 => "var(--c-warning)",
        _ => "var(--c-danger)",
    }
}

fn wait_tone(s: WaitStatus) -> &'static str {
    match s {
        WaitStatus::Waiting => "warning",
        WaitStatus::Arrived => "success",
        WaitStatus::Notified => "info",
        WaitStatus::Reserved => "accent",
        WaitStatus::PickedUp | WaitStatus::Cancelled => "",
    }
}

fn ticket_tone(s: TicketStatus) -> &'static str {
    match s {
        TicketStatus::New => "accent",
        TicketStatus::InProgress => "info",
        TicketStatus::Waiting => "warning",
        TicketStatus::Resolved => "success",
        TicketStatus::Closed => "",
    }
}

fn tx_icon(k: TxKind) -> (&'static str, &'static str) {
    match k {
        TxKind::Earn => ("coins", "success"),
        TxKind::Redeem => ("shopping-bag", "accent"),
        TxKind::Bonus => ("gift", "info"),
        TxKind::Expire => ("hourglass", "muted"),
        TxKind::Adjust => ("sliders-horizontal", "warning"),
    }
}

/// The core summary ends with the RFM slug; show the translated segment name instead.
fn polish_summary(s: String, seg: RfmSegment, l: Lang) -> String {
    let raw = if l == Lang::UzCyrl { crm::i18n::to_cyrillic(seg.slug()) } else { seg.slug().to_string() };
    let label = t(seg.key());
    match s.rfind(&raw) {
        Some(i) => format!("{}{}{}", &s[..i], label, &s[i + raw.len()..]),
        None => s,
    }
}

fn points_text(n: i64, l: Lang) -> String {
    fmt::plural(n, l, "ball|балл|балла|баллов|point|points")
}

/// Logs a finished call with the customer.
fn log_call(id: Id) {
    let name = DB.peek().customer_name(Some(id));
    let title = format!("{}: {}", t("activity.call"), name);
    let outcome = t("contacts.call_outcome");
    let now = now();
    mutate(|db| {
        let me = db.settings.me;
        db.add_activity(Activity {
            id: 0,
            kind: ActivityKind::Call,
            title,
            notes: String::new(),
            due: now,
            done: true,
            done_at: Some(now),
            owner_id: me,
            customer_id: Some(id),
            company_id: None,
            deal_id: None,
            ticket_id: None,
            priority: Priority::Normal,
            outcome: Some(outcome),
            duration_min: 4,
            daybook_task: None,
        });
    });
    toast(t("contacts.call_logged"), "phone", "success");
}

/// Records a Telegram message sent to the customer (as a done activity) and toasts.
fn log_telegram(id: Id, title: String, toast_key: &str) {
    let msg = t(toast_key);
    let now = now();
    mutate(|db| {
        let me = db.settings.me;
        db.add_activity(Activity {
            id: 0,
            kind: ActivityKind::Message,
            title,
            notes: String::new(),
            due: now,
            done: true,
            done_at: Some(now),
            owner_id: me,
            customer_id: Some(id),
            company_id: None,
            deal_id: None,
            ticket_id: None,
            priority: Priority::Normal,
            outcome: None,
            duration_min: 1,
            daybook_task: None,
        });
    });
    toast(msg, "send", "success");
}

/// Opens the customer's conversation, creating a Telegram one when there is none.
fn open_message(id: Id) {
    let existing = DB.peek().conversations.iter().find(|c| c.customer_id == Some(id)).map(|c| c.id);
    let conv = match existing {
        Some(cid) => cid,
        None => {
            let (name, handle) = {
                let db = DB.peek();
                let c = db.customer(id);
                (
                    c.map(|c| c.name()).unwrap_or_default(),
                    c.and_then(|c| c.telegram.clone().or_else(|| Some(c.phone.clone()))).unwrap_or_default(),
                )
            };
            let text = t("contacts.conv_started");
            let now = now();
            let mut new_id = 0;
            mutate(|db| {
                let cid = db.new_id();
                let mid = db.new_id();
                new_id = cid;
                let me = db.settings.me;
                db.conversations.insert(
                    0,
                    Conversation {
                        id: cid,
                        channel: Channel::Telegram,
                        customer_id: Some(id),
                        lead_id: None,
                        title: name,
                        handle,
                        assigned_to: Some(me),
                        status: ConvStatus::Open,
                        unread: 0,
                        messages: vec![Message { id: mid, inbound: false, author_id: Some(me), text, at: now, kind: MsgKind::System }],
                        tags: vec![],
                        starred: false,
                    },
                );
            });
            new_id
        }
    };
    go(&format!("/inbox/{conv}"));
}

// ---------------------------------------------------------------- list

#[derive(Clone, PartialEq)]
struct Row {
    id: Id,
    name: String,
    phone: String,
    tier: Tier,
    rfm: Option<RfmSegment>,
    branch: String,
    ltv: Money,
    orders: u32,
    last: Option<NaiveDate>,
    points: i64,
    owner: Option<(String, u16)>,
    chronic: bool,
}

#[derive(Clone, PartialEq)]
struct ListHint {
    chip: String,
    rfm: Option<RfmSegment>,
    segment: Option<Id>,
    company: Option<Id>,
}

fn parse_hint(h: Option<String>) -> ListHint {
    let mut out = ListHint { chip: "all".into(), rfm: None, segment: None, company: None };
    for part in h.unwrap_or_default().split('&') {
        if let Some((k, v)) = part.split_once('=') {
            match k {
                "rfm" => out.rfm = RfmSegment::from_slug(v),
                "segment" => out.segment = v.parse().ok(),
                "company" => out.company = v.parse().ok(),
                "chip" => out.chip = v.to_string(),
                _ => {}
            }
        }
    }
    out
}

const CHIPS: &[(&str, &str, &str)] = &[
    ("all", "users", "common.all"),
    ("vip", "crown", "contacts.chip_vip"),
    ("chronic", "heart-pulse", "contacts.chip_chronic"),
    ("risk", "triangle-alert", "contacts.chip_risk"),
    ("new", "sparkles", "contacts.chip_new"),
    ("birthday", "cake", "contacts.chip_birthday"),
    ("corporate", "briefcase", "contacts.chip_corporate"),
    ("archived", "archive", "contacts.chip_archived"),
];

fn chip_match(chip: &str, c: &Customer, today: NaiveDate) -> bool {
    match chip {
        "vip" => c.tier >= Tier::Gold,
        "chronic" => !c.regimens.is_empty(),
        "risk" => c.orders > 0 && analytics::churn_risk(c, today) >= 50,
        "new" => (today - c.created).num_days() <= 30,
        "birthday" => c.birthday_in(today).map(|d| d <= 7).unwrap_or(false),
        "corporate" => c.company_id.is_some(),
        _ => true,
    }
}

fn matches_query(c: &Customer, q: &str, digits: &str) -> bool {
    if q.is_empty() {
        return true;
    }
    if c.name().to_lowercase().contains(q) {
        return true;
    }
    if digits.len() >= 3 {
        if c.phone.contains(digits) {
            return true;
        }
        let card: String = c.card_no.chars().filter(|x| x.is_ascii_digit()).collect();
        if card.contains(digits) {
            return true;
        }
    }
    c.telegram.as_deref().map(|t| t.to_lowercase().contains(q)).unwrap_or(false) || c.tags.iter().any(|t| t.to_lowercase().contains(q))
}

fn make_row(db: &crm::Db, c: &Customer, today: NaiveDate) -> Row {
    Row {
        id: c.id,
        name: c.name(),
        phone: c.phone.clone(),
        tier: c.tier,
        rfm: if c.orders > 0 { Some(analytics::rfm(c, today).segment) } else { None },
        branch: db.branch_name(Some(c.home_branch)),
        ltv: c.total_spent,
        orders: c.orders,
        last: c.last_purchase,
        points: c.points,
        owner: c.owner_id.and_then(|o| db.staff_member(o)).map(|s| (s.name.clone(), s.hue)),
        chronic: !c.regimens.is_empty(),
    }
}

#[component]
pub fn Contacts() -> Element {
    let hint = use_hook(|| parse_hint(take_hint()));
    let mut query = use_signal(String::new);
    let mut chip = use_signal(|| hint.chip.clone());
    let mut branch = use_signal(|| 0u32);
    let mut tier = use_signal(String::new);
    let mut sort = use_signal(|| "ltv".to_string());
    let mut rfm_f = use_signal(|| hint.rfm);
    let mut seg_f = use_signal(|| hint.segment);
    let mut co_f = use_signal(|| hint.company);
    let mut limit = use_signal(|| PAGE);
    let mut selected = use_signal(HashSet::<Id>::new);
    let mut bulk = use_signal(|| None::<&'static str>);

    let stats = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let counts: Vec<(&'static str, usize)> = CHIPS
            .iter()
            .map(|(k, _, _)| {
                let n = if *k == "archived" {
                    db.customers.iter().filter(|c| c.archived).count()
                } else {
                    db.customers.iter().filter(|c| !c.archived && chip_match(k, c, today)).count()
                };
                (*k, n)
            })
            .collect();
        let active = db.customers.iter().filter(|c| !c.archived && c.days_since_last(today).map(|d| d <= 90).unwrap_or(false)).count();
        let m0 = analytics::month_start(today);
        let new_month = db.customers.iter().filter(|c| !c.archived && c.created >= m0).count();
        (counts, active, new_month)
    });

    let rows = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let q = query().trim().to_lowercase();
        let digits: String = q.chars().filter(|c| c.is_ascii_digit()).collect();
        let (chip_v, branch_v, tier_v, rfm_v, sort_v, co_v) = (chip(), branch(), tier(), rfm_f(), sort(), co_f());
        let members: Option<HashSet<Id>> = seg_f().and_then(|sid| db.segment(sid).map(|s| db.segment_members(s, today).into_iter().collect()));
        let mut v: Vec<Row> = db
            .customers
            .iter()
            .filter(|c| if chip_v == "archived" { c.archived } else { !c.archived && chip_match(&chip_v, c, today) })
            .filter(|c| branch_v == 0 || c.home_branch == branch_v)
            .filter(|c| tier_v.is_empty() || c.tier.slug() == tier_v)
            .filter(|c| rfm_v.map_or(true, |r| c.orders > 0 && analytics::rfm(c, today).segment == r))
            .filter(|c| members.as_ref().map_or(true, |m| m.contains(&c.id)))
            .filter(|c| co_v.map_or(true, |co| c.company_id == Some(co)))
            .filter(|c| matches_query(c, &q, &digits))
            .map(|c| make_row(&db, c, today))
            .collect();
        match sort_v.as_str() {
            "last" => v.sort_by(|a, b| b.last.cmp(&a.last)),
            "name" => v.sort_by(|a, b| a.name.cmp(&b.name)),
            "points" => v.sort_by(|a, b| b.points.cmp(&a.points)),
            "orders" => v.sort_by(|a, b| b.orders.cmp(&a.orders)),
            _ => v.sort_by(|a, b| b.ltv.cmp(&a.ltv)),
        }
        v
    });

    let l = lang();
    let (counts, active, new_month) = stats();
    let all_n = counts.first().map(|x| x.1).unwrap_or(0);
    let subtitle = format!(
        "{} · {} · +{} {}",
        fmt::plural(all_n as i64, l, "mijoz|клиент|клиента|клиентов|customer|customers"),
        fmt::plural(active as i64, l, "faol|активный|активных|активных|active|active"),
        new_month,
        t("home.new_this_month")
    );
    let chip_items: Vec<(&'static str, &'static str, String, usize)> = CHIPS
        .iter()
        .map(|(k, icon, key)| (*k, *icon, t(key), counts.iter().find(|x| x.0 == *k).map(|x| x.1).unwrap_or(0)))
        .filter(|x| x.0 != "archived" || x.3 > 0)
        .collect();
    let branches: Vec<(Id, String)> = DB.read().branches.iter().map(|b| (b.id, b.name.clone())).collect();
    let seg_name = seg_f().and_then(|sid| DB.read().segment(sid).map(|s| s.name.clone()));
    let co_name = co_f().and_then(|cid| DB.read().company(cid).map(|c| c.name.clone()));

    let list = rows();
    let total = list.len();
    let lim = limit();
    let shown: Vec<Row> = list.iter().take(lim).cloned().collect();
    let sel = selected();
    let n_sel = sel.len();
    let all_sel = total > 0 && list.iter().all(|r| sel.contains(&r.id));
    let ids_all: Vec<Id> = list.iter().map(|r| r.id).collect();
    let shown_of = t("contacts.shown_of").replace("{a}", &shown.len().to_string()).replace("{b}", &total.to_string());
    let sort_v = sort();
    let has_filters = !query().is_empty() || chip() != "all" || branch() != 0 || !tier().is_empty() || rfm_f().is_some() || seg_f().is_some() || co_f().is_some();

    let mut toggle = move |id: Id| {
        let mut s = selected.write();
        if !s.remove(&id) {
            s.insert(id);
        }
    };
    let mut reset = move || {
        query.set(String::new());
        chip.set("all".into());
        branch.set(0);
        tier.set(String::new());
        rfm_f.set(None);
        seg_f.set(None);
        co_f.set(None);
        limit.set(PAGE);
    };
    let send_tg = move |_: MouseEvent| {
        let ids: Vec<Id> = selected.peek().iter().copied().collect();
        let reach = {
            let db = DB.peek();
            ids.iter().filter(|i| db.customer(**i).map(|c| c.consent.telegram && c.telegram.is_some()).unwrap_or(false)).count()
        };
        let total = ids.len();
        let text = format!("{}: {reach} / {total}", t("contacts.tg_sent"));
        let log = format!("Telegram · {reach}/{total}");
        mutate(|db| db.log(crate::state::now(), log, false));
        toast(text, "send", "success");
        selected.write().clear();
    };
    let export_sel = move |_: MouseEvent| {
        let n = selected.peek().len();
        toast(format!("{}: {n}", t("contacts.exported")), "download", "success");
    };
    let sort_icon = |k: &str| -> &'static str {
        if sort_v == k {
            "arrow-down"
        } else {
            ""
        }
    };
    let (si_ltv, si_orders, si_last, si_points) = (sort_icon("ltv"), sort_icon("orders"), sort_icon("last"), sort_icon("points"));

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.contacts"), subtitle,
                button { class: "btn", onclick: move |_| toast(t("contacts.import_toast"), "upload", "info"),
                    Icon { name: "upload", size: 16 }
                    span { class: "label-text", {t("common.import")} }
                }
                button {
                    class: "btn",
                    onclick: move |_| {
                        let n = rows.peek().len();
                        toast(format!("{}: {n}", t("contacts.exported")), "download", "success");
                    },
                    Icon { name: "download", size: 16 }
                    span { class: "label-text", {t("common.export")} }
                }
                button { class: "btn primary", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Customer),
                    Icon { name: "user-plus", size: 16 }
                    span { class: "label-text", {t("palette.new_customer")} }
                }
            }

            div { class: "chips",
                if let Some(r) = rfm_f() {
                    button { class: "chip on", onclick: move |_| rfm_f.set(None),
                        Icon { name: "layout-grid", size: 14 }
                        "RFM · " {t(r.key())}
                        Icon { name: "x", size: 14 }
                    }
                }
                if let Some(name) = seg_name.clone() {
                    button { class: "chip on", onclick: move |_| seg_f.set(None),
                        Icon { name: "layers", size: 14 }
                        "{name}"
                        Icon { name: "x", size: 14 }
                    }
                }
                if let Some(name) = co_name.clone() {
                    button { class: "chip on", onclick: move |_| co_f.set(None),
                        Icon { name: "briefcase", size: 14 }
                        "{name}"
                        Icon { name: "x", size: 14 }
                    }
                }
                for (k, icon, label, n) in chip_items {
                    button {
                        key: "{k}",
                        class: if chip() == k { "chip on" } else { "chip" },
                        onclick: move |_| {
                            chip.set(k.to_string());
                            limit.set(PAGE);
                        },
                        Icon { name: icon, size: 14 }
                        "{label}"
                        span { class: "count num", "{n}" }
                    }
                }
            }

            div { class: "card",
                div { class: "card-head line",
                    div { class: "toolbar grow",
                        div { class: "search",
                            Icon { name: "search", size: 16 }
                            input {
                                class: "input",
                                r#type: "search",
                                placeholder: t("contacts.search_hint"),
                                value: "{query}",
                                oninput: move |e| {
                                    query.set(e.value());
                                    limit.set(PAGE);
                                },
                            }
                        }
                        div { class: "chips", style: "flex: 1 1 480px; gap: 8px; padding-bottom: 0",
                        select { class: "select", style: "width: auto; flex: 0 0 auto",
                            onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                            option { value: "0", selected: branch() == 0, {t("common.all_branches")} }
                            for (bid, bname) in branches {
                                option { key: "{bid}", value: "{bid}", selected: branch() == bid, "{bname}" }
                            }
                        }
                        select { class: "select", style: "width: auto; flex: 0 0 auto",
                            onchange: move |e| tier.set(e.value()),
                            option { value: "", selected: tier().is_empty(), {t("contacts.all_tiers")} }
                            for tr_ in Tier::ALL.iter().copied() {
                                option { key: "{tr_.slug()}", value: "{tr_.slug()}", selected: tier() == tr_.slug(), {t(tr_.key())} }
                            }
                        }
                        select { class: "select", style: "width: auto; flex: 0 0 auto",
                            onchange: move |e| sort.set(e.value()),
                            option { value: "ltv", selected: sort_v == "ltv", {t("contacts.sort_ltv")} }
                            option { value: "last", selected: sort_v == "last", {t("contacts.sort_last")} }
                            option { value: "orders", selected: sort_v == "orders", {t("field.orders")} }
                            option { value: "points", selected: sort_v == "points", {t("contacts.sort_points")} }
                            option { value: "name", selected: sort_v == "name", {t("contacts.sort_name")} }
                        }
                        }
                    }
                    span { class: "small muted nowrap hide-mobile", "{shown_of}" }
                }

                if total == 0 {
                    Empty { icon: "search", title: t("common.no_results"), text: t("contacts.no_results_text"),
                        if has_filters {
                            button { class: "btn", onclick: move |_| reset(), Icon { name: "rotate-ccw", size: 15 } {t("contacts.reset_filters")} }
                        }
                    }
                } else {
                    div { class: "table-wrap hide-mobile",
                        table { class: "table",
                            thead {
                                tr {
                                    th { style: "width: 40px",
                                        input {
                                            r#type: "checkbox",
                                            checked: all_sel,
                                            style: "width: 16px; height: 16px; accent-color: var(--c-primary)",
                                            onchange: move |_| {
                                                let mut s = selected.write();
                                                if all_sel {
                                                    for i in ids_all.iter() {
                                                        s.remove(i);
                                                    }
                                                } else {
                                                    s.extend(ids_all.iter().copied());
                                                }
                                            },
                                        }
                                    }
                                    th { {t("common.customer")} }
                                    th { {t("field.tier")} }
                                    th { "RFM" }
                                    th { {t("common.branch")} }
                                    th { class: "num sortable", onclick: move |_| sort.set("ltv".into()),
                                        span { class: "row gap-4", style: "justify-content: flex-end", "LTV" if !si_ltv.is_empty() { Icon { name: si_ltv, size: 12 } } }
                                    }
                                    th { class: "num sortable", onclick: move |_| sort.set("orders".into()),
                                        span { class: "row gap-4", style: "justify-content: flex-end", {t("contacts.orders")} if !si_orders.is_empty() { Icon { name: si_orders, size: 12 } } }
                                    }
                                    th { class: "sortable", onclick: move |_| sort.set("last".into()),
                                        span { class: "row gap-4", {t("contacts.last_purchase")} if !si_last.is_empty() { Icon { name: si_last, size: 12 } } }
                                    }
                                    th { class: "num sortable", onclick: move |_| sort.set("points".into()),
                                        span { class: "row gap-4", style: "justify-content: flex-end", {t("field.points")} if !si_points.is_empty() { Icon { name: si_points, size: 12 } } }
                                    }
                                    th { {t("common.owner")} }
                                }
                            }
                            tbody {
                                for r in shown.iter().cloned() {
                                    ContactRow { key: "{r.id}", checked: sel.contains(&r.id), r: r.clone(), ontoggle: move |id| toggle(id) }
                                }
                            }
                        }
                    }
                    div { class: "list only-mobile",
                        for r in shown.iter().cloned() {
                            MobileRow { key: "m{r.id}", checked: sel.contains(&r.id), r: r.clone(), ontoggle: move |id| toggle(id) }
                        }
                    }
                    if total > lim {
                        div { class: "card-foot",
                            span { class: "small muted", "{shown_of}" }
                            button { class: "btn soft sm", onclick: move |_| limit.set(lim + PAGE),
                                Icon { name: "chevron-down", size: 15 }
                                {t("contacts.show_more")}
                            }
                        }
                    }
                }
            }

            if n_sel > 0 {
                div { class: "bulkbar hide-mobile", style: "width: fit-content; max-width: 100%",
                    span { class: "strong nowrap", {t("contacts.selected")} ": " span { class: "num", "{n_sel}" } }
                    button { class: "btn sm", onclick: send_tg, Icon { name: "send", size: 14 } {t("contacts.bulk_telegram")} }
                    button { class: "btn sm", onclick: move |_| bulk.set(Some("tag")), Icon { name: "tag", size: 14 } {t("action.add_tag")} }
                    button { class: "btn sm", onclick: move |_| bulk.set(Some("owner")), Icon { name: "user-check", size: 14 } {t("contacts.bulk_owner")} }
                    button { class: "btn sm", onclick: export_sel, Icon { name: "download", size: 14 } {t("common.export")} }
                    button { class: "icon-btn sm", style: "color: inherit", title: t("common.close"), onclick: move |_| selected.write().clear(), Icon { name: "x", size: 16 } }
                }
                div { class: "bulkbar only-mobile", style: "width: fit-content; max-width: 100%; bottom: calc(var(--tabbar-h) + 14px + env(safe-area-inset-bottom))",
                    span { class: "strong num", "{n_sel}" }
                    button { class: "btn sm", onclick: send_tg, Icon { name: "send", size: 15 } }
                    button { class: "btn sm", onclick: move |_| bulk.set(Some("tag")), Icon { name: "tag", size: 15 } }
                    button { class: "btn sm", onclick: move |_| bulk.set(Some("owner")), Icon { name: "user-check", size: 15 } }
                    button { class: "btn sm", onclick: export_sel, Icon { name: "download", size: 15 } }
                    button { class: "icon-btn sm", style: "color: inherit", onclick: move |_| selected.write().clear(), Icon { name: "x", size: 16 } }
                }
            }
            if bulk() == Some("tag") {
                BulkTagModal { ids: sel.iter().copied().collect::<Vec<Id>>(), onclose: move |done: bool| { bulk.set(None); if done { selected.write().clear(); } } }
            }
            if bulk() == Some("owner") {
                BulkOwnerModal { ids: sel.iter().copied().collect::<Vec<Id>>(), onclose: move |done: bool| { bulk.set(None); if done { selected.write().clear(); } } }
            }
        }
    }
}

#[component]
fn ContactRow(r: Row, checked: bool, ontoggle: EventHandler<Id>) -> Element {
    let l = lang();
    let today = today();
    let id = r.id;
    let last = r.last.map(|d| short_date(d, today, l)).unwrap_or_else(|| "—".into());
    let ph = phone(&r.phone);
    let ltv = money_short(r.ltv);
    let points = fmt::num(r.points);
    let (rfm_label, rfm_tone) = match r.rfm {
        Some(s) => (t(s.key()), s.tone()),
        None => ("—".to_string(), ""),
    };
    let row_style = if checked { "background: var(--c-accent-soft)" } else { "" };
    rsx! {
        tr { class: "click", style: row_style, onclick: move |_| go(&format!("/contacts/{id}")),
            td {
                onclick: move |e| {
                    e.stop_propagation();
                    ontoggle.call(id);
                },
                input { r#type: "checkbox", checked, style: "pointer-events: none; width: 16px; height: 16px; accent-color: var(--c-primary)" }
            }
            td {
                div { class: "cell-main",
                    Avatar { name: r.name.clone(), size: "sm" }
                    div { class: "stack gap-4", style: "gap: 1px; min-width: 0",
                        span { class: "strong truncate", "{r.name}" }
                        span { class: "xs muted num nowrap", "{ph}" }
                    }
                    if r.chronic { span { class: "subtle", title: t("contacts.chip_chronic"), Icon { name: "heart-pulse", size: 14 } } }
                }
            }
            td { TierBadge { tier: r.tier } }
            td { Badge { text: rfm_label, tone: rfm_tone } }
            td { class: "muted nowrap", "{r.branch}" }
            td { class: "num strong nowrap", "{ltv}" }
            td { class: "num", "{r.orders}" }
            td { class: "muted nowrap", "{last}" }
            td { class: "num", "{points}" }
            td {
                if let Some((name, hue)) = r.owner.clone() {
                    Avatar { name, hue, size: "xs" }
                } else {
                    span { class: "subtle", "—" }
                }
            }
        }
    }
}

#[component]
fn MobileRow(r: Row, checked: bool, ontoggle: EventHandler<Id>) -> Element {
    let l = lang();
    let today = today();
    let id = r.id;
    let last = r.last.map(|d| short_date(d, today, l)).unwrap_or_else(|| t("contacts.never"));
    let ltv = money_short(r.ltv);
    let points = points_text(r.points, l);
    rsx! {
        div { class: if checked { "list-row click active" } else { "list-row click" }, onclick: move |_| go(&format!("/contacts/{id}")),
            div {
                onclick: move |e| {
                    e.stop_propagation();
                    ontoggle.call(id);
                },
                if checked {
                    span { class: "avatar", style: "background: var(--c-primary); color: var(--c-on-primary)", Icon { name: "check", size: 16 } }
                } else {
                    Avatar { name: r.name.clone() }
                }
            }
            div { class: "meta",
                span { class: "title truncate", "{r.name}" }
                span { class: "sub row gap-8", TierBadge { tier: r.tier } span { class: "truncate", "{last}" } }
            }
            div { class: "stack gap-4", style: "align-items: flex-end; gap: 2px",
                span { class: "strong num small nowrap", "{ltv}" }
                span { class: "xs muted num nowrap", "{points}" }
            }
        }
    }
}

#[component]
fn BulkTagModal(ids: Vec<Id>, onclose: EventHandler<bool>) -> Element {
    let mut tag = use_signal(String::new);
    let suggestions: Vec<String> = {
        let db = DB.read();
        let mut all: Vec<String> = Vec::new();
        for c in db.customers.iter() {
            for tg in c.tags.iter() {
                if !all.contains(tg) {
                    all.push(tg.clone());
                }
            }
        }
        all.truncate(10);
        all
    };
    let n = ids.len();
    let valid = !tag().trim().is_empty();
    let save = move |_| {
        let v = tag().trim().to_string();
        if v.is_empty() {
            return;
        }
        let ids = ids.clone();
        let log = format!("{} «{v}» · {}", t("action.add_tag"), ids.len());
        mutate(|db| {
            for id in ids.iter() {
                if let Some(c) = db.customer_mut(*id) {
                    if !c.tags.iter().any(|x| x.eq_ignore_ascii_case(&v)) {
                        c.tags.push(v.clone());
                    }
                }
            }
            db.log(crate::state::now(), log, false);
        });
        toast(format!("{}: {n}", t("contacts.tag_added")), "tag", "success");
        onclose.call(true);
    };
    rsx! {
        Modal { title: t("contacts.tag_title"), onclose: move |_| onclose.call(false),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("common.tags")} }
                    input {
                        class: "input",
                        value: "{tag}",
                        placeholder: t("contacts.tag_placeholder"),
                        oninput: move |e| tag.set(e.value()),
                        onmounted: move |e| async move {
                            let _ = e.set_focus(true).await;
                        },
                    }
                }
                if !suggestions.is_empty() {
                    div { class: "row wrap gap-8",
                        for s in suggestions {
                            {
                                let v = s.clone();
                                rsx! {
                                    button { key: "{s}", class: "chip", onclick: move |_| tag.set(v.clone()), Icon { name: "tag", size: 13 } "{s}" }
                                }
                            }
                        }
                    }
                }
                div { class: "hint", {t("contacts.selected")} ": " span { class: "num", "{n}" } }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(false), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
            }
        }
    }
}

#[component]
fn BulkOwnerModal(ids: Vec<Id>, onclose: EventHandler<bool>) -> Element {
    let staff: Vec<(Id, String, u16, String)> = DB
        .read()
        .staff
        .iter()
        .filter(|s| s.active && matches!(s.role, Role::Pharmacist | Role::CallAgent | Role::Manager | Role::SalesRep | Role::Marketer))
        .map(|s| (s.id, s.name.clone(), s.hue, t(s.role.key())))
        .collect();
    let mut pick = use_signal(|| 0u32);
    let n = ids.len();
    let save = move |_| {
        let owner = pick();
        if owner == 0 {
            return;
        }
        let ids = ids.clone();
        let name = DB.peek().staff_name(Some(owner));
        let log = format!("{} → {name} · {}", t("common.owner"), ids.len());
        mutate(|db| {
            for id in ids.iter() {
                if let Some(c) = db.customer_mut(*id) {
                    c.owner_id = Some(owner);
                }
            }
            db.log(crate::state::now(), log, false);
        });
        toast(format!("{}: {name} · {n}", t("contacts.owner_set")), "user-check", "success");
        onclose.call(true);
    };
    rsx! {
        Modal { title: t("contacts.owner_title"), onclose: move |_| onclose.call(false),
            div { class: "list", style: "max-height: 52vh; overflow-y: auto; padding: 4px 0",
                for (sid, name, hue, role) in staff {
                    div {
                        key: "{sid}",
                        class: if pick() == sid { "list-row click active" } else { "list-row click" },
                        onclick: move |_| pick.set(sid),
                        Avatar { name: name.clone(), hue, size: "sm" }
                        div { class: "meta",
                            span { class: "title small", "{name}" }
                            span { class: "sub", "{role}" }
                        }
                        if pick() == sid { Icon { name: "check", size: 16, class: "tone-accent" } }
                    }
                }
            }
            div { class: "modal-foot",
                span { class: "small muted grow", {t("contacts.selected")} ": " span { class: "num", "{n}" } }
                button { class: "btn ghost", onclick: move |_| onclose.call(false), {t("common.cancel")} }
                button { class: "btn primary", disabled: pick() == 0, onclick: save, Icon { name: "check", size: 16 } {t("common.assign")} }
            }
        }
    }
}

// ---------------------------------------------------------------- customer 360

#[derive(Clone, Copy, PartialEq, Debug)]
enum Dialog {
    Task,
    Note,
    Bonus,
    Reserve(Option<Id>),
    Regimen,
    Archive,
    Edit,
}

#[component]
pub fn ContactDetail(id: u32) -> Element {
    rsx! {
        Customer360 { key: "{id}", id }
    }
}

#[component]
fn Customer360(id: Id) -> Element {
    let mut tab = use_signal(|| "overview");
    let mut dialog = use_signal(|| None::<Dialog>);
    let mut health_logged = use_signal(|| false);
    let mut adding_tag = use_signal(|| false);
    let mut new_tag = use_signal(String::new);

    let now = now();
    let today = now.date();
    let l = lang();
    let Some(c) = DB.read().customer(id).cloned() else {
        return rsx! {
            div { class: "page",
                Empty { icon: "user-x", title: t("contacts.not_found"), text: t("contacts.not_found_text"),
                    Link { to: Route::Contacts {}, class: "btn primary", Icon { name: "arrow-left", size: 16 } {t("nav.contacts")} }
                }
            }
        };
    };
    let (branch, owner, company, n_open_care, n_notes, privacy) = {
        let db = DB.read();
        (
            db.branch_name(Some(c.home_branch)),
            c.owner_id.and_then(|o| db.staff_member(o)).map(|s| (s.name.clone(), s.hue)),
            c.company_id.and_then(|cid| db.company(cid)).map(|co| (co.id, co.name.clone())),
            db.tickets.iter().filter(|t| t.customer_id == Some(id) && t.is_open()).count()
                + db.waitlist.iter().filter(|w| w.customer_id == id && matches!(w.status, WaitStatus::Waiting | WaitStatus::Arrived | WaitStatus::Reserved | WaitStatus::Notified)).count(),
            db.notes.iter().filter(|n| n.customer_id == Some(id)).count(),
            db.settings.privacy_mode,
        )
    };
    let name = c.name().trim().to_string();
    let rfm = if c.orders > 0 { Some(analytics::rfm(&c, today).segment) } else { None };
    let risk = analytics::churn_risk(&c, today);
    let since = t("contacts.since").replace("{d}", &fmt::date(c.created, today, l));
    let ph = phone(&c.phone);
    let tel = fmt::tel_href(&c.phone);
    let ltv = money_short(c.total_spent);
    let avg = money_short(c.avg_basket());
    let points_money = money(c.points);
    let points_n = points_text(c.points, l);
    let last = c.last_purchase.map(|d| short_date(d, today, l)).unwrap_or_else(|| t("contacts.never"));
    let last_sub = c.last_purchase.map(|d| fmt::date(d, today, l)).unwrap_or_default();
    let rcolor = risk_color(risk);
    let risk_word = if risk >= 70 {
        t("contacts.risk_high")
    } else if risk >= 40 {
        t("contacts.risk_mid")
    } else {
        t("contacts.risk_low")
    };
    let cashback = DB.read().settings.loyalty.cashback(c.tier);
    let cashback_s = format!("{} {}%", t("contacts.cashback"), cashback);

    let mut open_tab = move |k: &'static str| {
        if k == "medicines" && !health_logged() {
            let nm = DB.peek().customer_name(Some(id));
            let text = format!("{}: {nm}", t("contacts.health_viewed"));
            mutate(|db| db.log(crate::state::now(), text, true));
            health_logged.set(true);
        }
        tab.set(k);
    };
    let tabs: Vec<(&'static str, &'static str, String, Option<usize>)> = vec![
        ("overview", "layout-dashboard", t("contacts.tab_overview"), None),
        ("timeline", "history", t("contacts.tab_timeline"), None),
        ("purchases", "shopping-bag", t("contacts.tab_purchases"), Some(c.orders as usize)),
        ("medicines", "pill", t("contacts.tab_medicines"), Some(c.regimens.len())),
        ("loyalty", "gift", t("contacts.tab_loyalty"), None),
        ("care", "life-buoy", t("contacts.tab_care"), Some(n_open_care)),
        ("notes", "sticky-note", t("common.notes"), Some(n_notes)),
        ("consent", "shield-check", t("contacts.tab_consent"), None),
    ];
    let cur = tab();
    let tags = c.tags.clone();
    let archived = c.archived;

    rsx! {
        div { class: "page",
            div { class: "row between wrap",
                Link { to: Route::Contacts {}, class: "btn ghost sm", Icon { name: "arrow-left", size: 15 } {t("nav.contacts")} }
                if archived {
                    Badge { text: t("contacts.archived_badge"), tone: "warning", icon: "archive" }
                }
            }

            div { class: "card", style: "overflow: hidden",
                div { class: "card-body", style: "padding: 20px 22px",
                    div { class: "row top gap-16",
                        Avatar { name: name.clone(), size: "xl" }
                        div { class: "grow stack gap-8",
                            div { class: "row wrap gap-8",
                                h1 { style: "font-size: 24px; font-weight: 700; letter-spacing: -0.02em", "{name}" }
                                TierBadge { tier: c.tier }
                                if let Some(s) = rfm {
                                    Badge { text: t(s.key()), tone: s.tone(), dot: true }
                                }
                                button { class: "icon-btn sm", title: t("contacts.edit_profile"), onclick: move |_| dialog.set(Some(Dialog::Edit)), Icon { name: "pen-line", size: 15 } }
                            }
                            div { class: "row wrap small muted", style: "gap: 6px 16px",
                                a { href: "{tel}", class: "row gap-4 num", style: "color: var(--c-text); font-weight: 600", Icon { name: "phone", size: 14, class: "subtle" } "{ph}" }
                                if let Some(tg) = c.telegram.clone() {
                                    span { class: "row gap-4", Icon { name: "send", size: 14, class: "subtle" } "{tg}" }
                                }
                                span { class: "row gap-4", Icon { name: "store", size: 14, class: "subtle" } "{branch}" }
                                if let Some((oname, ohue)) = owner.clone() {
                                    span { class: "row gap-4", Avatar { name: oname.clone(), hue: ohue, size: "xs" } "{oname}" }
                                }
                                span { class: "row gap-4", Icon { name: "calendar", size: 14, class: "subtle" } "{since}" }
                                if let Some((cid, cname)) = company.clone() {
                                    Link { to: Route::CompanyDetail { id: cid }, class: "row gap-4 tone-accent strong", Icon { name: "briefcase", size: 14 } "{cname}" }
                                }
                            }
                            div { class: "row wrap gap-6", style: "gap: 6px",
                                for tg in tags.iter().cloned() {
                                    {
                                        let v = tg.clone();
                                        rsx! {
                                            span { key: "{tg}", class: "tag", style: "gap: 4px; padding-right: 3px",
                                                "{tg}"
                                                button {
                                                    class: "icon-btn",
                                                    style: "width: 16px; height: 16px; border-radius: 4px",
                                                    title: t("common.delete"),
                                                    onclick: move |_| {
                                                        let v = v.clone();
                                                        mutate(|db| if let Some(c) = db.customer_mut(id) { c.tags.retain(|x| *x != v) });
                                                    },
                                                    Icon { name: "x", size: 11 }
                                                }
                                            }
                                        }
                                    }
                                }
                                if adding_tag() {
                                    input {
                                        class: "input sm",
                                        style: "width: 160px; height: 24px; font-size: 12px",
                                        value: "{new_tag}",
                                        placeholder: t("common.tags"),
                                        oninput: move |e| new_tag.set(e.value()),
                                        onmounted: move |e| async move {
                                            let _ = e.set_focus(true).await;
                                        },
                                        onkeydown: move |e: KeyboardEvent| {
                                            match e.key() {
                                                Key::Enter => {
                                                    let v = new_tag().trim().to_string();
                                                    if !v.is_empty() {
                                                        mutate(|db| if let Some(c) = db.customer_mut(id) { if !c.tags.contains(&v) { c.tags.push(v.clone()) } });
                                                    }
                                                    new_tag.set(String::new());
                                                    adding_tag.set(false);
                                                }
                                                Key::Escape => adding_tag.set(false),
                                                _ => {}
                                            }
                                        },
                                        onblur: move |_| {
                                            let v = new_tag().trim().to_string();
                                            if !v.is_empty() {
                                                mutate(|db| if let Some(c) = db.customer_mut(id) { if !c.tags.contains(&v) { c.tags.push(v.clone()) } });
                                            }
                                            new_tag.set(String::new());
                                            adding_tag.set(false);
                                        },
                                    }
                                } else {
                                    button { class: "tag", style: "cursor: pointer; border-style: dashed; background: transparent", onclick: move |_| adding_tag.set(true),
                                        Icon { name: "plus", size: 11 }
                                        {t("contacts.add_tag")}
                                    }
                                }
                            }
                        }
                    }
                    div { class: "chips", style: "margin-top: 16px; gap: 8px",
                        button { class: "btn sm primary", onclick: move |_| log_call(id), Icon { name: "phone-call", size: 15 } {t("common.call")} }
                        button { class: "btn sm", onclick: move |_| open_message(id), Icon { name: "message-circle", size: 15 } {t("common.write")} }
                        button { class: "btn sm", onclick: move |_| dialog.set(Some(Dialog::Task)), Icon { name: "square-check", size: 15 } {t("common.task")} }
                        button { class: "btn sm", onclick: move |_| dialog.set(Some(Dialog::Note)), Icon { name: "sticky-note", size: 15 } {t("common.add_note")} }
                        button { class: "btn sm", onclick: move |_| dialog.set(Some(Dialog::Bonus)), Icon { name: "gift", size: 15 } {t("contacts.give_bonus")} }
                        button { class: "btn sm", onclick: move |_| dialog.set(Some(Dialog::Reserve(None))), Icon { name: "package-check", size: 15 } {t("contacts.reserve")} }
                    }
                }
                div { style: "display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); border-top: 1px solid var(--c-border); overflow: hidden",
                    StatCell { label: t("contacts.ltv"), value: ltv, sub: fmt::plural(c.orders as i64, l, "xarid|покупка|покупки|покупок|purchase|purchases") }
                    StatCell { label: t("contacts.orders"), value: fmt::num(c.orders as i64), sub: c.first_purchase.map(|d| format!("{} {}", t("contacts.first"), fmt::date(d, today, l))).unwrap_or_default() }
                    StatCell { label: t("contacts.avg_basket"), value: avg }
                    StatCell { label: t("contacts.points_value"), value: points_money, sub: points_n }
                    StatCell { label: t("contacts.last_purchase"), value: last, sub: last_sub }
                    div { class: "row gap-12", style: "background: var(--c-surface); padding: 12px 18px; box-shadow: -1px -1px 0 var(--c-border)",
                        Ring { pct: risk as f64, size: 46, stroke: 5, color: rcolor,
                            span { class: "num strong", style: "font-size: 12px", "{risk}" }
                        }
                        div { class: "stack gap-4", style: "gap: 2px",
                            span { class: "xs muted strong", {t("contacts.churn_risk")} }
                            span { class: "small strong", "{risk_word}" }
                        }
                    }
                }
            }

            div { class: "tabs",
                for (k, icon, label, count) in tabs {
                    button { key: "{k}", class: if cur == k { "tab on" } else { "tab" }, onclick: move |_| open_tab(k),
                        Icon { name: icon, size: 15 }
                        "{label}"
                        if let Some(n) = count {
                            if n > 0 { span { class: "count num", "{n}" } }
                        }
                    }
                }
            }

            match cur {
                "timeline" => rsx! { TimelineTab { id } },
                "purchases" => rsx! { PurchasesTab { id } },
                "medicines" => rsx! { MedicinesTab { id, on_dialog: move |d| dialog.set(Some(d)) } },
                "loyalty" => rsx! { LoyaltyTab { id, cashback: cashback_s.clone(), on_dialog: move |d| dialog.set(Some(d)) } },
                "care" => rsx! { CareTab { id, on_dialog: move |d| dialog.set(Some(d)) } },
                "notes" => rsx! { NotesTab { id, privacy } },
                "consent" => rsx! { ConsentTab { id, on_dialog: move |d| dialog.set(Some(d)) } },
                _ => rsx! { OverviewTab { id, on_tab: move |k| open_tab(k), on_dialog: move |d| dialog.set(Some(d)) } },
            }

            match dialog() {
                Some(Dialog::Task) => rsx! { TaskModal { id, onclose: move |_| dialog.set(None) } },
                Some(Dialog::Note) => rsx! {
                    Modal { title: t("common.add_note"), onclose: move |_| dialog.set(None),
                        div { class: "modal-body", NoteComposer { id, ondone: move |_| dialog.set(None) } }
                    }
                },
                Some(Dialog::Bonus) => rsx! { BonusModal { id, onclose: move |_| dialog.set(None) } },
                Some(Dialog::Reserve(p)) => rsx! { ReserveModal { id, product: p, onclose: move |_| dialog.set(None) } },
                Some(Dialog::Regimen) => rsx! { RegimenModal { id, onclose: move |_| dialog.set(None) } },
                Some(Dialog::Archive) => rsx! { ArchiveModal { id, onclose: move |_| dialog.set(None) } },
                Some(Dialog::Edit) => rsx! { EditModal { id, onclose: move |_| dialog.set(None) } },
                None => rsx! {},
            }
        }
    }
}

#[component]
fn StatCell(#[props(into)] label: String, #[props(into)] value: String, #[props(default, into)] sub: String) -> Element {
    rsx! {
        div { class: "stack", style: "gap: 3px; background: var(--c-surface); padding: 14px 18px; min-width: 0; box-shadow: -1px -1px 0 var(--c-border)",
            span { class: "xs muted strong truncate", "{label}" }
            span { class: "num truncate", style: "font-size: 19px; font-weight: 700; letter-spacing: -0.01em", "{value}" }
            if !sub.is_empty() { span { class: "xs subtle truncate", "{sub}" } }
        }
    }
}

// ---------------------------------------------------------------- overview

#[component]
fn OverviewTab(id: Id, on_tab: EventHandler<&'static str>, on_dialog: EventHandler<Dialog>) -> Element {
    let now = now();
    let today = now.date();
    let l = lang();
    let mut done = use_signal(Vec::<String>::new);
    let Some(c) = DB.read().customer(id).cloned() else { return rsx! {} };
    let (summary, actions, recent, connected, favs, referrer, friends, company) = {
        let db = DB.read();
        let s = analytics::customer_summary(&db, id, now, l);
        let a = analytics::next_best_actions(&db, id, now, l);
        let r: Vec<TimelineItem> = db.customer_timeline(id, l).into_iter().take(6).collect();
        let favs: Vec<(String, u32)> = db.favourite_products(id, 5).into_iter().map(|(pid, n)| (db.product_name(Some(pid)), n)).collect();
        let referrer = c.referred_by.and_then(|r| db.customer(r)).map(|r| (r.id, r.name()));
        let friends: Vec<(Id, String)> = db.customers.iter().filter(|x| x.referred_by == Some(id)).map(|x| (x.id, x.name())).collect();
        let company = c.company_id.and_then(|cid| db.company(cid)).map(|co| (co.id, co.name.clone(), co.kind));
        (s, a, r, db.settings.daybook.connected && db.settings.ai.enabled, favs, referrer, friends, company)
    };
    let summary = match (c.orders > 0).then(|| analytics::rfm(&c, today).segment) {
        Some(seg) => polish_summary(summary, seg, l),
        None => t("contacts.ai_new").replace("{d}", &fmt::date(c.created, today, l)),
    };
    let ai_note = if connected { t("contacts.ai_cloud") } else { t("contacts.ai_local") };
    let ai_chip = if connected { "Claude Haiku".to_string() } else { t("contacts.ai_on_device") };
    let birthday = c.birth_date.map(|b| {
        let age = c.age(today).unwrap_or(0) as i64;
        format!("{} · {}", fmt::date(b, today, l), fmt::plural(age, l, "yosh|год|года|лет|year|years"))
    });
    let mut about: Vec<(String, String)> = Vec::new();
    if let Some(b) = birthday {
        about.push((t("contacts.birthday"), b));
    }
    about.push((t("field.gender"), t(c.gender.key())));
    if !c.district.is_empty() {
        about.push((t("contacts.district"), c.district.clone()));
    }
    about.push((t("field.source"), t(c.source.key())));
    about.push((t("common.language"), match c.lang {
        Lang::Ru => t("lang.ru"),
        Lang::En => t("lang.en"),
        _ => t("lang.uz"),
    }));
    about.push((t("contacts.card"), c.card_no.clone()));
    if let Some(n) = c.nps {
        about.push((t("contacts.nps"), format!("{n} / 10")));
    }
    let profile_note = c.notes.clone();

    rsx! {
        div { class: "grid-main",
            div { class: "stack gap-16",
                div { class: "ai-panel stack gap-8",
                    div { class: "row between",
                        div { class: "card-title", Icon { name: "sparkles", size: 16, class: "tone-accent" } {t("contacts.ai_summary")} }
                        span { class: "ai-chip", Icon { name: "sparkles", size: 12 } "{ai_chip}" }
                    }
                    p { style: "font-size: 14.5px; line-height: 1.6", "{summary}" }
                    if !profile_note.is_empty() {
                        div { class: "callout accent", Icon { name: "pin", size: 15 } span { "{profile_note}" } }
                    }
                    div { class: "xs subtle row gap-4", Icon { name: "info", size: 12 } "{ai_note}" }
                }

                div { class: "card",
                    div { class: "card-head",
                        div { class: "card-title", Icon { name: "wand-sparkles", size: 16, class: "tone-accent" } {t("contacts.nba")} }
                        if !actions.is_empty() { span { class: "badge accent", "{actions.len()}" } }
                    }
                    div { class: "list", style: "margin-top: 8px",
                        if actions.is_empty() {
                            Empty { icon: "circle-check", title: t("contacts.nba_empty") }
                        }
                        for (i, a) in actions.iter().cloned().enumerate() {
                            {
                                let is_done = done().contains(&a.text);
                                // A medicine that already ran out: the advice is to call, so the button calls.
                                let kind: &'static str = if a.kind == "remind" && a.tone == "danger" { "call" } else { a.kind };
                                let (label, icon): (String, &'static str) = match kind {
                                    "remind" => (t("contacts.nba_remind"), "send"),
                                    "reserve" => (t("contacts.reserve"), "package-check"),
                                    "bonus" => (t("contacts.nba_bonus"), "gift"),
                                    "call" => (t("common.call"), "phone-call"),
                                    "offer" => (t("contacts.nba_offer"), "send"),
                                    "upgrade" => (t("contacts.nba_upgrade"), "send"),
                                    _ => (t("contacts.nba_consent"), "shield-check"),
                                };
                                let text = a.text.clone();
                                rsx! {
                                    div { key: "{i}", class: "list-row",
                                        IconTile { icon: a.icon, tone: a.tone, size: "sm" }
                                        div { class: "meta", span { class: "small", style: "line-height: 1.45", "{a.text}" } }
                                        if is_done {
                                            span { class: "badge success nowrap", Icon { name: "check", size: 13 } {t("common.done")} }
                                        } else {
                                            button {
                                                class: "btn sm nowrap",
                                                onclick: move |_| {
                                                    run_action(id, kind, &text);
                                                    if kind == "reserve" {
                                                        on_dialog.call(Dialog::Reserve(None));
                                                    } else {
                                                        done.write().push(text.clone());
                                                    }
                                                },
                                                Icon { name: icon, size: 14 }
                                                "{label}"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                div { class: "card",
                    div { class: "card-head",
                        div { class: "card-title", Icon { name: "history", size: 16, class: "subtle" } {t("contacts.recent")} }
                        button { class: "btn ghost sm", onclick: move |_| on_tab.call("timeline"), {t("contacts.full_timeline")} Icon { name: "arrow-right", size: 14 } }
                    }
                    div { class: "card-body",
                        if recent.is_empty() {
                            Empty { icon: "history", title: t("common.empty") }
                        } else {
                            Timeline { items: recent.clone() }
                        }
                    }
                }
            }

            div { class: "stack gap-16",
                UpcomingTasks { id, on_dialog }
                div { class: "card",
                    div { class: "card-head", div { class: "card-title", Icon { name: "id-card", size: 16, class: "subtle" } {t("contacts.about")} } }
                    div { class: "card-body", KeyValues { items: about } }
                }
                div { class: "card",
                    div { class: "card-head", div { class: "card-title", Icon { name: "pill", size: 16, class: "subtle" } {t("contacts.favourites")} } }
                    div { class: "list", style: "margin-top: 6px",
                        if favs.is_empty() {
                            div { class: "list-row small muted", {t("contacts.never")} }
                        }
                        for (k, (pname, n)) in favs.into_iter().enumerate() {
                            div { key: "{k}", class: "list-row", style: "padding-top: 9px; padding-bottom: 9px",
                                span { class: "ic muted sm", Icon { name: "pill", size: 14 } }
                                span { class: "grow small truncate", "{pname}" }
                                span { class: "badge sm num", "×{n}" }
                            }
                        }
                    }
                }
                if let Some((cid, cname, kind)) = company {
                    div { class: "card",
                        div { class: "card-head", div { class: "card-title", Icon { name: "briefcase", size: 16, class: "subtle" } {t("common.company")} } }
                        div { style: "margin-top: 6px",
                            Link { to: Route::CompanyDetail { id: cid }, class: "list-row click",
                                IconTile { icon: crm::db::org_icon(kind), tone: "info", size: "sm" }
                                div { class: "meta", span { class: "title small truncate", "{cname}" } span { class: "sub", {t(kind.key())} } }
                                Icon { name: "chevron-right", size: 16, class: "subtle" }
                            }
                        }
                    }
                }
                if referrer.is_some() || !friends.is_empty() {
                    div { class: "card",
                        div { class: "card-head", div { class: "card-title", Icon { name: "hand-heart", size: 16, class: "subtle" } {t("source.referral")} } }
                        div { class: "list", style: "margin-top: 6px",
                            if let Some((rid, rname)) = referrer {
                                Link { to: Route::ContactDetail { id: rid }, class: "list-row click",
                                    Avatar { name: rname.clone(), size: "sm" }
                                    div { class: "meta", span { class: "title small", "{rname}" } span { class: "sub", {t("contacts.referred_by")} } }
                                }
                            }
                            for (fid, fname) in friends {
                                Link { key: "{fid}", to: Route::ContactDetail { id: fid }, class: "list-row click",
                                    Avatar { name: fname.clone(), size: "sm" }
                                    div { class: "meta", span { class: "title small", "{fname}" } span { class: "sub", {t("contacts.friend")} } }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn UpcomingTasks(id: Id, on_dialog: EventHandler<Dialog>) -> Element {
    let now = now();
    let l = lang();
    let tasks: Vec<(Id, String, NaiveDateTime, ActivityKind, Priority)> = {
        let db = DB.read();
        let mut v: Vec<&Activity> = db.activities.iter().filter(|a| a.customer_id == Some(id) && !a.done).collect();
        v.sort_by_key(|a| a.due);
        v.into_iter().take(5).map(|a| (a.id, a.title.clone(), a.due, a.kind, a.priority)).collect()
    };
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "calendar-check", size: 16, class: "tone-accent" } {t("contacts.upcoming")} }
                button { class: "btn ghost sm", onclick: move |_| on_dialog.call(Dialog::Task), Icon { name: "plus", size: 14 } {t("common.task")} }
            }
            div { class: "list", style: "margin-top: 6px",
                if tasks.is_empty() {
                    div { class: "list-row small muted", {t("contacts.no_upcoming")} }
                }
                for (aid, title, due, kind, prio) in tasks {
                    {
                        let when = fmt::relative(due, now, l);
                        let when_cls = if due < now { "tone-danger strong" } else { "" };
                        let icon = crm::db::activity_icon(kind);
                        let urgent = matches!(prio, Priority::High | Priority::Urgent);
                        let ptone: &'static str = if prio == Priority::Urgent { "danger" } else { "warning" };
                        rsx! {
                            div { key: "{aid}", class: "list-row",
                                button {
                                    class: "check-circle",
                                    title: t("common.done"),
                                    onclick: move |_| {
                                        mutate(|db| db.complete_activity(aid, crate::state::now()));
                                        toast(t("contacts.task_done"), "check", "success");
                                    },
                                    Icon { name: "check", size: 13 }
                                }
                                div { class: "meta",
                                    span { class: "title small truncate", "{title}" }
                                    span { class: "sub row gap-4", Icon { name: icon, size: 12 } span { class: when_cls, "{when}" } }
                                }
                                if urgent { Badge { text: t(prio.key()), tone: ptone } }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Performs a next-best-action in one click.
fn run_action(id: Id, kind: &str, text: &str) {
    let now = now();
    match kind {
        "remind" => log_telegram(id, format!("Telegram · {}", t("contacts.nba_remind")), "contacts.reminder_sent"),
        "bonus" => {
            let pts = DB.peek().settings.loyalty.birthday_bonus;
            let note = t("contacts.birthday");
            mutate(|db| db.give_points(id, pts, TxKind::Bonus, note, now));
            toast(format!("{}: +{}", t("contacts.bonus_given"), fmt::num(pts)), "gift", "success");
        }
        "call" => log_call(id),
        "offer" | "upgrade" => log_telegram(id, format!("Telegram · {}", text.chars().take(60).collect::<String>()), "contacts.offer_sent"),
        "consent" => {
            let today = now.date();
            mutate(|db| {
                if let Some(c) = db.customer_mut(id) {
                    c.consent.telegram = true;
                    c.consent.given_on = Some(today);
                }
            });
            toast(t("contacts.consent_saved"), "shield-check", "success");
        }
        _ => {}
    }
}

#[component]
fn Timeline(items: Vec<TimelineItem>) -> Element {
    let now = now();
    let l = lang();
    let privacy = DB.read().settings.privacy_mode;
    rsx! {
        div { class: "timeline",
            for (i, it) in items.iter().cloned().enumerate() {
                {
                    let when = fmt::relative(it.at, now, l);
                    let route = it.route.clone();
                    let clickable = route.is_some();
                    let body_cls = if privacy && it.kind == "note" { "small muted mask" } else { "small muted" };
                    rsx! {
                        div {
                            key: "{i}",
                            class: "tl-item",
                            style: if clickable { "cursor: pointer" } else { "" },
                            onclick: move |_| {
                                if let Some(r) = &route {
                                    go(r);
                                }
                            },
                            span { class: "ic {it.tone}", Icon { name: it.icon, size: 15 } }
                            div { class: "tl-body",
                                div { class: "tl-head",
                                    span { class: "strong small truncate", "{it.title}" }
                                    span { class: "xs subtle nowrap", "{when}" }
                                }
                                if !it.body.is_empty() {
                                    div { class: body_cls, style: "margin-top: 2px", "{it.body}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- timeline

#[component]
fn TimelineTab(id: Id) -> Element {
    let l = lang();
    let mut kind = use_signal(|| "all");
    let mut limit = use_signal(|| PAGE);
    let all: Vec<TimelineItem> = DB.read().customer_timeline(id, l);
    let kinds: Vec<(&'static str, String)> = vec![
        ("all", t("common.all")),
        ("purchase", t("contacts.tab_purchases")),
        ("activity", t("contacts.k_activity")),
        ("message", t("contacts.k_message")),
        ("ticket", t("nav.tickets")),
        ("note", t("common.notes")),
        ("waitlist", t("nav.waitlist")),
    ];
    let chips: Vec<(&'static str, String, usize)> = kinds
        .into_iter()
        .map(|(k, label)| {
            let n = if k == "all" { all.len() } else { all.iter().filter(|x| x.kind == k).count() };
            (k, label, n)
        })
        .filter(|x| x.0 == "all" || x.2 > 0)
        .collect();
    let cur = kind();
    let filtered: Vec<TimelineItem> = all.into_iter().filter(|x| cur == "all" || x.kind == cur).collect();
    let total = filtered.len();
    let lim = limit();
    let shown: Vec<TimelineItem> = filtered.into_iter().take(lim).collect();
    rsx! {
        div { class: "card",
            div { class: "card-head line",
                div { class: "chips",
                    for (k, label, n) in chips {
                        button {
                            key: "{k}",
                            class: if cur == k { "chip on" } else { "chip" },
                            onclick: move |_| {
                                kind.set(k);
                                limit.set(PAGE);
                            },
                            "{label}"
                            span { class: "count num", "{n}" }
                        }
                    }
                }
            }
            div { class: "card-body",
                if shown.is_empty() {
                    Empty { icon: "history", title: t("common.empty") }
                } else {
                    Timeline { items: shown }
                }
            }
            if total > lim {
                div { class: "card-foot",
                    span { class: "small muted num", "{lim} / {total}" }
                    button { class: "btn soft sm", onclick: move |_| limit.set(lim + PAGE), Icon { name: "chevron-down", size: 15 } {t("contacts.show_more")} }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- purchases

#[component]
fn PurchasesTab(id: Id) -> Element {
    let now = now();
    let today = now.date();
    let l = lang();
    let mut limit = use_signal(|| 30usize);
    let (rows, months, total, count) = {
        let db = DB.read();
        let ps = db.purchases_of(id);
        let m0 = analytics::month_start(today);
        let start = analytics::add_months(m0, -11);
        let mut months: Vec<(NaiveDate, f64)> = (0..12).map(|i| (analytics::add_months(start, i), 0.0)).collect();
        for p in ps.iter() {
            let m = analytics::month_start(p.at.date());
            if let Some(x) = months.iter_mut().find(|x| x.0 == m) {
                x.1 += p.total as f64;
            }
        }
        let total: Money = ps.iter().map(|p| p.total).sum();
        let count = ps.len();
        let rows: Vec<(Id, NaiveDateTime, String, SaleChannel, String, Money, i64, i64)> = ps
            .iter()
            .take(limit())
            .map(|p| {
                let items: Vec<String> = p
                    .items
                    .iter()
                    .map(|i| if i.qty > 1 { format!("{} ×{}", db.product_name(Some(i.product_id)), i.qty) } else { db.product_name(Some(i.product_id)) })
                    .collect();
                (p.id, p.at, db.branch_name(Some(p.branch_id)), p.channel, items.join(", "), p.total, p.points_earned, p.points_used)
            })
            .collect();
        (rows, months, total, count)
    };
    let labels: Vec<String> = months.iter().map(|(m, _)| fmt::month_short(m.month(), l)).collect();
    let values: Vec<f64> = months.iter().map(|x| x.1).collect();
    let year_sum: f64 = values.iter().sum();
    let lim = limit();
    rsx! {
        div { class: "stack gap-16",
            div { class: "card",
                div { class: "card-head",
                    div {
                        div { class: "card-title", Icon { name: "chart-column", size: 16, class: "subtle" } {t("contacts.spend_12m")} }
                        div { class: "kpi-value", style: "font-size: 22px; margin-top: 4px", "{money_short(year_sum as i64)}" }
                    }
                    div { class: "stack gap-4", style: "align-items: flex-end",
                        span { class: "small muted", {t("common.total")} ": " b { class: "num", style: "color: var(--c-text)", "{money_short(total)}" } }
                        span { class: "small muted", {t("contacts.orders")} ": " b { class: "num", style: "color: var(--c-text)", "{count}" } }
                    }
                }
                div { class: "card-body", BarChart { labels, values, height: 160, highlight: Some(11), money: true } }
            }
            div { class: "card",
                if rows.is_empty() {
                    Empty { icon: "shopping-bag", title: t("contacts.never") }
                }
                div { class: "list",
                    for (pid, at, branch, channel, items, sum, earned, used) in rows {
                        {
                            let when = fmt::datetime(at, now, l);
                            let sum_s = money(sum);
                            rsx! {
                                div { key: "{pid}", class: "list-row", style: "align-items: flex-start",
                                    span { class: "ic success sm", Icon { name: "shopping-bag", size: 14 } }
                                    div { class: "meta",
                                        div { class: "row between wrap", style: "gap: 4px 10px",
                                            span { class: "title small", "{when} · {branch}" }
                                            span { class: "num strong small nowrap", "{sum_s}" }
                                        }
                                        span { class: "sub", style: "line-height: 1.45", "{items}" }
                                        div { class: "row wrap gap-6", style: "gap: 6px; margin-top: 3px",
                                            Badge { text: t(channel.key()), icon: "store" }
                                            if earned > 0 { span { class: "badge sm success num", "+{points_text(earned, l)}" } }
                                            if used > 0 { span { class: "badge sm warning num", "−{points_text(used, l)}" } }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                if count > lim {
                    div { class: "card-foot",
                        span { class: "small muted num", "{lim} / {count}" }
                        button { class: "btn soft sm", onclick: move |_| limit.set(lim + 30), Icon { name: "chevron-down", size: 15 } {t("contacts.show_more")} }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- medicines

#[component]
fn MedicinesTab(id: Id, on_dialog: EventHandler<Dialog>) -> Element {
    let today = today();
    let l = lang();
    let mut allergy = use_signal(String::new);
    let Some(c) = DB.read().customer(id).cloned() else { return rsx! {} };
    let privacy = DB.read().settings.privacy_mode;
    let mask = if privacy { "mask" } else { "" };
    if !c.consent.health_data {
        return rsx! {
            div { class: "card pad stack gap-16", style: "max-width: 720px",
                div { class: "row top gap-12",
                    IconTile { icon: "shield-alert", tone: "warning", size: "lg" }
                    div { class: "stack gap-4",
                        div { class: "strong", style: "font-size: 15.5px", {t("contacts.no_consent_title")} }
                        p { class: "muted", style: "line-height: 1.55", {t("contacts.no_consent_text")} }
                    }
                }
                div { class: "callout", Icon { name: "lock", size: 15 } span { {t("contacts.health_audit")} } }
                div { class: "row",
                    button {
                        class: "btn primary",
                        onclick: move |_| {
                            let log = format!("{}: {}", t("contacts.consent_health"), DB.peek().customer_name(Some(id)));
                            let now = crate::state::now();
                            mutate(|db| {
                                if let Some(c) = db.customer_mut(id) {
                                    c.consent.health_data = true;
                                    c.consent.given_on = Some(now.date());
                                }
                                db.log(now, log, true);
                            });
                            toast(t("contacts.consent_saved"), "shield-check", "success");
                        },
                        Icon { name: "shield-check", size: 16 }
                        {t("contacts.record_consent")}
                    }
                }
            }
        };
    }
    let regimens: Vec<(usize, Regimen, String, bool)> = {
        let db = DB.read();
        c.regimens
            .iter()
            .cloned()
            .enumerate()
            .map(|(i, r)| {
                let stock = db.product(r.product_id).map(|p| p.stock_at(c.home_branch) > 0).unwrap_or(false);
                (i, r.clone(), db.product_name(Some(r.product_id)), stock)
            })
            .collect()
    };
    let allergies = c.allergies.clone();
    rsx! {
        div { class: "stack gap-16",
            div { class: "row between wrap",
                div { class: "row gap-8",
                    span { class: "section-title", {t("contacts.health_title")} }
                    span { class: "badge info", Icon { name: "lock", size: 12 } {t("contacts.health_audit")} }
                }
                button { class: "btn soft sm", onclick: move |_| on_dialog.call(Dialog::Regimen), Icon { name: "plus", size: 15 } {t("contacts.add_regimen")} }
            }
            if regimens.is_empty() {
                div { class: "card", Empty { icon: "pill", title: t("contacts.no_regimens"), text: t("contacts.no_regimens_text") } }
            }
            div { class: "grid-2",
                for (i, r, pname, in_stock) in regimens {
                    {
                        let left = r.days_left(today);
                        let used = (r.pack_days as i64 - left).clamp(0, r.pack_days as i64);
                        let pct = if r.pack_days == 0 { 0.0 } else { used as f64 / r.pack_days as f64 * 100.0 };
                        let tone: &'static str = if left < 0 { "danger" } else if left <= 3 { "warning" } else { "success" };
                        let ptone: &'static str = if left < 0 { "danger" } else if left <= 3 { "warning" } else { "" };
                        let due = fmt::due_in(r.next_due(), today, l);
                        let bought = fmt::date(r.last_bought, today, l);
                        let pid = r.product_id;
                        let remind = r.remind;
                        let pack_line = format!("{} {} / {}", t("contacts.pack"), used, fmt::days(r.pack_days as i64, l));
                        let due_label = if left < 0 { t("contacts.ran_out") } else { t("contacts.next_due") };
                        rsx! {
                            div { key: "{i}-{pid}", class: "card pad stack gap-12",
                                div { class: "row top gap-12",
                                    IconTile { icon: "pill", tone, size: "sm" }
                                    div { class: "grow stack gap-4", style: "gap: 3px",
                                        span { class: "strong {mask}", "{pname}" }
                                        div { class: "row wrap gap-6", style: "gap: 6px",
                                            span { class: "badge sm info {mask}", {t(r.condition.key())} }
                                            span { class: "small muted {mask}", "{r.dose}" }
                                        }
                                    }
                                    div { class: "stack gap-4", style: "align-items: flex-end; gap: 2px",
                                        span { class: "xs muted", "{due_label}" }
                                        Badge { text: due, tone }
                                    }
                                }
                                div { class: "stack gap-4", style: "gap: 6px",
                                    Progress { pct, tone: ptone, thin: true }
                                    div { class: "row between xs muted",
                                        span { class: "num", "{pack_line}" }
                                        span { {t("contacts.last_bought")} ": {bought}" }
                                    }
                                }
                                div { class: "row between wrap", style: "gap: 8px",
                                    div { class: "row gap-8 small",
                                        Switch {
                                            on: remind,
                                            onchange: move |v: bool| mutate(|db| {
                                                if let Some(c) = db.customer_mut(id) {
                                                    if let Some(r) = c.regimens.get_mut(i) {
                                                        r.remind = v;
                                                    }
                                                }
                                            }),
                                        }
                                        {t("contacts.remind")}
                                    }
                                    div { class: "row gap-4",
                                        if in_stock {
                                            button {
                                                class: "btn ghost sm",
                                                onclick: move |_| log_telegram(id, format!("Telegram · {}", t("contacts.nba_remind")), "contacts.reminder_sent"),
                                                Icon { name: "send", size: 14 }
                                                {t("contacts.nba_remind")}
                                            }
                                        }
                                        button { class: "btn ghost sm", onclick: move |_| on_dialog.call(Dialog::Reserve(Some(pid))), Icon { name: "package-check", size: 14 } {t("contacts.reserve")} }
                                        button {
                                            class: "icon-btn sm",
                                            title: t("common.delete"),
                                            onclick: move |_| {
                                                mutate(|db| {
                                                    if let Some(c) = db.customer_mut(id) {
                                                        if i < c.regimens.len() {
                                                            c.regimens.remove(i);
                                                        }
                                                    }
                                                });
                                                toast(t("contacts.removed"), "trash-2", "info");
                                            },
                                            Icon { name: "trash-2", size: 15 }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            div { class: "card",
                div { class: "card-head", div { class: "card-title", Icon { name: "triangle-alert", size: 16, class: "tone-danger" } {t("contacts.allergies")} } }
                div { class: "card-body stack gap-12",
                    if allergies.is_empty() {
                        span { class: "small muted", {t("contacts.no_allergies")} }
                    }
                    div { class: "row wrap gap-8",
                        for a in allergies {
                            {
                                let v = a.clone();
                                rsx! {
                                    span { key: "{a}", class: "badge danger {mask}", style: "padding-right: 4px",
                                        Icon { name: "triangle-alert", size: 12 }
                                        "{a}"
                                        button {
                                            class: "icon-btn",
                                            style: "width: 16px; height: 16px; color: inherit",
                                            onclick: move |_| {
                                                let v = v.clone();
                                                mutate(|db| if let Some(c) = db.customer_mut(id) { c.allergies.retain(|x| *x != v) });
                                            },
                                            Icon { name: "x", size: 11 }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "row gap-8", style: "max-width: 420px",
                        input {
                            class: "input sm",
                            value: "{allergy}",
                            placeholder: t("contacts.allergy_hint"),
                            oninput: move |e| allergy.set(e.value()),
                            onkeydown: move |e: KeyboardEvent| {
                                if e.key() == Key::Enter {
                                    add_allergy(id, allergy);
                                }
                            },
                        }
                        button { class: "btn sm", disabled: allergy().trim().is_empty(), onclick: move |_| add_allergy(id, allergy), Icon { name: "plus", size: 14 } {t("common.add")} }
                    }
                }
            }
        }
    }
}

fn add_allergy(id: Id, mut sig: Signal<String>) {
    let v = sig().trim().to_string();
    if v.is_empty() {
        return;
    }
    mutate(|db| {
        if let Some(c) = db.customer_mut(id) {
            if !c.allergies.contains(&v) {
                c.allergies.push(v.clone());
            }
        }
    });
    sig.set(String::new());
}

// ---------------------------------------------------------------- loyalty

#[component]
fn LoyaltyTab(id: Id, cashback: String, on_dialog: EventHandler<Dialog>) -> Element {
    let now = now();
    let l = lang();
    let Some(c) = DB.read().customer(id).cloned() else { return rsx! {} };
    let (company, settings, ledger) = {
        let db = DB.read();
        let mut v: Vec<LoyaltyTx> = db.loyalty.iter().filter(|x| x.customer_id == id).cloned().collect();
        v.sort_by(|a, b| b.at.cmp(&a.at));
        v.truncate(40);
        (db.settings.company_name.clone(), db.settings.loyalty.clone(), v)
    };
    let spent = c.total_spent;
    let (progress, line) = match settings.next_tier(spent) {
        Some((next, need)) => {
            let cur_min = settings.tiers.iter().filter(|r| r.min_spent <= spent).map(|r| r.min_spent).max().unwrap_or(0);
            let next_min = settings.tiers.iter().find(|r| r.tier == next).map(|r| r.min_spent).unwrap_or(spent + need);
            let pct = if next_min > cur_min { (spent - cur_min) as f64 / (next_min - cur_min) as f64 * 100.0 } else { 100.0 };
            (pct, t("contacts.to_next").replace("{tier}", &t(next.key())).replace("{sum}", &money_short(need)))
        }
        None => (100.0, t("contacts.top_tier")),
    };
    let slug = c.tier.slug();
    let tier_name = t(c.tier.key());
    let points = fmt::num(c.points);
    let points_money = money(c.points);
    let benefits: Vec<(&'static str, String, String)> = vec![
        ("percent", t("contacts.cashback"), format!("{}%", settings.cashback(c.tier))),
        ("cake", t("contacts.b_birthday"), money(settings.birthday_bonus)),
        ("shopping-bag", t("contacts.b_redeem"), format!("{}%", settings.max_redeem_pct)),
        ("hourglass", t("contacts.b_expiry"), fmt::days(settings.expiry_days as i64, l)),
        ("file-check", t("contacts.b_rx"), if settings.exclude_rx { t("contacts.b_rx_no") } else { t("common.yes") }),
    ];
    rsx! {
        div { class: "grid-2", style: "align-items: start",
            div { class: "stack gap-16",
                div { class: "loyalty-card {slug}",
                    div { class: "row between", style: "position: relative; z-index: 1",
                        span { class: "strong", style: "font-size: 15px", "{company}" }
                        span { class: "upper", style: "opacity: .9", Icon { name: "crown", size: 13 } " {tier_name}" }
                    }
                    div { style: "position: relative; z-index: 1",
                        div { class: "xs", style: "opacity: .8", {t("contacts.balance")} }
                        div { class: "num", style: "font-size: 32px; font-weight: 750; letter-spacing: -0.02em; line-height: 1.1", "{points}" }
                        div { class: "xs", style: "opacity: .8", "= {points_money}" }
                    }
                    div { class: "row between", style: "position: relative; z-index: 1",
                        span { class: "num", style: "letter-spacing: 0.12em; font-weight: 600", "{c.card_no}" }
                        span { class: "small strong", "{cashback}" }
                    }
                }
                div { class: "card pad stack gap-8",
                    div { class: "row between",
                        span { class: "strong small", "{line}" }
                        span { class: "xs muted num", "{progress:.0}%" }
                    }
                    Progress { pct: progress }
                    div { class: "row gap-8", style: "margin-top: 6px",
                        button { class: "btn soft sm", onclick: move |_| on_dialog.call(Dialog::Bonus), Icon { name: "gift", size: 14 } {t("contacts.give_bonus")} }
                    }
                }
                div { class: "card",
                    div { class: "card-head", div { class: "card-title", Icon { name: "crown", size: 16, class: "subtle" } {t("contacts.benefits")} " · {tier_name}" } }
                    div { class: "list", style: "margin-top: 6px",
                        for (icon, label, value) in benefits {
                            div { key: "{icon}", class: "list-row", style: "padding-top: 9px; padding-bottom: 9px",
                                span { class: "ic muted sm", Icon { name: icon, size: 14 } }
                                span { class: "grow small", "{label}" }
                                span { class: "small strong num", "{value}" }
                            }
                        }
                    }
                }
            }
            div { class: "card",
                div { class: "card-head", div { class: "card-title", Icon { name: "coins", size: 16, class: "subtle" } {t("contacts.ledger")} } }
                div { class: "list", style: "margin-top: 6px",
                    if ledger.is_empty() {
                        Empty { icon: "coins", title: t("contacts.no_ledger") }
                    }
                    for tx in ledger {
                        {
                            let (icon, tone) = tx_icon(tx.kind);
                            let when = fmt::relative(tx.at, now, l);
                            let label = if tx.note.is_empty() { t(tx.kind.key()) } else { format!("{} · {}", t(tx.kind.key()), tx.note) };
                            let pts = if tx.points >= 0 { format!("+{}", fmt::num(tx.points)) } else { fmt::num(tx.points) };
                            let cls = if tx.points >= 0 { "num strong small tone-success nowrap" } else { "num strong small tone-danger nowrap" };
                            rsx! {
                                div { key: "{tx.id}", class: "list-row", style: "padding-top: 9px; padding-bottom: 9px",
                                    IconTile { icon, tone, size: "sm" }
                                    div { class: "meta", span { class: "small truncate", "{label}" } span { class: "sub", "{when}" } }
                                    span { class: cls, "{pts}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- care

#[component]
fn CareTab(id: Id, on_dialog: EventHandler<Dialog>) -> Element {
    let now = now();
    let l = lang();
    let (tickets, waits) = {
        let db = DB.read();
        let mut tk: Vec<Ticket> = db.tickets.iter().filter(|x| x.customer_id == Some(id)).cloned().collect();
        tk.sort_by(|a, b| b.created.cmp(&a.created));
        let mut w: Vec<(WaitItem, String)> = db.waitlist.iter().filter(|x| x.customer_id == id).map(|x| (x.clone(), db.branch_name(Some(x.branch_id)))).collect();
        w.sort_by(|a, b| b.0.at.cmp(&a.0.at));
        (tk, w)
    };
    rsx! {
        div { class: "grid-2", style: "align-items: start",
            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "life-buoy", size: 16, class: "subtle" } {t("nav.tickets")} }
                    button { class: "btn ghost sm", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Ticket), Icon { name: "plus", size: 14 } {t("common.ticket")} }
                }
                div { class: "list", style: "margin-top: 6px",
                    if tickets.is_empty() {
                        Empty { icon: "smile", title: t("contacts.no_tickets") }
                    }
                    for tk in tickets {
                        {
                            let tid = tk.id;
                            let tone: &'static str = if tk.kind == TicketKind::AdverseReaction { "danger" } else { "warning" };
                            let when = fmt::relative(tk.created, now, l);
                            rsx! {
                                div { key: "{tid}", class: "list-row click", onclick: move |_| go(&format!("/tickets/{tid}")),
                                    IconTile { icon: crm::db::ticket_icon(tk.kind), tone, size: "sm" }
                                    div { class: "meta",
                                        span { class: "title small truncate", "{tk.number} · {tk.subject}" }
                                        span { class: "sub", {t(tk.kind.key())} " · {when}" }
                                    }
                                    Badge { text: t(tk.status.key()), tone: ticket_tone(tk.status) }
                                }
                            }
                        }
                    }
                }
            }
            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "hourglass", size: 16, class: "subtle" } {t("nav.waitlist")} }
                    button { class: "btn ghost sm", onclick: move |_| on_dialog.call(Dialog::Reserve(None)), Icon { name: "plus", size: 14 } {t("contacts.reserve")} }
                }
                div { class: "list", style: "margin-top: 6px",
                    if waits.is_empty() {
                        Empty { icon: "package-check", title: t("contacts.no_waitlist") }
                    }
                    for (w, bname) in waits {
                        {
                            let wid = w.id;
                            let when = fmt::relative(w.at, now, l);
                            let value = money_short(w.value);
                            let status = w.status;
                            rsx! {
                                div { key: "{wid}", class: "list-row",
                                    span { class: "ic {wait_tone(status)} sm", Icon { name: "pill", size: 14 } }
                                    div { class: "meta",
                                        span { class: "title small truncate", "{w.product_name}" }
                                        span { class: "sub", "{bname} · ×{w.qty} · {when}" }
                                    }
                                    div { class: "stack gap-4", style: "align-items: flex-end",
                                        Badge { text: t(status.key()), tone: wait_tone(status) }
                                        span { class: "xs muted num", "{value}" }
                                    }
                                    if status == WaitStatus::Arrived {
                                        button {
                                            class: "btn sm soft",
                                            onclick: move |_| {
                                                let now = crate::state::now();
                                                mutate(|db| if let Some(w) = db.wait_item_mut(wid) { w.status = WaitStatus::Notified; w.notified_at = Some(now); });
                                                toast(t("contacts.notified_toast"), "send", "success");
                                            },
                                            {t("contacts.notify")}
                                        }
                                    }
                                    if matches!(status, WaitStatus::Notified | WaitStatus::Reserved) {
                                        button {
                                            class: "btn sm",
                                            onclick: move |_| {
                                                mutate(|db| if let Some(w) = db.wait_item_mut(wid) { w.status = WaitStatus::PickedUp; });
                                                toast(t("wait_status.picked_up"), "package-check", "success");
                                            },
                                            Icon { name: "check", size: 14 }
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

// ---------------------------------------------------------------- notes

#[component]
fn NoteComposer(id: Id, ondone: EventHandler<()>) -> Element {
    let mut text = use_signal(String::new);
    let mut pinned = use_signal(|| false);
    let mut sensitive = use_signal(|| false);
    let valid = !text().trim().is_empty();
    let save = move |_| {
        let v = text().trim().to_string();
        if v.is_empty() {
            return;
        }
        let now = now();
        let (p, s) = (pinned(), sensitive());
        mutate(|db| {
            let nid = db.new_id();
            let me = db.settings.me;
            db.notes.push(Note { id: nid, at: now, author_id: Some(me), text: v, customer_id: Some(id), company_id: None, deal_id: None, pinned: p, sensitive: s });
        });
        text.set(String::new());
        pinned.set(false);
        sensitive.set(false);
        toast(t("contacts.note_saved"), "sticky-note", "success");
        ondone.call(());
    };
    rsx! {
        div { class: "stack gap-12",
            textarea {
                class: "textarea",
                value: "{text}",
                placeholder: t("contacts.note_placeholder"),
                oninput: move |e| text.set(e.value()),
                onmounted: move |e| async move {
                    let _ = e.set_focus(true).await;
                },
            }
            div { class: "row between wrap", style: "gap: 10px",
                div { class: "row wrap gap-16",
                    label { class: "check small", input { r#type: "checkbox", checked: pinned(), onchange: move |e| pinned.set(e.checked()) } Icon { name: "pin", size: 14 } {t("contacts.pin")} }
                    label { class: "check small", input { r#type: "checkbox", checked: sensitive(), onchange: move |e| sensitive.set(e.checked()) } Icon { name: "lock", size: 14 } {t("contacts.sensitive")} }
                }
                button { class: "btn primary sm", disabled: !valid, onclick: save, Icon { name: "check", size: 15 } {t("common.save")} }
            }
        }
    }
}

#[component]
fn NotesTab(id: Id, privacy: bool) -> Element {
    let now = now();
    let l = lang();
    let (notes, profile) = {
        let db = DB.read();
        let mut v: Vec<(Note, String, u16)> = db
            .notes
            .iter()
            .filter(|n| n.customer_id == Some(id))
            .map(|n| {
                let s = n.author_id.and_then(|a| db.staff_member(a));
                (n.clone(), s.map(|s| s.name.clone()).unwrap_or_else(|| "—".into()), s.map(|s| s.hue).unwrap_or(24))
            })
            .collect();
        v.sort_by(|a, b| b.0.pinned.cmp(&a.0.pinned).then(b.0.at.cmp(&a.0.at)));
        (v, db.customer(id).map(|c| c.notes.clone()).unwrap_or_default())
    };
    rsx! {
        div { class: "grid-main",
            div { class: "stack gap-12",
                if !profile.is_empty() {
                    div { class: "callout accent", Icon { name: "pin", size: 15 } div { div { class: "strong", {t("contacts.profile_note")} } span { "{profile}" } } }
                }
                if notes.is_empty() {
                    div { class: "card", Empty { icon: "sticky-note", title: t("contacts.no_notes") } }
                }
                for (n, author, hue) in notes {
                    {
                        let nid = n.id;
                        let when = fmt::datetime(n.at, now, l);
                        let text_cls = if n.sensitive && privacy { "mask" } else { "" };
                        let pin_cls = if n.pinned { "icon-btn sm tone-accent" } else { "icon-btn sm" };
                        let card_style = if n.pinned { "border-color: color-mix(in srgb, var(--c-primary) 35%, var(--c-border))" } else { "" };
                        rsx! {
                            div { key: "{nid}", class: "card pad stack gap-8", style: card_style,
                                div { class: "row gap-8",
                                    Avatar { name: author.clone(), hue, size: "sm" }
                                    div { class: "grow stack", style: "gap: 0",
                                        span { class: "small strong", "{author}" }
                                        span { class: "xs subtle", "{when}" }
                                    }
                                    if n.sensitive { span { class: "badge info sm", Icon { name: "lock", size: 11 } {t("contacts.sensitive_short")} } }
                                    if n.pinned { span { class: "badge accent sm", Icon { name: "pin", size: 11 } {t("contacts.pinned")} } }
                                    button {
                                        class: pin_cls,
                                        title: t("contacts.pin"),
                                        onclick: move |_| mutate(|db| if let Some(x) = db.notes.iter_mut().find(|x| x.id == nid) { x.pinned = !x.pinned }),
                                        Icon { name: "pin", size: 15 }
                                    }
                                    button {
                                        class: "icon-btn sm",
                                        title: t("common.delete"),
                                        onclick: move |_| {
                                            mutate(|db| db.notes.retain(|x| x.id != nid));
                                            toast(t("contacts.removed"), "trash-2", "info");
                                        },
                                        Icon { name: "trash-2", size: 15 }
                                    }
                                }
                                p { class: text_cls, style: "line-height: 1.55; white-space: pre-wrap", "{n.text}" }
                            }
                        }
                    }
                }
            }
            div { class: "card",
                div { class: "card-head", div { class: "card-title", Icon { name: "notebook-pen", size: 16, class: "subtle" } {t("common.add_note")} } }
                div { class: "card-body", NoteComposer { id, ondone: move |_| {} } }
            }
        }
    }
}

// ---------------------------------------------------------------- consent and data

#[component]
fn ConsentTab(id: Id, on_dialog: EventHandler<Dialog>) -> Element {
    let today = today();
    let l = lang();
    let Some(c) = DB.read().customer(id).cloned() else { return rsx! {} };
    let since = c.consent.given_on.map(|d| format!("{} {}", t("contacts.consent_since"), fmt::date(d, today, l))).unwrap_or_default();
    let set = move |which: &'static str, v: bool| {
        let label = match which {
            "sms" => t("field.consent_sms"),
            "telegram" => t("field.consent_telegram"),
            _ => t("contacts.consent_health"),
        };
        let log = format!("{label}: {} · {}", if v { "✓" } else { "✗" }, DB.peek().customer_name(Some(id)));
        let today = crate::state::today();
        mutate(|db| {
            if let Some(c) = db.customer_mut(id) {
                match which {
                    "sms" => c.consent.sms = v,
                    "telegram" => c.consent.telegram = v,
                    _ => c.consent.health_data = v,
                }
                c.consent.given_on = Some(today);
            }
            db.log(crate::state::now(), log, which == "health");
        });
        toast(t("contacts.consent_saved"), "shield-check", "success");
    };
    let rows: Vec<(&'static str, &'static str, String, String, bool)> = vec![
        ("telegram", "send", t("field.consent_telegram"), t("contacts.consent_tg_hint"), c.consent.telegram),
        ("sms", "message-square-text", t("field.consent_sms"), t("contacts.consent_sms_hint"), c.consent.sms),
        ("health", "heart-pulse", t("contacts.consent_health"), t("contacts.consent_health_hint"), c.consent.health_data),
    ];
    let archived = c.archived;
    rsx! {
        div { class: "grid-2", style: "align-items: start",
            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "shield-check", size: 16, class: "tone-success" } {t("contacts.consent")} }
                    span { class: "xs muted", "{since}" }
                }
                div { class: "list", style: "margin-top: 6px",
                    for (key, icon, label, hint, on) in rows {
                        div { key: "{key}", class: "list-row",
                            span { class: "ic muted sm", Icon { name: icon, size: 15 } }
                            div { class: "meta", span { class: "title small", "{label}" } span { class: "sub", "{hint}" } }
                            Switch { on, onchange: move |v: bool| set(key, v) }
                        }
                    }
                }
            }
            div { class: "card",
                div { class: "card-head", div { class: "card-title", Icon { name: "database", size: 16, class: "subtle" } {t("contacts.data")} } }
                div { class: "list", style: "margin-top: 6px",
                    div { class: "list-row",
                        span { class: "ic info sm", Icon { name: "file-down", size: 15 } }
                        div { class: "meta", span { class: "title small", {t("contacts.export_data")} } span { class: "sub", {t("contacts.export_data_hint")} } }
                        button {
                            class: "btn sm",
                            onclick: move |_| {
                                let log = format!("{}: {}", t("contacts.export_data"), DB.peek().customer_name(Some(id)));
                                mutate(|db| db.log(crate::state::now(), log, true));
                                toast(t("contacts.exported_one"), "file-down", "success");
                            },
                            Icon { name: "download", size: 14 }
                            "JSON"
                        }
                    }
                    div { class: "list-row",
                        span { class: "ic warning sm", Icon { name: "archive", size: 15 } }
                        div { class: "meta",
                            span { class: "title small", if archived { {t("contacts.restore")} } else { {t("contacts.archive")} } }
                            span { class: "sub", {t("contacts.archive_hint")} }
                        }
                        if archived {
                            button {
                                class: "btn sm",
                                onclick: move |_| {
                                    mutate(|db| if let Some(c) = db.customer_mut(id) { c.archived = false });
                                    toast(t("contacts.restored"), "undo-2", "success");
                                },
                                Icon { name: "undo-2", size: 14 }
                                {t("contacts.restore")}
                            }
                        } else {
                            button { class: "btn sm danger", onclick: move |_| on_dialog.call(Dialog::Archive), Icon { name: "archive", size: 14 } {t("contacts.archive_short")} }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- dialogs

#[component]
fn TaskModal(id: Id, onclose: EventHandler<()>) -> Element {
    let start = (now() + Duration::hours(1)).format("%Y-%m-%dT%H:00").to_string();
    let first = DB.read().customer(id).map(|c| c.first_name.clone()).unwrap_or_default();
    let default_title = format!("{}: {first}", t("contacts.task_default"));
    let mut title = use_signal(move || default_title.clone());
    let mut due = use_signal(move || start.clone());
    let mut kind = use_signal(|| ActivityKind::Call);
    let mut prio = use_signal(|| Priority::Normal);
    let valid = !title().trim().is_empty() && parse_dt(&due()).is_some();
    let save = move |_| {
        let Some(d) = parse_dt(&due()) else { return };
        let v = title().trim().to_string();
        if v.is_empty() {
            return;
        }
        let (k, p) = (kind(), prio());
        mutate(|db| {
            let me = db.settings.me;
            db.add_activity(Activity {
                id: 0,
                kind: k,
                title: v,
                notes: String::new(),
                due: d,
                done: false,
                done_at: None,
                owner_id: me,
                customer_id: Some(id),
                company_id: None,
                deal_id: None,
                ticket_id: None,
                priority: p,
                outcome: None,
                duration_min: 15,
                daybook_task: None,
            });
        });
        toast(t("quick.task_saved"), "square-check", "success");
        onclose.call(());
    };
    rsx! {
        Modal { title: t("palette.new_task"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("quick.task_title")} }
                    input {
                        class: "input",
                        value: "{title}",
                        oninput: move |e| title.set(e.value()),
                        onmounted: move |e| async move {
                            let _ = e.set_focus(true).await;
                        },
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("quick.kind")} }
                        select { class: "select", onchange: move |e| kind.set(ActivityKind::from_slug(&e.value()).unwrap_or(ActivityKind::Task)),
                            for k in ActivityKind::ALL.iter().copied() {
                                option { key: "{k.slug()}", value: "{k.slug()}", selected: k == kind(), {t(k.key())} }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("quick.due")} }
                        input { class: "input", r#type: "datetime-local", value: "{due}", oninput: move |e| due.set(e.value()) }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("contacts.priority")} }
                    Segmented {
                        options: Priority::ALL.iter().map(|p| (p.slug().to_string(), t(p.key()))).collect(),
                        value: prio().slug().to_string(),
                        onchange: move |v: String| prio.set(Priority::from_slug(&v).unwrap_or(Priority::Normal)),
                    }
                }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.create")} }
            }
        }
    }
}

#[component]
fn BonusModal(id: Id, onclose: EventHandler<()>) -> Element {
    let mut points = use_signal(|| "10000".to_string());
    let reason_default = t("contacts.bonus_default");
    let mut reason = use_signal(move || reason_default.clone());
    let pts = parse_num(&points());
    let valid = pts > 0 && pts <= 1_000_000;
    let presets: [i64; 4] = [5_000, 10_000, 25_000, 50_000];
    let save = move |_| {
        let pts = parse_num(&points());
        if pts <= 0 {
            return;
        }
        let note = reason().trim().to_string();
        let now = now();
        let log = format!("{} +{} · {}", t("tx.bonus"), fmt::num(pts), DB.peek().customer_name(Some(id)));
        mutate(|db| {
            db.give_points(id, pts, TxKind::Bonus, note, now);
            db.log(now, log, false);
        });
        toast(format!("{}: +{}", t("contacts.bonus_given"), fmt::num(pts)), "gift", "success");
        onclose.call(());
    };
    rsx! {
        Modal { title: t("contacts.give_bonus"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("field.points")} }
                    input {
                        class: "input num",
                        inputmode: "numeric",
                        value: "{points}",
                        oninput: move |e| points.set(e.value()),
                        onmounted: move |e| async move {
                            let _ = e.set_focus(true).await;
                        },
                    }
                    div { class: "row wrap gap-8", style: "margin-top: 4px",
                        for p in presets {
                            button { key: "{p}", class: if pts == p { "chip on" } else { "chip" }, onclick: move |_| points.set(p.to_string()), "+{fmt::num(p)}" }
                        }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("contacts.reason")} }
                    input { class: "input", value: "{reason}", oninput: move |e| reason.set(e.value()) }
                }
                div { class: "callout accent", Icon { name: "info", size: 15 } span { {t("contacts.bonus_hint")} } }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "gift", size: 16 } {t("contacts.give_bonus")} }
            }
        }
    }
}

#[component]
fn ReserveModal(id: Id, product: Option<Id>, onclose: EventHandler<()>) -> Element {
    let home = DB.read().customer(id).map(|c| c.home_branch).unwrap_or(0);
    let (products, branches) = {
        let db = DB.read();
        let mut p: Vec<(Id, String, Money)> = db.products.iter().map(|p| (p.id, p.name.clone(), p.price)).collect();
        p.sort_by(|a, b| a.1.cmp(&b.1));
        (p, db.branches.iter().map(|b| (b.id, b.name.clone())).collect::<Vec<_>>())
    };
    let first = product.or_else(|| products.first().map(|p| p.0)).unwrap_or(0);
    let mut pid = use_signal(move || first);
    let mut branch = use_signal(move || home);
    let mut qty = use_signal(|| "1".to_string());
    let mut note = use_signal(String::new);
    let q = parse_num(&qty()).clamp(0, 99) as u32;
    let (price, stock, pname) = {
        let db = DB.read();
        let p = db.product(pid());
        (p.map(|p| p.price).unwrap_or(0), p.map(|p| p.stock_at(branch())).unwrap_or(0), p.map(|p| p.name.clone()).unwrap_or_default())
    };
    let value = price * q as Money;
    let valid = q > 0 && pid() != 0;
    let save = move |_| {
        if !valid {
            return;
        }
        let now = now();
        let (p, b, n, text) = (pid(), branch(), q, note());
        let name = pname.clone();
        let bname = DB.peek().branch_name(Some(b));
        let log = format!("{} · {name} ×{n} · {}", t("wait_status.reserved"), DB.peek().customer_name(Some(id)));
        mutate(|db| {
            let wid = db.new_id();
            db.waitlist.insert(
                0,
                WaitItem {
                    id: wid,
                    customer_id: id,
                    product_id: Some(p),
                    product_name: name,
                    branch_id: b,
                    qty: n,
                    at: now,
                    status: WaitStatus::Reserved,
                    eta: Some(if stock >= n { now.date() } else { now.date() + Duration::days(2) }),
                    note: text,
                    notified_at: None,
                    value,
                },
            );
            db.log(now, log, false);
        });
        toast(format!("{}: {bname}", t("contacts.reserved_toast")), "package-check", "success");
        onclose.call(());
    };
    let stock_ok = stock >= q.max(1);
    rsx! {
        Modal { title: t("contacts.reserve_title"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("common.product")} }
                    select { class: "select", onchange: move |e| pid.set(e.value().parse().unwrap_or(0)),
                        for (id_, name, pr) in products {
                            option { key: "{id_}", value: "{id_}", selected: id_ == pid(), "{name} · {money(pr)}" }
                        }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("common.branch")} }
                        select { class: "select", onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                            for (bid, bname) in branches {
                                option { key: "{bid}", value: "{bid}", selected: bid == branch(), "{bname}" }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("contacts.qty")} }
                        input { class: "input num", inputmode: "numeric", value: "{qty}", oninput: move |e| qty.set(e.value()) }
                    }
                }
                if stock_ok {
                    div { class: "callout success", Icon { name: "package-check", size: 15 } span { {t("contacts.in_stock")} ": " b { class: "num", "{stock}" } } }
                } else {
                    div { class: "callout warning", Icon { name: "truck", size: 15 } span { {t("contacts.not_in_stock")} } }
                }
                div { class: "field",
                    label { class: "label", {t("common.notes")} }
                    input { class: "input", value: "{note}", oninput: move |e| note.set(e.value()) }
                }
                div { class: "row between small", span { class: "muted", {t("common.total")} } span { class: "num strong", "{money(value)}" } }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "package-check", size: 16 } {t("contacts.reserve")} }
            }
        }
    }
}

#[component]
fn RegimenModal(id: Id, onclose: EventHandler<()>) -> Element {
    let today = today();
    let products: Vec<(Id, String)> = {
        let db = DB.read();
        let mut p: Vec<(Id, String)> = db
            .products
            .iter()
            .filter(|p| matches!(p.category, ProductCategory::Rx | ProductCategory::Diabetes | ProductCategory::Otc | ProductCategory::Vitamins))
            .map(|p| (p.id, p.name.clone()))
            .collect();
        p.sort_by(|a, b| a.1.cmp(&b.1));
        p
    };
    let first = products.first().map(|p| p.0).unwrap_or(0);
    let mut pid = use_signal(move || first);
    let mut cond = use_signal(|| Condition::Hypertension);
    let mut dose = use_signal(|| tr("1 tabletka kuniga", "1 таблетка в день", "1 tablet a day"));
    let mut pack = use_signal(|| "30".to_string());
    let start = today.format("%Y-%m-%d").to_string();
    let mut bought = use_signal(move || start.clone());
    let mut remind = use_signal(|| true);
    let days = parse_num(&pack()).clamp(0, 365) as u16;
    let date_ok = NaiveDate::parse_from_str(&bought(), "%Y-%m-%d").is_ok();
    let valid = pid() != 0 && days > 0 && date_ok;
    let save = move |_| {
        let Ok(d) = NaiveDate::parse_from_str(&bought(), "%Y-%m-%d") else { return };
        let days = parse_num(&pack()).clamp(1, 365) as u16;
        let r = Regimen { product_id: pid(), condition: cond(), dose: dose().trim().to_string(), pack_days: days, last_bought: d, remind: remind() };
        let log = format!("{}: {}", t("contacts.add_regimen"), DB.peek().customer_name(Some(id)));
        mutate(|db| {
            if let Some(c) = db.customer_mut(id) {
                c.regimens.retain(|x| x.product_id != r.product_id);
                c.regimens.push(r);
            }
            db.log(crate::state::now(), log, true);
        });
        toast(t("contacts.regimen_saved"), "pill", "success");
        onclose.call(());
    };
    rsx! {
        Modal { title: t("contacts.add_regimen"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("common.product")} }
                    select { class: "select", onchange: move |e| pid.set(e.value().parse().unwrap_or(0)),
                        for (id_, name) in products {
                            option { key: "{id_}", value: "{id_}", selected: id_ == pid(), "{name}" }
                        }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("field.condition")} }
                        select { class: "select", onchange: move |e| cond.set(Condition::from_slug(&e.value()).unwrap_or(Condition::Hypertension)),
                            for k in Condition::ALL.iter().copied() {
                                option { key: "{k.slug()}", value: "{k.slug()}", selected: k == cond(), {t(k.key())} }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("contacts.dose")} }
                        input { class: "input", value: "{dose}", oninput: move |e| dose.set(e.value()) }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("contacts.pack_days")} }
                        input { class: "input num", inputmode: "numeric", value: "{pack}", oninput: move |e| pack.set(e.value()) }
                    }
                    div { class: "field",
                        label { class: "label", {t("contacts.last_bought")} }
                        input { class: "input", r#type: "date", value: "{bought}", oninput: move |e| bought.set(e.value()) }
                    }
                }
                label { class: "check", input { r#type: "checkbox", checked: remind(), onchange: move |e| remind.set(e.checked()) } {t("contacts.remind_hint")} }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
            }
        }
    }
}

#[component]
fn EditModal(id: Id, onclose: EventHandler<()>) -> Element {
    let init = use_hook(move || DB.peek().customer(id).cloned());
    let (branches, staff) = {
        let db = DB.read();
        (
            db.branches.iter().map(|b| (b.id, b.name.clone())).collect::<Vec<_>>(),
            db.staff.iter().filter(|s| s.active).map(|s| (s.id, s.name.clone())).collect::<Vec<_>>(),
        )
    };
    let c0 = init.clone();
    let mut first = use_signal(move || c0.as_ref().map(|c| c.first_name.clone()).unwrap_or_default());
    let c1 = init.clone();
    let mut last = use_signal(move || c1.as_ref().map(|c| c.last_name.clone()).unwrap_or_default());
    let c2 = init.clone();
    let mut phone_v = use_signal(move || c2.as_ref().map(|c| crm::fmt::phone(&c.phone)).unwrap_or_default());
    let c3 = init.clone();
    let mut tg = use_signal(move || c3.as_ref().and_then(|c| c.telegram.clone()).unwrap_or_default());
    let c4 = init.clone();
    let mut birth = use_signal(move || c4.as_ref().and_then(|c| c.birth_date).map(|d| d.format("%Y-%m-%d").to_string()).unwrap_or_default());
    let c5 = init.clone();
    let mut gender = use_signal(move || c5.as_ref().map(|c| c.gender).unwrap_or(Gender::Female));
    let c6 = init.clone();
    let mut branch = use_signal(move || c6.as_ref().map(|c| c.home_branch).unwrap_or(0));
    let c7 = init.clone();
    let mut owner = use_signal(move || c7.as_ref().and_then(|c| c.owner_id).unwrap_or(0));
    let c8 = init.clone();
    let mut district = use_signal(move || c8.as_ref().map(|c| c.district.clone()).unwrap_or_default());
    let digits: String = phone_v().chars().filter(|c| c.is_ascii_digit()).collect();
    let dup = if digits.len() >= 12 { DB.read().customers.iter().find(|x| x.phone == digits && x.id != id).map(|x| x.name()) } else { None };
    let birth_ok = birth().trim().is_empty() || NaiveDate::parse_from_str(birth().trim(), "%Y-%m-%d").is_ok();
    let valid = !first().trim().is_empty() && digits.len() >= 12 && dup.is_none() && birth_ok;
    let save = move |_| {
        let digits: String = phone_v().chars().filter(|c| c.is_ascii_digit()).collect();
        let raw = tg().trim().to_string();
        let handle = if raw.is_empty() {
            None
        } else if raw.starts_with('@') {
            Some(raw)
        } else {
            Some(format!("@{raw}"))
        };
        let bd = NaiveDate::parse_from_str(birth().trim(), "%Y-%m-%d").ok();
        let (f, l, g, b, o, d) = (first().trim().to_string(), last().trim().to_string(), gender(), branch(), owner(), district().trim().to_string());
        let log = format!("{}: {f} {l}", t("contacts.edit_profile"));
        mutate(|db| {
            if let Some(c) = db.customer_mut(id) {
                c.first_name = f;
                c.last_name = l;
                c.phone = digits;
                c.telegram = handle;
                c.birth_date = bd;
                c.gender = g;
                c.home_branch = b;
                c.owner_id = if o == 0 { None } else { Some(o) };
                c.district = d;
            }
            db.log(crate::state::now(), log, false);
        });
        toast(t("common.saved"), "user-check", "success");
        onclose.call(());
    };
    rsx! {
        Modal { title: t("contacts.edit_profile"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("quick.first_name")} }
                        input { class: "input", value: "{first}", oninput: move |e| first.set(e.value()) }
                    }
                    div { class: "field",
                        label { class: "label", {t("quick.last_name")} }
                        input { class: "input", value: "{last}", oninput: move |e| last.set(e.value()) }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("common.phone")} }
                        input { class: "input num", r#type: "tel", value: "{phone_v}", oninput: move |e| phone_v.set(e.value()) }
                        if let Some(n) = dup.clone() {
                            div { class: "hint tone-warning row gap-4", Icon { name: "triangle-alert", size: 13 } {t("quick.duplicate")} " {n}" }
                        }
                    }
                    div { class: "field",
                        label { class: "label", "Telegram" }
                        input { class: "input", value: "{tg}", placeholder: "@username", oninput: move |e| tg.set(e.value()) }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("contacts.birthday")} }
                        input { class: "input", r#type: "date", value: "{birth}", oninput: move |e| birth.set(e.value()) }
                    }
                    div { class: "field",
                        label { class: "label", {t("field.gender")} }
                        Segmented {
                            options: Gender::ALL.iter().map(|g| (g.slug().to_string(), t(g.key()))).collect(),
                            value: gender().slug().to_string(),
                            onchange: move |v: String| gender.set(Gender::from_slug(&v).unwrap_or(Gender::Female)),
                        }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("common.branch")} }
                        select { class: "select", onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                            for (bid, bname) in branches {
                                option { key: "{bid}", value: "{bid}", selected: bid == branch(), "{bname}" }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("common.owner")} }
                        select { class: "select", onchange: move |e| owner.set(e.value().parse().unwrap_or(0)),
                            option { value: "0", selected: owner() == 0, {t("common.unassigned")} }
                            for (sid, sname) in staff {
                                option { key: "{sid}", value: "{sid}", selected: sid == owner(), "{sname}" }
                            }
                        }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("contacts.district")} }
                    input { class: "input", value: "{district}", oninput: move |e| district.set(e.value()) }
                }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
            }
        }
    }
}

#[component]
fn ArchiveModal(id: Id, onclose: EventHandler<()>) -> Element {
    let name = DB.read().customer_name(Some(id));
    let text = t("contacts.archive_confirm").replace("{name}", &name);
    rsx! {
        Modal { title: t("contacts.archive"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "row top gap-12",
                    IconTile { icon: "archive", tone: "warning" }
                    p { class: "muted", style: "line-height: 1.55", "{text}" }
                }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button {
                    class: "btn danger solid",
                    onclick: move |_| {
                        let log = format!("{}: {}", t("contacts.archive"), DB.peek().customer_name(Some(id)));
                        mutate(|db| {
                            if let Some(c) = db.customer_mut(id) {
                                c.archived = true;
                            }
                            db.log(crate::state::now(), log, false);
                        });
                        toast(t("contacts.archived_toast"), "archive", "success");
                        onclose.call(());
                        go("/contacts");
                    },
                    Icon { name: "archive", size: 16 }
                    {t("contacts.archive_short")}
                }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    // list
    ("contacts.import_toast", "CSV/Excel import: kassa dasturidan olingan faylni tashlang, ustunlar o‘zi moslanadi", "Импорт CSV/Excel: перетащите файл из кассовой программы, столбцы сопоставятся сами", "CSV/Excel import: drop a file from your POS and the columns are matched for you"),
    ("contacts.exported", "CSV faylga eksport qilindi", "Экспортировано в CSV", "Exported to CSV"),
    ("contacts.search_hint", "Ism, telefon yoki karta raqami", "Имя, телефон или номер карты", "Name, phone or card number"),
    ("contacts.chip_vip", "VIP", "VIP", "VIP"),
    ("contacts.chip_chronic", "Surunkali", "Хронические", "Chronic"),
    ("contacts.chip_risk", "Ketish xavfi", "Риск ухода", "At risk"),
    ("contacts.chip_new", "Yangi", "Новые", "New"),
    ("contacts.chip_birthday", "Shu hafta tug‘ilgan kun", "ДР на этой неделе", "Birthdays this week"),
    ("contacts.chip_corporate", "Korporativ", "Корпоративные", "Corporate"),
    ("contacts.chip_archived", "Arxiv", "Архив", "Archived"),
    ("contacts.all_tiers", "Barcha darajalar", "Все уровни", "All tiers"),
    ("contacts.sort_ltv", "Xaridlar summasi", "Сумма покупок", "Lifetime value"),
    ("contacts.sort_last", "Oxirgi xarid", "Последняя покупка", "Last purchase"),
    ("contacts.sort_name", "Ism bo‘yicha", "По имени", "Name"),
    ("contacts.sort_points", "Ballar", "Баллы", "Points"),
    ("contacts.orders", "Xaridlar", "Покупки", "Orders"),
    ("contacts.last_purchase", "Oxirgi xarid", "Последняя покупка", "Last purchase"),
    ("contacts.shown_of", "{b} tadan {a} tasi ko‘rsatildi", "Показано {a} из {b}", "Showing {a} of {b}"),
    ("contacts.show_more", "Yana ko‘rsatish", "Показать ещё", "Show more"),
    ("contacts.no_results_text", "Qidiruv yoki filtrlarni o‘zgartirib ko‘ring.", "Измените запрос или фильтры.", "Try another search or fewer filters."),
    ("contacts.reset_filters", "Filtrlarni tozalash", "Сбросить фильтры", "Clear filters"),
    ("contacts.selected", "Tanlandi", "Выбрано", "Selected"),
    ("contacts.bulk_telegram", "Telegram xabar", "Сообщение в Telegram", "Send Telegram"),
    ("contacts.bulk_owner", "Mas’ul tayinlash", "Назначить ответственного", "Assign owner"),
    ("contacts.tg_sent", "Telegram xabar navbatga qo‘yildi (roziligi borlarga)", "Сообщение поставлено в очередь (тем, кто дал согласие)", "Telegram message queued (customers with consent)"),
    ("contacts.tag_title", "Tanlanganlarga teg qo‘shish", "Добавить тег выбранным", "Tag the selected customers"),
    ("contacts.tag_placeholder", "Masalan: Diabet maktabi", "Например: Школа диабета", "e.g. Diabetes school"),
    ("contacts.tag_added", "Teg qo‘shildi", "Тег добавлен", "Tag added"),
    ("contacts.owner_title", "Mas’ul xodimni tanlang", "Выберите ответственного", "Choose an owner"),
    ("contacts.owner_set", "Mas’ul tayinlandi", "Ответственный назначен", "Owner assigned"),
    // customer 360
    ("contacts.not_found", "Mijoz topilmadi", "Клиент не найден", "Customer not found"),
    ("contacts.not_found_text", "Ehtimol, havola eskirgan.", "Возможно, ссылка устарела.", "The link may be out of date."),
    ("contacts.since", "Ro‘yxatdan o‘tgan: {d}", "Клиент с {d}", "Customer since {d}"),
    ("contacts.add_tag", "Teg", "Тег", "Tag"),
    ("contacts.edit_profile", "Ma’lumotlarni tahrirlash", "Изменить данные", "Edit details"),
    ("contacts.give_bonus", "Bonus berish", "Начислить бонус", "Give bonus"),
    ("contacts.reserve", "Bron qilish", "Забронировать", "Reserve"),
    ("contacts.call_logged", "Qo‘ng‘iroq jurnalga yozildi", "Звонок записан в историю", "Call logged"),
    ("contacts.call_outcome", "Mijoz bilan gaplashildi", "Поговорили с клиентом", "Spoke with the customer"),
    ("contacts.conv_started", "Suhbat CRM’dan boshlandi", "Диалог начат из CRM", "Conversation started from the CRM"),
    ("contacts.ltv", "Jami xaridlar", "Сумма покупок", "Lifetime value"),
    ("contacts.first", "birinchisi", "первая", "first"),
    ("contacts.avg_basket", "O‘rtacha chek", "Средний чек", "Avg basket"),
    ("contacts.points_value", "Ballar, so‘mda", "Баллы в сумах", "Points in so‘m"),
    ("contacts.churn_risk", "Ketish xavfi", "Риск ухода", "Churn risk"),
    ("contacts.risk_low", "Past", "Низкий", "Low"),
    ("contacts.risk_mid", "O‘rtacha", "Средний", "Medium"),
    ("contacts.risk_high", "Yuqori", "Высокий", "High"),
    ("contacts.never", "Hali xarid yo‘q", "Покупок ещё нет", "No purchases yet"),
    ("contacts.tab_overview", "Umumiy", "Обзор", "Overview"),
    ("contacts.tab_timeline", "Tarix", "История", "Timeline"),
    ("contacts.tab_purchases", "Xaridlar", "Покупки", "Purchases"),
    ("contacts.tab_medicines", "Dorilar", "Лекарства", "Medicines"),
    ("contacts.tab_loyalty", "Sodiqlik", "Лояльность", "Loyalty"),
    ("contacts.tab_care", "Xizmat", "Сервис", "Care"),
    ("contacts.tab_consent", "Rozilik va ma’lumotlar", "Согласия и данные", "Consent & data"),
    ("contacts.ai_summary", "AI xulosa", "AI-сводка", "AI summary"),
    ("contacts.ai_new", "Ro‘yxatdan o‘tgan: {d}. Hali xarid qilmagan. Birinchi tashrifda sodiqlik kartasi afzalliklarini ayting va doimiy ichadigan dorilari haqida so‘rang.", "Клиент с {d}, покупок пока нет. При первом визите расскажите о карте лояльности и спросите о постоянных лекарствах.", "Customer since {d}, no purchases yet. On the first visit, explain the loyalty card and ask about regular medicines."),
    ("contacts.ai_on_device", "Qurilmada", "На устройстве", "On device"),
    ("contacts.ai_local", "Bu qurilmada xaridlar tarixidan hisoblandi. Daybook ulansa, matnni Daybook AI (Claude Haiku) yozadi.", "Посчитано на этом устройстве по истории покупок. При подключении Daybook текст пишет Daybook AI (Claude Haiku).", "Computed on this device from the purchase history. With Daybook connected, Daybook AI (Claude Haiku) writes it."),
    ("contacts.ai_cloud", "Daybook AI (Claude Haiku) yozdi, ma’lumotlar sizning Daybook serveringizda qayta ishlanadi.", "Написано Daybook AI (Claude Haiku) на вашем сервере Daybook.", "Written by Daybook AI (Claude Haiku) on your Daybook server."),
    ("contacts.nba", "Keyingi eng yaxshi qadamlar", "Следующие лучшие действия", "Next best actions"),
    ("contacts.nba_empty", "Hozircha tavsiya yo‘q: mijoz bilan hammasi joyida", "Пока рекомендаций нет: с клиентом всё в порядке", "No suggestions right now: this customer is in good shape"),
    ("contacts.nba_remind", "Eslatish", "Напомнить", "Remind"),
    ("contacts.nba_bonus", "Ball sovg‘a qilish", "Подарить баллы", "Gift points"),
    ("contacts.nba_offer", "Taklif yuborish", "Отправить предложение", "Send offer"),
    ("contacts.nba_upgrade", "Xabar berish", "Сообщить", "Tell them"),
    ("contacts.nba_consent", "Rozilik olindi", "Согласие получено", "Consent given"),
    ("contacts.reminder_sent", "Telegramda eslatma yuborildi", "Напоминание отправлено в Telegram", "Reminder sent on Telegram"),
    ("contacts.offer_sent", "Shaxsiy taklif Telegramda yuborildi", "Персональное предложение отправлено в Telegram", "Personal offer sent on Telegram"),
    ("contacts.bonus_given", "Bonus ballar berildi", "Бонусные баллы начислены", "Bonus points added"),
    ("contacts.consent_saved", "Rozilik saqlandi", "Согласие сохранено", "Consent saved"),
    ("contacts.recent", "So‘nggi voqealar", "Последние события", "Recent activity"),
    ("contacts.upcoming", "Rejadagi ishlar", "Запланировано", "Upcoming"),
    ("contacts.no_upcoming", "Rejalashtirilgan ish yo‘q", "Ничего не запланировано", "Nothing planned"),
    ("contacts.task_done", "Vazifa bajarildi", "Задача выполнена", "Task done"),
    ("contacts.full_timeline", "To‘liq tarix", "Вся история", "Full timeline"),
    ("contacts.about", "Ma’lumotlar", "Сведения", "About"),
    ("contacts.birthday", "Tug‘ilgan kun", "День рождения", "Birthday"),
    ("contacts.district", "Tuman", "Район", "District"),
    ("contacts.card", "Karta raqami", "Номер карты", "Card number"),
    ("contacts.nps", "NPS bahosi", "Оценка NPS", "NPS score"),
    ("contacts.favourites", "Ko‘p oladigan dorilari", "Чаще всего покупает", "Buys most often"),
    ("contacts.referred_by", "Uni tavsiya qilgan", "Порекомендовал(а)", "Referred them"),
    ("contacts.friend", "Tavsiyasi bilan kelgan", "Пришёл(ла) по рекомендации", "Came on their referral"),
    ("contacts.k_activity", "Faoliyat", "Активности", "Activities"),
    ("contacts.k_message", "Yozishmalar", "Переписка", "Messages"),
    ("contacts.spend_12m", "Oxirgi 12 oydagi xaridlar", "Покупки за 12 месяцев", "Spend, last 12 months"),
    // medicines
    ("contacts.health_title", "Doimiy dorilar", "Постоянные лекарства", "Regular medicines"),
    ("contacts.health_audit", "Har bir ko‘rish jurnalga yoziladi", "Каждый просмотр пишется в журнал", "Every view is written to the audit log"),
    ("contacts.health_viewed", "Sog‘liq ma’lumotlari ko‘rildi", "Просмотр данных о здоровье", "Health data viewed"),
    ("contacts.no_consent_title", "Sog‘liq ma’lumotlariga rozilik yo‘q", "Нет согласия на данные о здоровье", "No consent for health data"),
    ("contacts.no_consent_text", "Dorilar, kasalliklar va allergiyalar faqat mijozning roziligi bilan saqlanadi (shaxsga doir ma’lumotlar to‘g‘risidagi qonun). Rozilik olingach, dori radari dori tugashidan oldin eslatadi.", "Лекарства, диагнозы и аллергии хранятся только с согласия клиента (закон о персональных данных). После согласия радар лекарств напомнит до того, как лекарство закончится.", "Medicines, conditions and allergies are kept only with the customer’s consent (personal data law). Once given, the refill radar reminds them before a medicine runs out."),
    ("contacts.record_consent", "Rozilikni qayd etish", "Записать согласие", "Record consent"),
    ("contacts.add_regimen", "Doimiy dori qo‘shish", "Добавить лекарство", "Add regimen"),
    ("contacts.no_regimens", "Doimiy dorilar kiritilmagan", "Постоянных лекарств нет", "No regular medicines yet"),
    ("contacts.no_regimens_text", "Doimiy dori qo‘shsangiz, radar qadoq tugashini hisoblab, vaqtida eslatadi.", "Добавьте постоянное лекарство, и радар посчитает, когда закончится упаковка.", "Add a regular medicine and the radar works out when the pack runs out."),
    ("contacts.next_due", "Tugaydi", "Закончится", "Runs out"),
    ("contacts.ran_out", "Tugagan", "Закончилось", "Ran out"),
    ("contacts.benefits", "Daraja imtiyozlari", "Привилегии уровня", "Tier benefits"),
    ("contacts.b_birthday", "Tug‘ilgan kun bonusi", "Бонус на день рождения", "Birthday bonus"),
    ("contacts.b_redeem", "Chekni ball bilan to‘lash, gacha", "Оплата баллами, до", "Pay with points, up to"),
    ("contacts.b_expiry", "Ballar amal qiladi", "Баллы действуют", "Points last"),
    ("contacts.b_rx", "Retseptli dorilar", "Рецептурные препараты", "Prescription medicines"),
    ("contacts.b_rx_no", "ball berilmaydi", "без баллов", "earn no points"),
    ("contacts.pack", "Qadoq:", "Упаковка:", "Pack:"),
    ("contacts.last_bought", "Oxirgi marta olingan", "Последняя покупка", "Last bought"),
    ("contacts.remind", "Eslatma", "Напоминание", "Reminder"),
    ("contacts.remind_hint", "Tugashidan oldin Telegramda eslatish", "Напоминать в Telegram до окончания", "Remind on Telegram before it runs out"),
    ("contacts.dose", "Qabul qilish tartibi", "Схема приёма", "Dose"),
    ("contacts.pack_days", "Bir qadoq necha kunga yetadi", "На сколько дней упаковка", "Days per pack"),
    ("contacts.allergies", "Allergiyalar", "Аллергии", "Allergies"),
    ("contacts.no_allergies", "Allergiya qayd etilmagan", "Аллергии не отмечены", "No allergies recorded"),
    ("contacts.allergy_hint", "Masalan: Penitsillin", "Например: пенициллин", "e.g. Penicillin"),
    ("contacts.regimen_saved", "Doimiy dori qo‘shildi", "Лекарство добавлено", "Regimen added"),
    ("contacts.removed", "O‘chirildi", "Удалено", "Removed"),
    // loyalty
    ("contacts.cashback", "Keshbek", "Кешбэк", "Cashback"),
    ("contacts.balance", "Ballar balansi", "Баланс баллов", "Points balance"),
    ("contacts.to_next", "{tier} darajasigacha {sum} qoldi", "До уровня «{tier}» осталось {sum}", "{sum} more to reach {tier}"),
    ("contacts.top_tier", "Eng yuqori daraja", "Высший уровень", "Top tier reached"),
    ("contacts.ledger", "Ballar tarixi", "История баллов", "Points history"),
    ("contacts.no_ledger", "Oxirgi 5 oyda ballar harakati yo‘q", "За 5 месяцев движений по баллам нет", "No points activity in the last 5 months"),
    // care
    ("contacts.no_tickets", "Murojaatlar yo‘q", "Обращений нет", "No tickets"),
    ("contacts.no_waitlist", "Defekturada hech narsa yo‘q", "В дефектуре ничего нет", "Nothing on the waitlist"),
    ("contacts.notify", "Xabar berish", "Уведомить", "Notify"),
    ("contacts.notified_toast", "Mijozga dori kelgani haqida xabar berildi", "Клиент уведомлён о поступлении", "Customer told their medicine has arrived"),
    // notes
    ("contacts.note_placeholder", "Mijoz haqida bilish muhim bo‘lgan narsa…", "Что важно знать о клиенте…", "Something worth knowing about this customer…"),
    ("contacts.pin", "Qadab qo‘yish", "Закрепить", "Pin"),
    ("contacts.pinned", "Qadalgan", "Закреплено", "Pinned"),
    ("contacts.sensitive", "Sog‘liq bilan bog‘liq (maxfiy)", "Связано со здоровьем (скрыто)", "Health-related (sensitive)"),
    ("contacts.sensitive_short", "Maxfiy", "Скрыто", "Sensitive"),
    ("contacts.note_saved", "Izoh saqlandi", "Заметка сохранена", "Note saved"),
    ("contacts.no_notes", "Izohlar hali yo‘q", "Заметок пока нет", "No notes yet"),
    ("contacts.profile_note", "Kartadagi izoh", "Заметка в карточке", "Profile note"),
    // consent
    ("contacts.consent", "Roziliklar", "Согласия", "Consents"),
    ("contacts.consent_since", "Qayd etilgan:", "Записано:", "Recorded"),
    ("contacts.consent_health", "Sog‘liq ma’lumotlari", "Данные о здоровье", "Health data"),
    ("contacts.consent_tg_hint", "Eslatmalar, bonuslar va kampaniyalar Telegram bot orqali", "Напоминания, бонусы и рассылки через Telegram-бот", "Reminders, bonuses and campaigns through the Telegram bot"),
    ("contacts.consent_sms_hint", "Telegram bo‘lmasa, muhim eslatmalar SMS orqali", "Важные напоминания по SMS, если нет Telegram", "Important reminders by SMS when there’s no Telegram"),
    ("contacts.consent_health_hint", "O‘chirilsa, dorilar yashiriladi va eslatmalar to‘xtaydi", "Если выключить, лекарства скроются и напоминания прекратятся", "Turning it off hides medicines and stops refill reminders"),
    ("contacts.data", "Ma’lumotlar", "Данные", "Data"),
    ("contacts.export_data", "Mijoz ma’lumotlarini eksport qilish", "Экспорт данных клиента", "Export customer data"),
    ("contacts.export_data_hint", "Mijoz so‘rasa, barcha ma’lumotlarini bitta faylda bering", "По запросу клиента выдайте все его данные одним файлом", "When a customer asks, hand them all their data in one file"),
    ("contacts.exported_one", "Ma’lumotlar JSON faylga tayyorlandi", "Данные подготовлены в JSON", "Data prepared as a JSON file"),
    ("contacts.archive", "Mijozni arxivlash", "Архивировать клиента", "Archive customer"),
    ("contacts.archive_short", "Arxivlash", "В архив", "Archive"),
    ("contacts.archive_hint", "Arxivdagi mijoz ro‘yxatlar, segmentlar va kampaniyalarga tushmaydi", "Архивный клиент не попадает в списки, сегменты и рассылки", "Archived customers are left out of lists, segments and campaigns"),
    ("contacts.archive_confirm", "{name} arxivga o‘tkazilsinmi? Xaridlar tarixi saqlanadi, istalgan payt qaytarish mumkin.", "Перенести клиента {name} в архив? История покупок сохранится, вернуть можно в любой момент.", "Archive {name}? The purchase history stays, and you can restore them any time."),
    ("contacts.archived_toast", "Mijoz arxivga o‘tkazildi", "Клиент перенесён в архив", "Customer archived"),
    ("contacts.archived_badge", "Arxivda", "В архиве", "Archived"),
    ("contacts.restore", "Arxivdan qaytarish", "Вернуть из архива", "Restore"),
    ("contacts.restored", "Mijoz qaytarildi", "Клиент возвращён", "Customer restored"),
    // dialogs
    ("contacts.task_default", "Qayta qo‘ng‘iroq", "Перезвонить", "Call back"),
    ("contacts.priority", "Muhimligi", "Приоритет", "Priority"),
    ("contacts.reason", "Sabab", "Причина", "Reason"),
    ("contacts.bonus_default", "Sovg‘a", "Подарок", "Gift"),
    ("contacts.bonus_hint", "1 ball = 1 so‘m. Ballar mijozning Telegram kartasida darhol ko‘rinadi.", "1 балл = 1 сум. Баллы сразу появятся в Telegram-карте клиента.", "1 point = 1 so‘m. The points appear in the customer’s Telegram card right away."),
    ("contacts.reserve_title", "Dorini bron qilish", "Забронировать лекарство", "Reserve a medicine"),
    ("contacts.qty", "Soni", "Количество", "Quantity"),
    ("contacts.in_stock", "Filialda bor", "В наличии в филиале", "In stock at this branch"),
    ("contacts.not_in_stock", "Bu filialda yo‘q: buyurtma qilinadi, 2 kunda keladi", "В филиале нет: закажем, будет через 2 дня", "Not in stock here: we’ll order it, about 2 days"),
    ("contacts.reserved_toast", "Bron qilindi", "Забронировано", "Reserved"),
];
