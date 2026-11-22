//! Deals: each pipeline as a kanban (drag a card to another stage, or onto Won / Lost), a
//! sortable list and a forecast. The deal page has the stage track, product lines, a quote
//! built from them, activities, notes and the organisation's contact people.

use std::collections::HashMap;

use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime};
use crm::analytics;
use crm::fmt;
use crm::i18n::Entry;
use crm::model::*;
use dioxus::prelude::*;

use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

/// Drop targets below the board.
const WON_ZONE: Id = Id::MAX;
const LOST_ZONE: Id = Id::MAX - 1;

/// Preset lost reasons: stored in Uzbek like the rest of the data, shown in the interface language.
const REASONS: &[(&str, &str)] = &[
    ("deals.reason.price", "Narx yuqori"),
    ("deals.reason.competitor", "Raqobatchi arzonroq taklif berdi"),
    ("deals.reason.budget", "Byudjet qisqardi"),
    ("deals.reason.silent", "Javob bermay qo‘ydi"),
    ("deals.reason.timing", "Muddati to‘g‘ri kelmadi"),
    ("deals.reason.registration", "Dori ro‘yxatdan o‘tmagan"),
    ("deals.reason.tender", "Tenderda boshqa yetkazuvchi yutdi"),
];

fn reason_label(raw: &str) -> String {
    REASONS.iter().find(|(_, uz)| *uz == raw).map(|(k, _)| t(k)).unwrap_or_else(|| raw.to_string())
}

/// What a deal card and a list row show, looked up once.
#[derive(Clone, PartialEq)]
struct Card {
    id: Id,
    title: String,
    org: String,
    org_icon: &'static str,
    value: Money,
    owner: String,
    owner_hue: u16,
    owner_id: Id,
    days_in_stage: i64,
    idle: i64,
    rotting: bool,
    next_step: String,
    priority: Priority,
    stage_id: Id,
    stage_name: String,
    stage_hue: u16,
    stage_index: usize,
    status: DealStatus,
    probability: u8,
    expected_close: NaiveDate,
    closed_at: Option<NaiveDateTime>,
}

fn card_of(db: &crm::Db, d: &Deal, now: NaiveDateTime) -> Card {
    let stage = db.stage(d.stage_id);
    let (org, org_icon) = match d.company_id.and_then(|c| db.company(c)) {
        Some(c) => (c.name.clone(), crm::db::org_icon(c.kind)),
        None => (db.customer_name(d.customer_id), "user"),
    };
    let owner = db.staff_member(d.owner_id);
    Card {
        id: d.id,
        title: d.title.clone(),
        org,
        org_icon,
        value: db.deal_value(d),
        owner: owner.map(|s| s.name.clone()).unwrap_or_default(),
        owner_hue: owner.map(|s| s.hue).unwrap_or(24),
        owner_id: d.owner_id,
        days_in_stage: d.days_in_stage(now),
        idle: d.idle_days(now),
        rotting: db.is_rotting(d, now),
        next_step: d.next_step.clone(),
        priority: d.priority,
        stage_id: d.stage_id,
        stage_name: stage.map(|(_, s)| s.name.clone()).unwrap_or_default(),
        stage_hue: stage.map(|(_, s)| s.hue).unwrap_or(24),
        stage_index: stage.and_then(|(p, s)| p.stages.iter().position(|x| x.id == s.id)).unwrap_or(0),
        status: d.status,
        probability: db.deal_probability(d),
        expected_close: d.expected_close,
        closed_at: d.closed_at,
    }
}

/// "3 deals" with the right plural in every language.
fn deals_n(n: usize) -> String {
    fmt::plural(n as i64, lang(), "ta bitim|сделка|сделки|сделок|deal|deals")
}

fn status_tone(s: DealStatus) -> &'static str {
    match s {
        DealStatus::Open => "info",
        DealStatus::Won => "success",
        DealStatus::Lost => "danger",
    }
}

// ---------------------------------------------------------------- shared changes

fn move_to(id: Id, stage: Id) {
    let same = DB.peek().deal(id).map(|d| d.stage_id == stage && d.status == DealStatus::Open).unwrap_or(true);
    if same {
        return;
    }
    let mut name = String::new();
    mutate(|db| {
        name = db.stage(stage).map(|(_, s)| s.name.clone()).unwrap_or_default();
        db.move_deal(id, stage, now());
    });
    toast(format!("{} → {name}", t("deals.moved")), "arrow-right", "success");
}

fn win(id: Id) {
    let mut value = 0;
    mutate(|db| {
        db.win_deal(id, now());
        value = db.deal(id).map(|d| db.deal_value(d)).unwrap_or(0);
    });
    toast(format!("{} · {}", t("deals.won_toast"), money_short(value)), "trophy", "success");
}

fn reopen(id: Id) {
    mutate(|db| {
        if let Some(stage) = db.deal(id).map(|d| d.stage_id) {
            db.move_deal(id, stage, now());
        }
    });
    toast(t("deals.reopened"), "rotate-ccw", "");
}

// ---------------------------------------------------------------- the board

