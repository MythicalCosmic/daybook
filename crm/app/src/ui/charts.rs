//! Charts drawn as SVG in Rust (no JavaScript): sparkline, area/line, bars, donut, funnel.

use dioxus::prelude::*;

fn max_of(values: &[f64]) -> f64 {
    values.iter().cloned().fold(0.0_f64, f64::max).max(1e-9)
}

/// Smooth-ish path through points (monotone cubic approximation).
fn smooth_path(pts: &[(f64, f64)]) -> String {
    if pts.is_empty() {
        return String::new();
    }
    let mut d = format!("M{:.1},{:.1}", pts[0].0, pts[0].1);
    for i in 1..pts.len() {
        let (x0, y0) = pts[i - 1];
        let (x1, y1) = pts[i];
        let cx = (x0 + x1) / 2.0;
        d.push_str(&format!(" C{:.1},{:.1} {:.1},{:.1} {:.1},{:.1}", cx, y0, cx, y1, x1, y1));
    }
    d
}

static GRAD_SEQ: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);

fn grad_id() -> String {
    format!("g{}", GRAD_SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed))
}

/// Tiny trend line with a soft fill.
#[component]
pub fn Sparkline(values: Vec<f64>, #[props(default = 36)] height: u32, #[props(default = "var(--c-chart-1)")] color: &'static str) -> Element {
    let id = use_hook(grad_id);
    let w = 200.0;
    let h = height as f64;
    let m = max_of(&values);
    let n = values.len().max(2) as f64 - 1.0;
    let pts: Vec<(f64, f64)> = values.iter().enumerate().map(|(i, v)| (i as f64 / n * w, h - 3.0 - (v / m) * (h - 6.0))).collect();
    let line = smooth_path(&pts);
    let area = format!("{line} L{w:.1},{h:.1} L0,{h:.1} Z");
    let defs = format!(
        "<linearGradient id='{id}' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='{color}' stop-opacity='0.28'/><stop offset='1' stop-color='{color}' stop-opacity='0'/></linearGradient>"
    );
    rsx! {
        svg { class: "chart", view_box: "0 0 {w} {h}", preserve_aspect_ratio: "none", height: "{height}",
            defs { dangerous_inner_html: "{defs}" }
            path { d: "{area}", fill: "url(#{id})" }
            path { d: "{line}", fill: "none", stroke: "{color}", stroke_width: "2", vector_effect: "non-scaling-stroke" }
        }
    }
}

/// One series of an area chart.
#[derive(Clone, PartialEq, Debug)]
pub struct Series {
    pub name: String,
    pub values: Vec<f64>,
    pub color: &'static str,
    pub dashed: bool,
}

