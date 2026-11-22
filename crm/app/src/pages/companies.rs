//! Companies (B2B): clinics, hospitals, corporate clients, insurers, schools and distributors.
//! A card grid or a table with receivables against the credit limit and account health, and a
//! company page with contact persons, deals, quotes and invoices, activities, notes and the
//! employees covered by a corporate agreement.

use chrono::{Datelike, NaiveDate};
use crm::fmt;
use crm::i18n::Entry;
use crm::model::*;
use dioxus::prelude::*;

use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

fn kind_tone(k: OrgKind) -> &'static str {
    match k {
        OrgKind::Clinic | OrgKind::Lab => "info",
        OrgKind::Hospital => "danger",
        OrgKind::Corporate => "accent",
        OrgKind::Insurance => "success",
        OrgKind::Distributor | OrgKind::Government => "muted",
        OrgKind::School | OrgKind::Kindergarten => "warning",
    }
}

fn quote_tone(s: QuoteStatus) -> &'static str {
    match s {
        QuoteStatus::Draft => "",
        QuoteStatus::Sent => "info",
        QuoteStatus::Accepted | QuoteStatus::Paid => "success",
        QuoteStatus::Rejected | QuoteStatus::Overdue => "danger",
        QuoteStatus::Invoiced => "accent",
    }
}

fn deal_tone(s: DealStatus) -> &'static str {
    match s {
        DealStatus::Open => "info",
        DealStatus::Won => "success",
        DealStatus::Lost => "danger",
    }
}

fn health_color(h: u8) -> &'static str {
    match score_tone(h) {
        "danger" => "var(--c-danger)",
        "warning" => "var(--c-warning)",
        _ => "var(--c-success)",
    }
}

fn usage(receivable: Money, limit: Money) -> f64 {
    if limit > 0 {
        receivable as f64 / limit as f64 * 100.0
    } else if receivable > 0 {
        100.0
    } else {
        0.0
    }
}

fn usage_tone(pct: f64) -> &'static str {
    if pct > 100.0 {
        "danger"
    } else if pct > 80.0 {
        "warning"
    } else {
        "success"
    }
}

#[derive(Clone, PartialEq)]
struct CoRow {
    id: Id,
    name: String,
    kind: OrgKind,
    district: String,
    tin: String,
    contacts: usize,
    open_value: Money,
    open_count: usize,
    receivable: Money,
    limit: Money,
    health: u8,
    owner: Option<(String, u16)>,
    tags: Vec<String>,
    covered: usize,
}

