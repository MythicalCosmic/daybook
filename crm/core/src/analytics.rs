//! Numbers the screens show: KPIs, RFM, refills, funnels, cohorts, forecasts, leaderboards,
//! plus rule-based "smart insights" and next best actions (computed locally from the data,
//! so they work offline; the AI assistant can phrase them when Daybook's AI is connected).

use std::collections::{HashMap, HashSet};

use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime};

use crate::db::Db;
use crate::fmt;
use crate::i18n::{pick, Entry, Lang};
use crate::model::*;

pub fn month_start(d: NaiveDate) -> NaiveDate {
    NaiveDate::from_ymd_opt(d.year(), d.month(), 1).unwrap_or(d)
}

pub fn add_months(d: NaiveDate, n: i32) -> NaiveDate {
    let total = d.year() * 12 + d.month0() as i32 + n;
    let (y, m) = (total.div_euclid(12), total.rem_euclid(12) as u32 + 1);
    let mut day = d.day();
    loop {
        if let Some(x) = NaiveDate::from_ymd_opt(y, m, day) {
            return x;
        }
        day -= 1;
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Kpis {
    pub revenue_mtd: Money,
    pub revenue_prev_mtd: Money,
    pub orders_mtd: u32,
    pub avg_basket_mtd: Money,
    pub customers_total: u32,
    pub active_customers: u32,
    pub new_customers_mtd: u32,
    pub new_customers_prev: u32,
    pub repeat_rate: f64,
    pub open_deals: u32,
    pub open_pipeline: Money,
    pub weighted_pipeline: Money,
    pub won_mtd: Money,
    pub won_count_mtd: u32,
    pub win_rate: f64,
    pub rotting: u32,
    pub open_tickets: u32,
    pub breached: u32,
    pub unread: u32,
    pub waiting_conversations: u32,
    pub tasks_today: u32,
    pub overdue: u32,
    pub refills_week: u32,
    pub waitlist_waiting: u32,
    pub waitlist_value: Money,
    pub waitlist_arrived: u32,
    pub loyalty_liability: i64,
    pub leads_new: u32,
    pub nps: f64,
}

impl Kpis {
    pub fn revenue_delta(&self) -> f64 {
        delta(self.revenue_mtd as f64, self.revenue_prev_mtd as f64)
    }
    pub fn new_customers_delta(&self) -> f64 {
        delta(self.new_customers_mtd as f64, self.new_customers_prev as f64)
    }
}

pub fn delta(now: f64, before: f64) -> f64 {
    if before <= 0.0 {
        if now > 0.0 {
            100.0
        } else {
            0.0
        }
    } else {
        (now - before) / before * 100.0
    }
}

pub fn kpis(db: &Db, now: NaiveDateTime) -> Kpis {
    let today = now.date();
    let m0 = month_start(today);
    let prev = add_months(m0, -1);
    let prev_cut = add_months(today, -1) + Duration::days(1);
    let mut k = Kpis::default();
    let mut buyers90: HashSet<Id> = HashSet::new();
    for p in &db.purchases {
        let d = p.at.date();
        if d >= m0 {
            k.revenue_mtd += p.total;
            k.orders_mtd += 1;
        } else if d >= prev && d < prev_cut {
            k.revenue_prev_mtd += p.total;
        }
        if (today - d).num_days() <= 90 {
            buyers90.insert(p.customer_id);
        }
    }
    k.avg_basket_mtd = if k.orders_mtd > 0 { k.revenue_mtd / k.orders_mtd as Money } else { 0 };
    k.customers_total = db.customers.iter().filter(|c| !c.archived).count() as u32;
    k.active_customers = buyers90.len() as u32;
    let repeat = db.customers.iter().filter(|c| buyers90.contains(&c.id) && c.orders >= 2).count();
    k.repeat_rate = if buyers90.is_empty() { 0.0 } else { repeat as f64 / buyers90.len() as f64 * 100.0 };
    for c in &db.customers {
        if c.created >= m0 {
            k.new_customers_mtd += 1;
        } else if c.created >= prev && c.created < prev_cut {
            k.new_customers_prev += 1;
        }
    }
    let (mut won90, mut lost90) = (0u32, 0u32);
    for d in &db.deals {
        let v = db.deal_value(d);
        match d.status {
            DealStatus::Open => {
                k.open_deals += 1;
                k.open_pipeline += v;
                k.weighted_pipeline += v * db.deal_probability(d) as Money / 100;
                if db.is_rotting(d, now) {
                    k.rotting += 1;
                }
            }
            DealStatus::Won => {
                if let Some(c) = d.closed_at {
                    if c.date() >= m0 {
                        k.won_mtd += v;
                        k.won_count_mtd += 1;
                    }
                    if (now - c).num_days() <= 90 {
                        won90 += 1;
                    }
                }
            }
            DealStatus::Lost => {
                if d.closed_at.map(|c| (now - c).num_days() <= 90).unwrap_or(false) {
                    lost90 += 1;
                }
            }
        }
    }
    k.win_rate = if won90 + lost90 == 0 { 0.0 } else { won90 as f64 / (won90 + lost90) as f64 * 100.0 };
    for t in &db.tickets {
        if t.is_open() {
            k.open_tickets += 1;
            if t.breached(now) {
                k.breached += 1;
            }
        }
    }
    for c in &db.conversations {
        if c.status != ConvStatus::Resolved {
            k.unread += c.unread as u32;
            if c.waiting_min(now).is_some() {
                k.waiting_conversations += 1;
            }
        }
    }
    let me = db.settings.me;
    for a in db.activities.iter().filter(|a| !a.done && a.owner_id == me) {
        if a.due.date() == today {
            k.tasks_today += 1;
        } else if a.due.date() < today {
            k.overdue += 1;
        }
    }
    k.refills_week = refills(db, today, 7).len() as u32;
    for w in &db.waitlist {
        match w.status {
            WaitStatus::Waiting => {
                k.waitlist_waiting += 1;
                k.waitlist_value += w.value;
            }
            WaitStatus::Arrived => k.waitlist_arrived += 1,
            _ => {}
        }
    }
    k.loyalty_liability = db.customers.iter().map(|c| c.points).sum();
    k.leads_new = db.leads.iter().filter(|l| l.status == LeadStatus::New).count() as u32;
    let scores: Vec<u8> = db.customers.iter().filter_map(|c| c.nps).collect();
    if !scores.is_empty() {
        let pro = scores.iter().filter(|s| **s >= 9).count() as f64;
        let det = scores.iter().filter(|s| **s <= 6).count() as f64;
        k.nps = (pro - det) / scores.len() as f64 * 100.0;
    }
    k
}

/// Revenue per day for the last `days` days (oldest first, today last).
pub fn daily_revenue(db: &Db, today: NaiveDate, days: i64) -> Vec<(NaiveDate, Money)> {
    let start = today - Duration::days(days - 1);
    let mut map: HashMap<NaiveDate, Money> = HashMap::new();
    for p in &db.purchases {
        let d = p.at.date();
        if d >= start && d <= today {
            *map.entry(d).or_default() += p.total;
        }
    }
    (0..days).map(|i| start + Duration::days(i)).map(|d| (d, map.get(&d).copied().unwrap_or(0))).collect()
}

/// Revenue and order count per month for the last `months` months (oldest first).
pub fn monthly_revenue(db: &Db, today: NaiveDate, months: i32) -> Vec<(NaiveDate, Money, u32)> {
    let m0 = month_start(today);
    let start = add_months(m0, -(months - 1));
    let mut map: HashMap<NaiveDate, (Money, u32)> = HashMap::new();
    for p in &db.purchases {
        let m = month_start(p.at.date());
        if m >= start {
            let e = map.entry(m).or_default();
            e.0 += p.total;
            e.1 += 1;
        }
    }
    (0..months)
        .map(|i| add_months(start, i))
        .map(|m| {
            let (v, n) = map.get(&m).copied().unwrap_or((0, 0));
            (m, v, n)
        })
        .collect()
}

pub fn revenue_by_branch(db: &Db, from: NaiveDate) -> Vec<(Id, Money)> {
    let mut map: HashMap<Id, Money> = HashMap::new();
    for p in db.purchases.iter().filter(|p| p.at.date() >= from) {
        *map.entry(p.branch_id).or_default() += p.total;
    }
    let mut v: Vec<(Id, Money)> = db.branches.iter().map(|b| (b.id, map.get(&b.id).copied().unwrap_or(0))).collect();
    v.sort_by(|a, b| b.1.cmp(&a.1));
    v
}

/// Lifetime revenue and customer count per acquisition source.
pub fn revenue_by_source(db: &Db) -> Vec<(Source, Money, u32)> {
    let mut v: Vec<(Source, Money, u32)> = Source::ALL
        .iter()
        .map(|s| {
            let cs = db.customers.iter().filter(|c| c.source == *s);
            let (sum, n) = cs.fold((0, 0), |(a, n), c| (a + c.total_spent, n + 1));
            (*s, sum, n)
        })
        .filter(|x| x.2 > 0)
        .collect();
    v.sort_by(|a, b| b.1.cmp(&a.1));
    v
}

pub fn tier_counts(db: &Db) -> Vec<(Tier, u32, Money)> {
    Tier::ALL
        .iter()
        .map(|t| {
            let cs = db.customers.iter().filter(|c| c.tier == *t && !c.archived);
            let (n, sum) = cs.fold((0, 0), |(n, s), c| (n + 1, s + c.total_spent));
            (*t, n, sum)
        })
        .collect()
}

// ---------------------------------------------------------------- RFM

keyed_enum!(RfmSegment, "rfm", {
    Champions => "champions", Loyal => "loyal", CantLose => "cant_lose", NewCustomers => "new",
    Promising => "promising", NeedAttention => "need_attention", AtRisk => "at_risk",
    Hibernating => "hibernating", Lost => "lost",
});

impl RfmSegment {
    pub fn tone(self) -> &'static str {
        match self {
            RfmSegment::Champions | RfmSegment::Loyal => "success",
            RfmSegment::NewCustomers | RfmSegment::Promising => "info",
            RfmSegment::NeedAttention => "accent",
            RfmSegment::AtRisk | RfmSegment::CantLose => "warning",
            RfmSegment::Hibernating | RfmSegment::Lost => "danger",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rfm {
    pub r: u8,
    pub f: u8,
    pub m: u8,
    pub segment: RfmSegment,
}

pub fn rfm(c: &Customer, today: NaiveDate) -> Rfm {
    let days = c.days_since_last(today).unwrap_or(9999);
    let r = match days {
        d if d <= 14 => 5,
        d if d <= 30 => 4,
        d if d <= 60 => 3,
        d if d <= 120 => 2,
        _ => 1,
    };
    let f = match c.orders {
        o if o >= 20 => 5,
        o if o >= 10 => 4,
        o if o >= 5 => 3,
        o if o >= 2 => 2,
        _ => 1,
    };
    let m = match c.total_spent {
        s if s >= 8_000_000 => 5,
        s if s >= 3_000_000 => 4,
        s if s >= 1_000_000 => 3,
        s if s >= 300_000 => 2,
        _ => 1,
    };
    let segment = if r >= 4 && f >= 4 {
        RfmSegment::Champions
    } else if f >= 4 && r == 3 {
        RfmSegment::Loyal
    } else if f >= 4 {
        RfmSegment::CantLose
    } else if r >= 4 && f == 1 {
        RfmSegment::NewCustomers
    } else if r >= 4 {
        RfmSegment::Promising
    } else if r == 3 {
        RfmSegment::NeedAttention
    } else if r == 2 {
        RfmSegment::AtRisk
    } else if f >= 2 {
        RfmSegment::Hibernating
    } else {
        RfmSegment::Lost
    };
    Rfm { r, f, m, segment }
}

pub fn rfm_breakdown(db: &Db, today: NaiveDate) -> Vec<(RfmSegment, u32, Money)> {
    let mut map: HashMap<RfmSegment, (u32, Money)> = HashMap::new();
    for c in db.customers.iter().filter(|c| !c.archived && c.orders > 0) {
        let e = map.entry(rfm(c, today).segment).or_default();
        e.0 += 1;
        e.1 += c.total_spent;
    }
    RfmSegment::ALL.iter().map(|s| (*s, map.get(s).map(|x| x.0).unwrap_or(0), map.get(s).map(|x| x.1).unwrap_or(0))).collect()
}

/// 0-100: how overdue the customer is against their own buying rhythm.
pub fn churn_risk(c: &Customer, today: NaiveDate) -> u8 {
    let (Some(first), Some(last)) = (c.first_purchase, c.last_purchase) else { return 0 };
    if c.orders < 2 {
        return if (today - last).num_days() > 90 { 70 } else { 20 };
    }
    let rhythm = ((last - first).num_days() as f64 / (c.orders - 1) as f64).max(7.0);
    let since = (today - last).num_days() as f64;
    (((since / rhythm) - 1.0) * 45.0).clamp(0.0, 100.0) as u8
}

// ---------------------------------------------------------------- refills

#[derive(Clone, Debug, PartialEq)]
pub struct RefillDue {
    pub customer_id: Id,
    pub product_id: Id,
    pub condition: Condition,
    pub due: NaiveDate,
    pub days_left: i64,
    pub branch_id: Id,
    pub in_stock: bool,
    pub price: Money,
}

/// Regular medicines that run out within `within_days` (or already ran out, up to 30 days ago).
pub fn refills(db: &Db, today: NaiveDate, within_days: i64) -> Vec<RefillDue> {
    let mut v = Vec::new();
    for c in db.customers.iter().filter(|c| !c.archived && c.consent.health_data) {
        for r in c.regimens.iter().filter(|r| r.remind) {
            let left = r.days_left(today);
            if left <= within_days && left >= -14 {
                let p = db.product(r.product_id);
                v.push(RefillDue {
                    customer_id: c.id,
                    product_id: r.product_id,
                    condition: r.condition,
                    due: r.next_due(),
                    days_left: left,
                    branch_id: c.home_branch,
                    in_stock: p.map(|p| p.stock_at(c.home_branch) > 0).unwrap_or(false),
                    price: p.map(|p| p.price).unwrap_or(0),
                });
            }
        }
    }
    v.sort_by_key(|r| (if r.days_left >= 0 { r.days_left } else { 100 - r.days_left }, r.customer_id));
    v
}

// ---------------------------------------------------------------- pipeline

#[derive(Clone, Debug, PartialEq)]
pub struct FunnelStage {
    pub stage_id: Id,
    pub name: String,
    pub hue: u16,
    pub count: u32,
    pub value: Money,
    pub weighted: Money,
}

pub fn funnel(db: &Db, pipeline_id: Id) -> Vec<FunnelStage> {
    let Some(p) = db.pipeline(pipeline_id) else { return Vec::new() };
    p.stages
        .iter()
        .map(|s| {
            let deals: Vec<&Deal> =
                db.deals.iter().filter(|d| d.status == DealStatus::Open && d.stage_id == s.id).collect();
            let value: Money = deals.iter().map(|d| db.deal_value(d)).sum();
            FunnelStage {
                stage_id: s.id,
                name: s.name.clone(),
                hue: s.hue,
                count: deals.len() as u32,
                value,
                weighted: value * s.probability as Money / 100,
            }
        })
        .collect()
}

/// Weighted and best-case value of open deals by expected close month.
pub fn forecast(db: &Db, today: NaiveDate, months: i32) -> Vec<(NaiveDate, Money, Money)> {
    let m0 = month_start(today);
    (0..months)
        .map(|i| {
            let m = add_months(m0, i);
            let next = add_months(m0, i + 1);
            let (mut w, mut best) = (0, 0);
            for d in db.deals.iter().filter(|d| d.status == DealStatus::Open) {
                let close = if d.expected_close < m0 { m0 } else { d.expected_close };
                if close >= m && close < next {
                    let v = db.deal_value(d);
                    w += v * db.deal_probability(d) as Money / 100;
                    best += v;
                }
            }
            (m, w, best)
        })
        .collect()
}

/// Lost-deal reasons with counts, most common first.
pub fn lost_reasons(db: &Db) -> Vec<(String, u32)> {
    let mut map: HashMap<String, u32> = HashMap::new();
    for d in db.deals.iter().filter(|d| d.status == DealStatus::Lost) {
        *map.entry(d.lost_reason.clone().unwrap_or_else(|| "—".into())).or_default() += 1;
    }
    let mut v: Vec<(String, u32)> = map.into_iter().collect();
    v.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    v
}

// ---------------------------------------------------------------- cohorts

#[derive(Clone, Debug, PartialEq)]
pub struct Cohort {
    pub month: NaiveDate,
    pub size: u32,
    /// Share of the cohort buying again in month +1, +2, ... (percent).
    pub retention: Vec<f64>,
}

pub fn cohorts(db: &Db, today: NaiveDate, months: i32) -> Vec<Cohort> {
    let m0 = month_start(today);
    let start = add_months(m0, -(months - 1));
    let mut bought: HashMap<Id, HashSet<NaiveDate>> = HashMap::new();
    for p in &db.purchases {
        bought.entry(p.customer_id).or_default().insert(month_start(p.at.date()));
    }
    (0..months)
        .map(|i| {
            let month = add_months(start, i);
            let members: Vec<Id> = db
                .customers
                .iter()
                .filter(|c| c.first_purchase.map(month_start) == Some(month))
                .map(|c| c.id)
                .collect();
            let size = members.len() as u32;
            let mut retention = Vec::new();
            let mut k = 1;
            while add_months(month, k) <= m0 {
                let target = add_months(month, k);
                let back = members.iter().filter(|id| bought.get(id).map(|s| s.contains(&target)).unwrap_or(false)).count();
                retention.push(if size == 0 { 0.0 } else { back as f64 / size as f64 * 100.0 });
                k += 1;
            }
            Cohort { month, size, retention }
        })
        .collect()
}

// ---------------------------------------------------------------- team

#[derive(Clone, Debug, PartialEq)]
pub struct Leader {
    pub staff_id: Id,
    pub won_value: Money,
    pub won_count: u32,
    pub calls: u32,
    pub tasks_done: u32,
    pub customers: u32,
    pub score: u32,
}

/// This month's performance per active staff member, best first.
pub fn leaderboard(db: &Db, today: NaiveDate) -> Vec<Leader> {
    let m0 = month_start(today);
    let mut v: Vec<Leader> = db
        .staff
        .iter()
        .filter(|s| s.active && s.role != Role::Owner)
        .map(|s| {
            let won: Vec<&Deal> = db
                .deals
                .iter()
                .filter(|d| d.owner_id == s.id && d.status == DealStatus::Won && d.closed_at.map(|c| c.date() >= m0).unwrap_or(false))
                .collect();
            let won_value: Money = won.iter().map(|d| db.deal_value(d)).sum();
            let done = db.activities.iter().filter(|a| a.owner_id == s.id && a.done && a.done_at.map(|d| d.date() >= m0).unwrap_or(false));
            let (mut calls, mut tasks) = (0, 0);
            for a in done {
                if a.kind == ActivityKind::Call {
                    calls += 1;
                } else {
                    tasks += 1;
                }
            }
            let customers = db.customers.iter().filter(|c| c.owner_id == Some(s.id) && c.created >= m0).count() as u32;
            let score = (won_value / 1_000_000) as u32 * 3 + won.len() as u32 * 20 + calls * 4 + tasks * 3 + customers * 6;
            Leader { staff_id: s.id, won_value, won_count: won.len() as u32, calls, tasks_done: tasks, customers, score }
        })
        .collect();
    v.sort_by(|a, b| b.score.cmp(&a.score));
    v
}

/// Progress of a goal this month: (actual, target).
pub fn goal_progress(db: &Db, g: &Goal, today: NaiveDate) -> (i64, i64) {
    let m0 = month_start(today);
    let actual = match g.metric {
        Metric::Revenue => db
            .purchases
            .iter()
            .filter(|p| p.at.date() >= m0 && g.branch_id.map_or(true, |b| p.branch_id == b))
            .map(|p| p.total)
            .sum::<Money>(),
        Metric::NewCustomers => db
            .customers
            .iter()
            .filter(|c| c.created >= m0 && g.branch_id.map_or(true, |b| c.home_branch == b) && g.staff_id.map_or(true, |s| c.owner_id == Some(s)))
            .count() as i64,
        Metric::DealsWon => db
            .deals
            .iter()
            .filter(|d| d.status == DealStatus::Won && d.closed_at.map(|c| c.date() >= m0).unwrap_or(false) && g.staff_id.map_or(true, |s| d.owner_id == s))
            .map(|d| db.deal_value(d))
            .sum::<Money>(),
        Metric::Calls => db
            .activities
            .iter()
            .filter(|a| a.kind == ActivityKind::Call && a.done && a.done_at.map(|d| d.date() >= m0).unwrap_or(false) && g.staff_id.map_or(true, |s| a.owner_id == s))
            .count() as i64,
        Metric::Retention => kpis(db, today.and_hms_opt(12, 0, 0).unwrap_or_default()).repeat_rate.round() as i64,
    };
    (actual, g.target)
}

// ---------------------------------------------------------------- smart insights

#[derive(Clone, Debug, PartialEq)]
pub struct Insight {
    pub icon: &'static str,
    /// "accent" | "success" | "warning" | "danger" | "info"
    pub tone: &'static str,
    pub title: String,
    pub body: String,
    pub route: String,
    pub action: String,
}

pub fn insights(db: &Db, now: NaiveDateTime, lang: Lang) -> Vec<Insight> {
    let today = now.date();
    let mut v = Vec::new();
    let money = |m: Money| fmt::money_short(m, lang);

    let soon = refills(db, today, 3);
    if !soon.is_empty() {
        let value: Money = soon.iter().map(|r| r.price).sum();
        let out_of_stock = soon.iter().filter(|r| !r.in_stock).count();
        v.push(Insight {
            icon: "repeat",
            tone: "accent",
            title: match lang {
                Lang::Ru => format!("У {} клиентов заканчиваются лекарства", soon.len()),
                Lang::En => format!("{} customers run out of their medicine within 3 days", soon.len()),
                _ => uz(lang, &format!("{} ta mijozning dorisi 3 kun ichida tugaydi", soon.len())),
            },
            body: match lang {
                Lang::Ru => format!("Напомните в Telegram и отложите упаковки: это {} выручки. Нет в наличии: {}.", money(value), out_of_stock),
                Lang::En => format!("Nudge them on Telegram and hold the packs: {} of sales. Out of stock: {}.", money(value), out_of_stock),
                _ => uz(lang, &format!("Telegramda eslatib, qadoqlarni ajratib qo‘ying: {} savdo. Omborda yo‘q: {}.", money(value), out_of_stock)),
            },
            route: "/refills".into(),
            action: pick(lang, "Radarni ochish", "Открыть радар", "Open the radar").into_owned(),
        });
    }

    let rotting: Vec<&Deal> = db.deals.iter().filter(|d| db.is_rotting(d, now)).collect();
    if !rotting.is_empty() {
        let value: Money = rotting.iter().map(|d| db.deal_value(d)).sum();
        v.push(Insight {
            icon: "flame",
            tone: "warning",
            title: match lang {
                Lang::Ru => format!("{} сделок без движения", rotting.len()),
                Lang::En => format!("{} deals have gone quiet", rotting.len()),
                _ => uz(lang, &format!("{} ta bitim to‘xtab qoldi", rotting.len())),
            },
            body: match lang {
                Lang::Ru => format!("В них {}. Самая крупная: «{}».", money(value), rotting[0].title),
                Lang::En => format!("{} is stuck. Biggest: “{}”.", money(value), rotting[0].title),
                _ => uz(lang, &format!("Ularda {} turibdi. Eng kattasi: «{}».", money(value), rotting[0].title)),
            },
            route: "/deals".into(),
            action: pick(lang, "Bitimlarga o‘tish", "К сделкам", "Go to deals").into_owned(),
        });
    }

    let waiting: Vec<&Conversation> =
        db.conversations.iter().filter(|c| c.status != ConvStatus::Resolved && c.waiting_min(now).map(|m| m >= 30).unwrap_or(false)).collect();
    if !waiting.is_empty() {
        v.push(Insight {
            icon: "message-circle",
            tone: "danger",
            title: match lang {
                Lang::Ru => format!("{} клиентов ждут ответа дольше 30 минут", waiting.len()),
                Lang::En => format!("{} customers have waited over 30 minutes for a reply", waiting.len()),
                _ => uz(lang, &format!("{} ta mijoz 30 daqiqadan beri javob kutmoqda", waiting.len())),
            },
            body: pick(
                lang,
                "Tez javob sotuvni ikki baravar oshiradi. Shablonlar va AI javob tayyorlab beradi.",
                "Быстрый ответ удваивает продажи. Шаблоны и AI подготовят ответ.",
                "Fast replies double conversion. Templates and the AI can draft one.",
            )
            .into_owned(),
            route: "/inbox".into(),
            action: pick(lang, "Javob berish", "Ответить", "Reply now").into_owned(),
        });
    }

    let arrived: Vec<&WaitItem> = db.waitlist.iter().filter(|w| w.status == WaitStatus::Arrived).collect();
    if !arrived.is_empty() {
        let value: Money = arrived.iter().map(|w| w.value).sum();
        v.push(Insight {
            icon: "package-check",
            tone: "success",
            title: match lang {
                Lang::Ru => format!("Поступило {} позиций из дефектуры", arrived.len()),
                Lang::En => format!("{} waitlist items have arrived", arrived.len()),
                _ => uz(lang, &format!("Defekturadagi {} ta dori keldi", arrived.len())),
            },
            body: match lang {
                Lang::Ru => format!("Сообщите клиентам и забронируйте — {} продаж.", money(value)),
                Lang::En => format!("Tell the customers and reserve them: {} of sales.", money(value)),
                _ => uz(lang, &format!("Mijozlarga xabar bering va bron qiling: {} savdo.", money(value))),
            },
            route: "/waitlist".into(),
            action: pick(lang, "Xabar berish", "Уведомить", "Notify").into_owned(),
        });
    }

    let breached = db.tickets.iter().filter(|t| t.breached(now)).count();
    let adverse_open = db.tickets.iter().filter(|t| t.is_open() && t.kind == TicketKind::AdverseReaction).count();
    if breached > 0 || adverse_open > 0 {
        v.push(Insight {
            icon: "triangle-alert",
            tone: "danger",
            title: match lang {
                Lang::Ru => format!("Просрочено обращений: {}; нежелательных реакций: {}", breached, adverse_open),
                Lang::En => format!("{} tickets past their SLA, {} adverse reactions open", breached, adverse_open),
                _ => uz(lang, &format!("Muddati o‘tgan murojaatlar: {}, ochiq nojo‘ya ta’sirlar: {}", breached, adverse_open)),
            },
            body: pick(
                lang,
                "Nojo‘ya ta’sirlar 4 soat ichida ko‘rib chiqilishi va farmakonazoratga yuborilishi kerak.",
                "Нежелательные реакции нужно разобрать за 4 часа и передать в фармаконадзор.",
                "Adverse reactions need review within 4 hours and a pharmacovigilance report.",
            )
            .into_owned(),
            route: "/tickets".into(),
            action: pick(lang, "Murojaatlarni ochish", "Открыть обращения", "Open tickets").into_owned(),
        });
    }

    let vip_risk: Vec<&Customer> = db
        .customers
        .iter()
        .filter(|c| !c.archived && c.tier >= Tier::Gold && churn_risk(c, today) >= 50)
        .collect();
    if !vip_risk.is_empty() {
        let value: Money = vip_risk.iter().map(|c| c.avg_basket() * 2).sum();
        v.push(Insight {
            icon: "crown",
            tone: "warning",
            title: match lang {
                Lang::Ru => format!("{} VIP-клиентов перестали приходить", vip_risk.len()),
                Lang::En => format!("{} Gold and Platinum customers are slipping away", vip_risk.len()),
                _ => uz(lang, &format!("{} ta VIP mijoz kelmay qo‘ydi", vip_risk.len())),
            },
            body: match lang {
                Lang::Ru => format!("Персональный звонок фармацевта и бонус вернут около {} в месяц.", money(value)),
                Lang::En => format!("A personal call and a bonus could win back about {} a month.", money(value)),
                _ => uz(lang, &format!("Farmatsevtning shaxsiy qo‘ng‘irog‘i va bonus oyiga taxminan {} qaytaradi.", money(value))),
            },
            route: "/contacts?rfm=cant_lose".into(),
            action: pick(lang, "Ro‘yxatni ko‘rish", "Смотреть список", "See who").into_owned(),
        });
    }

    let birthdays = db.customers.iter().filter(|c| !c.archived && c.birthday_in(today).map(|d| d <= 7).unwrap_or(false)).count();
    if birthdays > 0 {
        v.push(Insight {
            icon: "cake",
            tone: "info",
            title: match lang {
                Lang::Ru => format!("{} дней рождения на этой неделе", birthdays),
                Lang::En => format!("{} birthdays this week", birthdays),
                _ => uz(lang, &format!("Shu hafta {} ta tug‘ilgan kun", birthdays)),
            },
            body: match lang {
                Lang::Ru => format!("Автоматизация поздравит и начислит {} баллов.", fmt::num(db.settings.loyalty.birthday_bonus)),
                Lang::En => format!("The birthday automation greets them with {} bonus points.", fmt::num(db.settings.loyalty.birthday_bonus)),
                _ => uz(lang, &format!("Avtomatlashtirish tabriklaydi va {} bonus ball beradi.", fmt::num(db.settings.loyalty.birthday_bonus))),
            },
            route: "/automations".into(),
            action: pick(lang, "Avtomatlashtirish", "Автоматизация", "Automation").into_owned(),
        });
    }

    let cold_leads = db.leads.iter().filter(|l| l.status == LeadStatus::New && (now - l.at).num_hours() >= 2).count();
    if cold_leads > 0 {
        v.push(Insight {
            icon: "magnet",
            tone: "accent",
            title: match lang {
                Lang::Ru => format!("{} лидов ждут больше 2 часов", cold_leads),
                Lang::En => format!("{} leads have waited more than 2 hours", cold_leads),
                _ => uz(lang, &format!("{} ta lid 2 soatdan ko‘proq kutmoqda", cold_leads)),
            },
            body: pick(
                lang,
                "Birinchi soatda bog‘lanilgan lidlar 7 barobar ko‘proq mijozga aylanadi.",
                "Лиды, с которыми связались в первый час, конвертируются в 7 раз чаще.",
                "Leads contacted within the first hour convert seven times more often.",
            )
            .into_owned(),
            route: "/leads".into(),
            action: pick(lang, "Lidlarni ochish", "Открыть лиды", "Open leads").into_owned(),
        });
    }

    let overdue: Vec<&Quote> = db.quotes.iter().filter(|q| q.status == QuoteStatus::Overdue).collect();
    if !overdue.is_empty() {
        let value: Money = overdue.iter().map(|q| q.total()).sum();
        v.push(Insight {
            icon: "receipt",
            tone: "warning",
            title: match lang {
                Lang::Ru => format!("Просрочены счета на {}", money(value)),
                Lang::En => format!("{} in overdue invoices", money(value)),
                _ => uz(lang, &format!("{} lik hisoblar muddati o‘tdi", money(value))),
            },
            body: match lang {
                Lang::Ru => format!("{} организаций. Daybook может поставить задачу бухгалтеру.", overdue.len()),
                Lang::En => format!("{} organisations. Daybook can give the accountant a task.", overdue.len()),
                _ => uz(lang, &format!("{} ta tashkilot. Daybook buxgalterga vazifa qo‘yishi mumkin.", overdue.len())),
            },
            route: "/quotes".into(),
            action: pick(lang, "Hisoblarni ko‘rish", "Смотреть счета", "See invoices").into_owned(),
        });
    }
    v
}

/// Uzbek text, transliterated for the Cyrillic interface.
fn uz(lang: Lang, s: &str) -> String {
    if lang == Lang::UzCyrl {
        crate::i18n::to_cyrillic(s)
    } else {
        s.to_string()
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct NextAction {
    pub icon: &'static str,
    pub tone: &'static str,
    pub text: String,
    /// "remind" | "call" | "bonus" | "offer" | "upgrade" | "consent" | "reserve"
    pub kind: &'static str,
}

/// Rule-based next best actions for one customer.
pub fn next_best_actions(db: &Db, customer_id: Id, now: NaiveDateTime, lang: Lang) -> Vec<NextAction> {
    let today = now.date();
    let Some(c) = db.customer(customer_id) else { return Vec::new() };
    let mut v = Vec::new();
    for r in c.regimens.iter().filter(|r| r.remind) {
        let left = r.days_left(today);
        if left <= db.settings.refill_lead_days as i64 + 2 {
            let p = db.product_name(Some(r.product_id));
            let in_stock = db.product(r.product_id).map(|p| p.stock_at(c.home_branch) > 0).unwrap_or(false);
            v.push(NextAction {
                icon: "repeat",
                tone: if left < 0 { "danger" } else { "accent" },
                text: match (lang, left < 0) {
                    (Lang::Ru, false) => format!("{p} закончится {}: напомнить и отложить упаковку", fmt::due_in(r.next_due(), today, lang)),
                    (Lang::Ru, true) => format!("{p} закончился {}: позвонить, узнать, всё ли в порядке", fmt::due_in(r.next_due(), today, lang)),
                    (Lang::En, false) => format!("{p} runs out {}: remind and hold a pack", fmt::due_in(r.next_due(), today, lang)),
                    (Lang::En, true) => format!("{p} ran out {}: call and check they're okay", fmt::due_in(r.next_due(), today, lang)),
                    (_, false) => uz(lang, &format!("{p} {} tugaydi: eslatib, qadoq ajratib qo‘ying", fmt::due_in(r.next_due(), today, Lang::Uz))),
                    (_, true) => uz(lang, &format!("{p} {} tugagan: qo‘ng‘iroq qilib, holidan xabar oling", fmt::due_in(r.next_due(), today, Lang::Uz))),
                },
                kind: if in_stock { "remind" } else { "reserve" },
            });
        }
    }
    if let Some(days) = c.birthday_in(today) {
        if days <= 10 {
            v.push(NextAction {
                icon: "cake",
                tone: "info",
                text: match lang {
                    Lang::Ru => format!("День рождения {}: подарите {} баллов", fmt::due_in(today + Duration::days(days), today, lang), db.settings.loyalty.birthday_bonus),
                    Lang::En => format!("Birthday {}: gift {} points", fmt::due_in(today + Duration::days(days), today, lang), db.settings.loyalty.birthday_bonus),
                    _ => uz(lang, &format!("Tug‘ilgan kuni {}: {} ball sovg‘a qiling", fmt::due_in(today + Duration::days(days), today, Lang::Uz), db.settings.loyalty.birthday_bonus)),
                },
                kind: "bonus",
            });
        }
    }
    let risk = churn_risk(c, today);
    if risk >= 50 {
        v.push(NextAction {
            icon: "phone-call",
            tone: "warning",
            text: match lang {
                Lang::Ru => format!("Не покупает уже {}: позвонить с персональным предложением", fmt::days(c.days_since_last(today).unwrap_or(0), lang)),
                Lang::En => format!("No purchase for {}: call with a personal offer", fmt::days(c.days_since_last(today).unwrap_or(0), lang)),
                _ => uz(lang, &format!("{} dan beri xarid qilmadi: shaxsiy taklif bilan qo‘ng‘iroq qiling", fmt::days(c.days_since_last(today).unwrap_or(0), Lang::Uz))),
            },
            kind: "call",
        });
    }
    if let Some((tier, need)) = db.settings.loyalty.next_tier(c.total_spent) {
        if need <= 600_000 {
            v.push(NextAction {
                icon: "crown",
                tone: "success",
                text: match lang {
                    Lang::Ru => format!("До уровня «{}» осталось {}: расскажите об этом", tier_ru(tier), fmt::money_short(need, lang)),
                    Lang::En => format!("{} more to reach {}: let them know", fmt::money_short(need, lang), tier_en(tier)),
                    _ => uz(lang, &format!("{} darajasigacha {} qoldi: bu haqda ayting", tier_uz(tier), fmt::money_short(need, Lang::Uz))),
                },
                kind: "upgrade",
            });
        }
    }
    if c.points >= 50_000 {
        v.push(NextAction {
            icon: "gift",
            tone: "accent",
            text: match lang {
                Lang::Ru => format!("На счёте {} баллов: предложите оплатить ими часть покупки", fmt::num(c.points)),
                Lang::En => format!("{} points waiting: offer to pay part of the next receipt with them", fmt::num(c.points)),
                _ => uz(lang, &format!("Hisobda {} ball bor: keyingi xaridning bir qismini ular bilan to‘lashni taklif qiling", fmt::num(c.points))),
            },
            kind: "offer",
        });
    }
    if !c.consent.telegram && c.telegram.is_some() {
        v.push(NextAction {
            icon: "shield-check",
            tone: "info",
            text: pick(
                lang,
                "Telegram xabarlariga rozilik olinmagan: keyingi tashrifda so‘rang",
                "Нет согласия на Telegram-рассылки: спросите при следующем визите",
                "No Telegram consent yet: ask on the next visit",
            )
            .into_owned(),
            kind: "consent",
        });
    }
    v
}

fn tier_uz(t: Tier) -> &'static str {
    match t {
        Tier::Bronze => "Bronza",
        Tier::Silver => "Kumush",
        Tier::Gold => "Oltin",
        Tier::Platinum => "Platina",
    }
}
fn tier_ru(t: Tier) -> &'static str {
    match t {
        Tier::Bronze => "Бронза",
        Tier::Silver => "Серебро",
        Tier::Gold => "Золото",
        Tier::Platinum => "Платина",
    }
}
fn tier_en(t: Tier) -> &'static str {
    match t {
        Tier::Bronze => "Bronze",
        Tier::Silver => "Silver",
        Tier::Gold => "Gold",
        Tier::Platinum => "Platinum",
    }
}

/// A short narrative about the customer (what the AI summary says in demo mode).
pub fn customer_summary(db: &Db, customer_id: Id, now: NaiveDateTime, lang: Lang) -> String {
    let today = now.date();
    let Some(c) = db.customer(customer_id) else { return String::new() };
    let fav: Vec<String> = db.favourite_products(customer_id, 2).iter().map(|(id, _)| db.product_name(Some(*id))).collect();
    let r = rfm(c, today);
    let conds: Vec<String> = c.regimens.iter().map(|g| g.condition.slug().to_string()).collect::<HashSet<_>>().into_iter().collect();
    let since = c.days_since_last(today).unwrap_or(0);
    match lang {
        Lang::Ru => format!(
            "Клиент с {} г., {} покупок на {}. Чаще всего берёт: {}. {}Последняя покупка {} назад, обычно приходит в {}. Сегмент: {}.",
            c.created.year(),
            c.orders,
            fmt::money_short(c.total_spent, lang),
            if fav.is_empty() { "—".into() } else { fav.join(", ") },
            if conds.is_empty() { String::new() } else { format!("Постоянная терапия ({}). ", conds.len()) },
            fmt::days(since, lang),
            db.branch_name(Some(c.home_branch)),
            r.segment.slug()
        ),
        Lang::En => format!(
            "Customer since {}, {} purchases worth {}. Buys most: {}. {}Last visit {} ago, usually at {}. RFM: {}.",
            c.created.year(),
            c.orders,
            fmt::money_short(c.total_spent, lang),
            if fav.is_empty() { "—".into() } else { fav.join(", ") },
            if conds.is_empty() { String::new() } else { format!("On {} regular therapies. ", c.regimens.len()) },
            fmt::days(since, lang),
            db.branch_name(Some(c.home_branch)),
            r.segment.slug()
        ),
        _ => uz(
            lang,
            &format!(
                "{} yildan beri mijoz, {} ta xarid, jami {}. Ko‘p oladi: {}. {}Oxirgi xarid {} oldin, odatda {} filialiga keladi. RFM: {}.",
                c.created.year(),
                c.orders,
                fmt::money_short(c.total_spent, Lang::Uz),
                if fav.is_empty() { "—".into() } else { fav.join(", ") },
                if conds.is_empty() { String::new() } else { format!("{} ta doimiy davolanish. ", c.regimens.len()) },
                fmt::days(since, Lang::Uz),
                db.branch_name(Some(c.home_branch)),
                r.segment.slug()
            ),
        ),
    }
}

/// Strings for the analytics enums.
pub const STRINGS: &[Entry] = &[
    ("rfm.champions", "Chempionlar", "Чемпионы", "Champions"),
    ("rfm.loyal", "Sodiq mijozlar", "Лояльные", "Loyal"),
    ("rfm.cant_lose", "Yo‘qotib bo‘lmaydi", "Нельзя потерять", "Can’t lose"),
    ("rfm.new", "Yangi mijozlar", "Новые", "New"),
    ("rfm.promising", "Umidli", "Перспективные", "Promising"),
    ("rfm.need_attention", "E’tibor kerak", "Требуют внимания", "Need attention"),
    ("rfm.at_risk", "Xavf ostida", "В зоне риска", "At risk"),
    ("rfm.hibernating", "Uyquda", "Спящие", "Hibernating"),
    ("rfm.lost", "Yo‘qotilgan", "Потерянные", "Lost"),
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn months() {
        let d = NaiveDate::from_ymd_opt(2026, 3, 31).unwrap();
        assert_eq!(add_months(d, -1), NaiveDate::from_ymd_opt(2026, 2, 28).unwrap());
        assert_eq!(add_months(d, 10), NaiveDate::from_ymd_opt(2027, 1, 31).unwrap());
    }
}
