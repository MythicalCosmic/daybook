//! Automations: pharmacy recipes that run by themselves (refill reminders, the birthday bonus,
//! win-back, the day-3 antibiotic check-in, waitlist arrivals, the 4-hour adverse-reaction rule).
//! A gallery with on/off switches and results, a flow editor in a drawer, a run log and a
//! library to start from a recipe or from scratch.

use chrono::{Duration, NaiveDateTime};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::Action;
use crm::model::*;
use crm::Db;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

fn recipe_tone(recipe: Option<&str>) -> &'static str {
    match recipe.unwrap_or("") {
        "refill" | "lead" => "accent",
        "birthday" | "deal" => "info",
        "winback" | "tier" => "warning",
        "day3" | "waitlist" | "first" => "success",
        "adverse" | "nps" => "danger",
        _ => "muted",
    }
}

fn action_tone(a: &Action) -> &'static str {
    match a {
        Action::SendTelegram { .. } => "info",
        Action::SendSms { .. } => "warning",
        Action::CreateTask { .. } => "accent",
        Action::GiveBonus { .. } => "success",
        Action::NotifyManager { .. } => "danger",
        Action::ReserveStock => "success",
        _ => "muted",
    }
}

fn days_text(n: i32, before: bool, after: bool) -> String {
    match lang() {
        Lang::Ru if before => format!("за {} дн.", n),
        Lang::Ru if after => format!("через {} дн. после покупки", n),
        Lang::Ru => format!("{} дн. без покупок", n),
        Lang::En if before => format!("{n} days before"),
        Lang::En if after => format!("{n} days after a purchase"),
        Lang::En => format!("{n} days without a purchase"),
        _ if before => uz(format!("{n} kun oldin")),
        _ if after => uz(format!("xariddan {n} kun keyin")),
        _ => uz(format!("{n} kun xarid yo‘q")),
    }
}

fn trigger_detail(db: &Db, tr_: &Trigger) -> String {
    match tr_ {
        Trigger::Birthday { days_before: 0 } => tr("o‘sha kuni", "в тот же день", "on the day"),
        Trigger::Birthday { days_before } | Trigger::RefillDue { days_before } => days_text(*days_before, true, false),
        Trigger::Inactive { days } => days_text(*days, false, false),
        Trigger::AfterPurchase { days } => days_text(*days, false, true),
        Trigger::DealStage { stage_id } => db.stage(*stage_id).map(|(_, s)| s.name.clone()).unwrap_or_default(),
        _ => String::new(),
    }
}

fn with_days(tr_: &Trigger, n: i32) -> Trigger {
    match tr_ {
        Trigger::Birthday { .. } => Trigger::Birthday { days_before: n },
        Trigger::RefillDue { .. } => Trigger::RefillDue { days_before: n },
        Trigger::Inactive { .. } => Trigger::Inactive { days: n },
        Trigger::AfterPurchase { .. } => Trigger::AfterPurchase { days: n },
        other => other.clone(),
    }
}

fn trigger_options(db: &Db) -> Vec<Trigger> {
    let stage = db.pipelines.first().and_then(|p| p.stages.get(2).or(p.stages.first())).map(|s| s.id).unwrap_or(0);
    vec![
        Trigger::RefillDue { days_before: 3 },
        Trigger::AfterPurchase { days: 3 },
        Trigger::Birthday { days_before: 0 },
        Trigger::Inactive { days: 60 },
        Trigger::FirstPurchase,
        Trigger::TierUp,
        Trigger::WaitlistArrived,
        Trigger::TicketCreated,
        Trigger::LowNps,
        Trigger::NewLead,
        Trigger::DealStage { stage_id: stage },
    ]
}

fn action_options() -> Vec<Action> {
    vec![
        Action::SendTelegram { text: String::new() },
        Action::SendSms { text: String::new() },
        Action::CreateTask { title: String::new(), role: Role::Pharmacist, due_days: 0 },
        Action::ReserveStock,
        Action::GiveBonus { points: 10_000 },
        Action::Wait { days: 1 },
        Action::NotifyManager { text: String::new() },
        Action::AddTag { tag: String::new() },
    ]
}

fn due_text(n: i32) -> String {
    match n {
        0 => t("common.today"),
        1 => t("common.tomorrow"),
        n => fmt::due_in(crate::state::today() + Duration::days(n as i64), crate::state::today(), lang()),
    }
}

fn rule_text(r: &Rule) -> String {
    format!("{} · {}{}", t(r.field.key()), t(r.op.key()), if r.value.is_empty() { String::new() } else { format!(" {}", r.value) })
}

fn new_automation(db: &mut Db, from: Automation, name: String) -> Id {
    let id = db.new_id();
    let today = db.generated_on.max(crate::state::today());
    db.automations.insert(0, Automation { id, name, enabled: false, runs: 0, conversions: 0, last_run: None, created: today, ..from });
    id
}

// ---------------------------------------------------------------- page

