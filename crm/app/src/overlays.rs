//! Overlays shared by every screen: the command palette, notifications, quick add, toasts
//! and the first-run welcome.

use chrono::{Duration, NaiveDateTime};
use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::shell::NAV;
use crate::state::{go, lang, money_short, mutate, now, t, toast, tr, QuickAdd, DB, UI};
use crate::ui::{Icon, Modal, Segmented};

// ---------------------------------------------------------------- command palette

#[derive(Clone, PartialEq, Debug)]
enum PAction {
    Go(String),
    Ai,
    Quick(QuickAdd),
    Theme,
    Lang(Lang),
    Privacy,
    Reset,
}

#[derive(Clone, PartialEq, Debug)]
struct PItem {
    group: String,
    icon: &'static str,
    tone: &'static str,
    title: String,
    subtitle: String,
    action: PAction,
}

fn palette_items(q: &str) -> Vec<PItem> {
    let ql = q.trim().to_lowercase();
    let mut out = Vec::new();
    let pages = t("palette.pages");
    for (_, items) in NAV {
        for i in items.iter() {
            let title = t(i.key);
            if ql.is_empty() || title.to_lowercase().contains(&ql) {
                out.push(PItem {
                    group: pages.clone(),
                    icon: i.icon,
                    tone: "muted",
                    title,
                    subtitle: String::new(),
                    action: PAction::Go((i.route)().to_string()),
                });
            }
        }
    }
    let actions = t("palette.actions");
    let acts: Vec<(&'static str, String, PAction)> = vec![
        ("sparkles", t("assistant.title"), PAction::Ai),
        ("user-plus", t("palette.new_customer"), PAction::Quick(QuickAdd::Customer)),
        ("square-kanban", t("palette.new_deal"), PAction::Quick(QuickAdd::Deal)),
        ("square-check", t("palette.new_task"), PAction::Quick(QuickAdd::Task)),
        ("magnet", t("palette.new_lead"), PAction::Quick(QuickAdd::Lead)),
        ("life-buoy", t("palette.new_ticket"), PAction::Quick(QuickAdd::Ticket)),
        ("moon", t("palette.toggle_theme"), PAction::Theme),
        ("eye-off", t("common.privacy_mode"), PAction::Privacy),
        ("languages", "O‘zbekcha".into(), PAction::Lang(Lang::Uz)),
        ("languages", "Ўзбекча".into(), PAction::Lang(Lang::UzCyrl)),
        ("languages", "Русский".into(), PAction::Lang(Lang::Ru)),
        ("languages", "English".into(), PAction::Lang(Lang::En)),
        ("rotate-ccw", t("common.reset_demo"), PAction::Reset),
    ];
    for (icon, title, action) in acts {
        if ql.is_empty() || title.to_lowercase().contains(&ql) {
            out.push(PItem { group: actions.clone(), icon, tone: "accent", title, subtitle: String::new(), action });
        }
    }
    if !ql.is_empty() {
        let results = t("palette.results");
        let db = DB.read();
        for h in db.search(q, 14) {
            out.insert(
                0,
                PItem { group: results.clone(), icon: h.icon, tone: "info", title: h.title, subtitle: h.subtitle, action: PAction::Go(h.route) },
            );
        }
        // results first, in their original order
        let n = out.iter().filter(|i| i.group == results).count();
        out[..n].reverse();
    }
    out
}

fn run(action: PAction) {
    UI.write().palette = false;
    match action {
        PAction::Go(r) => go(&r),
        PAction::Ai => UI.write().ai_panel = true,
        PAction::Quick(k) => UI.write().quick_add = Some(k),
        PAction::Theme => mutate(|db| {
            db.settings.theme = match db.settings.theme {
                Theme::Dark => Theme::Light,
                _ => Theme::Dark,
            }
        }),
        PAction::Lang(l) => mutate(|db| db.settings.lang = l),
        PAction::Privacy => mutate(|db| db.settings.privacy_mode = !db.settings.privacy_mode),
        PAction::Reset => {
            mutate(|db| {
                let fresh = crate::storage::reset(db);
                *db = fresh;
            });
            toast(t("palette.reset_done"), "rotate-ccw", "success");
        }
    }
}

