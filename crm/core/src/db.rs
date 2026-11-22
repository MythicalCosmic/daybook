//! The in-memory database: every collection, lookups, and the mutations screens share.
//! Screens may also change the public collections directly; keep aggregates in step
//! by going through the helpers here when one exists (add_purchase, move_deal, ...).

use chrono::{NaiveDate, NaiveDateTime};
use serde::{Deserialize, Serialize};

use crate::i18n::Lang;
use crate::model::*;

pub const DB_VERSION: u32 = 1;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Db {
    pub version: u32,
    pub generated_on: NaiveDate,
    pub next_id: Id,
    pub settings: Settings,
    pub branches: Vec<Branch>,
    pub staff: Vec<Staff>,
    pub customers: Vec<Customer>,
    pub purchases: Vec<Purchase>,
    pub companies: Vec<Company>,
    pub pipelines: Vec<Pipeline>,
    pub deals: Vec<Deal>,
    pub leads: Vec<Lead>,
    pub activities: Vec<Activity>,
    pub conversations: Vec<Conversation>,
    pub campaigns: Vec<Campaign>,
    pub segments: Vec<Segment>,
    pub automations: Vec<Automation>,
    pub products: Vec<Product>,
    pub waitlist: Vec<WaitItem>,
    pub tickets: Vec<Ticket>,
    pub quotes: Vec<Quote>,
    pub loyalty: Vec<LoyaltyTx>,
    pub goals: Vec<Goal>,
    pub notes: Vec<Note>,
    pub audit: Vec<AuditEntry>,
    pub notifications: Vec<Notification>,
}

macro_rules! finder {
    ($get:ident, $get_mut:ident, $field:ident, $ty:ty) => {
        pub fn $get(&self, id: Id) -> Option<&$ty> {
            self.$field.iter().find(|x| x.id == id)
        }
        pub fn $get_mut(&mut self, id: Id) -> Option<&mut $ty> {
            self.$field.iter_mut().find(|x| x.id == id)
        }
    };
}

/// One line in a customer's or company's timeline.
#[derive(Clone, Debug, PartialEq)]
pub struct TimelineItem {
    pub at: NaiveDateTime,
    pub icon: &'static str,
    /// "purchase", "activity", "message", "ticket", "note", "waitlist", "loyalty", "deal"
    pub kind: &'static str,
    pub title: String,
    pub body: String,
    pub route: Option<String>,
    pub tone: &'static str,
}

/// A command-palette search result.
#[derive(Clone, Debug, PartialEq)]
pub struct SearchHit {
    pub kind: &'static str,
    pub icon: &'static str,
    pub title: String,
    pub subtitle: String,
    pub route: String,
}

impl Db {
    finder!(branch, branch_mut, branches, Branch);
    finder!(staff_member, staff_member_mut, staff, Staff);
    finder!(customer, customer_mut, customers, Customer);
    finder!(company, company_mut, companies, Company);
    finder!(pipeline, pipeline_mut, pipelines, Pipeline);
    finder!(deal, deal_mut, deals, Deal);
    finder!(lead, lead_mut, leads, Lead);
    finder!(activity, activity_mut, activities, Activity);
    finder!(conversation, conversation_mut, conversations, Conversation);
    finder!(campaign, campaign_mut, campaigns, Campaign);
    finder!(segment, segment_mut, segments, Segment);
    finder!(automation, automation_mut, automations, Automation);
    finder!(product, product_mut, products, Product);
    finder!(wait_item, wait_item_mut, waitlist, WaitItem);
    finder!(ticket, ticket_mut, tickets, Ticket);
    finder!(quote, quote_mut, quotes, Quote);

    pub fn new_id(&mut self) -> Id {
        self.next_id += 1;
        self.next_id
    }

    pub fn lang(&self) -> Lang {
        self.settings.lang
    }

    pub fn me(&self) -> Option<&Staff> {
        self.staff_member(self.settings.me)
    }

    // ------------------------------------------------------------ names