#[component]
pub fn Deals() -> Element {
    let l = lang();
    let first_pipe = DB.peek().pipelines.first().map(|p| p.id).unwrap_or(0);
    let mut pipe = use_signal(move || first_pipe);
    let mut view = use_signal(|| "kanban".to_string());
    let mut owner = use_signal(|| 0u32);
    let mut q = use_signal(String::new);
    let mut dragging = use_signal(|| None::<Id>);
    let mut over = use_signal(|| None::<Id>);
    let mut losing = use_signal(|| None::<Id>);
    let mut adding = use_signal(|| None::<Id>);
    let menu = use_signal(|| None::<Id>);
    let sort = use_signal(|| ("value".to_string(), true));
    let mut status_f = use_signal(|| "open".to_string());
    let mut cold = use_signal(|| false);

    let cards = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let pid = pipe();
        db.deals.iter().filter(|d| d.pipeline_id == pid).map(|d| card_of(&db, d, now)).collect::<Vec<Card>>()
    });
    let k = use_memo(move || analytics::kpis(&DB.read(), crate::state::now()));

    let now = now();
    let today = now.date();
    let m0 = analytics::month_start(today);
    let (pipes, stages) = {
        let db = DB.read();
        (
            db.pipelines.iter().map(|p| (p.id.to_string(), p.name.clone())).collect::<Vec<_>>(),
            db.pipeline(pipe()).map(|p| p.stages.clone()).unwrap_or_default(),
        )
    };
    let all = cards();

    // owners who have deals in this pipeline
    let mut owners: Vec<(Id, String)> = Vec::new();
    for c in &all {
        if !owners.iter().any(|o| o.0 == c.owner_id) {
            owners.push((c.owner_id, c.owner.clone()));
        }
    }
    owners.sort_by(|a, b| a.1.cmp(&b.1));

    let cold_n = all.iter().filter(|c| c.rotting).count();
    let ql = q().trim().to_lowercase();
    let shown: Vec<Card> = all
        .iter()
        .filter(|c| !cold() || c.rotting)
        .filter(|c| owner() == 0 || c.owner_id == owner())
        .filter(|c| ql.is_empty() || c.title.to_lowercase().contains(&ql) || c.org.to_lowercase().contains(&ql))
        .cloned()
        .collect();

    // summary strip for this pipeline (with the company-wide figure underneath)
    let open: Vec<&Card> = shown.iter().filter(|c| c.status == DealStatus::Open).collect();
    let open_value: Money = open.iter().map(|c| c.value).sum();
    let weighted: Money = open.iter().map(|c| c.value * c.probability as Money / 100).sum();
    let rotting = open.iter().filter(|c| c.rotting).count();
    let won_month: Vec<&Card> =
        shown.iter().filter(|c| c.status == DealStatus::Won && c.closed_at.map(|d| d.date() >= m0).unwrap_or(false)).collect();
    let won_value: Money = won_month.iter().map(|c| c.value).sum();
    let recent = |c: &&Card| c.closed_at.map(|d| (now - d).num_days() <= 90).unwrap_or(false);
    let won90 = shown.iter().filter(|c| c.status == DealStatus::Won).filter(recent).count();
    let lost90 = shown.iter().filter(|c| c.status == DealStatus::Lost).filter(recent).count();
    let win_rate = if won90 + lost90 == 0 { 0.0 } else { won90 as f64 / (won90 + lost90) as f64 * 100.0 };
    let kk = k();
    let foot_open = t("deals.foot_open").replace("{n}", &deals_n(open.len()));
    let foot_weighted = if rotting > 0 { t("deals.foot_rotting").replace("{n}", &deals_n(rotting)) } else { t("deals.foot_weighted") };
    let foot_won = t("deals.foot_won").replace("{n}", &deals_n(won_month.len())).replace("{v}", &money_short(kk.won_mtd));
    let foot_rate = t("deals.foot_rate").replace("{n}", &deals_n(won90 + lost90));
    let weighted_tone: &'static str = if rotting > 0 { "warning" } else { "accent" };

    let stage_opts: Vec<(Id, String, u16)> = stages.iter().map(|s| (s.id, s.name.clone(), s.hue)).collect();
    let pid = pipe();
    let is_drag = dragging().is_some();
    let won_over = over() == Some(WON_ZONE);
    let lost_over = over() == Some(LOST_ZONE);
    let lost90_text = t("deals.zone_lost_text").replace("{n}", &deals_n(lost90));
    let won_text = t("deals.zone_won_text").replace("{n}", &deals_n(won_month.len())).replace("{v}", &money_short(won_value));

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.deals"), subtitle: t("deals.sub"),
                button { class: "btn primary", onclick: move |_| adding.set(stages_first(pid)),
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("palette.new_deal")} }
                }
            }

            div { class: "row between wrap gap-12",
                div { style: "overflow-x: auto; max-width: 100%; scrollbar-width: none",
                    Segmented {
                        options: pipes,
                        value: pipe().to_string(),
                        onchange: move |v: String| {
                            pipe.set(v.parse().unwrap_or(0));
                            owner.set(0);
                        },
                    }
                }
                Segmented {
                    options: vec![
                        ("kanban".into(), t("deals.view_kanban")),
                        ("list".into(), t("deals.view_list")),
                        ("forecast".into(), t("deals.view_forecast")),
                    ],
                    value: view(),
                    onchange: move |v| view.set(v),
                }
            }

            div { class: "grid-4",
                Kpi { label: t("deals.open_value"), value: money_short(open_value), icon: "square-kanban", foot: foot_open }
                Kpi { label: t("deals.weighted"), value: money_short(weighted), icon: "scale", tone: weighted_tone, foot: foot_weighted }
                Kpi { label: t("deals.won_month"), value: money_short(won_value), icon: "trophy", tone: "success", foot: foot_won }
                Kpi { label: t("deals.win_rate"), value: fmt::pct(win_rate, l), icon: "target", tone: "info", foot: foot_rate }
            }

            if view() != "forecast" {
                div { class: "toolbar",
                    div { class: "search",
                        Icon { name: "search", size: 16 }
                        input { class: "input", value: "{q}", placeholder: t("deals.search"), oninput: move |e| q.set(e.value()) }
                    }
                    select { class: "select", style: "width: auto; min-width: 180px", onchange: move |e| owner.set(e.value().parse().unwrap_or(0)),
                        option { value: "0", selected: owner() == 0, {t("deals.all_owners")} }
                        for (id, name) in owners {
                            option { key: "{id}", value: "{id}", selected: id == owner(), "{name}" }
                        }
                    }
                    if cold_n > 0 {
                        button { class: if cold() { "chip on" } else { "chip" }, onclick: move |_| cold.toggle(),
                            Icon { name: "flame", size: 14 }
                            {t("deals.going_cold")}
                            span { class: "count", "{cold_n}" }
                        }
                    }
                    if view() == "list" {
                        div { class: "chips",
                            for (key, label) in [("open", t("deal_status.open")), ("won", t("deal_status.won")), ("lost", t("deal_status.lost")), ("all", t("common.all"))] {
                                {
                                    let n = shown.iter().filter(|c| key == "all" || c.status.slug() == key).count();
                                    rsx! {
                                        button { key: "{key}", class: if status_f() == key { "chip on" } else { "chip" }, onclick: move |_| status_f.set(key.to_string()),
                                            "{label}"
                                            span { class: "count", "{n}" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if view() == "kanban" {
                div { class: "kanban",
                    for s in stages.iter().cloned() {
                        {
                            let sid = s.id;
                            let col: Vec<Card> = shown.iter().filter(|c| c.status == DealStatus::Open && c.stage_id == sid).cloned().collect();
                            let n = col.len();
                            let total: Money = col.iter().map(|c| c.value).sum();
                            let weighted_col = total * s.probability as Money / 100;
                            let sub = format!("{}% · {}", s.probability, money_short(weighted_col));
                            let cls = if over() == Some(sid) { "kanban-col drop" } else { "kanban-col" };
                            rsx! {
                                div {
                                    key: "{sid}",
                                    class: cls,
                                    ondragover: move |e| {
                                        e.prevent_default();
                                        if over() != Some(sid) {
                                            over.set(Some(sid));
                                        }
                                    },
                                    ondrop: move |e| {
                                        e.prevent_default();
                                        if let Some(id) = dragging() {
                                            move_to(id, sid);
                                        }
                                        dragging.set(None);
                                        over.set(None);
                                    },
                                    div { class: "kanban-head",
                                        span { style: "width: 9px; height: 9px; border-radius: 99px; background: hsl({s.hue} 55% 52%); flex: 0 0 9px" }
                                        span { class: "strong small truncate", "{s.name}" }
                                        span { class: "badge sm", "{n}" }
                                        span { class: "total num", "{money_short(total)}" }
                                    }
                                    div { class: "xs subtle", style: "padding: 0 6px; margin-top: -6px", "{sub}" }
                                    for c in col {
                                        DealCard { key: "{c.id}", card: c, dragging, over, menu, losing, stages: stage_opts.clone() }
                                    }
                                    button { class: "btn ghost sm", style: "justify-content: flex-start; color: var(--c-subtle)", onclick: move |_| adding.set(Some(sid)),
                                        Icon { name: "plus", size: 14 }
                                        {t("deals.add_here")}
                                    }
                                }
                            }
                        }
                    }
                }
                div { class: "grid-2 hide-mobile",
                    div {
                        style: if won_over { "border: 2px dashed var(--c-success); background: var(--c-success-soft); border-radius: 14px; padding: 14px 18px; transition: all .12s" } else if is_drag { "border: 2px dashed color-mix(in srgb, var(--c-success) 55%, transparent); background: color-mix(in srgb, var(--c-success-soft) 60%, transparent); border-radius: 14px; padding: 14px 18px; transition: all .12s" } else { "border: 2px dashed var(--c-border-strong); border-radius: 14px; padding: 14px 18px; transition: all .12s" },
                        ondragover: move |e| {
                            e.prevent_default();
                            if over() != Some(WON_ZONE) {
                                over.set(Some(WON_ZONE));
                            }
                        },
                        ondrop: move |e| {
                            e.prevent_default();
                            if let Some(id) = dragging() {
                                win(id);
                            }
                            dragging.set(None);
                            over.set(None);
                        },
                        div { class: "row gap-12",
                            span { class: "ic success", Icon { name: "trophy", size: 17 } }
                            div { class: "grow",
                                div { class: "strong tone-success", {t("deals.zone_won")} }
                                div { class: "xs muted", "{won_text}" }
                            }
                        }
                    }
                    div {
                        style: if lost_over { "border: 2px dashed var(--c-danger); background: var(--c-danger-soft); border-radius: 14px; padding: 14px 18px; transition: all .12s" } else if is_drag { "border: 2px dashed color-mix(in srgb, var(--c-danger) 55%, transparent); background: color-mix(in srgb, var(--c-danger-soft) 60%, transparent); border-radius: 14px; padding: 14px 18px; transition: all .12s" } else { "border: 2px dashed var(--c-border-strong); border-radius: 14px; padding: 14px 18px; transition: all .12s" },
                        ondragover: move |e| {
                            e.prevent_default();
                            if over() != Some(LOST_ZONE) {
                                over.set(Some(LOST_ZONE));
                            }
                        },
                        ondrop: move |e| {
                            e.prevent_default();
                            if let Some(id) = dragging() {
                                losing.set(Some(id));
                            }
                            dragging.set(None);
                            over.set(None);
                        },
                        div { class: "row gap-12",
                            span { class: "ic danger", Icon { name: "circle-x", size: 17 } }
                            div { class: "grow",
                                div { class: "strong tone-danger", {t("deals.zone_lost")} }
                                div { class: "xs muted", "{lost90_text}" }
                            }
                        }
                    }
                }
            } else if view() == "list" {
                DealTable { cards: shown.iter().filter(|c| status_f() == "all" || c.status.slug() == status_f()).cloned().collect::<Vec<Card>>(), sort }
            } else {
                Forecast { pipeline: pid }
            }
        }

        if let Some(id) = losing() {
            LostModal { id, onclose: move |_| losing.set(None) }
        }
        if let Some(stage) = adding() {
            QuickDeal { stage, pipeline: pid, onclose: move |_| adding.set(None) }
        }
    }
}

fn stages_first(pipeline: Id) -> Option<Id> {
    DB.peek().pipeline(pipeline).and_then(|p| p.stages.first()).map(|s| s.id)
}

#[component]
fn DealCard(
    card: Card,
    dragging: Signal<Option<Id>>,
    over: Signal<Option<Id>>,
    menu: Signal<Option<Id>>,
    losing: Signal<Option<Id>>,
    stages: Vec<(Id, String, u16)>,
) -> Element {
    let id = card.id;
    let mut dragging = dragging;
    let mut over = over;
    let mut menu = menu;
    let mut losing = losing;
    let mut cls = String::from("kanban-card");
    if card.rotting {
        cls.push_str(" rotting");
    }
    if dragging() == Some(id) {
        cls.push_str(" dragging");
    }
    let open_menu = menu() == Some(id);
    let idle_text = t("deals.idle").replace("{n}", &fmt::days(card.idle, lang()));
    let in_stage = t("deals.in_stage").replace("{n}", &card.days_in_stage.to_string());
    let close = fmt::date(card.expected_close, today(), lang());
    let flag: Option<(&'static str, String)> = match card.priority {
        Priority::Urgent => Some(("tone-danger", t(card.priority.key()))),
        Priority::High => Some(("tone-warning", t(card.priority.key()))),
        _ => None,
    };
    let current = card.stage_id;
    rsx! {
        div {
            class: "{cls}",
            draggable: "true",
            ondragstart: move |_| {
                menu.set(None);
                dragging.set(Some(id));
            },
            ondragend: move |_| {
                dragging.set(None);
                over.set(None);
            },
            onclick: move |_| go(&format!("/deals/{id}")),
            div { class: "row top between gap-8",
                span { class: "strong small clamp-2", "{card.title}" }
                button {
                    class: "icon-btn sm",
                    style: "margin: -5px -7px 0 0; width: 26px; height: 26px",
                    onclick: move |e| {
                        e.stop_propagation();
                        menu.set(if menu() == Some(id) { None } else { Some(id) });
                    },
                    Icon { name: "ellipsis", size: 15 }
                }
            }
            div { class: "row gap-4 xs muted", style: "margin-top: -4px",
                Icon { name: card.org_icon, size: 12 }
                span { class: "truncate", "{card.org}" }
            }
            div { class: "row between",
                span { class: "strong num", "{money_short(card.value)}" }
                div { class: "row gap-4",
                    if let Some((tone, label)) = flag {
                        span { class: "{tone}", title: "{label}", Icon { name: "flag", size: 14 } }
                    }
                    Avatar { name: card.owner.clone(), hue: card.owner_hue, size: "xs" }
                }
            }
            if card.rotting {
                div { Badge { text: idle_text, tone: "warning", icon: "flame" } }
            }
            if !card.next_step.is_empty() {
                div { class: "row gap-4 xs muted", style: "align-items: flex-start",
                    span { style: "margin-top: 1px", Icon { name: "arrow-right", size: 12 } }
                    span { class: "clamp-2", "{card.next_step}" }
                }
            }
            div { class: "row between xs subtle",
                span { class: "row gap-4", Icon { name: "hourglass", size: 11 } "{in_stage}" }
                span { class: "row gap-4", Icon { name: "calendar", size: 11 } "{close}" }
            }
            if open_menu {
                div {
                    class: "stack gap-8",
                    style: "padding-top: 10px; border-top: 1px solid var(--c-border); cursor: default",
                    onclick: move |e| e.stop_propagation(),
                    select {
                        class: "select sm",
                        onchange: move |e| {
                            let v = e.value();
                            menu.set(None);
                            match v.as_str() {
                                "won" => win(id),
                                "lost" => losing.set(Some(id)),
                                _ => {
                                    if let Ok(sid) = v.parse::<Id>() {
                                        move_to(id, sid);
                                    }
                                }
                            }
                        },
                        option { value: "", selected: true, disabled: true, {t("deals.move_to")} }
                        for (sid, name, _) in stages {
                            option { key: "{sid}", value: "{sid}", disabled: sid == current, "{name}" }
                        }
                        option { value: "won", {t("deals.mark_won")} }
                        option { value: "lost", {t("deals.mark_lost")} }
                    }
                    div { class: "row gap-4",
                        button { class: "btn sm success", style: "flex: 1; color: var(--c-on-primary)", onclick: move |_| { menu.set(None); win(id); }, Icon { name: "trophy", size: 13 } {t("deal_status.won")} }
                        button { class: "btn sm danger", style: "flex: 1", onclick: move |_| { menu.set(None); losing.set(Some(id)); }, Icon { name: "circle-x", size: 13 } {t("deal_status.lost")} }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- list

#[component]
fn DealTable(cards: Vec<Card>, sort: Signal<(String, bool)>) -> Element {
    let l = lang();
    let today = today();
    let mut sort = sort;
    let (key, desc) = sort();
    let mut rows = cards.clone();
    rows.sort_by(|a, b| {
        let o = match key.as_str() {
            "title" => a.title.to_lowercase().cmp(&b.title.to_lowercase()),
            "stage" => a.stage_index.cmp(&b.stage_index),
            "prob" => a.probability.cmp(&b.probability),
            "close" => a.expected_close.cmp(&b.expected_close),
            "idle" => a.idle.cmp(&b.idle),
            "owner" => a.owner.cmp(&b.owner),
            _ => a.value.cmp(&b.value),
        };
        if desc {
            o.reverse()
        } else {
            o
        }
    });
    let total: Money = rows.iter().map(|c| c.value).sum();
    let n = rows.len();
    let headers: Vec<(&'static str, String, &'static str)> = vec![
        ("title", t("common.deal"), ""),
        ("stage", t("deals.stage"), "m-hide"),
        ("value", t("common.value"), "num"),
        ("prob", t("deals.probability"), "num m-hide"),
        ("owner", t("common.owner"), "m-hide"),
        ("close", t("deals.expected_close"), "m-hide"),
        ("idle", t("deals.activity"), "m-hide"),
    ];
    let shown: Vec<Card> = rows.iter().take(80).cloned().collect();
    rsx! {
        div { class: "card",
            if rows.is_empty() {
                Empty { icon: "square-kanban", title: t("common.no_results"), text: t("deals.no_results_text") }
            } else {
                div { class: "table-wrap",
                    table { class: "table responsive",
                        thead {
                            tr {
                                for (k, label, cls) in headers {
                                    {
                                        let on = k == key;
                                        let arrow: &'static str = if desc { "arrow-down" } else { "arrow-up" };
                                        rsx! {
                                            th {
                                                key: "{k}",
                                                class: "sortable {cls}",
                                                onclick: move |_| {
                                                    let (cur, d) = sort();
                                                    sort.set((k.to_string(), if cur == k { !d } else { k != "title" && k != "owner" && k != "close" }));
                                                },
                                                span { class: "row gap-4", style: if cls.contains("num") { "justify-content: flex-end" } else { "" },
                                                    "{label}"
                                                    if on { Icon { name: arrow, size: 12 } }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        tbody {
                            for c in shown {
                                {
                                    let id = c.id;
                                    let close = fmt::date(c.expected_close, today, l);
                                    let close_cls = if c.status == DealStatus::Open && c.expected_close < today { "small tone-danger nowrap" } else { "small muted nowrap" };
                                    let weighted = c.value * c.probability as Money / 100;
                                    let status_text = t(c.status.key());
                                    let tone = status_tone(c.status);
                                    let idle_text = if c.status == DealStatus::Open { t("deals.idle").replace("{n}", &fmt::days(c.idle, l)) } else { status_text.clone() };
                                    let idle_cls = if c.rotting { "badge warning sm" } else if c.status == DealStatus::Open { "badge sm" } else { "badge sm" };
                                    rsx! {
                                        tr { key: "{id}", class: "click", onclick: move |_| go(&format!("/deals/{id}")),
                                            td {
                                                div { class: "strong small", "{c.title}" }
                                                div { class: "xs muted row gap-4", Icon { name: c.org_icon, size: 11 } span { class: "truncate", "{c.org}" } }
                                            }
                                            td { class: "m-hide",
                                                span { class: "row gap-8 small nowrap",
                                                    span { style: "width: 8px; height: 8px; border-radius: 99px; background: hsl({c.stage_hue} 55% 52%); flex: 0 0 8px" }
                                                    "{c.stage_name}"
                                                }
                                            }
                                            td { class: "num",
                                                div { class: "strong nowrap", "{money_short(c.value)}" }
                                                div { class: "xs subtle nowrap hide-mobile", "≈ {money_short(weighted)}" }
                                                div { class: "only-mobile", Badge { text: status_text.clone(), tone } }
                                            }
                                            td { class: "num m-hide", "{c.probability}%" }
                                            td { class: "m-hide",
                                                div { class: "row gap-8",
                                                    Avatar { name: c.owner.clone(), hue: c.owner_hue, size: "xs" }
                                                    span { class: "small truncate", "{c.owner}" }
                                                }
                                            }
                                            td { class: "m-hide", span { class: close_cls, "{close}" } }
                                            td { class: "m-hide",
                                                if c.status == DealStatus::Open {
                                                    span { class: idle_cls, "{idle_text}" }
                                                } else {
                                                    Badge { text: status_text, tone, dot: true }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                div { class: "card-foot",
                    span { class: "small muted", {deals_n(n)} }
                    span { class: "strong num", "{money(total)}" }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- forecast

fn forecast_for(db: &crm::Db, pipeline: Id, today: NaiveDate, months: i32) -> Vec<(NaiveDate, Money, Money)> {
    let m0 = analytics::month_start(today);
    (0..months)
        .map(|i| {
            let m = analytics::add_months(m0, i);
            let next = analytics::add_months(m0, i + 1);
            let (mut w, mut best) = (0, 0);
            for d in db.deals.iter().filter(|d| d.status == DealStatus::Open && d.pipeline_id == pipeline) {
                let close = d.expected_close.max(m0);
                if close >= m && close < next {
                    let v = db.deal_value(d);
                    w += v * db.deal_probability(d) as Money / 100;
                    best += v;
                }
            }
            (m, w, best)
        })
        .collect()
}

#[component]
fn Forecast(pipeline: Id) -> Element {
    let l = lang();
    let today = today();
    let data = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let today = now.date();
        let fc = forecast_for(&db, pipeline, today, 4);
        let funnel = analytics::funnel(&db, pipeline);
        let deals: Vec<&Deal> = db.deals.iter().filter(|d| d.pipeline_id == pipeline).collect();
        let won: Vec<&Deal> = deals.iter().copied().filter(|d| d.status == DealStatus::Won).collect();
        let is_recent = |d: &Deal| d.closed_at.map(|c| (now - c).num_days() <= 90).unwrap_or(false);
        let won90 = deals.iter().filter(|d| d.status == DealStatus::Won && is_recent(d)).count();
        let lost90 = deals.iter().filter(|d| d.status == DealStatus::Lost && is_recent(d)).count();
        let win_rate = if won90 + lost90 == 0 { 0.0 } else { won90 as f64 / (won90 + lost90) as f64 * 100.0 };
        let avg_deal = if won.is_empty() { 0 } else { won.iter().map(|d| db.deal_value(d)).sum::<Money>() / won.len() as Money };
        let cycle = if won.is_empty() {
            0
        } else {
            won.iter().map(|d| d.closed_at.map(|c| (c - d.created).num_days()).unwrap_or(0)).sum::<i64>() / won.len() as i64
        };
        let mut reasons: HashMap<String, u32> = HashMap::new();
        for d in deals.iter().filter(|d| d.status == DealStatus::Lost) {
            *reasons.entry(d.lost_reason.clone().unwrap_or_else(|| "—".into())).or_default() += 1;
        }
        let mut reasons: Vec<(String, u32)> = reasons.into_iter().collect();
        reasons.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        (fc, funnel, win_rate, avg_deal, cycle, won.len(), reasons)
    });
    let (fc, funnel, win_rate, avg_deal, cycle, won_n, reasons) = data();
    let fc_max = fc.iter().map(|x| x.2).max().unwrap_or(1).max(1);
    let total_w: Money = fc.iter().map(|x| x.1).sum();
    let total_best: Money = fc.iter().map(|x| x.2).sum();
    let funnel_rows: Vec<(String, u32, String, u16)> = funnel.iter().map(|s| (s.name.clone(), s.count, money_short(s.value), s.hue)).collect();
    let reason_items: Vec<(String, f64, String)> = reasons.iter().map(|(r, n)| (reason_label(r), *n as f64, n.to_string())).collect();
    let cycle_text = fmt::days(cycle, l);
    let _ = today;
    rsx! {
        div { class: "grid-main",
            div { class: "card",
                div { class: "card-head",
                    div {
                        div { class: "card-title", Icon { name: "chart-no-axes-combined", size: 16, class: "tone-accent" } {t("deals.forecast_title")} }
                        div { class: "xs muted", style: "margin-top: 2px", {t("deals.forecast_hint")} }
                    }
                }
                div { class: "card-body stack gap-16",
                    for (m, w, best) in fc.iter().cloned() {
                        {
                            let label = format!("{} {}", fmt::month_name(m.month(), l), m.year());
                            let outer = best as f64 / fc_max as f64 * 100.0;
                            let inner = if best > 0 { w as f64 / best as f64 * 100.0 } else { 0.0 };
                            rsx! {
                                div { key: "{m}", class: "stack gap-8",
                                    div { class: "row between small",
                                        span { class: "strong", "{label}" }
                                        span { class: "num",
                                            b { "{money_short(w)}" }
                                            span { class: "muted", " / {money_short(best)}" }
                                        }
                                    }
                                    div { style: "height: 14px; border-radius: 99px; background: var(--c-surface-2)",
                                        div { style: "height: 100%; width: {outer:.1}%; min-width: 4px; border-radius: 99px; background: color-mix(in srgb, var(--c-chart-1) 26%, var(--c-surface-3)); overflow: hidden; transition: width .5s var(--ease)",
                                            div { style: "height: 100%; width: {inner:.1}%; border-radius: 99px; background: var(--c-chart-1)" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "row between wrap gap-12", style: "padding-top: 6px; border-top: 1px dashed var(--c-border)",
                        div { class: "legend",
                            span { span { class: "sw", style: "background: var(--c-chart-1)" } {t("deals.weighted")} }
                            span { span { class: "sw", style: "background: color-mix(in srgb, var(--c-chart-1) 26%, var(--c-surface-3))" } {t("deals.best_case")} }
                        }
                        div { class: "row gap-16 small",
                            span { class: "muted", {t("common.total")} ": " b { class: "num", "{money_short(total_w)}" } }
                            span { class: "muted", {t("deals.best_case")} ": " b { class: "num", "{money_short(total_best)}" } }
                        }
                    }
                }
            }
            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "gauge", size: 16, class: "tone-info" } {t("deals.health")} }
                }
                div { class: "card-body",
                    div { class: "grid-2", style: "gap: 10px",
                        StatTile { label: t("deals.win_rate"), value: fmt::pct(win_rate, l), icon: "target", tone: "info" }
                        StatTile { label: t("deals.avg_deal"), value: money_short(avg_deal), icon: "coins", tone: "accent" }
                        StatTile { label: t("deals.avg_cycle"), value: cycle_text, icon: "timer", tone: "warning" }
                        StatTile { label: t("deals.won_total"), value: won_n.to_string(), icon: "trophy", tone: "success" }
                    }
                }
            }
        }
        div { class: "grid-2",
            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "funnel", size: 16, class: "subtle" } {t("deals.funnel")} }
                }
                div { class: "card-body",
                    if funnel_rows.iter().all(|r| r.1 == 0) {
                        Empty { icon: "funnel", title: t("deals.funnel_empty") }
                    } else {
                        Funnel { stages: funnel_rows }
                    }
                }
            }
            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "circle-x", size: 16, class: "tone-danger" } {t("deals.lost_reasons")} }
                }
                div { class: "card-body",
                    if reason_items.is_empty() {
                        Empty { icon: "smile", title: t("deals.no_lost") }
                    } else {
                        HBars { items: reason_items, color: "var(--c-danger)" }
                    }
                }
            }
        }
    }
}

#[component]
fn StatTile(#[props(into)] label: String, #[props(into)] value: String, icon: &'static str, tone: &'static str) -> Element {
    rsx! {
        div { style: "padding: 12px; border-radius: 12px; background: var(--c-surface-2); display: flex; flex-direction: column; gap: 6px; min-width: 0",
            span { class: "row gap-8 xs muted", span { class: "ic {tone} sm", style: "width: 24px; height: 24px; border-radius: 7px", Icon { name: icon, size: 13 } } span { class: "truncate", "{label}" } }
            span { class: "num", style: "font-size: 19px; font-weight: 700; letter-spacing: -0.01em", "{value}" }
        }
    }
}

// ---------------------------------------------------------------- modals

#[component]
fn LostModal(id: Id, onclose: EventHandler<()>) -> Element {
    let mut reason = use_signal(|| REASONS[0].1.to_string());
    let mut other = use_signal(String::new);
    let title = DB.read().deal(id).map(|d| d.title.clone()).unwrap_or_default();
    let custom = reason().is_empty();
    let valid = !custom || !other().trim().is_empty();
    let save = move |_| {
        let r = if reason().is_empty() { other().trim().to_string() } else { reason() };
        if r.is_empty() {
            return;
        }
        mutate(|db| db.lose_deal(id, r.clone(), now()));
        toast(t("deals.lost_toast"), "circle-x", "");
        onclose.call(());
    };
    rsx! {
        Modal { title: t("deals.lost_title"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "small muted", "{title}" }
                div { class: "stack gap-8",
                    for (key, uz) in REASONS.iter().copied() {
                        label { key: "{key}", class: "check", style: "padding: 9px 12px; border: 1px solid var(--c-border); border-radius: 10px",
                            input { r#type: "radio", name: "lost-reason", checked: reason() == uz, onchange: move |_| reason.set(uz.to_string()) }
                            {t(key)}
                        }
                    }
                    label { class: "check", style: "padding: 9px 12px; border: 1px solid var(--c-border); border-radius: 10px",
                        input { r#type: "radio", name: "lost-reason", checked: custom, onchange: move |_| reason.set(String::new()) }
                        {t("deals.reason.other")}
                    }
                    if custom {
                        textarea {
                            class: "textarea",
                            placeholder: t("deals.reason.other_hint"),
                            value: "{other}",
                            oninput: move |e| other.set(e.value()),
                            onmounted: move |e| async move {
                                let _ = e.set_focus(true).await;
                            },
                        }
                    }
                }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn danger solid", disabled: !valid, onclick: save, Icon { name: "circle-x", size: 16 } {t("deals.mark_lost")} }
            }
        }
    }
}

#[component]
fn QuickDeal(stage: Id, pipeline: Id, onclose: EventHandler<()>) -> Element {
    let mut title = use_signal(String::new);
    let mut value = use_signal(String::new);
    let mut company = use_signal(|| 0u32);
    let mut close = use_signal(|| (today() + Duration::days(30)).format("%Y-%m-%d").to_string());
    let (companies, stage_name, pipe_name) = {
        let db = DB.read();
        (
            db.companies.iter().filter(|c| c.kind != OrgKind::Distributor).map(|c| (c.id, c.name.clone())).collect::<Vec<_>>(),
            db.stage(stage).map(|(_, s)| s.name.clone()).unwrap_or_default(),
            db.pipeline(pipeline).map(|p| p.name.clone()).unwrap_or_default(),
        )
    };
    let v: Money = value().chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0);
    let valid = !title().trim().is_empty() && v > 0;
    let hint = format!("{pipe_name} → {stage_name}");
    let save = move |_| {
        if !valid {
            return;
        }
        let now = now();
        let close_date = NaiveDate::parse_from_str(&close(), "%Y-%m-%d").unwrap_or(now.date() + Duration::days(30));
        mutate(|db| {
            let id = db.new_id();
            let me = db.settings.me;
            db.deals.push(Deal {
                id,
                title: title().trim().to_string(),
                pipeline_id: pipeline,
                stage_id: stage,
                company_id: if company() == 0 { None } else { Some(company()) },
                customer_id: None,
                value: v,
                owner_id: me,
                created: now,
                stage_since: now,
                last_activity: now,
                expected_close: close_date,
                status: DealStatus::Open,
                lost_reason: None,
                lines: vec![],
                source: Source::Call,
                tags: vec![],
                next_step: String::new(),
                closed_at: None,
                priority: if v >= 100_000_000 { Priority::High } else { Priority::Normal },
            });
            db.log(now, format!("+ {}", title().trim()), false);
        });
        toast(t("quick.deal_saved"), "square-kanban", "success");
        onclose.call(());
    };
    rsx! {
        Modal { title: t("palette.new_deal"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "callout", Icon { name: "square-kanban", size: 16 } span { "{hint}" } }
                div { class: "field",
                    label { class: "label", {t("quick.deal_title")} }
                    input {
                        class: "input",
                        value: "{title}",
                        placeholder: t("quick.deal_title_hint"),
                        oninput: move |e| title.set(e.value()),
                        onmounted: move |e| async move {
                            let _ = e.set_focus(true).await;
                        },
                    }
                }
                div { class: "field",
                    label { class: "label", {t("common.company")} }
                    select { class: "select", onchange: move |e| company.set(e.value().parse().unwrap_or(0)),
                        option { value: "0", "—" }
                        for (cid, name) in companies {
                            option { key: "{cid}", value: "{cid}", selected: cid == company(), "{name}" }
                        }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("common.value")} }
                        input { class: "input num", inputmode: "numeric", value: "{value}", placeholder: "25 000 000", oninput: move |e| value.set(e.value()) }
                        div { class: "hint", "{money(v)}" }
                    }
                    div { class: "field",
                        label { class: "label", {t("deals.expected_close")} }
                        input { class: "input", r#type: "date", value: "{close}", oninput: move |e| close.set(e.value()) }
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

// ---------------------------------------------------------------- deal page

#[component]
pub fn DealDetail(id: u32) -> Element {
    let mut losing = use_signal(|| false);
    let deal = DB.read().deal(id).cloned();
    let Some(d) = deal else {
        return rsx! {
            div { class: "page",
                div { class: "card",
                    Empty { icon: "square-kanban", title: t("deals.not_found"),
                        Link { to: Route::Deals {}, class: "btn primary", Icon { name: "arrow-left", size: 16 } {t("deals.back")} }
                    }
                }
            }
        };
    };
    let l = lang();
    let now = now();
    let today = now.date();
    let (pipe_name, stages, org, owner_name, owner_hue, value, prob, has_lines) = {
        let db = DB.read();
        let p = db.pipeline(d.pipeline_id);
        let org = match d.company_id.and_then(|c| db.company(c)) {
            Some(c) => (c.name.clone(), format!("/companies/{}", c.id), crm::db::org_icon(c.kind)),
            None => (db.customer_name(d.customer_id), d.customer_id.map(|c| format!("/contacts/{c}")).unwrap_or_default(), "user"),
        };
        let owner = db.staff_member(d.owner_id);
        (
            p.map(|p| p.name.clone()).unwrap_or_default(),
            p.map(|p| p.stages.clone()).unwrap_or_default(),
            org,
            owner.map(|s| s.name.clone()).unwrap_or_default(),
            owner.map(|s| s.hue).unwrap_or(24),
            db.deal_value(&d),
            db.deal_probability(&d),
            !d.lines.is_empty(),
        )
    };
    let (org_name, org_route, org_icon) = org;
    let cur_idx = stages.iter().position(|s| s.id == d.stage_id).unwrap_or(0);
    let weighted = value * prob as Money / 100;
    let days_open = (d.closed_at.unwrap_or(now) - d.created).num_days();
    let status_text = t(d.status.key());
    let tone = status_tone(d.status);
    let close_val = d.expected_close.format("%Y-%m-%d").to_string();
    let close_rel = fmt::due_in(d.expected_close, today, l);
    let close_cls = if d.status == DealStatus::Open && d.expected_close < today { "kpi-foot tone-danger" } else { "kpi-foot" };
    let created = fmt::date(d.created.date(), today, l);
    let is_open = d.status == DealStatus::Open;
    let rotting = DB.read().is_rotting(&d, now);
    let idle_text = t("deals.idle").replace("{n}", &fmt::days(d.idle_days(now), l));
    let lost_reason = d.lost_reason.as_deref().map(reason_label);
    let closed_text = d.closed_at.map(|c| fmt::date(c.date(), today, l)).unwrap_or_default();
    let can_quote = has_lines;
    let quote_title = if can_quote { t("deals.create_quote") } else { t("deals.quote_needs_lines") };
    let subtitle = format!("{pipe_name} · {}", t("deals.created_on").replace("{d}", &created));
    let stage_label = stages.get(cur_idx).map(|s| s.name.clone()).unwrap_or_default();

    let create_quote = move |_| {
        let mut new_id = 0;
        mutate(|db| {
            let Some(d) = db.deal(id).cloned() else { return };
            if d.lines.is_empty() {
                return;
            }
            let now = crate::state::now();
            let n = db.quotes.iter().filter_map(|q| q.number.rsplit('-').next().and_then(|x| x.parse::<u32>().ok())).max().unwrap_or(130) + 1;
            let qid = db.new_id();
            new_id = qid;
            let me = db.settings.me;
            let number = format!("TK-{}-{:04}", now.date().year(), n);
            db.quotes.insert(
                0,
                Quote {
                    id: qid,
                    number: number.clone(),
                    company_id: d.company_id.unwrap_or(0),
                    deal_id: Some(d.id),
                    lines: d.lines.clone(),
                    status: QuoteStatus::Draft,
                    issued: now.date(),
                    valid_until: now.date() + Duration::days(30),
                    vat_pct: 12,
                    notes: "To‘lov: bank o‘tkazmasi, 30 kun ichida. Yetkazish bepul.".into(),
                    owner_id: me,
                    paid_on: None,
                },
            );
            if let Some(x) = db.deal_mut(id) {
                x.last_activity = now;
            }
            db.log(now, format!("{number}: {}", d.title), false);
        });
        if new_id != 0 {
            toast(t("deals.quote_created"), "file-text", "success");
            go(&format!("/quotes/{new_id}"));
        }
    };

    rsx! {
        div { class: "page",
            div { class: "row between wrap gap-8",
                Link { to: Route::Deals {}, class: "btn ghost sm", Icon { name: "arrow-left", size: 15 } {t("deals.back")} }
                div { class: "row gap-8 small muted",
                    Icon { name: "square-kanban", size: 14 }
                    "{pipe_name}"
                }
            }
            PageHeader { title: d.title.clone(), subtitle,
                if is_open {
                    button { class: "btn danger", onclick: move |_| losing.set(true), Icon { name: "circle-x", size: 16 } span { class: "label-text", {t("deal_status.lost")} } }
                    button { class: "btn success keep", style: "color: var(--c-on-primary)", onclick: move |_| win(id), Icon { name: "trophy", size: 16 } span { class: "label-text", {t("deals.mark_won")} } }
                } else {
                    button { class: "btn", onclick: move |_| reopen(id), Icon { name: "rotate-ccw", size: 16 } span { class: "label-text", {t("deals.reopen")} } }
                }
                button { class: "btn primary", disabled: !can_quote, title: "{quote_title}", onclick: create_quote,
                    Icon { name: "file-plus", size: 16 }
                    span { class: "label-text", {t("deals.create_quote")} }
                }
            }

            div { class: "card pad", style: "display: flex; flex-wrap: wrap; gap: 14px 28px; align-items: center",
                div { class: "stack gap-4",
                    span { class: "xs muted upper", {t("common.value")} }
                    span { class: "num", style: "font-size: 26px; font-weight: 750; letter-spacing: -0.02em", "{money(value)}" }
                }
                div { class: "stack gap-4",
                    span { class: "xs muted upper", {t("common.status")} }
                    div { class: "row gap-8",
                        Badge { text: status_text, tone, dot: true }
                        if rotting {
                            Badge { text: idle_text.clone(), tone: "warning", icon: "flame" }
                        }
                    }
                }
                div { class: "stack gap-4",
                    span { class: "xs muted upper", {t("common.company")} }
                    if org_route.is_empty() {
                        span { class: "row gap-8 strong", Icon { name: org_icon, size: 15 } "{org_name}" }
                    } else {
                        button { class: "row gap-8 strong", style: "border: 0; background: none; padding: 0; cursor: pointer; color: var(--c-accent-fg)", onclick: move |_| go(&org_route),
                            Icon { name: org_icon, size: 15 }
                            "{org_name}"
                        }
                    }
                }
                div { class: "stack gap-4",
                    span { class: "xs muted upper", {t("common.owner")} }
                    span { class: "row gap-8", Avatar { name: owner_name.clone(), hue: owner_hue, size: "xs" } span { class: "small strong", "{owner_name}" } }
                }
                if let Some(r) = lost_reason {
                    div { class: "callout danger", style: "flex: 1 1 260px",
                        Icon { name: "circle-x", size: 16 }
                        div { div { class: "strong", {t("deals.lost_because")} } div { "{r} · {closed_text}" } }
                    }
                }
                if d.status == DealStatus::Won {
                    div { class: "callout success", style: "flex: 1 1 260px",
                        Icon { name: "trophy", size: 16 }
                        div { div { class: "strong", {t("deals.won_banner")} } div { "{closed_text}" } }
                    }
                }
            }

            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "milestone", size: 16, class: "subtle" } {t("deals.stage")} ": {stage_label}" }
                    span { class: "xs muted hide-mobile", {t("deals.track_hint")} }
                }
                div { class: "card-body",
                    div { class: "stage-track",
                        for (i, s) in stages.iter().cloned().enumerate() {
                            {
                                let cls = if d.status == DealStatus::Won {
                                    "st done"
                                } else if s.id == d.stage_id {
                                    if is_open { "st current" } else { "st" }
                                } else if i < cur_idx {
                                    "st done"
                                } else {
                                    "st"
                                };
                                let sid = s.id;
                                let name_cls = if s.id == d.stage_id { "truncate" } else { "truncate hide-mobile" };
                                rsx! {
                                    div { key: "{sid}", class: cls, title: "{s.name} · {s.probability}%", onclick: move |_| move_to(id, sid),
                                        span { class: name_cls, "{s.name}" }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            div { class: "grid-4",
                Kpi { label: t("deals.probability"), value: format!("{prob}%"), icon: "percent", tone: "info", foot: stage_label.clone() }
                Kpi { label: t("deals.weighted"), value: money_short(weighted), icon: "scale", foot: t("deals.weighted_foot") }
                Kpi { label: t("deals.days_open"), value: fmt::days(days_open, l), icon: "hourglass", tone: "warning", foot: t("deals.created_on").replace("{d}", &created) }
                div { class: "card kpi",
                    div { class: "kpi-label",
                        span { class: "icon-wrap ic success", Icon { name: "calendar-check", size: 15 } }
                        span { class: "truncate", {t("deals.expected_close")} }
                    }
                    input {
                        class: "input sm num",
                        r#type: "date",
                        value: "{close_val}",
                        style: "font-size: 16px; font-weight: 650",
                        onchange: move |e| {
                            if let Ok(nd) = NaiveDate::parse_from_str(&e.value(), "%Y-%m-%d") {
                                mutate(|db| {
                                    if let Some(x) = db.deal_mut(id) {
                                        x.expected_close = nd;
                                    }
                                });
                                toast(t("common.saved"), "calendar-check", "success");
                            }
                        },
                    }
                    div { class: close_cls, "{close_rel}" }
                }
            }

            div { class: "grid-main",
                div { class: "stack gap-16",
                    LinesEditor { id }
                    DealActivities { id }
                    DealNotes { id }
                }
                div { class: "stack gap-16",
                    OrgCard { id }
                    DealInfo { id }
                    DealQuotes { id }
                }
            }
        }

        if losing() {
            LostModal { id, onclose: move |_| losing.set(false) }
        }
    }
}

#[component]
fn LinesEditor(id: Id) -> Element {
    let mut pick = use_signal(|| 0u32);
    let mut qty = use_signal(|| "10".to_string());
    let (lines, products, manual) = {
        let db = DB.read();
        let d = db.deal(id);
        let lines: Vec<(usize, LineItem, String, bool)> = d
            .map(|d| {
                d.lines
                    .iter()
                    .enumerate()
                    .map(|(i, li)| (i, li.clone(), db.product_name(Some(li.product_id)), db.product(li.product_id).map(|p| p.rx).unwrap_or(false)))
                    .collect()
            })
            .unwrap_or_default();
        let products: Vec<(Id, String, Money)> = db.products.iter().map(|p| (p.id, p.name.clone(), p.price)).collect();
        (lines, products, d.map(|d| d.value).unwrap_or(0))
    };
    let subtotal: Money = lines.iter().map(|x| x.1.total()).sum();
    let gross: Money = lines.iter().map(|x| x.1.price * x.1.qty as Money).sum();
    let discount = gross - subtotal;
    let price_pick = products.iter().find(|p| p.0 == pick()).map(|p| p.2).unwrap_or(0);
    let n: u32 = qty().trim().parse().unwrap_or(0);
    let can_add = pick() != 0 && n > 0;
    let add_preview = money(price_pick * n as Money);
    let add = move |_| {
        if !can_add {
            return;
        }
        let pid = pick();
        mutate(|db| {
            let price = db.product(pid).map(|p| p.price).unwrap_or(0);
            if let Some(d) = db.deal_mut(id) {
                if let Some(li) = d.lines.iter_mut().find(|l| l.product_id == pid) {
                    li.qty += n;
                } else {
                    d.lines.push(LineItem { product_id: pid, qty: n, price, discount_pct: 0 });
                }
                d.last_activity = now();
            }
        });
        pick.set(0);
        toast(t("deals.line_added"), "plus", "success");
    };
    let manual_text = t("deals.manual_value").replace("{v}", &money(manual));
    let manual_money = money(manual);
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "pill", size: 16, class: "tone-accent" } {t("deals.lines")} }
                if !lines.is_empty() {
                    span { class: "badge", "{lines.len()}" }
                }
            }
            if lines.is_empty() {
                div { class: "card-body stack gap-12",
                    div { class: "callout", Icon { name: "info", size: 16 } span { "{manual_text}" } }
                    div { class: "row gap-12 wrap",
                        span { class: "label", {t("deals.subtotal")} }
                        input {
                            class: "input sm num",
                            style: "width: 180px",
                            inputmode: "numeric",
                            value: "{manual}",
                            onchange: move |e| {
                                let v: Money = e.value().chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0);
                                if v > 0 {
                                    mutate(|db| {
                                        if let Some(d) = db.deal_mut(id) {
                                            d.value = v;
                                            d.last_activity = crate::state::now();
                                        }
                                    });
                                    toast(t("common.saved"), "check", "success");
                                }
                            },
                        }
                        span { class: "small muted num", "{manual_money}" }
                    }
                }
            } else {
                div { class: "list", style: "margin-top: 8px",
                    for (i, li, name, rx) in lines {
                        {
                            let price = money(li.price);
                            let total = money(li.total());
                            let q = li.qty.to_string();
                            let disc = li.discount_pct.to_string();
                            rsx! {
                                div { key: "{i}-{li.product_id}", class: "list-row", style: "flex-wrap: wrap; row-gap: 8px",
                                    div { class: "meta", style: "flex: 1 1 220px",
                                        div { class: "row gap-8",
                                            span { class: "title small", "{name}" }
                                            if rx { span { class: "badge sm info", "Rx" } }
                                        }
                                        span { class: "sub num", "{price}" }
                                    }
                                    div { class: "row gap-8",
                                        label { class: "stack gap-4",
                                            span { class: "xs subtle", {t("deals.qty")} }
                                            input {
                                                class: "input sm num",
                                                style: "width: 84px",
                                                r#type: "number",
                                                min: "1",
                                                value: "{q}",
                                                onchange: move |e| {
                                                    let v: u32 = e.value().trim().parse().unwrap_or(0);
                                                    if v > 0 {
                                                        update_line(id, i, move |li| li.qty = v);
                                                    }
                                                },
                                            }
                                        }
                                        label { class: "stack gap-4",
                                            span { class: "xs subtle", {t("deals.discount")} }
                                            input {
                                                class: "input sm num",
                                                style: "width: 70px",
                                                r#type: "number",
                                                min: "0",
                                                max: "100",
                                                value: "{disc}",
                                                onchange: move |e| {
                                                    let v: u8 = e.value().trim().parse::<u32>().unwrap_or(0).min(100) as u8;
                                                    update_line(id, i, move |li| li.discount_pct = v);
                                                },
                                            }
                                        }
                                        div { class: "stack gap-4", style: "width: 128px; align-items: flex-end",
                                            span { class: "xs subtle", {t("common.total")} }
                                            span { class: "strong num nowrap", style: "line-height: 32px", "{total}" }
                                        }
                                        button {
                                            class: "icon-btn sm",
                                            style: "align-self: flex-end",
                                            onclick: move |_| {
                                                mutate(|db| {
                                                    if let Some(d) = db.deal_mut(id) {
                                                        if i < d.lines.len() {
                                                            d.lines.remove(i);
                                                        }
                                                    }
                                                });
                                            },
                                            Icon { name: "trash-2", size: 15 }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                div { class: "card-body stack gap-4", style: "border-top: 1px solid var(--c-border)",
                    div { class: "stat-line small", span { class: "muted", {t("deals.gross")} } span { class: "num", "{money(gross)}" } }
                    if discount > 0 {
                        div { class: "stat-line small", span { class: "muted", {t("deals.discounts")} } span { class: "num tone-success", "−{money(discount)}" } }
                    }
                    div { class: "stat-line", span { class: "strong", {t("deals.subtotal")} } span { class: "num strong", style: "font-size: 17px", "{money(subtotal)}" } }
                }
            }
            div { class: "card-foot", style: "flex-wrap: wrap",
                select { class: "select sm", style: "flex: 1 1 240px; width: auto; min-width: 0", onchange: move |e| pick.set(e.value().parse().unwrap_or(0)),
                    option { value: "0", selected: pick() == 0, {t("deals.pick_product")} }
                    for (pid, name, p) in products {
                        option { key: "{pid}", value: "{pid}", selected: pid == pick(), "{name} · {money_short(p)}" }
                    }
                }
                input { class: "input sm num", style: "width: 84px", r#type: "number", min: "1", value: "{qty}", oninput: move |e| qty.set(e.value()) }
                button { class: "btn soft sm", disabled: !can_add, onclick: add, Icon { name: "plus", size: 14 } {t("common.add")} }
                if can_add {
                    span { class: "xs muted num", "{add_preview}" }
                }
            }
        }
    }
}

fn update_line(id: Id, idx: usize, f: impl FnOnce(&mut LineItem)) {
    mutate(|db| {
        if let Some(d) = db.deal_mut(id) {
            if let Some(li) = d.lines.get_mut(idx) {
                f(li);
            }
            d.last_activity = now();
        }
    });
}

#[component]
fn DealActivities(id: Id) -> Element {
    let l = lang();
    let now = now();
    let mut kind = use_signal(|| ActivityKind::Call);
    let mut title = use_signal(String::new);
    let mut due = use_signal(|| (crate::state::now() + Duration::days(1)).format("%Y-%m-%dT10:00").to_string());
    let items: Vec<(Activity, String, u16)> = {
        let db = DB.read();
        let mut v: Vec<&Activity> = db.activities.iter().filter(|a| a.deal_id == Some(id)).collect();
        v.sort_by(|a, b| a.done.cmp(&b.done).then_with(|| if a.done { b.due.cmp(&a.due) } else { a.due.cmp(&b.due) }));
        v.into_iter()
            .map(|a| {
                let s = db.staff_member(a.owner_id);
                (a.clone(), s.map(|s| s.name.clone()).unwrap_or_default(), s.map(|s| s.hue).unwrap_or(24))
            })
            .collect()
    };
    let open = items.iter().filter(|x| !x.0.done).count();
    let valid = !title().trim().is_empty() && NaiveDateTime::parse_from_str(&due(), "%Y-%m-%dT%H:%M").is_ok();
    let add = move |_| {
        let Ok(when) = NaiveDateTime::parse_from_str(&due(), "%Y-%m-%dT%H:%M") else { return };
        if title().trim().is_empty() {
            return;
        }
        mutate(|db| {
            let (company, customer) = db.deal(id).map(|d| (d.company_id, d.customer_id)).unwrap_or((None, None));
            let me = db.settings.me;
            db.add_activity(Activity {
                id: 0,
                kind: kind(),
                title: title().trim().to_string(),
                notes: String::new(),
                due: when,
                done: false,
                done_at: None,
                owner_id: me,
                customer_id: customer,
                company_id: company,
                deal_id: Some(id),
                ticket_id: None,
                priority: Priority::Normal,
                outcome: None,
                duration_min: 20,
                daybook_task: None,
            });
        });
        title.set(String::new());
        toast(t("quick.task_saved"), "square-check", "success");
    };
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "calendar-check", size: 16, class: "tone-info" } {t("deals.activities")} }
                if open > 0 {
                    span { class: "badge info", "{open}" }
                }
            }
            div { class: "list", style: "margin-top: 8px",
                if items.is_empty() {
                    Empty { icon: "calendar-check", title: t("deals.no_activities") }
                }
                for (a, owner, hue) in items {
                    {
                        let aid = a.id;
                        let icon = crm::db::activity_icon(a.kind);
                        let check_cls = if a.done { "check-circle on" } else { "check-circle" };
                        let when = fmt::datetime(a.done_at.unwrap_or(a.due), now, l);
                        let overdue = !a.done && a.due < now;
                        let when_cls = if overdue { "tone-danger strong" } else { "" };
                        let title_style = if a.done { "text-decoration: line-through; opacity: .6" } else { "" };
                        let kind_label = t(a.kind.key());
                        rsx! {
                            div { key: "{aid}", class: "list-row",
                                button { class: check_cls, onclick: move |_| mutate(|db| db.complete_activity(aid, crate::state::now())), Icon { name: "check", size: 13 } }
                                span { class: "ic muted sm", Icon { name: icon, size: 14 } }
                                div { class: "meta",
                                    span { class: "title small", style: title_style, "{a.title}" }
                                    span { class: "sub row gap-4 wrap",
                                        span { "{kind_label}" }
                                        span { "·" }
                                        span { class: when_cls, "{when}" }
                                        if let Some(o) = a.outcome.clone() {
                                            span { "·" }
                                            span { class: "truncate", "{o}" }
                                        }
                                    }
                                }
                                Avatar { name: owner.clone(), hue, size: "xs" }
                            }
                        }
                    }
                }
            }
            div { class: "card-foot", style: "flex-wrap: wrap",
                select { class: "select sm", style: "width: auto", onchange: move |e| kind.set(ActivityKind::from_slug(&e.value()).unwrap_or(ActivityKind::Call)),
                    for k in ActivityKind::ALL.iter().copied() {
                        option { key: "{k.slug()}", value: "{k.slug()}", selected: k == kind(), {t(k.key())} }
                    }
                }
                input { class: "input sm", style: "flex: 1 1 200px; width: auto; min-width: 0", value: "{title}", placeholder: t("deals.activity_hint"), oninput: move |e| title.set(e.value()) }
                input { class: "input sm", style: "width: auto", r#type: "datetime-local", value: "{due}", oninput: move |e| due.set(e.value()) }
                button { class: "btn soft sm", disabled: !valid, onclick: add, Icon { name: "plus", size: 14 } {t("common.add")} }
            }
        }
    }
}

#[component]
fn DealNotes(id: Id) -> Element {
    let l = lang();
    let now = now();
    let mut text = use_signal(String::new);
    let notes: Vec<(Note, String, u16)> = {
        let db = DB.read();
        let mut v: Vec<&Note> = db.notes.iter().filter(|n| n.deal_id == Some(id)).collect();
        v.sort_by(|a, b| b.pinned.cmp(&a.pinned).then(b.at.cmp(&a.at)));
        v.into_iter()
            .map(|n| {
                let s = n.author_id.and_then(|a| db.staff_member(a));
                (n.clone(), s.map(|s| s.name.clone()).unwrap_or_default(), s.map(|s| s.hue).unwrap_or(24))
            })
            .collect()
    };
    let valid = !text().trim().is_empty();
    let add = move |_| {
        let body = text().trim().to_string();
        if body.is_empty() {
            return;
        }
        mutate(|db| {
            let nid = db.new_id();
            let me = db.settings.me;
            let company = db.deal(id).and_then(|d| d.company_id);
            db.notes.insert(
                0,
                Note { id: nid, at: crate::state::now(), author_id: Some(me), text: body.clone(), customer_id: None, company_id: company, deal_id: Some(id), pinned: false, sensitive: false },
            );
            if let Some(d) = db.deal_mut(id) {
                d.last_activity = crate::state::now();
            }
        });
        text.set(String::new());
        toast(t("common.saved"), "sticky-note", "success");
    };
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "sticky-note", size: 16, class: "tone-warning" } {t("common.notes")} }
            }
            div { class: "card-body stack gap-12",
                div { class: "stack gap-8",
                    textarea { class: "textarea", style: "min-height: 70px", placeholder: t("deals.note_hint"), value: "{text}", oninput: move |e| text.set(e.value()) }
                    div { class: "row end",
                        button { class: "btn soft sm", disabled: !valid, onclick: add, Icon { name: "plus", size: 14 } {t("common.add_note")} }
                    }
                }
                for (n, author, hue) in notes {
                    {
                        let when = fmt::relative(n.at, now, l);
                        let nid = n.id;
                        let pin_cls = if n.pinned { "icon-btn sm tone-accent" } else { "icon-btn sm" };
                        rsx! {
                            div { key: "{nid}", class: "row top gap-12", style: "padding: 12px; border-radius: 12px; background: var(--c-surface-2)",
                                Avatar { name: author.clone(), hue, size: "sm" }
                                div { class: "grow",
                                    div { class: "row between",
                                        span { class: "small strong", "{author}" }
                                        span { class: "xs subtle", "{when}" }
                                    }
                                    p { class: "small", style: "margin-top: 3px; white-space: pre-wrap", "{n.text}" }
                                }
                                button {
                                    class: pin_cls,
                                    onclick: move |_| mutate(|db| if let Some(x) = db.notes.iter_mut().find(|x| x.id == nid) { x.pinned = !x.pinned }),
                                    Icon { name: "pin", size: 14 }
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
fn OrgCard(id: Id) -> Element {
    let (company, customer) = {
        let db = DB.read();
        let d = db.deal(id);
        (d.and_then(|d| d.company_id).and_then(|c| db.company(c)).cloned(), d.and_then(|d| d.customer_id).and_then(|c| db.customer(c)).cloned())
    };
    if let Some(c) = company {
        let cid = c.id;
        let kind = t(c.kind.key());
        let icon = crm::db::org_icon(c.kind);
        let terms = t("deals.terms").replace("{n}", &c.terms_days.to_string());
        let receivable = money_short(c.receivable);
        let limit = money_short(c.credit_limit);
        let health_tone = score_tone(c.health);
        return rsx! {
            div { class: "card",
                div { class: "card-head",
                    div { class: "card-title", Icon { name: "building-2", size: 16, class: "subtle" } {t("common.company")} }
                    Link { to: Route::CompanyDetail { id: cid }, class: "btn ghost sm", {t("common.see")} Icon { name: "arrow-right", size: 14 } }
                }
                div { class: "card-body stack gap-12",
                    div { class: "row gap-12",
                        IconTile { icon, tone: "accent" }
                        div { class: "grow",
                            div { class: "strong", "{c.name}" }
                            div { class: "xs muted", "{kind} · STIR {c.tin}" }
                        }
                        Badge { text: format!("{}", c.health), tone: health_tone, icon: "heart-pulse" }
                    }
                    div { class: "grid-3", style: "gap: 8px; grid-template-columns: repeat(3, minmax(0, 1fr))",
                        div { style: "padding: 8px 10px; border-radius: 10px; background: var(--c-surface-2)",
                            div { class: "xs muted", {t("deals.receivable")} }
                            div { class: "small strong num", "{receivable}" }
                        }
                        div { style: "padding: 8px 10px; border-radius: 10px; background: var(--c-surface-2)",
                            div { class: "xs muted", {t("deals.credit")} }
                            div { class: "small strong num", "{limit}" }
                        }
                        div { style: "padding: 8px 10px; border-radius: 10px; background: var(--c-surface-2)",
                            div { class: "xs muted", {t("deals.payment")} }
                            div { class: "small strong", "{terms}" }
                        }
                    }
                }
                div { class: "list",
                    for p in c.contacts.iter().cloned() {
                        {
                            let tel = phone(&p.phone);
                            let href = crm::fmt::tel_href(&p.phone);
                            rsx! {
                                div { key: "{p.name}", class: "list-row",
                                    Avatar { name: p.name.clone(), size: "sm" }
                                    div { class: "meta",
                                        div { class: "row gap-8",
                                            span { class: "title small truncate", "{p.name}" }
                                            if p.primary { span { class: "badge sm accent", {t("deals.primary")} } }
                                        }
                                        span { class: "sub truncate", "{p.position}" }
                                        span { class: "xs muted num", "{tel}" }
                                    }
                                    a { class: "icon-btn sm bordered", href: "{href}", title: "{tel}", Icon { name: "phone", size: 14 } }
                                    if let Some(tg) = p.telegram.clone() {
                                        span { class: "icon-btn sm bordered", title: "{tg}", Icon { name: "send", size: 14 } }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        };
    }
    if let Some(c) = customer {
        let cid = c.id;
        let tel = phone(&c.phone);
        let spent = money_short(c.total_spent);
        let orders = c.orders;
        return rsx! {
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
                    div { class: "row gap-16 small",
                        span { class: "muted", {t("deals.spent")} ": " b { class: "num", "{spent}" } }
                        span { class: "muted", {t("deals.orders")} ": " b { class: "num", "{orders}" } }
                    }
                }
            }
        };
    }
    rsx! {}
}

#[component]
fn DealInfo(id: Id) -> Element {
    let l = lang();
    let now = now();
    let today = now.date();
    let mut step = use_signal(move || DB.peek().deal(id).map(|d| d.next_step.clone()).unwrap_or_default());
    let Some(d) = DB.read().deal(id).cloned() else { return rsx! {} };
    let rows: Vec<(String, String)> = vec![
        (t("deals.source"), t(d.source.key())),
        (t("deals.in_stage_since"), fmt::date(d.stage_since.date(), today, l)),
        (t("deals.last_activity"), fmt::relative(d.last_activity, now, l)),
        (t("deals.priority"), t(d.priority.key())),
    ];
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "info", size: 16, class: "subtle" } {t("common.details")} }
            }
            div { class: "card-body stack gap-12",
                KeyValues { items: rows }
                div { class: "field",
                    label { class: "label", {t("deals.next_step")} }
                    input {
                        class: "input sm",
                        value: "{step}",
                        placeholder: t("deals.next_step_hint"),
                        oninput: move |e| step.set(e.value()),
                        onchange: move |e| {
                            let v = e.value();
                            mutate(|db| {
                                if let Some(x) = db.deal_mut(id) {
                                    x.next_step = v.trim().to_string();
                                }
                            });
                            toast(t("common.saved"), "check", "success");
                        },
                    }
                }
                div { class: "field",
                    label { class: "label", {t("deals.priority")} }
                    select {
                        class: "select sm",
                        onchange: move |e| {
                            if let Some(p) = Priority::from_slug(&e.value()) {
                                mutate(|db| {
                                    if let Some(x) = db.deal_mut(id) {
                                        x.priority = p;
                                    }
                                });
                            }
                        },
                        for p in Priority::ALL.iter().copied() {
                            option { key: "{p.slug()}", value: "{p.slug()}", selected: p == d.priority, {t(p.key())} }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn DealQuotes(id: Id) -> Element {
    let l = lang();
    let today = today();
    let quotes: Vec<Quote> = DB.read().quotes.iter().filter(|q| q.deal_id == Some(id)).cloned().collect();
    if quotes.is_empty() {
        return rsx! {};
    }
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "file-text", size: 16, class: "subtle" } {t("nav.quotes")} }
            }
            div { class: "list", style: "margin-top: 8px",
                for qt in quotes {
                    {
                        let qid = qt.id;
                        let total = money_short(qt.total());
                        let issued = fmt::date(qt.issued, today, l);
                        let st = t(qt.status.key());
                        let tone: &'static str = match qt.status {
                            QuoteStatus::Paid | QuoteStatus::Accepted => "success",
                            QuoteStatus::Overdue | QuoteStatus::Rejected => "danger",
                            QuoteStatus::Sent | QuoteStatus::Invoiced => "info",
                            QuoteStatus::Draft => "",
                        };
                        rsx! {
                            div { key: "{qid}", class: "list-row click", onclick: move |_| go(&format!("/quotes/{qid}")),
                                span { class: "ic muted sm", Icon { name: "receipt", size: 14 } }
                                div { class: "meta",
                                    span { class: "title small num", "{qt.number}" }
                                    span { class: "sub", "{issued}" }
                                }
                                div { class: "stack gap-4", style: "align-items: flex-end",
                                    span { class: "strong small num", "{total}" }
                                    Badge { text: st, tone }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("deals.sub", "Klinikalar, korxonalar va maxsus buyurtmalar: har bir bitim qayerda turibdi", "Клиники, компании и спецзаказы: где сейчас каждая сделка", "Clinics, companies and special orders: where every deal stands"),
    ("deals.view_kanban", "Kanban", "Канбан", "Kanban"),
    ("deals.view_list", "Ro‘yxat", "Список", "List"),
    ("deals.view_forecast", "Prognoz", "Прогноз", "Forecast"),
    ("deals.open_value", "Ochiq bitimlar", "Открытые сделки", "Open pipeline"),
    ("deals.foot_open", "{n} ochiq", "открыто: {n}", "{n} open"),
    ("deals.weighted", "Ehtimol bilan", "Взвешенная сумма", "Weighted value"),
    ("deals.foot_weighted", "bosqich ehtimoli bo‘yicha", "с учётом вероятности этапа", "by stage probability"),
    ("deals.foot_rotting", "{n} to‘xtab qoldi", "без движения: {n}", "{n} going cold"),
    ("deals.won_month", "Shu oy yutildi", "Выиграно за месяц", "Won this month"),
    ("deals.foot_won", "{n} · hammasi {v}", "{n} · всего {v}", "{n} · {v} company-wide"),
    ("deals.win_rate", "Yutish darajasi", "Доля побед", "Win rate"),
    ("deals.foot_rate", "90 kunda yopilgan: {n}", "закрыто за 90 дней: {n}", "{n} closed in 90 days"),
    ("deals.search", "Bitim yoki tashkilot…", "Сделка или организация…", "Deal or organisation…"),
    ("deals.all_owners", "Barcha mas’ullar", "Все ответственные", "All owners"),
    ("deals.going_cold", "To‘xtab qolganlar", "Без движения", "Going cold"),
    ("deals.add_here", "Bitim qo‘shish", "Добавить сделку", "Add a deal"),
    ("deals.moved", "Bitim ko‘chirildi", "Сделка перенесена", "Deal moved"),
    ("deals.won_toast", "Bitim yutildi", "Сделка выиграна", "Deal won"),
    ("deals.lost_toast", "Bitim boy berildi deb belgilandi", "Сделка отмечена как проигранная", "Deal marked as lost"),
    ("deals.reopened", "Bitim qayta ochildi", "Сделка снова открыта", "Deal reopened"),
    ("deals.idle", "{n} harakatsiz", "{n} без движения", "{n} idle"),
    ("deals.in_stage", "bosqichda {n} kun", "{n} дн. на этапе", "{n} d in stage"),
    ("deals.move_to", "Ko‘chirish…", "Перенести в…", "Move to…"),
    ("deals.mark_won", "Yutildi", "Выиграна", "Mark won"),
    ("deals.mark_lost", "Boy berildi", "Проиграна", "Mark lost"),
    ("deals.zone_won", "Yutildi: shu yerga tashlang", "Выиграна: перетащите сюда", "Won: drop here"),
    ("deals.zone_won_text", "Shu oy: {n}, {v}", "В этом месяце: {n}, {v}", "{n} this month, {v}"),
    ("deals.zone_lost", "Boy berildi: shu yerga tashlang", "Проиграна: перетащите сюда", "Lost: drop here"),
    ("deals.zone_lost_text", "90 kunda: {n}; sababi so‘raladi", "За 90 дней: {n}; спросим причину", "{n} in 90 days; we’ll ask why"),
    ("deals.stage", "Bosqich", "Этап", "Stage"),
    ("deals.probability", "Ehtimol", "Вероятность", "Probability"),
    ("deals.expected_close", "Kutilgan yopilish", "Ожидаемое закрытие", "Expected close"),
    ("deals.activity", "Faollik", "Активность", "Activity"),
    ("deals.no_results_text", "Qidiruv yoki filtrni o‘zgartiring.", "Измените поиск или фильтр.", "Change the search or filter."),
    ("deals.forecast_title", "4 oylik prognoz", "Прогноз на 4 месяца", "4-month forecast"),
    ("deals.forecast_hint", "Kutilgan yopilish oyi bo‘yicha: ehtimol bilan va eng yaxshi holatda", "По месяцу закрытия: взвешенно и в лучшем случае", "By expected close month: weighted and best case"),
    ("deals.best_case", "Eng yaxshi holat", "Лучший случай", "Best case"),
    ("deals.health", "Voronka ko‘rsatkichlari", "Показатели воронки", "Pipeline health"),
    ("deals.avg_deal", "O‘rtacha bitim", "Средняя сделка", "Average deal"),
    ("deals.avg_cycle", "O‘rtacha sikl", "Средний цикл", "Average cycle"),
    ("deals.won_total", "Yutilgan bitimlar", "Выигранные сделки", "Deals won"),
    ("deals.funnel", "Bosqichlar bo‘yicha", "По этапам", "By stage"),
    ("deals.funnel_empty", "Ochiq bitimlar yo‘q", "Открытых сделок нет", "No open deals"),
    ("deals.lost_reasons", "Nega boy beramiz", "Почему проигрываем", "Why we lose"),
    ("deals.no_lost", "Boy berilgan bitimlar yo‘q", "Проигранных сделок нет", "No lost deals"),
    ("deals.lost_title", "Nega boy berildi?", "Почему проиграли?", "Why was it lost?"),
    ("deals.reason.price", "Narx yuqori", "Высокая цена", "Price too high"),
    ("deals.reason.competitor", "Raqobatchi arzonroq taklif berdi", "Конкурент предложил дешевле", "A competitor offered less"),
    ("deals.reason.budget", "Byudjet qisqardi", "Сократили бюджет", "Budget was cut"),
    ("deals.reason.silent", "Javob bermay qo‘ydi", "Перестали отвечать", "Stopped responding"),
    ("deals.reason.timing", "Muddati to‘g‘ri kelmadi", "Не подошли сроки", "Timing didn’t work"),
    ("deals.reason.registration", "Dori ro‘yxatdan o‘tmagan", "Препарат не зарегистрирован", "Medicine not registered"),
    ("deals.reason.tender", "Tenderda boshqa yetkazuvchi yutdi", "Тендер выиграл другой поставщик", "Another supplier won the tender"),
    ("deals.reason.other", "Boshqa sabab", "Другая причина", "Other reason"),
    ("deals.reason.other_hint", "Nima bo‘ldi? Keyingi safar uchun yozib qo‘ying", "Что произошло? Запишите на будущее", "What happened? Note it for next time"),
    ("deals.not_found", "Bitim topilmadi", "Сделка не найдена", "Deal not found"),
    ("deals.back", "Bitimlarga qaytish", "К сделкам", "Back to deals"),
    ("deals.reopen", "Qayta ochish", "Открыть снова", "Reopen"),
    ("deals.create_quote", "Taklif yaratish", "Создать КП", "Create quote"),
    ("deals.quote_needs_lines", "Avval mahsulot qo‘shing", "Сначала добавьте товары", "Add products first"),
    ("deals.quote_created", "Tijorat taklifi yaratildi", "Коммерческое предложение создано", "Quote created"),
    ("deals.created_on", "{d} yaratilgan", "создана {d}", "created {d}"),
    ("deals.lost_because", "Boy berilish sababi", "Причина проигрыша", "Lost because"),
    ("deals.won_banner", "Bitim yutildi", "Сделка выиграна", "Deal won"),
    ("deals.track_hint", "Bosqichni bosib ko‘chiring", "Нажмите на этап, чтобы перенести", "Click a stage to move the deal"),
    ("deals.weighted_foot", "summa × ehtimol", "сумма × вероятность", "value × probability"),
    ("deals.days_open", "Ochiq turibdi", "Открыта", "Open for"),
    ("deals.lines", "Mahsulotlar", "Товары", "Products"),
    ("deals.manual_value", "Mahsulotlar qo‘shilmagan: bitim summasi qo‘lda kiritilgan ({v}). Mahsulot qo‘shsangiz, summa ular bo‘yicha hisoblanadi.", "Товары не добавлены: сумма сделки введена вручную ({v}). С товарами сумма считается по ним.", "No products yet: the deal value was entered by hand ({v}). Add products and the value follows them."),
    ("deals.qty", "Soni", "Кол-во", "Qty"),
    ("deals.discount", "Chegirma %", "Скидка %", "Disc. %"),
    ("deals.gross", "Chegirmasiz", "Без скидки", "Before discount"),
    ("deals.discounts", "Chegirmalar", "Скидки", "Discounts"),
    ("deals.subtotal", "Bitim summasi", "Сумма сделки", "Deal value"),
    ("deals.pick_product", "Katalogdan mahsulot…", "Товар из каталога…", "Product from the catalogue…"),
    ("deals.line_added", "Mahsulot qo‘shildi", "Товар добавлен", "Product added"),
    ("deals.activities", "Faoliyat", "Активности", "Activities"),
    ("deals.no_activities", "Hali faoliyat yo‘q", "Пока нет активностей", "No activities yet"),
    ("deals.activity_hint", "Masalan: narx bo‘yicha qo‘ng‘iroq", "Например: звонок по цене", "e.g. call about the price"),
    ("deals.note_hint", "Muhim narsani yozib qo‘ying…", "Запишите важное…", "Write down what matters…"),
    ("deals.terms", "{n} kun", "{n} дн.", "{n} days"),
    ("deals.receivable", "Qarzi", "Долг", "Owes us"),
    ("deals.credit", "Kredit limiti", "Кредитный лимит", "Credit limit"),
    ("deals.payment", "To‘lov muddati", "Отсрочка", "Payment terms"),
    ("deals.primary", "Asosiy", "Основной", "Primary"),
    ("deals.spent", "Xaridlari", "Покупки", "Spent"),
    ("deals.orders", "Xaridlar soni", "Число покупок", "Orders"),
    ("deals.source", "Manba", "Источник", "Source"),
    ("deals.in_stage_since", "Bosqichda", "На этапе с", "In stage since"),
    ("deals.last_activity", "Oxirgi faollik", "Последняя активность", "Last activity"),
    ("deals.priority", "Muhimlik", "Приоритет", "Priority"),
    ("deals.next_step", "Keyingi qadam", "Следующий шаг", "Next step"),
    ("deals.next_step_hint", "Masalan: shartnomani imzolash", "Например: подписать договор", "e.g. sign the contract"),
];
