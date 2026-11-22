//! Loyalty: the cashback programme. KPIs and liability, tier cards, the settings editor (tiers,
//! bonuses, expiry, the Rx rule), top members, the points ledger, manual adjustments and a
//! preview of the digital card customers carry in the Daybook Telegram bot.

use crm::analytics;
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

fn tx_style(k: TxKind) -> (&'static str, &'static str) {
    match k {
        TxKind::Earn => ("coins", "success"),
        TxKind::Redeem => ("shopping-bag", "accent"),
        TxKind::Bonus => ("gift", "info"),
        TxKind::Expire => ("hourglass", "muted"),
        TxKind::Adjust => ("sliders-horizontal", "warning"),
    }
}

fn parse_i64(v: &str) -> i64 {
    let s = v.trim();
    let neg = s.starts_with('-') || s.starts_with('−');
    let n = s.chars().filter(|c| c.is_ascii_digit()).collect::<String>().parse::<i64>().unwrap_or(0);
    if neg {
        -n
    } else {
        n
    }
}

fn pts(n: i64, l: Lang) -> String {
    fmt::plural(n, l, "ball|балл|балла|баллов|point|points")
}

/// A real QR code for `data`, as one SVG path (module size 1).
fn qr_path(data: &str) -> (usize, String) {
    match qrcode::QrCode::new(data.as_bytes()) {
        Ok(code) => {
            let w = code.width();
            let colors = code.to_colors();
            let mut d = String::with_capacity(w * w * 6);
            for y in 0..w {
                for x in 0..w {
                    if colors[y * w + x] == qrcode::Color::Dark {
                        d.push_str(&format!("M{x} {y}h1v1h-1z"));
                    }
                }
            }
            (w, d)
        }
        Err(_) => (0, String::new()),
    }
}

#[derive(Clone, PartialEq)]
struct Stats {
    members: usize,
    new_month: usize,
    liability: i64,
    earned: i64,
    bonus: i64,
    redeemed: i64,
    receipts: usize,
    rate: f64,
    tiers: Vec<(Tier, u32, Money)>,
}