#[component]
pub fn Automations() -> Element {
    let mut selected = use_signal(|| None::<u32>);
    let mut library = use_signal(|| false);
    let mut filter = use_signal(|| "all".to_string());
    let all: Vec<Automation> = DB.read().automations.clone();
    let active = all.iter().filter(|a| a.enabled).count();
    let runs: u32 = all.iter().map(|a| a.runs).sum();
    let conv: u32 = all.iter().map(|a| a.conversions).sum();
    let l = lang();
    let conv_rate = if runs > 0 { conv as f64 / runs as f64 * 100.0 } else { 0.0 };
    let hours = runs as i64 * 3 / 60;
    let shown: Vec<Automation> = all
        .iter()
        .filter(|a| match filter().as_str() {
            "on" => a.enabled,
            "off" => !a.enabled,
            _ => true,
        })
        .cloned()
        .collect();
    let subtitle = match l {
        Lang::Ru => format!("{} сценариев · включено: {} · запусков: {}", all.len(), active, fmt::num(runs as i64)),
        Lang::En => format!("{} recipes · {} on · {} runs", all.len(), active, fmt::num(runs as i64)),
        _ => uz(format!("{} ta ssenariy · {} tasi yoqilgan · {} marta ishladi", all.len(), active, fmt::num(runs as i64))),
    };
    let hero_items: Vec<(Option<Id>, &'static str, String, String)> = {
        let find = |r: &str| all.iter().find(|a| a.recipe.as_deref() == Some(r));
        let refill = find("refill");
        let day3 = find("day3");
        let adverse = find("adverse");
        vec![
            (
                refill.map(|a| a.id),
                "repeat",
                t("auto.hero_refill"),
                refill
                    .map(|a| t("auto.hero_refill_stat").replace("{n}", &fmt::num(a.runs as i64)).replace("{p}", &fmt::pct(a.conversions as f64 / a.runs.max(1) as f64 * 100.0, l)))
                    .unwrap_or_default(),
            ),
            (day3.map(|a| a.id), "pill", t("auto.hero_day3"), day3.map(|a| t("auto.hero_day3_stat").replace("{n}", &fmt::num(a.runs as i64))).unwrap_or_default()),
            (adverse.map(|a| a.id), "triangle-alert", t("auto.hero_adverse"), t("auto.hero_adverse_stat")),
        ]
    };
    let best: Vec<(String, f64, String)> = {
        let mut v: Vec<&Automation> = all.iter().filter(|a| a.runs >= 20 && a.conversions > 0).collect();
        v.sort_by(|a, b| (b.conversions as f64 / b.runs as f64).partial_cmp(&(a.conversions as f64 / a.runs as f64)).unwrap_or(std::cmp::Ordering::Equal));
        v.iter().take(6).map(|a| {
            let p = a.conversions as f64 / a.runs as f64 * 100.0;
            (a.name.clone(), p, fmt::pct(p, l))
        }).collect()
    };
    let filters = vec![
        ("all".to_string(), format!("{} · {}", t("common.all"), all.len())),
        ("on".to_string(), format!("{} · {}", t("auto.on"), active)),
        ("off".to_string(), format!("{} · {}", t("auto.off"), all.len() - active)),
    ];

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.automations"), subtitle,
                button { class: "btn", onclick: move |_| library.set(true), Icon { name: "folder-open", size: 16 } span { class: "label-text", {t("auto.library")} } }
                button {
                    class: "btn primary",
                    onclick: move |_| {
                        let name = t("auto.blank_name");
                        let mut id = 0;
                        mutate(|db| {
                            let blank = Automation {
                                id: 0,
                                name: String::new(),
                                description: String::new(),
                                trigger: Trigger::NewLead,
                                conditions: Vec::new(),
                                actions: vec![Action::SendTelegram { text: String::new() }],
                                enabled: false,
                                runs: 0,
                                conversions: 0,
                                last_run: None,
                                recipe: None,
                                created: db.generated_on,
                            };
                            id = new_automation(db, blank, name);
                        });
                        selected.set(Some(id));
                    },
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("auto.new")} }
                }
            }
            div { class: "card hero", style: "padding: 22px",
                div { class: "stack gap-16",
                    div { class: "stack gap-8",
                        span { class: "badge", style: "align-self: flex-start; background: rgb(255 255 255 / .16); color: #fff", Icon { name: "sparkles", size: 12 } {t("auto.hero_badge")} }
                        h2 { class: "display", style: "font-size: 24px; line-height: 1.15", {t("auto.hero_title")} }
                        p { class: "muted", style: "max-width: 640px", {t("auto.hero_text")} }
                    }
                    div { class: "grid-3", style: "gap: 12px",
                        for (aid, icon, title, stat) in hero_items {
                            div {
                                key: "{icon}",
                                class: "stack gap-8",
                                style: "padding: 14px; border-radius: 14px; background: rgb(255 255 255 / .1); border: 1px solid rgb(255 255 255 / .16); cursor: pointer",
                                onclick: move |_| if let Some(i) = aid { selected.set(Some(i)) },
                                div { class: "row gap-8",
                                    span { class: "ic sm", style: "background: rgb(255 255 255 / .18); color: #fff", Icon { name: icon, size: 15 } }
                                    span { class: "strong", "{title}" }
                                }
                                span { class: "small muted", "{stat}" }
                            }
                        }
                    }
                }
            }
            div { class: "grid-4",
                Kpi { label: t("auto.active"), value: format!("{active}/{}", all.len()), icon: "workflow", foot: t("auto.active_foot") }
                Kpi { label: t("auto.runs"), value: fmt::num(runs as i64), icon: "play", tone: "info", foot: t("auto.runs_foot") }
                Kpi { label: t("auto.results"), value: fmt::num(conv as i64), icon: "circle-check", tone: "success", foot: format!("{} {}", fmt::pct(conv_rate, l), t("auto.of_runs")) }
                Kpi { label: t("auto.saved"), value: format!("≈ {} {}", fmt::num(hours), t("auto.hours")), icon: "timer", tone: "warning", foot: t("auto.saved_foot") }
            }
            div { class: "section-head",
                div { class: "section-title", {t("auto.recipes")} }
                Segmented { options: filters, value: filter(), onchange: move |v: String| filter.set(v) }
            }
            if shown.is_empty() {
                div { class: "card", Empty { icon: "workflow", title: t("auto.empty"), text: t("auto.empty_text") } }
            }
            div { class: "grid-3",
                for a in shown {
                    RecipeCard { key: "{a.id}", a: a.clone(), onopen: move |id| selected.set(Some(id)) }
                }
            }
            div { class: "grid-main",
                RunLog {}
                div { class: "card",
                    div { class: "card-head", div { class: "card-title", Icon { name: "trophy", size: 16, class: "tone-warning" } {t("auto.best")} } }
                    div { class: "card-body", HBars { items: best, color: "var(--c-chart-2)" } }
                }
            }
        }
        // Overlays sit outside .page: its entry animation would pin fixed elements to the page box.
        if let Some(id) = selected() {
            EditorDrawer { key: "{id}", id, onclose: move |_| selected.set(None) }
        }
        if library() {
            Library {
                onclose: move |_| library.set(false),
                onpick: move |id| {
                    library.set(false);
                    selected.set(Some(id));
                },
            }
        }
    }
}

