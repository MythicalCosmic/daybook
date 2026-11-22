//! Products: the pharmacy catalogue with stock in every branch, the nearest expiry and the
//! loyalty flags. A product's drawer shows who buys it, regular-therapy demand, the waitlist,
//! and sends a purchase request to Daybook.

use std::collections::HashMap;

use chrono::{Duration, NaiveDate};
use crm::fmt;
use crm::i18n::Entry;
use crm::model::*;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

#[derive(Clone, PartialEq)]
struct Row {
    id: Id,
    name: String,
    generic: String,
    form: String,
    maker: String,
    category: ProductCategory,
    rx: bool,
    price: Money,
    /// Stock per branch, in branch order.
    stock: Vec<(String, u32)>,
    total: u32,
    expiry: NaiveDate,
    days_to_expiry: i64,
    no_bonus: bool,
    low: bool,
    waiting: usize,
    regular: usize,
    barcode: String,
}

fn parse_id(hint: &str) -> Option<Id> {
    hint.split('&').find_map(|p| p.strip_prefix("id=")).and_then(|v| v.parse().ok())
}

fn expiry_tone(days: i64) -> &'static str {
    if days < 60 {
        "danger"
    } else if days < 120 {
        "warning"
    } else {
        ""
    }
}

#[component]
pub fn Products() -> Element {
    let l = lang();
    let rows = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let mut waiting: HashMap<Id, usize> = HashMap::new();
        for w in db.waitlist.iter().filter(|w| matches!(w.status, WaitStatus::Waiting | WaitStatus::Arrived | WaitStatus::Notified | WaitStatus::Reserved)) {
            if let Some(p) = w.product_id {
                *waiting.entry(p).or_default() += 1;
            }
        }
        let mut regular: HashMap<Id, usize> = HashMap::new();
        for c in db.customers.iter().filter(|c| !c.archived) {
            for g in &c.regimens {
                *regular.entry(g.product_id).or_default() += 1;
            }
        }
        db.products
            .iter()
            .map(|p| {
                let stock: Vec<(String, u32)> = db.branches.iter().map(|b| (b.name.clone(), p.stock_at(b.id))).collect();
                let total = p.total_stock();
                Row {
                    id: p.id,
                    name: p.name.clone(),
                    generic: p.generic.clone(),
                    form: p.form.clone(),
                    maker: p.maker.clone(),
                    category: p.category,
                    rx: p.rx,
                    price: p.price,
                    low: total <= 10 || stock.iter().any(|s| s.1 == 0),
                    stock,
                    total,
                    expiry: p.expiry,
                    days_to_expiry: (p.expiry - today).num_days(),
                    no_bonus: p.no_bonus,
                    waiting: waiting.get(&p.id).copied().unwrap_or(0),
                    regular: regular.get(&p.id).copied().unwrap_or(0),
                    barcode: p.barcode.clone(),
                }
            })
            .collect::<Vec<Row>>()
    });
    let mut q = use_signal(String::new);
    let mut cat = use_signal(|| None::<ProductCategory>);
    let mut rx = use_signal(|| "all".to_string());
    let mut low = use_signal(|| false);
    let mut expiring = use_signal(|| false);
    let mut sort = use_signal(|| ("name".to_string(), false));
    let mut limit = use_signal(|| 60usize);
    let mut sel = use_signal(|| None::<Id>);
    // a link such as "/products?id=12" (search results, other screens) opens that product
    use_effect(move || {
        let wants = UI.read().hint.as_deref().map(|h| h.contains("id=")).unwrap_or(false);
        if wants {
            if let Some(id) = take_hint().and_then(|h| parse_id(&h)) {
                sel.set(Some(id));
            }
        }
    });

    let (connected, last_sync, branches_n) = {
        let db = DB.read();
        (db.settings.daybook.connected, db.settings.daybook.last_sync, db.branches.len())
    };
    let all = rows();
    let ql = q().trim().to_lowercase();
    let base: Vec<&Row> = all
        .iter()
        .filter(|r| match rx().as_str() {
            "rx" => r.rx,
            "otc" => !r.rx,
            _ => true,
        })
        .filter(|r| !low() || r.low)
        .filter(|r| !expiring() || r.days_to_expiry < 120)
        .filter(|r| {
            ql.is_empty()
                || r.name.to_lowercase().contains(&ql)
                || r.generic.to_lowercase().contains(&ql)
                || r.maker.to_lowercase().contains(&ql)
                || r.barcode.contains(&ql)
        })
        .collect();
    let cat_counts: Vec<(ProductCategory, usize)> =
        ProductCategory::ALL.iter().map(|c| (*c, base.iter().filter(|r| r.category == *c).count())).filter(|x| x.1 > 0).collect();
    let mut shown: Vec<Row> = base.iter().filter(|r| cat().map_or(true, |c| r.category == c)).map(|r| (*r).clone()).collect();
    let (key, desc) = sort();
    shown.sort_by(|a, b| {
        let o = match key.as_str() {
            "price" => a.price.cmp(&b.price),
            "stock" => a.total.cmp(&b.total),
            "expiry" => a.expiry.cmp(&b.expiry),
            "demand" => (a.waiting * 3 + a.regular).cmp(&(b.waiting * 3 + b.regular)),
            _ => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
        };
        if desc {
            o.reverse()
        } else {
            o
        }
    });
    let total_n = shown.len();
    let cut = if total_n > 80 { limit() } else { total_n };
    let hidden = total_n.saturating_sub(cut);
    let visible: Vec<Row> = shown.into_iter().take(cut).collect();
    let low_n = all.iter().filter(|r| r.low).count();
    let exp_n = all.iter().filter(|r| r.days_to_expiry < 120).count();
    let stock_max = all.iter().flat_map(|r| r.stock.iter().map(|s| s.1)).max().unwrap_or(1).max(1);
    let subtitle = t("products.sub").replace("{n}", &all.len().to_string()).replace("{m}", &branches_n.to_string());
    let sync_text = if connected {
        let when = last_sync.map(|s| fmt::relative(s, now(), l)).unwrap_or_default();
        format!("{} · {}", t("products.synced"), t("products.last_sync").replace("{t}", &when))
    } else {
        t("products.demo_banner")
    };
    let more_label = t("products.show_more").replace("{n}", &hidden.to_string());
    let headers: Vec<(&'static str, String, &'static str)> = vec![
        ("name", t("common.product"), ""),
        ("category", t("products.col_category"), "m-hide"),
        ("price", t("products.col_price"), "num"),
        ("stock", t("products.col_stock"), "m-hide"),
        ("expiry", t("products.col_expiry"), "m-hide"),
        ("demand", t("products.col_demand"), "m-hide"),
    ];

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.products"), subtitle }

            div { class: "card tinted", style: "padding: 12px 16px",
                div { class: "row gap-12 wrap",
                    span { class: "ic accent sm", Icon { name: "warehouse", size: 15 } }
                    span { class: "grow small", style: "min-width: 200px", "{sync_text}" }
                    span { class: if connected { "badge success" } else { "badge accent" }, Icon { name: "link-2", size: 12 } "Daybook" }
                    if !connected {
                        button { class: "btn sm", onclick: move |_| go("/settings/daybook"), Icon { name: "plug-zap", size: 14 } {t("common.connect_daybook")} }
                    }
                }
            }

            div { class: "toolbar",
                div { class: "search",
                    Icon { name: "search", size: 16 }
                    input { class: "input", value: "{q}", placeholder: t("products.search"), oninput: move |e| q.set(e.value()) }
                }
                Segmented {
                    options: vec![("all".into(), t("common.all")), ("rx".into(), t("products.f_rx")), ("otc".into(), t("products.f_otc"))],
                    value: rx(),
                    onchange: move |v| rx.set(v),
                }
                button { class: if low() { "chip on" } else { "chip" }, onclick: move |_| low.toggle(),
                    Icon { name: "package", size: 14 }
                    {t("products.low")}
                    span { class: "count", "{low_n}" }
                }
                button { class: if expiring() { "chip on" } else { "chip" }, onclick: move |_| expiring.toggle(),
                    Icon { name: "calendar-x", size: 14 }
                    {t("products.expiring")}
                    span { class: "count", "{exp_n}" }
                }
            }
            div { class: "chips",
                button { class: if cat().is_none() { "chip on" } else { "chip" }, onclick: move |_| cat.set(None),
                    {t("common.all")}
                    span { class: "count", "{base.len()}" }
                }
                for (c, n) in cat_counts {
                    button {
                        key: "{c.slug()}",
                        class: if cat() == Some(c) { "chip on" } else { "chip" },
                        onclick: move |_| cat.set(if cat() == Some(c) { None } else { Some(c) }),
                        Icon { name: crm::db::category_icon(c), size: 14 }
                        {t(c.key())}
                        span { class: "count", "{n}" }
                    }
                }
            }

            div { class: "card",
                if visible.is_empty() {
                    Empty { icon: "pill", title: t("products.empty"), text: t("products.empty_text") }
                } else {
                    div { class: "table-wrap",
                        table { class: "table responsive",
                            thead {
                                tr {
                                    for (k, label, cls) in headers {
                                        {
                                            let on = k == key;
                                            let arrow: &'static str = if desc { "arrow-down" } else { "arrow-up" };
                                            let sortable = k != "category";
                                            let th_cls = if sortable { format!("sortable {cls}") } else { cls.to_string() };
                                            rsx! {
                                                th {
                                                    key: "{k}",
                                                    class: "{th_cls}",
                                                    onclick: move |_| {
                                                        if sortable {
                                                            let (cur, d) = sort();
                                                            sort.set((k.to_string(), if cur == k { !d } else { k == "demand" || k == "price" }));
                                                        }
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
                                for r in visible {
                                    ProductRow { key: "{r.id}", row: r, stock_max, onopen: move |id| sel.set(Some(id)) }
                                }
                            }
                        }
                    }
                    if hidden > 0 {
                        div { class: "card-foot", style: "justify-content: center",
                            button { class: "btn ghost sm", onclick: move |_| limit.set(limit() + 60), Icon { name: "chevron-down", size: 14 } "{more_label}" }
                        }
                    }
                }
            }
        }

        if let Some(id) = sel() {
            ProductDrawer { key: "{id}", id, onclose: move |_| sel.set(None) }
        }
    }
}

#[component]
fn ProductRow(row: Row, stock_max: u32, onopen: EventHandler<Id>) -> Element {
    let l = lang();
    let today = today();
    let id = row.id;
    let cat_label = t(row.category.key());
    let cat_icon = crm::db::category_icon(row.category);
    let exp_tone = expiry_tone(row.days_to_expiry);
    let exp_date = fmt::date(row.expiry, today, l);
    let exp_left = fmt::due_in(row.expiry, today, l);
    let price = money(row.price);
    let total = fmt::num(row.total as i64);
    let total_cls = if row.total == 0 { "strong num tone-danger" } else if row.total <= 10 { "strong num tone-warning" } else { "strong num" };
    let no_bonus = t("products.no_bonus");
    let regular_title = t("products.regular");
    let stock_line = t("products.stock_total").replace("{n}", &total);
    let waiting_title = t("products.waiting");
    rsx! {
        tr { class: "click", onclick: move |_| onopen.call(id),
            td {
                div { class: "row gap-8 wrap",
                    span { class: "strong small", "{row.name}" }
                    if row.rx { span { class: "badge sm info", "Rx" } }
                    if row.no_bonus { span { class: "badge sm warning", Icon { name: "gift", size: 11 } "{no_bonus}" } }
                }
                div { class: "xs muted", "{row.generic} · {row.form} · {row.maker}" }
                div { class: "only-mobile row gap-8 xs", style: "margin-top: 4px",
                    span { class: total_cls, "{stock_line}" }
                    if !exp_tone.is_empty() {
                        Badge { text: exp_left.clone(), tone: exp_tone }
                    }
                }
            }
            td { class: "m-hide",
                span { class: "badge", Icon { name: cat_icon, size: 12 } "{cat_label}" }
            }
            td { class: "num", span { class: "strong nowrap", "{price}" } }
            td { class: "m-hide",
                div { class: "row gap-12",
                    span { class: total_cls, style: "min-width: 34px; text-align: right", "{total}" }
                    div { class: "row", style: "gap: 3px; align-items: flex-end; height: 24px",
                        for (bname, qty) in row.stock.iter().cloned() {
                            {
                                let h = if qty == 0 { 4.0 } else { 6.0 + (qty as f64 / stock_max as f64).sqrt() * 18.0 };
                                let color = if qty == 0 { "var(--c-danger)" } else if qty <= 3 { "var(--c-warning)" } else { "var(--c-chart-1)" };
                                rsx! {
                                    span { key: "{bname}", title: "{bname}: {qty}", style: "display: inline-block; width: 6px; height: {h:.0}px; border-radius: 3px; background: {color}" }
                                }
                            }
                        }
                    }
                }
            }
            td { class: "m-hide",
                div { class: "small nowrap", "{exp_date}" }
                if !exp_tone.is_empty() {
                    Badge { text: exp_left, tone: exp_tone }
                }
            }
            td { class: "m-hide",
                if row.regular == 0 && row.waiting == 0 {
                    span { class: "subtle", "—" }
                }
                div { class: if row.regular == 0 && row.waiting == 0 { "hide" } else { "row gap-12 small" },
                    span { class: "row gap-4", title: "{regular_title}",
                        Icon { name: "repeat", size: 13, class: "subtle" }
                        span { class: "num", "{row.regular}" }
                    }
                    if row.waiting > 0 {
                        span { class: "row gap-4 tone-warning", title: "{waiting_title}",
                            Icon { name: "hourglass", size: 13 }
                            span { class: "num strong", "{row.waiting}" }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn ProductDrawer(id: Id, onclose: EventHandler<()>) -> Element {
    let l = lang();
    let now = now();
    let today = now.date();
    let mut adding = use_signal(|| false);
    let mut find = use_signal(String::new);
    let mut customer = use_signal(|| 0u32);
    let mut branch = use_signal(|| 0u32);
    let mut qty = use_signal(|| "1".to_string());

    let Some(p) = DB.read().product(id).cloned() else { return rsx! {} };
    let (stock, buyers, regular, due14, waits, sold_qty, sold_sum, customers) = {
        let db = DB.read();
        let stock: Vec<(Id, String, u32)> = db.branches.iter().map(|b| (b.id, b.name.clone(), p.stock_at(b.id))).collect();
        // who buys it: quantity and last purchase per customer
        let mut by: HashMap<Id, (u32, chrono::NaiveDateTime)> = HashMap::new();
        let (mut sold_qty, mut sold_sum) = (0u32, 0 as Money);
        let since = now - Duration::days(30);
        for pu in &db.purchases {
            for li in pu.items.iter().filter(|li| li.product_id == id) {
                let e = by.entry(pu.customer_id).or_insert((0, pu.at));
                e.0 += li.qty;
                if pu.at > e.1 {
                    e.1 = pu.at;
                }
                if pu.at >= since {
                    sold_qty += li.qty;
                    sold_sum += li.total();
                }
            }
        }
        let mut buyers: Vec<(Id, String, Tier, u32, chrono::NaiveDateTime)> = by
            .into_iter()
            .filter_map(|(cid, (n, at))| db.customer(cid).map(|c| (cid, c.name(), c.tier, n, at)))
            .collect();
        buyers.sort_by(|a, b| b.3.cmp(&a.3).then(b.4.cmp(&a.4)));
        buyers.truncate(5);
        let mut regular = 0usize;
        let mut due14 = 0usize;
        for c in db.customers.iter().filter(|c| !c.archived) {
            for g in c.regimens.iter().filter(|g| g.product_id == id) {
                regular += 1;
                if g.days_left(today) <= 14 {
                    due14 += 1;
                }
            }
        }
        let waits: Vec<(String, String, u32, WaitStatus)> = db
            .waitlist
            .iter()
            .filter(|w| w.product_id == Some(id) && matches!(w.status, WaitStatus::Waiting | WaitStatus::Arrived | WaitStatus::Notified | WaitStatus::Reserved))
            .map(|w| (db.customer_name(Some(w.customer_id)), db.branch_name(Some(w.branch_id)), w.qty, w.status))
            .collect();
        let fq = find().trim().to_lowercase();
        let mut cs: Vec<(Id, String, Id)> = db
            .customers
            .iter()
            .filter(|c| !c.archived && (fq.is_empty() || c.name().to_lowercase().contains(&fq) || (fq.len() >= 3 && c.phone.contains(&fq))))
            .map(|c| (c.id, c.name(), c.home_branch))
            .collect();
        cs.sort_by(|a, b| a.1.cmp(&b.1));
        cs.truncate(50);
        (stock, buyers, regular, due14, waits, sold_qty, sold_sum, cs)
    };
    let max_stock = stock.iter().map(|s| s.2).max().unwrap_or(1).max(1);
    let branch_opts: Vec<(Id, String)> = stock.iter().map(|s| (s.0, s.1.clone())).collect();
    let total = p.total_stock();
    let days_left = (p.expiry - today).num_days();
    let exp_tone = expiry_tone(days_left);
    let exp_text = t("products.expiry_warn").replace("{n}", &days_left.to_string());
    let exp_date = fmt::date(p.expiry, today, l);
    let cat_label = t(p.category.key());
    let cat_icon = crm::db::category_icon(p.category);
    let sold_text = fmt::plural(sold_qty as i64, l, "dona|упаковка|упаковки|упаковок|pack|packs");
    let wait_qty: u32 = waits.iter().map(|w| w.2).sum();
    let n: u32 = qty().trim().parse().unwrap_or(0);
    let valid = customer() != 0 && branch() != 0 && n > 0;
    let price = p.price;
    let pname = p.name.clone();
    let pname2 = p.name.clone();

    let add_wait = move |_| {
        if !valid {
            return;
        }
        let in_stock = DB.peek().product(id).map(|x| x.stock_at(branch()) > 0).unwrap_or(false);
        mutate(|db| {
            let wid = db.new_id();
            let now = crate::state::now();
            db.waitlist.insert(
                0,
                WaitItem {
                    id: wid,
                    customer_id: customer(),
                    product_id: Some(id),
                    product_name: pname.clone(),
                    branch_id: branch(),
                    qty: n,
                    at: now,
                    status: if in_stock { WaitStatus::Reserved } else { WaitStatus::Waiting },
                    eta: if in_stock { None } else { Some(now.date() + Duration::days(3)) },
                    note: String::new(),
                    notified_at: None,
                    value: price * n as Money,
                },
            );
            db.log(now, format!("Defekturaga: {}", pname), false);
        });
        adding.set(false);
        customer.set(0);
        find.set(String::new());
        toast(if in_stock { t("refills.toast_reserved") } else { t("waitlist.toast_added") }, "hourglass", "success");
    };
    let send_purchasing = move |_| {
        mutate(|db| db.log(crate::state::now(), format!("Daybook xarid so‘rovi: {pname2}"), false));
        toast(t("products.purchasing_sent"), "send", "success");
    };

    rsx! {
        Drawer { title: p.name.clone(), icon: cat_icon, onclose: move |_| onclose.call(()),
            div { class: "drawer-body",
                div { class: "row gap-8 wrap",
                    span { class: "badge", Icon { name: cat_icon, size: 12 } "{cat_label}" }
                    if p.rx { span { class: "badge info", "Rx" } }
                    if p.no_bonus { span { class: "badge warning", Icon { name: "gift", size: 12 } {t("products.no_bonus")} } }
                    span { class: "spacer" }
                    span { class: "num", style: "font-size: 22px; font-weight: 750", "{money(p.price)}" }
                }
                if p.rx {
                    div { class: "callout", Icon { name: "file-check", size: 16 } span { {t("products.rx_note")} } }
                }
                KeyValues {
                    items: vec![
                        (t("products.generic"), p.generic.clone()),
                        (t("products.form"), p.form.clone()),
                        (t("products.maker"), p.maker.clone()),
                        (t("products.barcode"), p.barcode.clone()),
                        (t("products.col_expiry"), exp_date.clone()),
                    ],
                }
                if !exp_tone.is_empty() {
                    div { class: "callout {exp_tone}", Icon { name: "calendar-x", size: 16 } span { "{exp_text}" } }
                }

                div { class: "grid-3", style: "gap: 8px; grid-template-columns: repeat(3, minmax(0, 1fr))",
                    div { style: "padding: 12px; border-radius: 12px; background: var(--c-surface-2)",
                        div { class: "xs muted", {t("products.sold_30")} }
                        div { class: "strong num", style: "font-size: 18px", "{sold_text}" }
                        div { class: "xs subtle num", "{money_short(sold_sum)}" }
                    }
                    div { style: "padding: 12px; border-radius: 12px; background: var(--c-surface-2)",
                        div { class: "xs muted", {t("products.regular")} }
                        div { class: "strong num", style: "font-size: 18px", "{regular}" }
                        div { class: "xs subtle", {t("products.regular_due").replace("{n}", &due14.to_string())} }
                    }
                    div { style: "padding: 12px; border-radius: 12px; background: var(--c-warning-soft)",
                        div { class: "xs tone-warning", {t("products.waiting")} }
                        div { class: "strong num tone-warning", style: "font-size: 18px", "{waits.len()}" }
                        div { class: "xs tone-warning", {fmt::plural(wait_qty as i64, l, "dona|шт.|шт.|шт.|pc|pcs")} }
                    }
                }

                div { class: "stack gap-8",
                    div { class: "row between",
                        span { class: "section-title", {t("products.drawer_stock")} }
                        span { class: "small muted num", {t("products.stock_total").replace("{n}", &total.to_string())} }
                    }
                    for (bid, bname, qty) in stock {
                        {
                            let pct = qty as f64 / max_stock as f64 * 100.0;
                            let tone: &'static str = if qty == 0 { "danger" } else if qty <= 3 { "warning" } else { "" };
                            rsx! {
                                div { key: "{bid}", class: "row gap-12 small",
                                    span { class: "truncate", style: "width: 130px", "{bname}" }
                                    div { class: "grow", Progress { pct, tone, thin: true } }
                                    if qty == 0 {
                                        span { class: "badge sm danger", style: "min-width: 56px; justify-content: center", {t("products.out")} }
                                    } else {
                                        span { class: "num strong", style: "min-width: 56px; text-align: right", "{qty}" }
                                    }
                                }
                            }
                        }
                    }
                }

                div { class: "stack gap-8",
                    span { class: "section-title", {t("products.who_buys")} }
                    if buyers.is_empty() {
                        div { class: "small muted", {t("products.no_buyers")} }
                    }
                    div { class: "list", style: "margin: 0 -18px",
                        for (cid, name, tier, n, at) in buyers {
                            {
                                let when = fmt::relative(at, now, l);
                                let packs = fmt::plural(n as i64, l, "dona|упаковка|упаковки|упаковок|pack|packs");
                                rsx! {
                                    div { key: "{cid}", class: "list-row click", onclick: move |_| go(&format!("/contacts/{cid}")),
                                        Avatar { name: name.clone(), size: "sm" }
                                        div { class: "meta",
                                            div { class: "row gap-8", span { class: "title small truncate", "{name}" } TierBadge { tier } }
                                            span { class: "sub", "{when}" }
                                        }
                                        span { class: "small strong num nowrap", "{packs}" }
                                    }
                                }
                            }
                        }
                    }
                }

                if !waits.is_empty() {
                    div { class: "stack gap-8",
                        span { class: "section-title", {t("products.waiting")} }
                        for (i, (name, bname, n, st)) in waits.into_iter().enumerate() {
                            div { key: "{i}", class: "row gap-8 small",
                                Icon { name: "hourglass", size: 13, class: "tone-warning" }
                                span { class: "grow truncate", "{name} · {bname}" }
                                span { class: "num muted", "×{n}" }
                                Badge { text: t(st.key()), tone: "warning" }
                            }
                        }
                    }
                }

                if adding() {
                    div { class: "card pad stack gap-12", style: "box-shadow: none; background: var(--c-surface-2)",
                        span { class: "strong", {t("products.add_waitlist")} }
                        div { class: "search",
                            Icon { name: "search", size: 16 }
                            input {
                                class: "input",
                                value: "{find}",
                                placeholder: t("waitlist.find_customer"),
                                oninput: move |e| find.set(e.value()),
                                onmounted: move |e| async move {
                                    let _ = e.set_focus(true).await;
                                },
                            }
                        }
                        select {
                            class: "select",
                            onchange: move |e| {
                                let cid: Id = e.value().parse().unwrap_or(0);
                                customer.set(cid);
                                if let Some(c) = DB.peek().customer(cid) {
                                    branch.set(c.home_branch);
                                }
                            },
                            option { value: "0", selected: customer() == 0, {t("waitlist.pick_customer")} }
                            for (cid, name, _) in customers {
                                option { key: "{cid}", value: "{cid}", selected: cid == customer(), "{name}" }
                            }
                        }
                        div { class: "grid-2",
                            select { class: "select", onchange: move |e| branch.set(e.value().parse().unwrap_or(0)),
                                option { value: "0", selected: branch() == 0, {t("common.branch")} }
                                for (bid, bname) in branch_opts {
                                    option { key: "{bid}", value: "{bid}", selected: bid == branch(), "{bname}" }
                                }
                            }
                            input { class: "input num", r#type: "number", min: "1", value: "{qty}", oninput: move |e| qty.set(e.value()) }
                        }
                        div { class: "row end gap-8",
                            button { class: "btn ghost sm", onclick: move |_| adding.set(false), {t("common.cancel")} }
                            button { class: "btn primary sm", disabled: !valid, onclick: add_wait, Icon { name: "check", size: 14 } {t("common.save")} }
                        }
                    }
                }
            }
            div { class: "drawer-foot",
                button { class: "btn", onclick: move |_| adding.set(true), Icon { name: "hourglass", size: 16 } {t("products.add_waitlist")} }
                button { class: "btn primary", onclick: send_purchasing, Icon { name: "send", size: 16 } {t("products.to_purchasing")} }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("products.sub", "{n} ta mahsulot · {m} ta filialdagi qoldiq", "Товаров: {n} · остатки в {m} филиалах", "{n} products · stock across {m} branches"),
    ("products.synced", "Daybook omboridan sinxronlanadi", "Синхронизируется со складом Daybook", "Synced from Daybook stock"),
    ("products.last_sync", "oxirgi sinxronlash: {t}", "последняя синхронизация: {t}", "last sync {t}"),
    ("products.demo_banner", "Demo katalog. Daybook ulansa, mahsulotlar va qoldiqlar uning omboridan avtomatik keladi.", "Демо-каталог. После подключения Daybook товары и остатки подтянутся с его склада.", "Demo catalogue. Once Daybook is connected, products and stock come straight from its warehouse."),
    ("products.search", "Nomi, xalqaro nomi yoki shtrix-kod…", "Название, МНН или штрихкод…", "Name, generic or barcode…"),
    ("products.f_rx", "Retseptli", "Рецептурные", "Rx"),
    ("products.f_otc", "Retseptsiz", "Без рецепта", "OTC"),
    ("products.low", "Kam qolgan", "Мало на складе", "Low stock"),
    ("products.expiring", "Muddati yaqin", "Скоро истекает", "Near expiry"),
    ("products.col_category", "Toifa", "Категория", "Category"),
    ("products.col_price", "Narx", "Цена", "Price"),
    ("products.col_stock", "Qoldiq va filiallar", "Остаток по филиалам", "Stock by branch"),
    ("products.col_expiry", "Yaroqlilik muddati", "Годен до", "Expiry"),
    ("products.col_demand", "Talab", "Спрос", "Demand"),
    ("products.no_bonus", "Bonussiz", "Без бонусов", "No bonus"),
    ("products.regular", "Doimiy qabul qiladi", "Принимают постоянно", "Take it regularly"),
    ("products.regular_due", "14 kunda tugaydi: {n}", "закончится за 14 дн.: {n}", "{n} run out in 14 days"),
    ("products.waiting", "Defekturada kutmoqda", "Ждут в дефектуре", "On the waitlist"),
    ("products.sold_30", "30 kunda sotildi", "Продано за 30 дней", "Sold in 30 days"),
    ("products.drawer_stock", "Filiallardagi qoldiq", "Остатки по филиалам", "Stock by branch"),
    ("products.stock_total", "jami {n}", "всего {n}", "{n} in total"),
    ("products.out", "Yo‘q", "Нет", "Out"),
    ("products.who_buys", "Kim ko‘p oladi", "Кто покупает", "Who buys it"),
    ("products.no_buyers", "Hali hech kim olmagan", "Ещё никто не покупал", "No one has bought it yet"),
    ("products.expiry_warn", "Eng yaqin partiyaning muddati {n} kundan keyin tugaydi: oldinga qo‘ying yoki chegirma bering.", "Ближайшая партия истекает через {n} дн.: выставьте вперёд или дайте скидку.", "The nearest batch expires in {n} days: put it up front or offer a discount."),
    ("products.rx_note", "Retseptli dori: reklama xabarlariga qo‘shilmaydi va bonus ball bermaydi.", "Рецептурный препарат: не попадает в рассылки и не даёт бонусов.", "Prescription-only: never in campaigns and earns no bonus points."),
    ("products.generic", "Xalqaro nomi", "МНН", "Generic"),
    ("products.form", "Shakli", "Форма", "Form"),
    ("products.maker", "Ishlab chiqarilgan", "Страна", "Made in"),
    ("products.barcode", "Shtrix-kod", "Штрихкод", "Barcode"),
    ("products.add_waitlist", "Defekturaga yozish", "Записать в дефектуру", "Add to the waitlist"),
    ("products.to_purchasing", "Daybook xaridiga yuborish", "В закупки Daybook", "Send to Daybook purchasing"),
    ("products.purchasing_sent", "Xarid so‘rovi Daybook’ga yuborildi", "Заявка на закупку отправлена в Daybook", "Purchase request sent to Daybook"),
    ("products.empty", "Bunday mahsulot topilmadi", "Таких товаров нет", "No products match"),
    ("products.empty_text", "Qidiruv yoki filtrlarni o‘zgartiring.", "Измените поиск или фильтры.", "Change the search or filters."),
    ("products.show_more", "Yana {n} ta ko‘rsatish", "Показать ещё {n}", "Show {n} more"),
];
