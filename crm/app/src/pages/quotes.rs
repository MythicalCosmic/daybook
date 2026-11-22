//! Quotes and invoices for organisations: a list with status chips and the money waiting,
//! and a printable document (seller, buyer, lines, VAT 12%) that moves from draft to paid.

use chrono::{Datelike, Duration};
use crm::analytics;
use crm::fmt;
use crm::i18n::Entry;
use crm::model::*;
use dioxus::prelude::*;

use crate::routes::Route;
use crate::state::*;
use crate::ui::*;

/// The seller's tax id on documents (the demo company's).
const SELLER_TIN: &str = "307 845 219";

fn tone(s: QuoteStatus) -> &'static str {
    match s {
        QuoteStatus::Draft => "",
        QuoteStatus::Sent => "info",
        QuoteStatus::Accepted => "accent",
        QuoteStatus::Invoiced => "warning",
        QuoteStatus::Paid => "success",
        QuoteStatus::Overdue | QuoteStatus::Rejected => "danger",
    }
}

fn is_invoice(s: QuoteStatus) -> bool {
    matches!(s, QuoteStatus::Invoiced | QuoteStatus::Paid | QuoteStatus::Overdue)
}

/// The buyer's name: the organisation, or the deal's customer for a personal order.
fn buyer_name(db: &crm::Db, q: &Quote) -> String {
    match db.company(q.company_id) {
        Some(c) => c.name.clone(),
        None => db.customer_name(q.deal_id.and_then(|d| db.deal(d)).and_then(|d| d.customer_id)),
    }
}

#[derive(Clone, PartialEq)]
struct Row {
    q: Quote,
    buyer: String,
    total: Money,
    owner: String,
    owner_hue: u16,
}

