//! Reports: sales, customers, pipeline, marketing, service and team. Every number comes from
//! `crm::analytics` or straight from the data, and every chart uses the shared chart components.

use std::collections::{HashMap, HashSet};

use chrono::{Datelike, Duration, NaiveDate};
use crm::analytics::{self, add_months, month_start};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

const TABS: [(&str, &str, &str); 6] = [
    ("sales", "reports.sales", "wallet"),
    ("customers", "reports.customers", "users"),
    ("pipeline", "reports.pipeline", "square-kanban"),
    ("marketing", "reports.marketing", "megaphone"),
    ("service", "reports.service", "life-buoy"),
    ("team", "reports.team", "trophy"),
];

const COLORS: [&str; 7] = ["var(--c-chart-1)", "var(--c-chart-2)", "var(--c-chart-3)", "var(--c-chart-4)", "var(--c-chart-5)", "var(--c-chart-6)", "var(--c-subtle)"];

/// Short month for chart labels (Uzbek keeps June and July apart: Iyun, Iyul).
fn mon(m: u32, l: Lang) -> String {
    const UZ: [&str; 12] = ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"];
    let i = (m.clamp(1, 12) - 1) as usize;
    match l {
        Lang::Uz => UZ[i].to_string(),
        Lang::UzCyrl => crm::i18n::to_cyrillic(UZ[i]),
        _ => fmt::month_short(m, l),
    }
}

/// Revenue per so‘m spent: "×4.2", or rounded and grouped when large ("×2 827").
fn ratio(revenue: Money, cost: Money) -> String {
    let r = revenue as f64 / cost.max(1) as f64;
    if r >= 10.0 {
        format!("×{}", fmt::num(r.round() as i64))
    } else {
        format!("×{:.1}", r)
    }
}

/// [from, to) for the period select, and the period before it.
fn period_range(p: &str, today: NaiveDate) -> (NaiveDate, NaiveDate, NaiveDate) {
    let m0 = month_start(today);
    let end = today + Duration::days(1);
    match p {
        "last" => (add_months(m0, -1), m0, add_months(m0, -2)),
        "quarter" => {
            let q0 = NaiveDate::from_ymd_opt(today.year(), (today.month0() / 3) * 3 + 1, 1).unwrap_or(m0);
            (q0, end, add_months(q0, -3))
        }
        _ => (m0, end, add_months(m0, -1)),
    }
}

#[component]
fn Card(#[props(into)] title: String, icon: &'static str, #[props(default, into)] extra: String, children: Element) -> Element {
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: icon, size: 16, class: "subtle" } "{title}" }
                if !extra.is_empty() { span { class: "small muted", "{extra}" } }
            }
            div { class: "card-body", {children} }
        }
    }
}

#[component]
pub fn Reports() -> Element {
    let mut tab = use_signal(|| "sales".to_string());
    let mut period = use_signal(|| "month".to_string());
    let mut export = use_signal(|| false);
    let today = today();
    let l = lang();
    let (from, to, _) = period_range(&period(), today);
    let range = format!("{} – {}", fmt::date(from, today, l), fmt::date(to - Duration::days(1), today, l));
    let cur = tab();
    let p = period();
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.reports"), subtitle: range,
                select { class: "select", style: "width: auto", onchange: move |e| period.set(e.value()),
                    option { value: "month", selected: p == "month", {t("common.this_month")} }
                    option { value: "last", selected: p == "last", {t("common.last_month")} }
                    option { value: "quarter", selected: p == "quarter", {t("reports.quarter")} }
                }
                div { class: "popover-anchor",
                    button { class: "btn", onclick: move |_| export.toggle(), Icon { name: "download", size: 16 } span { class: "label-text", {t("common.export")} } }
                    if export() {
                        div { style: "position: fixed; inset: 0; z-index: 39", onclick: move |_| export.set(false) }
                        div { class: "menu", style: "right: 0; top: 42px",
                            button {
                                class: "menu-item",
                                onclick: move |_| {
                                    export.set(false);
                                    toast(t("reports.exported_excel"), "file-spreadsheet", "success");
                                },
                                Icon { name: "file-spreadsheet", size: 16 }
                                "Excel (.xlsx)"
                            }
                            button {
                                class: "menu-item",
                                onclick: move |_| {
                                    export.set(false);
                                    toast(t("reports.exported_pdf"), "file-down", "success");
                                },
                                Icon { name: "file-down", size: 16 }
                                "PDF"
                            }
                        }
                    }
                }
            }
            div { class: "tabs",
                for (key, label, icon) in TABS {
                    button { key: "{key}", class: if cur == key { "tab on" } else { "tab" }, onclick: move |_| tab.set(key.to_string()),
                        Icon { name: icon, size: 15 }
                        {t(label)}
                    }
                }
            }
            {match cur.as_str() {
                "customers" => rsx! { CustomersTab { period: p.clone() } },
                "pipeline" => rsx! { PipelineTab {} },
                "marketing" => rsx! { MarketingTab {} },
                "service" => rsx! { ServiceTab {} },
                "team" => rsx! { TeamTab {} },
                _ => rsx! { SalesTab { period: p.clone() } },
            }}
        }
    }
}

// ---------------------------------------------------------------- sales

#[derive(Clone, Debug, PartialEq)]
struct Sales {
    revenue: Money,
    prev_revenue: Money,
    orders: u32,
    prev_orders: u32,
    buyers: u32,
    by_branch: Vec<(String, Money)>,
    by_channel: Vec<(SaleChannel, Money)>,
    top: Vec<(String, bool, u32, Money)>,
}