#[component]
pub fn Loyalty() -> Element {
    let mut adjust = use_signal(|| false);
    let stats = use_memo(move || {
        let db = DB.read();
        let now = crate::state::now();
        let today = now.date();
        let m0 = analytics::month_start(today);
        let d90 = now - chrono::Duration::days(90);
        let mut s = Stats {
            members: db.customers.iter().filter(|c| !c.archived).count(),
            new_month: db.customers.iter().filter(|c| !c.archived && c.created >= m0).count(),
            liability: db.customers.iter().filter(|c| !c.archived).map(|c| c.points).sum(),
            earned: 0,
            bonus: 0,
            redeemed: 0,
            receipts: 0,
            rate: 0.0,
            tiers: analytics::tier_counts(&db),
        };
        let (mut e90, mut r90) = (0i64, 0i64);
        for tx in db.loyalty.iter() {
            if tx.at.date() >= m0 {
                match tx.kind {
                    TxKind::Earn | TxKind::Bonus if tx.points > 0 => {
                        s.earned += tx.points;
                        if tx.kind == TxKind::Bonus {
                            s.bonus += tx.points;
                        }
                    }
                    TxKind::Redeem => {
                        s.redeemed += -tx.points;
                        s.receipts += 1;
                    }
                    _ => {}
                }
            }
            if tx.at >= d90 {
                match tx.kind {
                    TxKind::Earn | TxKind::Bonus if tx.points > 0 => e90 += tx.points,
                    TxKind::Redeem => r90 += -tx.points,
                    _ => {}
                }
            }
        }
        s.rate = if e90 > 0 { r90 as f64 / e90 as f64 * 100.0 } else { 0.0 };
        s
    });
    let l = lang();
    let s = stats();
    let (settings, company) = {
        let db = DB.read();
        (db.settings.loyalty.clone(), db.settings.company_name.clone())
    };
    let total_members: u32 = s.tiers.iter().map(|x| x.1).sum::<u32>().max(1);
    let subtitle = if settings.enabled { t("loyalty.subtitle") } else { t("loyalty.disabled") };

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.loyalty"), subtitle,
                button { class: "btn primary", onclick: move |_| adjust.set(true),
                    Icon { name: "sliders-horizontal", size: 16 }
                    span { class: "label-text", {t("loyalty.adjust")} }
                }
            }

            div { class: "grid", style: "grid-template-columns: repeat(auto-fit, minmax(160px, 1fr))",
                Kpi { label: t("loyalty.members"), value: fmt::num(s.members as i64), icon: "users", tone: "info",
                    foot: t("loyalty.members_foot").replace("{n}", &s.new_month.to_string()), onclick: move |_| go("/contacts") }
                Kpi { label: t("loyalty.liability"), value: money_short(s.liability), icon: "wallet", tone: "warning", foot: t("loyalty.liability_foot") }
                Kpi { label: t("loyalty.earned"), value: fmt::num(s.earned), icon: "coins", tone: "success",
                    foot: if s.bonus > 0 { format!("{}: {}", t("loyalty.of_bonus"), fmt::num(s.bonus)) } else { t("loyalty.earned_foot") } }
                Kpi { label: t("loyalty.redeemed"), value: fmt::num(s.redeemed), icon: "shopping-bag", tone: "accent",
                    foot: fmt::plural(s.receipts as i64, l, "chekda|чек|чека|чеков|receipt|receipts") }
                Kpi { label: t("loyalty.rate"), value: fmt::pct(s.rate, l), icon: "percent", foot: t("loyalty.rate_foot") }
            }

            div { class: "stack gap-8",
                div { class: "row between",
                    span { class: "section-title", {t("loyalty.tiers")} }
                    span { class: "small muted", {t("loyalty.levels_hint")} }
                }
                div { class: "grid-4",
                    for rule in settings.tiers.iter().cloned() {
                        {
                            let (n, _) = s.tiers.iter().find(|x| x.0 == rule.tier).map(|x| (x.1, x.2)).unwrap_or((0, 0));
                            let share = fmt::pct(n as f64 / total_members as f64 * 100.0, l);
                            let from = t("loyalty.from").replace("{sum}", &money_short(rule.min_spent));
                            let slug = rule.tier.slug();
                            let members = fmt::plural(n as i64, l, "a’zo|участник|участника|участников|member|members");
                            rsx! {
                                div { key: "{slug}", class: "loyalty-card {slug}",
                                    div { class: "row between", style: "position: relative; z-index: 1",
                                        span { class: "strong", style: "font-size: 16px", {t(rule.tier.key())} }
                                        Icon { name: "crown", size: 18 }
                                    }
                                    div { style: "position: relative; z-index: 1",
                                        span { class: "num", style: "font-size: 34px; font-weight: 750; letter-spacing: -0.02em", "{rule.cashback_pct}%" }
                                        span { class: "small", style: "opacity: .85", " {t(\"loyalty.cashback\")}" }
                                    }
                                    div { class: "row between small", style: "position: relative; z-index: 1; opacity: .92",
                                        span { class: "num", "{from}" }
                                        span { class: "num strong", "{members} · {share}" }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            div { class: "grid-main",
                div { class: "stack gap-16",
                    PointsFlow {}
                    SettingsEditor {}
                    TopMembers {}
                }
                div { class: "stack gap-16",
                    CardPreview { company: company.clone() }
                    RecentLedger {}
                }
            }

            if adjust() {
                AdjustModal { onclose: move |_| adjust.set(false) }
            }
        }
    }
}

#[component]
fn PointsFlow() -> Element {
    let data = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let weeks = 19usize;
        let mut earned = vec![0f64; weeks];
        let mut redeemed = vec![0f64; weeks];
        for tx in db.loyalty.iter() {
            let ago = (today - tx.at.date()).num_days();
            if ago < 0 {
                continue;
            }
            let w = (ago / 7) as usize;
            if w >= weeks {
                continue;
            }
            let idx = weeks - 1 - w;
            match tx.kind {
                TxKind::Earn | TxKind::Bonus if tx.points > 0 => earned[idx] += tx.points as f64,
                TxKind::Redeem => redeemed[idx] += (-tx.points) as f64,
                _ => {}
            }
        }
        let starts: Vec<chrono::NaiveDate> = (0..weeks).map(|i| today - chrono::Duration::days(((weeks - 1 - i) * 7) as i64)).collect();
        (starts, earned, redeemed)
    });
    let l = lang();
    let (starts, earned, redeemed) = data();
    let labels: Vec<String> = starts.iter().map(|d| format!("{} {}", chrono::Datelike::day(d), fmt::month_short(chrono::Datelike::month(d), l))).collect();
    let total_e: f64 = earned.iter().sum();
    let total_r: f64 = redeemed.iter().sum();
    let series = vec![
        Series { name: t("loyalty.series_earned"), values: earned, color: "var(--c-chart-1)", dashed: false },
        Series { name: t("loyalty.series_redeemed"), values: redeemed, color: "var(--c-chart-3)", dashed: false },
    ];
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "chart-line", size: 16, class: "subtle" } {t("loyalty.flow")} }
                div { class: "legend",
                    for s in series.iter() {
                        span { key: "{s.name}", span { class: "sw", style: "background: {s.color}" } "{s.name}" }
                    }
                }
            }
            div { class: "card-body",
                AreaChart { labels, series: series.clone(), height: 190, money: true }
                div { class: "row gap-16 small muted", style: "margin-top: 8px",
                    span { {t("loyalty.series_earned")} ": " b { class: "num", style: "color: var(--c-text)", "{fmt::num(total_e as i64)}" } }
                    span { {t("loyalty.series_redeemed")} ": " b { class: "num", style: "color: var(--c-text)", "{fmt::num(total_r as i64)}" } }
                }
            }
        }
    }
}

