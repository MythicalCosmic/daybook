//! Home: the owner's morning dashboard. KPIs with trends, revenue chart, smart insights,
//! today's agenda, the refill radar, the inbox and the Daybook connection at a glance.
//! This is the reference screen for the look and the patterns (use_memo for heavy numbers).

use chrono::{Datelike, Duration, Timelike};
use crm::analytics;
use crm::fmt;
use crm::i18n::Entry;
use crm::model::*;
use dioxus::prelude::*;

use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

#[component]
pub fn Home() -> Element {
    let now = now();
    let today = now.date();
    let l = lang();
    let k = use_memo(move || analytics::kpis(&DB.read(), crate::state::now()));
    let daily = use_memo(move || analytics::daily_revenue(&DB.read(), crate::state::today(), 30));
    let prev = use_memo(move || analytics::daily_revenue(&DB.read(), crate::state::today() - Duration::days(30), 30));
    let monthly = use_memo(move || analytics::monthly_revenue(&DB.read(), crate::state::today(), 12));
    let insights = use_memo(move || analytics::insights(&DB.read(), crate::state::now(), crate::state::lang()));
    let refills = use_memo(move || analytics::refills(&DB.read(), crate::state::today(), 7));
    let branch_rev = use_memo(move || analytics::revenue_by_branch(&DB.read(), analytics::month_start(crate::state::today())));
    let tiers = use_memo(move || analytics::tier_counts(&DB.read()));
    let mut range = use_signal(|| "30".to_string());
    let k = k();

    let first = DB.read().me().map(|m| m.name.split_whitespace().next().unwrap_or("").to_string()).unwrap_or_default();
    let greeting = match now.hour() {
        5..=11 => tr("Xayrli tong", "Доброе утро", "Good morning"),
        12..=17 => tr("Xayrli kun", "Добрый день", "Good afternoon"),
        _ => tr("Xayrli kech", "Добрый вечер", "Good evening"),
    };
    let date_line = format!("{}, {}", fmt::weekday_long(today.weekday().num_days_from_monday(), l), fmt::date(today, today, l));
    let summary = match l {
        crm::i18n::Lang::Ru => format!("{} · задач на сегодня: {} · лекарства заканчиваются у {} клиентов", date_line, k.tasks_today, k.refills_week),
        crm::i18n::Lang::En => format!("{} · {} tasks today · {} customers running out of medicine", date_line, k.tasks_today, k.refills_week),
        _ => format!("{} · {}", date_line, uz(format!("bugun {} ta vazifa · {} ta mijozning dorisi tugayapti", k.tasks_today, k.refills_week))),
    };

    let spark: Vec<f64> = daily().iter().map(|d| d.1 as f64).collect();
    let (labels, series) = if range() == "30" {
        let d = daily();
        let p = prev();
        (
            d.iter().map(|(day, _)| format!("{} {}", day.day(), fmt::month_short(day.month(), l))).collect::<Vec<_>>(),
            vec![
                Series { name: t("home.this_period"), values: d.iter().map(|x| x.1 as f64).collect(), color: "var(--c-chart-1)", dashed: false },
                Series { name: t("home.prev_period"), values: p.iter().map(|x| x.1 as f64).collect(), color: "var(--c-chart-2)", dashed: true },
            ],
        )
    } else {
        let m = monthly();
        (
            m.iter().map(|(month, _, _)| fmt::month_short(month.month(), l)).collect::<Vec<_>>(),
            vec![Series { name: t("metric.revenue"), values: m.iter().map(|x| x.1 as f64).collect(), color: "var(--c-chart-1)", dashed: false }],
        )
    };
    let period_total: i64 = series.first().map(|s| s.values.iter().sum::<f64>() as i64).unwrap_or(0);

    let branch_items: Vec<(String, f64, String)> = {
        let db = DB.read();
        branch_rev().iter().map(|(id, v)| (db.branch_name(Some(*id)), *v as f64, money_short(*v))).collect()
    };
    let tier_colors = ["#c67139", "#8d9aab", "#d9a637", "#7d68b8"];
    let tier_slices: Vec<Slice> = tiers()
        .iter()
        .enumerate()
        .map(|(i, (tier, n, _))| Slice { label: t(tier.key()), value: *n as f64, color: tier_colors[i % 4].to_string() })
        .collect();
    let customers_total = k.customers_total;

    rsx! {
        div { class: "page",
            PageHeader { title: format!("{greeting}, {first}"), subtitle: summary,
                button { class: "btn", onclick: move |_| go("/reports"), Icon { name: "chart-column", size: 16 } span { class: "label-text", {t("nav.reports")} } }
                button { class: "btn primary", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Customer), Icon { name: "user-plus", size: 16 } span { class: "label-text", {t("palette.new_customer")} } }
            }

            div { class: "grid-4",
                Kpi {
                    label: t("home.revenue_mtd"),
                    value: money_short(k.revenue_mtd),
                    icon: "wallet",
                    delta: Some(k.revenue_delta()),
                    foot: t("common.vs_last_month"),
                    spark: spark.clone(),
                }
                Kpi {
                    label: t("home.active_customers"),
                    value: fmt::num(k.active_customers as i64),
                    icon: "users",
                    tone: "info",
                    delta: Some(k.new_customers_delta()),
                    foot: format!("+{} {}", k.new_customers_mtd, t("home.new_this_month")),
                    onclick: move |_| go("/contacts"),
                }
                Kpi {
                    label: t("home.weighted_pipeline"),
                    value: money_short(k.weighted_pipeline),
                    icon: "square-kanban",
                    tone: "warning",
                    foot: format!("{} {} · {}", k.open_deals, t("home.open_deals"), money_short(k.open_pipeline)),
                    onclick: move |_| go("/deals"),
                }
                Kpi {
                    label: t("home.refills_week"),
                    value: fmt::num(k.refills_week as i64),
                    icon: "repeat",
                    tone: "success",
                    foot: format!("{} {}", k.waitlist_waiting, t("home.on_waitlist")),
                    onclick: move |_| go("/refills"),
                }
            }

            div { class: "grid-main",
                div { class: "stack gap-16",
                    div { class: "card",
                        div { class: "card-head",
                            div {
                                div { class: "card-title", {t("metric.revenue")} }
                                div { class: "row gap-8", style: "margin-top: 4px",
                                    span { class: "kpi-value", style: "font-size: 22px", "{money_short(period_total)}" }
                                    if range() == "30" { Delta { value: k.revenue_delta() } }
                                }
                            }
                            Segmented {
                                options: vec![("30".into(), t("home.days_30")), ("12".into(), t("home.months_12"))],
                                value: range(),
                                onchange: move |v| range.set(v),
                            }
                        }
                        div { class: "card-body",
                            AreaChart { labels, series: series.clone(), height: 230, money: true }
                            div { class: "row between wrap", style: "margin-top: 10px",
                                div { class: "legend",
                                    for s in series.iter() {
                                        span { key: "{s.name}", span { class: "sw", style: "background: {s.color}" } "{s.name}" }
                                    }
                                }
                                div { class: "row gap-16 small muted",
                                    span { {t("home.avg_basket")} ": " b { class: "num", style: "color: var(--c-text)", "{money_short(k.avg_basket_mtd)}" } }
                                    span { {t("home.orders")} ": " b { class: "num", style: "color: var(--c-text)", "{fmt::num(k.orders_mtd as i64)}" } }
                                }
                            }
                        }
                    }

                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "sparkles", size: 16, class: "tone-accent" } {t("common.insights")} }
                            span { class: "ai-chip", Icon { name: "sparkles", size: 12 } {t("home.updated_now")} }
                        }
                        div { class: "card-body stack gap-8",
                            if insights().is_empty() {
                                Empty { icon: "circle-check", title: t("home.all_good"), text: t("home.all_good_text") }
                            }
                            for (i, ins) in insights().iter().take(6).cloned().enumerate() {
                                div { key: "{i}", class: "insight {ins.tone}",
                                    span { class: "ic", Icon { name: ins.icon, size: 17 } }
                                    div { class: "grow",
                                        div { class: "strong", "{ins.title}" }
                                        div { class: "small muted", style: "margin-top: 2px", "{ins.body}" }
                                    }
                                    button { class: "btn sm", onclick: move |_| go(&ins.route), "{ins.action}" Icon { name: "arrow-right", size: 14 } }
                                }
                            }
                        }
                    }

                    div { class: "grid-2",
                        div { class: "card",
                            div { class: "card-head",
                                div { class: "card-title", Icon { name: "store", size: 16, class: "subtle" } {t("home.branches_month")} }
                            }
                            div { class: "card-body", HBars { items: branch_items } }
                        }
                        div { class: "card",
                            div { class: "card-head",
                                div { class: "card-title", Icon { name: "crown", size: 16, class: "subtle" } {t("home.tiers")} }
                                Link { to: Route::Loyalty {}, class: "btn ghost sm", {t("common.view_all")} }
                            }
                            div { class: "card-body",
                                Donut { slices: tier_slices, center: fmt::num(customers_total as i64), caption: t("common.customers").to_lowercase(), size: 136 }
                            }
                        }
                    }
                }

                div { class: "stack gap-16",
                    TodayAgenda {}
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "repeat", size: 16, class: "tone-success" } {t("nav.refills")} }
                            Link { to: Route::Refills {}, class: "btn ghost sm", {t("common.view_all")} }
                        }
                        div { class: "list", style: "margin-top: 8px",
                            if refills().is_empty() {
                                Empty { icon: "circle-check", title: t("home.no_refills") }
                            }
                            for r in refills().iter().take(5).cloned() {
                                RefillRow { key: "{r.customer_id}-{r.product_id}", r }
                            }
                        }
                        if !refills().is_empty() {
                            div { class: "card-foot",
                                span { class: "small muted", "{refills().len()} " {t("home.refill_people")} }
                                button {
                                    class: "btn soft sm",
                                    onclick: move |_| {
                                        let n = refills.peek().len();
                                        mutate(|db| db.log(crate::state::now(), format!("Telegram: {n} refill reminders"), false));
                                        toast(format!("{} · {n}", t("home.reminders_sent")), "send", "success");
                                    },
                                    Icon { name: "send", size: 14 }
                                    {t("home.remind_all")}
                                }
                            }
                        }
                    }
                    InboxPreview {}
                    DaybookCard {}
                }
            }
        }
    }
}