#[component]
fn RecipeCard(a: Automation, onopen: EventHandler<u32>) -> Element {
    let now = now();
    let l = lang();
    let id = a.id;
    let tone = recipe_tone(a.recipe.as_deref());
    let icon = a.trigger.icon();
    let trig = t(a.trigger.key());
    let detail = trigger_detail(&DB.read(), &a.trigger);
    let trig_line = if detail.is_empty() { trig } else { format!("{trig} · {detail}") };
    let steps = format!("{} {}", a.actions.len(), t("auto.steps"));
    let rate = if a.runs > 0 { fmt::pct(a.conversions as f64 / a.runs as f64 * 100.0, l) } else { "—".into() };
    let last = a.last_run.map(|r| fmt::relative(r, now, l)).unwrap_or_else(|| t("auto.never"));
    let enabled = a.enabled;
    let body_style = if enabled { "" } else { "opacity: .62" };
    let stats = vec![
        (t("auto.runs_short"), fmt::num(a.runs as i64)),
        (t("auto.results_short"), fmt::num(a.conversions as i64)),
        (t("auto.rate"), rate),
    ];
    let name = a.name.clone();
    rsx! {
        div { class: "card hover", style: "display: flex; flex-direction: column", onclick: move |_| onopen.call(id),
            div { class: "card-head", style: "align-items: flex-start",
                span { style: "{body_style}", IconTile { icon, tone } }
                div {
                    class: "row gap-8",
                    onclick: move |e| e.stop_propagation(),
                    span { class: if enabled { "xs strong tone-success" } else { "xs strong subtle" }, if enabled { {t("auto.on")} } else { {t("auto.off")} } }
                    Switch {
                        on: enabled,
                        onchange: move |v: bool| {
                            mutate(|db| {
                                if let Some(x) = db.automation_mut(id) {
                                    x.enabled = v;
                                }
                            });
                            toast(if v { t("auto.enabled_toast") } else { t("auto.disabled_toast") }, "workflow", if v { "success" } else { "" });
                        },
                    }
                }
            }
            div { class: "card-body stack gap-8", style: "flex: 1; {body_style}",
                span { class: "strong", style: "font-size: 15px", "{name}" }
                span { class: "small muted clamp-2", "{a.description}" }
                div { class: "row wrap gap-4", style: "margin-top: 2px",
                    span { class: "tag", "{trig_line}" }
                    span { class: "tag", "{steps}" }
                }
            }
            div { class: "card-foot", style: "align-items: flex-end",
                div { class: "row gap-16",
                    for (label, value) in stats {
                        div { key: "{label}", class: "stack", style: "gap: 0",
                            span { class: "strong num", "{value}" }
                            span { class: "xs muted", "{label}" }
                        }
                    }
                }
                span { class: "xs subtle row gap-4 nowrap", Icon { name: "clock", size: 12 } "{last}" }
            }
        }
    }
}

// ---------------------------------------------------------------- run log

