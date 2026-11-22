//! The frame around every screen: sidebar (desktop), top bar, tab bar and + button (phone),
//! and the overlays (palette, notifications, quick add, toasts, welcome).

use crm::i18n::{Entry, Lang};
use crm::model::{Theme, WaitStatus};
use dioxus::prelude::*;

use crate::overlays::{NotificationsPanel, Onboarding, Palette, QuickAddModal, Toasts};
use crate::routes::Route;
use crate::state::{lang, mutate, t, today, QuickAdd, DB, UI};
use crate::ui::{Avatar, Empty, Icon};

pub struct NavItem {
    pub section: &'static str,
    pub icon: &'static str,
    pub key: &'static str,
    pub route: fn() -> Route,
}

pub const NAV: &[(&str, &[NavItem])] = &[
    ("nav.group.main", &[
        NavItem { section: "home", icon: "house", key: "nav.home", route: || Route::Home {} },
        NavItem { section: "inbox", icon: "inbox", key: "nav.inbox", route: || Route::Inbox {} },
        NavItem { section: "tasks", icon: "square-check", key: "nav.tasks", route: || Route::Tasks {} },
        NavItem { section: "calendar", icon: "calendar-days", key: "nav.calendar", route: || Route::Calendar {} },
    ]),
    ("nav.group.customers", &[
        NavItem { section: "contacts", icon: "users", key: "nav.contacts", route: || Route::Contacts {} },
        NavItem { section: "companies", icon: "building-2", key: "nav.companies", route: || Route::Companies {} },
        NavItem { section: "leads", icon: "magnet", key: "nav.leads", route: || Route::Leads {} },
        NavItem { section: "segments", icon: "layers", key: "nav.segments", route: || Route::Segments {} },
    ]),
    ("nav.group.sales", &[
        NavItem { section: "deals", icon: "square-kanban", key: "nav.deals", route: || Route::Deals {} },
        NavItem { section: "quotes", icon: "file-text", key: "nav.quotes", route: || Route::Quotes {} },
        NavItem { section: "products", icon: "pill", key: "nav.products", route: || Route::Products {} },
    ]),
    ("nav.group.marketing", &[
        NavItem { section: "campaigns", icon: "megaphone", key: "nav.campaigns", route: || Route::Campaigns {} },
        NavItem { section: "automations", icon: "workflow", key: "nav.automations", route: || Route::Automations {} },
        NavItem { section: "loyalty", icon: "gift", key: "nav.loyalty", route: || Route::Loyalty {} },
    ]),
    ("nav.group.care", &[
        NavItem { section: "refills", icon: "repeat", key: "nav.refills", route: || Route::Refills {} },
        NavItem { section: "waitlist", icon: "hourglass", key: "nav.waitlist", route: || Route::Waitlist {} },
        NavItem { section: "tickets", icon: "life-buoy", key: "nav.tickets", route: || Route::Tickets {} },
    ]),
    ("nav.group.insights", &[
        NavItem { section: "reports", icon: "chart-column", key: "nav.reports", route: || Route::Reports {} },
        NavItem { section: "goals", icon: "trophy", key: "nav.goals", route: || Route::Goals {} },
        NavItem { section: "team", icon: "users-round", key: "nav.team", route: || Route::Team {} },
    ]),
];

/// Translated label of the section a route belongs to.
pub fn section_label(section: &str) -> String {
    for (_, items) in NAV {
        if let Some(i) = items.iter().find(|i| i.section == section) {
            return t(i.key);
        }
    }
    match section {
        "settings" => t("nav.settings"),
        "more" => t("nav.more"),
        _ => String::new(),
    }
}