    pub fn staff_name(&self, id: Option<Id>) -> String {
        id.and_then(|i| self.staff_member(i)).map(|s| s.name.clone()).unwrap_or_else(|| "—".into())
    }
    pub fn branch_name(&self, id: Option<Id>) -> String {
        id.and_then(|i| self.branch(i)).map(|b| b.name.clone()).unwrap_or_else(|| "—".into())
    }
    pub fn customer_name(&self, id: Option<Id>) -> String {
        id.and_then(|i| self.customer(i)).map(|c| c.name()).unwrap_or_else(|| "—".into())
    }
    pub fn company_name(&self, id: Option<Id>) -> String {
        id.and_then(|i| self.company(i)).map(|c| c.name.clone()).unwrap_or_else(|| "—".into())
    }
    pub fn product_name(&self, id: Option<Id>) -> String {
        id.and_then(|i| self.product(i)).map(|p| p.name.clone()).unwrap_or_else(|| "—".into())
    }

    /// The stage and its pipeline for a stage id.
    pub fn stage(&self, stage_id: Id) -> Option<(&Pipeline, &Stage)> {
        self.pipelines.iter().find_map(|p| p.stages.iter().find(|s| s.id == stage_id).map(|s| (p, s)))
    }

    pub fn deal_probability(&self, d: &Deal) -> u8 {
        match d.status {
            DealStatus::Won => 100,
            DealStatus::Lost => 0,
            DealStatus::Open => self.stage(d.stage_id).map(|(_, s)| s.probability).unwrap_or(10),
        }
    }

    pub fn is_rotting(&self, d: &Deal, now: NaiveDateTime) -> bool {
        d.status == DealStatus::Open
            && self.stage(d.stage_id).map(|(_, s)| d.idle_days(now) > s.rot_days as i64).unwrap_or(false)
    }

    // ------------------------------------------------------------ journal

    /// Adds an audit line by the signed-in user.
    pub fn log(&mut self, now: NaiveDateTime, text: impl Into<String>, sensitive: bool) {
        let id = self.new_id();
        let actor = Some(self.settings.me);
        self.audit.insert(0, AuditEntry { id, at: now, actor_id: actor, text: text.into(), sensitive });
        if self.audit.len() > 500 {
            self.audit.truncate(500);
        }
    }

    pub fn notify(&mut self, now: NaiveDateTime, kind: NotifKind, title: impl Into<String>, body: impl Into<String>, route: impl Into<String>) {
        let id = self.new_id();
        self.notifications.insert(
            0,
            Notification { id, at: now, kind, title: title.into(), body: body.into(), read: false, route: route.into() },
        );
        if self.notifications.len() > 80 {
            self.notifications.truncate(80);
        }
    }

    pub fn unread_notifications(&self) -> usize {
        self.notifications.iter().filter(|n| !n.read).count()
    }

    // ------------------------------------------------------------ activities

    pub fn add_activity(&mut self, mut a: Activity) -> Id {
        a.id = self.new_id();
        let id = a.id;
        if let (Some(deal_id), true) = (a.deal_id, a.done) {
            let at = a.done_at.unwrap_or(a.due);
            if let Some(d) = self.deal_mut(deal_id) {
                d.last_activity = d.last_activity.max(at);
            }
        }
        self.activities.push(a);
        id
    }

    pub fn complete_activity(&mut self, id: Id, now: NaiveDateTime) {
        let mut deal = None;
        if let Some(a) = self.activity_mut(id) {
            a.done = !a.done;
            a.done_at = if a.done { Some(now) } else { None };
            deal = a.deal_id;
        }
        if let Some(d) = deal.and_then(|d| self.deal_mut(d)) {
            d.last_activity = now;
        }
    }

    pub fn open_activities_for(&self, owner: Id) -> impl Iterator<Item = &Activity> {
        self.activities.iter().filter(move |a| !a.done && a.owner_id == owner)
    }

    // ------------------------------------------------------------ deals

    pub fn move_deal(&mut self, id: Id, stage_id: Id, now: NaiveDateTime) {
        let stage_name = self.stage(stage_id).map(|(_, s)| s.name.clone()).unwrap_or_default();
        let mut title = String::new();
        if let Some(d) = self.deal_mut(id) {
            if d.stage_id == stage_id && d.status == DealStatus::Open {
                return;
            }
            d.stage_id = stage_id;
            d.stage_since = now;
            d.last_activity = now;
            d.status = DealStatus::Open;
            d.closed_at = None;
            title = d.title.clone();
        }
        if !title.is_empty() {
            self.log(now, format!("{title} → {stage_name}"), false);
        }
    }