#[component]
pub fn Palette() -> Element {
    let mut q = use_signal(String::new);
    let mut sel = use_signal(|| 0usize);
    let items = use_memo(move || palette_items(&q()));
    let list = items();
    let count = list.len();
    let cur = sel().min(count.saturating_sub(1));
    let mut last_group = String::new();
    let rows: Vec<(usize, PItem, bool)> = list
        .iter()
        .cloned()
        .enumerate()
        .map(|(i, it)| {
            let head = it.group != last_group;
            last_group = it.group.clone();
            (i, it, head)
        })
        .collect();
    rsx! {
        div { class: "overlay", onclick: move |_| UI.write().palette = false }
        div { class: "palette", role: "dialog",
            div { class: "palette-input",
                Icon { name: "search", size: 19, class: "subtle" }
                input {
                    value: "{q}",
                    placeholder: t("common.search_hint"),
                    oninput: move |e| {
                        q.set(e.value());
                        sel.set(0);
                    },
                    onmounted: move |e| async move {
                        let _ = e.set_focus(true).await;
                    },
                    onkeydown: move |e: KeyboardEvent| {
                        match e.key() {
                            Key::ArrowDown => {
                                e.prevent_default();
                                sel.set((cur + 1).min(count.saturating_sub(1)));
                            }
                            Key::ArrowUp => {
                                e.prevent_default();
                                sel.set(cur.saturating_sub(1));
                            }
                            Key::Enter => {
                                if let Some(it) = items.peek().get(cur).cloned() {
                                    run(it.action);
                                }
                            }
                            _ => {}
                        }
                    },
                }
                span { class: "kbd", "Esc" }
            }
            div { class: "palette-list",
                if rows.is_empty() {
                    div { class: "empty", style: "padding: 28px", {t("common.no_results")} }
                }
                for (i, it, head) in rows {
                    div { key: "{i}", style: "display: contents",
                    if head { div { class: "palette-group upper subtle", "{it.group}" } }
                    div {
                        class: if i == cur { "palette-item hi" } else { "palette-item" },
                        onmouseenter: move |_| sel.set(i),
                        onclick: {
                            let a = it.action.clone();
                            move |_| run(a.clone())
                        },
                        span { class: "ic {it.tone}", Icon { name: it.icon, size: 16 } }
                        div { class: "grow",
                            div { class: "strong truncate", "{it.title}" }
                            if !it.subtitle.is_empty() { div { class: "xs muted truncate", "{it.subtitle}" } }
                        }
                        if i == cur { Icon { name: "arrow-right", size: 15, class: "subtle" } }
                    }
                    }
                }
            }
            div { class: "palette-foot",
                span { span { class: "kbd", "↑↓" } " " {t("palette.move")} }
                span { span { class: "kbd", "Enter" } " " {t("palette.open")} }
                span { class: "spacer" }
                span { "Daybook CRM" }
            }
        }
    }
}

// ---------------------------------------------------------------- notifications

fn notif_icon(k: NotifKind) -> (&'static str, &'static str) {
    match k {
        NotifKind::Lead => ("magnet", "accent"),
        NotifKind::Message => ("message-circle", "info"),
        NotifKind::Task => ("square-check", "muted"),
        NotifKind::Deal => ("trophy", "success"),
        NotifKind::Ticket => ("triangle-alert", "danger"),
        NotifKind::Refill => ("repeat", "accent"),
        NotifKind::Waitlist => ("package-check", "success"),
        NotifKind::System => ("crown", "warning"),
    }
}

