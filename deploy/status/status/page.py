"""Server-rendered status page. One HTML response, inline CSS, no JavaScript, no external requests."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from .core import duration_text

T = {
    "uz": {
        "title": "Holat",
        "sub": "Daybook xizmatlarining holati",
        "operational": "Barcha tizimlar ishlayapti",
        "degraded": "Ayrim xizmatlar sekin ishlayapti",
        "partial": "Ayrim xizmatlar ishlamayapti",
        "major": "Xizmatlar ishlamayapti",
        "up": "Ishlayapti",
        "warn": "Ogohlantirish",
        "down": "Ishlamayapti",
        "unknown": "Tekshirilmoqda",
        "days90": "90 kun oldin",
        "today": "Bugun",
        "uptime": "Ishlash vaqti",
        "resp": "Javob vaqti",
        "incidents": "So'nggi nosozliklar",
        "none": "So'nggi 90 kunda nosozlik bo'lmadi.",
        "ongoing": "davom etmoqda",
        "lasted": "davomiyligi",
        "updated": "Yangilandi",
        "every": "har {n} soniyada tekshiriladi",
        "version": "versiya",
        "nodata": "ma'lumot yo'q",
        "certdays": "sertifikat: {n} kun qoldi",
        "lang": "English",
        "checks": "Tekshiruvlar",
    },
    "en": {
        "title": "Status",
        "sub": "Daybook service status",
        "operational": "All systems operational",
        "degraded": "Some services are degraded",
        "partial": "Partial outage",
        "major": "Major outage",
        "up": "Operational",
        "warn": "Degraded",
        "down": "Down",
        "unknown": "Checking",
        "days90": "90 days ago",
        "today": "Today",
        "uptime": "Uptime",
        "resp": "Response time",
        "incidents": "Recent incidents",
        "none": "No incidents in the last 90 days.",
        "ongoing": "ongoing",
        "lasted": "lasted",
        "updated": "Updated",
        "every": "checked every {n} s",
        "version": "version",
        "nodata": "no data",
        "certdays": "certificate: {n} days left",
        "lang": "O'zbekcha",
        "checks": "Checks",
    },
}

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#14171c;--mute:#667085;--line:#e6e8ec;--ok:#12a150;--warn:#e5a000;
--bad:#e5484d;--none:#dfe2e7;--okbg:#e9f8ef;--warnbg:#fff6e0;--badbg:#fdecec;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0d1014;--card:#151a20;--fg:#e8ebef;--mute:#8b95a3;--line:#242b33;
--ok:#2fc26b;--warn:#f0b429;--bad:#f2555a;--none:#2a313a;--okbg:#10291b;--warnbg:#2e2510;--badbg:#321617}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,
"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:32px 16px 48px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:24px}
.brand{display:flex;align-items:center;gap:10px;font-weight:650;font-size:20px;letter-spacing:-.01em}
.brand small{display:block;font-weight:400;font-size:13px;color:var(--mute)}
.logo{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,#2563eb,#0ea5e9);display:grid;
place-items:center;color:#fff;font-size:17px;font-weight:700}
a{color:inherit}.lang{font-size:13px;color:var(--mute);text-decoration:none;border:1px solid var(--line);
padding:5px 11px;border-radius:999px;background:var(--card)}.lang:hover{color:var(--fg)}
.banner{display:flex;align-items:center;gap:14px;padding:18px 20px;border-radius:14px;margin-bottom:28px;
font-weight:600;font-size:17px;border:1px solid transparent}
.banner.operational{background:var(--okbg);border-color:color-mix(in srgb,var(--ok) 30%,transparent)}
.banner.degraded{background:var(--warnbg);border-color:color-mix(in srgb,var(--warn) 35%,transparent)}
.banner.partial,.banner.major{background:var(--badbg);border-color:color-mix(in srgb,var(--bad) 35%,transparent)}
.banner .meta{margin-left:auto;font-weight:400;font-size:13px;color:var(--mute);text-align:right}
.big{width:28px;height:28px;border-radius:50%;flex:none;display:grid;place-items:center;color:#fff}
.operational .big{background:var(--ok)}.degraded .big{background:var(--warn)}.partial .big,.major .big{background:var(--bad)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:16px}
.row{display:flex;align-items:center;gap:10px}.row h2{margin:0;font-size:16px;font-weight:620}
.ver{font-size:12px;color:var(--mute);border:1px solid var(--line);border-radius:6px;padding:1px 7px}
.state{margin-left:auto;font-size:14px;font-weight:550;display:flex;align-items:center;gap:7px}
.dot{width:9px;height:9px;border-radius:50%;flex:none;background:var(--none)}
.up .dot,.dot.up{background:var(--ok)}.warn .dot,.dot.warn{background:var(--warn)}.down .dot,.dot.down{background:var(--bad)}
.state.up{color:var(--ok)}.state.warn{color:var(--warn)}.state.down{color:var(--bad)}.state.unknown{color:var(--mute)}
.bars{display:flex;gap:2px;height:34px;margin:16px 0 6px}
.bars i{flex:1;border-radius:2px;background:var(--none);min-width:2px}
.bars i.g{background:var(--ok)}.bars i.a{background:var(--warn)}.bars i.r{background:var(--bad)}
.bars i:hover{opacity:.7}
.axis{display:flex;justify-content:space-between;font-size:12px;color:var(--mute)}
.axis b{font-weight:500;color:var(--fg)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:16px}
.stat{background:var(--bg);border-radius:10px;padding:9px 12px}.stat span{display:block;font-size:12px;color:var(--mute)}
.stat b{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums}
details{margin-top:14px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-size:13px;color:var(--mute);list-style:none}summary::-webkit-details-marker{display:none}
summary:before{content:"+ "}details[open] summary:before{content:"- "}
.checks{margin:8px 0 0;padding:0;list-style:none}
.checks li{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;padding:7px 0;font-size:14px}
.checks li+li{border-top:1px dashed var(--line)}
.checks .t{font-size:12px;color:var(--mute);word-break:break-all}
.checks .r{font-size:13px;color:var(--mute);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
h3{font-size:15px;margin:32px 0 12px;font-weight:620}
.inc{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;padding:14px 0;border-top:1px solid var(--line)}
.inc:first-of-type{border-top:0}.inc .dot{margin-top:7px}.inc b{font-weight:600}
.inc p{margin:0;font-size:13px;color:var(--mute);grid-column:2}
.empty{color:var(--mute);font-size:14px}
footer{margin-top:36px;font-size:12px;color:var(--mute);text-align:center}
@media (max-width:560px){.wrap{padding:20px 16px 36px}.stats{grid-template-columns:repeat(2,1fr)}
.banner{flex-wrap:wrap;font-size:16px}.banner .meta{margin-left:42px;text-align:left;width:100%}
.bars{gap:1px;height:30px}.checks li{grid-template-columns:auto 1fr}.checks .r{grid-column:2;text-align:left}}
"""

