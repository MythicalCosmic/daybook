//! Segments: saved audiences built from rules (tier, spend, conditions, consent, birthdays,
//! refills ...) with live counts, Telegram reach and value, a rule builder, and the RFM matrix
//! that opens the matching customers in one click.

use crm::analytics::{self, RfmSegment};
use crm::fmt;
use crm::i18n::{Entry, Lang};
use crm::model::*;
use dioxus::prelude::*;

use crate::state::*;
use crate::ui::*;

const ICONS: &[&str] = &[
    "layers", "crown", "heart-pulse", "activity", "heart", "hourglass", "sparkles", "cake", "send", "briefcase", "baby", "gift", "users", "pill",
    "star", "target",
];
const HUES: &[u16] = &[24, 42, 95, 150, 205, 230, 265, 330];

fn static_icon(s: &str) -> &'static str {
    ICON_NAMES.iter().copied().find(|n| *n == s).unwrap_or("layers")
}

fn ops_for(f: Field) -> &'static [Op] {
    match f {
        Field::TotalSpent | Field::Orders | Field::DaysSinceLast | Field::Age | Field::Points | Field::BirthdayInDays | Field::RefillDueInDays => {
            &[Op::Gt, Op::Lt, Op::Eq, Op::Ne]
        }
        Field::Tier | Field::Gender | Field::Branch | Field::Source | Field::Condition => &[Op::Eq, Op::Ne],
        Field::Tag => &[Op::Contains, Op::Ne],
        Field::ConsentTelegram | Field::ConsentSms | Field::Corporate => &[Op::IsTrue, Op::IsFalse],
    }
}

fn default_value(f: Field, first_branch: Id) -> String {
    match f {
        Field::Tier => "gold".into(),
        Field::Gender => "female".into(),
        Field::Condition => "hypertension".into(),
        Field::Source => "walk_in".into(),
        Field::Branch => first_branch.to_string(),
        Field::TotalSpent => "1000000".into(),
        Field::Orders => "5".into(),
        Field::DaysSinceLast => "60".into(),
        Field::Age => "60".into(),
        Field::Points => "50000".into(),
        Field::BirthdayInDays | Field::RefillDueInDays => "7".into(),
        Field::Tag | Field::ConsentTelegram | Field::ConsentSms | Field::Corporate => String::new(),
    }
}

fn is_number(f: Field) -> bool {
    matches!(f, Field::TotalSpent | Field::Orders | Field::DaysSinceLast | Field::Age | Field::Points | Field::BirthdayInDays | Field::RefillDueInDays)
}

/// A rule in words: "Daraja teng Oltin", "Oxirgi xariddan beri, kun: 60 dan ko‘p".
fn rule_text(r: &Rule, branches: &[(Id, String)], l: Lang) -> String {
    let field = t(r.field.key());
    let op = t(r.op.key());
    let v = r.value.trim();
    let value = match r.field {
        Field::Tier => Tier::from_slug(v).map(|x| t(x.key())).unwrap_or_else(|| v.to_string()),
        Field::Gender => Gender::from_slug(v).map(|x| t(x.key())).unwrap_or_else(|| v.to_string()),
        Field::Condition => Condition::from_slug(v).map(|x| t(x.key())).unwrap_or_else(|| v.to_string()),
        Field::Source => Source::from_slug(v).map(|x| t(x.key())).unwrap_or_else(|| v.to_string()),
        Field::Branch => v.parse::<Id>().ok().and_then(|id| branches.iter().find(|b| b.0 == id).map(|b| b.1.clone())).unwrap_or_else(|| v.to_string()),
        Field::TotalSpent | Field::Points => fmt::num(v.replace([' ', '\u{a0}'], "").parse::<i64>().unwrap_or(0)),
        Field::ConsentTelegram | Field::ConsentSms | Field::Corporate => String::new(),
        _ => v.to_string(),
    };
    if value.is_empty() {
        format!("{field}: {op}")
    } else if l.is_uzbek() && matches!(r.op, Op::Gt | Op::Lt) {
        format!("{field}: {value} {op}")
    } else {
        format!("{field} {op} {value}")
    }
}

#[derive(Clone, PartialEq)]
struct SegCard {
    id: Id,
    name: String,
    description: String,
    icon: &'static str,
    hue: u16,
    system: bool,
    count: usize,
    reach: usize,
    ltv: Money,
    sample: Vec<String>,
    rules: String,
}