#[component]
pub fn Shell() -> Element {
    let route = use_route::<Route>();
    let section = route.section();
    let counts = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let refills = crm::analytics::refills(&db, now.date(), db.settings.refill_lead_days as i64).len();
        let breached = db.tickets.iter().filter(|t| t.breached(now)).count();
        let open_tickets = db.tickets.iter().filter(|t| t.is_open()).count();
        let arrived = db.waitlist.iter().filter(|w| w.status == WaitStatus::Arrived).count();
        let leads = db.leads.iter().filter(|l| l.status == crm::model::LeadStatus::New).count();
        (db.unread_inbox() as usize, db.tasks_due(Some(db.settings.me), now.date()), leads, refills, arrived, open_tickets, breached)
    });
    let (unread, tasks, leads, refills, arrived, tickets, breached) = counts();
    let (theme, collapsed, compact, company, onboarded, me_name, me_hue, connected, unread_notifs) = {
        let db = DB.read();
        let me = db.me().cloned();
        (
            db.settings.theme,
            db.settings.sidebar_collapsed,
            db.settings.compact,
            db.settings.company_name.clone(),
            db.settings.onboarded,
            me.as_ref().map(|m| m.name.clone()).unwrap_or_default(),
            me.as_ref().map(|m| m.hue).unwrap_or(24),
            db.settings.daybook.connected,
            db.unread_notifications(),
        )
    };
    let ui = UI.read().clone();
    let count_for = move |s: &str| -> Option<(usize, bool)> {
        match s {
            "inbox" if unread > 0 => Some((unread, true)),
            "tasks" if tasks > 0 => Some((tasks, false)),
            "leads" if leads > 0 => Some((leads, true)),
            "refills" if refills > 0 => Some((refills, false)),
            "waitlist" if arrived > 0 => Some((arrived, true)),
            "tickets" if tickets > 0 => Some((tickets, breached > 0)),
            _ => None,
        }
    };
    let app_cls = format!(
        "app{}{}",
        if collapsed { " collapsed" } else { "" },
        if compact { " compact" } else { "" }
    );
    let theme_slug = theme.slug();
    let mut lang_menu = use_signal(|| false);
    let mut add_menu = use_signal(|| false);
    let cur_lang = lang();

    let on_key = move |e: KeyboardEvent| {
        let key = e.key();
        let ctrl = e.modifiers().ctrl() || e.modifiers().meta();
        match key {
            Key::Character(c) if ctrl && c.eq_ignore_ascii_case("k") => {
                e.prevent_default();
                let open = UI.peek().palette;
                UI.write().palette = !open;
            }
            Key::Escape => {
                let mut ui = UI.write();
                ui.palette = false;
                ui.notifications = false;
                ui.quick_add = None;
                lang_menu.set(false);
                add_menu.set(false);
            }
            _ => {}
        }
    };

    rsx! {
        div { class: "{app_cls}", "data-theme": "{theme_slug}", tabindex: "-1", onkeydown: on_key,
            aside { class: "sidebar",
                div { class: "brand",
                    div { class: "brand-mark", Icon { name: "heart-pulse", size: 18 } }
                    div { class: "brand-text",
                        div { class: "brand-name", "Daybook" }
                        div { class: "brand-sub", "CRM" }
                    }
                }
                button { class: "workspace", onclick: move |_| { navigator().push(Route::SettingsPage {}); },
                    Avatar { name: company.clone(), hue: 24u16, size: "sm", square: true }
                    div { class: "grow",
                        div { class: "strong truncate small", "{company}" }
                        div { class: "xs muted truncate", {t("common.all_branches")} }
                    }
                    Icon { name: "chevrons-up-down", size: 15, class: "subtle" }
                }
                button { class: "search-trigger", onclick: move |_| UI.write().palette = true,
                    Icon { name: "search", size: 16 }
                    span { class: "label-text small", {t("common.search")} }
                    span { class: "kbd", "Ctrl K" }
                }
                for (group, items) in NAV.iter() {
                    div { class: "nav-group", key: "{group}",
                        div { class: "nav-label upper", {t(group)} }
                        for item in items.iter() {
                            Link {
                                key: "{item.section}",
                                to: (item.route)(),
                                class: if item.section == section { "nav-item active" } else { "nav-item" },
                                Icon { name: item.icon, size: 18 }
                                span { class: "label-text", {t(item.key)} }
                                if let Some((n, hot)) = count_for(item.section) {
                                    span { class: if hot { "count hot" } else { "count" }, "{n}" }
                                }
                            }
                        }
                    }
                }
                div { class: "sidebar-foot",
                    Link { to: Route::DaybookConnect {}, class: if connected { "conn on" } else { "conn" },
                        span { class: "dot" }
                        span { class: "label-text truncate grow",
                            if connected { {t("common.daybook_connected")} } else { {t("common.demo_mode")} }
                        }
                        Icon { name: "link-2", size: 14, class: "subtle label-text" }
                    }
                    Link { to: Route::SettingsPage {}, class: if section == "settings" { "nav-item active" } else { "nav-item" },
                        Icon { name: "settings", size: 18 }
                        span { class: "label-text", {t("nav.settings")} }
                    }
                    div { class: "me",
                        Avatar { name: me_name.clone(), hue: me_hue, size: "sm", online: true }
                        div { class: "grow label-text",
                            div { class: "small strong truncate", "{me_name}" }
                            div { class: "xs muted", {t("role.owner")} }
                        }
                        button {
                            class: "icon-btn sm label-text",
                            title: "Collapse",
                            onclick: move |_| mutate(|db| db.settings.sidebar_collapsed = !db.settings.sidebar_collapsed),
                            Icon { name: "panel-left", size: 16 }
                        }
                    }
                }
            }
            div { class: "main",
                header { class: "topbar",
                    div { class: "only-mobile brand-mark", style: "width:30px;height:30px;border-radius:9px", Icon { name: "heart-pulse", size: 16 } }
                    div { class: "crumbs grow",
                        span { class: "parent hide-mobile", "{company}" }
                        span { class: "parent hide-mobile subtle", "/" }
                        span { class: "here truncate", {section_label(section)} }
                    }
                    button { class: "icon-btn only-mobile", onclick: move |_| UI.write().palette = true, Icon { name: "search", size: 19 } }
                    div { class: "popover-anchor hide-mobile",
                        button { class: "btn primary sm", onclick: move |_| add_menu.toggle(),
                            Icon { name: "plus", size: 16 }
                            {t("common.new")}
                        }
                        if add_menu() {
                            div { class: "menu", style: "right: 0; top: 38px",
                                for (kind, icon, key) in quick_kinds() {
                                    button {
                                        key: "{key}",
                                        class: "menu-item",
                                        onclick: move |_| {
                                            add_menu.set(false);
                                            UI.write().quick_add = Some(kind);
                                        },
                                        Icon { name: icon, size: 16 }
                                        {t(key)}
                                    }
                                }
                            }
                        }
                    }
                    button {
                        class: "icon-btn",
                        title: "{t(\"common.notifications\")}",
                        onclick: move |_| {
                            let open = UI.peek().notifications;
                            UI.write().notifications = !open;
                        },
                        Icon { name: "bell", size: 19 }
                        if unread_notifs > 0 { span { class: "badge-dot" } }
                    }
                    button {
                        class: "icon-btn hide-mobile",
                        title: "{t(\"common.theme\")}",
                        onclick: move |_| mutate(|db| {
                            db.settings.theme = match db.settings.theme {
                                Theme::Light => Theme::Dark,
                                Theme::Dark => Theme::System,
                                Theme::System => Theme::Light,
                            }
                        }),
                        Icon { name: match theme { Theme::Light => "sun", Theme::Dark => "moon", Theme::System => "monitor" }, size: 18 }
                    }
                    div { class: "popover-anchor",
                        button { class: "btn ghost sm", onclick: move |_| lang_menu.toggle(),
                            Icon { name: "languages", size: 16 }
                            "{cur_lang.short()}"
                        }
                        if lang_menu() {
                            div { class: "menu", style: "right: 0; top: 36px; min-width: 180px",
                                for l in Lang::ALL.iter().copied() {
                                    button {
                                        key: "{l.code()}",
                                        class: if l == cur_lang { "menu-item hi" } else { "menu-item" },
                                        onclick: move |_| {
                                            lang_menu.set(false);
                                            mutate(|db| db.settings.lang = l);
                                        },
                                        span { class: "badge sm outline", "{l.short()}" }
                                        "{l.native_name()}"
                                        if l == cur_lang { span { class: "spacer" } Icon { name: "check", size: 15 } }
                                    }
                                }
                            }
                        }
                    }
                }
                main { class: "content", Outlet::<Route> {} }
            }
            nav { class: "tabbar",
                for (sec, icon, key, r) in tab_items() {
                    Link {
                        key: "{sec}",
                        to: r,
                        class: if sec == section || (sec == "more" && is_more_section(section)) { "tab-item active" } else { "tab-item" },
                        Icon { name: icon, size: 22 }
                        span { {t(key)} }
                        if sec == "inbox" && unread > 0 { span { class: "pip", "{unread}" } }
                    }
                }
            }
            button { class: "fab", "aria-label": "{t(\"common.quick_add\")}", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Customer),
                Icon { name: "plus", size: 26 }
            }
            if ui.palette { Palette {} }
            if ui.notifications { NotificationsPanel {} }
            if let Some(kind) = ui.quick_add { QuickAddModal { kind } }
            if !onboarded { Onboarding {} }
            Toasts {}
            if add_menu() || lang_menu() {
                div { style: "position: fixed; inset: 0; z-index: 14", onclick: move |_| { add_menu.set(false); lang_menu.set(false); } }
            }
        }
    }
}