//// Area/line chart with gridlines and a hover tooltip. The plot is SVG; axis labels, hover dots
/// and the tooltip are HTML, so text keeps its size on every screen width.
#[component]
pub fn AreaChart(
    labels: Vec<String>,
    series: Vec<Series>,
    #[props(default = 220)] height: u32,
    #[props(default)] money: bool,
) -> Element {
    let mut hover = use_signal(|| None::<usize>);
    let id = use_hook(grad_id);
    let lang = crate::state::lang();
    let w = 1000.0;
    let h = height as f64;
    let (pt, pb) = (10.0, 2.0);
    let all: Vec<f64> = series.iter().flat_map(|s| s.values.iter().cloned()).collect();
    let raw_max = max_of(&all);
    let step = nice_step(raw_max / 4.0);
    let top = (raw_max / step).ceil() * step;
    let n = labels.len().max(2);
    let x = |i: usize| (i as f64) / ((n - 1) as f64) * w;
    let y = |v: f64| pt + (1.0 - v / top) * (h - pt - pb);
    let ticks: Vec<(f64, String)> = (0..=4)
        .map(|k| {
            let v = top / 4.0 * k as f64;
            (y(v), if money { crm::fmt::compact(v, lang) } else { format!("{:.0}", v) })
        })
        .collect();
    let every = (n / 6).max(1);
    let xlabels: Vec<(f64, String, &'static str)> = labels
        .iter()
        .enumerate()
        .filter(|(i, _)| i % every == 0 || *i == n - 1)
        .enumerate()
        .map(|(k, (i, l))| {
            let edge = if i == 0 {
                "first"
            } else if i == n - 1 {
                "last"
            } else if k % 2 == 1 {
                "alt"
            } else {
                ""
            };
            (x(i) / w * 100.0, l.clone(), edge)
        })
        .collect();
    let paths: Vec<(String, String, &'static str, bool)> = series
        .iter()
        .map(|s| {
            let pts: Vec<(f64, f64)> = s.values.iter().enumerate().map(|(i, v)| (x(i), y(*v))).collect();
            let line = smooth_path(&pts);
            let area = format!("{line} L{:.1},{:.1} L0,{:.1} Z", x(s.values.len().saturating_sub(1)), h - pb, h - pb);
            (line, area, s.color, s.dashed)
        })
        .collect();
    let first_color = series.first().map(|s| s.color).unwrap_or("var(--c-chart-1)");
    let defs = format!(
        "<linearGradient id='{id}' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='{first_color}' stop-opacity='0.22'/><stop offset='1' stop-color='{first_color}' stop-opacity='0'/></linearGradient>"
    );
    let zone_w = w / (n as f64 - 1.0).max(1.0);
    let tip = hover().map(|i| {
        let label = labels.get(i).cloned().unwrap_or_default();
        let rows: Vec<(String, String, &'static str)> = series
            .iter()
            .map(|s| {
                let v = s.values.get(i).map(|v| if money { crm::fmt::money_short(*v as i64, lang) } else { crm::fmt::num(*v as i64) }).unwrap_or_default();
                (s.name.clone(), v, s.color)
            })
            .collect();
        let dots: Vec<(f64, &'static str)> = series.iter().filter_map(|s| s.values.get(i).map(|v| (y(*v), s.color))).collect();
        let frac = x(i) / w;
        (label, rows, frac, dots)
    });
    rsx! {
        div { class: "chart-wrap",
            for (k, (ty, text)) in ticks.iter().cloned().enumerate() {
                div { key: "y{k}", class: "axis-y", style: "top: {ty - 7.0:.1}px", "{text}" }
            }
            svg { class: "chart", view_box: "0 0 {w} {h}", height: "{height}", preserve_aspect_ratio: "none",
                onmouseleave: move |_| hover.set(None),
                defs { dangerous_inner_html: "{defs}" }
                for (k, (ty, _)) in ticks.iter().cloned().enumerate() {
                    line { key: "g{k}", class: "grid-line", x1: "0", x2: "{w}", y1: "{ty:.1}", y2: "{ty:.1}", vector_effect: "non-scaling-stroke" }
                }
                for (k, (line, area, color, dashed)) in paths.iter().cloned().enumerate() {
                    g { key: "s{k}",
                        if k == 0 { path { d: "{area}", fill: "url(#{id})" } }
                        path {
                            d: "{line}",
                            fill: "none",
                            stroke: "{color}",
                            stroke_width: if dashed { "1.8" } else { "2.4" },
                            stroke_dasharray: if dashed { "5 5" } else { "none" },
                            stroke_linecap: "round",
                            vector_effect: "non-scaling-stroke",
                        }
                    }
                }
                for i in 0..n {
                    rect {
                        key: "z{i}",
                        class: "hover-zone",
                        x: "{x(i) - zone_w / 2.0:.1}",
                        y: "0",
                        width: "{zone_w:.1}",
                        height: "{h}",
                        onmouseenter: move |_| hover.set(Some(i)),
                        onclick: move |_| hover.set(Some(i)),
                    }
                }
            }
            div { class: "axis-x",
                for (k, (left, text, edge)) in xlabels.into_iter().enumerate() {
                    span { key: "x{k}", class: "{edge}", style: "left: {left:.2}%", "{text}" }
                }
            }
            if let Some((label, rows, frac, dots)) = tip {
                div { class: "chart-vline", style: "left: calc(46px + (100% - 46px) * {frac:.4}); height: {height}px" }
                for (k, (dy, color)) in dots.into_iter().enumerate() {
                    div { key: "d{k}", class: "chart-dot", style: "left: calc(46px + (100% - 46px) * {frac:.4}); top: {dy:.1}px; border-color: {color}" }
                }
                div {
                    class: "chart-tip",
                    style: "left: calc(46px + (100% - 46px) * {frac.clamp(0.12, 0.86):.4})",
                    div { class: "strong", style: "margin-bottom:4px", "{label}" }
                    for (name, val, color) in rows {
                        div { class: "row between", key: "{name}",
                            span { class: "row gap-4 muted", span { style: "width:8px;height:8px;border-radius:3px;background:{color};display:inline-block" } "{name}" }
                            span { class: "num strong", "{val}" }
                        }
                    }
                }
            }
        }
    }
}

fn nice_step(raw: f64) -> f64 {
    if raw <= 0.0 {
        return 1.0;
    }
    let mag = 10f64.powf(raw.log10().floor());
    let n = raw / mag;
    let m = if n <= 1.0 {
        1.0
    } else if n <= 2.0 {
        2.0
    } else if n <= 2.5 {
        2.5
    } else if n <= 5.0 {
        5.0
    } else {
        10.0
    };
    m * mag
}

//// Vertical bars with labels under them; the highlighted index is drawn full colour.
#[component]
pub fn BarChart(labels: Vec<String>, values: Vec<f64>, #[props(default = 180)] height: u32, #[props(default)] highlight: Option<usize>, #[props(default)] money: bool) -> Element {
    let mut hover = use_signal(|| None::<usize>);
    let lang = crate::state::lang();
    let w = 1000.0;
    let h = height as f64;
    let pt = 20.0;
    let m = max_of(&values);
    let n = values.len().max(1) as f64;
    let slot = w / n;
    let bw = (slot * 0.62).min(70.0);
    let bars: Vec<(usize, f64, f64, f64, bool, String, String)> = values
        .iter()
        .enumerate()
        .map(|(i, v)| {
            let bh = (v / m) * (h - pt);
            let xx = slot * i as f64 + (slot - bw) / 2.0;
            let on = highlight.map_or(true, |hl| hl == i) || hover() == Some(i);
            let label = labels.get(i).cloned().unwrap_or_default();
            let val = if money { crm::fmt::compact(*v, lang) } else { format!("{:.0}", v) };
            (i, xx, h - bh, bh.max(2.0), on, label, val)
        })
        .collect();
    let shown = hover().or(highlight);
    rsx! {
        div { class: "chart-wrap bars", onmouseleave: move |_| hover.set(None),
            svg { class: "chart", view_box: "0 0 {w} {h}", height: "{height}", preserve_aspect_ratio: "none",
                line { class: "grid-line", x1: "0", x2: "{w}", y1: "{h - 0.5}", y2: "{h - 0.5}", vector_effect: "non-scaling-stroke" }
                for (i, xx, yy, bh, on, _, _) in bars.iter().cloned() {
                    rect {
                        key: "{i}",
                        class: if on { "bar" } else { "bar dim" },
                        x: "{xx:.1}",
                        y: "{yy:.1}",
                        width: "{bw:.1}",
                        height: "{bh:.1}",
                        rx: "3",
                        onmouseenter: move |_| hover.set(Some(i)),
                        onclick: move |_| hover.set(Some(i)),
                    }
                }
            }
            div { class: "axis-x",
                for (i, _, _, _, _, label, _) in bars.iter().cloned() {
                    span { key: "l{i}", style: "left: {(i as f64 + 0.5) / n * 100.0:.2}%", "{label}" }
                }
            }
            for (i, _, yy, _, _, _, val) in bars.iter().cloned() {
                if shown == Some(i) {
                    div { key: "v{i}", class: "bar-value", style: "left: {(i as f64 + 0.5) / n * 100.0:.2}%; top: {(yy - 18.0).max(0.0):.1}px", "{val}" }
                }
            }
        }
    }
}

// One slice of a donut.
#[derive(Clone, PartialEq, Debug)]
pub struct Slice {
    pub label: String,
    pub value: f64,
    pub color: String,
}

/// Donut chart with a centre label and a legend.
#[component]
pub fn Donut(slices: Vec<Slice>, #[props(default = 150)] size: u32, #[props(default, into)] center: String, #[props(default, into)] caption: String, #[props(default = true)] legend: bool) -> Element {
    let total: f64 = slices.iter().map(|s| s.value).sum::<f64>().max(1e-9);
    let r = 42.0;
    let c = 2.0 * std::f64::consts::PI * r;
    let mut acc = 0.0;
    let arcs: Vec<(String, f64, f64, String)> = slices
        .iter()
        .map(|s| {
            let frac = s.value / total;
            let dash = (frac * c - 2.0).max(0.0);
            let off = -acc * c;
            acc += frac;
            (s.color.clone(), dash, off, s.label.clone())
        })
        .collect();
    rsx! {
        div { class: "row gap-16 wrap", style: "justify-content: center",
            div { class: "ring", style: "width: {size}px; height: {size}px",
                svg { width: "{size}", height: "{size}", view_box: "0 0 100 100",
                    circle { cx: "50", cy: "50", r: "{r}", fill: "none", stroke: "var(--c-surface-2)", stroke_width: "12" }
                    for (k, (color, dash, off, _)) in arcs.iter().cloned().enumerate() {
                        circle {
                            key: "{k}",
                            cx: "50", cy: "50", r: "{r}", fill: "none", stroke: "{color}", stroke_width: "12",
                            stroke_dasharray: "{dash:.2} {c:.2}", stroke_dashoffset: "{off:.2}",
                        }
                    }
                }
                div { class: "ring-label",
                    div { class: "strong num", style: "font-size: 20px", "{center}" }
                    div { class: "xs muted", "{caption}" }
                }
            }
            if legend {
                div { class: "stack gap-8", style: "min-width: 150px",
                    for s in slices.iter().cloned() {
                        div { class: "row between small", key: "{s.label}",
                            span { class: "row gap-8 muted", span { class: "sw", style: "width:10px;height:10px;border-radius:3px;background:{s.color};display:inline-block" } "{s.label}" }
                            span { class: "num strong", "{(s.value / total * 100.0):.0}%" }
                        }
                    }
                }
            }
        }
    }
}

/// Horizontal bars: label, bar, value text.
#[component]
pub fn HBars(items: Vec<(String, f64, String)>, #[props(default = "var(--c-chart-1)")] color: &'static str) -> Element {
    let m = items.iter().map(|x| x.1).fold(0.0_f64, f64::max).max(1e-9);
    rsx! {
        div { class: "bars-h",
            for (label, v, text) in items.iter().cloned() {
                div { class: "bar-h", key: "{label}",
                    span { class: "truncate muted", "{label}" }
                    div { class: "track", div { class: "fill", style: "width: {(v / m * 100.0).max(1.5):.1}%; background: {color}" } }
                    span { class: "num strong small", "{text}" }
                }
            }
        }
    }
}

/// Pipeline funnel: (stage, count, value text, hue).
#[component]
pub fn Funnel(stages: Vec<(String, u32, String, u16)>) -> Element {
    let m = stages.iter().map(|s| s.1).max().unwrap_or(1).max(1) as f64;
    rsx! {
        div { class: "funnel",
            for (name, count, value, hue) in stages.iter().cloned() {
                div { class: "funnel-row", key: "{name}",
                    span { class: "truncate small muted", "{name}" }
                    div {
                        div { class: "funnel-bar", style: "width: {(count as f64 / m * 100.0).max(6.0):.1}%; background: hsl({hue} 48% 52%)", "{count}" }
                    }
                    span { class: "num small strong right", "{value}" }
                }
            }
        }
    }
}
