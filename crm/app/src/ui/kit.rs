//! Small building blocks shared by every screen.

use crm::model::{Tier, Money};
use dioxus::prelude::*;

use super::charts::Sparkline;
use super::icons_gen::icon_svg;
use crate::state::{hue_of, t};

/// A Lucide icon (see ui/icons_gen.rs for the names).
#[component]
pub fn Icon(name: &'static str, #[props(default = 18)] size: u32, #[props(default)] class: &'static str) -> Element {
    let inner = icon_svg(name);
    rsx! {
        svg {
            class: "icon {class}",
            width: "{size}",
            height: "{size}",
            view_box: "0 0 24 24",
            fill: "none",
            stroke: "currentColor",
            stroke_width: "2",
            stroke_linecap: "round",
            stroke_linejoin: "round",
            "aria-hidden": "true",
            dangerous_inner_html: "{inner}",
        }
    }
}

/// Initials on a soft, stable colour. `size`: "xs" | "sm" | "" | "lg" | "xl".
#[component]
pub fn Avatar(
    #[props(into)] name: String,
    #[props(default)] hue: Option<u16>,
    #[props(default)] size: &'static str,
    #[props(default)] square: bool,
    #[props(default)] online: bool,
) -> Element {
    let h = hue.unwrap_or_else(|| hue_of(&name));
    let initials = crm::fmt::initials(&name);
    let sq = if square { "square" } else { "" };
    rsx! {
        span { class: "avatar {size} {sq}", style: "--h: {h}", title: "{name}",
            "{initials}"
            if online { span { class: "presence" } }
        }
    }
}

/// A soft status pill. `tone`: "" | "accent" | "success" | "warning" | "danger" | "info" | "outline".
#[component]
pub fn Badge(#[props(into)] text: String, #[props(default)] tone: &'static str, #[props(default)] dot: bool, #[props(default)] icon: Option<&'static str>) -> Element {
    rsx! {
        span { class: "badge {tone}",
            if dot { span { class: "dot" } }
            if let Some(i) = icon { Icon { name: i, size: 13 } }
            "{text}"
        }
    }
}

/// The loyalty tier chip.
#[component]
pub fn TierBadge(tier: Tier) -> Element {
    let label = t(tier.key());
    let slug = tier.slug();
    rsx! {
        span { class: "tier {slug}", Icon { name: "crown", size: 12 } "{label}" }
    }
}

/// "+12%" in green or "−4%" in red.
#[component]
pub fn Delta(value: f64, #[props(default)] invert: bool) -> Element {
    let good = if invert { value <= 0.0 } else { value >= 0.0 };
    let cls = if value.abs() < 0.5 { "flat" } else if good { "up" } else { "down" };
    let icon = if value >= 0.0 { "arrow-up-right" } else { "arrow-down-right" };
    let text = crm::fmt::delta_pct(value, crate::state::lang());
    rsx! {
        span { class: "delta {cls}", Icon { name: icon, size: 12 } "{text}" }
    }
}

/// The page title row: title, optional subtitle and actions on the right.
#[component]
pub fn PageHeader(#[props(into)] title: String, #[props(default, into)] subtitle: String, #[props(default)] children: Element) -> Element {
    rsx! {
        div { class: "page-head",
            div { class: "grow",
                h1 { class: "page-title", "{title}" }
                if !subtitle.is_empty() { p { class: "page-sub", "{subtitle}" } }
            }
            div { class: "page-actions", {children} }
        }
    }
}

/// A KPI tile with an icon, value, change and optional sparkline.
#[component]
pub fn Kpi(
    #[props(into)] label: String,
    #[props(into)] value: String,
    icon: &'static str,
    #[props(default)] delta: Option<f64>,
    #[props(default, into)] foot: String,
    #[props(default)] spark: Vec<f64>,
    #[props(default)] tone: &'static str,
    #[props(default)] onclick: Option<EventHandler<MouseEvent>>,
) -> Element {
    let clickable = if onclick.is_some() { "hover" } else { "" };
    rsx! {
        div {
            class: "card kpi {clickable}",
            onclick: move |e| {
                if let Some(h) = &onclick {
                    h.call(e)
                }
            },
            div { class: "kpi-label",
                span { class: "icon-wrap ic {tone}", Icon { name: icon, size: 15 } }
                span { class: "truncate", "{label}" }
            }
            div { class: "kpi-value", "{value}" }
            div { class: "kpi-foot",
                if let Some(d) = delta { Delta { value: d } }
                span { class: "truncate", "{foot}" }
            }
            if spark.len() > 1 {
                div { class: "spark", Sparkline { values: spark.clone(), height: 34 } }
            }
        }
    }
}

/// Friendly empty state.
#[component]
pub fn Empty(icon: &'static str, #[props(into)] title: String, #[props(default, into)] text: String, #[props(default)] children: Element) -> Element {
    rsx! {
        div { class: "empty",
            div { class: "art", Icon { name: icon, size: 28 } }
            div { class: "title", "{title}" }
            if !text.is_empty() { p { class: "small", style: "max-width: 380px", "{text}" } }
            {children}
        }
    }
}