#[component]
pub fn Quotes() -> Element {
    let l = lang();
    let today = today();
    let rows = use_memo(move || {
        let db = DB.read();
        let mut v: Vec<Row> = db
            .quotes
            .iter()
            .map(|q| {
                let s = db.staff_member(q.owner_id);
                Row {
                    q: q.clone(),
                    buyer: buyer_name(&db, q),
                    total: q.total(),
                    owner: s.map(|s| s.name.clone()).unwrap_or_default(),
                    owner_hue: s.map(|s| s.hue).unwrap_or(24),
                }
            })
            .collect();
        v.sort_by(|a, b| b.q.issued.cmp(&a.q.issued).then(b.q.id.cmp(&a.q.id)));
        v
    });
    let mut status = use_signal(|| None::<QuoteStatus>);
    let mut q = use_signal(String::new);

    let all = rows();
    let m0 = analytics::month_start(today);
    let outstanding: Vec<&Row> = all.iter().filter(|r| matches!(r.q.status, QuoteStatus::Sent | QuoteStatus::Invoiced | QuoteStatus::Overdue)).collect();
    let outstanding_sum: Money = outstanding.iter().map(|r| r.total).sum();
    let overdue: Vec<&Row> = all.iter().filter(|r| r.q.status == QuoteStatus::Overdue).collect();
    let overdue_sum: Money = overdue.iter().map(|r| r.total).sum();
    let paid: Vec<&Row> = all.iter().filter(|r| r.q.status == QuoteStatus::Paid && r.q.paid_on.map(|d| d >= m0).unwrap_or(false)).collect();
    let paid_sum: Money = paid.iter().map(|r| r.total).sum();
    let decided = all.iter().filter(|r| r.q.status != QuoteStatus::Draft).count();
    let won = all.iter().filter(|r| matches!(r.q.status, QuoteStatus::Accepted | QuoteStatus::Invoiced | QuoteStatus::Paid | QuoteStatus::Overdue)).count();
    let accept = if decided == 0 { 0.0 } else { won as f64 / decided as f64 * 100.0 };
    let overdue_orgs = overdue.iter().map(|r| r.q.company_id).collect::<std::collections::HashSet<_>>().len();

    let ql = q().trim().to_lowercase();
    let base: Vec<&Row> = all.iter().filter(|r| ql.is_empty() || r.q.number.to_lowercase().contains(&ql) || r.buyer.to_lowercase().contains(&ql)).collect();
    let counts: Vec<(QuoteStatus, usize)> = [
        QuoteStatus::Draft,
        QuoteStatus::Sent,
        QuoteStatus::Accepted,
        QuoteStatus::Invoiced,
        QuoteStatus::Paid,
        QuoteStatus::Overdue,
        QuoteStatus::Rejected,
    ]
    .iter()
    .map(|s| (*s, base.iter().filter(|r| r.q.status == *s).count()))
    .collect();
    let shown: Vec<Row> = base.iter().filter(|r| status().map_or(true, |s| r.q.status == s)).map(|r| (*r).clone()).collect();
    let shown_sum: Money = shown.iter().map(|r| r.total).sum();
    let shown_n = shown.len();

    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.quotes"), subtitle: t("quotes.sub"),
                button { class: "btn primary", onclick: move |_| go("/deals"),
                    Icon { name: "file-plus", size: 16 }
                    span { class: "label-text", {t("quotes.from_deal")} }
                }
            }

            div { class: "grid-4",
                Kpi { label: t("quotes.kpi_outstanding"), value: money_short(outstanding_sum), icon: "hourglass", tone: "info",
                    foot: t("quotes.kpi_docs").replace("{n}", &outstanding.len().to_string()),
                }
                Kpi { label: t("quotes.kpi_overdue"), value: money_short(overdue_sum), icon: "triangle-alert", tone: "danger",
                    foot: t("quotes.kpi_orgs").replace("{n}", &overdue_orgs.to_string()),
                    onclick: move |_| status.set(Some(QuoteStatus::Overdue)),
                }
                Kpi { label: t("quotes.kpi_paid"), value: money_short(paid_sum), icon: "banknote", tone: "success",
                    foot: t("quotes.kpi_payments").replace("{n}", &paid.len().to_string()),
                }
                Kpi { label: t("quotes.kpi_accept"), value: fmt::pct(accept, l), icon: "handshake", foot: t("quotes.kpi_accept_foot") }
            }

            div { class: "toolbar",
                div { class: "search",
                    Icon { name: "search", size: 16 }
                    input { class: "input", value: "{q}", placeholder: t("quotes.search"), oninput: move |e| q.set(e.value()) }
                }
            }
            div { class: "chips",
                button { class: if status().is_none() { "chip on" } else { "chip" }, onclick: move |_| status.set(None),
                    {t("common.all")}
                    span { class: "count", "{base.len()}" }
                }
                for (s, n) in counts {
                    button {
                        key: "{s.slug()}",
                        class: if status() == Some(s) { "chip on" } else { "chip" },
                        onclick: move |_| status.set(if status() == Some(s) { None } else { Some(s) }),
                        {t(s.key())}
                        span { class: "count", "{n}" }
                    }
                }
            }

            div { class: "card",
                if shown.is_empty() {
                    Empty { icon: "file-text", title: t("quotes.empty"), text: t("quotes.empty_text") }
                } else {
                    div { class: "table-wrap",
                        table { class: "table responsive",
                            thead {
                                tr {
                                    th { {t("quotes.number")} }
                                    th { class: "m-hide", {t("common.company")} }
                                    th { class: "m-hide", {t("quotes.issued")} }
                                    th { class: "m-hide", {t("quotes.valid")} }
                                    th { class: "num", {t("common.total")} }
                                    th { class: "m-hide", {t("common.status")} }
                                    th { class: "m-hide", {t("common.owner")} }
                                }
                            }
                            tbody {
                                for r in shown {
                                    {
                                        let id = r.q.id;
                                        let issued = fmt::date(r.q.issued, today, l);
                                        let until = fmt::date(r.q.valid_until, today, l);
                                        let late = matches!(r.q.status, QuoteStatus::Sent | QuoteStatus::Invoiced | QuoteStatus::Overdue) && r.q.valid_until < today;
                                        let until_cls = if late { "small tone-danger strong nowrap" } else { "small muted nowrap" };
                                        let st = t(r.q.status.key());
                                        let stone = tone(r.q.status);
                                        let doc_icon: &'static str = if is_invoice(r.q.status) { "receipt" } else { "file-text" };
                                        rsx! {
                                            tr { key: "{id}", class: "click", onclick: move |_| go(&format!("/quotes/{id}")),
                                                td {
                                                    div { class: "row gap-12",
                                                        span { class: "ic muted sm hide-mobile", Icon { name: doc_icon, size: 15 } }
                                                        div { style: "min-width: 0",
                                                            div { class: "strong small num", "{r.q.number}" }
                                                            div { class: "xs muted only-mobile truncate", "{r.buyer}" }
                                                            div { class: "only-mobile", style: "margin-top: 4px", Badge { text: st.clone(), tone: stone, dot: true } }
                                                        }
                                                    }
                                                }
                                                td { class: "m-hide",
                                                    div { class: "row gap-8",
                                                        Avatar { name: r.buyer.clone(), size: "xs", square: true }
                                                        span { class: "small truncate", "{r.buyer}" }
                                                    }
                                                }
                                                td { class: "m-hide small muted nowrap", "{issued}" }
                                                td { class: "m-hide", span { class: until_cls, "{until}" } }
                                                td { class: "num", span { class: "strong nowrap", "{money(r.total)}" } }
                                                td { class: "m-hide", Badge { text: st, tone: stone, dot: true } }
                                                td { class: "m-hide", Avatar { name: r.owner.clone(), hue: r.owner_hue, size: "xs" } }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    div { class: "card-foot",
                        span { class: "small muted", {t("quotes.count").replace("{n}", &shown_n.to_string())} }
                        span { class: "strong num", "{money(shown_sum)}" }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- document

fn set_status(id: Id, st: QuoteStatus) -> bool {
    let mut deal_won = false;
    mutate(|db| {
        let now = now();
        let mut deal = None;
        let mut number = String::new();
        let terms = db.quote(id).and_then(|q| db.company(q.company_id)).map(|c| c.terms_days).unwrap_or(30).max(1);
        if let Some(q) = db.quote_mut(id) {
            q.status = st;
            number = q.number.clone();
            match st {
                QuoteStatus::Paid => q.paid_on = Some(now.date()),
                QuoteStatus::Invoiced => q.valid_until = now.date() + Duration::days(terms as i64),
                _ => {}
            }
            deal = q.deal_id;
        }
        if st == QuoteStatus::Accepted {
            if let Some(d) = deal {
                if db.deal(d).map(|x| x.status == DealStatus::Open).unwrap_or(false) {
                    db.win_deal(d, now);
                    deal_won = true;
                }
            }
        }
        db.log(now, format!("{number}: {}", st.slug()), false);
    });
    deal_won
}

#[component]
pub fn QuoteDetail(id: u32) -> Element {
    let Some(qt) = DB.read().quote(id).cloned() else {
        return rsx! {
            div { class: "page",
                div { class: "card",
                    Empty { icon: "file-text", title: t("quotes.not_found"),
                        Link { to: Route::Quotes {}, class: "btn primary", Icon { name: "arrow-left", size: 16 } {t("quotes.back")} }
                    }
                }
            }
        };
    };
    let l = lang();
    let now = now();
    let today = now.date();
    let (seller, seller_addr, seller_phone, company, buyer, lines, owner, deal, history) = {
        let db = DB.read();
        let b0 = db.branches.first();
        let lines: Vec<(LineItem, String)> = qt.lines.iter().map(|li| (li.clone(), db.product_name(Some(li.product_id)))).collect();
        let deal = qt.deal_id.and_then(|d| db.deal(d)).map(|d| (d.id, d.title.clone(), d.status));
        let history: Vec<(chrono::NaiveDateTime, String)> =
            db.audit.iter().filter(|a| a.text.starts_with(&qt.number)).map(|a| (a.at, a.text.clone())).take(8).collect();
        (
            db.settings.company_name.clone(),
            b0.map(|b| format!("{}, {}", b.address, b.district)).unwrap_or_default(),
            b0.map(|b| b.phone.clone()).unwrap_or_default(),
            db.company(qt.company_id).cloned(),
            buyer_name(&db, &qt),
            lines,
            db.staff_name(Some(qt.owner_id)),
            deal,
            history,
        )
    };
    let invoice = is_invoice(qt.status);
    let doc_title = if invoice { t("quotes.doc_invoice") } else { t("quotes.doc_quote") };
    let doc_icon: &'static str = if invoice { "receipt" } else { "file-text" };
    let st_text = t(qt.status.key());
    let st_tone = tone(qt.status);
    let issued = fmt::date_numeric(qt.issued);
    let until = fmt::date_numeric(qt.valid_until);
    let until_label = if invoice { t("quotes.due_date") } else { t("quotes.valid_until") };
    let subtotal = qt.subtotal();
    let vat = qt.vat();
    let total = qt.total();
    let vat_label = t("quotes.vat").replace("{n}", &qt.vat_pct.to_string());
    let terms_days = company.as_ref().map(|c| c.terms_days).unwrap_or(30);
    let terms = t("quotes.terms_text").replace("{n}", &terms_days.to_string());
    let contact = company.as_ref().and_then(|c| c.contacts.iter().find(|p| p.primary).or(c.contacts.first()).cloned());
    let contact_name = contact.as_ref().map(|c| c.name.clone()).unwrap_or_else(|| buyer.clone());
    let late_days = (today - qt.valid_until).num_days();
    let overdue_note = if qt.status == QuoteStatus::Overdue || (qt.status == QuoteStatus::Invoiced && late_days > 0) {
        Some(t("quotes.days_overdue").replace("{n}", &late_days.max(1).to_string()))
    } else {
        None
    };
    let subtitle = format!("{buyer} · {}", fmt::date(qt.issued, today, l));
    let number = qt.number.clone();
    let st = qt.status;
    let deal_tone: &'static str = match deal.as_ref().map(|d| d.2) {
        Some(DealStatus::Won) => "success",
        Some(DealStatus::Lost) => "danger",
        _ => "info",
    };

    // the steps a document goes through, with where this one is
    let order = [QuoteStatus::Draft, QuoteStatus::Sent, QuoteStatus::Accepted, QuoteStatus::Invoiced, QuoteStatus::Paid];
    let reached = match st {
        QuoteStatus::Draft => 0,
        QuoteStatus::Sent | QuoteStatus::Rejected => 1,
        QuoteStatus::Accepted => 2,
        QuoteStatus::Invoiced | QuoteStatus::Overdue => 3,
        QuoteStatus::Paid => 4,
    };
    let mut steps: Vec<(String, String, &'static str, &'static str)> = Vec::new();
    for (i, s) in order.iter().enumerate() {
        if i > reached {
            break;
        }
        let when = match s {
            QuoteStatus::Draft => fmt::date(qt.issued, today, l),
            QuoteStatus::Paid => qt.paid_on.map(|d| fmt::date(d, today, l)).unwrap_or_default(),
            _ => String::new(),
        };
        let icon: &'static str = match s {
            QuoteStatus::Draft => "file-plus",
            QuoteStatus::Sent => "send",
            QuoteStatus::Accepted => "handshake",
            QuoteStatus::Invoiced => "receipt",
            _ => "banknote",
        };
        steps.push((t(s.key()), when, icon, if *s == QuoteStatus::Paid { "success" } else { "accent" }));
    }
    if st == QuoteStatus::Rejected {
        steps.push((t("quote_status.rejected"), String::new(), "circle-x", "danger"));
    }
    if st == QuoteStatus::Overdue {
        steps.push((t("quote_status.overdue"), overdue_note.clone().unwrap_or_default(), "triangle-alert", "danger"));
    }

    let send = move |_| {
        set_status(id, QuoteStatus::Sent);
        toast(t("quotes.sent_toast").replace("{c}", &contact_name), "send", "success");
    };
    let accept = move |_| {
        let won = set_status(id, QuoteStatus::Accepted);
        toast(if won { t("quotes.accepted_deal") } else { t("quotes.accepted_toast") }, "handshake", "success");
    };
    let to_invoice = move |_| {
        set_status(id, QuoteStatus::Invoiced);
        toast(t("quotes.invoiced_toast"), "receipt", "success");
    };
    let mark_paid = move |_| {
        set_status(id, QuoteStatus::Paid);
        toast(t("quotes.paid_toast"), "banknote", "success");
    };
    let reject = move |_| {
        set_status(id, QuoteStatus::Rejected);
        toast(t("quotes.rejected_toast"), "circle-x", "");
    };
    let duplicate = move |_| {
        let mut new_id = 0;
        mutate(|db| {
            let Some(src) = db.quote(id).cloned() else { return };
            let now = crate::state::now();
            let n = db.quotes.iter().filter_map(|q| q.number.rsplit('-').next().and_then(|x| x.parse::<u32>().ok())).max().unwrap_or(130) + 1;
            let qid = db.new_id();
            new_id = qid;
            let me = db.settings.me;
            let number = format!("TK-{}-{:04}", now.date().year(), n);
            db.quotes.insert(
                0,
                Quote {
                    id: qid,
                    number: number.clone(),
                    status: QuoteStatus::Draft,
                    issued: now.date(),
                    valid_until: now.date() + Duration::days(30),
                    owner_id: me,
                    paid_on: None,
                    ..src
                },
            );
            db.log(now, format!("{number}: draft"), false);
        });
        if new_id != 0 {
            toast(t("quotes.duplicated_toast"), "copy", "success");
            go(&format!("/quotes/{new_id}"));
        }
    };
    let print = move |_| {
        mutate(|db| db.log(crate::state::now(), format!("{number}: PDF"), false));
        toast(t("quotes.print_toast"), "printer", "success");
    };

    rsx! {
        div { class: "page",
            div { class: "row between wrap gap-8",
                Link { to: Route::Quotes {}, class: "btn ghost sm", Icon { name: "arrow-left", size: 15 } {t("quotes.back")} }
                Badge { text: st_text.clone(), tone: st_tone, dot: true }
            }
            PageHeader { title: qt.number.clone(), subtitle,
                button { class: "btn", onclick: print, Icon { name: "printer", size: 16 } span { class: "label-text", {t("quotes.print")} } }
                button { class: "btn", onclick: duplicate, Icon { name: "copy", size: 16 } span { class: "label-text", {t("quotes.duplicate")} } }
            }

            div { class: "grid-main",
                div { class: "card", style: "padding: clamp(18px, 4vw, 44px); display: flex; flex-direction: column; gap: 26px",
                    div { class: "row between top wrap gap-16",
                        div { class: "stack gap-4",
                            div { class: "row gap-12",
                                div { class: "brand-mark", style: "width: 38px; height: 38px; border-radius: 12px", Icon { name: "heart-pulse", size: 20 } }
                                div {
                                    div { class: "display", style: "font-size: 22px; line-height: 1.1", "{seller}" }
                                    div { class: "xs muted upper", {t("quotes.pharmacy_chain")} }
                                }
                            }
                            div { class: "small muted", style: "margin-top: 8px", "{seller_addr}" }
                            div { class: "small muted num", "STIR {SELLER_TIN} · {seller_phone}" }
                        }
                        div { class: "stack gap-4", style: "text-align: right; align-items: flex-end",
                            span { class: "upper tone-accent", "{doc_title}" }
                            span { class: "num", style: "font-size: 24px; font-weight: 750; letter-spacing: -0.01em", "№ {qt.number}" }
                            span { class: "small muted num", {t("common.date")} ": {issued}" }
                            span { class: "small muted num", "{until_label}: {until}" }
                        }
                    }

                    div { class: "grid-2", style: "gap: 12px",
                        div { style: "padding: 14px 16px; border-radius: 12px; background: var(--c-surface-2)",
                            div { class: "xs muted upper", style: "margin-bottom: 6px", {t("quotes.seller")} }
                            div { class: "strong", "{seller}" }
                            div { class: "small muted num", "STIR {SELLER_TIN}" }
                            div { class: "small muted", "{seller_addr}" }
                        }
                        div { style: "padding: 14px 16px; border-radius: 12px; background: var(--c-surface-2)",
                            div { class: "xs muted upper", style: "margin-bottom: 6px", {t("quotes.buyer")} }
                            div { class: "strong", "{buyer}" }
                            if let Some(c) = company.clone() {
                                div { class: "small muted num", "STIR {c.tin}" }
                                div { class: "small muted", "{c.address}" }
                            }
                            if let Some(p) = contact.clone() {
                                div { class: "small muted", "{p.name}, {p.position}" }
                            }
                        }
                    }

                    div { class: "table-wrap", style: "margin: 0 -6px",
                        table { class: "table", style: "font-size: 13px",
                            thead {
                                tr {
                                    th { style: "width: 34px", "№" }
                                    th { {t("common.product")} }
                                    th { class: "num", {t("quotes.col_qty")} }
                                    th { class: "num", {t("quotes.col_price")} }
                                    th { class: "num", {t("quotes.col_disc")} }
                                    th { class: "num", {t("quotes.col_total")} }
                                }
                            }
                            tbody {
                                for (i, (li, name)) in lines.into_iter().enumerate() {
                                    {
                                        let n = i + 1;
                                        let disc = if li.discount_pct > 0 { format!("{}%", li.discount_pct) } else { "—".into() };
                                        rsx! {
                                            tr { key: "{i}",
                                                td { class: "muted num", "{n}" }
                                                td { class: "small", "{name}" }
                                                td { class: "num", "{fmt::num(li.qty as i64)}" }
                                                td { class: "num nowrap", "{money(li.price)}" }
                                                td { class: "num muted", "{disc}" }
                                                td { class: "num strong nowrap", "{money(li.total())}" }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    div { class: "row end",
                        div { class: "stack gap-4", style: "width: min(340px, 100%)",
                            div { class: "stat-line small", span { class: "muted", {t("quotes.subtotal")} } span { class: "num", "{money(subtotal)}" } }
                            div { class: "stat-line small", span { class: "muted", "{vat_label}" } span { class: "num", "{money(vat)}" } }
                            div { class: "stat-line", style: "border-top: 2px solid var(--c-text); padding-top: 10px",
                                span { class: "strong", {t("quotes.total")} }
                                span { class: "num", style: "font-size: 20px; font-weight: 800", "{money(total)}" }
                            }
                        }
                    }

                    div { class: "stack gap-4", style: "padding: 14px 16px; border-radius: 12px; border: 1px dashed var(--c-border-strong)",
                        span { class: "xs muted upper", {t("quotes.terms")} }
                        span { class: "small", "{terms}" }
                        if !qt.notes.is_empty() {
                            span { class: "small muted", "{qt.notes}" }
                        }
                    }

                    div { class: "grid-2", style: "gap: 28px; margin-top: 8px",
                        div { class: "stack gap-8",
                            div { style: "height: 44px; border-bottom: 1px solid var(--c-border-strong)" }
                            div { class: "row between xs muted",
                                span { {t("quotes.sign_seller")} ": {owner}" }
                                span { {t("quotes.stamp")} }
                            }
                        }
                        div { class: "stack gap-8",
                            div { style: "height: 44px; border-bottom: 1px solid var(--c-border-strong)" }
                            div { class: "row between xs muted",
                                span { {t("quotes.sign_buyer")} }
                                span { {t("quotes.stamp")} }
                            }
                        }
                    }
                }

                div { class: "stack gap-16",
                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: doc_icon, size: 16, class: "tone-accent" } {t("quotes.actions")} }
                            Badge { text: st_text, tone: st_tone, dot: true }
                        }
                        div { class: "card-body stack gap-8",
                            if let Some(n) = overdue_note.clone() {
                                div { class: "callout danger", Icon { name: "triangle-alert", size: 15 } span { "{n}" } }
                            }
                            if st == QuoteStatus::Draft {
                                button { class: "btn primary block", onclick: send, Icon { name: "send", size: 16 } {t("quotes.send")} }
                            }
                            if st == QuoteStatus::Sent {
                                button { class: "btn primary block", onclick: accept, Icon { name: "handshake", size: 16 } {t("quotes.accept")} }
                                button { class: "btn danger block", onclick: reject, Icon { name: "circle-x", size: 16 } {t("quotes.reject")} }
                            }
                            if st == QuoteStatus::Accepted {
                                button { class: "btn primary block", onclick: to_invoice, Icon { name: "receipt", size: 16 } {t("quotes.invoice")} }
                            }
                            if matches!(st, QuoteStatus::Invoiced | QuoteStatus::Overdue) {
                                button { class: "btn success block", onclick: mark_paid, Icon { name: "banknote", size: 16 } {t("quotes.paid")} }
                            }
                            if st == QuoteStatus::Paid {
                                div { class: "callout success", Icon { name: "circle-check", size: 15 } span { {t("quotes.all_done")} } }
                            }
                            if st == QuoteStatus::Rejected {
                                div { class: "callout", Icon { name: "info", size: 15 } span { {t("quotes.rejected_hint")} } }
                            }
                        }
                    }

                    div { class: "card",
                        div { class: "card-head",
                            div { class: "card-title", Icon { name: "history", size: 16, class: "subtle" } {t("quotes.timeline")} }
                        }
                        div { class: "card-body",
                            div { class: "timeline",
                                for (i, (label, when, icon, tn)) in steps.into_iter().enumerate() {
                                    div { key: "{i}", class: "tl-item",
                                        span { class: "ic {tn}", Icon { name: icon, size: 15 } }
                                        div { class: "tl-body",
                                            div { class: "tl-head",
                                                span { class: "small strong", "{label}" }
                                                span { class: "xs subtle", "{when}" }
                                            }
                                        }
                                    }
                                }
                            }
                            if !history.is_empty() {
                                div { class: "stack gap-4", style: "margin-top: 4px; padding-top: 10px; border-top: 1px dashed var(--c-border)",
                                    for (i, (at, text)) in history.into_iter().enumerate() {
                                        {
                                            let when = fmt::relative(at, now, l);
                                            rsx! {
                                                div { key: "{i}", class: "row between xs",
                                                    span { class: "muted truncate", "{text}" }
                                                    span { class: "subtle nowrap", "{when}" }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    if let Some((did, title, dst)) = deal {
                        div { class: "card",
                            div { class: "card-head",
                                div { class: "card-title", Icon { name: "square-kanban", size: 16, class: "subtle" } {t("common.deal")} }
                            }
                            div { class: "list", style: "margin-top: 8px",
                                div { class: "list-row click", onclick: move |_| go(&format!("/deals/{did}")),
                                    div { class: "meta",
                                        span { class: "title small", "{title}" }
                                    }
                                    Badge { text: t(dst.key()), tone: deal_tone }
                                    Icon { name: "chevron-right", size: 16, class: "subtle" }
                                }
                            }
                        }
                    }

                    if let Some(c) = company {
                        {
                            let cid = c.id;
                            let receivable = money_short(c.receivable);
                            let limit = money_short(c.credit_limit);
                            let used = if c.credit_limit > 0 { c.receivable as f64 / c.credit_limit as f64 * 100.0 } else { 0.0 };
                            let used_tone: &'static str = if used > 85.0 { "danger" } else if used > 60.0 { "warning" } else { "success" };
                            rsx! {
                                div { class: "card",
                                    div { class: "card-head",
                                        div { class: "card-title", Icon { name: "building-2", size: 16, class: "subtle" } {t("common.company")} }
                                        Link { to: Route::CompanyDetail { id: cid }, class: "btn ghost sm", {t("common.see")} Icon { name: "arrow-right", size: 14 } }
                                    }
                                    div { class: "card-body stack gap-8",
                                        div { class: "strong", "{c.name}" }
                                        div { class: "row between small", span { class: "muted", {t("deals.receivable")} } span { class: "num strong", "{receivable}" } }
                                        if c.credit_limit > 0 {
                                            Progress { pct: used, tone: used_tone, thin: true }
                                            div { class: "row between xs muted", span { {t("deals.credit")} } span { class: "num", "{limit}" } }
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

pub const STRINGS: &[Entry] = &[
    ("quotes.sub", "Tashkilotlar uchun tijorat takliflari va hisob-fakturalar", "Коммерческие предложения и счета для организаций", "Quotes and invoices for organisations"),
    ("quotes.from_deal", "Bitimdan taklif", "КП из сделки", "Quote from a deal"),
    ("quotes.kpi_outstanding", "To‘lov kutilmoqda", "Ожидаем оплату", "Outstanding"),
    ("quotes.kpi_docs", "{n} ta hujjat", "документов: {n}", "{n} documents"),
    ("quotes.kpi_overdue", "Muddati o‘tgan hisoblar", "Просроченные счета", "Overdue invoices"),
    ("quotes.kpi_orgs", "{n} ta tashkilot", "организаций: {n}", "{n} organisations"),
    ("quotes.kpi_paid", "Shu oy to‘landi", "Оплачено в этом месяце", "Paid this month"),
    ("quotes.kpi_payments", "{n} ta to‘lov", "платежей: {n}", "{n} payments"),
    ("quotes.kpi_accept", "Qabul qilinish", "Принимают", "Acceptance rate"),
    ("quotes.kpi_accept_foot", "yuborilgan takliflardan", "из отправленных КП", "of quotes sent"),
    ("quotes.search", "Raqam yoki tashkilot…", "Номер или организация…", "Number or organisation…"),
    ("quotes.number", "Raqam", "Номер", "Number"),
    ("quotes.issued", "Berilgan", "Выставлен", "Issued"),
    ("quotes.valid", "Amal qiladi / muddat", "Действует / срок", "Valid / due"),
    ("quotes.count", "{n} ta hujjat", "Документов: {n}", "{n} documents"),
    ("quotes.empty", "Bunday hujjatlar yo‘q", "Таких документов нет", "No documents here"),
    ("quotes.empty_text", "Bitim sahifasida mahsulotlardan taklif yarating.", "Создайте КП из товаров на странице сделки.", "Create a quote from a deal’s products."),
    ("quotes.not_found", "Hujjat topilmadi", "Документ не найден", "Document not found"),
    ("quotes.back", "Takliflar va hisoblarga", "К КП и счетам", "Back to quotes"),
    ("quotes.doc_quote", "Tijorat taklifi", "Коммерческое предложение", "Quote"),
    ("quotes.doc_invoice", "Hisob-faktura", "Счёт-фактура", "Invoice"),
    ("quotes.pharmacy_chain", "Dorixonalar tarmog‘i", "Сеть аптек", "Pharmacy chain"),
    ("quotes.seller", "Sotuvchi", "Продавец", "Seller"),
    ("quotes.buyer", "Xaridor", "Покупатель", "Buyer"),
    ("quotes.valid_until", "Amal qilish muddati", "Действительно до", "Valid until"),
    ("quotes.due_date", "To‘lov muddati", "Оплатить до", "Due by"),
    ("quotes.col_qty", "Soni", "Кол-во", "Qty"),
    ("quotes.col_price", "Narxi", "Цена", "Price"),
    ("quotes.col_disc", "Chegirma", "Скидка", "Disc."),
    ("quotes.col_total", "Summa", "Сумма", "Amount"),
    ("quotes.subtotal", "QQSsiz jami", "Итого без НДС", "Subtotal"),
    ("quotes.vat", "QQS {n}%", "НДС {n}%", "VAT {n}%"),
    ("quotes.total", "To‘lovga jami", "Итого к оплате", "Total due"),
    ("quotes.terms", "To‘lov shartlari", "Условия оплаты", "Payment terms"),
    ("quotes.terms_text", "{n} kun ichida bank o‘tkazmasi orqali", "Банковским переводом в течение {n} дн.", "Bank transfer within {n} days"),
    ("quotes.sign_seller", "Sotuvchi", "Продавец", "Seller"),
    ("quotes.sign_buyer", "Xaridor", "Покупатель", "Buyer"),
    ("quotes.stamp", "M.O‘.", "М.П.", "Stamp"),
    ("quotes.actions", "Keyingi qadam", "Следующий шаг", "Next step"),
    ("quotes.send", "Mijozga yuborish", "Отправить клиенту", "Send to the client"),
    ("quotes.sent_toast", "Telegram va e-mail orqali yuborildi: {c}", "Отправлено в Telegram и на e-mail: {c}", "Sent via Telegram and e-mail to {c}"),
    ("quotes.accept", "Qabul qilindi deb belgilash", "Отметить принятым", "Mark accepted"),
    ("quotes.accepted_toast", "Taklif qabul qilindi", "КП принято", "Quote accepted"),
    ("quotes.accepted_deal", "Taklif qabul qilindi, bitim yutildi", "КП принято, сделка выиграна", "Quote accepted and the deal is won"),
    ("quotes.reject", "Rad etildi deb belgilash", "Отметить отказ", "Mark rejected"),
    ("quotes.rejected_toast", "Taklif rad etildi", "КП отклонено", "Quote rejected"),
    ("quotes.rejected_hint", "Nusxa olib, narxni o‘zgartirib qayta yuborish mumkin.", "Можно сделать копию, поменять цену и отправить снова.", "Duplicate it, adjust the price and send again."),
    ("quotes.invoice", "Hisob-fakturaga aylantirish", "Выставить счёт", "Convert to invoice"),
    ("quotes.invoiced_toast", "Hisob-faktura chiqarildi", "Счёт выставлен", "Invoice issued"),
    ("quotes.paid", "To‘landi deb belgilash", "Отметить оплату", "Mark paid"),
    ("quotes.paid_toast", "To‘lov qayd etildi", "Оплата отмечена", "Payment recorded"),
    ("quotes.all_done", "To‘langan. Hammasi joyida.", "Оплачено. Всё готово.", "Paid. All done."),
    ("quotes.duplicate", "Nusxa olish", "Дублировать", "Duplicate"),
    ("quotes.duplicated_toast", "Nusxa qoralama sifatida yaratildi", "Копия создана как черновик", "Copy created as a draft"),
    ("quotes.print", "PDF / chop etish", "PDF / печать", "PDF / print"),
    ("quotes.print_toast", "PDF tayyor", "PDF готов", "PDF ready"),
    ("quotes.timeline", "Holat tarixi", "История статусов", "Status history"),
    ("quotes.days_overdue", "To‘lov {n} kunga kechikdi", "Оплата просрочена на {n} дн.", "Payment is {n} days late"),
];