#[component]
pub fn NotificationsPanel() -> Element {
    let now = now();
    let l = lang();
    let list: Vec<Notification> = DB.read().notifications.clone();
    rsx! {
        div { style: "position: fixed; inset: 0; z-index: 61", onclick: move |_| UI.write().notifications = false }
        div { class: "notif-panel",
            div { class: "pane-head",
                div { class: "strong grow", {t("common.notifications")} }
                button { class: "btn ghost sm", onclick: move |_| mutate(|db| db.notifications.iter_mut().for_each(|n| n.read = true)),
                    Icon { name: "check-check", size: 15 }
                    {t("common.mark_all_read")}
                }
            }
            div { class: "pane-body",
                if list.is_empty() {
                    crate::ui::Empty { icon: "bell-off", title: t("common.empty") }
                }
                for n in list {
                    {
                        let (icon, tone) = notif_icon(n.kind);
                        let title = match n.kind {
                            NotifKind::Refill => match l {
                                Lang::Ru => format!("У {} клиентов заканчиваются лекарства", n.title),
                                Lang::En => format!("{} customers are running out of medicine", n.title),
                                _ => crate::state::uz(format!("{} ta mijozning dorisi tugayapti", n.title)),
                            },
                            _ => n.title.clone(),
                        };
                        let body = if n.body.starts_with("tier.") { format!("{} → {}", tr("Yangi daraja", "Новый уровень", "New tier"), t(&n.body)) } else { n.body.clone() };
                        let when = crm::fmt::relative(n.at, now, l);
                        let id = n.id;
                        let route = n.route.clone();
                        rsx! {
                            div {
                                key: "{id}",
                                class: if n.read { "notif" } else { "notif unread" },
                                onclick: move |_| {
                                    mutate(|db| if let Some(x) = db.notifications.iter_mut().find(|x| x.id == id) { x.read = true });
                                    UI.write().notifications = false;
                                    go(&route);
                                },
                                span { class: "ic {tone} sm", Icon { name: icon, size: 15 } }
                                div { class: "grow",
                                    div { class: "row between",
                                        span { class: "xs upper subtle", {t(n.kind.key())} }
                                        span { class: "xs subtle", "{when}" }
                                    }
                                    div { class: "strong small clamp-2", "{title}" }
                                    if !body.is_empty() { div { class: "small muted clamp-2", "{body}" } }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- toasts

#[component]
pub fn Toasts() -> Element {
    let toasts = UI.read().toasts.clone();
    rsx! {
        div { class: "toasts",
            for tst in toasts {
                div {
                    key: "{tst.id}",
                    class: "toast",
                    onclick: move |_| UI.write().toasts.retain(|x| x.id != tst.id),
                    span { class: "ic", Icon { name: tst.icon, size: 15 } }
                    span { "{tst.text}" }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- quick add

fn parse_dt(v: &str) -> Option<NaiveDateTime> {
    NaiveDateTime::parse_from_str(v, "%Y-%m-%dT%H:%M").ok()
}

#[component]
pub fn QuickAddModal(kind: QuickAdd) -> Element {
    let close = move |_| UI.write().quick_add = None;
    let kinds: Vec<(String, String)> = vec![
        ("customer".into(), t("common.customer")),
        ("deal".into(), t("common.deal")),
        ("task".into(), t("common.task")),
        ("lead".into(), t("common.lead")),
        ("ticket".into(), t("common.ticket")),
    ];
    let cur = match kind {
        QuickAdd::Customer => "customer",
        QuickAdd::Deal => "deal",
        QuickAdd::Task => "task",
        QuickAdd::Lead => "lead",
        QuickAdd::Ticket => "ticket",
    };
    rsx! {
        Modal { title: t("common.quick_add"), onclose: close,
            div { class: "modal-body",
                div { style: "overflow-x:auto",
                    Segmented {
                        options: kinds,
                        value: cur.to_string(),
                        onchange: move |v: String| {
                            UI.write().quick_add = Some(match v.as_str() {
                                "deal" => QuickAdd::Deal,
                                "task" => QuickAdd::Task,
                                "lead" => QuickAdd::Lead,
                                "ticket" => QuickAdd::Ticket,
                                _ => QuickAdd::Customer,
                            })
                        },
                    }
                }
                match kind {
                    QuickAdd::Customer => rsx! { NewCustomer {} },
                    QuickAdd::Deal => rsx! { NewDeal {} },
                    QuickAdd::Task => rsx! { NewTask {} },
                    QuickAdd::Lead => rsx! { NewLead {} },
                    QuickAdd::Ticket => rsx! { NewTicket {} },
                }
            }
        }
    }
}

#[component]
fn NewCustomer() -> Element {
    let mut first = use_signal(String::new);
    let mut last = use_signal(String::new);
    let mut phone = use_signal(|| "+998 ".to_string());
    let mut branch = use_signal(|| DB.peek().branches.first().map(|b| b.id).unwrap_or(0));
    let mut tg = use_signal(|| true);
    let mut sms = use_signal(|| true);
    let branches: Vec<(Id, String)> = DB.read().branches.iter().map(|b| (b.id, b.name.clone())).collect();
    let digits = phone().chars().filter(|c| c.is_ascii_digit()).count();
    let dup = {
        let p: String = phone().chars().filter(|c| c.is_ascii_digit()).collect();
        if p.len() >= 12 { DB.read().customers.iter().find(|c| c.phone == p).map(|c| (c.id, c.name())) } else { None }
    };
    let valid = !first().trim().is_empty() && digits >= 12 && dup.is_none();
    let save = move |_| {
        if !valid {
            return;
        }
        let now = now();
        let mut new_id = 0;
        mutate(|db| {
            let id = db.new_id();
            new_id = id;
            let bonus = db.settings.loyalty.welcome_bonus;
            let me = db.settings.me;
            let p: String = phone().chars().filter(|c| c.is_ascii_digit()).collect();
            db.customers.insert(
                0,
                Customer {
                    id,
                    first_name: first().trim().to_string(),
                    last_name: last().trim().to_string(),
                    gender: Gender::Female,
                    phone: p,
                    telegram: None,
                    birth_date: None,
                    district: String::new(),
                    home_branch: branch(),
                    owner_id: Some(me),
                    tags: vec![],
                    tier: Tier::Bronze,
                    points: bonus,
                    card_no: format!("7801 {:04} {:04}", id % 10_000, (id * 7) % 10_000),
                    source: Source::WalkIn,
                    consent: Consent { sms: sms(), telegram: tg(), health_data: false, given_on: Some(now.date()) },
                    regimens: vec![],
                    allergies: vec![],
                    company_id: None,
                    created: now.date(),
                    lang: Lang::Uz,
                    notes: String::new(),
                    nps: None,
                    total_spent: 0,
                    orders: 0,
                    first_purchase: None,
                    last_purchase: None,
                    archived: false,
                    referred_by: None,
                },
            );
            db.give_points(id, 0, TxKind::Bonus, "", now);
            db.log(now, format!("+ {} {}", first(), last()), false);
        });
        UI.write().quick_add = None;
        toast(t("quick.customer_saved"), "user-check", "success");
        go(&format!("/contacts/{new_id}"));
    };
    rsx! {
        div { class: "grid-2",
            div { class: "field", label { class: "label", {t("quick.first_name")} }
                input { class: "input", value: "{first}", oninput: move |e| first.set(e.value()), onmounted: move |e| async move { let _ = e.set_focus(true).await; } }
            }
            div { class: "field", label { class: "label", {t("quick.last_name")} }
                input { class: "input", value: "{last}", oninput: move |e| last.set(e.value()) }
            }
        }
        div { class: "grid-2",
            div { class: "field", label { class: "label", {t("common.phone")} }
                input { class: "input num", r#type: "tel", value: "{phone}", oninput: move |e| phone.set(e.value()) }
                if let Some((id, name)) = dup.clone() {
                    div { class: "hint tone-warning row gap-4",
                        Icon { name: "triangle-alert", size: 13 }
                        span { {t("quick.duplicate")} " " }
                        Link { to: crate::routes::Route::ContactDetail { id }, class: "strong", onclick: move |_| UI.write().quick_add = None, "{name}" }
                    }
                }
            }
            div { class: "field", label { class: "label", {t("common.branch")} }
                select { class: "select", onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                    for (id, name) in branches { option { key: "{id}", value: "{id}", selected: id == branch(), "{name}" } }
                }
            }
        }
        div { class: "stack gap-8",
            label { class: "check", input { r#type: "checkbox", checked: tg(), onchange: move |e| tg.set(e.checked()) } {t("field.consent_telegram")} }
            label { class: "check", input { r#type: "checkbox", checked: sms(), onchange: move |e| sms.set(e.checked()) } {t("field.consent_sms")} }
        }
        div { class: "callout accent", Icon { name: "gift", size: 16 } span { {t("quick.welcome_bonus")} } }
        div { class: "modal-foot",
            button { class: "btn ghost", onclick: move |_| UI.write().quick_add = None, {t("common.cancel")} }
            button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
        }
    }
}

#[component]
fn NewDeal() -> Element {
    let mut title = use_signal(String::new);
    let mut value = use_signal(|| "10000000".to_string());
    let (pipes, companies) = {
        let db = DB.read();
        (
            db.pipelines.iter().map(|p| (p.id, p.name.clone())).collect::<Vec<_>>(),
            db.companies.iter().filter(|c| c.kind != OrgKind::Distributor).map(|c| (c.id, c.name.clone())).collect::<Vec<_>>(),
        )
    };
    let mut pipe = use_signal(|| DB.peek().pipelines.first().map(|p| p.id).unwrap_or(0));
    let mut company = use_signal(|| 0u32);
    let v: i64 = value().chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse().unwrap_or(0);
    let valid = !title().trim().is_empty() && v > 0;
    let save = move |_| {
        if !valid {
            return;
        }
        let now = now();
        let mut new_id = 0;
        mutate(|db| {
            let id = db.new_id();
            new_id = id;
            let stage = db.pipeline(pipe()).and_then(|p| p.stages.first()).map(|s| s.id).unwrap_or(0);
            let me = db.settings.me;
            db.deals.push(Deal {
                id,
                title: title().trim().to_string(),
                pipeline_id: pipe(),
                stage_id: stage,
                company_id: if company() == 0 { None } else { Some(company()) },
                customer_id: None,
                value: v,
                owner_id: me,
                created: now,
                stage_since: now,
                last_activity: now,
                expected_close: now.date() + Duration::days(30),
                status: DealStatus::Open,
                lost_reason: None,
                lines: vec![],
                source: Source::Call,
                tags: vec![],
                next_step: String::new(),
                closed_at: None,
                priority: Priority::Normal,
            });
            db.log(now, format!("+ {}", title()), false);
        });
        UI.write().quick_add = None;
        toast(t("quick.deal_saved"), "square-kanban", "success");
        go(&format!("/deals/{new_id}"));
    };
    rsx! {
        div { class: "field", label { class: "label", {t("quick.deal_title")} }
            input { class: "input", value: "{title}", placeholder: t("quick.deal_title_hint"), oninput: move |e| title.set(e.value()), onmounted: move |e| async move { let _ = e.set_focus(true).await; } }
        }
        div { class: "grid-2",
            div { class: "field", label { class: "label", {t("common.company")} }
                select { class: "select", onchange: move |e| company.set(e.value().parse().unwrap_or(0)),
                    option { value: "0", "—" }
                    for (id, name) in companies { option { key: "{id}", value: "{id}", "{name}" } }
                }
            }
            div { class: "field", label { class: "label", {t("quick.pipeline")} }
                select { class: "select", onchange: move |e| pipe.set(e.value().parse().unwrap_or(0)),
                    for (id, name) in pipes { option { key: "{id}", value: "{id}", selected: id == pipe(), "{name}" } }
                }
            }
        }
        div { class: "field", label { class: "label", {t("common.value")} }
            input { class: "input num", inputmode: "numeric", value: "{value}", oninput: move |e| value.set(e.value()) }
            div { class: "hint", "{money_short(v)}" }
        }
        div { class: "modal-foot",
            button { class: "btn ghost", onclick: move |_| UI.write().quick_add = None, {t("common.cancel")} }
            button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.create")} }
        }
    }
}

#[component]
fn NewTask() -> Element {
    let start = (now() + Duration::hours(1)).format("%Y-%m-%dT%H:00").to_string();
    let mut title = use_signal(String::new);
    let mut due = use_signal(move || start.clone());
    let mut kind = use_signal(|| ActivityKind::Call);
    let mut to_daybook = use_signal(|| true);
    let valid = !title().trim().is_empty() && parse_dt(&due()).is_some();
    let save = move |_| {
        let Some(d) = parse_dt(&due()) else { return };
        if title().trim().is_empty() {
            return;
        }
        mutate(|db| {
            let me = db.settings.me;
            db.add_activity(Activity {
                id: 0,
                kind: kind(),
                title: title().trim().to_string(),
                notes: String::new(),
                due: d,
                done: false,
                done_at: None,
                owner_id: me,
                customer_id: None,
                company_id: None,
                deal_id: None,
                ticket_id: None,
                priority: Priority::Normal,
                outcome: None,
                duration_min: 15,
                daybook_task: if to_daybook() && db.settings.daybook.connected { Some(0) } else { None },
            });
        });
        UI.write().quick_add = None;
        toast(t("quick.task_saved"), "square-check", "success");
    };
    rsx! {
        div { class: "field", label { class: "label", {t("quick.task_title")} }
            input { class: "input", value: "{title}", oninput: move |e| title.set(e.value()), onmounted: move |e| async move { let _ = e.set_focus(true).await; } }
        }
        div { class: "grid-2",
            div { class: "field", label { class: "label", {t("quick.kind")} }
                select { class: "select", onchange: move |e| kind.set(ActivityKind::from_slug(&e.value()).unwrap_or(ActivityKind::Task)),
                    for k in ActivityKind::ALL.iter().copied() { option { key: "{k.slug()}", value: "{k.slug()}", selected: k == kind(), {t(k.key())} } }
                }
            }
            div { class: "field", label { class: "label", {t("quick.due")} }
                input { class: "input", r#type: "datetime-local", value: "{due}", oninput: move |e| due.set(e.value()) }
            }
        }
        label { class: "check", input { r#type: "checkbox", checked: to_daybook(), onchange: move |e| to_daybook.set(e.checked()) } {t("quick.to_daybook")} }
        div { class: "modal-foot",
            button { class: "btn ghost", onclick: move |_| UI.write().quick_add = None, {t("common.cancel")} }
            button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.create")} }
        }
    }
}

#[component]
fn NewLead() -> Element {
    let mut name = use_signal(String::new);
    let mut phone = use_signal(|| "+998 ".to_string());
    let mut interest = use_signal(String::new);
    let mut channel = use_signal(|| Channel::Telegram);
    let valid = !name().trim().is_empty();
    let save = move |_| {
        if !valid {
            return;
        }
        let now = now();
        mutate(|db| {
            let id = db.new_id();
            db.leads.insert(
                0,
                Lead {
                    id,
                    name: name().trim().to_string(),
                    phone: phone().chars().filter(|c| c.is_ascii_digit()).collect(),
                    channel: channel(),
                    message: interest(),
                    interest: interest(),
                    at: now,
                    status: LeadStatus::New,
                    owner_id: None,
                    score: 50,
                    company_name: None,
                    estimate: 0,
                    converted_customer: None,
                    converted_deal: None,
                },
            );
            db.notify(now, NotifKind::Lead, name(), interest(), "/leads");
        });
        UI.write().quick_add = None;
        toast(t("quick.lead_saved"), "magnet", "success");
        go("/leads");
    };
    rsx! {
        div { class: "grid-2",
            div { class: "field", label { class: "label", {t("common.name")} }
                input { class: "input", value: "{name}", oninput: move |e| name.set(e.value()), onmounted: move |e| async move { let _ = e.set_focus(true).await; } }
            }
            div { class: "field", label { class: "label", {t("common.phone")} }
                input { class: "input num", r#type: "tel", value: "{phone}", oninput: move |e| phone.set(e.value()) }
            }
        }
        div { class: "grid-2",
            div { class: "field", label { class: "label", {t("quick.channel")} }
                select { class: "select", onchange: move |e| channel.set(Channel::from_slug(&e.value()).unwrap_or(Channel::Telegram)),
                    for c in Channel::ALL.iter().copied() { option { key: "{c.slug()}", value: "{c.slug()}", selected: c == channel(), {t(c.key())} } }
                }
            }
            div { class: "field", label { class: "label", {t("quick.interest")} }
                input { class: "input", value: "{interest}", oninput: move |e| interest.set(e.value()) }
            }
        }
        div { class: "modal-foot",
            button { class: "btn ghost", onclick: move |_| UI.write().quick_add = None, {t("common.cancel")} }
            button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.create")} }
        }
    }
}

#[component]
fn NewTicket() -> Element {
    let mut subject = use_signal(String::new);
    let mut desc = use_signal(String::new);
    let mut kind = use_signal(|| TicketKind::Complaint);
    let mut customer = use_signal(|| 0u32);
    let customers: Vec<(Id, String)> = DB.read().customers.iter().take(80).map(|c| (c.id, c.name())).collect();
    let valid = !subject().trim().is_empty();
    let save = move |_| {
        if !valid {
            return;
        }
        let now = now();
        let mut new_id = 0;
        mutate(|db| {
            let id = db.new_id();
            new_id = id;
            let hours = if kind() == TicketKind::AdverseReaction { 4 } else { db.settings.sla_hours as i64 };
            let number = format!("MRJ-{}", 1031 + db.tickets.len());
            let branch = db.customer(customer()).map(|c| c.home_branch);
            db.tickets.insert(
                0,
                Ticket {
                    id,
                    number: number.clone(),
                    kind: kind(),
                    subject: subject().trim().to_string(),
                    description: desc(),
                    customer_id: if customer() == 0 { None } else { Some(customer()) },
                    product_id: None,
                    batch: None,
                    branch_id: branch,
                    priority: if kind() == TicketKind::AdverseReaction { Priority::Urgent } else { Priority::Normal },
                    status: TicketStatus::New,
                    created: now,
                    due: now + Duration::hours(hours),
                    assigned_to: None,
                    resolved: None,
                    csat: None,
                    comments: vec![],
                    reported_to_regulator: false,
                },
            );
            db.notify(now, NotifKind::Ticket, number, subject(), format!("/tickets/{id}"));
        });
        UI.write().quick_add = None;
        toast(t("quick.ticket_saved"), "life-buoy", "success");
        go(&format!("/tickets/{new_id}"));
    };
    rsx! {
        div { class: "grid-2",
            div { class: "field", label { class: "label", {t("quick.kind")} }
                select { class: "select", onchange: move |e| kind.set(TicketKind::from_slug(&e.value()).unwrap_or(TicketKind::Complaint)),
                    for k in TicketKind::ALL.iter().copied() { option { key: "{k.slug()}", value: "{k.slug()}", selected: k == kind(), {t(k.key())} } }
                }
            }
            div { class: "field", label { class: "label", {t("common.customer")} }
                select { class: "select", onchange: move |e| customer.set(e.value().parse().unwrap_or(0)),
                    option { value: "0", "—" }
                    for (id, name) in customers { option { key: "{id}", value: "{id}", "{name}" } }
                }
            }
        }
        if kind() == TicketKind::AdverseReaction {
            div { class: "callout danger", Icon { name: "triangle-alert", size: 16 } span { {t("quick.adverse_hint")} } }
        }
        div { class: "field", label { class: "label", {t("quick.subject")} }
            input { class: "input", value: "{subject}", oninput: move |e| subject.set(e.value()), onmounted: move |e| async move { let _ = e.set_focus(true).await; } }
        }
        div { class: "field", label { class: "label", {t("common.description")} }
            textarea { class: "textarea", value: "{desc}", oninput: move |e| desc.set(e.value()) }
        }
        div { class: "modal-foot",
            button { class: "btn ghost", onclick: move |_| UI.write().quick_add = None, {t("common.cancel")} }
            button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.create")} }
        }
    }
}

// ---------------------------------------------------------------- welcome

#[component]
pub fn Onboarding() -> Element {
    let cur = lang();
    let (company, customers, branches) = {
        let db = DB.read();
        (db.settings.company_name.clone(), db.customers.len(), db.branches.len())
    };
    let features: Vec<(&'static str, &'static str, String)> = vec![
        ("users", "accent", t("welcome.f_customers")),
        ("repeat", "success", t("welcome.f_refills")),
        ("square-kanban", "info", t("welcome.f_deals")),
        ("send", "accent", t("welcome.f_inbox")),
        ("gift", "warning", t("welcome.f_loyalty")),
        ("sparkles", "info", t("welcome.f_ai")),
    ];
    rsx! {
        div { class: "overlay" }
        div { class: "modal-wrap",
            div { class: "modal wide", role: "dialog",
                div { class: "card hero", style: "border-radius: 20px 20px 0 0; padding: 26px 24px",
                    div { class: "row gap-12",
                        div { class: "brand-mark", style: "width:44px;height:44px;border-radius:14px;background:rgb(255 255 255 / .16)", Icon { name: "heart-pulse", size: 24 } }
                        div {
                            div { class: "display", style: "font-size: 26px", "Daybook CRM" }
                            div { class: "muted small", {t("welcome.tagline")} }
                        }
                    }
                    p { style: "margin-top: 16px; max-width: 560px; opacity: .92", {t("welcome.lead")} }
                    div { class: "row gap-8 wrap", style: "margin-top: 14px",
                        span { class: "badge", style: "background: rgb(255 255 255 / .16); color: #fff", Icon { name: "store", size: 13 } "{company}" }
                        span { class: "badge", style: "background: rgb(255 255 255 / .16); color: #fff", "{branches} " {t("common.branches").to_lowercase()} }
                        span { class: "badge", style: "background: rgb(255 255 255 / .16); color: #fff", "{customers} " {t("common.customers").to_lowercase()} }
                    }
                }
                div { class: "modal-body",
                    div { class: "field",
                        span { class: "label", {t("common.language")} }
                        div { class: "row wrap gap-8",
                            for l in Lang::ALL.iter().copied() {
                                button {
                                    key: "{l.code()}",
                                    class: if l == cur { "chip on" } else { "chip" },
                                    onclick: move |_| mutate(|db| db.settings.lang = l),
                                    "{l.native_name()}"
                                }
                            }
                        }
                    }
                    div { class: "grid-3", style: "gap: 10px",
                        for (icon, tone, text) in features {
                            div { class: "row top gap-8 small", key: "{icon}",
                                span { class: "ic {tone} sm", Icon { name: icon, size: 15 } }
                                span { "{text}" }
                            }
                        }
                    }
                }
                div { class: "modal-foot",
                    button { class: "btn ghost", onclick: move |_| { mutate(|db| db.settings.onboarded = true); go("/settings/daybook"); },
                        Icon { name: "link-2", size: 16 } {t("common.connect_daybook")}
                    }
                    button { class: "btn primary lg", onclick: move |_| mutate(|db| db.settings.onboarded = true),
                        {t("welcome.start")} Icon { name: "arrow-right", size: 17 }
                    }
                }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("palette.pages", "Bo‘limlar", "Разделы", "Pages"),
    ("palette.actions", "Amallar", "Действия", "Actions"),
    ("palette.results", "Topildi", "Найдено", "Results"),
    ("palette.new_customer", "Yangi mijoz", "Новый клиент", "New customer"),
    ("palette.new_deal", "Yangi bitim", "Новая сделка", "New deal"),
    ("palette.new_task", "Yangi vazifa", "Новая задача", "New task"),
    ("palette.new_lead", "Yangi lid", "Новый лид", "New lead"),
    ("palette.new_ticket", "Yangi murojaat", "Новое обращение", "New ticket"),
    ("palette.toggle_theme", "Yorug‘ / qorong‘i mavzu", "Светлая / тёмная тема", "Light / dark theme"),
    ("palette.move", "tanlash", "выбор", "move"),
    ("palette.open", "ochish", "открыть", "open"),
    ("palette.reset_done", "Demo ma’lumotlar qayta yaratildi", "Демо-данные созданы заново", "Demo data rebuilt"),
    ("quick.first_name", "Ism", "Имя", "First name"),
    ("quick.last_name", "Familiya", "Фамилия", "Last name"),
    ("quick.duplicate", "Bu raqam allaqachon bor:", "Этот номер уже есть:", "This number already belongs to"),
    ("quick.welcome_bonus", "Yangi mijozga xush kelibsiz bonusi beriladi va sodiqlik kartasi ochiladi.", "Новый клиент получит приветственный бонус и карту лояльности.", "New customers get a welcome bonus and a loyalty card."),
    ("quick.customer_saved", "Mijoz qo‘shildi", "Клиент добавлен", "Customer added"),
    ("quick.deal_title", "Bitim nomi", "Название сделки", "Deal title"),
    ("quick.deal_title_hint", "Masalan: klinika uchun oylik ta’minot", "Например: ежемесячные поставки для клиники", "e.g. monthly supply for a clinic"),
    ("quick.pipeline", "Voronka", "Воронка", "Pipeline"),
    ("quick.deal_saved", "Bitim yaratildi", "Сделка создана", "Deal created"),
    ("quick.task_title", "Nima qilish kerak?", "Что нужно сделать?", "What needs doing?"),
    ("quick.kind", "Turi", "Тип", "Type"),
    ("quick.due", "Muddat", "Срок", "Due"),
    ("quick.to_daybook", "Daybook vazifalariga ham qo‘shish", "Также создать задачу в Daybook", "Also create the task in Daybook"),
    ("quick.task_saved", "Vazifa qo‘shildi", "Задача добавлена", "Task added"),
    ("quick.channel", "Kanal", "Канал", "Channel"),
    ("quick.interest", "Nimaga qiziqmoqda", "Что интересует", "Interested in"),
    ("quick.lead_saved", "Lid qo‘shildi", "Лид добавлен", "Lead added"),
    ("quick.subject", "Mavzu", "Тема", "Subject"),
    ("quick.ticket_saved", "Murojaat ochildi", "Обращение открыто", "Ticket opened"),
    ("quick.adverse_hint", "Nojo‘ya ta’sir: 4 soatlik muddat, provizorga vazifa va farmakonazorat shakli avtomatik yaratiladi.", "Нежелательная реакция: срок 4 часа, задача провизору и форма фармаконадзора создаются автоматически.", "Adverse reaction: a 4-hour deadline, a task for the pharmacist and a pharmacovigilance form are created automatically."),
    ("welcome.tagline", "Dorixonalar uchun mijozlar bilan ishlash tizimi", "CRM для аптек и аптечных сетей", "The CRM built for pharmacies"),
    ("welcome.lead", "Bu demo kompaniya: haqiqiy dorixona tarmog‘idek ma’lumotlar bilan to‘ldirilgan. Hammasini bemalol bosib ko‘ring: hech narsa buzilmaydi, istalgan payt qayta yaratish mumkin.", "Это демо-компания, наполненная данными как настоящая аптечная сеть. Нажимайте всё подряд: ничего не сломается, данные можно пересоздать в любой момент.", "This is a demo company filled with data like a real pharmacy chain. Click anything: nothing breaks, and the data can be rebuilt any time."),
    ("welcome.f_customers", "Mijoz kartasi: xaridlar, dorilar, ballar, yozishmalar bir joyda", "Карточка клиента: покупки, лекарства, баллы и переписка в одном месте", "Customer 360: purchases, medicines, points and chats in one place"),
    ("welcome.f_refills", "Dori radari: kimning dorisi tugayotganini oldindan biladi", "Радар лекарств: знает заранее, у кого заканчивается лекарство", "Refill radar: knows who runs out of medicine before they do"),
    ("welcome.f_deals", "Klinikalar va korxonalar bilan bitimlar voronkasi", "Воронка сделок с клиниками и компаниями", "Deal pipelines for clinics and companies"),
    ("welcome.f_inbox", "Telegram, SMS va WhatsApp yagona xabarlar oynasida", "Telegram, SMS и WhatsApp в одном окне", "Telegram, SMS and WhatsApp in one inbox"),
    ("welcome.f_loyalty", "Keshbek, darajalar va tug‘ilgan kun bonuslari", "Кешбэк, уровни и бонусы на день рождения", "Cashback, tiers and birthday bonuses"),
    ("welcome.f_ai", "Aqlli tavsiyalar va AI yordamchi (Haiku, arzon)", "Умные подсказки и AI-помощник (Haiku, недорого)", "Smart insights and an AI assistant (Haiku, low cost)"),
    ("welcome.start", "Demoni boshlash", "Начать демо", "Start the demo"),
];
