//! Tasks and the calendar: every call, meeting, delivery and to-do of the team, grouped by when
//! it is due. Complete with one click, add inline, and push a task to Daybook (it lands in the
//! employee's Telegram bot there). The calendar shows the same activities by month or week.

use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime, Timelike};
use crm::analytics::{add_months, month_start};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use crm::Db;
use dioxus::prelude::*;

use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

fn kind_tone(k: ActivityKind) -> &'static str {
    match k {
        ActivityKind::Call => "info",
        ActivityKind::Meeting | ActivityKind::Visit => "success",
        ActivityKind::Delivery => "warning",
        ActivityKind::Email | ActivityKind::Message => "muted",
        ActivityKind::Task => "accent",
    }
}

fn cal_class(k: ActivityKind) -> &'static str {
    match k {
        ActivityKind::Call => "cal-ev call",
        ActivityKind::Meeting | ActivityKind::Visit => "cal-ev meeting",
        ActivityKind::Delivery => "cal-ev delivery",
        _ => "cal-ev",
    }
}

/// The record an activity is about: (label, route, icon). Deal first, then company, customer, ticket.
fn related(db: &Db, a: &Activity) -> Option<(String, String, &'static str)> {
    if let Some(d) = a.deal_id.and_then(|id| db.deal(id)) {
        return Some((d.title.clone(), format!("/deals/{}", d.id), "square-kanban"));
    }
    if let Some(c) = a.company_id.and_then(|id| db.company(id)) {
        return Some((c.name.clone(), format!("/companies/{}", c.id), "building-2"));
    }
    if let Some(c) = a.customer_id.and_then(|id| db.customer(id)) {
        return Some((c.name(), format!("/contacts/{}", c.id), "user"));
    }
    if let Some(tk) = a.ticket_id.and_then(|id| db.ticket(id)) {
        return Some((tk.number.clone(), format!("/tickets/{}", tk.id), "life-buoy"));
    }
    None
}