    pub fn win_deal(&mut self, id: Id, now: NaiveDateTime) {
        let mut title = String::new();
        if let Some(d) = self.deal_mut(id) {
            d.status = DealStatus::Won;
            d.closed_at = Some(now);
            d.last_activity = now;
            d.lost_reason = None;
            title = d.title.clone();
        }
        if !title.is_empty() {
            self.log(now, format!("✓ {title}"), false);
            self.notify(now, NotifKind::Deal, title, String::new(), format!("/deals/{id}"));
        }
    }

    pub fn lose_deal(&mut self, id: Id, reason: impl Into<String>, now: NaiveDateTime) {
        let reason = reason.into();
        let mut title = String::new();
        if let Some(d) = self.deal_mut(id) {
            d.status = DealStatus::Lost;
            d.closed_at = Some(now);
            d.last_activity = now;
            d.lost_reason = Some(reason.clone());
            title = d.title.clone();
        }
        if !title.is_empty() {
            self.log(now, format!("✗ {title}: {reason}"), false);
        }
    }

    pub fn deal_value(&self, d: &Deal) -> Money {
        if d.lines.is_empty() {
            d.value
        } else {
            d.lines.iter().map(LineItem::total).sum()
        }
    }

    // ------------------------------------------------------------ purchases and loyalty

    /// Records a sale: keeps the customer's totals, points, tier and loyalty ledger in step.
    pub fn add_purchase(&mut self, mut p: Purchase) -> Id {
        p.id = self.new_id();
        let id = p.id;
        let loyalty = self.settings.loyalty.clone();
        let bonus_base: Money = p
            .items
            .iter()
            .filter(|i| {
                self.product(i.product_id).map(|pr| !(pr.no_bonus || (loyalty.exclude_rx && pr.rx))).unwrap_or(true)
            })
            .map(LineItem::total)
            .sum();
        p.total = p.items.iter().map(LineItem::total).sum::<Money>() - p.points_used;
        let mut tier_up = None;
        if let Some(c) = self.customers.iter_mut().find(|c| c.id == p.customer_id) {
            let rate = loyalty.cashback(c.tier) as f64 / 100.0;
            p.points_earned = if loyalty.enabled { (bonus_base as f64 * rate).round() as i64 } else { 0 };
            c.points += p.points_earned - p.points_used;
            c.total_spent += p.total;
            c.orders += 1;
            let day = p.at.date();
            c.first_purchase = Some(c.first_purchase.map_or(day, |f| f.min(day)));
            c.last_purchase = Some(c.last_purchase.map_or(day, |l| l.max(day)));
            let new_tier = loyalty.tier_for(c.total_spent);
            if new_tier > c.tier {
                c.tier = new_tier;
                tier_up = Some(new_tier);
            }
            // regimens: buying the medicine restarts its pack
            for r in c.regimens.iter_mut() {
                if p.items.iter().any(|i| i.product_id == r.product_id) {
                    r.last_bought = r.last_bought.max(day);
                }
            }
        }
        if p.points_earned > 0 {
            let tid = self.new_id();
            self.loyalty.push(LoyaltyTx {
                id: tid,
                customer_id: p.customer_id,
                at: p.at,
                points: p.points_earned,
                kind: TxKind::Earn,
                note: String::new(),
                branch_id: Some(p.branch_id),
            });
        }
        if p.points_used > 0 {
            let tid = self.new_id();
            self.loyalty.push(LoyaltyTx {
                id: tid,
                customer_id: p.customer_id,
                at: p.at,
                points: -p.points_used,
                kind: TxKind::Redeem,
                note: String::new(),
                branch_id: Some(p.branch_id),
            });
        }
        let at = p.at;
        let cid = p.customer_id;
        self.purchases.push(p);
        if let Some(t) = tier_up {
            let name = self.customer_name(Some(cid));
            self.notify(at, NotifKind::System, name, t.key(), format!("/contacts/{cid}"));
        }
        id
    }