#[component]
pub fn Segments() -> Element {
    let mut editing = use_signal(|| None::<Option<Id>>);
    let cards = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let l = crate::state::lang();
        let branches: Vec<(Id, String)> = db.branches.iter().map(|b| (b.id, b.name.clone())).collect();
        let joiner = if l == Lang::Ru { " · " } else { " · " };
        db.segments
            .iter()
            .map(|s| {
                let members = db.segment_members(s, today);
                let reach = members.iter().filter(|id| db.customer(**id).map(|c| c.consent.telegram && c.telegram.is_some()).unwrap_or(false)).count();
                let ltv: Money = members.iter().filter_map(|id| db.customer(*id)).map(|c| c.total_spent).sum();
                let sample: Vec<String> = members.iter().take(5).filter_map(|id| db.customer(*id)).map(|c| c.name()).collect();
                let word = if s.match_all { crm::i18n::pick(l, " va ", " и ", " and ") } else { crm::i18n::pick(l, " yoki ", " или ", " or ") };
                let rules: Vec<String> = s.rules.iter().map(|r| rule_text(r, &branches, l)).collect();
                let _ = joiner;
                SegCard {
                    id: s.id,
                    name: s.name.clone(),
                    description: s.description.clone(),
                    icon: static_icon(&s.icon),
                    hue: s.hue,
                    system: s.system,
                    count: members.len(),
                    reach,
                    ltv,
                    sample,
                    rules: rules.join(&word),
                }
            })
            .collect::<Vec<_>>()
    });
    let rfm = use_memo(move || analytics::rfm_breakdown(&DB.read(), crate::state::today()));
    let l = lang();
    let list = cards();
    let subtitle = format!("{} · {}", fmt::plural(list.len() as i64, l, "segment|сегмент|сегмента|сегментов|segment|segments"), t("segments.subtitle"));

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.segments"), subtitle,
                button { class: "btn primary", onclick: move |_| editing.set(Some(None)),
                    Icon { name: "plus", size: 16 }
                    span { class: "label-text", {t("segments.new")} }
                }
            }
            if list.is_empty() {
                div { class: "card", Empty { icon: "layers", title: t("segments.empty") } }
            }
            div { class: "grid-auto", style: "grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))",
                for s in list {
                    SegmentCard { key: "{s.id}", s: s.clone(), onedit: move |id| editing.set(Some(Some(id))) }
                }
            }
            RfmMatrix { data: rfm() }
            if let Some(seg) = editing() {
                SegmentBuilder { seg, onclose: move |_| editing.set(None) }
            }
        }
    }
}

#[component]
fn SegmentCard(s: SegCard, onedit: EventHandler<Id>) -> Element {
    let l = lang();
    let id = s.id;
    let count = fmt::num(s.count as i64);
    let word = fmt::plural(s.count as i64, l, "mijoz|клиент|клиента|клиентов|customer|customers").replace(&format!("{}\u{a0}", count), "");
    let reach = fmt::num(s.reach as i64);
    let ltv = money_short(s.ltv);
    let hue = s.hue;
    rsx! {
        div { class: "card pad stack gap-12",
            div { class: "row top gap-12",
                span { class: "avatar lg square", style: "--h: {hue}", Icon { name: s.icon, size: 20 } }
                div { class: "grow stack", style: "gap: 3px; min-width: 0",
                    div { class: "row gap-6", style: "gap: 6px",
                        span { class: "strong truncate", style: "font-size: 15px", "{s.name}" }
                        if s.system { span { class: "subtle", title: t("segments.system"), Icon { name: "lock", size: 13 } } }
                    }
                    span { class: "small muted clamp-2", "{s.description}" }
                }
                button { class: "icon-btn sm", title: t("common.edit"), onclick: move |_| onedit.call(id), Icon { name: "pen-line", size: 15 } }
            }
            div { class: "row between", style: "align-items: flex-end",
                div { class: "row gap-8", style: "align-items: baseline",
                    span { class: "num", style: "font-size: 28px; font-weight: 750; letter-spacing: -0.02em; line-height: 1", "{count}" }
                    span { class: "small muted", "{word}" }
                }
                div { class: "avatars",
                    for (k, n) in s.sample.iter().cloned().enumerate() {
                        Avatar { key: "{k}", name: n, size: "sm" }
                    }
                }
            }
            div { class: "row wrap small muted", style: "gap: 4px 14px",
                span { class: "row gap-4", Icon { name: "send", size: 13, class: "tone-info" } b { class: "num", style: "color: var(--c-text)", "{reach}" } " " {t("segments.reachable")} }
                span { class: "row gap-4", Icon { name: "wallet", size: 13, class: "tone-success" } b { class: "num", style: "color: var(--c-text)", "{ltv}" } " " {t("segments.ltv")} }
            }
            div { class: "xs subtle clamp-2", style: "padding: 8px 10px; border-radius: 10px; background: var(--c-surface-2)",
                Icon { name: "filter", size: 11 }
                " {s.rules}"
            }
            div { class: "row gap-8 wrap",
                button { class: "btn soft sm", onclick: move |_| go(&format!("/campaigns?segment={id}")), Icon { name: "send", size: 14 } {t("segments.send")} }
                button { class: "btn ghost sm", onclick: move |_| go(&format!("/contacts?segment={id}")), Icon { name: "users", size: 14 } {t("segments.show")} }
            }
        }
    }
}