fn quick_kinds() -> Vec<(QuickAdd, &'static str, &'static str)> {
    vec![
        (QuickAdd::Customer, "user-plus", "common.customer"),
        (QuickAdd::Deal, "square-kanban", "common.deal"),
        (QuickAdd::Task, "square-check", "common.task"),
        (QuickAdd::Lead, "magnet", "common.lead"),
        (QuickAdd::Ticket, "life-buoy", "common.ticket"),
    ]
}

fn tab_items() -> Vec<(&'static str, &'static str, &'static str, Route)> {
    vec![
        ("home", "house", "nav.home", Route::Home {}),
        ("inbox", "inbox", "nav.inbox", Route::Inbox {}),
        ("contacts", "users", "nav.contacts", Route::Contacts {}),
        ("deals", "square-kanban", "nav.deals", Route::Deals {}),
        ("more", "layout-grid", "nav.more", Route::More {}),
    ]
}

fn is_more_section(s: &str) -> bool {
    !matches!(s, "home" | "inbox" | "contacts" | "deals")
}

/// The phone's "More" screen: every section as a tile, plus quick settings.
#[component]
pub fn More() -> Element {
    let db = DB.read();
    let theme = db.settings.theme;
    let cur = db.settings.lang;
    drop(db);
    rsx! {
        div { class: "page",
            crate::ui::PageHeader { title: t("nav.more") }
            for (group, items) in NAV.iter() {
                div { class: "stack gap-8", key: "{group}",
                    div { class: "upper subtle", {t(group)} }
                    div { class: "grid-3", style: "grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px",
                        for item in items.iter() {
                            Link { key: "{item.section}", to: (item.route)(), class: "card pad hover stack gap-8", style: "align-items:center; text-align:center; padding:14px 8px",
                                span { class: "ic accent", Icon { name: item.icon, size: 18 } }
                                span { class: "small strong", {t(item.key)} }
                            }
                        }
                    }
                }
            }
            div { class: "card",
                div { class: "list",
                    Link { to: Route::SettingsPage {}, class: "list-row click",
                        span { class: "ic muted sm", Icon { name: "settings", size: 15 } }
                        span { class: "grow strong", {t("nav.settings")} }
                        Icon { name: "chevron-right", size: 16, class: "subtle" }
                    }
                    Link { to: Route::DaybookConnect {}, class: "list-row click",
                        span { class: "ic muted sm", Icon { name: "link-2", size: 15 } }
                        span { class: "grow strong", {t("nav.daybook")} }
                        Icon { name: "chevron-right", size: 16, class: "subtle" }
                    }
                    div { class: "list-row",
                        span { class: "ic muted sm", Icon { name: "moon", size: 15 } }
                        span { class: "grow strong", {t("common.theme")} }
                        crate::ui::Segmented {
                            options: Theme::ALL.iter().map(|th| (th.slug().to_string(), t(th.key()))).collect(),
                            value: theme.slug().to_string(),
                            onchange: move |v: String| mutate(|db| if let Some(th) = Theme::from_slug(&v) { db.settings.theme = th }),
                        }
                    }
                    div { class: "list-row",
                        span { class: "ic muted sm", Icon { name: "languages", size: 15 } }
                        span { class: "grow strong", {t("common.language")} }
                        crate::ui::Segmented {
                            options: Lang::ALL.iter().map(|l| (l.code().to_string(), l.short().to_string())).collect(),
                            value: cur.code().to_string(),
                            onchange: move |v: String| mutate(|db| if let Some(l) = Lang::from_code(&v) { db.settings.lang = l }),
                        }
                    }
                }
            }
        }
    }
}

#[component]
pub fn NotFound(segments: Vec<String>) -> Element {
    let _ = segments;
    let _ = today();
    rsx! {
        div { class: "page",
            Empty { icon: "map", title: t("shell.not_found"), text: t("shell.not_found_text"),
                Link { to: Route::Home {}, class: "btn primary", Icon { name: "house", size: 16 } {t("nav.home")} }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("shell.not_found", "Bu sahifa topilmadi", "Страница не найдена", "Page not found"),
    ("shell.not_found_text", "Havola eskirgan bo‘lishi mumkin. Bosh sahifaga qayting.", "Возможно, ссылка устарела. Вернитесь на главную.", "The link may be out of date. Head back home."),
];