    pub fn give_points(&mut self, customer_id: Id, points: i64, kind: TxKind, note: impl Into<String>, now: NaiveDateTime) {
        if let Some(c) = self.customer_mut(customer_id) {
            c.points = (c.points + points).max(0);
        }
        let id = self.new_id();
        self.loyalty.push(LoyaltyTx { id, customer_id, at: now, points, kind, note: note.into(), branch_id: None });
    }

    pub fn purchases_of(&self, customer_id: Id) -> Vec<&Purchase> {
        let mut v: Vec<&Purchase> = self.purchases.iter().filter(|p| p.customer_id == customer_id).collect();
        v.sort_by(|a, b| b.at.cmp(&a.at));
        v
    }

    /// The products a customer buys most, with counts.
    pub fn favourite_products(&self, customer_id: Id, n: usize) -> Vec<(Id, u32)> {
        let mut counts: std::collections::HashMap<Id, u32> = std::collections::HashMap::new();
        for p in self.purchases.iter().filter(|p| p.customer_id == customer_id) {
            for i in &p.items {
                *counts.entry(i.product_id).or_default() += i.qty;
            }
        }
        let mut v: Vec<(Id, u32)> = counts.into_iter().collect();
        v.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        v.truncate(n);
        v
    }

    // ------------------------------------------------------------ timeline

    pub fn customer_timeline(&self, customer_id: Id, lang: Lang) -> Vec<TimelineItem> {
        let mut out = Vec::new();
        for p in self.purchases.iter().filter(|p| p.customer_id == customer_id) {
            let names: Vec<String> = p.items.iter().take(3).map(|i| self.product_name(Some(i.product_id))).collect();
            out.push(TimelineItem {
                at: p.at,
                icon: "shopping-bag",
                kind: "purchase",
                title: format!("{} · {}", crate::fmt::money(p.total, lang), self.branch_name(Some(p.branch_id))),
                body: names.join(", "),
                route: None,
                tone: "success",
            });
        }
        for a in self.activities.iter().filter(|a| a.customer_id == Some(customer_id)) {
            out.push(TimelineItem {
                at: a.done_at.unwrap_or(a.due),
                icon: activity_icon(a.kind),
                kind: "activity",
                title: a.title.clone(),
                body: a.outcome.clone().unwrap_or_else(|| a.notes.clone()),
                route: None,
                tone: if a.done { "muted" } else { "accent" },
            });
        }
        for c in self.conversations.iter().filter(|c| c.customer_id == Some(customer_id)) {
            if let Some(m) = c.messages.last() {
                out.push(TimelineItem {
                    at: m.at,
                    icon: channel_icon(c.channel),
                    kind: "message",
                    title: crate::i18n::pick(lang, "Yozishma", "Переписка", "Conversation").into_owned(),
                    body: m.text.clone(),
                    route: Some(format!("/inbox/{}", c.id)),
                    tone: "info",
                });
            }
        }
        for t in self.tickets.iter().filter(|t| t.customer_id == Some(customer_id)) {
            out.push(TimelineItem {
                at: t.created,
                icon: "life-buoy",
                kind: "ticket",
                title: format!("{} · {}", t.number, t.subject),
                body: t.description.clone(),
                route: Some(format!("/tickets/{}", t.id)),
                tone: if t.kind == TicketKind::AdverseReaction { "danger" } else { "warning" },
            });
        }
        for n in self.notes.iter().filter(|n| n.customer_id == Some(customer_id)) {
            out.push(TimelineItem {
                at: n.at,
                icon: "sticky-note",
                kind: "note",
                title: self.staff_name(n.author_id),
                body: n.text.clone(),
                route: None,
                tone: "muted",
            });
        }
        for w in self.waitlist.iter().filter(|w| w.customer_id == customer_id) {
            out.push(TimelineItem {
                at: w.at,
                icon: "hourglass",
                kind: "waitlist",
                title: w.product_name.clone(),
                body: crate::i18n::pick(lang, "Defekturaga yozildi", "Записан в дефектуру", "Added to the waitlist").into_owned(),
                route: Some("/waitlist".into()),
                tone: "warning",
            });
        }
        out.sort_by(|a, b| b.at.cmp(&a.at));
        out
    }

    // ------------------------------------------------------------ segments

