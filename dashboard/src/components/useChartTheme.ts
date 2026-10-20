/**
 * Chart colors, type and axes from the CSS tokens (plan §6.3), so every chart follows the theme and
 * re-themes when it switches. Read from the chart's own element, so a nested `[data-theme]` region
 * (the component gallery) gets its own colors.
 *
 * Series order: the plan's eight series tokens are assigned 1, 3, 4, 5, 6, 2, 7, 8. Validated with
 * the dataviz palette checker, that order keeps every adjacent pair of the first four series apart
 * for colour-blind readers in both themes (terracotta next to sage, the token order, is ΔE 4.8 for
 * protanopia). Token 8 (warm gray) is kept for "Other" and comparison series.
 */
import { computed, nextTick, onMounted, ref, watch, type Ref } from "vue";

import { useUiStore } from "@/stores/ui";

export const SERIES_ORDER = [1, 3, 4, 5, 6, 2, 7, 8] as const;

export interface ChartTheme {
  text: string;
  muted: string;
  subtle: string;
  border: string;
  surface: string;
  surface2: string;
  primary: string;
  success: string;
  warning: string;
  danger: string;
  info: string;
  /** Categorical colors in assignment order. */
  series: string[];
  /** The neutral used for comparison (previous period) series. */
  compare: string;
  fontFamily: string;
  dark: boolean;
}

const FALLBACK: ChartTheme = {
  text: "#201e1d",
  muted: "#6b6359",
  subtle: "#8e8579",
  border: "rgba(32,30,29,0.1)",
  surface: "#ffffff",
  surface2: "#f1ebe1",
  primary: "#a85a27",
  success: "#5f7a45",
  warning: "#a8701c",
  danger: "#b3412e",
  info: "#4a6a8a",
  series: ["#c67139", "#4a6a8a", "#d1a040", "#8a5a7a", "#3f8a83", "#7a8a5e", "#a66a4f", "#8c857a"],
  compare: "#8c857a",
  fontFamily: '"Figtree Variable", system-ui, sans-serif',
  dark: false,
};

export function readChartTheme(el: Element | null | undefined): ChartTheme {
  if (typeof window === "undefined") return FALLBACK;
  const target = el ?? document.documentElement;
  const style = getComputedStyle(target);
  // Tokens are written in modern syntax ("rgb(32 30 29 / 0.1)"); the canvas renderer wants the
  // browser's normalized form, so each color goes through a probe element once.
  const probe = document.createElement("span");
  probe.style.display = "none";
  (target === document.documentElement ? document.body : target).appendChild(probe);
  const get = (name: string, fallback: string) => {
    const raw = style.getPropertyValue(name).trim();
    if (!raw) return fallback;
    if (!name.startsWith("--c-")) return raw;
    probe.style.color = "";
    probe.style.color = raw;
    return getComputedStyle(probe).color || raw;
  };
  try {
    return themeFrom(get, target);
  } finally {
    probe.remove();
  }
}

function themeFrom(get: (name: string, fallback: string) => string, target: Element): ChartTheme {
  const series = SERIES_ORDER.map((n, i) => get(`--c-chart-${n}`, FALLBACK.series[i]!));
  const themed = target.closest("[data-theme]")?.getAttribute("data-theme");
  return {
    text: get("--c-text", FALLBACK.text),
    muted: get("--c-muted", FALLBACK.muted),
    subtle: get("--c-subtle", FALLBACK.subtle),
    border: get("--c-border", FALLBACK.border),
    surface: get("--c-surface", FALLBACK.surface),
    surface2: get("--c-surface-2", FALLBACK.surface2),
    primary: get("--c-primary", FALLBACK.primary),
    success: get("--c-success", FALLBACK.success),
    warning: get("--c-warning", FALLBACK.warning),
    danger: get("--c-danger", FALLBACK.danger),
    info: get("--c-info", FALLBACK.info),
    series,
    compare: get("--c-chart-8", FALLBACK.compare),
    fontFamily: get("--font-sans", FALLBACK.fontFamily),
    dark: themed === "dark",
  };
}

/** A theme that follows the person's light/dark choice, read from `el` once it is mounted. */
export function useChartTheme(el?: Ref<HTMLElement | null | undefined>) {
  const ui = useUiStore();
  const theme = ref<ChartTheme>(FALLBACK);
  const refresh = () => (theme.value = readChartTheme(el?.value));
  onMounted(refresh);
  watch(
    () => ui.theme,
    () => void nextTick(refresh),
  );
  return computed(() => theme.value);
}

/** Pixel font sizes the charts use (12 axis, 13 tooltip). */
export const CHART_TYPE = { axis: 11, label: 12, tooltip: 13 } as const;

/** Escapes text placed in tooltip HTML (series and category names can come from the API). */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!);
}

/** Tooltip box style shared by every chart. */
export function tooltipStyle(theme: ChartTheme) {
  return {
    backgroundColor: theme.dark ? "#2d2822" : "#201e1d",
    borderWidth: 0,
    padding: [8, 10],
    textStyle: { color: "#f7f3ec", fontFamily: theme.fontFamily, fontSize: CHART_TYPE.tooltip },
    extraCssText: "border-radius: 8px; box-shadow: 0 8px 24px -8px rgba(0,0,0,.35);",
  };
}

export function axisStyle(theme: ChartTheme) {
  return {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: theme.subtle, fontFamily: theme.fontFamily, fontSize: CHART_TYPE.axis, hideOverlap: true },
    splitLine: { lineStyle: { color: theme.border, width: 1, type: "solid" as const } },
  };
}