/// A thin progress bar; `pct` 0-100.
#[component]
pub fn Progress(pct: f64, #[props(default)] tone: &'static str, #[props(default)] thin: bool) -> Element {
    let w = pct.clamp(0.0, 100.0);
    let th = if thin { "thin" } else { "" };
    rsx! {
        div { class: "progress {tone} {th}", span { style: "width: {w:.1}%" } }
    }
}

/// A circular progress ring with a label inside.
#[component]
pub fn Ring(pct: f64, #[props(default = 64)] size: u32, #[props(default = 7)] stroke: u32, #[props(default)] children: Element, #[props(default = "var(--c-primary)")] color: &'static str) -> Element {
    let r = (size as f64 - stroke as f64) / 2.0;
    let c = 2.0 * std::f64::consts::PI * r;
    let off = c * (1.0 - pct.clamp(0.0, 100.0) / 100.0);
    let half = size as f64 / 2.0;
    rsx! {
        div { class: "ring", style: "width: {size}px; height: {size}px",
            svg { width: "{size}", height: "{size}", view_box: "0 0 {size} {size}",
                circle { cx: "{half}", cy: "{half}", r: "{r}", fill: "none", stroke: "var(--c-surface-3)", stroke_width: "{stroke}" }
                circle {
                    cx: "{half}", cy: "{half}", r: "{r}", fill: "none", stroke: "{color}", stroke_width: "{stroke}",
                    stroke_linecap: "round", stroke_dasharray: "{c:.2}", stroke_dashoffset: "{off:.2}",
                    style: "transition: stroke-dashoffset .6s cubic-bezier(.2,.8,.2,1)",
                }
            }
            div { class: "ring-label", {children} }
        }
    }
}

/// On/off switch.
#[component]
pub fn Switch(on: bool, onchange: EventHandler<bool>) -> Element {
    let cls = if on { "switch on" } else { "switch" };
    rsx! {
        button { class: "{cls}", r#type: "button", role: "switch", "aria-checked": "{on}", onclick: move |_| onchange.call(!on) }
    }
}

/// Segmented control: one of several options.
#[component]
pub fn Segmented(options: Vec<(String, String)>, value: String, onchange: EventHandler<String>) -> Element {
    rsx! {
        div { class: "seg",
            for (val, label) in options.iter().cloned() {
                button {
                    key: "{val}",
                    class: if val == value { "on" } else { "" },
                    onclick: move |_| onchange.call(val.clone()),
                    "{label}"
                }
            }
        }
    }
}

/// Centered dialog (a bottom sheet on phones). Put buttons in a `div { class: "modal-foot" }` child.
#[component]
pub fn Modal(#[props(into)] title: String, onclose: EventHandler<()>, #[props(default)] wide: bool, children: Element) -> Element {
    let cls = if wide { "modal wide" } else { "modal" };
    rsx! {
        div { class: "overlay", onclick: move |_| onclose.call(()) }
        div { class: "modal-wrap",
            div { class: "{cls}", role: "dialog", onclick: move |e| e.stop_propagation(),
                div { class: "modal-head",
                    div { class: "modal-title", "{title}" }
                    button { class: "icon-btn sm", onclick: move |_| onclose.call(()), Icon { name: "x", size: 18 } }
                }
                {children}
            }
        }
    }
}

/// Side panel from the right (a tall sheet on phones). Children: drawer-body / drawer-foot divs.
#[component]
pub fn Drawer(#[props(into)] title: String, onclose: EventHandler<()>, children: Element, #[props(default)] icon: Option<&'static str>) -> Element {
    rsx! {
        div { class: "overlay", onclick: move |_| onclose.call(()) }
        div { class: "drawer", role: "dialog",
            div { class: "drawer-head",
                div { class: "grow row gap-12",
                    if let Some(i) = icon { IconTile { icon: i, size: "sm" } }
                    div { class: "modal-title truncate", "{title}" }
                }
                button { class: "icon-btn sm", onclick: move |_| onclose.call(()), Icon { name: "x", size: 18 } }
            }
            {children}
        }
    }
}

/// Coloured round icon tile. `tone`: accent | success | warning | danger | info | muted.
#[component]
pub fn IconTile(icon: &'static str, #[props(default = "accent")] tone: &'static str, #[props(default)] size: &'static str) -> Element {
    let px = match size {
        "sm" => 15,
        "lg" => 22,
        _ => 17,
    };
    rsx! {
        span { class: "ic {tone} {size}", Icon { name: icon, size: px } }
    }
}

/// Money with a muted currency, e.g. in tables.
#[component]
pub fn MoneyText(value: Money, #[props(default)] short: bool) -> Element {
    let s = if short { crate::state::money_short(value) } else { crate::state::money(value) };
    rsx! { span { class: "num nowrap", "{s}" } }
}

/// A labelled key/value list (<dl>). Pass (label, value) pairs.
#[component]
pub fn KeyValues(items: Vec<(String, String)>) -> Element {
    rsx! {
        dl { class: "kv",
            for (k, v) in items.iter().cloned() {
                dt { key: "{k}", "{k}" }
                dd { class: "truncate", "{v}" }
            }
        }
    }
}

/// Tone for a 0-100 score (health, churn risk inverted by the caller).
pub fn score_tone(score: u8) -> &'static str {
    match score {
        0..=39 => "danger",
        40..=69 => "warning",
        _ => "success",
    }
}