#[component]
fn SalesTab(period: String) -> Element {
    let l = lang();
    let p = period.clone();
    let data = use_memo(use_reactive!(|p| {
        let db = DB.read();
        let today = crate::state::today();
        let (from, to, prev_from) = period_range(&p, today);
        let span = (to - from).num_days();
        let prev_to = prev_from + Duration::days(span);
        let mut s = Sales { revenue: 0, prev_revenue: 0, orders: 0, prev_orders: 0, buyers: 0, by_branch: vec![], by_channel: vec![], top: vec![] };
        let mut buyers: HashSet<Id> = HashSet::new();
        let mut branch: HashMap<Id, Money> = HashMap::new();
        let mut channel: HashMap<SaleChannel, Money> = HashMap::new();
        let mut items: HashMap<Id, (u32, Money)> = HashMap::new();
        for pu in &db.purchases {
            let d = pu.at.date();
            if d >= from && d < to {
                s.revenue += pu.total;
                s.orders += 1;
                buyers.insert(pu.customer_id);
                *branch.entry(pu.branch_id).or_default() += pu.total;
                *channel.entry(pu.channel).or_default() += pu.total;
                for i in &pu.items {
                    let e = items.entry(i.product_id).or_default();
                    e.0 += i.qty;
                    e.1 += i.total();
                }
            } else if d >= prev_from && d < prev_to {
                s.prev_revenue += pu.total;
                s.prev_orders += 1;
            }
        }
        s.buyers = buyers.len() as u32;
        let mut b: Vec<(String, Money)> = db.branches.iter().map(|br| (br.name.clone(), branch.get(&br.id).copied().unwrap_or(0))).collect();
        b.sort_by(|x, y| y.1.cmp(&x.1));
        s.by_branch = b;
        let mut c: Vec<(SaleChannel, Money)> = channel.into_iter().collect();
        c.sort_by(|x, y| y.1.cmp(&x.1));
        s.by_channel = c;
        let mut top: Vec<(Id, (u32, Money))> = items.into_iter().collect();
        top.sort_by(|x, y| y.1 .1.cmp(&x.1 .1));
        s.top = top.into_iter().take(8).filter_map(|(id, (q, v))| db.product(id).map(|pr| (pr.name.clone(), pr.rx, q, v))).collect();
        s
    }));
    let monthly = use_memo(move || analytics::monthly_revenue(&DB.read(), crate::state::today(), 12));
    let sources = use_memo(move || analytics::revenue_by_source(&DB.read()));
    let s = data();
    let m = monthly();
    let basket = if s.orders > 0 { s.revenue / s.orders as Money } else { 0 };
    let prev_basket = if s.prev_orders > 0 { s.prev_revenue / s.prev_orders as Money } else { 0 };
    let labels: Vec<String> = m.iter().map(|(d, _, _)| mon(d.month(), l)).collect();
    let series = vec![Series { name: t("metric.revenue"), values: m.iter().map(|x| x.1 as f64).collect(), color: "var(--c-chart-1)", dashed: false }];
    let baskets: Vec<f64> = m.iter().map(|(_, v, n)| if *n > 0 { (*v / *n as Money) as f64 } else { 0.0 }).collect();
    let branch_items: Vec<(String, f64, String)> = s.by_branch.iter().map(|(n, v)| (n.clone(), *v as f64, money_short(*v))).collect();
    let channel_slices: Vec<Slice> = s.by_channel.iter().enumerate().map(|(i, (c, v))| Slice { label: t(c.key()), value: *v as f64, color: COLORS[i % 7].to_string() }).collect();
    let source_items: Vec<(String, f64, String)> = sources().iter().take(7).map(|(src, v, n)| (t(src.key()), *v as f64, format!("{} · {}", money_short(*v), fmt::num(*n as i64)))).collect();
    let year_total: Money = m.iter().map(|x| x.1).sum();
    let rev_delta = analytics::delta(s.revenue as f64, s.prev_revenue as f64);
    let ord_delta = analytics::delta(s.orders as f64, s.prev_orders as f64);
    let basket_delta = analytics::delta(basket as f64, prev_basket as f64);
    let center = fmt::compact(s.revenue as f64, l);
    let top = s.top.clone();
    let rx_label = t("category.rx");
    rsx! {
        div { class: "grid-4",
            Kpi { label: t("metric.revenue"), value: money_short(s.revenue), icon: "wallet", delta: Some(rev_delta), foot: t("reports.vs_prev") }
            Kpi { label: t("reports.orders"), value: fmt::num(s.orders as i64), icon: "receipt", tone: "info", delta: Some(ord_delta), foot: t("reports.vs_prev") }
            Kpi { label: t("reports.avg_basket"), value: money_short(basket), icon: "shopping-bag", tone: "success", delta: Some(basket_delta), foot: t("reports.vs_prev") }
            Kpi { label: t("reports.buyers"), value: fmt::num(s.buyers as i64), icon: "users", tone: "warning", foot: t("reports.unique_buyers") }
        }
        Card { title: t("reports.monthly"), icon: "chart-line", extra: format!("{} · {}", t("reports.year_total"), money_short(year_total)),
            AreaChart { labels: labels.clone(), series, height: 240, money: true }
        }
        div { class: "grid-2",
            Card { title: t("reports.by_branch"), icon: "store", HBars { items: branch_items } }
            Card { title: t("reports.by_channel"), icon: "truck",
                if channel_slices.is_empty() { Empty { icon: "chart-pie", title: t("common.empty") } } else {
                    Donut { slices: channel_slices, center, caption: t("metric.revenue").to_lowercase(), size: 150 }
                }
            }
        }
        div { class: "grid-2",
            Card { title: t("reports.by_source"), icon: "magnet", extra: t("reports.lifetime"), HBars { items: source_items, color: "var(--c-chart-3)" } }
            Card { title: t("reports.basket_trend"), icon: "chart-column", BarChart { labels, values: baskets, height: 200, highlight: Some(11), money: true } }
        }
        div { class: "card",
            div { class: "card-head", div { class: "card-title", Icon { name: "pill", size: 16, class: "subtle" } {t("reports.top_products")} } }
            div { class: "table-wrap", style: "margin-top: 8px",
                table { class: "table responsive",
                    thead { tr { th { {t("common.product")} } th { class: "num", {t("reports.qty")} } th { class: "num", {t("metric.revenue")} } } }
                    tbody {
                        for (k, name, rx, q, v) in top.into_iter().enumerate().map(|(k, (n, r, q, v))| (k + 1, n, r, q, v)) {
                            tr { key: "{k}",
                                td { div { class: "cell-main",
                                    span { class: "badge sm", "{k}" }
                                    span { class: "truncate strong", "{name}" }
                                    if rx { span { class: "badge sm info", "{rx_label}" } }
                                } }
                                td { class: "num m-hide", "{q}" }
                                td { class: "num strong", "{money_short(v)}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- customers

#[component]
fn CustomersTab(period: String) -> Element {
    let l = lang();
    let p = period.clone();
    let k = use_memo(move || analytics::kpis(&DB.read(), crate::state::now()));
    let cohorts = use_memo(move || analytics::cohorts(&DB.read(), crate::state::today(), 8));
    let rfm = use_memo(move || analytics::rfm_breakdown(&DB.read(), crate::state::today()));
    let tiers = use_memo(move || analytics::tier_counts(&DB.read()));
    let extra = use_memo(use_reactive!(|p| {
        let db = DB.read();
        let today = crate::state::today();
        let (from, to, _) = period_range(&p, today);
        let new = db.customers.iter().filter(|c| c.created >= from && c.created < to).count();
        let risk = db.customers.iter().filter(|c| !c.archived && c.orders > 0 && analytics::churn_risk(c, today) >= 50).count();
        // new vs returning buyers, last 6 months
        let m0 = month_start(today);
        let mut buyers: HashMap<NaiveDate, HashSet<Id>> = HashMap::new();
        for pu in &db.purchases {
            let m = month_start(pu.at.date());
            if m >= add_months(m0, -5) {
                buyers.entry(m).or_default().insert(pu.customer_id);
            }
        }
        let months: Vec<(NaiveDate, f64, f64)> = (0..6)
            .map(|i| {
                let m = add_months(m0, i - 5);
                let set = buyers.get(&m).cloned().unwrap_or_default();
                let new = set.iter().filter(|id| db.customer(**id).and_then(|c| c.first_purchase).map(month_start) == Some(m)).count();
                (m, new as f64, (set.len() - new) as f64)
            })
            .collect();
        (new, risk, months)
    }));
    let k = k();
    let (new, risk, months) = extra();
    let tier_colors = ["#c67139", "#8d9aab", "#d9a637", "#7d68b8"];
    let tier_slices: Vec<Slice> = tiers().iter().enumerate().map(|(i, (tier, n, _))| Slice { label: t(tier.key()), value: *n as f64, color: tier_colors[i % 4].to_string() }).collect();
    let rfm_rows = rfm();
    let rfm_total: u32 = rfm_rows.iter().map(|r| r.1).sum::<u32>().max(1);
    let labels: Vec<String> = months.iter().map(|(m, _, _)| mon(m.month(), l)).collect();
    let series = vec![
        Series { name: t("reports.returning"), values: months.iter().map(|x| x.2).collect(), color: "var(--c-chart-1)", dashed: false },
        Series { name: t("reports.new_buyers"), values: months.iter().map(|x| x.1).collect(), color: "var(--c-chart-2)", dashed: true },
    ];
    let legend: Vec<(String, &'static str)> = series.iter().map(|s| (s.name.clone(), s.color)).collect();
    let cols = cohorts().iter().map(|c| c.retention.len()).max().unwrap_or(0).min(7);
    let grid = format!("grid-template-columns: 96px 52px repeat({}, minmax(0, 1fr))", cols.max(1));
    let cohort_rows: Vec<(String, u32, Vec<f64>)> = cohorts().iter().map(|c| (format!("{} {}", mon(c.month.month(), l), c.month.year() % 100), c.size, c.retention.iter().take(cols).cloned().collect())).collect();
    let total = fmt::num(k.customers_total as i64);
    rsx! {
        div { class: "grid-4",
            Kpi { label: t("common.customers"), value: total.clone(), icon: "users", foot: t("reports.in_base") }
            Kpi { label: t("reports.active_90"), value: fmt::num(k.active_customers as i64), icon: "activity", tone: "success", foot: format!("{} {}", fmt::pct(k.repeat_rate, l), t("reports.repeat")) }
            Kpi { label: t("reports.new_customers"), value: fmt::num(new as i64), icon: "user-plus", tone: "info", foot: t("reports.in_period") }
            Kpi { label: t("reports.at_risk"), value: fmt::num(risk as i64), icon: "triangle-alert", tone: "danger", foot: t("reports.at_risk_foot"), onclick: move |_| go("/contacts?rfm=at_risk") }
        }
        Card { title: t("reports.cohorts"), icon: "layout-grid", extra: t("reports.cohorts_hint"),
            div { class: "table-wrap",
                div { class: "heat", style: "{grid}; min-width: 560px",
                    div { class: "xs subtle upper", style: "align-self: center", {t("reports.cohort")} }
                    div { class: "xs subtle upper right", style: "align-self: center", {t("reports.size")} }
                    for i in 1..=cols {
                        div { key: "h{i}", class: "xs subtle center strong", style: "align-self: center", "+{i}" }
                    }
                    for (label, size, ret) in cohort_rows {
                        div { key: "l{label}", class: "small strong", style: "align-self: center", "{label}" }
                        div { class: "small muted num right", style: "align-self: center", "{size}" }
                        for i in 0..cols {
                            {
                                let v = ret.get(i).copied();
                                let (bg, fg, text) = match v {
                                    Some(p) if size > 0 => {
                                        let mix = (p * 0.95).clamp(8.0, 92.0);
                                        let fg = if mix > 48.0 { "var(--c-on-primary)" } else { "var(--c-text)" };
                                        (format!("color-mix(in srgb, var(--c-primary) {mix:.0}%, var(--c-surface-2))"), fg, format!("{p:.0}%"))
                                    }
                                    _ => ("transparent".to_string(), "var(--c-subtle)", String::new()),
                                };
                                rsx! { div { key: "c{label}{i}", class: "heat-cell", style: "background: {bg}; color: {fg}", "{text}" } }
                            }
                        }
                    }
                }
            }
        }
        div { class: "grid-2",
            Card { title: t("reports.rfm"), icon: "layers",
                div { class: "stack gap-8",
                    for (seg, n, v) in rfm_rows.iter().cloned() {
                        {
                            let share = n as f64 / rfm_total as f64 * 100.0;
                            let tone = seg.tone();
                            let slug = seg.slug();
                            let label = t(seg.key());
                            let bar: &'static str = match tone {
                                "danger" => "danger",
                                "warning" => "warning",
                                "success" => "success",
                                _ => "",
                            };
                            rsx! {
                                div { key: "{slug}", class: "row gap-12", style: "cursor: pointer", onclick: move |_| go(&format!("/contacts?rfm={slug}")),
                                    div { style: "width: 150px; flex: 0 0 150px", Badge { text: label, tone, dot: true } }
                                    div { class: "grow", Progress { pct: share, tone: bar, thin: true } }
                                    span { class: "small strong num nowrap", style: "width: 34px; text-align: right", "{n}" }
                                    span { class: "xs muted num nowrap hide-mobile", style: "width: 78px; text-align: right", "{money_short(v)}" }
                                }
                            }
                        }
                    }
                }
            }
            Card { title: t("home.tiers"), icon: "crown",
                Donut { slices: tier_slices, center: total, caption: t("common.customers").to_lowercase(), size: 150 }
            }
        }
        Card { title: t("reports.new_vs_returning"), icon: "users-round",
            AreaChart { labels, series, height: 220 }
            div { class: "legend", style: "margin-top: 10px",
                for (name, color) in legend {
                    span { key: "{name}", span { class: "sw", style: "background: {color}" } "{name}" }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- pipeline

#[component]
fn PipelineTab() -> Element {
    let l = lang();
    let k = use_memo(move || analytics::kpis(&DB.read(), crate::state::now()))();
    let funnels = use_memo(move || {
        let db = DB.read();
        db.pipelines.iter().map(|p| (p.id, p.name.clone(), p.icon.clone(), analytics::funnel(&db, p.id))).collect::<Vec<_>>()
    })();
    let forecast = use_memo(move || analytics::forecast(&DB.read(), crate::state::today(), 6))();
    let lost = use_memo(move || analytics::lost_reasons(&DB.read()))();
    let labels: Vec<String> = forecast.iter().map(|(m, _, _)| mon(m.month(), l)).collect();
    let series = vec![
        Series { name: t("reports.weighted"), values: forecast.iter().map(|x| x.1 as f64).collect(), color: "var(--c-chart-1)", dashed: false },
        Series { name: t("reports.best_case"), values: forecast.iter().map(|x| x.2 as f64).collect(), color: "var(--c-chart-3)", dashed: true },
    ];
    let legend: Vec<(String, &'static str)> = series.iter().map(|s| (s.name.clone(), s.color)).collect();
    let lost_items: Vec<(String, f64, String)> = lost.iter().take(7).map(|(r, n)| (r.clone(), *n as f64, fmt::num(*n as i64))).collect();
    rsx! {
        div { class: "grid-4",
            Kpi { label: t("reports.open_pipeline"), value: money_short(k.open_pipeline), icon: "square-kanban", foot: format!("{} {}", k.open_deals, t("reports.open_deals")) }
            Kpi { label: t("reports.weighted"), value: money_short(k.weighted_pipeline), icon: "scale", tone: "info", foot: t("reports.weighted_foot") }
            Kpi { label: t("reports.win_rate"), value: fmt::pct(k.win_rate, l), icon: "target", tone: "success", foot: t("reports.win_rate_foot") }
            Kpi { label: t("reports.won_month"), value: money_short(k.won_mtd), icon: "trophy", tone: "warning", foot: format!("{} {}", k.won_count_mtd, t("reports.deals_lc")) }
        }
        div { class: "grid-2",
            for (pid, name, icon, stages) in funnels {
                {
                    let total: Money = stages.iter().map(|s| s.value).sum();
                    let rows: Vec<(String, u32, String, u16)> = stages.iter().map(|s| (s.name.clone(), s.count, money_short(s.value), s.hue)).collect();
                    let extra = money_short(total);
                    let ic: &'static str = match icon.as_str() {
                        "building-2" => "building-2",
                        "hospital" => "hospital",
                        "briefcase" => "briefcase",
                        "store" => "store",
                        _ => "funnel",
                    };
                    rsx! {
                        div { key: "{pid}",
                            Card { title: name.clone(), icon: ic, extra,
                                if rows.iter().all(|r| r.1 == 0) { Empty { icon: "funnel", title: t("common.empty") } } else { Funnel { stages: rows } }
                            }
                        }
                    }
                }
            }
        }
        div { class: "grid-2",
            Card { title: t("reports.forecast"), icon: "chart-line",
                AreaChart { labels, series, height: 210, money: true }
                div { class: "legend", style: "margin-top: 10px",
                    for (name, color) in legend {
                        span { key: "{name}", span { class: "sw", style: "background: {color}" } "{name}" }
                    }
                }
            }
            Card { title: t("reports.lost_reasons"), icon: "circle-x",
                if lost_items.is_empty() { Empty { icon: "circle-check", title: t("common.empty") } } else { HBars { items: lost_items, color: "var(--c-chart-5)" } }
            }
        }
    }
}

// ---------------------------------------------------------------- marketing

#[component]
fn MarketingTab() -> Element {
    let l = lang();
    let campaigns: Vec<Campaign> = DB.read().campaigns.iter().filter(|c| c.sent > 0).cloned().collect();
    let sent: u32 = campaigns.iter().map(|c| c.sent).sum();
    let revenue: Money = campaigns.iter().map(|c| c.revenue).sum();
    let cost: Money = campaigns.iter().map(|c| c.cost).sum();
    let conv: u32 = campaigns.iter().map(|c| c.converted).sum();
    let roi = if cost > 0 { ratio(revenue, cost) } else { "—".into() };
    // per channel: revenue per 1 000 messages
    let mut by: Vec<(Channel, u32, Money, u32)> = Vec::new();
    for c in &campaigns {
        if let Some(e) = by.iter_mut().find(|x| x.0 == c.channel) {
            e.1 += c.sent;
            e.2 += c.revenue;
            e.3 += c.converted;
        } else {
            by.push((c.channel, c.sent, c.revenue, c.converted));
        }
    }
    by.sort_by(|a, b| (b.2 as f64 / b.1.max(1) as f64).partial_cmp(&(a.2 as f64 / a.1.max(1) as f64)).unwrap_or(std::cmp::Ordering::Equal));
    let channel_items: Vec<(String, f64, String)> = by
        .iter()
        .map(|(ch, s, r, _)| {
            let per = *r as f64 / (*s).max(1) as f64 * 1000.0;
            (t(ch.key()), per, money_short(per as Money))
        })
        .collect();
    let best = by.first().map(|(ch, s, r, cv)| (t(ch.key()), fmt::pct(*cv as f64 / (*s).max(1) as f64 * 100.0, l), money_short((*r as f64 / (*s).max(1) as f64 * 1000.0) as Money)));
    let mut rows = campaigns.clone();
    rows.sort_by(|a, b| b.revenue.cmp(&a.revenue));
    rsx! {
        div { class: "grid-4",
            Kpi { label: t("reports.messages"), value: fmt::num(sent as i64), icon: "send", foot: format!("{} {}", campaigns.len(), t("reports.campaigns_lc")) }
            Kpi { label: t("reports.conversions"), value: fmt::num(conv as i64), icon: "shopping-bag", tone: "success", foot: fmt::pct(conv as f64 / sent.max(1) as f64 * 100.0, l) }
            Kpi { label: t("reports.attributed"), value: money_short(revenue), icon: "wallet", tone: "warning", foot: t("reports.attributed_foot") }
            Kpi { label: "ROI", value: roi, icon: "trending-up", tone: "info", foot: format!("{} {}", t("reports.sms_cost"), money_short(cost)) }
        }
        if let Some((ch, rate, per)) = best {
            div { class: "insight success",
                span { class: "ic", Icon { name: "trophy", size: 17 } }
                div { class: "grow",
                    div { class: "strong", {t("reports.best_channel").replace("{c}", &ch)} }
                    div { class: "small muted", style: "margin-top: 2px", {t("reports.best_channel_text").replace("{r}", &rate).replace("{m}", &per)} }
                }
            }
        }
        div { class: "grid-main",
            div { class: "card",
                div { class: "card-head", div { class: "card-title", Icon { name: "megaphone", size: 16, class: "subtle" } {t("reports.campaigns")} } }
                div { class: "table-wrap", style: "margin-top: 8px",
                    table { class: "table responsive",
                        thead { tr {
                            th { {t("common.campaign")} }
                            th { class: "num", {t("campaigns.f_sent")} }
                            th { class: "num", {t("campaigns.read_rate")} }
                            th { class: "num", {t("campaigns.f_converted")} }
                            th { class: "num", {t("metric.revenue")} }
                            th { class: "num", "ROI" }
                        } }
                        tbody {
                            for c in rows {
                                {
                                    let id = c.id;
                                    let read = if c.channel == Channel::Sms { "—".to_string() } else { fmt::pct(c.read as f64 / c.sent.max(1) as f64 * 100.0, l) };
                                    let roi = if c.cost > 0 { ratio(c.revenue, c.cost) } else { t("campaigns.free") };
                                    let icon = crm::db::channel_icon(c.channel);
                                    let sent = fmt::num(c.sent as i64);
                                    rsx! {
                                        tr { key: "{id}", class: "click", onclick: move |_| go(&format!("/campaigns/{id}")),
                                            td { div { class: "cell-main",
                                                span { class: "ic info sm", Icon { name: icon, size: 14 } }
                                                span { class: "truncate strong", style: "max-width: 280px", "{c.name}" }
                                            } }
                                            td { class: "num m-hide", "{sent}" }
                                            td { class: "num m-hide", "{read}" }
                                            td { class: "num m-hide", "{c.converted}" }
                                            td { class: "num strong", "{money_short(c.revenue)}" }
                                            td { class: "num m-hide", "{roi}" }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Card { title: t("reports.per_1000"), icon: "chart-column",
                HBars { items: channel_items, color: "var(--c-chart-2)" }
                p { class: "xs muted", style: "margin-top: 12px", {t("reports.per_1000_hint")} }
            }
        }
    }
}

// ---------------------------------------------------------------- service

#[component]
fn ServiceTab() -> Element {
    let l = lang();
    let data = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let open = db.tickets.iter().filter(|t| t.is_open()).count();
        let resolved: Vec<&Ticket> = db.tickets.iter().filter(|t| t.resolved.is_some()).collect();
        let on_time = resolved.iter().filter(|t| t.resolved.map_or(false, |r| r <= t.due)).count();
        let breached_open = db.tickets.iter().filter(|t| t.breached(now)).count();
        let considered = resolved.len() + breached_open;
        let sla = if considered > 0 { on_time as f64 / considered as f64 * 100.0 } else { 100.0 };
        let hours: Vec<f64> = resolved.iter().filter_map(|t| t.resolved.map(|r| (r - t.created).num_minutes() as f64 / 60.0)).collect();
        let avg_h = if hours.is_empty() { 0.0 } else { hours.iter().sum::<f64>() / hours.len() as f64 };
        let csats: Vec<u8> = db.tickets.iter().filter_map(|t| t.csat).collect();
        let csat = if csats.is_empty() { 0.0 } else { csats.iter().map(|x| *x as f64).sum::<f64>() / csats.len() as f64 };
        let kinds: Vec<(TicketKind, usize)> = TicketKind::ALL.iter().map(|k| (*k, db.tickets.iter().filter(|t| t.kind == *k).count())).filter(|x| x.1 > 0).collect();
        let scores: Vec<u8> = db.customers.iter().filter_map(|c| c.nps).collect();
        let pro = scores.iter().filter(|s| **s >= 9).count();
        let det = scores.iter().filter(|s| **s <= 6).count();
        let pas = scores.len() - pro - det;
        let adverse = db.tickets.iter().filter(|t| t.kind == TicketKind::AdverseReaction).count();
        let reported = db.tickets.iter().filter(|t| t.kind == TicketKind::AdverseReaction && t.reported_to_regulator).count();
        (open, sla, avg_h, csat, csats.len(), kinds, (pro, pas, det), adverse, reported)
    });
    let (open, sla, avg_h, csat, csat_n, kinds, (pro, pas, det), adverse, reported) = data();
    let k = use_memo(move || analytics::kpis(&DB.read(), crate::state::now()))();
    let slices: Vec<Slice> = kinds.iter().enumerate().map(|(i, (kind, n))| Slice { label: t(kind.key()), value: *n as f64, color: COLORS[i % 7].to_string() }).collect();
    let total: usize = kinds.iter().map(|x| x.1).sum();
    let nps_n = (pro + pas + det).max(1) as f64;
    let parts: Vec<(String, usize, &'static str, f64)> = vec![
        (t("reports.promoters"), pro, "var(--c-success)", pro as f64 / nps_n * 100.0),
        (t("reports.passives"), pas, "var(--c-warning)", pas as f64 / nps_n * 100.0),
        (t("reports.detractors"), det, "var(--c-danger)", det as f64 / nps_n * 100.0),
    ];
    let nps = format!("{:+.0}", k.nps);
    let hours_text = match l {
        Lang::Ru => format!("{:.1} ч", avg_h).replace('.', ","),
        Lang::En => format!("{:.1} h", avg_h),
        _ => uz(format!("{:.1} soat", avg_h).replace('.', ",")),
    };
    let csat_text = if csat_n > 0 {
        let v = format!("{:.1}", csat);
        format!("{} / 5", if l == Lang::En { v } else { v.replace('.', ",") })
    } else {
        "—".into()
    };
    let sla_tone: &'static str = if sla >= 90.0 { "success" } else if sla >= 75.0 { "warning" } else { "danger" };
    let adverse_line = t("reports.adverse_text").replace("{n}", &adverse.to_string()).replace("{r}", &reported.to_string());
    rsx! {
        div { class: "grid-4",
            Kpi { label: t("reports.open_tickets"), value: fmt::num(open as i64), icon: "life-buoy", foot: format!("{} {}", k.breached, t("reports.breached_lc")), onclick: move |_| go("/tickets") }
            Kpi { label: t("reports.sla"), value: fmt::pct(sla, l), icon: "timer", tone: sla_tone, foot: t("reports.sla_foot") }
            Kpi { label: t("reports.resolution"), value: hours_text, icon: "clock", tone: "info", foot: t("reports.resolution_foot") }
            Kpi { label: "CSAT", value: csat_text, icon: "smile", tone: "success", foot: format!("{} {}", csat_n, t("reports.ratings")) }
        }
        div { class: "grid-2",
            Card { title: t("reports.by_kind"), icon: "chart-pie",
                Donut { slices, center: fmt::num(total as i64), caption: t("reports.tickets_lc"), size: 150 }
            }
            Card { title: "NPS", icon: "thumbs-up",
                div { class: "stack gap-16",
                    div { class: "row gap-12",
                        span { class: "kpi-value", style: "font-size: 40px", "{nps}" }
                        span { class: "small muted", {t("reports.nps_hint")} }
                    }
                    div { class: "stackbar", style: "height: 14px",
                        for (label, _, color, w) in parts.iter().cloned() {
                            span { key: "{label}", style: "width: {w:.1}%; background: {color}" }
                        }
                    }
                    div { class: "legend",
                        for (label, n, color, _) in parts {
                            span { key: "l{label}", span { class: "sw", style: "background: {color}" } "{label} · {n}" }
                        }
                    }
                }
            }
        }
        div { class: "insight danger",
            span { class: "ic", Icon { name: "triangle-alert", size: 17 } }
            div { class: "grow",
                div { class: "strong", {t("reports.adverse_title")} }
                div { class: "small muted", style: "margin-top: 2px", "{adverse_line}" }
            }
            button { class: "btn sm", onclick: move |_| go("/tickets"), {t("nav.tickets")} Icon { name: "arrow-right", size: 14 } }
        }
    }
}

// ---------------------------------------------------------------- team

#[component]
fn TeamTab() -> Element {
    let rows = use_memo(move || {
        let db = DB.read();
        analytics::leaderboard(&db, crate::state::today())
            .into_iter()
            .map(|r| {
                let s = db.staff_member(r.staff_id);
                (r.clone(), s.map(|s| s.name.clone()).unwrap_or_default(), s.map(|s| s.hue).unwrap_or(24), s.map(|s| t(s.role.key())).unwrap_or_default(), db.branch_name(s.and_then(|s| s.branch_id)))
            })
            .collect::<Vec<_>>()
    })();
    let max = rows.iter().map(|r| r.0.score).max().unwrap_or(1).max(1) as f64;
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "trophy", size: 16, class: "tone-warning" } {t("reports.leaderboard")} }
                button { class: "btn ghost sm", onclick: move |_| go("/goals"), {t("nav.goals")} Icon { name: "arrow-right", size: 14 } }
            }
            div { class: "table-wrap", style: "margin-top: 8px",
                table { class: "table responsive",
                    thead { tr {
                        th { "#" }
                        th { {t("reports.employee")} }
                        th { class: "num", {t("metric.deals_won")} }
                        th { class: "num", {t("metric.calls")} }
                        th { class: "num", {t("reports.tasks")} }
                        th { class: "num", {t("metric.new_customers")} }
                        th { {t("reports.score")} }
                    } }
                    tbody {
                        for (i, (r, name, hue, role, branch)) in rows.into_iter().enumerate() {
                            {
                                let pct = r.score as f64 / max * 100.0;
                                let won = if r.won_value > 0 { money_short(r.won_value) } else { "—".to_string() };
                                let rank = i + 1;
                                let sub = if branch == "—" { role.clone() } else { format!("{role} · {branch}") };
                                rsx! {
                                    tr { key: "{r.staff_id}",
                                        td { class: "m-hide", span { class: "badge sm", "{rank}" } }
                                        td { div { class: "cell-main",
                                            Avatar { name: name.clone(), hue: Some(hue), size: "sm" }
                                            div { class: "stack", style: "gap: 0; min-width: 0",
                                                span { class: "strong truncate", "{name}" }
                                                span { class: "xs muted truncate", "{sub}" }
                                            }
                                        } }
                                        td { class: "num m-hide", "{won}" }
                                        td { class: "num m-hide", "{r.calls}" }
                                        td { class: "num m-hide", "{r.tasks_done}" }
                                        td { class: "num m-hide", "{r.customers}" }
                                        td { div { class: "row gap-8", style: "min-width: 120px",
                                            div { class: "grow", Progress { pct, thin: true } }
                                            span { class: "strong num small", "{r.score}" }
                                        } }
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

pub const STRINGS: &[Entry] = &[
    ("reports.sales", "Savdo", "Продажи", "Sales"),
    ("reports.customers", "Mijozlar", "Клиенты", "Customers"),
    ("reports.pipeline", "Bitimlar", "Воронка", "Pipeline"),
    ("reports.marketing", "Marketing", "Маркетинг", "Marketing"),
    ("reports.service", "Xizmat", "Сервис", "Service"),
    ("reports.team", "Jamoa", "Команда", "Team"),
    ("reports.quarter", "Shu chorak", "Этот квартал", "This quarter"),
    ("reports.exported_excel", "Hisobot Excel faylga tayyorlandi", "Отчёт выгружен в Excel", "Report exported to Excel"),
    ("reports.exported_pdf", "Hisobot PDF faylga tayyorlandi", "Отчёт выгружен в PDF", "Report exported to PDF"),
    ("reports.vs_prev", "oldingi davrga nisbatan", "к прошлому периоду", "vs the previous period"),
    ("reports.orders", "Xaridlar", "Покупки", "Orders"),
    ("reports.avg_basket", "O‘rtacha chek", "Средний чек", "Avg basket"),
    ("reports.buyers", "Xaridorlar", "Покупатели", "Buyers"),
    ("reports.unique_buyers", "takrorlanmas mijozlar", "уникальных клиентов", "unique customers"),
    ("reports.monthly", "Tushum, 12 oy", "Выручка за 12 месяцев", "Revenue, 12 months"),
    ("reports.year_total", "Jami", "Всего", "Total"),
    ("reports.by_branch", "Filiallar bo‘yicha", "По филиалам", "By branch"),
    ("reports.by_channel", "Savdo kanallari", "Каналы продаж", "Sales channels"),
    ("reports.by_source", "Mijoz manbalari bo‘yicha", "По источникам клиентов", "By acquisition source"),
    ("reports.lifetime", "butun davr", "за всё время", "lifetime"),
    ("reports.basket_trend", "O‘rtacha chek dinamikasi", "Динамика среднего чека", "Average basket trend"),
    ("reports.top_products", "Eng ko‘p sotilgan dorilar", "Самые продаваемые товары", "Top products"),
    ("reports.qty", "Soni", "Кол-во", "Qty"),
    ("reports.in_base", "bazada", "в базе", "in the base"),
    ("reports.active_90", "Faol (90 kun)", "Активные (90 дн.)", "Active (90 days)"),
    ("reports.repeat", "qayta xarid", "повторные покупки", "repeat buyers"),
    ("reports.new_customers", "Yangi mijozlar", "Новые клиенты", "New customers"),
    ("reports.in_period", "tanlangan davrda", "за выбранный период", "in the selected period"),
    ("reports.at_risk", "Ketish xavfi", "Риск оттока", "Churn risk"),
    ("reports.at_risk_foot", "odatdagidan ancha kech qolmoqda", "сильно выбились из своего ритма", "well behind their usual rhythm"),
    ("reports.cohorts", "Kogortalar: qaytib kelish", "Когорты: возвращаемость", "Cohort retention"),
    ("reports.cohorts_hint", "birinchi xarid oyidan keyin qaytganlar ulushi", "доля вернувшихся после месяца первой покупки", "share coming back after the first-purchase month"),
    ("reports.cohort", "Kogorta", "Когорта", "Cohort"),
    ("reports.size", "Hajmi", "Размер", "Size"),
    ("reports.rfm", "RFM segmentlari", "RFM-сегменты", "RFM segments"),
    ("reports.new_vs_returning", "Yangi va qaytgan xaridorlar", "Новые и вернувшиеся покупатели", "New vs returning buyers"),
    ("reports.returning", "Qaytganlar", "Вернувшиеся", "Returning"),
    ("reports.new_buyers", "Yangilar", "Новые", "New"),
    ("reports.open_pipeline", "Ochiq bitimlar", "Открытая воронка", "Open pipeline"),
    ("reports.open_deals", "ta ochiq bitim", "открытых сделок", "open deals"),
    ("reports.weighted", "Ehtimol bilan", "Взвешенная", "Weighted"),
    ("reports.weighted_foot", "bosqich ehtimoliga ko‘ra", "с учётом вероятности этапа", "by stage probability"),
    ("reports.win_rate", "Yutish darajasi", "Доля выигранных", "Win rate"),
    ("reports.win_rate_foot", "oxirgi 90 kun", "за 90 дней", "last 90 days"),
    ("reports.won_month", "Shu oy yutildi", "Выиграно за месяц", "Won this month"),
    ("reports.deals_lc", "ta bitim", "сделок", "deals"),
    ("reports.best_case", "Eng yaxshi holat", "Лучший сценарий", "Best case"),
    ("reports.forecast", "Prognoz, 6 oy", "Прогноз на 6 месяцев", "Forecast, 6 months"),
    ("reports.lost_reasons", "Boy berish sabablari", "Причины проигрыша", "Lost reasons"),
    ("reports.messages", "Yuborilgan xabarlar", "Отправлено сообщений", "Messages sent"),
    ("reports.campaigns_lc", "ta kampaniya", "рассылок", "campaigns"),
    ("reports.conversions", "Xarid qilganlar", "Конверсии", "Conversions"),
    ("reports.attributed", "Kampaniyalar tushumi", "Выручка рассылок", "Attributed revenue"),
    ("reports.attributed_foot", "xabardan keyin 7 kun ichida", "в течение 7 дней после сообщения", "within 7 days of the message"),
    ("reports.sms_cost", "SMS xarajati", "Расходы на SMS", "SMS cost"),
    ("reports.best_channel", "Eng foydali kanal: {c}", "Самый выгодный канал: {c}", "Best channel: {c}"),
    ("reports.best_channel_text", "Konversiya {r}, har 1 000 xabarga {m} tushum.", "Конверсия {r}, {m} выручки на 1 000 сообщений.", "{r} conversion, {m} of revenue per 1,000 messages."),
    ("reports.campaigns", "Kampaniyalar natijasi", "Результаты рассылок", "Campaign results"),
    ("reports.per_1000", "1 000 xabarga tushum", "Выручка на 1 000 сообщений", "Revenue per 1,000 messages"),
    ("reports.per_1000_hint", "Kanallarni adolatli solishtirish uchun: auditoriya hajmidan qat’i nazar.", "Чтобы честно сравнивать каналы независимо от размера аудитории.", "A fair comparison of channels whatever the audience size."),
    ("reports.open_tickets", "Ochiq murojaatlar", "Открытые обращения", "Open tickets"),
    ("reports.breached_lc", "ta muddati o‘tgan", "просрочено", "past SLA"),
    ("reports.sla", "SLA bajarilishi", "Соблюдение SLA", "SLA compliance"),
    ("reports.sla_foot", "o‘z vaqtida hal qilinganlar", "решено вовремя", "resolved on time"),
    ("reports.resolution", "O‘rtacha hal qilish", "Среднее время решения", "Avg resolution"),
    ("reports.resolution_foot", "murojaatdan yechimgacha", "от обращения до решения", "from report to resolution"),
    ("reports.ratings", "ta baho", "оценок", "ratings"),
    ("reports.by_kind", "Murojaat turlari", "Типы обращений", "Tickets by kind"),
    ("reports.tickets_lc", "murojaat", "обращений", "tickets"),
    ("reports.nps_hint", "tavsiya qilishga tayyorlik, −100 dan +100 gacha", "готовность рекомендовать, от −100 до +100", "willingness to recommend, −100 to +100"),
    ("reports.promoters", "Tarafdorlar", "Промоутеры", "Promoters"),
    ("reports.passives", "Betaraflar", "Нейтралы", "Passives"),
    ("reports.detractors", "Tanqidchilar", "Критики", "Detractors"),
    ("reports.adverse_title", "Nojo‘ya ta’sirlar nazoratda", "Нежелательные реакции под контролем", "Adverse reactions under control"),
    ("reports.adverse_text", "Jami {n} ta xabar, {r} tasi farmakonazoratga yuborilgan. Har biriga 4 soatlik SLA.", "Всего {n} сообщений, {r} передано в фармаконадзор. На каждое SLA 4 часа.", "{n} reports in total, {r} sent to pharmacovigilance. A 4-hour SLA on each."),
    ("reports.leaderboard", "Reyting, shu oy", "Рейтинг за месяц", "Leaderboard, this month"),
    ("reports.employee", "Xodim", "Сотрудник", "Employee"),
    ("reports.tasks", "Vazifalar", "Задачи", "Tasks"),
    ("reports.score", "Ball", "Баллы", "Score"),
];