#[component]
fn SettingsEditor() -> Element {
    let mut draft = use_signal(|| DB.peek().settings.loyalty.clone());
    let saved = DB.read().settings.loyalty.clone();
    let d = draft();
    let dirty = d != saved;
    let increasing = d.tiers.windows(2).all(|w| w[1].min_spent > w[0].min_spent);
    let valid = increasing && d.tiers.iter().all(|r| (0.0..=20.0).contains(&r.cashback_pct)) && d.max_redeem_pct <= 100;
    let save = move |_| {
        let d = draft();
        let mut changed = 0usize;
        let log = t("loyalty.save_ok");
        mutate(|db| {
            for c in db.customers.iter_mut() {
                let nt = d.tier_for(c.total_spent);
                if nt != c.tier {
                    c.tier = nt;
                    changed += 1;
                }
            }
            db.settings.loyalty = d.clone();
            db.log(crate::state::now(), log, false);
        });
        let msg = if changed > 0 { format!("{} · {}", t("loyalty.save_ok"), t("loyalty.tier_changed").replace("{n}", &changed.to_string())) } else { t("loyalty.save_ok") };
        toast(msg, "save", "success");
    };
    let bonuses: Vec<(&'static str, &'static str, String, i64)> = vec![
        ("welcome", "sparkles", t("loyalty.welcome"), d.welcome_bonus),
        ("birthday", "cake", t("loyalty.birthday"), d.birthday_bonus),
        ("referral", "hand-heart", t("loyalty.referral"), d.referral_bonus),
    ];
    rsx! {
        div { class: "card",
            div { class: "card-head line",
                div { class: "card-title", Icon { name: "settings-2", size: 16, class: "subtle" } {t("loyalty.settings")} }
                div { class: "row gap-8 small",
                    span { class: "muted", {t("loyalty.enabled")} }
                    Switch { on: d.enabled, onchange: move |v: bool| draft.write().enabled = v }
                }
            }
            div { class: "card-body stack gap-16",
                div { class: "stack gap-8",
                    div { class: "row xs upper subtle", style: "gap: 10px",
                        span { style: "flex: 0 0 112px", {t("field.tier")} }
                        span { class: "grow", {t("loyalty.threshold")} }
                        span { style: "flex: 0 0 96px", {t("loyalty.cashback_pct")} }
                    }
                    for (i, r) in d.tiers.iter().cloned().enumerate() {
                        div { key: "{i}", class: "row", style: "gap: 10px",
                            div { style: "flex: 0 0 112px", TierBadge { tier: r.tier } }
                            input {
                                class: "input sm num grow",
                                inputmode: "numeric",
                                disabled: i == 0,
                                value: "{r.min_spent}",
                                oninput: move |e| {
                                    let v = parse_i64(&e.value()).max(0);
                                    if let Some(t) = draft.write().tiers.get_mut(i) {
                                        t.min_spent = v;
                                    }
                                },
                            }
                            input {
                                class: "input sm num",
                                style: "flex: 0 0 96px",
                                inputmode: "decimal",
                                value: "{r.cashback_pct}",
                                oninput: move |e| {
                                    let v: f32 = e.value().replace(',', ".").trim().parse().unwrap_or(0.0);
                                    if let Some(t) = draft.write().tiers.get_mut(i) {
                                        t.cashback_pct = v;
                                    }
                                },
                            }
                        }
                    }
                    if !increasing {
                        div { class: "small tone-danger row gap-4", Icon { name: "circle-alert", size: 14 } {t("loyalty.invalid")} }
                    }
                }
                div { class: "grid-3", style: "gap: 12px",
                    for (k, icon, label, v) in bonuses {
                        div { key: "{k}", class: "field",
                            label { class: "label row gap-4", Icon { name: icon, size: 13 } "{label}" }
                            input {
                                class: "input sm num",
                                inputmode: "numeric",
                                value: "{v}",
                                oninput: move |e| {
                                    let n = parse_i64(&e.value()).max(0);
                                    let mut w = draft.write();
                                    match k {
                                        "welcome" => w.welcome_bonus = n,
                                        "birthday" => w.birthday_bonus = n,
                                        _ => w.referral_bonus = n,
                                    }
                                },
                            }
                        }
                    }
                }
                div { class: "grid-2", style: "gap: 12px",
                    div { class: "field",
                        label { class: "label", {t("loyalty.expiry")} }
                        input {
                            class: "input sm num",
                            inputmode: "numeric",
                            value: "{d.expiry_days}",
                            oninput: move |e| draft.write().expiry_days = parse_i64(&e.value()).clamp(0, 3650) as u16,
                        }
                        span { class: "hint", {t("loyalty.expiry_hint")} }
                    }
                    div { class: "field",
                        label { class: "label", {t("loyalty.max_redeem")} }
                        input {
                            class: "input sm num",
                            inputmode: "numeric",
                            value: "{d.max_redeem_pct}",
                            oninput: move |e| draft.write().max_redeem_pct = parse_i64(&e.value()).clamp(0, 100) as u8,
                        }
                    }
                }
                div { class: "stack gap-8", style: "padding: 12px 14px; border-radius: 12px; border: 1px solid var(--c-border)",
                    div { class: "row between", style: "gap: 12px",
                        span { class: "row gap-8 strong small", Icon { name: "file-check", size: 15, class: "tone-danger" } {t("loyalty.exclude_rx")} }
                        Switch { on: d.exclude_rx, onchange: move |v: bool| draft.write().exclude_rx = v }
                    }
                    p { class: "small muted", style: "line-height: 1.5", {t("loyalty.exclude_rx_hint")} }
                }
            }
            div { class: "card-foot",
                if dirty {
                    span { class: "small tone-warning row gap-4", Icon { name: "circle-dot", size: 13 } {t("loyalty.unsaved")} }
                } else {
                    span { class: "small muted row gap-4", Icon { name: "check", size: 13 } {t("common.saved")} }
                }
                div { class: "row gap-8",
                    button { class: "btn ghost sm", disabled: !dirty, onclick: move |_| draft.set(DB.peek().settings.loyalty.clone()), {t("common.cancel")} }
                    button { class: "btn primary sm", disabled: !dirty || !valid, onclick: save, Icon { name: "save", size: 14 } {t("common.save")} }
                }
            }
        }
    }
}