#[component]
fn RefillRow(r: analytics::RefillDue) -> Element {
    let l = lang();
    let today = today();
    let (name, product) = {
        let db = DB.read();
        (db.customer_name(Some(r.customer_id)), db.product_name(Some(r.product_id)))
    };
    let tone = if r.days_left <= 0 { "danger" } else if r.days_left <= 2 { "warning" } else { "accent" };
    let when = fmt::due_in(r.due, today, l);
    let cid = r.customer_id;
    rsx! {
        div { class: "list-row click", onclick: move |_| go(&format!("/contacts/{cid}")),
            Avatar { name: name.clone(), size: "sm" }
            div { class: "meta",
                span { class: "title truncate small", "{name}" }
                span { class: "sub truncate", "{product}" }
            }
            div { class: "stack gap-4", style: "align-items: flex-end",
                Badge { text: when, tone }
                if !r.in_stock { span { class: "xs tone-danger", {t("home.not_in_stock")} } }
            }
        }
    }
}

#[component]
fn TodayAgenda() -> Element {
    let now = now();
    let today = now.date();
    let items: Vec<(Activity, String)> = {
        let db = DB.read();
        let me = db.settings.me;
        let mut v: Vec<&Activity> =
            db.activities.iter().filter(|a| a.owner_id == me && (a.due.date() == today || (!a.done && a.due.date() < today))).collect();
        v.sort_by_key(|a| (a.done, a.due));
        v.into_iter()
            .take(7)
            .map(|a| {
                let rel = if let Some(c) = a.company_id { db.company_name(Some(c)) } else if let Some(c) = a.customer_id { db.customer_name(Some(c)) } else { String::new() };
                (a.clone(), rel)
            })
            .collect()
    };
    let done = items.iter().filter(|(a, _)| a.done).count();
    let total = items.len();
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "calendar-check", size: 16, class: "tone-accent" } {t("home.today")} }
                span { class: "badge", "{done}/{total}" }
            }
            div { class: "list", style: "margin-top: 8px",
                if items.is_empty() {
                    Empty { icon: "smile", title: t("home.free_day") }
                }
                for (a, rel) in items {
                    {
                        let id = a.id;
                        let overdue = !a.done && a.due < now;
                        let time = if a.due.date() < today { fmt::date(a.due.date(), today, lang()) } else { fmt::time(a.due) };
                        let icon = crm::db::activity_icon(a.kind);
                        let check_cls = if a.done { "check-circle on" } else { "check-circle" };
                        let title_style = if a.done { "text-decoration: line-through; opacity: .55" } else { "" };
                        let time_cls = if overdue { "tone-danger strong" } else { "" };
                        let rel_text = if rel.is_empty() { String::new() } else { format!("· {rel}") };
                        let prio = if matches!(a.priority, Priority::High | Priority::Urgent) && !a.done { Some(t(a.priority.key())) } else { None };
                        let prio_tone = if a.priority == Priority::Urgent { "danger" } else { "warning" };
                        let title = a.title.clone();
                        rsx! {
                            div { key: "{id}", class: "list-row",
                                button {
                                    class: check_cls,
                                    onclick: move |_| {
                                        mutate(|db| db.complete_activity(id, crate::state::now()));
                                    },
                                    Icon { name: "check", size: 13 }
                                }
                                div { class: "meta",
                                    span { class: "title truncate small", style: title_style, "{title}" }
                                    span { class: "sub row gap-4",
                                        Icon { name: icon, size: 12 }
                                        span { class: time_cls, "{time}" }
                                        span { class: "truncate", "{rel_text}" }
                                    }
                                }
                                if let Some(p) = prio {
                                    Badge { text: p, tone: prio_tone }
                                }
                            }
                        }
                    }
                }
            }
            div { class: "card-foot",
                Link { to: Route::Tasks {}, class: "btn ghost sm", Icon { name: "list-todo", size: 14 } {t("common.view_all")} }
                button { class: "btn soft sm", onclick: move |_| UI.write().quick_add = Some(QuickAdd::Task), Icon { name: "plus", size: 14 } {t("common.task")} }
            }
        }
    }
}