#[derive(Clone, Debug, PartialEq)]
struct TaskRow {
    id: Id,
    kind: ActivityKind,
    title: String,
    due: NaiveDateTime,
    done: bool,
    done_at: Option<NaiveDateTime>,
    priority: Priority,
    owner: String,
    owner_hue: u16,
    related: Option<(String, String, &'static str)>,
    daybook: Option<i64>,
    outcome: Option<String>,
}

fn task_row(db: &Db, a: &Activity) -> TaskRow {
    let owner = db.staff_member(a.owner_id);
    TaskRow {
        id: a.id,
        kind: a.kind,
        title: a.title.clone(),
        due: a.due,
        done: a.done,
        done_at: a.done_at,
        priority: a.priority,
        owner: owner.map(|s| s.name.clone()).unwrap_or_default(),
        owner_hue: owner.map(|s| s.hue).unwrap_or(24),
        related: related(db, a),
        daybook: a.daybook_task,
        outcome: a.outcome.clone(),
    }
}

fn toggle_done(id: Id) {
    let was_done = DB.peek().activity(id).map(|a| a.done).unwrap_or(false);
    mutate(|db| db.complete_activity(id, crate::state::now()));
    if was_done {
        toast(t("tasks.reopened"), "rotate-ccw", "");
    } else {
        toast(t("common.done"), "circle-check", "success");
    }
}

fn send_to_daybook(id: Id) {
    let pseudo = 40_000 + id as i64;
    let now = crate::state::now();
    mutate(|db| {
        let mut title = String::new();
        if let Some(a) = db.activity_mut(id) {
            a.daybook_task = Some(pseudo);
            title = a.title.clone();
        }
        db.settings.daybook.pulled.tasks_pushed += 1;
        db.log(now, format!("Daybook: {title}"), false);
    });
    toast(format!("{} · #{pseudo}", t("tasks.sent_daybook")), "send-horizontal", "success");
}


/// The task open in the detail drawer (shared by Tasks and Calendar).
static OPEN_TASK: GlobalSignal<Option<Id>> = Signal::global(|| None);

const OUTCOMES: [&str; 4] = ["tasks.out_reserved", "tasks.out_reminded", "tasks.out_no_answer", "tasks.out_callback"];

#[component]
fn TaskDrawer(id: u32) -> Element {
    let src = DB.peek().activity(id).cloned();
    let mut title = use_signal(|| src.as_ref().map(|a| a.title.clone()).unwrap_or_default());
    let mut kind = use_signal(|| src.as_ref().map(|a| a.kind).unwrap_or(ActivityKind::Task));
    let mut due = use_signal(|| src.as_ref().map(|a| a.due.format("%Y-%m-%dT%H:%M").to_string()).unwrap_or_default());
    let mut priority = use_signal(|| src.as_ref().map(|a| a.priority).unwrap_or(Priority::Normal));
    let mut owner = use_signal(|| src.as_ref().map(|a| a.owner_id).unwrap_or(0));
    let mut notes = use_signal(|| src.as_ref().map(|a| a.notes.clone()).unwrap_or_default());
    let mut outcome = use_signal(|| src.as_ref().and_then(|a| a.outcome.clone()).unwrap_or_default());
    if src.is_none() {
        return rsx! {};
    }
    let (done, daybook, rel, staff, created_line) = {
        let db = DB.read();
        let a = db.activity(id);
        let staff: Vec<(Id, String)> = db.staff.iter().filter(|s| s.active).map(|s| (s.id, s.name.clone())).collect();
        let line = a.map(|a| format!("{} · {}", t(a.kind.key()), db.staff_name(Some(a.owner_id)))).unwrap_or_default();
        (a.map(|a| a.done).unwrap_or(false), a.and_then(|a| a.daybook_task), a.and_then(|a| related(&db, a)), staff, line)
    };
    let close = move || *OPEN_TASK.write() = None;
    let save = move |_| {
        let when = NaiveDateTime::parse_from_str(&due(), "%Y-%m-%dT%H:%M").ok();
        let (ti, k, p, o, n, out) = (title().trim().to_string(), kind(), priority(), owner(), notes(), outcome().trim().to_string());
        mutate(move |db| {
            if let Some(a) = db.activity_mut(id) {
                if !ti.is_empty() {
                    a.title = ti;
                }
                a.kind = k;
                a.priority = p;
                if o != 0 {
                    a.owner_id = o;
                }
                a.notes = n;
                a.outcome = if out.is_empty() { None } else { Some(out) };
                if let Some(w) = when {
                    a.due = w;
                }
            }
        });
        toast(t("common.saved"), "save", "success");
        *OPEN_TASK.write() = None;
    };
    let icon = crm::db::activity_icon(kind());
    let head = title();
    let done_label = if done { t("tasks.reopen") } else { t("tasks.mark_done") };
    let done_icon: &'static str = if done { "rotate-ccw" } else { "circle-check" };
    let outcome_chips: Vec<String> = OUTCOMES.iter().map(|k| t(k)).collect();
    rsx! {
        Drawer { title: head, icon: Some(icon), onclose: move |_| close(),
            div { class: "drawer-body",
                div { class: "row wrap gap-8",
                    if done { Badge { text: t("common.done"), tone: "success", icon: Some("check") } } else { Badge { text: t("common.open"), tone: "accent", dot: true } }
                    if daybook.is_some() { Badge { text: "Daybook", tone: "info", icon: Some("link-2") } }
                    span { class: "xs muted", "{created_line}" }
                }
                div { class: "field",
                    label { class: "label", {t("tasks.title")} }
                    input { class: "input", value: "{title}", oninput: move |e| title.set(e.value()) }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("tasks.kind")} }
                        select { class: "select", onchange: move |e| kind.set(ActivityKind::from_slug(&e.value()).unwrap_or(ActivityKind::Task)),
                            for k in ActivityKind::ALL.iter().copied() {
                                option { key: "{k.slug()}", value: "{k.slug()}", selected: k == kind(), {t(k.key())} }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("tasks.priority")} }
                        select { class: "select", onchange: move |e| priority.set(Priority::from_slug(&e.value()).unwrap_or(Priority::Normal)),
                            for p in Priority::ALL.iter().copied() {
                                option { key: "{p.slug()}", value: "{p.slug()}", selected: p == priority(), {t(p.key())} }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("tasks.due")} }
                        input { class: "input", r#type: "datetime-local", value: "{due}", oninput: move |e| due.set(e.value()) }
                    }
                    div { class: "field",
                        label { class: "label", {t("common.owner")} }
                        select { class: "select", onchange: move |e| owner.set(e.value().parse().unwrap_or(0)),
                            for (sid, name) in staff {
                                option { key: "{sid}", value: "{sid}", selected: sid == owner(), "{name}" }
                            }
                        }
                    }
                }
                if let Some((label, route, ricon)) = rel {
                    div { class: "row gap-12", style: "padding: 12px 14px; border-radius: 12px; border: 1px solid var(--c-border)",
                        IconTile { icon: ricon, tone: "info", size: "sm" }
                        span { class: "grow strong small truncate", "{label}" }
                        button {
                            class: "btn sm",
                            onclick: move |_| {
                                *OPEN_TASK.write() = None;
                                go(&route);
                            },
                            {t("common.see")}
                            Icon { name: "arrow-right", size: 14 }
                        }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("common.notes")} }
                    textarea { class: "textarea", rows: "3", value: "{notes}", placeholder: t("tasks.notes_hint"), oninput: move |e| notes.set(e.value()) }
                }
                div { class: "field",
                    label { class: "label", {t("tasks.outcome")} }
                    input { class: "input", value: "{outcome}", placeholder: t("tasks.outcome_hint"), oninput: move |e| outcome.set(e.value()) }
                    div { class: "row wrap gap-4", style: "margin-top: 4px",
                        for (k, chip) in outcome_chips.into_iter().enumerate() {
                            button { key: "{k}", class: "chip", style: "height: 26px; font-size: 12px", onclick: move |_| outcome.set(chip.clone()), "{chip}" }
                        }
                    }
                }
            }
            div { class: "drawer-foot", style: "justify-content: space-between",
                button {
                    class: "btn ghost danger",
                    onclick: move |_| {
                        mutate(|db| db.activities.retain(|a| a.id != id));
                        toast(t("tasks.deleted"), "trash-2", "");
                        *OPEN_TASK.write() = None;
                    },
                    Icon { name: "trash-2", size: 16 }
                    span { class: "hide-mobile", {t("common.delete")} }
                }
                div { class: "row gap-8",
                    if daybook.is_none() && !done {
                        button { class: "btn hide-mobile", onclick: move |_| send_to_daybook(id), Icon { name: "send-horizontal", size: 16 } "Daybook" }
                    }
                    button { class: "btn", onclick: move |_| toggle_done(id), Icon { name: done_icon, size: 16 } "{done_label}" }
                    button { class: "btn primary", onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- one row (tasks and agenda)

#[component]
fn ActivityRow(r: TaskRow, #[props(default)] compact: bool) -> Element {
    let now = now();
    let l = lang();
    let id = r.id;
    let overdue = !r.done && r.due < now;
    let due_text = if r.done {
        r.done_at.map(|d| fmt::relative(d, now, l)).unwrap_or_default()
    } else if compact || r.due.date() == now.date() {
        fmt::time(r.due)
    } else {
        fmt::datetime(r.due, now, l)
    };
    let due_cls = if overdue { "row gap-4 tone-danger strong nowrap" } else { "row gap-4 nowrap" };
    let due_icon: &'static str = if r.done { "check" } else { "clock" };
    let check_cls = if r.done { "check-circle on" } else { "check-circle" };
    let title_style = if r.done { "text-decoration: line-through; opacity: .55" } else { "" };
    let icon = crm::db::activity_icon(r.kind);
    let tone = kind_tone(r.kind);
    let prio = if !r.done && matches!(r.priority, Priority::High | Priority::Urgent) { Some(t(r.priority.key())) } else { None };
    let prio_tone: &'static str = if r.priority == Priority::Urgent { "danger" } else { "warning" };
    let outcome = if r.done { r.outcome.clone() } else { None };
    let kind_label = t(r.kind.key());
    let daybook_label = t("tasks.send_daybook");
    rsx! {
        div { class: "list-row click", onclick: move |_| *OPEN_TASK.write() = Some(id),
            button {
                class: check_cls,
                title: "{kind_label}",
                onclick: move |e| {
                    e.stop_propagation();
                    toggle_done(id);
                },
                Icon { name: "check", size: 13 }
            }
            span { class: "hide-mobile", IconTile { icon, tone, size: "sm" } }
            div { class: "meta",
                span { class: "title small", style: "{title_style}", "{r.title}" }
                div { class: "sub row gap-12 wrap", style: "row-gap: 2px",
                    span { class: "{due_cls}", Icon { name: due_icon, size: 12 } "{due_text}" }
                    if let Some((label, route, ricon)) = r.related.clone() {
                        span {
                            class: "row gap-4",
                            style: "cursor: pointer; min-width: 0; max-width: 100%",
                            onclick: move |e| {
                                e.stop_propagation();
                                go(&route);
                            },
                            Icon { name: ricon, size: 12 }
                            span { class: "truncate", style: "text-decoration: underline; text-decoration-color: var(--c-border-strong); text-underline-offset: 3px", "{label}" }
                        }
                    }
                    if let Some(o) = outcome {
                        span { class: "row gap-4 subtle", Icon { name: "arrow-right", size: 12 } span { class: "truncate", "{o}" } }
                    }
                }
            }
            if let Some(p) = prio { Badge { text: p, tone: prio_tone } }
            if r.daybook.is_some() {
                span { class: "hide-mobile", Badge { text: "Daybook", tone: "info", icon: Some("link-2") } }
            } else if !r.done {
                button {
                    class: "icon-btn sm hide-mobile",
                    title: "{daybook_label}",
                    onclick: move |e| {
                        e.stop_propagation();
                        send_to_daybook(id);
                    },
                    Icon { name: "send-horizontal", size: 15 }
                }
            }
            Avatar { name: r.owner.clone(), hue: Some(r.owner_hue), size: "xs" }
        }
    }
}

// ---------------------------------------------------------------- tasks

const GROUPS: [(&str, &str, &str); 6] = [
    ("common.overdue", "alarm-clock", "danger"),
    ("common.today", "calendar-check", "accent"),
    ("common.tomorrow", "calendar", "info"),
    ("common.this_week", "calendar-days", "success"),
    ("tasks.later", "calendar-clock", "muted"),
    ("tasks.done_group", "circle-check", "success"),
];

#[component]
pub fn Tasks() -> Element {
    let mut mine = use_signal(|| true);
    let mut kind = use_signal(|| None::<ActivityKind>);
    let mut owner = use_signal(|| 0u32);
    let mut query = use_signal(String::new);
    let mut show_done = use_signal(|| false);
    let mut expanded = use_signal(Vec::<usize>::new);
    let mut new_title = use_signal(String::new);
    let mut new_kind = use_signal(|| ActivityKind::Task);
    let mut new_when = use_signal(|| "today".to_string());

    let data = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let today = now.date();
        let me = db.settings.me;
        let q = query().trim().to_lowercase();
        let week_end = today + Duration::days(6 - today.weekday().num_days_from_monday() as i64);
        let mut groups: [Vec<TaskRow>; 6] = Default::default();
        let mut kinds = vec![0usize; ActivityKind::ALL.len()];
        let mut in_daybook = 0;
        for a in &db.activities {
            if mine() && a.owner_id != me {
                continue;
            }
            if !mine() && owner() != 0 && a.owner_id != owner() {
                continue;
            }
            if !q.is_empty() && !a.title.to_lowercase().contains(&q) {
                continue;
            }
            if let Some(i) = ActivityKind::ALL.iter().position(|k| *k == a.kind) {
                if !a.done {
                    kinds[i] += 1;
                }
            }
            if kind().map_or(false, |k| k != a.kind) {
                continue;
            }
            if a.daybook_task.is_some() && !a.done {
                in_daybook += 1;
            }
            let d = a.due.date();
            let g = if a.done {
                5
            } else if d < today {
                0
            } else if d == today {
                1
            } else if d == today + Duration::days(1) {
                2
            } else if d <= week_end {
                3
            } else {
                4
            };
            groups[g].push(task_row(&db, a));
        }
        for g in groups.iter_mut().take(5) {
            g.sort_by_key(|r| r.due);
        }
        groups[5].sort_by(|a, b| b.done_at.cmp(&a.done_at));
        let done_today = groups[5].iter().filter(|r| r.done_at.map_or(false, |d| d.date() == today)).count();
        (groups, kinds, in_daybook, done_today)
    });
    let (groups, kinds, in_daybook, done_today) = data();
    let staff: Vec<(Id, String)> = DB.read().staff.iter().filter(|s| s.active).map(|s| (s.id, s.name.clone())).collect();
    let open: usize = groups.iter().take(5).map(|g| g.len()).sum();
    let overdue = groups[0].len();
    let due_week = groups[1].len() + groups[2].len() + groups[3].len();
    let l = lang();
    let subtitle = match l {
        Lang::Ru => format!("{} открытых · просрочено: {}", open, overdue),
        Lang::En => format!("{} open · {} overdue", open, overdue),
        _ => uz(format!("{} ta ochiq · {} tasining muddati o‘tgan", open, overdue)),
    };
    let total_kinds: usize = kinds.iter().sum();
    let kind_chips: Vec<(ActivityKind, String, usize)> =
        ActivityKind::ALL.iter().enumerate().filter(|(i, _)| kinds[*i] > 0).map(|(i, k)| (*k, t(k.key()), kinds[i])).collect();
    let cur_kind = kind();
    let nothing = groups.iter().all(|g| g.is_empty());
    let overdue_tone: &'static str = if overdue > 0 { "danger" } else { "success" };

    let mut add = move || {
        let title = new_title().trim().to_string();
        if title.is_empty() {
            return;
        }
        let now = crate::state::now();
        let today = now.date();
        let due = match new_when().as_str() {
            "tomorrow" => (today + Duration::days(1)).and_hms_opt(10, 0, 0),
            "week" => (today + Duration::days((4 - today.weekday().num_days_from_monday() as i64).max(2))).and_hms_opt(12, 0, 0),
            "next" => (today + Duration::days(7 - today.weekday().num_days_from_monday() as i64)).and_hms_opt(10, 0, 0),
            _ => {
                if now.hour() >= 17 {
                    Some(now + Duration::hours(1))
                } else {
                    today.and_hms_opt(18, 0, 0)
                }
            }
        }
        .unwrap_or(now);
        let k = new_kind();
        let who = if !mine() && owner() != 0 { owner() } else { DB.peek().settings.me };
        mutate(|db| {
            db.add_activity(Activity {
                id: 0,
                kind: k,
                title,
                notes: String::new(),
                due,
                done: false,
                done_at: None,
                owner_id: who,
                customer_id: None,
                company_id: None,
                deal_id: None,
                ticket_id: None,
                priority: Priority::Normal,
                outcome: None,
                duration_min: 15,
                daybook_task: None,
            });
        });
        new_title.set(String::new());
        toast(t("tasks.added"), "square-check", "success");
    };

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.tasks"), subtitle,
                Link { to: Route::Calendar {}, class: "btn", Icon { name: "calendar-days", size: 16 } span { class: "label-text", {t("nav.calendar")} } }
                button { class: "btn primary", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Task),
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("tasks.new")} }
                }
            }
            div { class: "grid-4",
                Kpi { label: t("tasks.done_today"), value: fmt::num(done_today as i64), icon: "circle-check", tone: "success", foot: t("tasks.keep_going") }
                Kpi { label: t("common.overdue"), value: fmt::num(overdue as i64), icon: "alarm-clock", tone: overdue_tone, foot: t("tasks.overdue_foot") }
                Kpi { label: t("tasks.due_week"), value: fmt::num(due_week as i64), icon: "calendar-days", tone: "info", foot: t("tasks.due_week_foot") }
                Kpi { label: t("tasks.in_daybook"), value: fmt::num(in_daybook as i64), icon: "link-2", tone: "accent", foot: t("tasks.in_daybook_foot") }
            }
            div { class: "toolbar",
                Segmented {
                    options: vec![("mine".to_string(), t("tasks.mine")), ("all".to_string(), t("tasks.team"))],
                    value: if mine() { "mine".to_string() } else { "all".to_string() },
                    onchange: move |v: String| mine.set(v == "mine"),
                }
                if !mine() {
                    select { class: "select", style: "width: auto; min-width: 180px", onchange: move |e| owner.set(e.value().parse().unwrap_or(0)),
                        option { value: "0", selected: owner() == 0, {t("tasks.everyone")} }
                        for (sid, name) in staff {
                            option { key: "{sid}", value: "{sid}", selected: owner() == sid, "{name}" }
                        }
                    }
                }
                div { class: "search",
                    Icon { name: "search", size: 16 }
                    input { class: "input", value: "{query}", placeholder: t("tasks.search"), oninput: move |e| query.set(e.value()) }
                }
            }
            div { class: "chips",
                button { class: if cur_kind.is_none() { "chip on" } else { "chip" }, onclick: move |_| kind.set(None),
                    {t("common.all")}
                    span { class: "count", "{total_kinds}" }
                }
                for (k, label, n) in kind_chips {
                    button {
                        key: "{k.slug()}",
                        class: if cur_kind == Some(k) { "chip on" } else { "chip" },
                        onclick: move |_| kind.set(if kind() == Some(k) { None } else { Some(k) }),
                        Icon { name: crm::db::activity_icon(k), size: 14 }
                        "{label}"
                        span { class: "count", "{n}" }
                    }
                }
            }
            div { class: "card",
                div { class: "list-row", style: "gap: 10px",
                    span { class: "ic accent sm", Icon { name: "plus", size: 15 } }
                    input {
                        class: "input grow",
                        style: "border: 0; box-shadow: none; padding-left: 2px; background: transparent",
                        value: "{new_title}",
                        placeholder: t("tasks.add_hint"),
                        oninput: move |e| new_title.set(e.value()),
                        onkeydown: move |e: KeyboardEvent| {
                            if e.key() == Key::Enter {
                                add();
                            }
                        },
                    }
                    select { class: "select sm hide-mobile", style: "width: auto", onchange: move |e| new_kind.set(ActivityKind::from_slug(&e.value()).unwrap_or(ActivityKind::Task)),
                        for k in ActivityKind::ALL.iter().copied() {
                            option { key: "{k.slug()}", value: "{k.slug()}", selected: k == new_kind(), {t(k.key())} }
                        }
                    }
                    select { class: "select sm", style: "width: auto", onchange: move |e| new_when.set(e.value()),
                        option { value: "today", selected: new_when() == "today", {t("common.today")} }
                        option { value: "tomorrow", selected: new_when() == "tomorrow", {t("common.tomorrow")} }
                        option { value: "week", selected: new_when() == "week", {t("common.this_week")} }
                        option { value: "next", selected: new_when() == "next", {t("tasks.next_week")} }
                    }
                    button { class: "btn primary sm", disabled: new_title().trim().is_empty(), onclick: move |_| add(),
                        Icon { name: "plus", size: 14 }
                        span { class: "hide-mobile", {t("common.add")} }
                    }
                }
            }
            if nothing {
                div { class: "card", Empty { icon: "list-checks", title: t("tasks.empty"), text: t("tasks.empty_text") } }
            }
            for (g, (key, icon, tone)) in GROUPS.into_iter().enumerate() {
                if !groups[g].is_empty() {
                    {
                        let rows = groups[g].clone();
                        let n = rows.len();
                        let is_done = g == 5;
                        let open_group = !is_done || show_done();
                        let all = expanded().contains(&g);
                        let shown: Vec<TaskRow> = if all { rows.clone() } else { rows.iter().take(60).cloned().collect() };
                        let rest = n.saturating_sub(shown.len());
                        let chevron: &'static str = if show_done() { "chevron-up" } else { "chevron-down" };
                        let more_label = t("tasks.show_more").replace("{n}", &rest.to_string());
                        rsx! {
                            div { key: "{key}", class: "card",
                                div {
                                    class: if open_group { "card-head line" } else { "card-head" },
                                    style: if is_done { "cursor: pointer; padding-bottom: 14px" } else { "" },
                                    onclick: move |_| if is_done { show_done.toggle() },
                                    div { class: "card-title",
                                        IconTile { icon, tone, size: "sm" }
                                        {t(key)}
                                        span { class: "badge sm", "{n}" }
                                    }
                                    if is_done {
                                        Icon { name: chevron, size: 16, class: "subtle" }
                                    }
                                }
                                if open_group {
                                    div { class: "list",
                                        for r in shown {
                                            ActivityRow { key: "{r.id}", r: r.clone() }
                                        }
                                    }
                                    if rest > 0 {
                                        div { class: "card-foot", style: "justify-content: center",
                                            button { class: "btn ghost sm", onclick: move |_| expanded.write().push(g), Icon { name: "chevron-down", size: 14 } "{more_label}" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            div { class: "callout", Icon { name: "link-2", size: 16 } span { {t("tasks.daybook_note")} } }
        }
        if let Some(open) = OPEN_TASK() {
            TaskDrawer { key: "{open}", id: open }
        }
    }
}

// ---------------------------------------------------------------- calendar

#[component]
pub fn Calendar() -> Element {
    let today = today();
    let l = lang();
    let mut month = use_signal(move || month_start(crate::state::today()));
    let mut selected = use_signal(move || crate::state::today());
    let mut view = use_signal(|| "month".to_string());
    let mut all = use_signal(|| true);

    // every activity in scope, by day
    let events = use_memo(move || {
        let db = DB.read();
        let me = db.settings.me;
        let mut map: std::collections::BTreeMap<NaiveDate, Vec<TaskRow>> = std::collections::BTreeMap::new();
        for a in db.activities.iter().filter(|a| all() || a.owner_id == me) {
            map.entry(a.due.date()).or_default().push(task_row(&db, a));
        }
        for v in map.values_mut() {
            v.sort_by_key(|r| r.due);
        }
        map
    });
    let ev = events();
    let m0 = month();
    let offset = m0.weekday().num_days_from_monday() as i64;
    let days_in_month = (add_months(m0, 1) - m0).num_days();
    let weeks = (offset + days_in_month + 6) / 7;
    let grid_start = m0 - Duration::days(offset);
    let cells: Vec<NaiveDate> = (0..weeks * 7).map(|i| grid_start + Duration::days(i)).collect();
    let month_count: usize = ev.range(m0..add_months(m0, 1)).map(|(_, v)| v.len()).sum();
    let title = format!("{} {}", fmt::month_name(m0.month(), l), m0.year());
    let subtitle = match l {
        Lang::Ru => format!("{title} · {month_count} дел"),
        Lang::En => format!("{title} · {month_count} activities"),
        _ => uz(format!("{title} · {month_count} ta ish")),
    };
    let sel = selected();
    let week_start = sel - Duration::days(sel.weekday().num_days_from_monday() as i64);
    let week_days: Vec<NaiveDate> = (0..7).map(|i| week_start + Duration::days(i)).collect();
    let is_week = view() == "week";
    let agenda: Vec<TaskRow> = ev.get(&sel).cloned().unwrap_or_default();
    let agenda_title = format!("{}, {}", fmt::weekday_long(sel.weekday().num_days_from_monday(), l), fmt::date(sel, today, l));
    let agenda_n = agenda.len();
    let weekdays: Vec<String> = (0..7).map(|i| fmt::weekday_short(i, l)).collect();
    let hours: Vec<u32> = (8..=20).collect();

    let mut shift = move |dir: i32| {
        if view() == "week" {
            let s = selected() + Duration::days(7 * dir as i64);
            selected.set(s);
            month.set(month_start(s));
        } else {
            let m = add_months(month(), dir);
            month.set(m);
            let s = selected();
            if month_start(s) != m {
                selected.set(m);
            }
        }
    };

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.calendar"), subtitle,
                span { class: "hide-mobile",
                    Segmented {
                        options: vec![("month".to_string(), t("tasks.cal_month")), ("week".to_string(), t("tasks.cal_week"))],
                        value: view(),
                        onchange: move |v: String| view.set(v),
                    }
                }
                Segmented {
                    options: vec![("all".to_string(), t("tasks.team")), ("mine".to_string(), t("tasks.mine"))],
                    value: if all() { "all".to_string() } else { "mine".to_string() },
                    onchange: move |v: String| all.set(v == "all"),
                }
                div { class: "row gap-4",
                    button { class: "icon-btn bordered", title: t("tasks.prev"), onclick: move |_| shift(-1), Icon { name: "chevron-left", size: 18 } }
                    button {
                        class: "btn",
                        onclick: move |_| {
                            let d = crate::state::today();
                            selected.set(d);
                            month.set(month_start(d));
                        },
                        {t("common.today")}
                    }
                    button { class: "icon-btn bordered", title: t("common.next"), onclick: move |_| shift(1), Icon { name: "chevron-right", size: 18 } }
                }
            }
            div { class: if is_week { "card only-mobile" } else { "card" }, style: "overflow: hidden",
                div { style: "display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); border-bottom: 1px solid var(--c-border)",
                    for (i, wd) in weekdays.iter().enumerate() {
                        div { key: "{i}", class: "upper subtle center", style: "padding: 10px 0", "{wd}" }
                    }
                }
                div { class: "cal", style: "border-top: 0; border-left: 0",
                    for d in cells {
                        {
                            let out = d.month() != m0.month();
                            let is_today = d == today;
                            let mut cls = String::from("cal-cell");
                            if out {
                                cls.push_str(" out");
                            }
                            if is_today {
                                cls.push_str(" today");
                            }
                            let mut list = ev.get(&d).cloned().unwrap_or_default();
                            list.sort_by_key(|r| (r.done, r.due));
                            let n = list.len();
                            let extra = n.saturating_sub(3);
                            let style = if d == sel { "cursor: pointer; box-shadow: inset 0 0 0 2px var(--c-primary)" } else { "cursor: pointer" };
                            let day = d.day();
                            rsx! {
                                div { key: "{d}", class: "{cls}", style: "{style}", onclick: move |_| selected.set(d),
                                    div { class: "row between",
                                        span { class: "cal-day", "{day}" }
                                        if extra > 0 { span { class: "xs subtle hide-mobile", "+{extra}" } }
                                    }
                                    for r in list.iter().take(3).cloned() {
                                        {
                                            let cls = cal_class(r.kind);
                                            let time = fmt::time(r.due);
                                            let st = if r.done { "opacity: .5" } else { "" };
                                            let rid = r.id;
                                            rsx! {
                                                div {
                                                    key: "{rid}",
                                                    class: "{cls} hide-mobile",
                                                    style: "{st}",
                                                    title: "{r.title}",
                                                    onclick: move |e| {
                                                        e.stop_propagation();
                                                        *OPEN_TASK.write() = Some(rid);
                                                    },
                                                    "{time} {r.title}"
                                                }
                                            }
                                        }
                                    }
                                    if !list.is_empty() {
                                        div { class: "only-mobile row wrap", style: "gap: 3px; justify-content: center; margin-top: 2px",
                                            for r in list.iter().take(6).cloned() {
                                                {
                                                    let color = match r.kind {
                                                        ActivityKind::Call => "var(--c-info)",
                                                        ActivityKind::Meeting | ActivityKind::Visit => "var(--c-success)",
                                                        ActivityKind::Delivery => "var(--c-warning)",
                                                        _ => "var(--c-primary)",
                                                    };
                                                    let op = if r.done { ".35" } else { "1" };
                                                    rsx! { span { key: "{r.id}", style: "width: 6px; height: 6px; border-radius: 99px; background: {color}; opacity: {op}" } }
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
            if is_week {
                div { class: "card hide-mobile", style: "overflow: hidden",
                    div { style: "display: grid; grid-template-columns: 64px repeat(7, minmax(0, 1fr))",
                        div { style: "border-bottom: 1px solid var(--c-border)" }
                        for d in week_days.iter().copied() {
                            {
                                let wd = fmt::weekday_short(d.weekday().num_days_from_monday(), l);
                                let day = d.day();
                                let style = if d == today { "background: var(--c-accent-soft); color: var(--c-accent-fg)" } else { "" };
                                rsx! {
                                    div { key: "h{d}", class: "center", style: "padding: 10px 4px; border-bottom: 1px solid var(--c-border); border-left: 1px solid var(--c-border); cursor: pointer; {style}", onclick: move |_| selected.set(d),
                                        div { class: "upper subtle", "{wd}" }
                                        div { class: "strong", style: "font-size: 18px", "{day}" }
                                    }
                                }
                            }
                        }
                        for h in hours.iter().copied() {
                            div { key: "l{h}", class: "xs subtle right", style: "padding: 6px 8px; border-bottom: 1px solid var(--c-border)", "{h:02}:00" }
                            for d in week_days.iter().copied() {
                                {
                                    let list: Vec<TaskRow> = ev
                                        .get(&d)
                                        .map(|v| v.iter().filter(|r| r.due.hour().clamp(8, 20) == h).cloned().collect())
                                        .unwrap_or_default();
                                    let bg = if d == today { "background: color-mix(in srgb, var(--c-accent-soft) 40%, transparent);" } else { "" };
                                    rsx! {
                                        div { key: "c{h}-{d}", class: "stack", style: "gap: 3px; padding: 4px; min-height: 46px; border-bottom: 1px solid var(--c-border); border-left: 1px solid var(--c-border); {bg}",
                                            for r in list {
                                                {
                                                    let cls = cal_class(r.kind);
                                                    let time = fmt::time(r.due);
                                                    let st = if r.done { "opacity: .5; white-space: normal" } else { "white-space: normal" };
                                                    let rid = r.id;
                                                    rsx! {
                                                        div {
                                                            key: "{rid}",
                                                            class: "{cls}",
                                                            style: "{st}",
                                                            title: "{r.title}",
                                                            onclick: move |_| *OPEN_TASK.write() = Some(rid),
                                                            b { "{time} " }
                                                            "{r.title}"
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
            div { class: "card",
                div { class: "card-head line",
                    div { class: "card-title", Icon { name: "calendar-check", size: 16, class: "tone-accent" } "{agenda_title}" }
                    span { class: "badge", "{agenda_n}" }
                }
                if agenda.is_empty() {
                    Empty { icon: "calendar", title: t("tasks.cal_free"),
                        button { class: "btn soft sm", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Task), Icon { name: "plus", size: 14 } {t("tasks.new")} }
                    }
                }
                div { class: "list",
                    for r in agenda {
                        ActivityRow { key: "{r.id}", r: r.clone(), compact: true }
                    }
                }
            }
            div { class: "legend",
                span { span { class: "sw", style: "background: var(--c-info)" } {t("activity.call")} }
                span { span { class: "sw", style: "background: var(--c-success)" } {t("activity.meeting")} }
                span { span { class: "sw", style: "background: var(--c-warning)" } {t("activity.delivery")} }
                span { span { class: "sw", style: "background: var(--c-primary)" } {t("activity.task")} }
            }
        }
        if let Some(open) = OPEN_TASK() {
            TaskDrawer { key: "{open}", id: open }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("tasks.new", "Yangi vazifa", "Новая задача", "New task"),
    ("tasks.mine", "Meniki", "Мои", "Mine"),
    ("tasks.team", "Jamoa", "Команда", "Team"),
    ("tasks.everyone", "Barcha xodimlar", "Все сотрудники", "Everyone"),
    ("tasks.search", "Vazifani qidirish…", "Поиск задач…", "Search tasks…"),
    ("tasks.add_hint", "Yangi vazifa yozing va Enter bosing…", "Новая задача: напишите и нажмите Enter…", "Type a new task and press Enter…"),
    ("tasks.next_week", "Keyingi hafta", "Следующая неделя", "Next week"),
    ("tasks.later", "Keyinroq", "Позже", "Later"),
    ("tasks.done_group", "Bajarilganlar", "Выполненные", "Done"),
    ("tasks.done_today", "Bugun bajarildi", "Сделано сегодня", "Done today"),
    ("tasks.keep_going", "Davom eting, yaxshi ketyapti", "Хороший темп", "Nice pace"),
    ("tasks.overdue_foot", "Avval shularni yoping", "Закройте их в первую очередь", "Close these first"),
    ("tasks.due_week", "Shu hafta muddati", "Срок на этой неделе", "Due this week"),
    ("tasks.due_week_foot", "bugun, ertaga va hafta oxirigacha", "сегодня, завтра и до конца недели", "today, tomorrow and the rest of the week"),
    ("tasks.in_daybook", "Daybook’da", "В Daybook", "In Daybook"),
    ("tasks.in_daybook_foot", "xodimning Telegram botida", "в Telegram-боте сотрудника", "in the employee’s Telegram bot"),
    ("tasks.send_daybook", "Daybook’ga yuborish", "Отправить в Daybook", "Send to Daybook"),
    ("tasks.sent_daybook", "Daybook’ga yuborildi", "Отправлено в Daybook", "Sent to Daybook"),
    ("tasks.added", "Vazifa qo‘shildi", "Задача добавлена", "Task added"),
    ("tasks.reopened", "Vazifa qayta ochildi", "Задача снова открыта", "Task reopened"),
    ("tasks.show_more", "Yana {n} tasini ko‘rsatish", "Показать ещё {n}", "Show {n} more"),
    ("tasks.empty", "Vazifalar yo‘q", "Задач нет", "No tasks"),
    ("tasks.empty_text", "Filtrlarni o‘zgartiring yoki yuqorida yangi vazifa qo‘shing.", "Измените фильтры или добавьте задачу выше.", "Change the filters or add a task above."),
    (
        "tasks.daybook_note",
        "Daybook’ga yuborilgan vazifa xodimning Telegram botida paydo bo‘ladi, bajarilgani esa shu yerga qaytadi.",
        "Задача, отправленная в Daybook, появится у сотрудника в Telegram-боте, а отметка о выполнении вернётся сюда.",
        "A task sent to Daybook shows up in the employee’s Telegram bot, and its completion syncs back here.",
    ),
    ("tasks.cal_month", "Oy", "Месяц", "Month"),
    ("tasks.cal_week", "Hafta", "Неделя", "Week"),
    ("tasks.cal_free", "Bu kunga reja yo‘q", "На этот день ничего не запланировано", "Nothing planned for this day"),
    ("tasks.prev", "Oldingi", "Назад", "Previous"),
    ("tasks.title", "Vazifa", "Задача", "Task"),
    ("tasks.kind", "Turi", "Тип", "Type"),
    ("tasks.priority", "Muhimlik", "Приоритет", "Priority"),
    ("tasks.due", "Muddat", "Срок", "Due"),
    ("tasks.notes_hint", "Qo‘shimcha ma’lumot, masalan: ertalab qo‘ng‘iroq qilmang", "Подробности, например: не звонить утром", "Details, e.g. don’t call in the morning"),
    ("tasks.outcome", "Natija", "Результат", "Outcome"),
    ("tasks.outcome_hint", "Nima bo‘ldi? Masalan: bron qilindi", "Чем закончилось? Например: забронировано", "What happened? For example: reserved"),
    ("tasks.out_reserved", "Bron qilindi", "Забронировано", "Reserved"),
    ("tasks.out_reminded", "Eslatildi, ertaga keladi", "Напомнили, придёт завтра", "Reminded, coming tomorrow"),
    ("tasks.out_no_answer", "Javob bermadi", "Не ответил", "No answer"),
    ("tasks.out_callback", "Qayta qo‘ng‘iroq so‘radi", "Просил перезвонить", "Asked for a call back"),
    ("tasks.mark_done", "Bajarildi deb belgilash", "Отметить выполненной", "Mark done"),
    ("tasks.reopen", "Qayta ochish", "Открыть снова", "Reopen"),
    ("tasks.deleted", "Vazifa o‘chirildi", "Задача удалена", "Task deleted"),
];
