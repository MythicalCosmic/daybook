//! Settings (appearance, company, care rules, pipelines, AI budget, data and privacy) and the
//! Daybook connection: server check, Telegram sign-in with number matching, sync.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::daybook::{self, background, Health, LoginLink, Session};
use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

fn platform() -> &'static str {
    if cfg!(target_arch = "wasm32") {
        "Web (WASM)"
    } else if cfg!(target_os = "android") {
        "Android"
    } else if cfg!(target_os = "ios") {
        "iOS"
    } else if cfg!(target_os = "windows") {
        "Windows"
    } else if cfg!(target_os = "macos") {
        "macOS"
    } else {
        "Linux"
    }
}

#[component]
pub fn SettingsPage() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.settings"), subtitle: t("settings.subtitle"),
                Link { to: Route::DaybookConnect {}, class: "btn", Icon { name: "link-2", size: 16 } span { class: "label-text", {t("nav.daybook")} } }
            }
            div { class: "grid-main",
                div { class: "stack gap-16",
                    Appearance {}
                    CareRules {}
                    Pipelines {}
                    DataPrivacy {}
                }
                div { class: "stack gap-16",
                    DaybookMini {}
                    AiBudget {}
                    About {}
                }
            }
        }
    }
}

#[component]
fn Appearance() -> Element {
    let (theme, cur, compact, privacy, company, me) = {
        let db = DB.read();
        (db.settings.theme, db.settings.lang, db.settings.compact, db.settings.privacy_mode, db.settings.company_name.clone(), db.settings.me)
    };
    let staff: Vec<(Id, String, Role)> = DB.read().staff.iter().map(|s| (s.id, s.name.clone(), s.role)).collect();
    let mut name = use_signal(move || company.clone());
    rsx! {
        div { class: "card",
            div { class: "card-head line", div { class: "card-title", Icon { name: "sliders-horizontal", size: 16, class: "subtle" } {t("settings.appearance")} } }
            div { class: "list",
                div { class: "list-row",
                    div { class: "meta", span { class: "title", {t("common.theme")} } }
                    Segmented {
                        options: Theme::ALL.iter().map(|th| (th.slug().to_string(), t(th.key()))).collect(),
                        value: theme.slug().to_string(),
                        onchange: move |v: String| mutate(|db| if let Some(th) = Theme::from_slug(&v) { db.settings.theme = th }),
                    }
                }
                div { class: "list-row", style: "flex-wrap: wrap",
                    div { class: "meta", span { class: "title", {t("common.language")} } span { class: "sub", {t("settings.lang_hint")} } }
                    div { class: "row wrap gap-4",
                        for l in Lang::ALL.iter().copied() {
                            button { key: "{l.code()}", class: if l == cur { "chip on" } else { "chip" }, onclick: move |_| mutate(|db| db.settings.lang = l), "{l.native_name()}" }
                        }
                    }
                }
                div { class: "list-row",
                    div { class: "meta", span { class: "title", {t("settings.compact")} } span { class: "sub", {t("settings.compact_hint")} } }
                    Switch { on: compact, onchange: move |v| mutate(|db| db.settings.compact = v) }
                }
                div { class: "list-row",
                    div { class: "meta", span { class: "title", {t("common.privacy_mode")} } span { class: "sub", {t("settings.privacy_hint")} } }
                    Switch { on: privacy, onchange: move |v| mutate(|db| db.settings.privacy_mode = v) }
                }
                div { class: "list-row", style: "flex-wrap: wrap",
                    div { class: "meta", span { class: "title", {t("settings.company_name")} } }
                    div { class: "row", style: "flex: 1 1 260px",
                        input { class: "input", value: "{name}", oninput: move |e| name.set(e.value()) }
                        button { class: "btn", onclick: move |_| { let n = name(); mutate(|db| db.settings.company_name = n); toast(t("common.saved"), "check", "success"); }, {t("common.save")} }
                    }
                }
                div { class: "list-row", style: "flex-wrap: wrap",
                    div { class: "meta", span { class: "title", {t("settings.view_as")} } span { class: "sub", {t("settings.view_as_hint")} } }
                    select { class: "select", style: "flex: 0 1 280px", onchange: move |e| { let id: Id = e.value().parse().unwrap_or(me); mutate(|db| db.settings.me = id); },
                        for (id, n, role) in staff { option { key: "{id}", value: "{id}", selected: id == me, {format!("{n} · {}", t(role.key()))} } }
                    }
                }
            }
        }
    }
}

#[component]
fn CareRules() -> Element {
    let (refill, inactive, sla) = {
        let db = DB.read();
        (db.settings.refill_lead_days, db.settings.inactive_days, db.settings.sla_hours)
    };
    let opts = |vals: &[u16], unit: &str| -> Vec<(String, String)> { vals.iter().map(|v| (v.to_string(), format!("{v} {unit}"))).collect() };
    let days = tr("kun", "дн.", "d");
    let hours = tr("soat", "ч", "h");
    rsx! {
        div { class: "card",
            div { class: "card-head line",
                div { class: "card-title", Icon { name: "heart-pulse", size: 16, class: "subtle" } {t("settings.care")} }
                span { class: "badge", {t("settings.per_company")} }
            }
            div { class: "list",
                div { class: "list-row", style: "flex-wrap: wrap",
                    div { class: "meta", span { class: "title", {t("settings.refill_lead")} } span { class: "sub", {t("settings.refill_lead_hint")} } }
                    Segmented { options: opts(&[2, 3, 5, 7], &days), value: refill.to_string(), onchange: move |v: String| mutate(|db| db.settings.refill_lead_days = v.parse().unwrap_or(3)) }
                }
                div { class: "list-row", style: "flex-wrap: wrap",
                    div { class: "meta", span { class: "title", {t("settings.inactive")} } span { class: "sub", {t("settings.inactive_hint")} } }
                    Segmented { options: opts(&[30, 45, 60, 90], &days), value: inactive.to_string(), onchange: move |v: String| mutate(|db| db.settings.inactive_days = v.parse().unwrap_or(60)) }
                }
                div { class: "list-row", style: "flex-wrap: wrap",
                    div { class: "meta", span { class: "title", {t("settings.sla")} } span { class: "sub", {t("settings.sla_hint")} } }
                    Segmented { options: opts(&[8, 24, 48], &hours), value: sla.to_string(), onchange: move |v: String| mutate(|db| db.settings.sla_hours = v.parse().unwrap_or(24)) }
                }
                Link { to: Route::Loyalty {}, class: "list-row click",
                    span { class: "ic accent sm", Icon { name: "gift", size: 15 } }
                    div { class: "meta", span { class: "title", {t("nav.loyalty")} } span { class: "sub", {t("settings.loyalty_hint")} } }
                    Icon { name: "chevron-right", size: 16, class: "subtle" }
                }
            }
        }
    }
}