#[component]
fn InboxPreview() -> Element {
    let now = now();
    let l = lang();
    let rows: Vec<(Id, String, String, String, u16, &'static str)> = {
        let db = DB.read();
        let mut v: Vec<&Conversation> = db.conversations.iter().filter(|c| c.status != ConvStatus::Resolved).collect();
        v.sort_by(|a, b| b.last_at().cmp(&a.last_at()));
        v.into_iter()
            .take(4)
            .map(|c| {
                (c.id, c.title.clone(), c.last_text().to_string(), c.last_at().map(|a| fmt::relative(a, now, l)).unwrap_or_default(), c.unread, crm::db::channel_icon(c.channel))
            })
            .collect()
    };
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "inbox", size: 16, class: "tone-info" } {t("nav.inbox")} }
                Link { to: Route::Inbox {}, class: "btn ghost sm", {t("common.view_all")} }
            }
            div { class: "list", style: "margin-top: 8px",
                for (id, title, text, when, unread, icon) in rows {
                    div { key: "{id}", class: "list-row click", onclick: move |_| go(&format!("/inbox/{id}")),
                        div { style: "position: relative",
                            Avatar { name: title.clone(), size: "sm" }
                            span { class: "ic info", style: "position:absolute; right:-6px; bottom:-4px; width:16px; height:16px; border-radius:6px; box-shadow:0 0 0 2px var(--c-surface)", Icon { name: icon, size: 10 } }
                        }
                        div { class: "meta",
                            div { class: "row between",
                                span { class: "title truncate small", "{title}" }
                                span { class: "xs subtle nowrap", "{when}" }
                            }
                            span { class: "sub truncate", "{text}" }
                        }
                        if unread > 0 { span { class: "badge accent sm", "{unread}" } }
                    }
                }
            }
        }
    }
}