#[component]
fn RunLog() -> Element {
    let now = now();
    let l = lang();
    let rows = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let mut autos: Vec<&Automation> = db.automations.iter().filter(|a| a.enabled && a.runs > 0).collect();
        autos.sort_by(|a, b| b.last_run.cmp(&a.last_run));
        let with_rx: Vec<&Customer> = db.customers.iter().filter(|c| !c.archived && !c.regimens.is_empty() && c.consent.telegram).collect();
        let anyone: Vec<&Customer> = db.customers.iter().filter(|c| !c.archived).collect();
        let mut out: Vec<(Id, String, u16, String, NaiveDateTime, &'static str, &'static str, &'static str)> = Vec::new();
        if autos.is_empty() || anyone.is_empty() {
            return out;
        }
        for k in 0..12usize {
            let a = autos[if k < 3 { 0 } else { k % autos.len() }];
            let recipe = a.recipe.clone().unwrap_or_default();
            let pool = if recipe == "refill" && !with_rx.is_empty() { &with_rx } else { &anyone };
            let c = pool[(k * 37 + 11) % pool.len()];
            let product = c.regimens.first().map(|r| db.product(r.product_id).map(|p| p.generic.clone()).unwrap_or_default()).unwrap_or_default();
            let what = if recipe == "refill" && !product.is_empty() { format!("{} · {}", a.name, product) } else { a.name.clone() };
            let (key, tone, icon): (&'static str, &'static str, &'static str) = match recipe.as_str() {
                "refill" => [("auto.out_reserved", "success", "package-check"), ("auto.out_read", "info", "check-check"), ("auto.out_tomorrow", "accent", "calendar"), ("auto.out_waiting", "", "clock")][k % 4],
                "birthday" => ("auto.out_bonus", "success", "gift"),
                "winback" => [("auto.out_sent", "info", "send"), ("auto.out_returned", "success", "shopping-bag")][k % 2],
                "day3" => ("auto.out_feels_good", "success", "smile"),
                "waitlist" => ("auto.out_reserved", "success", "package-check"),
                "adverse" => ("auto.out_adverse", "danger", "triangle-alert"),
                "lead" | "deal" | "nps" => ("auto.out_task", "accent", "square-check"),
                _ => ("auto.out_sent", "info", "send"),
            };
            let at = now - Duration::minutes(7 + k as i64 * 23 + (k as i64 / 4) * 40);
            out.push((c.id, c.name(), c.home_branch as u16, what, at, key, tone, icon));
        }
        out
    });
    let list = rows();
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "history", size: 16, class: "subtle" } {t("auto.log")} }
                span { class: "badge success", span { class: "dot" } {t("auto.live")} }
            }
            div { class: "list", style: "margin-top: 8px",
                if list.is_empty() { Empty { icon: "history", title: t("auto.log_empty") } }
                for (k, (cid, name, _, what, at, key, tone, icon)) in list.into_iter().enumerate() {
                    {
                        let when = fmt::relative(at, now, l);
                        let outcome = t(key);
                        rsx! {
                            div { key: "{k}", class: "list-row click", onclick: move |_| go(&format!("/contacts/{cid}")),
                                Avatar { name: name.clone(), size: "sm" }
                                div { class: "meta",
                                    span { class: "title small truncate", "{name}" }
                                    span { class: "sub truncate", "{what}" }
                                }
                                div { class: "stack", style: "gap: 3px; align-items: flex-end",
                                    Badge { text: outcome, tone, icon: Some(icon) }
                                    span { class: "xs subtle nowrap", "{when}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- editor

#[component]
fn EditorDrawer(id: u32, onclose: EventHandler<()>) -> Element {
    let source = DB.peek().automation(id).cloned();
    let mut name = use_signal(|| source.as_ref().map(|a| a.name.clone()).unwrap_or_default());
    let mut enabled = use_signal(|| source.as_ref().map(|a| a.enabled).unwrap_or(false));
    let mut trigger = use_signal(|| source.as_ref().map(|a| a.trigger.clone()).unwrap_or(Trigger::NewLead));
    let mut actions = use_signal(|| source.as_ref().map(|a| a.actions.clone()).unwrap_or_default());
    let mut add_menu = use_signal(|| false);
    let Some(src) = source else {
        return rsx! {};
    };
    let now = now();
    let l = lang();
    let (options, stages, detail) = {
        let db = DB.read();
        let stages: Vec<(Id, String)> = db.pipelines.iter().flat_map(|p| p.stages.iter().map(move |s| (s.id, format!("{} · {}", p.name, s.name)))).collect();
        (trigger_options(&db), stages, trigger_detail(&db, &trigger()))
    };
    let tr_now = trigger();
    let days = tr_now.days();
    let conditions: Vec<String> = src.conditions.iter().map(rule_text).collect();
    let stats = format!(
        "{} {} · {} {} · {}",
        fmt::num(src.runs as i64),
        t("auto.runs_short").to_lowercase(),
        fmt::num(src.conversions as i64),
        t("auto.results_short").to_lowercase(),
        src.last_run.map(|r| fmt::relative(r, now, l)).unwrap_or_else(|| t("auto.never"))
    );
    let acts = actions();
    let title = if name().trim().is_empty() { t("auto.blank_name") } else { name() };
    let icon = tr_now.icon();
    let sel_key = tr_now.key();
    let tr_label = t(tr_now.key());
    let if_label = t("auto.if");
    let add_opts: Vec<(usize, &'static str, String)> = action_options().iter().enumerate().map(|(i, a)| (i, a.icon(), t(a.key()))).collect();

    let save = move |_| {
        let (n, en, tr_, acts) = (name(), enabled(), trigger(), actions());
        mutate(move |db| {
            if let Some(a) = db.automation_mut(id) {
                if !n.trim().is_empty() {
                    a.name = n.trim().to_string();
                }
                a.enabled = en;
                a.trigger = tr_;
                a.actions = acts;
            }
        });
        toast(t("common.saved"), "save", "success");
        onclose.call(());
    };
    let test = move |_| {
        let (who, steps) = {
            let db = DB.peek();
            let who = db.customers.iter().find(|c| !c.regimens.is_empty() && c.consent.telegram).map(|c| c.name()).unwrap_or_default();
            (who, actions.peek().len())
        };
        toast(format!("{}: {} · {} {}", t("auto.test_done"), who, steps, t("auto.steps")), "play", "success");
    };

    rsx! {
        Drawer { title: title.clone(), icon: Some(icon), onclose: move |_| onclose.call(()),
            div { class: "drawer-body",
                div { class: "field",
                    label { class: "label", {t("common.name")} }
                    input { class: "input", value: "{name}", placeholder: t("auto.blank_name"), oninput: move |e| name.set(e.value()) }
                }
                div { class: "row between", style: "padding: 12px 14px; border-radius: 12px; background: var(--c-surface-2)",
                    div { class: "stack", style: "gap: 2px",
                        span { class: "strong small", if enabled() { {t("auto.on")} } else { {t("auto.off")} } }
                        span { class: "xs muted", "{stats}" }
                    }
                    Switch { on: enabled(), onchange: move |v: bool| enabled.set(v) }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("auto.trigger")} }
                        select {
                            class: "select",
                            onchange: move |e| {
                                let key = e.value();
                                let opts = trigger_options(&DB.peek());
                                if let Some(tr_) = opts.into_iter().find(|x| x.key() == key) {
                                    trigger.set(tr_);
                                }
                            },
                            for o in options {
                                option { key: "{o.key()}", value: "{o.key()}", selected: o.key() == sel_key, {t(o.key())} }
                            }
                        }
                    }
                    if let Some(d) = days {
                        div { class: "field",
                            label { class: "label", {t("auto.days")} }
                            input {
                                class: "input num",
                                r#type: "number",
                                min: "0",
                                value: "{d}",
                                oninput: move |e| {
                                    let n: i32 = e.value().parse().unwrap_or(0);
                                    let cur = trigger();
                                    trigger.set(with_days(&cur, n.clamp(0, 365)));
                                },
                            }
                        }
                    }
                    if let Trigger::DealStage { stage_id } = tr_now.clone() {
                        div { class: "field",
                            label { class: "label", {t("auto.stage")} }
                            select { class: "select", onchange: move |e| trigger.set(Trigger::DealStage { stage_id: e.value().parse().unwrap_or(0) }),
                                for (sid, sname) in stages {
                                    option { key: "{sid}", value: "{sid}", selected: sid == stage_id, "{sname}" }
                                }
                            }
                        }
                    }
                }
                div { class: "upper subtle", {t("auto.flow")} }
                div { class: "flow",
                    div { class: "flow-node trigger",
                        IconTile { icon, tone: "accent" }
                        div { class: "stack", style: "gap: 2px; min-width: 0",
                            span { class: "xs upper subtle", {t("auto.when")} }
                            span { class: "strong", "{tr_label}" }
                            if !detail.is_empty() { span { class: "small muted", "{detail}" } }
                        }
                    }
                    for (k, c) in conditions.into_iter().enumerate() {
                        div { key: "c{k}", class: "flow", style: "width: 100%",
                            div { class: "flow-link" }
                            div { class: "flow-node", style: "border-style: dashed",
                                IconTile { icon: "filter", tone: "muted", size: "sm" }
                                div { class: "stack", style: "gap: 2px; min-width: 0",
                                    span { class: "xs upper subtle", "{if_label}" }
                                    span { class: "small strong", "{c}" }
                                }
                            }
                        }
                    }
                    for (k, a) in acts.into_iter().enumerate() {
                        div { key: "a{k}-{a.key()}", class: "flow", style: "width: 100%",
                            div { class: "flow-link" }
                            ActionNode { idx: k, a: a.clone(), actions }
                        }
                    }
                    div { class: "flow-link" }
                    div { class: "popover-anchor",
                        button { class: "btn soft sm", onclick: move |_| add_menu.toggle(), Icon { name: "plus", size: 14 } {t("auto.add_step")} }
                        if add_menu() {
                            div { style: "position: fixed; inset: 0; z-index: 39", onclick: move |_| add_menu.set(false) }
                            div { class: "menu", style: "bottom: 38px; left: 0",
                                for (i, aicon, label) in add_opts {
                                    button {
                                        key: "{i}",
                                        class: "menu-item",
                                        onclick: move |_| {
                                            if let Some(a) = action_options().into_iter().nth(i) {
                                                actions.write().push(a);
                                            }
                                            add_menu.set(false);
                                        },
                                        Icon { name: aicon, size: 16 }
                                        "{label}"
                                    }
                                }
                            }
                        }
                    }
                }
            }
            div { class: "drawer-foot", style: "justify-content: space-between",
                button {
                    class: "btn ghost danger",
                    onclick: move |_| {
                        mutate(|db| db.automations.retain(|a| a.id != id));
                        toast(t("auto.deleted"), "trash-2", "");
                        onclose.call(());
                    },
                    Icon { name: "trash-2", size: 16 }
                    span { class: "hide-mobile", {t("common.delete")} }
                }
                div { class: "row gap-8",
                    button { class: "btn", onclick: test, Icon { name: "play", size: 16 } {t("auto.test")} }
                    button { class: "btn primary", onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
                }
            }
        }
    }
}

#[component]
fn ActionNode(idx: usize, a: Action, actions: Signal<Vec<Action>>) -> Element {
    let mut actions = actions;
    let icon = a.icon();
    let tone = action_tone(&a);
    let label = t(a.key());
    let text = a.text().map(|s| s.to_string());
    let extra = match &a {
        Action::CreateTask { role, due_days, .. } => Some(format!("{} · {}", t(role.key()), due_text(*due_days))),
        Action::GiveBonus { points } => Some(format!("+{} {}", fmt::num(*points), t("common.points"))),
        Action::Wait { days } => Some(fmt::days(*days as i64, lang())),
        Action::ReserveStock => Some(t("auto.reserve_text")),
        Action::MoveDeal { stage_id } => DB.read().stage(*stage_id).map(|(_, s)| s.name.clone()),
        _ => None,
    };
    let number = match &a {
        Action::GiveBonus { points } => Some(*points),
        Action::Wait { days } => Some(*days as i64),
        _ => None,
    };
    let rows = if matches!(a, Action::SendTelegram { .. } | Action::SendSms { .. }) { "3" } else { "1" };
    let placeholder = t("auto.text_hint");
    rsx! {
        div { class: "flow-node", style: "align-items: flex-start",
            IconTile { icon, tone, size: "sm" }
            div { class: "grow stack", style: "gap: 6px; min-width: 0",
                div { class: "row between",
                    span { class: "strong small", "{label}" }
                    button {
                        class: "icon-btn sm",
                        style: "width: 24px; height: 24px",
                        onclick: move |_| {
                            let mut v = actions.write();
                            if idx < v.len() {
                                v.remove(idx);
                            }
                        },
                        Icon { name: "x", size: 14 }
                    }
                }
                if let Some(tx) = text {
                    textarea {
                        class: "textarea",
                        style: "min-height: 0; font-size: 13px",
                        rows: "{rows}",
                        value: "{tx}",
                        placeholder: "{placeholder}",
                        oninput: move |e| {
                            let v = e.value();
                            let mut list = actions.write();
                            if let Some(x) = list.get_mut(idx) {
                                *x = match x.clone() {
                                    Action::SendTelegram { .. } => Action::SendTelegram { text: v },
                                    Action::SendSms { .. } => Action::SendSms { text: v },
                                    Action::NotifyManager { .. } => Action::NotifyManager { text: v },
                                    Action::CreateTask { role, due_days, .. } => Action::CreateTask { title: v, role, due_days },
                                    Action::AddTag { .. } => Action::AddTag { tag: v },
                                    other => other,
                                };
                            }
                        },
                    }
                }
                if let Some(n) = number {
                    input {
                        class: "input sm num",
                        r#type: "number",
                        min: "0",
                        style: "width: 140px",
                        value: "{n}",
                        oninput: move |e| {
                            let n: i64 = e.value().parse().unwrap_or(0);
                            let mut list = actions.write();
                            if let Some(x) = list.get_mut(idx) {
                                *x = match x.clone() {
                                    Action::GiveBonus { .. } => Action::GiveBonus { points: n.max(0) },
                                    Action::Wait { .. } => Action::Wait { days: n.clamp(0, 365) as i32 },
                                    other => other,
                                };
                            }
                        },
                    }
                }
                if let Some(e) = extra { span { class: "xs muted", "{e}" } }
            }
        }
    }
}

// ---------------------------------------------------------------- library

#[component]
fn Library(onclose: EventHandler<()>, onpick: EventHandler<u32>) -> Element {
    let recipes: Vec<(Id, String, String, &'static str, &'static str)> =
        DB.read().automations.iter().filter(|a| a.recipe.is_some()).map(|a| (a.id, a.name.clone(), a.description.clone(), a.trigger.icon(), recipe_tone(a.recipe.as_deref()))).collect();
    let use_label = t("auto.use");
    let copy_suffix = t("auto.copy");
    let first_name = t("auto.first_name");
    let first_desc = t("auto.first_desc");
    let blank_name = t("auto.blank_name");
    rsx! {
        Modal { title: t("auto.library"), wide: true, onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                p { class: "muted small", {t("auto.library_text")} }
                div { class: "grid-2", style: "gap: 10px",
                    {
                        let fname = first_name.clone();
                        let blank = blank_name.clone();
                        rsx! {
                            div { class: "insight success", style: "cursor: pointer",
                                onclick: move |_| {
                                    let mut id = 0;
                                    let n = fname.clone();
                                    mutate(|db| {
                                        let a = Automation {
                                            id: 0,
                                            name: String::new(),
                                            description: String::new(),
                                            trigger: Trigger::FirstPurchase,
                                            conditions: Vec::new(),
                                            actions: vec![
                                                Action::SendTelegram { text: "{ism}, Oydin Farm’ga xush kelibsiz! Hisobingizga 10 000 bonus ball qo‘shdik: keyingi xaridda ishlating.".into() },
                                                Action::GiveBonus { points: 10_000 },
                                            ],
                                            enabled: false,
                                            runs: 0,
                                            conversions: 0,
                                            last_run: None,
                                            recipe: Some("first".into()),
                                            created: db.generated_on,
                                        };
                                        id = new_automation(db, a, n);
                                    });
                                    onpick.call(id);
                                },
                                span { class: "ic", Icon { name: "sparkles", size: 17 } }
                                div { class: "grow stack", style: "gap: 2px",
                                    span { class: "strong", "{first_name}" }
                                    span { class: "small muted", "{first_desc}" }
                                }
                                span { class: "badge success sm", {t("common.new")} }
                            }
                            div { class: "insight", style: "cursor: pointer; border-style: dashed",
                                onclick: move |_| {
                                    let mut id = 0;
                                    let n = blank.clone();
                                    mutate(|db| {
                                        let a = Automation {
                                            id: 0,
                                            name: String::new(),
                                            description: String::new(),
                                            trigger: Trigger::NewLead,
                                            conditions: Vec::new(),
                                            actions: vec![Action::SendTelegram { text: String::new() }],
                                            enabled: false,
                                            runs: 0,
                                            conversions: 0,
                                            last_run: None,
                                            recipe: None,
                                            created: db.generated_on,
                                        };
                                        id = new_automation(db, a, n);
                                    });
                                    onpick.call(id);
                                },
                                span { class: "ic muted", Icon { name: "plus", size: 17 } }
                                div { class: "grow stack", style: "gap: 2px",
                                    span { class: "strong", "{blank_name}" }
                                    span { class: "small muted", {t("auto.blank_desc")} }
                                }
                            }
                        }
                    }
                    for (rid, rname, rdesc, icon, tone) in recipes {
                        {
                            let label = format!("{rname} ({copy_suffix})");
                            rsx! {
                                div { key: "{rid}", class: "insight {tone}",
                                    span { class: "ic", Icon { name: icon, size: 17 } }
                                    div { class: "grow stack", style: "gap: 2px; min-width: 0",
                                        span { class: "strong", "{rname}" }
                                        span { class: "small muted clamp-2", "{rdesc}" }
                                    }
                                    button {
                                        class: "btn sm",
                                        onclick: move |_| {
                                            let mut id = 0;
                                            let n = label.clone();
                                            mutate(|db| {
                                                if let Some(src) = db.automation(rid).cloned() {
                                                    id = new_automation(db, src, n);
                                                }
                                            });
                                            if id != 0 {
                                                toast(t("auto.created"), "copy", "success");
                                                onpick.call(id);
                                            }
                                        },
                                        Icon { name: "copy", size: 14 }
                                        "{use_label}"
                                    }
                                }
                            }
                        }
                    }
                }
            }
            div { class: "modal-foot",
                button { class: "btn", onclick: move |_| onclose.call(()), {t("common.close")} }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("auto.new", "Yangi ssenariy", "Новый сценарий", "New automation"),
    ("auto.library", "Retseptlar kutubxonasi", "Библиотека сценариев", "Recipe library"),
    ("auto.library_text", "Tayyor dorixona ssenariylari: nusxa oling, matnni moslang va yoqing.", "Готовые аптечные сценарии: скопируйте, поправьте текст и включите.", "Ready-made pharmacy recipes: copy one, adjust the text and switch it on."),
    ("auto.hero_badge", "Faqat Daybook’da", "Только в Daybook", "Only in Daybook"),
    ("auto.hero_title", "Boshqa CRMlarda yo‘q dorixona retseptlari", "Аптечные сценарии, которых нет в других CRM", "Pharmacy recipes nobody else ships"),
    ("auto.hero_text", "Doimiy dori tugashidan oldin eslatadi, antibiotik kursini kuzatadi va nojo‘ya ta’sirni 4 soat ichida provizorga yetkazadi. Hammasi o‘zi ishlaydi.", "Напомнит до того, как закончится постоянный препарат, проследит за курсом антибиотика и передаст нежелательную реакцию провизору за 4 часа. Всё работает само.", "It reminds people before their regular medicine runs out, follows up on antibiotic courses and gets an adverse reaction to a pharmacist within 4 hours. All on its own."),
    ("auto.hero_refill", "Dori tugashidan oldin eslatma", "Напоминание до конца лекарства", "Refill reminder"),
    ("auto.hero_refill_stat", "{n} marta ishladi · {p} bron yoki xarid", "{n} запусков · {p} бронь или покупка", "{n} runs · {p} reserved or bought"),
    ("auto.hero_day3", "Antibiotikdan keyin 3-kun", "3-й день после антибиотика", "Day-3 antibiotic check-in"),
    ("auto.hero_day3_stat", "{n} mijozdan holi so‘raldi: kursni oxirigacha ichishga yordam beradi", "{n} клиентов опрошены: помогает пройти курс до конца", "{n} customers checked on: helps them finish the course"),
    ("auto.hero_adverse", "Nojo‘ya ta’sir: 4 soatlik qoida", "Нежелательная реакция: правило 4 часов", "Adverse reaction: the 4-hour rule"),
    ("auto.hero_adverse_stat", "Provizorga vazifa, mudirga xabar va farmakonazorat shakli darhol", "Задача провизору, сигнал заведующему и форма фармаконадзора сразу", "A task for the pharmacist, a manager alert and the pharmacovigilance form at once"),
    ("auto.active", "Yoqilgan ssenariylar", "Включённые сценарии", "Active automations"),
    ("auto.active_foot", "24/7 ishlaydi", "работают 24/7", "running 24/7"),
    ("auto.runs", "Ishga tushishlar", "Запуски", "Runs"),
    ("auto.runs_foot", "shu oy, barcha filiallarda", "за месяц по всем филиалам", "this month, every branch"),
    ("auto.results", "Natijalar", "Результаты", "Results"),
    ("auto.of_runs", "ishga tushishlardan", "от запусков", "of runs"),
    ("auto.saved", "Tejalgan vaqt", "Сэкономлено времени", "Time saved"),
    ("auto.hours", "soat", "ч", "h"),
    ("auto.saved_foot", "har bir ishga ≈ 3 daqiqa qo‘l mehnati", "≈ 3 минуты ручной работы на запуск", "≈ 3 minutes of manual work per run"),
    ("auto.recipes", "Ssenariylar", "Сценарии", "Recipes"),
    ("auto.on", "Yoqilgan", "Вкл.", "On"),
    ("auto.off", "O‘chiq", "Выкл.", "Off"),
    ("auto.enabled_toast", "Ssenariy yoqildi", "Сценарий включён", "Automation switched on"),
    ("auto.disabled_toast", "Ssenariy o‘chirildi", "Сценарий выключен", "Automation switched off"),
    ("auto.steps", "qadam", "шагов", "steps"),
    ("auto.runs_short", "Ishladi", "Запуски", "Runs"),
    ("auto.results_short", "Natija", "Результат", "Results"),
    ("auto.rate", "Konversiya", "Конверсия", "Conversion"),
    ("auto.never", "hali ishlamagan", "ещё не запускался", "not run yet"),
    ("auto.empty", "Ssenariy yo‘q", "Сценариев нет", "No automations"),
    ("auto.empty_text", "Kutubxonadan tayyor retseptni oling yoki noldan boshlang.", "Возьмите готовый рецепт из библиотеки или начните с нуля.", "Take a recipe from the library or start from scratch."),
    ("auto.best", "Eng samarali ssenariylar", "Самые результативные", "Best performers"),
    ("auto.log", "Oxirgi ishga tushishlar", "Последние запуски", "Recent runs"),
    ("auto.live", "jonli", "в реальном времени", "live"),
    ("auto.log_empty", "Hali ishga tushish yo‘q", "Запусков пока нет", "No runs yet"),
    ("auto.out_reserved", "Bron qilindi", "Забронировано", "Reserved"),
    ("auto.out_read", "O‘qildi", "Прочитано", "Read"),
    ("auto.out_tomorrow", "Ertaga olib ketadi", "Заберёт завтра", "Picking up tomorrow"),
    ("auto.out_waiting", "Javob kutilmoqda", "Ждём ответа", "Awaiting reply"),
    ("auto.out_bonus", "25 000 ball berildi", "Начислено 25 000 баллов", "25,000 points given"),
    ("auto.out_sent", "Xabar yuborildi", "Сообщение отправлено", "Message sent"),
    ("auto.out_returned", "Qaytib keldi: xarid", "Вернулся: покупка", "Came back: purchase"),
    ("auto.out_feels_good", "Javob: o‘zini yaxshi his qilyapti", "Ответ: чувствует себя хорошо", "Reply: feeling well"),
    ("auto.out_adverse", "Provizorga vazifa · 4 soat", "Задача провизору · 4 ч", "Pharmacist task · 4 h"),
    ("auto.out_task", "Vazifa yaratildi", "Задача создана", "Task created"),
    ("auto.trigger", "Ishga tushiruvchi", "Триггер", "Trigger"),
    ("auto.days", "Kunlar", "Дней", "Days"),
    ("auto.stage", "Bosqich", "Этап", "Stage"),
    ("auto.flow", "Ish tartibi", "Порядок действий", "Flow"),
    ("auto.when", "Qachon", "Когда", "When"),
    ("auto.if", "Agar", "Если", "If"),
    ("auto.add_step", "Qadam qo‘shish", "Добавить шаг", "Add a step"),
    ("auto.text_hint", "Matn: {ism}, {dori}, {filial} o‘zgaruvchilari ishlaydi", "Текст: работают переменные {ism}, {dori}, {filial}", "Text: {ism}, {dori} and {filial} work here"),
    ("auto.reserve_text", "Mijozning filialida 1 qadoq ajratiladi", "В филиале клиента откладывается 1 упаковка", "One pack is held at the customer’s branch"),
    ("auto.test", "Sinab ko‘rish", "Тестовый запуск", "Test run"),
    ("auto.test_done", "Sinov o‘tdi, hech kimga yuborilmadi", "Тест пройден, никому не отправлено", "Test passed, nothing was sent"),
    ("auto.deleted", "Ssenariy o‘chirildi", "Сценарий удалён", "Automation deleted"),
    ("auto.use", "Ishlatish", "Использовать", "Use"),
    ("auto.copy", "nusxa", "копия", "copy"),
    ("auto.created", "Retseptdan ssenariy yaratildi", "Сценарий создан из рецепта", "Automation created from the recipe"),
    ("auto.first_name", "Birinchi xarid: xush kelibsiz", "Первая покупка: добро пожаловать", "First purchase: welcome"),
    ("auto.first_desc", "Telegram tabrigi va 10 000 bonus ball: ikkinchi xaridga undaydi", "Приветствие в Telegram и 10 000 баллов: подталкивает ко второй покупке", "A Telegram welcome and 10,000 points: nudges the second purchase"),
    ("auto.blank_name", "Yangi ssenariy", "Новый сценарий", "New automation"),
    ("auto.blank_desc", "Bitta ishga tushiruvchi va bitta qadam bilan noldan boshlash", "С нуля: один триггер и один шаг", "From scratch: one trigger and one step"),
];