#[component]
fn Pipelines() -> Element {
    let pipes: Vec<Pipeline> = DB.read().pipelines.clone();
    let counts: Vec<(Id, usize)> = {
        let db = DB.read();
        db.pipelines.iter().flat_map(|p| p.stages.iter().map(|s| (s.id, db.deals.iter().filter(|d| d.stage_id == s.id && d.status == DealStatus::Open).count()))).collect()
    };
    let mut open = use_signal(|| None::<Id>);
    rsx! {
        div { class: "card",
            div { class: "card-head line",
                div { class: "card-title", Icon { name: "square-kanban", size: 16, class: "subtle" } {t("settings.pipelines")} }
                span { class: "badge", {t("settings.per_company")} }
            }
            div { class: "list",
                for p in pipes {
                    {
                        let pid = p.id;
                        let expanded = open() == Some(pid);
                        let stages_line = p.stages.iter().map(|s| s.name.clone()).collect::<Vec<_>>().join(" → ");
                        let n = p.stages.len();
                        let picon: &'static str = match p.icon.as_str() { "building-2" => "building-2", "briefcase" => "briefcase", _ => "package" };
                        let chevron: &'static str = if expanded { "chevron-up" } else { "chevron-down" };
                        rsx! {
                            div { key: "{pid}",
                                div { class: "list-row click", onclick: move |_| open.set(if expanded { None } else { Some(pid) }),
                                    span { class: "ic muted sm", Icon { name: picon, size: 15 } }
                                    div { class: "meta",
                                        span { class: "title", "{p.name}" }
                                        span { class: "sub truncate", "{n} · {stages_line}" }
                                    }
                                    Icon { name: chevron, size: 16, class: "subtle" }
                                }
                                if expanded {
                                    div { class: "stack gap-8", style: "padding: 4px 18px 16px",
                                        for (i, s) in p.stages.iter().cloned().enumerate() {
                                            {
                                                let sid = s.id;
                                                let deals = counts.iter().find(|c| c.0 == sid).map(|c| c.1).unwrap_or(0);
                                                rsx! {
                                                    div { key: "{sid}", class: "row gap-8",
                                                        span { style: "width:10px;height:10px;border-radius:99px;background:hsl({s.hue} 48% 52%);flex:0 0 10px" }
                                                        input {
                                                            class: "input sm",
                                                            value: "{s.name}",
                                                            onchange: move |e| { let v = e.value(); mutate(|db| if let Some(st) = db.pipelines.iter_mut().flat_map(|p| p.stages.iter_mut()).find(|x| x.id == sid) { st.name = v }) },
                                                        }
                                                        select {
                                                            class: "select sm",
                                                            style: "width: 92px",
                                                            onchange: move |e| { let v: u8 = e.value().parse().unwrap_or(50); mutate(|db| if let Some(st) = db.pipelines.iter_mut().flat_map(|p| p.stages.iter_mut()).find(|x| x.id == sid) { st.probability = v }) },
                                                            for pr in [5u8, 10, 25, 30, 45, 50, 55, 65, 75, 80, 85, 90] { option { key: "{pr}", value: "{pr}", selected: pr == s.probability, "{pr}%" } }
                                                        }
                                                        span { class: "badge sm nowrap", "{deals}" }
                                                        button {
                                                            class: "icon-btn sm",
                                                            disabled: deals > 0 || n <= 2,
                                                            title: t("common.delete"),
                                                            onclick: move |_| mutate(|db| if let Some(p) = db.pipeline_mut(pid) { p.stages.retain(|x| x.id != sid) }),
                                                            Icon { name: "trash-2", size: 15 }
                                                        }
                                                        if i == 0 { span {} }
                                                    }
                                                }
                                            }
                                        }
                                        button {
                                            class: "btn soft sm",
                                            style: "align-self: flex-start",
                                            onclick: move |_| mutate(|db| {
                                                let id = db.new_id();
                                                let stage_name = crm::i18n::pick(db.settings.lang, "Yangi bosqich", "Новый этап", "New stage").into_owned();
                                                if let Some(p) = db.pipeline_mut(pid) {
                                                    let at = p.stages.len().saturating_sub(1);
                                                    p.stages.insert(at, Stage { id, name: stage_name, probability: 50, rot_days: 7, hue: 190 });
                                                }
                                            }),
                                            Icon { name: "plus", size: 14 }
                                            {t("settings.add_stage")}
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

#[component]
fn AiBudget() -> Element {
    let ai = DB.read().settings.ai.clone();
    let pct = (ai.spent_usd / ai.monthly_cap_usd.max(0.01) * 100.0) as f64;
    let mut cap = use_signal(move || format!("{:.0}", ai.monthly_cap_usd));
    let costs: Vec<(&'static str, String, &'static str)> = vec![
        ("message-circle", t("settings.ai_reply"), "$0.0004"),
        ("sparkles", t("settings.ai_summary"), "$0.0007"),
        ("layers", t("settings.ai_segment"), "$0.0009"),
        ("shield-check", t("settings.ai_compliance"), "$0.0003"),
    ];
    let model = ai.model.clone();
    let bar_tone: &'static str = if pct > 85.0 { "warning" } else { "" };
    rsx! {
        div { class: "card ai-panel stack gap-12",
            div { class: "row between",
                div { class: "card-title", Icon { name: "sparkles", size: 16 } {t("common.ai")} }
                Switch { on: ai.enabled, onchange: move |v| mutate(|db| db.settings.ai.enabled = v) }
            }
            div { class: "field",
                span { class: "label", {t("settings.ai_model")} }
                select { class: "select", onchange: move |e| { let v = e.value(); mutate(|db| db.settings.ai.model = v) },
                    option { value: "claude-haiku-5-5", selected: model == "claude-haiku-5-5", {t("settings.ai_haiku")} }
                    option { value: "claude-sonnet-5-5", selected: model == "claude-sonnet-5-5", {t("settings.ai_sonnet")} }
                }
            }
            div { class: "stack gap-4",
                div { class: "row between small",
                    span { class: "muted", {t("settings.ai_spent")} }
                    span { class: "num strong", {format!("${:.2} / ${:.0}", ai.spent_usd, ai.monthly_cap_usd)} }
                }
                Progress { pct, tone: bar_tone }
                span { class: "xs muted", {format!("{} {}", crm::fmt::num(ai.requests as i64), t("settings.ai_requests"))} }
            }
            div { class: "row gap-8",
                span { class: "small muted nowrap", {t("settings.ai_cap")} }
                input { class: "input sm num", style: "width: 90px", value: "{cap}", oninput: move |e| cap.set(e.value()) }
                button { class: "btn sm", onclick: move |_| { let v: f32 = cap().parse().unwrap_or(20.0); mutate(|db| db.settings.ai.monthly_cap_usd = v.max(1.0)); toast(t("common.saved"), "check", "success"); }, {t("common.save")} }
            }
            div { class: "stack gap-4",
                for (icon, label, cost) in costs {
                    div { key: "{label}", class: "row between small",
                        span { class: "row gap-8 muted", Icon { name: icon, size: 14 } "{label}" }
                        span { class: "num", "{cost}" }
                    }
                }
            }
            p { class: "xs muted", {t("settings.ai_note")} }
        }
    }
}

#[component]
fn DataPrivacy() -> Element {
    let audit: Vec<AuditEntry> = DB.read().audit.iter().take(10).cloned().collect();
    let staff_names: Vec<(Id, String)> = DB.read().staff.iter().map(|s| (s.id, s.name.clone())).collect();
    let mut confirm = use_signal(|| false);
    let now = now();
    let l = lang();
    let export = move |_| {
        let size = serde_json::to_string(&*DB.peek()).map(|s| s.len()).unwrap_or(0);
        mutate(|db| db.log(crate::state::now(), "Export: JSON", false));
        toast(format!("{} · {:.1} MB", t("settings.exported"), size as f64 / 1_048_576.0), "download", "success");
    };
    rsx! {
        div { class: "card",
            div { class: "card-head line", div { class: "card-title", Icon { name: "shield-check", size: 16, class: "subtle" } {t("settings.data")} } }
            div { class: "card-body stack gap-12",
                div { class: "row wrap gap-8",
                    button { class: "btn", onclick: move |_| toast(t("settings.import_hint"), "upload", "info"), Icon { name: "upload", size: 15 } {t("common.import")} }
                    button { class: "btn", onclick: export, Icon { name: "download", size: 15 } {t("common.export")} }
                    button { class: "btn danger", onclick: move |_| confirm.set(true), Icon { name: "rotate-ccw", size: 15 } {t("common.reset_demo")} }
                }
                div { class: "callout", Icon { name: "lock", size: 16 } span { {t("settings.privacy_note")} } }
                div { class: "upper subtle", {t("settings.audit")} }
                div { class: "list", style: "margin: 0 -18px",
                    for a in audit {
                        {
                            let who = staff_names.iter().find(|s| Some(s.0) == a.actor_id).map(|s| s.1.clone()).unwrap_or_default();
                            let when = crm::fmt::relative(a.at, now, l);
                            let a_icon: &'static str = if a.sensitive { "eye" } else { "history" };
                            rsx! {
                                div { key: "{a.id}", class: "list-row",
                                    span { class: if a.sensitive { "ic danger sm" } else { "ic muted sm" }, Icon { name: a_icon, size: 14 } }
                                    div { class: "meta",
                                        span { class: "small truncate", "{a.text}" }
                                        span { class: "sub", "{who} · {when}" }
                                    }
                                    if a.sensitive { Badge { text: t("settings.sensitive"), tone: "danger" } }
                                }
                            }
                        }
                    }
                }
            }
        }
        if confirm() {
            Modal { title: t("common.reset_demo"), onclose: move |_| confirm.set(false),
                div { class: "modal-body", p { {t("settings.reset_text")} } }
                div { class: "modal-foot",
                    button { class: "btn ghost", onclick: move |_| confirm.set(false), {t("common.cancel")} }
                    button { class: "btn danger solid", onclick: move |_| {
                        confirm.set(false);
                        mutate(|db| { let fresh = crate::storage::reset(db); *db = fresh; });
                        toast(t("palette.reset_done"), "rotate-ccw", "success");
                    }, Icon { name: "rotate-ccw", size: 15 } {t("common.reset_demo")} }
                }
            }
        }
    }
}

#[component]
fn About() -> Element {
    let rows: Vec<(String, String)> = vec![
        (t("settings.version"), format!("Daybook CRM {}", env!("CARGO_PKG_VERSION"))),
        (t("settings.platform"), platform().to_string()),
        (t("settings.engine"), "Rust · Dioxus 0.7".to_string()),
        (t("settings.storage"), t("settings.storage_value")),
        (t("common.language"), "O‘zbekcha · Ўзбекча · Русский · English".to_string()),
    ];
    rsx! {
        div { class: "card pad stack gap-12",
            div { class: "row gap-12",
                div { class: "brand-mark", Icon { name: "heart-pulse", size: 18 } }
                div {
                    div { class: "strong", "Daybook CRM" }
                    div { class: "xs muted", {t("welcome.tagline")} }
                }
            }
            KeyValues { items: rows }
        }
    }
}

#[component]
fn DaybookMini() -> Element {
    let d = DB.read().settings.daybook.clone();
    let mini_icon: &'static str = if d.connected { "circle-check" } else { "link-2" };
    let mini_title = if d.connected { d.company_name.clone() } else { t("home.daybook_title") };
    rsx! {
        div { class: "card tinted pad stack gap-12",
            div { class: "row gap-12",
                span { class: if d.connected { "ic success" } else { "ic accent" }, Icon { name: mini_icon, size: 17 } }
                div { class: "grow",
                    div { class: "strong", "{mini_title}" }
                    div { class: "small muted truncate", "{d.server}" }
                }
            }
            Link { to: Route::DaybookConnect {}, class: "btn block", {t("settings.manage_connection")} Icon { name: "arrow-right", size: 15 } }
        }
    }
}

// ---------------------------------------------------------------- Daybook connection

#[derive(Clone, PartialEq)]
enum Step {
    Idle,
    Waiting(LoginLink),
    Choose(Vec<(i64, String)>),
    Syncing,
}

fn session_from_settings() -> Session {
    let d = DB.peek().settings.daybook.clone();
    Session { server: d.server, access: d.access, refresh: d.refresh }
}

fn store_session(s: &Session) {
    let (server, access, refresh) = (s.server.clone(), s.access.clone(), s.refresh.clone());
    mutate(|db| {
        db.settings.daybook.server = server;
        db.settings.daybook.access = access;
        db.settings.daybook.refresh = refresh;
    });
}

async fn sync_company(s: Session, company: (i64, String), user: String) -> Result<SyncCounts, String> {
    let tasks: Vec<(u32, String, String, String)> = {
        let db = DB.peek();
        db.activities
            .iter()
            .filter(|a| a.daybook_task == Some(0))
            .map(|a| (a.id, a.title.clone(), a.due.format("%Y-%m-%dT%H:%M:00").to_string(), db.staff_name(Some(a.owner_id))))
            .collect()
    };
    let (s, pulled) = background(move || {
        let mut s = s;
        let p = s.pull(company.0, tasks);
        (s, p)
    })
    .await;
    store_session(&s);
    let pulled = pulled?;
    let mut counts = SyncCounts::default();
    mutate(|db| {
        counts = daybook::apply(db, &pulled);
        let d = &mut db.settings.daybook;
        d.connected = true;
        d.company_id = Some(company.0);
        d.company_name = company.1.clone();
        if !user.is_empty() {
            d.user_name = user.clone();
        }
        d.last_sync = Some(crate::state::now());
        d.pulled = counts.clone();
        let text = format!("Daybook: {} filial, {} xodim, {} mahsulot", counts.branches, counts.staff, counts.products);
        db.log(crate::state::now(), text, false);
    });
    Ok(counts)
}

#[component]
pub fn DaybookConnect() -> Element {
    let d = DB.read().settings.daybook.clone();
    let mut server = use_signal(move || d.server.clone());
    let mut health = use_signal(|| None::<Result<Health, String>>);
    let mut checking = use_signal(|| false);
    let mut step = use_signal(|| Step::Idle);
    let mut error = use_signal(|| None::<String>);
    let mut dev_id = use_signal(|| "1001".to_string());
    let cancel = use_hook(|| Arc::new(AtomicBool::new(false)));
    let local = daybook::is_local(&server());
    let web = cfg!(target_arch = "wasm32");

    let check = move |_| {
        let s = Session { server: server(), ..Default::default() };
        checking.set(true);
        spawn(async move {
            let r = background(move || s.health()).await;
            health.set(Some(r));
            checking.set(false);
        });
    };

    // After a successful sign-in: who am I, which company, then sync.
    let after_login = move |s: Session| {
        spawn(async move {
            store_session(&s);
            let (s, me) = background(move || {
                let mut s = s;
                let m = s.me();
                (s, m)
            })
            .await;
            store_session(&s);
            match me {
                Ok(me) => {
                    let user = me.name.clone();
                    mutate(|db| db.settings.daybook.user_name = user.clone());
                    if me.companies.len() == 1 {
                        step.set(Step::Syncing);
                        match sync_company(s, me.companies[0].clone(), user).await {
                            Ok(_) => {
                                step.set(Step::Idle);
                                toast(t("daybook.synced"), "circle-check", "success");
                            }
                            Err(e) => {
                                step.set(Step::Idle);
                                error.set(Some(e));
                            }
                        }
                    } else if me.companies.is_empty() {
                        step.set(Step::Idle);
                        error.set(Some(t("daybook.no_company")));
                    } else {
                        step.set(Step::Choose(me.companies));
                    }
                }
                Err(e) => {
                    step.set(Step::Idle);
                    error.set(Some(e));
                }
            }
        });
    };

    let cancel_start = cancel.clone();
    let start = move |_| {
        error.set(None);
        cancel_start.store(false, Ordering::Relaxed);
        let s = Session { server: server(), ..Default::default() };
        let flag = cancel_start.clone();
        spawn(async move {
            let s2 = s.clone();
            match background(move || s2.start_login()).await {
                Ok(link) => {
                    step.set(Step::Waiting(link.clone()));
                    let r = background(move || {
                        let mut s = s;
                        s.wait_for_approval(&link, flag).map(|_| s)
                    })
                    .await;
                    match r {
                        Ok(s) => after_login(s),
                        Err(e) => {
                            step.set(Step::Idle);
                            if e != "cancelled" {
                                error.set(Some(e));
                            }
                        }
                    }
                }
                Err(e) => error.set(Some(e)),
            }
        });
    };
    let cancel_wait = cancel.clone();

    let dev = move |_| {
        error.set(None);
        let tg: i64 = dev_id().trim().parse().unwrap_or(1001);
        let s = Session { server: server(), ..Default::default() };
        spawn(async move {
            let r = background(move || {
                let mut s = s;
                s.dev_login(tg).map(|_| s)
            })
            .await;
            match r {
                Ok(s) => after_login(s),
                Err(e) => error.set(Some(e)),
            }
        });
    };

    let sync_now = move |_| {
        let d = DB.peek().settings.daybook.clone();
        let Some(cid) = d.company_id else { return };
        step.set(Step::Syncing);
        let s = session_from_settings();
        spawn(async move {
            match sync_company(s, (cid, d.company_name.clone()), String::new()).await {
                Ok(_) => toast(t("daybook.synced"), "circle-check", "success"),
                Err(e) => error.set(Some(e)),
            }
            step.set(Step::Idle);
        });
    };

    let disconnect = move |_| {
        let server = DB.peek().settings.daybook.server.clone();
        mutate(|db| {
            db.settings.daybook = DaybookLink { server, ..Default::default() };
            db.log(crate::state::now(), "Daybook: disconnected", false);
        });
        toast(t("daybook.disconnected"), "unlink", "info");
    };

    let health_view = match health() {
        Some(Ok(h)) if h.ok => Some(("success", "circle-check", format!("{} · Daybook {}", t("daybook.server_ok"), h.version))),
        Some(Ok(h)) => Some(("warning", "triangle-alert", format!("{} · {}", t("daybook.server_degraded"), h.version))),
        Some(Err(e)) if e == "web" => Some(("info", "info", t("daybook.web_note"))),
        Some(Err(e)) => Some(("danger", "circle-x", format!("{}: {e}", t("daybook.server_error")))),
        None => None,
    };
    let err_text = error().map(|e| if e == "web" { t("daybook.web_note") } else if e == "denied" { t("daybook.denied") } else if e == "expired" { t("daybook.expired") } else { e });
    let now = now();
    let l = lang();
    let d = DB.read().settings.daybook.clone();
    let features: Vec<(&'static str, String)> = vec![
        ("store", t("daybook.f_branches")),
        ("pill", t("daybook.f_products")),
        ("hourglass", t("daybook.f_defektura")),
        ("building-2", t("daybook.f_customers")),
        ("square-check", t("daybook.f_tasks")),
        ("fingerprint", t("daybook.f_attendance")),
        ("sparkles", t("daybook.f_ai")),
    ];

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.daybook"), subtitle: t("daybook.subtitle"),
                Link { to: Route::SettingsPage {}, class: "btn ghost", Icon { name: "arrow-left", size: 16 } {t("nav.settings")} }
            }
            div { class: "grid-main",
                div { class: "stack gap-16",
                    if d.connected {
                        div { class: "card",
                            div { class: "card-body stack gap-16",
                                div { class: "row gap-12",
                                    span { class: "ic success lg", Icon { name: "circle-check", size: 22 } }
                                    div { class: "grow",
                                        div { class: "strong", style: "font-size: 17px", "{d.company_name}" }
                                        div { class: "small muted", {format!("{} · {} · {}", d.user_name, d.server, d.last_sync.map(|s| crm::fmt::relative(s, now, l)).unwrap_or_default())} }
                                    }
                                    Badge { text: t("common.daybook_connected"), tone: "success", dot: true }
                                }
                                div { class: "grid-3",
                                    for (icon, label, n) in vec![
                                        ("store", t("common.branches"), d.pulled.branches),
                                        ("users", t("nav.team"), d.pulled.staff),
                                        ("pill", t("nav.products"), d.pulled.products),
                                        ("building-2", t("nav.companies"), d.pulled.customers),
                                        ("hourglass", t("nav.waitlist"), d.pulled.defektura),
                                        ("square-check", t("daybook.tasks_pushed"), d.pulled.tasks_pushed),
                                    ] {
                                        div { key: "{label}", class: "card flat pad row gap-12",
                                            span { class: "ic muted sm", Icon { name: icon, size: 15 } }
                                            div { div { class: "kpi-value", style: "font-size: 20px", "{n}" } div { class: "xs muted", "{label}" } }
                                        }
                                    }
                                }
                                div { class: "row gap-8 wrap",
                                    button { class: "btn primary", disabled: step() == Step::Syncing, onclick: sync_now, Icon { name: "refresh-cw", size: 15 } {t("home.daybook_sync")} }
                                    button { class: "btn danger", onclick: disconnect, Icon { name: "unlink", size: 15 } {t("daybook.disconnect")} }
                                }
                            }
                        }
                    } else {
                        div { class: "card",
                            div { class: "card-head line",
                                div { class: "card-title", span { class: "badge accent sm", "1" } {t("daybook.step_server")} }
                            }
                            div { class: "card-body stack gap-12",
                                div { class: "row gap-8",
                                    input { class: "input", value: "{server}", placeholder: "https://…", oninput: move |e| server.set(e.value()) }
                                    button { class: "btn", disabled: checking(), onclick: check, Icon { name: "server", size: 15 } {t("daybook.check")} }
                                }
                                if let Some((tone, icon, text)) = health_view.clone() {
                                    div { class: "callout {tone}", Icon { name: icon, size: 16 } span { "{text}" } }
                                }
                            }
                            div { class: "card-head line", style: "border-top: 1px solid var(--c-border)",
                                div { class: "card-title", span { class: "badge accent sm", "2" } {t("daybook.step_signin")} }
                            }
                            div { class: "card-body stack gap-12",
                                match step() {
                                    Step::Waiting(link) => {
                                        let qr = daybook::qr_path(&link.deep_link);
                                        let deep = link.deep_link.clone();
                                        let code = link.match_code.clone();
                                        let bot = link.bot_username.clone();
                                        let cw = cancel_wait.clone();
                                        rsx! {
                                            div { class: "row top gap-16 wrap",
                                                if let Some((path, w)) = qr {
                                                    div { class: "qr",
                                                        svg { width: "176", height: "176", view_box: "-2 -2 {w + 4} {w + 4}", shape_rendering: "crispEdges",
                                                            rect { x: "-2", y: "-2", width: "{w + 4}", height: "{w + 4}", fill: "#fff" }
                                                            path { d: "{path}", fill: "#1c1916" }
                                                        }
                                                    }
                                                }
                                                div { class: "stack gap-8", style: "flex: 1 1 220px",
                                                    div { class: "small muted", {t("daybook.scan")} }
                                                    div { class: "row gap-8",
                                                        span { class: "small muted", {t("daybook.match")} }
                                                        span { class: "display", style: "font-size: 40px; color: var(--c-primary); line-height: 1", "{code}" }
                                                    }
                                                    a { class: "btn primary", href: "{deep}", target: "_blank", Icon { name: "send", size: 15 } {format!("@{bot}")} }
                                                    div { class: "row gap-8 small muted", span { class: "skeleton", style: "width: 14px; height: 14px; border-radius: 99px" } {t("daybook.waiting")} }
                                                    button { class: "btn ghost sm", style: "align-self: flex-start", onclick: move |_| { cw.store(true, Ordering::Relaxed); step.set(Step::Idle); }, {t("common.cancel")} }
                                                }
                                            }
                                        }
                                    }
                                    Step::Choose(list) => rsx! {
                                        div { class: "stack gap-8",
                                            span { class: "label", {t("daybook.choose_company")} }
                                            for (cid, cname) in list {
                                                button {
                                                    key: "{cid}",
                                                    class: "btn",
                                                    style: "justify-content: flex-start",
                                                    onclick: move |_| {
                                                        let s = session_from_settings();
                                                        let user = DB.peek().settings.daybook.user_name.clone();
                                                        let name = cname.clone();
                                                        step.set(Step::Syncing);
                                                        spawn(async move {
                                                            match sync_company(s, (cid, name), user).await {
                                                                Ok(_) => toast(t("daybook.synced"), "circle-check", "success"),
                                                                Err(e) => error.set(Some(e)),
                                                            }
                                                            step.set(Step::Idle);
                                                        });
                                                    },
                                                    Icon { name: "store", size: 15 }
                                                    "{cname}"
                                                }
                                            }
                                        }
                                    },
                                    Step::Syncing => rsx! {
                                        div { class: "row gap-8", span { class: "skeleton", style: "width: 18px; height: 18px; border-radius: 99px" } span { {t("daybook.syncing")} } }
                                    },
                                    Step::Idle => rsx! {
                                        p { class: "small muted", {t("daybook.signin_text")} }
                                        div { class: "row gap-8 wrap",
                                            button { class: "btn primary lg", onclick: start, Icon { name: "send", size: 17 } {t("daybook.signin")} }
                                        }
                                        if local {
                                            div { class: "callout", style: "flex-wrap: wrap",
                                                Icon { name: "key-round", size: 16 }
                                                span { class: "grow", {t("daybook.dev")} }
                                                input { class: "input sm num", style: "width: 110px", value: "{dev_id}", oninput: move |e| dev_id.set(e.value()) }
                                                button { class: "btn sm", onclick: dev, {t("daybook.dev_button")} }
                                            }
                                        }
                                    },
                                }
                                if let Some(e) = err_text.clone() {
                                    div { class: "callout danger", Icon { name: "circle-alert", size: 16 } span { "{e}" } }
                                }
                                if web {
                                    div { class: "callout", Icon { name: "info", size: 16 } span { {t("daybook.web_note")} } }
                                }
                            }
                        }
                    }
                }
                div { class: "stack gap-16",
                    div { class: "card pad stack gap-12",
                        div { class: "card-title", Icon { name: "link-2", size: 16, class: "tone-accent" } {t("daybook.what_syncs")} }
                        for (icon, text) in features {
                            div { key: "{icon}", class: "row top gap-8 small",
                                span { class: "ic accent sm", Icon { name: icon, size: 14 } }
                                span { style: "padding-top: 4px", "{text}" }
                            }
                        }
                    }
                    div { class: "card pad stack gap-8",
                        div { class: "card-title", Icon { name: "shield-check", size: 16, class: "tone-success" } {t("daybook.security")} }
                        p { class: "small muted", {t("daybook.security_text")} }
                    }
                }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("settings.subtitle", "Har bir kompaniya o‘zi uchun sozlaydi: qoidalar, voronkalar, AI byudjeti va maxfiylik.", "Каждая компания настраивает под себя: правила, воронки, бюджет AI и приватность.", "Every company tunes its own rules, pipelines, AI budget and privacy."),
    ("settings.appearance", "Ko‘rinish va kompaniya", "Внешний вид и компания", "Look and company"),
    ("settings.lang_hint", "O‘zbek tili lotin va kirill yozuvida", "Узбекский — латиница и кириллица", "Uzbek in Latin and Cyrillic script"),
    ("settings.compact", "Zich ko‘rinish", "Компактный вид", "Compact density"),
    ("settings.compact_hint", "Ekranga ko‘proq qator sig‘adi", "Больше строк на экране", "More rows on screen"),
    ("settings.privacy_hint", "Telefon raqamlari va sog‘liq ma’lumotlarini ekranda yashiradi", "Скрывает номера телефонов и данные о здоровье на экране", "Masks phone numbers and health data on screen"),
    ("settings.company_name", "Kompaniya nomi", "Название компании", "Company name"),
    ("settings.view_as", "Kim sifatida ko‘rish", "Смотреть как", "View as"),
    ("settings.view_as_hint", "Demo uchun: rolni almashtirib ko‘ring", "Для демо: переключите роль", "For the demo: switch the role"),
    ("settings.care", "Mijozlarga xizmat qoidalari", "Правила работы с клиентами", "Customer care rules"),
    ("settings.per_company", "Kompaniya sozlamasi", "Настройка компании", "Per company"),
    ("settings.refill_lead", "Dori eslatmasi oldindan", "Напоминать о лекарстве заранее", "Refill reminder lead time"),
    ("settings.refill_lead_hint", "Dori tugashidan necha kun oldin eslatiladi", "За сколько дней до окончания лекарства", "Days before the medicine runs out"),
    ("settings.inactive", "Mijoz «yo‘qolgan» hisoblanadi", "Клиент считается «уходящим»", "A customer counts as lapsing"),
    ("settings.inactive_hint", "Shuncha kun xarid qilmasa", "Если не покупал столько дней", "After this many days without a purchase"),
    ("settings.sla", "Murojaatga javob muddati", "Срок ответа на обращение", "Ticket response time"),
    ("settings.sla_hint", "Nojo‘ya ta’sirlar uchun har doim 4 soat", "Для нежелательных реакций всегда 4 часа", "Adverse reactions always get 4 hours"),
    ("settings.loyalty_hint", "Darajalar, keshbek va bonuslar", "Уровни, кешбэк и бонусы", "Tiers, cashback and bonuses"),
    ("settings.pipelines", "Bitim voronkalari", "Воронки сделок", "Deal pipelines"),
    ("settings.add_stage", "Bosqich qo‘shish", "Добавить этап", "Add stage"),
    ("settings.ai_model", "Model", "Модель", "Model"),
    ("settings.ai_haiku", "Claude Haiku 5.5 · tavsiya, arzon", "Claude Haiku 5.5 · рекомендуется, недорого", "Claude Haiku 5.5 · recommended, low cost"),
    ("settings.ai_sonnet", "Claude Sonnet 5.5 · past effort, qimmatroq", "Claude Sonnet 5.5 · low effort, дороже", "Claude Sonnet 5.5 · low effort, costs more"),
    ("settings.ai_spent", "Shu oy sarflandi", "Потрачено в этом месяце", "Spent this month"),
    ("settings.ai_requests", "so‘rov", "запросов", "requests"),
    ("settings.ai_cap", "Oylik limit, $", "Лимит в месяц, $", "Monthly cap, $"),
    ("settings.ai_reply", "Javob qoralamasi", "Черновик ответа", "Reply draft"),
    ("settings.ai_summary", "Mijoz xulosasi", "Сводка по клиенту", "Customer summary"),
    ("settings.ai_segment", "Savoldan segment", "Сегмент из вопроса", "Segment from a question"),
    ("settings.ai_compliance", "Matnni tekshirish", "Проверка текста", "Compliance check"),
    ("settings.ai_note", "AI Daybook kaliti orqali ishlaydi va kompaniya limitidan oshmaydi. Dozalash bo‘yicha maslahat bermaydi.", "AI работает через ключ Daybook и не превышает лимит компании. Не даёт советов по дозировкам.", "The AI runs on Daybook's key and stays inside the company cap. It never gives dosage advice."),
    ("settings.data", "Ma’lumotlar va maxfiylik", "Данные и приватность", "Data and privacy"),
    ("settings.import_hint", "CSV yoki Excel faylini tanlang: mijozlar, telefonlar, ballar", "Выберите CSV или Excel: клиенты, телефоны, баллы", "Pick a CSV or Excel file: customers, phones, points"),
    ("settings.exported", "Eksport tayyor", "Экспорт готов", "Export ready"),
    ("settings.privacy_note", "Sog‘liq ma’lumotlari faqat mijoz roziligi bilan saqlanadi, har bir ko‘rish jurnalga yoziladi.", "Данные о здоровье хранятся только с согласия клиента, каждый просмотр записывается в журнал.", "Health data is kept only with the customer’s consent, and every view is logged."),
    ("settings.audit", "Harakatlar jurnali", "Журнал действий", "Audit log"),
    ("settings.sensitive", "Maxfiy", "Конфиденциально", "Sensitive"),
    ("settings.reset_text", "Hamma demo ma’lumotlar bugungi sana bilan qaytadan yaratiladi. Til va mavzu saqlanib qoladi.", "Все демо-данные будут созданы заново на сегодняшнюю дату. Язык и тема сохранятся.", "All demo data is rebuilt as of today. Your language and theme stay."),
    ("settings.version", "Versiya", "Версия", "Version"),
    ("settings.platform", "Platforma", "Платформа", "Platform"),
    ("settings.engine", "Texnologiya", "Технология", "Built with"),
    ("settings.storage", "Ma’lumotlar", "Данные", "Data"),
    ("settings.storage_value", "Qurilmada, oflayn ishlaydi", "На устройстве, работает офлайн", "On this device, works offline"),
    ("settings.manage_connection", "Ulanishni boshqarish", "Управлять подключением", "Manage connection"),
    ("daybook.subtitle", "CRM’ni Daybook’dagi kompaniyangizga ulang: filiallar, xodimlar, dorilar va vazifalar bir joyda.", "Подключите CRM к вашей компании в Daybook: филиалы, сотрудники, лекарства и задачи в одном месте.", "Link the CRM to your Daybook company: branches, staff, medicines and tasks in one place."),
    ("daybook.step_server", "Daybook serveri", "Сервер Daybook", "Daybook server"),
    ("daybook.check", "Tekshirish", "Проверить", "Check"),
    ("daybook.server_ok", "Server ishlayapti", "Сервер работает", "Server is up"),
    ("daybook.server_degraded", "Server javob berdi, lekin ba’zi qismlar ishlamayapti", "Сервер ответил, но часть сервисов не работает", "Server answered, but some parts are down"),
    ("daybook.server_error", "Serverga ulanib bo‘lmadi", "Не удалось подключиться к серверу", "Couldn’t reach the server"),
    ("daybook.step_signin", "Telegram orqali kirish", "Вход через Telegram", "Sign in with Telegram"),
    ("daybook.signin_text", "Parol kerak emas: Daybook botida tasdiqlaysiz. Ekrandagi raqamni botdagisi bilan solishtiring.", "Пароль не нужен: вы подтверждаете вход в боте Daybook. Сверьте число на экране с числом в боте.", "No password: you approve in the Daybook bot. Match the number on screen with the one in the bot."),
    ("daybook.signin", "Telegram bilan kirish", "Войти через Telegram", "Sign in with Telegram"),
    ("daybook.scan", "Telefon kamerasi bilan QR kodni skanerlang yoki tugmani bosing.", "Отсканируйте QR-код камерой телефона или нажмите кнопку.", "Scan the QR code with your phone camera or tap the button."),
    ("daybook.match", "Botda shu raqamni bosing:", "Нажмите в боте это число:", "Tap this number in the bot:"),
    ("daybook.waiting", "Tasdiqlash kutilmoqda…", "Ждём подтверждения…", "Waiting for approval…"),
    ("daybook.choose_company", "Kompaniyani tanlang", "Выберите компанию", "Choose the company"),
    ("daybook.syncing", "Ma’lumotlar olinmoqda…", "Загружаем данные…", "Pulling your data…"),
    ("daybook.synced", "Daybook bilan sinxronlandi", "Синхронизировано с Daybook", "Synced with Daybook"),
    ("daybook.disconnect", "Uzish", "Отключить", "Disconnect"),
    ("daybook.disconnected", "Daybook’dan uzildi", "Daybook отключён", "Disconnected from Daybook"),
    ("daybook.no_company", "Bu akkauntda kompaniya topilmadi", "В этом аккаунте нет компаний", "This account has no company"),
    ("daybook.denied", "Kirish botda rad etildi", "Вход отклонён в боте", "The sign-in was declined in the bot"),
    ("daybook.expired", "Havola muddati tugadi, qaytadan urinib ko‘ring", "Ссылка устарела, попробуйте ещё раз", "The link expired, try again"),
    ("daybook.dev", "Lokal server: dasturchi kirishi (Telegram ID)", "Локальный сервер: вход разработчика (Telegram ID)", "Local server: developer sign-in (Telegram ID)"),
    ("daybook.dev_button", "Kirish", "Войти", "Sign in"),
    ("daybook.web_note", "Brauzerdagi demo serverga to‘g‘ridan-to‘g‘ri ulanmaydi: Windows va Android ilovalari ulanadi.", "Веб-демо не подключается к серверу напрямую: подключаются приложения для Windows и Android.", "The browser demo can’t reach the server directly; the Windows and Android apps can."),
    ("daybook.tasks_pushed", "Yuborilgan vazifalar", "Отправлено задач", "Tasks sent"),
    ("daybook.what_syncs", "Nimalar sinxronlanadi", "Что синхронизируется", "What syncs"),
    ("daybook.f_branches", "Filiallar va xodimlar (rollar bilan)", "Филиалы и сотрудники (с ролями)", "Branches and staff, with roles"),
    ("daybook.f_products", "Dorilar katalogi, narxlar va qoldiqlar", "Каталог лекарств, цены и остатки", "Medicine catalogue, prices and stock"),
    ("daybook.f_defektura", "Defektura: kelgan dorilar mijozga avtomatik xabar qilinadi", "Дефектура: о поступлении клиенту сообщат автоматически", "Waitlist: customers hear when their medicine arrives"),
    ("daybook.f_customers", "Korporativ mijozlar va ularning qarzlari", "Корпоративные клиенты и их долги", "B2B customers and what they owe"),
    ("daybook.f_tasks", "CRM vazifalari Daybook vazifalariga tushadi", "Задачи из CRM попадают в задачи Daybook", "CRM tasks land in Daybook tasks"),
    ("daybook.f_attendance", "Kim smenada: Face ID davomatidan", "Кто на смене: из Face ID учёта", "Who is on shift, from Face ID attendance"),
    ("daybook.f_ai", "AI byudjeti kompaniya bilan umumiy", "Бюджет AI общий с компанией", "One shared AI budget"),
    ("daybook.security", "Xavfsizlik", "Безопасность", "Security"),
    ("daybook.security_text", "Kirish Telegram’da raqamni solishtirib tasdiqlanadi. Kalitlar faqat shu qurilmada saqlanadi; seansni Daybook’da istalgan payt bekor qilish mumkin.", "Вход подтверждается в Telegram сверкой числа. Ключи хранятся только на этом устройстве; сеанс можно отозвать в Daybook в любой момент.", "Sign-in is confirmed in Telegram by matching a number. Keys stay on this device, and the session can be revoked from Daybook any time."),
];