    pub fn rule_matches(&self, r: &Rule, c: &Customer, today: NaiveDate) -> bool {
        let num = |v: i64| -> bool {
            let x: i64 = r.value.trim().replace([' ', '\u{a0}'], "").parse().unwrap_or(0);
            match r.op {
                Op::Gt => v > x,
                Op::Lt => v < x,
                Op::Eq => v == x,
                Op::Ne => v != x,
                _ => false,
            }
        };
        let text = |v: &str| -> bool {
            let x = r.value.trim().to_lowercase();
            let v = v.to_lowercase();
            match r.op {
                Op::Eq => v == x,
                Op::Ne => v != x,
                Op::Contains => v.contains(&x),
                _ => false,
            }
        };
        let flag = |v: bool| -> bool {
            match r.op {
                Op::IsTrue => v,
                Op::IsFalse => !v,
                _ => false,
            }
        };
        match r.field {
            Field::Tier => text(c.tier.slug()),
            Field::TotalSpent => num(c.total_spent),
            Field::Orders => num(c.orders as i64),
            Field::DaysSinceLast => num(c.days_since_last(today).unwrap_or(9999)),
            Field::Age => c.age(today).map(|a| num(a as i64)).unwrap_or(false),
            Field::Gender => text(c.gender.slug()),
            Field::Branch => text(&c.home_branch.to_string()),
            Field::Tag => match r.op {
                Op::Ne => !c.tags.iter().any(|t| t.eq_ignore_ascii_case(r.value.trim())),
                _ => c.tags.iter().any(|t| t.to_lowercase().contains(&r.value.trim().to_lowercase())),
            },
            Field::Condition => {
                let has = c.regimens.iter().any(|g| g.condition.slug() == r.value.trim());
                if r.op == Op::Ne {
                    !has
                } else {
                    has
                }
            }
            Field::Source => text(c.source.slug()),
            Field::Points => num(c.points),
            Field::ConsentTelegram => flag(c.consent.telegram),
            Field::ConsentSms => flag(c.consent.sms),
            Field::BirthdayInDays => c.birthday_in(today).map(num).unwrap_or(false),
            Field::RefillDueInDays => c.regimens.iter().map(|g| g.days_left(today)).min().map(num).unwrap_or(false),
            Field::Corporate => flag(c.company_id.is_some()),
        }
    }

    pub fn customer_in_segment(&self, s: &Segment, c: &Customer, today: NaiveDate) -> bool {
        if c.archived {
            return false;
        }
        if s.rules.is_empty() {
            return true;
        }
        if s.match_all {
            s.rules.iter().all(|r| self.rule_matches(r, c, today))
        } else {
            s.rules.iter().any(|r| self.rule_matches(r, c, today))
        }
    }

    pub fn segment_members(&self, s: &Segment, today: NaiveDate) -> Vec<Id> {
        self.customers.iter().filter(|c| self.customer_in_segment(s, c, today)).map(|c| c.id).collect()
    }

    pub fn segment_size(&self, segment_id: Id, today: NaiveDate) -> usize {
        self.segment(segment_id).map(|s| self.segment_members(s, today).len()).unwrap_or(0)
    }

    // ------------------------------------------------------------ inbox, tasks

    pub fn unread_inbox(&self) -> u32 {
        self.conversations.iter().filter(|c| c.status != ConvStatus::Resolved).map(|c| c.unread as u32).sum()
    }

    pub fn tasks_due(&self, owner: Option<Id>, day: NaiveDate) -> usize {
        self.activities
            .iter()
            .filter(|a| !a.done && a.due.date() <= day && owner.map_or(true, |o| a.owner_id == o))
            .count()
    }

    // ------------------------------------------------------------ search