#[component]
fn CardPreview(company: String) -> Element {
    let top: Vec<(Id, String)> = {
        let db = DB.read();
        let mut v: Vec<&Customer> = db.customers.iter().filter(|c| !c.archived).collect();
        v.sort_by(|a, b| b.points.cmp(&a.points));
        v.into_iter().take(12).map(|c| (c.id, c.name())).collect()
    };
    let first = top.first().map(|x| x.0).unwrap_or(0);
    let mut pick = use_signal(move || first);
    let Some(c) = DB.read().customer(pick()).cloned() else { return rsx! {} };
    let cashback = DB.read().settings.loyalty.cashback(c.tier);
    let link = format!("https://t.me/daybook_crm_bot?start=card{}", c.card_no.replace(' ', ""));
    let (w, path) = qr_path(&link);
    let vb = format!("-2 -2 {} {}", w + 4, w + 4);
    let hello = t("loyalty.tg_hello").replace("{name}", &c.first_name);
    let slug = c.tier.slug();
    let tier_name = t(c.tier.key());
    let points = fmt::num(c.points);
    let points_money = money(c.points);
    let initials = crm::fmt::initials(&company);
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div { class: "card-title", Icon { name: "smartphone", size: 16, class: "tone-info" } {t("loyalty.card_preview")} }
            }
            div { class: "card-body stack gap-16",
                div { class: "field",
                    label { class: "label", {t("loyalty.preview_for")} }
                    select { class: "select sm", onchange: move |e| pick.set(e.value().parse().unwrap_or(0)),
                        for (id, name) in top {
                            option { key: "{id}", value: "{id}", selected: id == pick(), "{name}" }
                        }
                    }
                }
                div { class: "phone-mock", style: "align-self: center",
                    div { class: "phone-screen", style: "gap: 10px",
                        div { class: "row gap-8", style: "background: rgb(255 255 255 / .78); margin: -14px -14px 2px; padding: 12px 14px; color: #1c1916",
                            span { class: "avatar sm", style: "--h: 24", "{initials}" }
                            div { class: "stack", style: "gap: 0",
                                span { class: "strong small", "{company}" }
                                span { class: "xs", style: "opacity: .6", "bot" }
                            }
                        }
                        div { class: "tg-bubble", "{hello}" }
                        div { class: "loyalty-card {slug}", style: "min-height: 150px; padding: 14px; border-radius: 16px",
                            div { class: "row between", style: "position: relative; z-index: 1",
                                span { class: "strong small", "{company}" }
                                span { class: "xs upper", Icon { name: "crown", size: 11 } " {tier_name}" }
                            }
                            div { style: "position: relative; z-index: 1",
                                div { class: "num", style: "font-size: 26px; font-weight: 750; line-height: 1.1", "{points}" }
                                div { class: "xs", style: "opacity: .85", "= {points_money} · {cashback}%" }
                            }
                            span { class: "num xs", style: "position: relative; z-index: 1; letter-spacing: .12em; opacity: .92", "{c.card_no}" }
                        }
                        if w > 0 {
                            div { class: "qr", style: "align-self: center; line-height: 0",
                                svg { width: "128", height: "128", view_box: "{vb}", shape_rendering: "crispEdges",
                                    path { d: "{path}", fill: "#1c1916" }
                                }
                            }
                        }
                        div { class: "tg-bubble", {t("loyalty.tg_show")} }
                        div { style: "display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px",
                            for (icon, key) in [("coins", "loyalty.btn_points"), ("pill", "loyalty.btn_meds"), ("map-pin", "loyalty.btn_branches")] {
                                span { key: "{key}", class: "row gap-4 xs strong", style: "justify-content: center; padding: 8px 4px; border-radius: 10px; background: rgb(255 255 255 / .6); color: #2a5b84",
                                    Icon { name: icon, size: 12 }
                                    {t(key)}
                                }
                            }
                        }
                    }
                }
                div { class: "callout", Icon { name: "send", size: 15 } span { {t("loyalty.card_note")} } }
            }
        }
    }
}