#[component]
pub fn Companies() -> Element {
    let mut query = use_signal(String::new);
    let mut kind = use_signal(|| None::<OrgKind>);
    let mut view = use_signal(|| "grid".to_string());
    let mut creating = use_signal(|| false);
    let rows = use_memo(move || {
        let db = DB.read();
        let mut v: Vec<CoRow> = db
            .companies
            .iter()
            .map(|c| {
                let open: Vec<&Deal> = db.deals.iter().filter(|d| d.company_id == Some(c.id) && d.status == DealStatus::Open).collect();
                CoRow {
                    id: c.id,
                    name: c.name.clone(),
                    kind: c.kind,
                    district: c.district.clone(),
                    tin: c.tin.clone(),
                    contacts: c.contacts.len(),
                    open_value: open.iter().map(|d| db.deal_value(d)).sum(),
                    open_count: open.len(),
                    receivable: c.receivable,
                    limit: c.credit_limit,
                    health: c.health,
                    owner: c.owner_id.and_then(|o| db.staff_member(o)).map(|s| (s.name.clone(), s.hue)),
                    tags: c.tags.clone(),
                    covered: db.customers.iter().filter(|x| x.company_id == Some(c.id) && !x.archived).count(),
                }
            })
            .collect();
        v.sort_by(|a, b| b.open_value.cmp(&a.open_value).then(b.receivable.cmp(&a.receivable)));
        v
    });
    let won_year = use_memo(move || {
        let db = DB.read();
        let y = crate::state::today().year();
        db.deals
            .iter()
            .filter(|d| d.company_id.is_some() && d.status == DealStatus::Won && d.closed_at.map(|c| c.date().year() == y).unwrap_or(false))
            .map(|d| db.deal_value(d))
            .sum::<Money>()
    });

    let l = lang();
    let all = rows();
    let total_recv: Money = all.iter().map(|r| r.receivable).sum();
    let near_limit = all.iter().filter(|r| r.limit > 0 && usage(r.receivable, r.limit) > 80.0).count();
    let pipeline: Money = all.iter().map(|r| r.open_value).sum();
    let open_deals: usize = all.iter().map(|r| r.open_count).sum();
    let at_risk: Vec<&CoRow> = all.iter().filter(|r| r.health < 60).collect();
    let risk_recv: Money = at_risk.iter().map(|r| r.receivable).sum();
    let n_risk = at_risk.len();
    let q = query().trim().to_lowercase();
    let kind_v = kind();
    let shown: Vec<CoRow> = all
        .iter()
        .filter(|r| kind_v.map_or(true, |k| r.kind == k))
        .filter(|r| q.is_empty() || r.name.to_lowercase().contains(&q) || r.tin.contains(&q) || r.district.to_lowercase().contains(&q))
        .cloned()
        .collect();
    let kinds: Vec<(OrgKind, String, usize)> = OrgKind::ALL
        .iter()
        .copied()
        .map(|k| (k, t(k.key()), all.iter().filter(|r| r.kind == k).count()))
        .filter(|x| x.2 > 0)
        .collect();
    let subtitle = format!("{} · {}", fmt::plural(all.len() as i64, l, "tashkilot|организация|организации|организаций|company|companies"), t("companies.subtitle"));
    let view_v = view();

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.companies"), subtitle,
                Segmented {
                    options: vec![("grid".into(), t("companies.cards")), ("table".into(), t("companies.table"))],
                    value: view_v.clone(),
                    onchange: move |v| view.set(v),
                }
                button { class: "btn", onclick: move |_| creating.set(true),
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("companies.new")} }
                }
                button { class: "btn primary", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Deal),
                    Icon { name: "square-kanban", size: 16 }
                    span { class: "label-text", {t("palette.new_deal")} }
                }
            }

            div { class: "grid-4",
                Kpi { label: t("companies.receivable"), value: money_short(total_recv), icon: "receipt", tone: "warning",
                    foot: t("companies.near_limit_n").replace("{n}", &near_limit.to_string()),
                    onclick: move |_| go("/quotes"),
                }
                Kpi { label: t("companies.pipeline"), value: money_short(pipeline), icon: "square-kanban", tone: "info",
                    foot: fmt::plural(open_deals as i64, l, "ochiq bitim|открытая сделка|открытые сделки|открытых сделок|open deal|open deals"),
                    onclick: move |_| go("/deals"),
                }
                Kpi { label: t("companies.at_risk"), value: fmt::num(n_risk as i64), icon: "heart-pulse", tone: "danger",
                    foot: format!("{} · {}", t("companies.health_below"), money_short(risk_recv)),
                }
                Kpi { label: t("companies.won_year"), value: money_short(won_year()), icon: "trophy", tone: "success", foot: t("companies.b2b") }
            }

            div { class: "toolbar",
                div { class: "search",
                    Icon { name: "search", size: 16 }
                    input { class: "input", r#type: "search", placeholder: t("companies.search"), value: "{query}", oninput: move |e| query.set(e.value()) }
                }
                div { class: "chips grow",
                    button { class: if kind_v.is_none() { "chip on" } else { "chip" }, onclick: move |_| kind.set(None),
                        {t("common.all")}
                        span { class: "count num", "{all.len()}" }
                    }
                    for (k, label, n) in kinds {
                        button { key: "{k.slug()}", class: if kind_v == Some(k) { "chip on" } else { "chip" }, onclick: move |_| kind.set(Some(k)),
                            Icon { name: crm::db::org_icon(k), size: 14 }
                            "{label}"
                            span { class: "count num", "{n}" }
                        }
                    }
                }
            }

            if shown.is_empty() {
                div { class: "card",
                    Empty { icon: "building-2", title: t("common.no_results"), text: t("companies.no_results_text") }
                }
            } else if view_v == "table" {
                div { class: "card",
                    div { class: "table-wrap",
                        table { class: "table responsive",
                            thead {
                                tr {
                                    th { {t("common.company")} }
                                    th { {t("companies.kind")} }
                                    th { class: "num", {t("companies.contacts")} }
                                    th { class: "num", {t("companies.open_deals")} }
                                    th { style: "min-width: 200px", {t("companies.receivable")} }
                                    th { class: "num", {t("companies.health")} }
                                    th { {t("common.owner")} }
                                }
                            }
                            tbody {
                                for r in shown.iter().cloned() {
                                    CompanyTr { key: "{r.id}", r: r.clone() }
                                }
                            }
                        }
                    }
                }
            } else {
                div { class: "grid-auto", style: "grid-template-columns: repeat(auto-fill, minmax(300px, 1fr))",
                    for r in shown.iter().cloned() {
                        CompanyCard { key: "{r.id}", r: r.clone() }
                    }
                }
            }
            if creating() {
                CompanyModal { id: None, onclose: move |_| creating.set(false) }
            }
        }
    }
}

#[component]
fn CompanyCard(r: CoRow) -> Element {
    let l = lang();
    let id = r.id;
    let pct = usage(r.receivable, r.limit);
    let tone = usage_tone(pct);
    let recv = money_short(r.receivable);
    let limit = if r.limit > 0 { t("companies.of_limit").replace("{limit}", &money_short(r.limit)) } else { t("companies.no_limit") };
    let open = money_short(r.open_value);
    let htone = health_color(r.health);
    let ktone = kind_tone(r.kind);
    let covered = fmt::plural(r.covered as i64, l, "xodim|сотрудник|сотрудника|сотрудников|employee|employees");
    let warn = pct > 80.0 && r.limit > 0;
    let warn_text = if pct > 100.0 { t("companies.over_limit") } else { t("companies.near_limit") };
    let warn_tone: &'static str = if pct > 100.0 { "danger" } else { "warning" };
    rsx! {
        div { class: "card hover pad stack gap-12", onclick: move |_| go(&format!("/companies/{id}")),
            div { class: "row top gap-12",
                IconTile { icon: crm::db::org_icon(r.kind), tone: ktone }
                div { class: "grow stack", style: "gap: 2px",
                    span { class: "strong truncate", style: "font-size: 15px", "{r.name}" }
                    span { class: "small muted truncate", {t(r.kind.key())} " · {r.district}" }
                }
                Ring { pct: r.health as f64, size: 44, stroke: 5, color: htone,
                    span { class: "num strong", style: "font-size: 12px", "{r.health}" }
                }
            }
            div { class: "row", style: "gap: 18px",
                div { class: "stack", style: "gap: 1px",
                    span { class: "xs muted", {t("companies.open_deals")} }
                    span { class: "num strong", "{open}" }
                }
                div { class: "stack", style: "gap: 1px",
                    span { class: "xs muted", {t("companies.contacts")} }
                    span { class: "num strong", "{r.contacts}" }
                }
                if r.covered > 0 {
                    div { class: "stack", style: "gap: 1px",
                        span { class: "xs muted", {t("companies.covered_short")} }
                        span { class: "num strong", "{covered}" }
                    }
                }
            }
            div { class: "stack", style: "gap: 6px",
                div { class: "row between small",
                    span { class: "muted", {t("companies.receivable")} }
                    span { class: "num", b { "{recv}" } span { class: "muted", " {limit}" } }
                }
                if r.limit > 0 {
                    Progress { pct, tone, thin: true }
                } else {
                    div { style: "height: 5px; border-radius: 99px; background: repeating-linear-gradient(90deg, var(--c-surface-3) 0 6px, transparent 6px 10px)" }
                }
            }
            div { class: "row between", style: "margin-top: 2px",
                div { class: "row gap-8 small muted",
                    if let Some((name, hue)) = r.owner.clone() {
                        Avatar { name: name.clone(), hue, size: "xs" }
                        span { class: "truncate", "{name}" }
                    }
                }
                div { class: "row gap-4",
                    if warn {
                        Badge { text: warn_text, tone: warn_tone, icon: "triangle-alert" }
                    }
                    for tg in r.tags.iter().take(1).cloned() {
                        span { key: "{tg}", class: "tag", "{tg}" }
                    }
                }
            }
        }
    }
}