#[component]
fn RfmMatrix(data: Vec<(RfmSegment, u32, Money)>) -> Element {
    let total: u32 = data.iter().map(|x| x.1).sum::<u32>().max(1);
    let get = |s: RfmSegment| data.iter().find(|x| x.0 == s).map(|x| (x.1, x.2)).unwrap_or((0, 0));
    let layout = [
        RfmSegment::CantLose,
        RfmSegment::Loyal,
        RfmSegment::Champions,
        RfmSegment::AtRisk,
        RfmSegment::NeedAttention,
        RfmSegment::Promising,
        RfmSegment::Lost,
        RfmSegment::Hibernating,
        RfmSegment::NewCustomers,
    ];
    let tiles: Vec<(RfmSegment, u32, Money, f64)> = layout
        .iter()
        .map(|s| {
            let (n, v) = get(*s);
            (*s, n, v, n as f64 / total as f64 * 100.0)
        })
        .collect();
    let plays: Vec<(RfmSegment, &'static str, String)> = vec![
        (RfmSegment::CantLose, "phone-call", t("segments.play_cant_lose")),
        (RfmSegment::AtRisk, "repeat", t("segments.play_at_risk")),
        (RfmSegment::NewCustomers, "sparkles", t("segments.play_new")),
        (RfmSegment::Champions, "hand-heart", t("segments.play_champions")),
    ];
    let l = lang();
    rsx! {
        div { class: "card",
            div { class: "card-head",
                div {
                    div { class: "card-title", Icon { name: "layout-grid", size: 16, class: "tone-accent" } {t("segments.rfm_title")} }
                    div { class: "small muted", style: "margin-top: 3px", {t("segments.rfm_hint")} }
                }
            }
            div { class: "card-body",
                div { class: "grid-main", style: "align-items: stretch",
                    div { class: "stack gap-8",
                        div { class: "xs subtle upper row gap-4", Icon { name: "arrow-up", size: 12 } {t("segments.frequency")} }
                        div { style: "display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px",
                            for (seg, n, v, share) in tiles {
                                {
                                    let tone = seg.tone();
                                    let slug = seg.slug();
                                    let value = money_short(v);
                                    let share_s = fmt::pct(share, l);
                                    rsx! {
                                        div {
                                            key: "{slug}",
                                            class: "callout {tone}",
                                            style: "flex-direction: column; align-items: stretch; gap: 2px; cursor: pointer; min-height: 104px; padding: 12px",
                                            onclick: move |_| go(&format!("/contacts?rfm={slug}")),
                                            span { class: "strong small truncate", {t(seg.key())} }
                                            span { class: "num", style: "font-size: 24px; font-weight: 750; letter-spacing: -0.02em; color: var(--c-text)", "{n}" }
                                            div { class: "row between xs", style: "opacity: .85",
                                                span { class: "num truncate", "{value}" }
                                                span { class: "num", "{share_s}" }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        div { class: "xs subtle upper row gap-4", style: "justify-content: flex-end", {t("segments.recency")} Icon { name: "arrow-right", size: 12 } }
                    }
                    div { class: "stack gap-8",
                        div { class: "section-title", {t("segments.playbook")} }
                        for (seg, icon, text) in plays {
                            {
                                let slug = seg.slug();
                                let (n, _) = get(seg);
                                rsx! {
                                    div { key: "{slug}", class: "insight {seg.tone()}", style: "cursor: pointer", onclick: move |_| go(&format!("/contacts?rfm={slug}")),
                                        span { class: "ic", Icon { name: icon, size: 16 } }
                                        div { class: "grow",
                                            div { class: "row between",
                                                span { class: "strong small", {t(seg.key())} }
                                                span { class: "badge sm num", "{n}" }
                                            }
                                            div { class: "xs muted", style: "margin-top: 2px; line-height: 1.45", "{text}" }
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
fn SegmentBuilder(seg: Option<Id>, onclose: EventHandler<()>) -> Element {
    let init = use_hook(move || seg.and_then(|id| DB.peek().segment(id).cloned()));
    let first_branch = DB.read().branches.first().map(|b| b.id).unwrap_or(0);
    let i1 = init.clone();
    let mut name = use_signal(move || i1.as_ref().map(|s| s.name.clone()).unwrap_or_default());
    let i2 = init.clone();
    let mut desc = use_signal(move || i2.as_ref().map(|s| s.description.clone()).unwrap_or_default());
    let i3 = init.clone();
    let mut icon = use_signal(move || i3.as_ref().map(|s| static_icon(&s.icon)).unwrap_or("layers"));
    let i4 = init.clone();
    let mut hue = use_signal(move || i4.as_ref().map(|s| s.hue).unwrap_or(205));
    let i5 = init.clone();
    let mut match_all = use_signal(move || i5.as_ref().map(|s| s.match_all).unwrap_or(true));
    let i6 = init.clone();
    let mut rules = use_signal(move || {
        i6.as_ref().map(|s| s.rules.clone()).unwrap_or_else(|| vec![Rule { field: Field::Tier, op: Op::Eq, value: "gold".into() }])
    });
    let mut confirm = use_signal(|| false);
    let system = init.as_ref().map(|s| s.system).unwrap_or(false);
    let preview = use_memo(move || {
        let db = DB.read();
        let today = crate::state::today();
        let s = Segment { id: 0, name: String::new(), description: String::new(), rules: rules(), match_all: match_all(), hue: 0, system: false, icon: String::new() };
        let members = db.segment_members(&s, today);
        let reach = members.iter().filter(|id| db.customer(**id).map(|c| c.consent.telegram && c.telegram.is_some()).unwrap_or(false)).count();
        let ltv: Money = members.iter().filter_map(|id| db.customer(*id)).map(|c| c.total_spent).sum();
        let sample: Vec<String> = members.iter().take(7).filter_map(|id| db.customer(*id)).map(|c| c.name()).collect();
        (members.len(), reach, ltv, sample)
    });
    let branches: Vec<(Id, String)> = DB.read().branches.iter().map(|b| (b.id, b.name.clone())).collect();
    let l = lang();
    let (count, reach, ltv, sample) = preview();
    let count_s = fmt::plural(count as i64, l, "mijoz|клиент|клиента|клиентов|customer|customers");
    let valid = !name().trim().is_empty();
    let title = if seg.is_some() { t("segments.edit") } else { t("segments.new") };
    let all_v = if match_all() { "all".to_string() } else { "any".to_string() };
    let cur_hue = hue();
    let cur_icon = icon();
    let save = move |_| {
        let nm = name().trim().to_string();
        if nm.is_empty() {
            return;
        }
        let (d, ic, h, all, rs) = (desc().trim().to_string(), icon().to_string(), hue(), match_all(), rules());
        let log = format!("{}: {nm}", t("segments.saved"));
        mutate(|db| {
            match seg {
                Some(id) => {
                    if let Some(s) = db.segment_mut(id) {
                        s.name = nm;
                        s.description = d;
                        s.icon = ic;
                        s.hue = h;
                        s.match_all = all;
                        s.rules = rs;
                    }
                }
                None => {
                    let id = db.new_id();
                    db.segments.push(Segment { id, name: nm, description: d, rules: rs, match_all: all, hue: h, system: false, icon: ic });
                }
            }
            db.log(crate::state::now(), log, false);
        });
        toast(t("segments.saved"), "layers", "success");
        onclose.call(());
    };
    rsx! {
        Drawer { title, icon: "layers", onclose: move |_| onclose.call(()),
            div { class: "drawer-body",
                div { class: "card flat pad stack gap-8", style: "background: var(--c-accent-soft); border-color: transparent",
                    div { class: "xs upper", style: "color: var(--c-accent-fg)", {t("segments.live")} }
                    div { class: "row between",
                        span { class: "num", style: "font-size: 26px; font-weight: 750; letter-spacing: -0.02em", "{count_s}" }
                        div { class: "avatars",
                            for (k, n) in sample.iter().cloned().enumerate() {
                                Avatar { key: "{k}", name: n, size: "sm" }
                            }
                        }
                    }
                    div { class: "row wrap small muted", style: "gap: 4px 14px",
                        span { class: "row gap-4", Icon { name: "send", size: 13 } b { class: "num", "{reach}" } " " {t("segments.reachable")} }
                        span { class: "row gap-4", Icon { name: "wallet", size: 13 } b { class: "num", "{money_short(ltv)}" } " " {t("segments.ltv")} }
                    }
                    if count == 0 {
                        div { class: "small tone-warning", {t("segments.no_match")} }
                    }
                }
                div { class: "field",
                    label { class: "label", {t("segments.name_label")} }
                    input {
                        class: "input",
                        value: "{name}",
                        placeholder: t("segments.name_hint"),
                        oninput: move |e| name.set(e.value()),
                        onmounted: move |e| async move {
                            let _ = e.set_focus(true).await;
                        },
                    }
                }
                div { class: "field",
                    label { class: "label", {t("common.description")} }
                    input { class: "input", value: "{desc}", oninput: move |e| desc.set(e.value()) }
                }
                div { class: "row between wrap", style: "gap: 10px",
                    div { class: "row wrap", style: "gap: 4px",
                        for ic in ICONS.iter().copied() {
                            button {
                                key: "{ic}",
                                class: if cur_icon == ic { "icon-btn sm bordered tone-accent" } else { "icon-btn sm" },
                                onclick: move |_| icon.set(ic),
                                Icon { name: ic, size: 15 }
                            }
                        }
                    }
                    div { class: "row", style: "gap: 6px",
                        for h in HUES.iter().copied() {
                            button {
                                key: "{h}",
                                class: "avatar xs",
                                style: if cur_hue == h { "--h: {h}; border: 0; cursor: pointer; box-shadow: 0 0 0 2px var(--c-surface), 0 0 0 4px var(--c-primary)" } else { "--h: {h}; border: 0; cursor: pointer" },
                                onclick: move |_| hue.set(h),
                            }
                        }
                    }
                }
                div { class: "stack gap-8",
                    div { class: "row between wrap", style: "gap: 8px",
                        span { class: "label", {t("segments.rules")} }
                        Segmented {
                            options: vec![("all".into(), t("segments.match_all")), ("any".into(), t("segments.match_any"))],
                            value: all_v,
                            onchange: move |v: String| match_all.set(v == "all"),
                        }
                    }
                    for (i, r) in rules().iter().cloned().enumerate() {
                        RuleRow {
                            key: "{i}",
                            index: i,
                            rule: r,
                            branches: branches.clone(),
                            first_branch,
                            onchange: move |(i, r): (usize, Rule)| {
                                if let Some(x) = rules.write().get_mut(i) {
                                    *x = r;
                                }
                            },
                            onremove: move |i: usize| {
                                let mut w = rules.write();
                                if i < w.len() {
                                    w.remove(i);
                                }
                            },
                        }
                    }
                    button {
                        class: "btn soft sm",
                        style: "align-self: flex-start",
                        onclick: move |_| rules.write().push(Rule { field: Field::DaysSinceLast, op: Op::Gt, value: "60".into() }),
                        Icon { name: "plus", size: 14 }
                        {t("segments.add_rule")}
                    }
                }
            }
            div { class: "drawer-foot",
                if let Some(id) = seg {
                    if !system {
                        if confirm() {
                            button {
                                class: "btn danger solid",
                                onclick: move |_| {
                                    mutate(|db| db.segments.retain(|s| s.id != id));
                                    toast(t("segments.deleted"), "trash-2", "info");
                                    onclose.call(());
                                },
                                Icon { name: "trash-2", size: 15 }
                                {t("segments.confirm_delete")}
                            }
                        } else {
                            button { class: "btn ghost danger", onclick: move |_| confirm.set(true), Icon { name: "trash-2", size: 15 } {t("common.delete")} }
                        }
                    } else {
                        span { class: "xs muted row gap-4", Icon { name: "lock", size: 13 } {t("segments.system")} }
                    }
                }
                span { class: "spacer" }
                button { class: "btn ghost", onclick: move |_| onclose.call(()), {t("common.cancel")} }
                button { class: "btn primary", disabled: !valid, onclick: save, Icon { name: "check", size: 16 } {t("common.save")} }
            }
        }
    }
}

#[component]
fn RuleRow(index: usize, rule: Rule, branches: Vec<(Id, String)>, first_branch: Id, onchange: EventHandler<(usize, Rule)>, onremove: EventHandler<usize>) -> Element {
    let ops = ops_for(rule.field);
    let field = rule.field;
    let op = rule.op;
    let value = rule.value.clone();
    let mk = move |f: Field, o: Op, v: String| Rule { field: f, op: o, value: v };
    rsx! {
        div { class: "row wrap", style: "gap: 8px; padding: 10px; border: 1px solid var(--c-border); border-radius: 12px; background: var(--c-surface)",
            select {
                class: "select sm",
                style: "flex: 1 1 200px; width: auto; min-width: 0",
                onchange: move |e| {
                    let f = Field::from_slug(&e.value()).unwrap_or(Field::Tier);
                    onchange.call((index, mk(f, ops_for(f)[0], default_value(f, first_branch))));
                },
                for f in Field::ALL.iter().copied() {
                    option { key: "{f.slug()}", value: "{f.slug()}", selected: f == field, {t(f.key())} }
                }
            }
            select {
                class: "select sm",
                style: "flex: 0 1 130px; width: auto; min-width: 0",
                onchange: {
                    let value = value.clone();
                    move |e: FormEvent| onchange.call((index, mk(field, Op::from_slug(&e.value()).unwrap_or(Op::Eq), value.clone())))
                },
                for o in ops.iter().copied() {
                    option { key: "{o.slug()}", value: "{o.slug()}", selected: o == op, {t(o.key())} }
                }
            }
            {
                match field {
                    Field::Tier => rsx! {
                        select { class: "select sm", style: "flex: 1 1 130px; width: auto; min-width: 0", onchange: move |e| onchange.call((index, mk(field, op, e.value()))),
                            for x in Tier::ALL.iter().copied() { option { key: "{x.slug()}", value: "{x.slug()}", selected: value == x.slug(), {t(x.key())} } }
                        }
                    },
                    Field::Gender => rsx! {
                        select { class: "select sm", style: "flex: 1 1 130px; width: auto; min-width: 0", onchange: move |e| onchange.call((index, mk(field, op, e.value()))),
                            for x in Gender::ALL.iter().copied() { option { key: "{x.slug()}", value: "{x.slug()}", selected: value == x.slug(), {t(x.key())} } }
                        }
                    },
                    Field::Condition => rsx! {
                        select { class: "select sm", style: "flex: 1 1 130px; width: auto; min-width: 0", onchange: move |e| onchange.call((index, mk(field, op, e.value()))),
                            for x in Condition::ALL.iter().copied() { option { key: "{x.slug()}", value: "{x.slug()}", selected: value == x.slug(), {t(x.key())} } }
                        }
                    },
                    Field::Source => rsx! {
                        select { class: "select sm", style: "flex: 1 1 130px; width: auto; min-width: 0", onchange: move |e| onchange.call((index, mk(field, op, e.value()))),
                            for x in Source::ALL.iter().copied() { option { key: "{x.slug()}", value: "{x.slug()}", selected: value == x.slug(), {t(x.key())} } }
                        }
                    },
                    Field::Branch => rsx! {
                        select { class: "select sm", style: "flex: 1 1 130px; width: auto; min-width: 0", onchange: move |e| onchange.call((index, mk(field, op, e.value()))),
                            for (bid, bname) in branches.iter().cloned() { option { key: "{bid}", value: "{bid}", selected: value == bid.to_string(), "{bname}" } }
                        }
                    },
                    Field::ConsentTelegram | Field::ConsentSms | Field::Corporate => rsx! {},
                    f if is_number(f) => rsx! {
                        input { class: "input sm num", style: "flex: 1 1 110px; width: auto; min-width: 0", inputmode: "numeric", value: "{value}", oninput: move |e| onchange.call((index, mk(field, op, e.value()))) }
                    },
                    _ => rsx! {
                        input { class: "input sm", style: "flex: 1 1 130px; width: auto; min-width: 0", value: "{value}", oninput: move |e| onchange.call((index, mk(field, op, e.value()))) }
                    },
                }
            }
            button { class: "icon-btn sm", title: t("common.delete"), onclick: move |_| onremove.call(index), Icon { name: "x", size: 15 } }
        }
    }
}

pub const STRINGS: &[Entry] = &[
    ("segments.subtitle", "kampaniyalar va avtomatlashtirish uchun auditoriyalar", "аудитории для рассылок и автоматизаций", "audiences for campaigns and automations"),
    ("segments.new", "Yangi segment", "Новый сегмент", "New segment"),
    ("segments.edit", "Segmentni tahrirlash", "Изменить сегмент", "Edit segment"),
    ("segments.empty", "Segmentlar hali yo‘q", "Сегментов пока нет", "No segments yet"),
    ("segments.system", "Tizim segmenti: o‘chirib bo‘lmaydi", "Системный сегмент: удалить нельзя", "Built-in segment: can’t be deleted"),
    ("segments.reachable", "Telegramda", "в Telegram", "on Telegram"),
    ("segments.ltv", "jami xarid", "сумма покупок", "lifetime value"),
    ("segments.send", "Kampaniya yuborish", "Отправить рассылку", "Send campaign"),
    ("segments.show", "Mijozlarni ko‘rish", "Показать клиентов", "Show customers"),
    ("segments.live", "Hozir mos keladi", "Сейчас подходят", "Matching right now"),
    ("segments.no_match", "Hech kim mos kelmadi: shartlarni yumshating", "Никто не подходит: ослабьте условия", "Nobody matches: loosen the rules"),
    ("segments.name_label", "Segment nomi", "Название сегмента", "Segment name"),
    ("segments.name_hint", "Masalan: Diabet, 60 kundan beri kelmagan", "Например: диабет, не приходили 60 дней", "e.g. Diabetes, gone 60 days"),
    ("segments.rules", "Shartlar", "Условия", "Rules"),
    ("segments.match_all", "Hamma shart", "Все условия", "All rules"),
    ("segments.match_any", "Istalgan shart", "Любое условие", "Any rule"),
    ("segments.add_rule", "Shart qo‘shish", "Добавить условие", "Add rule"),
    ("segments.saved", "Segment saqlandi", "Сегмент сохранён", "Segment saved"),
    ("segments.deleted", "Segment o‘chirildi", "Сегмент удалён", "Segment deleted"),
    ("segments.confirm_delete", "Ha, o‘chirish", "Да, удалить", "Yes, delete"),
    ("segments.rfm_title", "RFM matritsa", "RFM-матрица", "RFM matrix"),
    ("segments.rfm_hint", "Mijozlar oxirgi xarid (R), xaridlar soni (F) va summasi (M) bo‘yicha guruhlangan. Katakni bosing: ro‘yxat ochiladi.", "Клиенты сгруппированы по давности (R), частоте (F) и сумме (M) покупок. Нажмите на ячейку, чтобы открыть список.", "Customers grouped by recency (R), frequency (F) and spend (M). Click a tile to open the list."),
    ("segments.recency", "Yaqinda xarid qilgan", "Недавность покупки", "Bought recently"),
    ("segments.frequency", "Ko‘p xarid qiladi", "Частота покупок", "Buys often"),
    ("segments.playbook", "Nima qilish kerak", "Что делать", "What to do now"),
    ("segments.play_cant_lose", "Shaxsiy qo‘ng‘iroq va bonus: ko‘p xarid qilgan, lekin kelmay qo‘ydi", "Личный звонок и бонус: покупали много, но перестали приходить", "A personal call and a bonus: they bought a lot but stopped coming"),
    ("segments.play_at_risk", "Dori eslatmasi va kichik chegirma bilan qaytaring", "Верните напоминанием о лекарстве и небольшой скидкой", "Win them back with a refill reminder and a small discount"),
    ("segments.play_new", "Xush kelibsiz seriyasi: ikkinchi xarid uchun bonus", "Приветственная серия: бонус за вторую покупку", "A welcome series: a bonus for the second purchase"),
    ("segments.play_champions", "Rahmat ayting va tavsiya dasturiga taklif qiling", "Поблагодарите и пригласите в реферальную программу", "Say thanks and invite them to the referral programme"),
];