#[component]
fn TopMembers() -> Element {
    let l = lang();
    let rows: Vec<(Id, String, Tier, i64, Money)> = {
        let db = DB.read();
        let mut v: Vec<&Customer> = db.customers.iter().filter(|c| !c.archived).collect();
        v.sort_by(|a, b| b.points.cmp(&a.points));
        v.into_iter().take(8).map(|c| (c.id, c.name(), c.tier, c.points, c.total_spent)).collect()
    };
    rsx! {
        div { class: "card",
            div { class: "card-head", div { class: "card-title", Icon { name: "trophy", size: 16, class: "tone-warning" } {t("loyalty.top")} } }
            div { class: "list", style: "margin-top: 6px",
                for (i, (id, name, tier, p, ltv)) in rows.into_iter().enumerate() {
                    {
                        let rank = i + 1;
                        let points = pts(p, l);
                        let ltv_s = money_short(ltv);
                        let rank_style = match rank {
                            1 => "background: #f1cf72; color: #5b4206",
                            2 => "background: #d5dbe3; color: #3b4652",
                            3 => "background: #e8b58c; color: #5c2f14",
                            _ => "background: var(--c-surface-2); color: var(--c-muted)",
                        };
                        rsx! {
                            div { key: "{id}", class: "list-row click", onclick: move |_| go(&format!("/contacts/{id}")),
                                span { class: "num strong xs", style: "width: 22px; height: 22px; border-radius: 99px; display: grid; place-items: center; flex: 0 0 22px; {rank_style}", "{rank}" }
                                Avatar { name: name.clone(), size: "sm" }
                                div { class: "meta", span { class: "title small truncate", "{name}" } span { class: "sub num", "{ltv_s}" } }
                                TierBadge { tier }
                                span { class: "num strong small nowrap", style: "min-width: 92px; text-align: right", "{points}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn RecentLedger() -> Element {
    let now = now();
    let l = lang();
    let rows: Vec<(LoyaltyTx, String)> = {
        let db = DB.read();
        let mut v: Vec<&LoyaltyTx> = db.loyalty.iter().collect();
        v.sort_by(|a, b| b.at.cmp(&a.at));
        v.into_iter().take(7).map(|x| (x.clone(), db.customer_name(Some(x.customer_id)))).collect()
    };
    rsx! {
        div { class: "card",
            div { class: "card-head", div { class: "card-title", Icon { name: "history", size: 16, class: "subtle" } {t("loyalty.ledger")} } }
            div { class: "list", style: "margin-top: 6px",
                if rows.is_empty() {
                    Empty { icon: "coins", title: t("loyalty.no_ledger") }
                }
                for (tx, name) in rows {
                    {
                        let (icon, tone) = tx_style(tx.kind);
                        let when = fmt::relative(tx.at, now, l);
                        let what = if tx.note.is_empty() { t(tx.kind.key()) } else { format!("{} · {}", t(tx.kind.key()), tx.note) };
                        let amount = if tx.points >= 0 { format!("+{}", fmt::num(tx.points)) } else { fmt::num(tx.points) };
                        let cls = if tx.points >= 0 { "num strong small tone-success nowrap" } else { "num strong small tone-danger nowrap" };
                        let cid = tx.customer_id;
                        rsx! {
                            div { key: "{tx.id}", class: "list-row click", onclick: move |_| go(&format!("/contacts/{cid}")),
                                IconTile { icon, tone, size: "sm" }
                                div { class: "meta", span { class: "title small truncate", "{name}" } span { class: "sub truncate", "{what} · {when}" } }
                                span { class: cls, "{amount}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn AdjustModal(onclose: EventHandler<()>) -> Element {
    let mut query = use_signal(String::new);
    let mut chosen = use_signal(|| None::<Id>);
    let mut amount = use_signal(|| "5000".to_string());
    let mut reason = use_signal(String::new);
    let l = lang();
    let q = query().trim().to_lowercase();
    let digits: String = q.chars().filter(|c| c.is_ascii_digit()).collect();
    let matches: Vec<(Id, String, String, i64)> = {
        let db = DB.read();
        db.customers
            .iter()
            .filter(|c| !c.archived)
            .filter(|c| q.is_empty() || c.name().to_lowercase().contains(&q) || (digits.len() >= 3 && (c.phone.contains(&digits) || c.card_no.replace(' ', "").contains(&digits))))
            .take(6)
            .map(|c| (c.id, c.name(), c.card_no.clone(), c.points))
            .collect()
    };
    let n = parse_i64(&amount());
    let valid = chosen().is_some() && n != 0 && !reason().trim().is_empty();
    let save = move |_| {
        let Some(cid) = chosen() else { return };
        let n = parse_i64(&amount());
        if n == 0 {
            return;
        }
        let note = reason().trim().to_string();
        let now = now();
        let log = format!("{} {:+} · {}", t("tx.adjust"), n, DB.peek().customer_name(Some(cid)));
        mutate(|db| {
            db.give_points(cid, n, TxKind::Adjust, note, now);
            db.log(now, log, false);
        });
        toast(format!("{}: {}", t("loyalty.adjust_done"), if n > 0 { format!("+{}", fmt::num(n)) } else { fmt::num(n) }), "sliders-horizontal", "success");
        onclose.call(());
    };
    rsx! {
        Modal { title: t("loyalty.adjust"), onclose: move |_| onclose.call(()),
            div { class: "modal-body",
                div { class: "field",
                    label { class: "label", {t("common.customer")} }
                    div { class: "search",
                        Icon { name: "search", size: 16 }
                        input {
                            class: "input",
                            value: "{query}",
                            placeholder: t("loyalty.adjust_find"),
                            oninput: move |e| query.set(e.value()),
                            onmounted: move |e| async move {
                                let _ = e.set_focus(true).await;
                            },
                        }
                    }
                    div { class: "list", style: "border: 1px solid var(--c-border); border-radius: 12px; overflow: hidden",
                        if matches.is_empty() {
                            div { class: "list-row small muted", {t("common.no_results")} }
                        }
                        for (id, name, card, p) in matches {
                            div {
                                key: "{id}",
                                class: if chosen() == Some(id) { "list-row click active" } else { "list-row click" },
                                style: "padding-top: 8px; padding-bottom: 8px",
                                onclick: move |_| chosen.set(Some(id)),
                                Avatar { name: name.clone(), size: "sm" }
                                div { class: "meta", span { class: "title small", "{name}" } span { class: "sub num", "{card}" } }
                                span { class: "num small muted", "{pts(p, l)}" }
                                if chosen() == Some(id) { Icon { name: "check", size: 16, class: "tone-accent" } }
                            }
                        }
                    }
                }
                div { class: "grid-2",
                    div { class: "field",
                        label { class: "label", {t("loyalty.adjust_points")} }
                        input { class: "input num", value: "{amount}", oninput: move |e| amount.set(e.value()) }
                        div { class: "row gap-8",
                            for v in [-5000i64, 5000, 10000] {
                                button { key: "{v}", class: "chip", onclick: move |_| amount.set(v.to_string()), if v > 0 { "+{fmt::num(v)}" } else { "{fmt::num(v)}" } }
                            }
                        }
                    }
                    div { class: "field",
                        label { class: "label", {t("contacts.reason")} }
                        input { class: "input", value: "{reason}", placeholder: t("loyalty.reason_hint"), oninput: move |e| reason.set(e.value()) }
                    }
                }
                div { class: "callout", Icon { name: "info", size: 15 } span { {t("loyalty.adjust_hint")} } }
            }
            div { class: "modal-foot",
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
            }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("loyalty.subtitle", "Keshbek dasturi: 1 ball = 1 so‘m, Telegram botdagi raqamli karta", "Кешбэк-программа: 1 балл = 1 сум, цифровая карта в Telegram-боте", "Cashback programme: 1 point = 1 so‘m, a digital card in the Telegram bot"),
    ("loyalty.disabled", "Dastur o‘chirilgan: ballar berilmayapti", "Программа выключена: баллы не начисляются", "The programme is off: no points are earned"),
    ("loyalty.adjust", "Ballarni tuzatish", "Скорректировать баллы", "Adjust points"),
    ("loyalty.members", "A’zolar", "Участники", "Members"),
    ("loyalty.members_foot", "+{n} shu oy", "+{n} в этом месяце", "+{n} this month"),
    ("loyalty.liability", "Ballar majburiyati", "Обязательства по баллам", "Points liability"),
    ("loyalty.liability_foot", "mijozlar hisobidagi ballar, so‘mda", "баллы на счетах клиентов, в сумах", "points on customer balances, in so‘m"),
    ("loyalty.earned", "Shu oy berilgan ballar", "Начислено за месяц", "Points earned this month"),
    ("loyalty.of_bonus", "shundan bonus", "из них бонусы", "of which bonuses"),
    ("loyalty.earned_foot", "xaridlardan keshbek", "кешбэк с покупок", "cashback from purchases"),
    ("loyalty.redeemed", "Shu oy sarflangan", "Списано за месяц", "Redeemed this month"),
    ("loyalty.rate", "Sarflanish ulushi", "Доля списания", "Redemption rate"),
    ("loyalty.rate_foot", "oxirgi 90 kun", "за последние 90 дней", "last 90 days"),
    ("loyalty.tiers", "Darajalar", "Уровни", "Tiers"),
    ("loyalty.levels_hint", "Daraja umrbod xaridlar summasiga qarab beriladi", "Уровень зависит от суммы покупок за всё время", "Tiers follow lifetime spend"),
    ("loyalty.from", "{sum} dan", "от {sum}", "from {sum}"),
    ("loyalty.cashback", "keshbek", "кешбэк", "cashback"),
    ("loyalty.settings", "Dastur sozlamalari", "Настройки программы", "Programme settings"),
    ("loyalty.enabled", "Dastur yoqilgan", "Программа включена", "Programme on"),
    ("loyalty.threshold", "Jami xarid, so‘mdan", "Сумма покупок от, сум", "Lifetime spend from, so‘m"),
    ("loyalty.cashback_pct", "Keshbek, %", "Кешбэк, %", "Cashback, %"),
    ("loyalty.invalid", "Chegaralar darajadan darajaga o‘sib borishi kerak", "Пороги должны расти от уровня к уровню", "Thresholds must go up tier by tier"),
    ("loyalty.welcome", "Xush kelibsiz bonusi", "Приветственный бонус", "Welcome bonus"),
    ("loyalty.birthday", "Tug‘ilgan kun bonusi", "Бонус на день рождения", "Birthday bonus"),
    ("loyalty.referral", "Do‘stni taklif qilgani uchun", "За приглашённого друга", "Referral bonus"),
    ("loyalty.expiry", "Ballar amal qilish muddati, kun", "Срок жизни баллов, дней", "Points expire after, days"),
    ("loyalty.expiry_hint", "oxirgi xariddan keyin", "после последней покупки", "after the last purchase"),
    ("loyalty.max_redeem", "Chekning necha foizini ball bilan to‘lash mumkin", "Какую долю чека можно оплатить баллами, %", "Max share of a receipt paid with points, %"),
    ("loyalty.exclude_rx", "Retseptli dorilarga keshbek yo‘q", "Без кешбэка на рецептурные препараты", "No cashback on prescription medicines"),
    ("loyalty.exclude_rx_hint", "Retsept bo‘yicha beriladigan dorilarni reklama qilib, sotishini rag‘batlantirib bo‘lmaydi. Shuning uchun Rx dorilar ball to‘plamaydi va bonus takliflarida ko‘rinmaydi. Bu qoidani yoqilgan holda qoldiring.", "Рецептурные препараты нельзя рекламировать и стимулировать их продажу. Поэтому Rx-препараты не дают баллов и не попадают в бонусные предложения. Оставьте правило включённым.", "Prescription-only medicines may not be advertised or pushed with incentives, so Rx items earn no points and never appear in bonus offers. Keep this rule on."),
    ("loyalty.unsaved", "Saqlanmagan o‘zgarishlar bor", "Есть несохранённые изменения", "Unsaved changes"),
    ("loyalty.save_ok", "Dastur sozlamalari saqlandi", "Настройки программы сохранены", "Programme settings saved"),
    ("loyalty.tier_changed", "{n} ta mijozning darajasi qayta hisoblandi", "уровень пересчитан у {n} клиентов", "{n} customers moved to a new tier"),
    ("loyalty.flow", "Ballar oqimi, haftalar bo‘yicha", "Движение баллов по неделям", "Points flow by week"),
    ("loyalty.series_earned", "Berildi", "Начислено", "Earned"),
    ("loyalty.series_redeemed", "Sarflandi", "Списано", "Redeemed"),
    ("loyalty.top", "Eng ko‘p balli a’zolar", "Лидеры по баллам", "Top members by points"),
    ("loyalty.ledger", "So‘nggi ball harakatlari", "Последние движения баллов", "Recent points activity"),
    ("loyalty.no_ledger", "Ball harakatlari hali yo‘q", "Движений по баллам пока нет", "No points activity yet"),
    ("loyalty.card_preview", "Telegramdagi raqamli karta", "Цифровая карта в Telegram", "Digital card in Telegram"),
    ("loyalty.preview_for", "Kimning kartasi", "Чья карта", "Card of"),
    ("loyalty.tg_hello", "Assalomu alaykum, {name}! Sizning sodiqlik kartangiz:", "Здравствуйте, {name}! Ваша карта лояльности:", "Hello, {name}! Here is your loyalty card:"),
    ("loyalty.tg_show", "Kassada QR kodni ko‘rsating: ballar o‘zi yoziladi.", "Покажите QR-код на кассе: баллы начислятся сами.", "Show the QR code at the till: points are added automatically."),
    ("loyalty.btn_points", "Ballarim", "Мои баллы", "My points"),
    ("loyalty.btn_meds", "Dorilarim", "Лекарства", "Medicines"),
    ("loyalty.btn_branches", "Filiallar", "Аптеки", "Pharmacies"),
    ("loyalty.card_note", "Karta Daybook Telegram botida turadi: mijoz uni kassada ko‘rsatadi, ballar va dori eslatmalari ham shu yerga keladi. Plastik karta kerak emas.", "Карта живёт в Telegram-боте Daybook: клиент показывает её на кассе, туда же приходят баллы и напоминания о лекарствах. Пластик не нужен.", "The card lives in the Daybook Telegram bot: customers show it at the till, and points and refill reminders arrive there too. No plastic needed."),
    ("loyalty.adjust_find", "Ism, telefon yoki karta raqami", "Имя, телефон или номер карты", "Name, phone or card number"),
    ("loyalty.adjust_points", "Ballar (+ yoki −)", "Баллы (+ или −)", "Points (+ or −)"),
    ("loyalty.reason_hint", "Masalan: kassadagi xato", "Например: ошибка на кассе", "e.g. a till mistake"),
    ("loyalty.adjust_done", "Ballar tuzatildi", "Баллы скорректированы", "Points adjusted"),
    ("loyalty.adjust_hint", "Tuzatish jurnalga yoziladi va mijozning Telegram kartasida ko‘rinadi.", "Корректировка пишется в журнал и видна в Telegram-карте клиента.", "Adjustments go to the audit log and show in the customer’s Telegram card."),
];