    pub fn search(&self, query: &str, limit: usize) -> Vec<SearchHit> {
        let q = query.trim().to_lowercase();
        if q.is_empty() {
            return Vec::new();
        }
        let digits: String = q.chars().filter(|c| c.is_ascii_digit()).collect();
        let mut out = Vec::new();
        for c in &self.customers {
            let name = c.name().to_lowercase();
            let phone_hit = digits.len() >= 3 && c.phone.contains(&digits);
            if name.contains(&q) || phone_hit || c.card_no.contains(&q) {
                out.push(SearchHit {
                    kind: "customer",
                    icon: "user",
                    title: c.name(),
                    subtitle: format!("{} · {}", crate::fmt::phone(&c.phone), c.tier.slug()),
                    route: format!("/contacts/{}", c.id),
                });
            }
        }
        for co in &self.companies {
            if co.name.to_lowercase().contains(&q) || co.tin.contains(&q) {
                out.push(SearchHit {
                    kind: "company",
                    icon: "building-2",
                    title: co.name.clone(),
                    subtitle: co.kind.slug().into(),
                    route: format!("/companies/{}", co.id),
                });
            }
        }
        for d in &self.deals {
            if d.title.to_lowercase().contains(&q) {
                out.push(SearchHit {
                    kind: "deal",
                    icon: "square-kanban",
                    title: d.title.clone(),
                    subtitle: crate::fmt::money_short(self.deal_value(d), self.lang()),
                    route: format!("/deals/{}", d.id),
                });
            }
        }
        for p in &self.products {
            if p.name.to_lowercase().contains(&q) || p.generic.to_lowercase().contains(&q) || p.barcode.contains(&q) {
                out.push(SearchHit {
                    kind: "product",
                    icon: "pill",
                    title: p.name.clone(),
                    subtitle: crate::fmt::money(p.price, self.lang()),
                    route: format!("/products?id={}", p.id),
                });
            }
        }
        for t in &self.tickets {
            if t.number.to_lowercase().contains(&q) || t.subject.to_lowercase().contains(&q) {
                out.push(SearchHit {
                    kind: "ticket",
                    icon: "life-buoy",
                    title: format!("{} · {}", t.number, t.subject),
                    subtitle: t.kind.slug().into(),
                    route: format!("/tickets/{}", t.id),
                });
            }
        }
        for l in &self.leads {
            if l.name.to_lowercase().contains(&q) || (digits.len() >= 3 && l.phone.contains(&digits)) {
                out.push(SearchHit {
                    kind: "lead",
                    icon: "magnet",
                    title: l.name.clone(),
                    subtitle: l.interest.clone(),
                    route: "/leads".into(),
                });
            }
        }
        out.truncate(limit);
        out
    }
}

pub fn activity_icon(k: ActivityKind) -> &'static str {
    match k {
        ActivityKind::Call => "phone",
        ActivityKind::Meeting => "users",
        ActivityKind::Task => "square-check",
        ActivityKind::Message => "message-circle",
        ActivityKind::Email => "mail",
        ActivityKind::Visit => "map-pin",
        ActivityKind::Delivery => "truck",
    }
}

pub fn channel_icon(c: Channel) -> &'static str {
    match c {
        Channel::Telegram => "send",
        Channel::Sms => "message-square-text",
        Channel::WhatsApp => "message-circle",
        Channel::Instagram => "camera",
        Channel::Phone => "phone",
        Channel::Email => "mail",
        Channel::Web => "globe",
    }
}

pub fn org_icon(k: OrgKind) -> &'static str {
    match k {
        OrgKind::Clinic => "stethoscope",
        OrgKind::Hospital => "hospital",
        OrgKind::Corporate => "briefcase",
        OrgKind::Insurance => "shield-check",
        OrgKind::Distributor => "truck",
        OrgKind::School => "notebook-pen",
        OrgKind::Kindergarten => "baby",
        OrgKind::Lab => "syringe",
        OrgKind::Government => "building",
    }
}

pub fn category_icon(c: ProductCategory) -> &'static str {
    match c {
        ProductCategory::Rx => "file-check",
        ProductCategory::Otc => "pill",
        ProductCategory::Vitamins => "sparkles",
        ProductCategory::Diabetes => "activity",
        ProductCategory::Devices => "gauge",
        ProductCategory::Baby => "baby",
        ProductCategory::Cosmetics => "heart",
        ProductCategory::Hygiene => "shield",
    }
}

pub fn ticket_icon(k: TicketKind) -> &'static str {
    match k {
        TicketKind::Complaint => "circle-alert",
        TicketKind::Return => "undo-2",
        TicketKind::AdverseReaction => "triangle-alert",
        TicketKind::Quality => "badge-check",
        TicketKind::Delivery => "truck",
        TicketKind::Question => "circle-help",
        TicketKind::Praise => "thumbs-up",
    }
}