#[component]
fn CompanyTr(r: CoRow) -> Element {
    let id = r.id;
    let pct = usage(r.receivable, r.limit);
    let tone = usage_tone(pct);
    let recv = money_short(r.receivable);
    let limit = if r.limit > 0 { money_short(r.limit) } else { "—".to_string() };
    let open = money_short(r.open_value);
    let ktone = kind_tone(r.kind);
    let htone = score_tone(r.health);
    rsx! {
        tr { class: "click", onclick: move |_| go(&format!("/companies/{id}")),
            td {
                div { class: "cell-main",
                    IconTile { icon: crm::db::org_icon(r.kind), tone: ktone, size: "sm" }
                    div { class: "stack", style: "gap: 1px; min-width: 0",
                        span { class: "strong truncate", "{r.name}" }
                        span { class: "xs muted", "{r.district}" }
                    }
                }
            }
            td { class: "m-hide muted", {t(r.kind.key())} }
            td { class: "num m-hide", "{r.contacts}" }
            td { class: "num strong", "{open}" }
            td { class: "m-hide",
                div { class: "stack", style: "gap: 4px",
                    span { class: "small num", b { "{recv}" } span { class: "muted", " / {limit}" } }
                    if r.limit > 0 { Progress { pct, tone, thin: true } }
                }
            }
            td { class: "num m-hide", Badge { text: format!("{}", r.health), tone: htone } }
            td { class: "m-hide",
                if let Some((name, hue)) = r.owner.clone() {
                    Avatar { name, hue, size: "xs" }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- company page

#[component]
pub fn CompanyDetail(id: u32) -> Element {
    rsx! {
        CompanyPage { key: "{id}", id }
    }
}

#[derive(Clone, PartialEq)]
struct DealLine {
    id: Id,
    title: String,
    stage: String,
    hue: u16,
    value: Money,
    status: DealStatus,
    close: NaiveDate,
}

#[component]
fn CompanyPage(id: Id) -> Element {
    let mut note = use_signal(String::new);
    let mut editing = use_signal(|| false);
    let now = now();
    let today = now.date();
    let l = lang();
    let Some(co) = DB.read().company(id).cloned() else {
        return rsx! {
            div { class: "page",
                Empty { icon: "building-2", title: t("companies.not_found"),
                    Link { to: Route::Companies {}, class: "btn primary", Icon { name: "arrow-left", size: 16 } {t("nav.companies")} }
                }
            }
        };
    };
    let (owner, deals, quotes, acts, notes, covered) = {
        let db = DB.read();
        let owner = co.owner_id.and_then(|o| db.staff_member(o)).map(|s| (s.name.clone(), s.hue));
        let mut deals: Vec<DealLine> = db
            .deals
            .iter()
            .filter(|d| d.company_id == Some(id))
            .map(|d| {
                let (stage, hue) = db.stage(d.stage_id).map(|(_, s)| (s.name.clone(), s.hue)).unwrap_or_default();
                DealLine { id: d.id, title: d.title.clone(), stage, hue, value: db.deal_value(d), status: d.status, close: d.closed_at.map(|c| c.date()).unwrap_or(d.expected_close) }
            })
            .collect();
        deals.sort_by(|a, b| (a.status != DealStatus::Open).cmp(&(b.status != DealStatus::Open)).then(b.value.cmp(&a.value)));
        let mut quotes: Vec<(Id, String, QuoteStatus, Money, NaiveDate)> =
            db.quotes.iter().filter(|q| q.company_id == id).map(|q| (q.id, q.number.clone(), q.status, q.total(), q.issued)).collect();
        quotes.sort_by(|a, b| b.4.cmp(&a.4));
        let mut acts: Vec<(Activity, String, u16)> = db
            .activities
            .iter()
            .filter(|a| a.company_id == Some(id))
            .map(|a| {
                let s = db.staff_member(a.owner_id);
                (a.clone(), s.map(|s| s.name.clone()).unwrap_or_default(), s.map(|s| s.hue).unwrap_or(24))
            })
            .collect();
        acts.sort_by(|a, b| a.0.done.cmp(&b.0.done).then(if a.0.done { b.0.due.cmp(&a.0.due) } else { a.0.due.cmp(&b.0.due) }));
        acts.truncate(10);
        let mut notes: Vec<(Note, String, u16)> = db
            .notes
            .iter()
            .filter(|n| n.company_id == Some(id))
            .map(|n| {
                let s = n.author_id.and_then(|a| db.staff_member(a));
                (n.clone(), s.map(|s| s.name.clone()).unwrap_or_else(|| "—".into()), s.map(|s| s.hue).unwrap_or(24))
            })
            .collect();
        notes.sort_by(|a, b| b.0.pinned.cmp(&a.0.pinned).then(b.0.at.cmp(&a.0.at)));
        let covered: Vec<(Id, String)> = db.customers.iter().filter(|c| c.company_id == Some(id) && !c.archived).map(|c| (c.id, c.name())).collect();
        (owner, deals, quotes, acts, notes, covered)
    };
    let open_value: Money = deals.iter().filter(|d| d.status == DealStatus::Open).map(|d| d.value).sum();
    let open_n = deals.iter().filter(|d| d.status == DealStatus::Open).count();
    let won_year: Money = {
        let db = DB.read();
        db.deals
            .iter()
            .filter(|d| d.company_id == Some(id) && d.status == DealStatus::Won && d.closed_at.map(|c| c.date().year() == today.year()).unwrap_or(false))
            .map(|d| db.deal_value(d))
            .sum()
    };
    let won_n = deals.iter().filter(|d| d.status == DealStatus::Won).count();
    let pct = usage(co.receivable, co.credit_limit);
    let utone = usage_tone(pct);
    let recv = money_short(co.receivable);
    let limit_line = if co.credit_limit > 0 {
        format!("{} · {}", t("companies.of_limit").replace("{limit}", &money_short(co.credit_limit)), fmt::days(co.terms_days as i64, l))
    } else {
        t("companies.no_limit")
    };
    let htone = score_tone(co.health);
    let hcolor = health_color(co.health);
    let health_word = match htone {
        "danger" => t("companies.health_bad"),
        "warning" => t("companies.health_mid"),
        _ => t("companies.health_good"),
    };
    let ktone = kind_tone(co.kind);
    let phone_s = phone(&co.phone);
    let tel = fmt::tel_href(&co.phone);
    let mail = format!("mailto:{}", co.email);
    let employees = fmt::plural(co.employees as i64, l, "xodim|сотрудник|сотрудника|сотрудников|employee|employees");
    let n_covered = covered.len();
    let primary_contact = co.contacts.iter().find(|c| c.primary).or(co.contacts.first()).map(|c| c.name.clone()).unwrap_or_default();

    let log_call = move |who: String| {
        let title = format!("{}: {}", t("activity.call"), who);
        let outcome = t("contacts.call_outcome");
        let now = crate::state::now();
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
                customer_id: None,
                company_id: Some(id),
                deal_id: None,
                ticket_id: None,
                priority: Priority::Normal,
                outcome: Some(outcome),
                duration_min: 6,
                daybook_task: None,
            });
        });
        toast(t("contacts.call_logged"), "phone", "success");
    };
    let add_note = move |_| {
        let v = note().trim().to_string();
        if v.is_empty() {
            return;
        }
        let now = crate::state::now();
        mutate(|db| {
            let nid = db.new_id();
            let me = db.settings.me;
            db.notes.push(Note { id: nid, at: now, author_id: Some(me), text: v, customer_id: None, company_id: Some(id), deal_id: None, pinned: false, sensitive: false });
        });
        note.set(String::new());
        toast(t("contacts.note_saved"), "sticky-note", "success");
    };

    rsx! {
        div { class: "page",
            div { class: "row",
                Link { to: Route::Companies {}, class: "btn ghost sm", Icon { name: "arrow-left", size: 15 } {t("nav.companies")} }
            }
            div { class: "card pad stack gap-16",
                div { class: "row top gap-16 wrap",
                    IconTile { icon: crm::db::org_icon(co.kind), tone: ktone, size: "lg" }
                    div { class: "grow stack gap-8",
                        div { class: "row wrap gap-8",
                            h1 { style: "font-size: 24px; font-weight: 700; letter-spacing: -0.02em", "{co.name}" }
                            Badge { text: t(co.kind.key()), tone: ktone }
                            button { class: "icon-btn sm", title: t("companies.edit"), onclick: move |_| editing.set(true), Icon { name: "pen-line", size: 15 } }
                            for tg in co.tags.iter().cloned() {
                                span { key: "{tg}", class: "tag", "{tg}" }
                            }
                        }
                        div { class: "row wrap small muted", style: "gap: 6px 16px",
                            if !co.tin.is_empty() {
                                span { class: "row gap-4 num", Icon { name: "hash", size: 14, class: "subtle" } {t("companies.tin")} " {co.tin}" }
                            }
                            if !co.address.is_empty() {
                                span { class: "row gap-4", Icon { name: "map-pin", size: 14, class: "subtle" } "{co.address}" }
                            }
                            if !co.phone.is_empty() {
                                a { href: "{tel}", class: "row gap-4 num strong", Icon { name: "phone", size: 14, class: "subtle" } "{phone_s}" }
                            }
                            if !co.email.is_empty() {
                                a { href: "{mail}", class: "row gap-4", Icon { name: "mail", size: 14, class: "subtle" } "{co.email}" }
                            }
                            if co.employees > 0 {
                                span { class: "row gap-4", Icon { name: "users", size: 14, class: "subtle" } "{employees}" }
                            }
                            if let Some((oname, ohue)) = owner.clone() {
                                span { class: "row gap-4", Avatar { name: oname.clone(), hue: ohue, size: "xs" } "{oname}" }
                            }
                        }
                    }
                    div { class: "row gap-8 wrap",
                        button { class: "btn", onclick: move |_| log_call(primary_contact.clone()), Icon { name: "phone-call", size: 16 } {t("companies.log_call")} }
                        button { class: "btn primary", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Deal), Icon { name: "plus", size: 16 } {t("palette.new_deal")} }
                    }
                }
            }

            div { class: "grid-4",
                div { class: "card kpi",
                    div { class: "kpi-label", span { class: "icon-wrap ic warning", Icon { name: "receipt", size: 15 } } span { class: "truncate", {t("companies.receivable")} } }
                    div { class: "kpi-value", "{recv}" }
                    if co.credit_limit > 0 { Progress { pct, tone: utone, thin: true } }
                    div { class: "kpi-foot", span { class: "truncate", "{limit_line}" } }
                }
                Kpi { label: t("companies.open_deals"), value: money_short(open_value), icon: "square-kanban", tone: "info",
                    foot: fmt::plural(open_n as i64, l, "bitim|сделка|сделки|сделок|deal|deals") }
                Kpi { label: t("companies.won_year"), value: money_short(won_year), icon: "trophy", tone: "success",
                    foot: format!("{} · {}", t("deal_status.won"), won_n) }
                div { class: "card kpi",
                    div { class: "kpi-label", span { class: "icon-wrap ic success", Icon { name: "heart-pulse", size: 15 } } span { class: "truncate", {t("companies.health")} } }
                    div { class: "row gap-12",
                        Ring { pct: co.health as f64, size: 52, stroke: 6, color: hcolor, span { class: "num strong", "{co.health}" } }
                        div { class: "stack", style: "gap: 2px",
                            span { class: "strong", "{health_word}" }
                            span { class: "xs muted", {t("companies.health_hint")} }
                        }
                    }
                }
            }

            div { class: "grid-main",
                div { class: "stack gap-16",
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "square-kanban", size: 16, class: "subtle" } {t("nav.deals")} }
                            button { class: "btn ghost sm", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Deal), Icon { name: "plus", size: 14 } {t("common.deal")} }
                        }
                        div { class: "list", style: "margin-top: 6px",
                            if deals.is_empty() {
                                Empty { icon: "square-kanban", title: t("companies.no_deals") }
                            }
                            for d in deals {
                                {
                                    let did = d.id;
                                    let value = money_short(d.value);
                                    let close = fmt::date(d.close, today, l);
                                    let stone = deal_tone(d.status);
                                    let status = t(d.status.key());
                                    rsx! {
                                        div { key: "{did}", class: "list-row click", onclick: move |_| go(&format!("/deals/{did}")),
                                            span { style: "width: 10px; height: 10px; border-radius: 3px; flex: 0 0 10px; background: hsl({d.hue} 48% 52%)" }
                                            div { class: "meta",
                                                span { class: "title small truncate", "{d.title}" }
                                                span { class: "sub truncate", "{d.stage} · {close}" }
                                            }
                                            span { class: "num strong small nowrap", "{value}" }
                                            Badge { text: status, tone: stone }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "file-text", size: 16, class: "subtle" } {t("nav.quotes")} }
                        }
                        div { class: "list", style: "margin-top: 6px",
                            if quotes.is_empty() {
                                Empty { icon: "file-text", title: t("companies.no_quotes") }
                            }
                            for (qid, number, status, total, issued) in quotes {
                                {
                                    let total_s = money(total);
                                    let issued_s = fmt::date(issued, today, l);
                                    let tone = quote_tone(status);
                                    rsx! {
                                        div { key: "{qid}", class: "list-row click", onclick: move |_| go(&format!("/quotes/{qid}")),
                                            span { class: "ic muted sm", Icon { name: "receipt", size: 14 } }
                                            div { class: "meta",
                                                span { class: "title small num", "{number}" }
                                                span { class: "sub", "{issued_s}" }
                                            }
                                            span { class: "num strong small nowrap", "{total_s}" }
                                            Badge { text: t(status.key()), tone }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "list-checks", size: 16, class: "subtle" } {t("companies.activities")} }
                            button { class: "btn ghost sm", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Task), Icon { name: "plus", size: 14 } {t("common.task")} }
                        }
                        div { class: "list", style: "margin-top: 6px",
                            if acts.is_empty() {
                                Empty { icon: "calendar-check", title: t("companies.no_activities") }
                            }
                            for (a, oname, ohue) in acts {
                                {
                                    let aid = a.id;
                                    let when = fmt::relative(a.done_at.unwrap_or(a.due), now, l);
                                    let overdue = !a.done && a.due < now;
                                    let check_cls = if a.done { "check-circle on" } else { "check-circle" };
                                    let title_style = if a.done { "text-decoration: line-through; opacity: .55" } else { "" };
                                    let when_cls = if overdue { "tone-danger strong" } else { "" };
                                    let icon = crm::db::activity_icon(a.kind);
                                    rsx! {
                                        div { key: "{aid}", class: "list-row",
                                            button { class: check_cls, onclick: move |_| mutate(|db| db.complete_activity(aid, crate::state::now())), Icon { name: "check", size: 13 } }
                                            div { class: "meta",
                                                span { class: "title small truncate", style: title_style, "{a.title}" }
                                                span { class: "sub row gap-4", Icon { name: icon, size: 12 } span { class: when_cls, "{when}" } }
                                            }
                                            Avatar { name: oname.clone(), hue: ohue, size: "xs" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                div { class: "stack gap-16",
                    div { class: "card",
                        div { class: "card-head", div { class: "card-title", Icon { name: "contact", size: 16, class: "subtle" } {t("companies.people")} } }
                        div { class: "list", style: "margin-top: 6px",
                            if co.contacts.is_empty() {
                                div { class: "list-row small muted", {t("companies.no_people")} }
                            }
                            for (k, p) in co.contacts.iter().cloned().enumerate() {
                                {
                                    let tel = fmt::tel_href(&p.phone);
                                    let ph = phone(&p.phone);
                                    let who = p.name.clone();
                                    let tg = p.telegram.clone();
                                    rsx! {
                                        div { key: "{k}", class: "list-row",
                                            Avatar { name: p.name.clone(), size: "sm" }
                                            div { class: "meta",
                                                span { class: "title small row gap-6", style: "gap: 6px", "{p.name}" if p.primary { span { class: "badge sm accent", {t("companies.primary")} } } }
                                                span { class: "sub truncate", "{p.position}" }
                                                a { href: "{tel}", class: "xs muted num", "{ph}" }
                                            }
                                            button { class: "icon-btn sm bordered", title: t("common.call"), onclick: move |_| log_call(who.clone()), Icon { name: "phone", size: 15 } }
                                            if let Some(handle) = tg {
                                                button {
                                                    class: "icon-btn sm bordered",
                                                    title: "{handle}",
                                                    onclick: move |_| toast(format!("{}: {handle}", t("companies.tg_opened")), "send", "info"),
                                                    Icon { name: "send", size: 15 }
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
                            div { class: "card-title", Icon { name: "users", size: 16, class: "subtle" } {t("companies.covered")} }
                            span { class: "badge num", "{n_covered}" }
                        }
                        div { class: "card-body stack gap-12",
                            if covered.is_empty() {
                                span { class: "small muted", {t("companies.no_covered")} }
                            } else {
                                span { class: "small muted", {t("companies.covered_hint")} }
                                div { class: "row wrap", style: "gap: 6px",
                                    for (cid, cname) in covered.iter().take(18).cloned() {
                                        Link { key: "{cid}", to: Route::ContactDetail { id: cid }, Avatar { name: cname, size: "sm" } }
                                    }
                                    if n_covered > 18 {
                                        span { class: "avatar sm", style: "background: var(--c-surface-3); color: var(--c-muted)", "+{n_covered - 18}" }
                                    }
                                }
                                button { class: "btn soft sm", style: "align-self: flex-start", onclick: move |_| go(&format!("/contacts?company={id}")),
                                    Icon { name: "users", size: 14 }
                                    {t("companies.show_covered")}
                                }
                            }
                        }
                    }
                    div { class: "card",
                        div { class: "card-head", div { class: "card-title", Icon { name: "sticky-note", size: 16, class: "subtle" } {t("common.notes")} } }
                        div { class: "card-body stack gap-12",
                            for (n, author, hue) in notes {
                                {
                                    let when = fmt::relative(n.at, now, l);
                                    let nid = n.id;
                                    rsx! {
                                        div { key: "{nid}", class: "stack gap-4", style: "padding-bottom: 10px; border-bottom: 1px dashed var(--c-border)",
                                            div { class: "row gap-8",
                                                Avatar { name: author.clone(), hue, size: "xs" }
                                                span { class: "small strong grow truncate", "{author}" }
                                                if n.pinned { Icon { name: "pin", size: 13, class: "tone-accent" } }
                                                span { class: "xs subtle nowrap", "{when}" }
                                            }
                                            p { class: "small", style: "line-height: 1.5", "{n.text}" }
                                        }
                                    }
                                }
                            }
                            textarea {
                                class: "textarea",
                                style: "min-height: 70px",
                                value: "{note}",
                                placeholder: t("companies.note_placeholder"),
                                oninput: move |e| note.set(e.value()),
                            }
                            button { class: "btn sm primary", style: "align-self: flex-end", disabled: note().trim().is_empty(), onclick: add_note,
                                Icon { name: "check", size: 14 }
                                {t("common.add_note")}
                            }
                        }
                    }
                }
            }
            if editing() {
                CompanyModal { id: Some(id), onclose: move |_| editing.set(false) }
            }
        }
    }
}

#[component]
fn CompanyModal(id: Option<Id>, onclose: EventHandler<()>) -> Element {
    let init = use_hook(move || id.and_then(|i| DB.peek().company(i).cloned()));
    let staff: Vec<(Id, String)> = DB
        .read()
        .staff
        .iter()
        .filter(|s| s.active && matches!(s.role, Role::SalesRep | Role::Manager | Role::Owner))
        .map(|s| (s.id, s.name.clone()))
        .collect();
    let me = DB.peek().settings.me;
    let i0 = init.clone();
    let mut name = use_signal(move || i0.as_ref().map(|c| c.name.clone()).unwrap_or_default());
    let i1 = init.clone();
    let mut kind = use_signal(move || i1.as_ref().map(|c| c.kind).unwrap_or(OrgKind::Clinic));
    let i2 = init.clone();
    let mut tin = use_signal(move || i2.as_ref().map(|c| c.tin.clone()).unwrap_or_default());
    let i3 = init.clone();
    let mut address = use_signal(move || i3.as_ref().map(|c| c.address.clone()).unwrap_or_default());
    let i4 = init.clone();
    let mut phone_v = use_signal(move || i4.as_ref().map(|c| crm::fmt::phone(&c.phone)).unwrap_or_else(|| "+998 ".into()));
    let i5 = init.clone();
    let mut email = use_signal(move || i5.as_ref().map(|c| c.email.clone()).unwrap_or_default());
    let i6 = init.clone();
    let mut limit = use_signal(move || i6.as_ref().map(|c| c.credit_limit.to_string()).unwrap_or_else(|| "20000000".into()));
    let i7 = init.clone();
    let mut terms = use_signal(move || i7.as_ref().map(|c| c.terms_days.to_string()).unwrap_or_else(|| "30".into()));
    let i8 = init.clone();
    let mut owner = use_signal(move || i8.as_ref().and_then(|c| c.owner_id).unwrap_or(me));
    let tin_dup = {
        let v = tin().trim().to_string();
        if v.len() >= 9 { DB.read().companies.iter().find(|c| c.tin == v && Some(c.id) != id).map(|c| c.name.clone()) } else { None }
    };
    let lim: i64 = limit().chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0);
    let valid = !name().trim().is_empty() && tin_dup.is_none();
    let title = if id.is_some() { t("companies.edit") } else { t("companies.new") };
    let save = move |_| {
        let nm = name().trim().to_string();
        if nm.is_empty() {
            return;
        }
        let lim: i64 = limit().chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0);
        let days: u16 = terms().chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(30);
        let ph = {
            let d: String = phone_v().chars().filter(|c| c.is_ascii_digit()).collect();
            if d.len() <= 3 {
                String::new()
            } else {
                phone_v().trim().to_string()
            }
        };
        let (k, tn, ad, em, ow) = (kind(), tin().trim().to_string(), address().trim().to_string(), email().trim().to_string(), owner());
        let today = crate::state::today();
        let log = format!("{}: {nm}", if id.is_some() { t("companies.edit") } else { t("companies.new") });
        let mut target = 0;
        mutate(|db| {
            match id {
                Some(cid) => {
                    target = cid;
                    if let Some(c) = db.company_mut(cid) {
                        c.name = nm;
                        c.kind = k;
                        c.tin = tn;
                        c.address = ad;
                        c.phone = ph;
                        c.email = em;
                        c.credit_limit = lim;
                        c.terms_days = days;
                        c.owner_id = if ow == 0 { None } else { Some(ow) };
                    }
                }
                None => {
                    let cid = db.new_id();
                    target = cid;
                    db.companies.push(Company {
                        id: cid,
                        name: nm,
                        kind: k,
                        tin: tn,
                        district: String::new(),
                        address: ad,
                        phone: ph,
                        email: em,
                        owner_id: if ow == 0 { None } else { Some(ow) },
                        credit_limit: lim,
                        terms_days: days,
                        receivable: 0,
                        tags: vec![],
                        created: today,
                        employees: 0,
                        contacts: vec![],
                        notes: String::new(),
                        health: 70,
                        daybook_id: None,
                    });
                }
            }
            db.log(crate::state::now(), log, false);
        });
        toast(t("common.saved"), "building-2", "success");
        onclose.call(());
        if id.is_none() {
            go(&format!("/companies/{target}"));
        }
    };
    rsx! {
        Modal { title, onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("companies.name")} }
                    input {
                        class: "input",
                        value: "{name}",
                        placeholder: t("companies.name_hint"),
                        oninput: move |e| name.set(e.value()),
                        onmounted: move |e| async move {
                            let _ = e.set_focus(true).await;
                        },
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("companies.kind")} }
                        select { class: "select", onchange: move |e| kind.set(OrgKind::from_slug(&e.value()).unwrap_or(OrgKind::Clinic)),
                            for k in OrgKind::ALL.iter().copied() {
                                option { key: "{k.slug()}", value: "{k.slug()}", selected: k == kind(), {t(k.key())} }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("companies.tin")} }
                        input { class: "input num", inputmode: "numeric", value: "{tin}", oninput: move |e| tin.set(e.value()) }
                        if let Some(n) = tin_dup.clone() {
                            div { class: "hint tone-warning row gap-4", Icon { name: "triangle-alert", size: 13 } {t("companies.tin_taken")} " {n}" }
                        }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("companies.address")} }
                    input { class: "input", value: "{address}", oninput: move |e| address.set(e.value()) }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("common.phone")} }
                        input { class: "input num", r#type: "tel", value: "{phone_v}", oninput: move |e| phone_v.set(e.value()) }
                    }
                    div { class: "field",
                        label { class: "label", "E-mail" }
                        input { class: "input", r#type: "email", value: "{email}", oninput: move |e| email.set(e.value()) }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("companies.credit_limit")} }
                        input { class: "input num", inputmode: "numeric", value: "{limit}", oninput: move |e| limit.set(e.value()) }
                        span { class: "hint", "{money_short(lim)}" }
                    }
                    div { class: "field",
                        label { class: "label", {t("companies.terms")} }
                        input { class: "input num", inputmode: "numeric", value: "{terms}", oninput: move |e| terms.set(e.value()) }
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
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("companies.subtitle", "klinikalar, korxonalar, sug‘urta va yetkazib beruvchilar", "клиники, компании, страховые и поставщики", "clinics, employers, insurers and suppliers"),
    ("companies.cards", "Kartochkalar", "Карточки", "Cards"),
    ("companies.table", "Jadval", "Таблица", "Table"),
    ("companies.receivable", "Debitorlik qarzi", "Дебиторская задолженность", "Receivable"),
    ("companies.near_limit_n", "{n} tasida limitning 80% dan ko‘pi ishlatilgan", "у {n} использовано больше 80% лимита", "{n} above 80% of their credit limit"),
    ("companies.pipeline", "Ochiq B2B bitimlar", "Открытые B2B-сделки", "Open B2B pipeline"),
    ("companies.at_risk", "Xavf ostidagi mijozlar", "Клиенты в зоне риска", "Accounts at risk"),
    ("companies.health_below", "salomatlik 60 dan past", "здоровье ниже 60", "health below 60"),
    ("companies.won_year", "Shu yil yutilgan", "Выиграно в этом году", "Won this year"),
    ("companies.b2b", "tashkilotlar bilan bitimlar", "сделки с организациями", "deals with organisations"),
    ("companies.search", "Nomi, STIR yoki tuman", "Название, ИНН или район", "Name, TIN or district"),
    ("companies.no_results_text", "Boshqa nom yoki turni tanlab ko‘ring.", "Попробуйте другое название или тип.", "Try another name or type."),
    ("companies.kind", "Turi", "Тип", "Type"),
    ("companies.contacts", "Kontaktlar", "Контакты", "Contacts"),
    ("companies.open_deals", "Ochiq bitimlar", "Открытые сделки", "Open deals"),
    ("companies.of_limit", "{limit} limitdan", "из лимита {limit}", "of {limit} limit"),
    ("companies.no_limit", "Kredit limiti yo‘q", "Без кредитного лимита", "No credit limit"),
    ("companies.over_limit", "Limitdan oshgan", "Лимит превышен", "Over the limit"),
    ("companies.near_limit", "Limitga yaqin", "Близко к лимиту", "Near the limit"),
    ("companies.health", "Mijoz salomatligi", "Здоровье клиента", "Account health"),
    ("companies.health_good", "Barqaror", "Стабильный", "Healthy"),
    ("companies.health_mid", "E’tibor kerak", "Нужно внимание", "Needs attention"),
    ("companies.health_bad", "Xavf ostida", "Под угрозой", "At risk"),
    ("companies.health_hint", "to‘lovlar, faollik va o‘sish", "оплаты, активность и рост", "payments, activity and growth"),
    ("companies.covered_short", "Xodimlar", "Сотрудники", "Employees"),
    ("companies.tin", "STIR", "ИНН", "TIN"),
    ("companies.log_call", "Qo‘ng‘iroqni yozish", "Записать звонок", "Log call"),
    ("companies.no_deals", "Bitimlar hali yo‘q", "Сделок пока нет", "No deals yet"),
    ("companies.no_quotes", "Takliflar va hisoblar yo‘q", "КП и счетов нет", "No quotes or invoices"),
    ("companies.activities", "Faoliyat", "Активности", "Activities"),
    ("companies.no_activities", "Hali faoliyat yo‘q", "Активностей пока нет", "No activities yet"),
    ("companies.people", "Kontakt shaxslar", "Контактные лица", "Contact persons"),
    ("companies.primary", "Asosiy", "Основной", "Primary"),
    ("companies.tg_opened", "Telegram suhbati ochildi", "Открыт чат в Telegram", "Telegram chat opened"),
    ("companies.covered", "Xizmat ko‘rsatiladigan xodimlar", "Сотрудники на обслуживании", "Employees covered"),
    ("companies.covered_hint", "Korporativ shartnoma bo‘yicha dorixonadan xarid qiladi", "Покупают в аптеке по корпоративному договору", "They buy at the pharmacy under the corporate agreement"),
    ("companies.no_covered", "Hali hech kim bog‘lanmagan", "Пока никто не привязан", "No employees linked yet"),
    ("companies.show_covered", "Mijozlar ro‘yxatida ko‘rish", "Показать в списке клиентов", "Show in customers"),
    ("companies.note_placeholder", "Tashkilot haqida izoh…", "Заметка об организации…", "A note about this company…"),
    ("companies.not_found", "Tashkilot topilmadi", "Организация не найдена", "Company not found"),
    ("companies.new", "Yangi tashkilot", "Новая организация", "New company"),
    ("companies.no_people", "Kontakt shaxslar hali qo‘shilmagan", "Контактных лиц пока нет", "No contact persons yet"),
    ("companies.edit", "Tashkilotni tahrirlash", "Изменить организацию", "Edit company"),
    ("companies.name", "Tashkilot nomi", "Название организации", "Company name"),
    ("companies.name_hint", "Masalan: Shifo Nur klinikasi", "Например: клиника «Шифо Нур»", "e.g. Shifo Nur clinic"),
    ("companies.address", "Manzil", "Адрес", "Address"),
    ("companies.credit_limit", "Kredit limiti, so‘m", "Кредитный лимит, сум", "Credit limit, so‘m"),
    ("companies.terms", "To‘lov muddati, kun", "Отсрочка платежа, дней", "Payment terms, days"),
    ("companies.tin_taken", "Bu STIR allaqachon bor:", "Этот ИНН уже есть:", "This TIN already belongs to"),
];