ICON = {"operational": "&#10003;", "degraded": "!", "partial": "!", "major": "&#10005;"}


def _pct(v):
    if v is None:
        return "&mdash;"
    if v >= 99.995:
        return "100%"
    return f"{v:.2f}%"


def _fmt_time(ts, tz, with_date=True):
    d = datetime.fromtimestamp(ts, timezone(timedelta(seconds=tz)))
    return d.strftime("%d.%m.%Y %H:%M" if with_date else "%H:%M")


def _bar_class(day):
    u = day["uptime"]
    if u is None:
        return ""
    if u >= 99.9:
        return "g"
    if u >= 98:
        return "a"
    return "r"


def render(snap: dict, lang: str = "uz") -> str:
    t = T[lang]
    e = html.escape
    tz = snap["tz_offset_s"]
    other = "?lang=en" if lang == "uz" else "?"
    out = [
        f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60">
<title>Holat · Status</title><meta name="description" content="{e(t["sub"])}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%2312a150'/%3E%3C/svg%3E">
<style>{CSS}</style></head><body><div class="wrap">
<header><div class="brand"><div class="logo">D</div><div>Holat · Status<small>{e(t["sub"])}</small></div></div>
<a class="lang" href="{other}">{t["lang"]}</a></header>"""
    ]
    ov = snap["overall"]
    out.append(f"""<div class="banner {ov}"><div class="big">{ICON[ov]}</div><div>{e(t[ov])}</div>
<div class="meta">{t["updated"]} {_fmt_time(snap["generated_at"], tz, False)}<br>{t["every"].format(n=snap["interval_s"])}</div></div>""")

    for s in snap["services"]:
        lv = s["level"]
        ver = (
            f'<span class="ver">{t["version"]} {e(s["version"])}</span>' if s.get("version") else ""
        )
        bars = []
        for d in s["days"]:
            day = _fmt_time(d["day"] + 43200, tz).split()[0]
            tip = f"{day}: {_pct(d['uptime']) if d['uptime'] is not None else t['nodata']}"
            if d["down_s"]:
                tip += f" ({duration_text(d['down_s'])})"
            bars.append(f'<i class="{_bar_class(d)}" title="{e(tip)}"></i>')
        ms = [c["avg_ms_24h"] for c in s["checks"] if c["type"] == "http" and c["avg_ms_24h"]]
        resp = f"{round(sum(ms) / len(ms))} ms" if ms else "&mdash;"
        u = s["uptime"]
        out.append(f"""<section class="card"><div class="row"><h2>{e(s["name"])}</h2>{ver}
<div class="state {lv}"><span class="dot"></span>{t[lv]}</div></div>
<div class="bars" role="img" aria-label="{e(t["uptime"])} 90">{"".join(bars)}</div>
<div class="axis"><span>{t["days90"]}</span><b>{_pct(u["90d"])}</b><span>{t["today"]}</span></div>
<div class="stats"><div class="stat"><span>24h</span><b>{_pct(u["24h"])}</b></div>
<div class="stat"><span>7d / 30d</span><b>{_pct(u["7d"])} · {_pct(u["30d"])}</b></div>
<div class="stat"><span>90d</span><b>{_pct(u["90d"])}</b></div>
<div class="stat"><span>{t["resp"]}</span><b>{resp}</b></div></div>
<details><summary>{t["checks"]} ({len(s["checks"])})</summary><ul class="checks">""")
        for c in s["checks"]:
            last = c.get("last") or {}
            if c["type"] == "tls" and last.get("days_left") is not None:
                right = t["certdays"].format(n=int(last["days_left"]))
            elif last.get("ms") is not None:
                right = f"{last['ms']} ms" + (f" · HTTP {last['code']}" if last.get("code") else "")
            else:
                right = e(last.get("detail") or t["nodata"])
            out.append(f"""<li><span class="dot {c["level"]}" title="{t[c["level"]]}"></span>
<div>{e(c["name"])}<div class="t">{e(c["target"] or "")}</div></div><div class="r">{right} · {_pct(c["uptime"]["24h"])}</div></li>""")
        out.append("</ul></details></section>")

    out.append(f'<h3>{t["incidents"]}</h3><section class="card">')
    if not snap["incidents"]:
        out.append(f'<div class="empty">{t["none"]}</div>')
    for i in snap["incidents"][:15]:
        ongoing = i["end"] is None
        when = _fmt_time(i["start"], tz)
        if ongoing:
            tail = f"{t['ongoing']} · {duration_text(i['duration_s'])}"
        else:
            tail = f"{when} &ndash; {_fmt_time(i['end'], tz, False)} · {t['lasted']} {duration_text(i['duration_s'])}"
            when = ""
        out.append(f"""<div class="inc"><span class="dot {"down" if ongoing else "up"}"></span>
<b>{e(i["service"])} &mdash; {e(i["check"])}</b><p>{when + " · " if when else ""}{tail}</p>
<p>{e(i["detail"] or "")}</p></div>""")
    out.append(f"""</section><footer>Holat · Status &middot; <a href="/api/status.json">status.json</a> &middot;
UTC{"+" if tz >= 0 else "-"}{abs(tz) // 3600}</footer></div></body></html>""")
    return "".join(out)