#[component]
fn DaybookCard() -> Element {
    let (connected, company, last_sync) = {
        let db = DB.read();
        (db.settings.daybook.connected, db.settings.daybook.company_name.clone(), db.settings.daybook.last_sync)
    };
    let l = lang();
    let now = now();
    let title = if connected { company } else { t("home.daybook_title") };
    let sub = if connected {
        format!("{} · {}", t("common.synced"), last_sync.map(|s| fmt::relative(s, now, l)).unwrap_or_default())
    } else {
        t("home.daybook_text")
    };
    let cta = if connected { t("home.daybook_sync") } else { t("common.connect_daybook") };
    let cta_icon = if connected { "refresh-cw" } else { "plug-zap" };
    rsx! {
        div { class: "card tinted pad stack gap-12",
            div { class: "row gap-12",
                span { class: "ic accent", Icon { name: "link-2", size: 17 } }
                div { class: "grow",
                    div { class: "strong", "{title}" }
                    div { class: "small muted", "{sub}" }
                }
            }
            Link { to: Route::DaybookConnect {}, class: "btn primary block",
                Icon { name: cta_icon, size: 16 }
                "{cta}"
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("home.revenue_mtd", "Shu oy tushumi", "Выручка за месяц", "Revenue this month"),
    ("home.active_customers", "Faol mijozlar (90 kun)", "Активные клиенты (90 дн.)", "Active customers (90 days)"),
    ("home.new_this_month", "yangi, shu oy", "новых в этом месяце", "new this month"),
    ("home.weighted_pipeline", "Kutilayotgan bitimlar", "Взвешенная воронка", "Weighted pipeline"),
    ("home.open_deals", "ochiq bitim", "открытых сделок", "open deals"),
    ("home.refills_week", "Shu hafta dori tugaydi", "Лекарства закончатся на неделе", "Refills due this week"),
    ("home.on_waitlist", "defekturada kutmoqda", "ждут в дефектуре", "waiting on the waitlist"),
    ("home.this_period", "Oxirgi 30 kun", "Последние 30 дней", "Last 30 days"),
    ("home.prev_period", "Oldingi 30 kun", "Предыдущие 30 дней", "Previous 30 days"),
    ("home.days_30", "30 kun", "30 дней", "30 days"),
    ("home.months_12", "12 oy", "12 мес.", "12 months"),
    ("home.avg_basket", "O‘rtacha chek", "Средний чек", "Avg basket"),
    ("home.orders", "Xaridlar", "Покупки", "Orders"),
    ("home.updated_now", "hozir yangilandi", "обновлено сейчас", "updated just now"),
    ("home.all_good", "Hammasi joyida", "Всё в порядке", "All clear"),
    ("home.all_good_text", "Hozircha shoshilinch ishlar yo‘q.", "Срочных дел пока нет.", "Nothing urgent right now."),
    ("home.branches_month", "Filiallar, shu oy", "Филиалы за месяц", "Branches this month"),
    ("home.tiers", "Sodiqlik darajalari", "Уровни лояльности", "Loyalty tiers"),
    ("home.no_refills", "Bu hafta tugaydigan dorilar yo‘q", "На этой неделе ничего не заканчивается", "No refills due this week"),
    ("home.refill_people", "mijoz", "клиентов", "customers"),
    ("home.remind_all", "Hammasiga eslatish", "Напомнить всем", "Remind all"),
    ("home.reminders_sent", "Telegram eslatmalar yuborildi", "Напоминания отправлены в Telegram", "Telegram reminders sent"),
    ("home.not_in_stock", "omborda yo‘q", "нет в наличии", "out of stock"),
    ("home.today", "Bugungi ishlarim", "Мои дела на сегодня", "My day"),
    ("home.free_day", "Bugun bo‘sh kun", "Сегодня свободно", "Nothing scheduled today"),
    ("home.daybook_title", "Daybook’ga ulaning", "Подключите Daybook", "Connect to Daybook"),
    ("home.daybook_text", "Filiallar, xodimlar, dorilar va defektura avtomatik keladi; vazifalar Daybook’ga tushadi.", "Филиалы, сотрудники, товары и дефектура подтянутся сами, а задачи уйдут в Daybook.", "Branches, staff, products and the waitlist sync in; tasks flow back to Daybook."),
    ("home.daybook_sync", "Hozir sinxronlash", "Синхронизировать", "Sync now"),
];
