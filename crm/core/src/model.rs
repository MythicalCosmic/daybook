//! The CRM's data. Plain serde structs, one company per database.
//! Ids are unique across every collection (one counter in [`crate::Db`]).
//! New fields go at the end of a struct with `#[serde(default)]`, so saved data keeps loading.

use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime};
use serde::{Deserialize, Serialize};

use crate::i18n::Lang;

pub type Id = u32;
/// Money in so'm. UZS has no subunits in practice.
pub type Money = i64;

keyed_enum!(Role, "role", {
    Owner => "owner", Manager => "manager", Pharmacist => "pharmacist", Cashier => "cashier",
    CallAgent => "call_agent", SalesRep => "sales_rep", Courier => "courier", Marketer => "marketer",
});
keyed_enum!(Gender, "gender", { Female => "female", Male => "male" });
keyed_enum!(Tier, "tier", { Bronze => "bronze", Silver => "silver", Gold => "gold", Platinum => "platinum" });
keyed_enum!(Source, "source", {
    WalkIn => "walk_in", Telegram => "telegram", Instagram => "instagram", Referral => "referral",
    Doctor => "doctor", Website => "website", Call => "call", Corporate => "corporate", Qr => "qr",
});
keyed_enum!(Condition, "condition", {
    Hypertension => "hypertension", Diabetes => "diabetes", Cholesterol => "cholesterol",
    Thyroid => "thyroid", Asthma => "asthma", Heart => "heart", Pregnancy => "pregnancy", Allergy => "allergy",
});
keyed_enum!(Channel, "channel", {
    Telegram => "telegram", Sms => "sms", WhatsApp => "whatsapp", Instagram => "instagram",
    Phone => "phone", Email => "email", Web => "web",
});
keyed_enum!(SaleChannel, "sale_channel", {
    InStore => "in_store", Delivery => "delivery", Pickup => "pickup", TelegramOrder => "telegram_order",
});
keyed_enum!(OrgKind, "org", {
    Clinic => "clinic", Hospital => "hospital", Corporate => "corporate", Insurance => "insurance",
    Distributor => "distributor", School => "school", Kindergarten => "kindergarten", Lab => "lab",
    Government => "government",
});
keyed_enum!(DealStatus, "deal_status", { Open => "open", Won => "won", Lost => "lost" });
keyed_enum!(LeadStatus, "lead_status", {
    New => "new", Contacted => "contacted", Qualified => "qualified", Converted => "converted", Junk => "junk",
});
keyed_enum!(ActivityKind, "activity", {
    Call => "call", Meeting => "meeting", Task => "task", Message => "message", Email => "email",
    Visit => "visit", Delivery => "delivery",
});
keyed_enum!(Priority, "priority", { Low => "low", Normal => "normal", High => "high", Urgent => "urgent" });
keyed_enum!(ConvStatus, "conv_status", { Open => "open", Pending => "pending", Resolved => "resolved" });
keyed_enum!(MsgKind, "msg_kind", {
    Text => "text", Photo => "photo", Voice => "voice", File => "file", System => "system", Note => "note",
});
keyed_enum!(CampaignStatus, "campaign_status", {
    Draft => "draft", Scheduled => "scheduled", Running => "running", Done => "done", Paused => "paused",
});
keyed_enum!(ProductCategory, "category", {
    Rx => "rx", Otc => "otc", Vitamins => "vitamins", Diabetes => "diabetes", Devices => "devices",
    Baby => "baby", Cosmetics => "cosmetics", Hygiene => "hygiene",
});
keyed_enum!(WaitStatus, "wait_status", {
    Waiting => "waiting", Arrived => "arrived", Notified => "notified", Reserved => "reserved",
    PickedUp => "picked_up", Cancelled => "cancelled",
});
keyed_enum!(TicketKind, "ticket_kind", {
    Complaint => "complaint", Return => "return", AdverseReaction => "adverse_reaction", Quality => "quality",
    Delivery => "delivery", Question => "question", Praise => "praise",
});
keyed_enum!(TicketStatus, "ticket_status", {
    New => "new", InProgress => "in_progress", Waiting => "waiting", Resolved => "resolved", Closed => "closed",
});
keyed_enum!(QuoteStatus, "quote_status", {
    Draft => "draft", Sent => "sent", Accepted => "accepted", Rejected => "rejected",
    Invoiced => "invoiced", Paid => "paid", Overdue => "overdue",
});
keyed_enum!(TxKind, "tx", { Earn => "earn", Redeem => "redeem", Bonus => "bonus", Expire => "expire", Adjust => "adjust" });
keyed_enum!(Metric, "metric", {
    Revenue => "revenue", NewCustomers => "new_customers", DealsWon => "deals_won", Calls => "calls",
    Retention => "retention",
});
keyed_enum!(Field, "field", {
    Tier => "tier", TotalSpent => "total_spent", Orders => "orders", DaysSinceLast => "days_since_last",
    Age => "age", Gender => "gender", Branch => "branch", Tag => "tag", Condition => "condition",
    Source => "source", Points => "points", ConsentTelegram => "consent_telegram", ConsentSms => "consent_sms",
    BirthdayInDays => "birthday_in_days", RefillDueInDays => "refill_due_in_days", Corporate => "corporate",
});
keyed_enum!(Op, "op", {
    Eq => "eq", Ne => "ne", Gt => "gt", Lt => "lt", Contains => "contains", IsTrue => "is_true", IsFalse => "is_false",
});
keyed_enum!(NotifKind, "notif", {
    Lead => "lead", Message => "message", Task => "task", Deal => "deal", Ticket => "ticket",
    Refill => "refill", Waitlist => "waitlist", System => "system",
});
keyed_enum!(Theme, "theme", { System => "system", Light => "light", Dark => "dark" });

impl Default for Theme {
    fn default() -> Self {
        Theme::System
    }
}

impl Tier {
    /// Hue used for the tier's badge and card art.
    pub fn hue(self) -> u16 {
        match self {
            Tier::Bronze => 24,
            Tier::Silver => 210,
            Tier::Gold => 42,
            Tier::Platinum => 265,
        }
    }
}

// ---------------------------------------------------------------- organisation

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Branch {
    pub id: Id,
    pub name: String,
    pub district: String,
    pub address: String,
    pub phone: String,
    pub manager_id: Option<Id>,
    pub hue: u16,
    pub open_hours: String,
    #[serde(default)]
    pub daybook_id: Option<i64>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Staff {
    pub id: Id,
    pub name: String,
    pub role: Role,
    pub branch_id: Option<Id>,
    pub phone: String,
    pub telegram: String,
    pub hue: u16,
    pub active: bool,
    #[serde(default)]
    pub daybook_id: Option<i64>,
}

// ---------------------------------------------------------------- customers

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Consent {
    pub sms: bool,
    pub telegram: bool,
    /// Consent to keep health data (regimens, allergies). Without it those stay empty.
    pub health_data: bool,
    pub given_on: Option<NaiveDate>,
}

/// A regular medicine a customer buys (chronic therapy): drives the refill radar.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Regimen {
    pub product_id: Id,
    pub condition: Condition,
    pub dose: String,
    /// How many days one pack lasts.
    pub pack_days: u16,
    pub last_bought: NaiveDate,
    pub remind: bool,
}

impl Regimen {
    pub fn next_due(&self) -> NaiveDate {
        self.last_bought + Duration::days(self.pack_days as i64)
    }
    /// Days until the pack runs out (negative = already out).
    pub fn days_left(&self, today: NaiveDate) -> i64 {
        (self.next_due() - today).num_days()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Customer {
    pub id: Id,
    pub first_name: String,
    pub last_name: String,
    pub gender: Gender,
    pub phone: String,
    pub telegram: Option<String>,
    pub birth_date: Option<NaiveDate>,
    pub district: String,
    pub home_branch: Id,
    pub owner_id: Option<Id>,
    pub tags: Vec<String>,
    pub tier: Tier,
    /// Loyalty balance (1 point = 1 so'm of cashback).
    pub points: i64,
    pub card_no: String,
    pub source: Source,
    pub consent: Consent,
    pub regimens: Vec<Regimen>,
    pub allergies: Vec<String>,
    /// Employer, when the customer is covered by a corporate deal.
    pub company_id: Option<Id>,
    pub created: NaiveDate,
    pub lang: Lang,
    pub notes: String,
    pub nps: Option<u8>,
    // Aggregates kept in step with purchases by Db::add_purchase.
    pub total_spent: Money,
    pub orders: u32,
    pub first_purchase: Option<NaiveDate>,
    pub last_purchase: Option<NaiveDate>,
    pub archived: bool,
    #[serde(default)]
    pub referred_by: Option<Id>,
}

impl Customer {
    pub fn name(&self) -> String {
        format!("{} {}", self.first_name, self.last_name)
    }
    pub fn initials(&self) -> String {
        let a = self.first_name.chars().next().unwrap_or(' ');
        let b = self.last_name.chars().next().unwrap_or(' ');
        format!("{a}{b}").trim().to_uppercase()
    }
    pub fn age(&self, today: NaiveDate) -> Option<i32> {
        let b = self.birth_date?;
        let mut age = today.year() - b.year();
        if (today.month(), today.day()) < (b.month(), b.day()) {
            age -= 1;
        }
        Some(age)
    }
    /// Days until the next birthday (0 = today).
    pub fn birthday_in(&self, today: NaiveDate) -> Option<i64> {
        let b = self.birth_date?;
        let this_year = NaiveDate::from_ymd_opt(today.year(), b.month(), b.day().min(28)).unwrap_or(today);
        let next = if this_year < today {
            NaiveDate::from_ymd_opt(today.year() + 1, b.month(), b.day().min(28)).unwrap_or(today)
        } else {
            this_year
        };
        Some((next - today).num_days())
    }
    pub fn days_since_last(&self, today: NaiveDate) -> Option<i64> {
        self.last_purchase.map(|d| (today - d).num_days())
    }
    pub fn avg_basket(&self) -> Money {
        if self.orders == 0 {
            0
        } else {
            self.total_spent / self.orders as Money
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LineItem {
    pub product_id: Id,
    pub qty: u32,
    pub price: Money,
    pub discount_pct: u8,
}

impl LineItem {
    pub fn total(&self) -> Money {
        self.price * self.qty as Money * (100 - self.discount_pct.min(100) as Money) / 100
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Purchase {
    pub id: Id,
    pub customer_id: Id,
    pub branch_id: Id,
    pub at: NaiveDateTime,
    pub items: Vec<LineItem>,
    pub total: Money,
    pub points_earned: i64,
    pub points_used: i64,
    pub channel: SaleChannel,
    pub cashier_id: Option<Id>,
}

// ---------------------------------------------------------------- companies (B2B)

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ContactPerson {
    pub name: String,
    pub position: String,
    pub phone: String,
    pub telegram: Option<String>,
    pub primary: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Company {
    pub id: Id,
    pub name: String,
    pub kind: OrgKind,
    /// STIR (tax id).
    pub tin: String,
    pub district: String,
    pub address: String,
    pub phone: String,
    pub email: String,
    pub owner_id: Option<Id>,
    pub credit_limit: Money,
    pub terms_days: u16,
    /// What they owe us now.
    pub receivable: Money,
    pub tags: Vec<String>,
    pub created: NaiveDate,
    pub employees: u32,
    pub contacts: Vec<ContactPerson>,
    pub notes: String,
    /// Account health 0-100 (payments, activity, growth).
    pub health: u8,
    #[serde(default)]
    pub daybook_id: Option<i64>,
}

// ---------------------------------------------------------------- sales

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Stage {
    pub id: Id,
    pub name: String,
    /// Default win probability in percent.
    pub probability: u8,
    /// A deal sitting here longer than this many days is "rotting".
    pub rot_days: u16,
    pub hue: u16,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Pipeline {
    pub id: Id,
    pub name: String,
    pub icon: String,
    pub stages: Vec<Stage>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Deal {
    pub id: Id,
    pub title: String,
    pub pipeline_id: Id,
    pub stage_id: Id,
    pub company_id: Option<Id>,
    pub customer_id: Option<Id>,
    pub value: Money,
    pub owner_id: Id,
    pub created: NaiveDateTime,
    pub stage_since: NaiveDateTime,
    pub last_activity: NaiveDateTime,
    pub expected_close: NaiveDate,
    pub status: DealStatus,
    pub lost_reason: Option<String>,
    pub lines: Vec<LineItem>,
    pub source: Source,
    pub tags: Vec<String>,
    pub next_step: String,
    pub closed_at: Option<NaiveDateTime>,
    pub priority: Priority,
}

impl Deal {
    /// Days since the deal entered its current stage.
    pub fn days_in_stage(&self, now: NaiveDateTime) -> i64 {
        (now - self.stage_since).num_days()
    }
    pub fn idle_days(&self, now: NaiveDateTime) -> i64 {
        (now - self.last_activity).num_days()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Lead {
    pub id: Id,
    pub name: String,
    pub phone: String,
    pub channel: Channel,
    pub message: String,
    pub interest: String,
    pub at: NaiveDateTime,
    pub status: LeadStatus,
    pub owner_id: Option<Id>,
    /// 0-100, higher = hotter.
    pub score: u8,
    pub company_name: Option<String>,
    pub estimate: Money,
    pub converted_customer: Option<Id>,
    pub converted_deal: Option<Id>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Activity {
    pub id: Id,
    pub kind: ActivityKind,
    pub title: String,
    pub notes: String,
    pub due: NaiveDateTime,
    pub done: bool,
    pub done_at: Option<NaiveDateTime>,
    pub owner_id: Id,
    pub customer_id: Option<Id>,
    pub company_id: Option<Id>,
    pub deal_id: Option<Id>,
    pub ticket_id: Option<Id>,
    pub priority: Priority,
    pub outcome: Option<String>,
    pub duration_min: u16,
    /// Id of the matching task in Daybook, once pushed there.
    pub daybook_task: Option<i64>,
}

// ---------------------------------------------------------------- inbox

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Message {
    pub id: Id,
    pub inbound: bool,
    pub author_id: Option<Id>,
    pub text: String,
    pub at: NaiveDateTime,
    pub kind: MsgKind,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Conversation {
    pub id: Id,
    pub channel: Channel,
    pub customer_id: Option<Id>,
    pub lead_id: Option<Id>,
    /// Display name when not linked to a customer.
    pub title: String,
    /// Phone number or @username.
    pub handle: String,
    pub assigned_to: Option<Id>,
    pub status: ConvStatus,
    pub unread: u16,
    pub messages: Vec<Message>,
    pub tags: Vec<String>,
    pub starred: bool,
}

impl Conversation {
    pub fn last_at(&self) -> Option<NaiveDateTime> {
        self.messages.last().map(|m| m.at)
    }
    pub fn last_text(&self) -> &str {
        self.messages.last().map(|m| m.text.as_str()).unwrap_or("")
    }
    /// Minutes the customer has been waiting for our reply (None = we replied last).
    pub fn waiting_min(&self, now: NaiveDateTime) -> Option<i64> {
        let last = self.messages.iter().rev().find(|m| m.kind != MsgKind::Note && m.kind != MsgKind::System)?;
        if last.inbound {
            Some((now - last.at).num_minutes())
        } else {
            None
        }
    }
}

// ---------------------------------------------------------------- marketing

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Rule {
    pub field: Field,
    pub op: Op,
    pub value: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Segment {
    pub id: Id,
    pub name: String,
    pub description: String,
    pub rules: Vec<Rule>,
    /// true = every rule must match, false = any.
    pub match_all: bool,
    pub hue: u16,
    /// Built-in segments can't be deleted.
    pub system: bool,
    pub icon: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Campaign {
    pub id: Id,
    pub name: String,
    pub channel: Channel,
    pub segment_id: Id,
    pub message: String,
    pub status: CampaignStatus,
    pub scheduled: Option<NaiveDateTime>,
    pub created: NaiveDateTime,
    pub owner_id: Id,
    pub audience: u32,
    pub sent: u32,
    pub delivered: u32,
    pub read: u32,
    pub clicked: u32,
    pub converted: u32,
    pub revenue: Money,
    pub cost: Money,
    pub bonus_points: i64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Trigger {
    Birthday { days_before: i32 },
    RefillDue { days_before: i32 },
    Inactive { days: i32 },
    AfterPurchase { days: i32 },
    FirstPurchase,
    TierUp,
    DealStage { stage_id: Id },
    NewLead,
    WaitlistArrived,
    TicketCreated,
    LowNps,
}

impl Trigger {
    pub fn key(&self) -> &'static str {
        match self {
            Trigger::Birthday { .. } => "trigger.birthday",
            Trigger::RefillDue { .. } => "trigger.refill_due",
            Trigger::Inactive { .. } => "trigger.inactive",
            Trigger::AfterPurchase { .. } => "trigger.after_purchase",
            Trigger::FirstPurchase => "trigger.first_purchase",
            Trigger::TierUp => "trigger.tier_up",
            Trigger::DealStage { .. } => "trigger.deal_stage",
            Trigger::NewLead => "trigger.new_lead",
            Trigger::WaitlistArrived => "trigger.waitlist_arrived",
            Trigger::TicketCreated => "trigger.ticket_created",
            Trigger::LowNps => "trigger.low_nps",
        }
    }
    pub fn icon(&self) -> &'static str {
        match self {
            Trigger::Birthday { .. } => "cake",
            Trigger::RefillDue { .. } => "repeat",
            Trigger::Inactive { .. } => "hourglass",
            Trigger::AfterPurchase { .. } => "shopping-bag",
            Trigger::FirstPurchase => "sparkles",
            Trigger::TierUp => "crown",
            Trigger::DealStage { .. } => "square-kanban",
            Trigger::NewLead => "magnet",
            Trigger::WaitlistArrived => "package-check",
            Trigger::TicketCreated => "life-buoy",
            Trigger::LowNps => "thumbs-down",
        }
    }
    /// The number shown in the trigger ("3 days before"), if it has one.
    pub fn days(&self) -> Option<i32> {
        match self {
            Trigger::Birthday { days_before } | Trigger::RefillDue { days_before } => Some(*days_before),
            Trigger::Inactive { days } | Trigger::AfterPurchase { days } => Some(*days),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Action {
    SendTelegram { text: String },
    SendSms { text: String },
    CreateTask { title: String, role: Role, due_days: i32 },
    AddTag { tag: String },
    GiveBonus { points: i64 },
    NotifyManager { text: String },
    MoveDeal { stage_id: Id },
    Wait { days: i32 },
    ReserveStock,
}

impl Action {
    pub fn key(&self) -> &'static str {
        match self {
            Action::SendTelegram { .. } => "action.send_telegram",
            Action::SendSms { .. } => "action.send_sms",
            Action::CreateTask { .. } => "action.create_task",
            Action::AddTag { .. } => "action.add_tag",
            Action::GiveBonus { .. } => "action.give_bonus",
            Action::NotifyManager { .. } => "action.notify_manager",
            Action::MoveDeal { .. } => "action.move_deal",
            Action::Wait { .. } => "action.wait",
            Action::ReserveStock => "action.reserve_stock",
        }
    }
    pub fn icon(&self) -> &'static str {
        match self {
            Action::SendTelegram { .. } => "send",
            Action::SendSms { .. } => "message-square-text",
            Action::CreateTask { .. } => "square-check",
            Action::AddTag { .. } => "tag",
            Action::GiveBonus { .. } => "gift",
            Action::NotifyManager { .. } => "bell-ring",
            Action::MoveDeal { .. } => "arrow-right",
            Action::Wait { .. } => "timer",
            Action::ReserveStock => "package-check",
        }
    }
    /// The free text of the action (message, task title, tag), if any.
    pub fn text(&self) -> Option<&str> {
        match self {
            Action::SendTelegram { text } | Action::SendSms { text } | Action::NotifyManager { text } => Some(text),
            Action::CreateTask { title, .. } => Some(title),
            Action::AddTag { tag } => Some(tag),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Automation {
    pub id: Id,
    pub name: String,
    pub description: String,
    pub trigger: Trigger,
    pub conditions: Vec<Rule>,
    pub actions: Vec<Action>,
    pub enabled: bool,
    pub runs: u32,
    pub conversions: u32,
    pub last_run: Option<NaiveDateTime>,
    /// Which recipe it came from, if any.
    pub recipe: Option<String>,
    pub created: NaiveDate,
}

// ---------------------------------------------------------------- catalogue and service

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BranchStock {
    pub branch_id: Id,
    pub qty: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Product {
    pub id: Id,
    /// Display name: generic + strength + pack.
    pub name: String,
    pub generic: String,
    pub form: String,
    pub maker: String,
    pub category: ProductCategory,
    /// Prescription-only: never in broadcasts, never earns bonus when the company says so.
    pub rx: bool,
    pub price: Money,
    pub stock: Vec<BranchStock>,
    /// Nearest batch expiry.
    pub expiry: NaiveDate,
    /// Excluded from the loyalty programme.
    pub no_bonus: bool,
    pub barcode: String,
    #[serde(default)]
    pub daybook_id: Option<i64>,
}

impl Product {
    pub fn total_stock(&self) -> u32 {
        self.stock.iter().map(|s| s.qty).sum()
    }
    pub fn stock_at(&self, branch_id: Id) -> u32 {
        self.stock.iter().find(|s| s.branch_id == branch_id).map(|s| s.qty).unwrap_or(0)
    }
}

/// Defektura: a customer asked for something we didn't have.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct WaitItem {
    pub id: Id,
    pub customer_id: Id,
    pub product_id: Option<Id>,
    pub product_name: String,
    pub branch_id: Id,
    pub qty: u32,
    pub at: NaiveDateTime,
    pub status: WaitStatus,
    pub eta: Option<NaiveDate>,
    pub note: String,
    pub notified_at: Option<NaiveDateTime>,
    /// What the sale would be worth.
    pub value: Money,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Comment {
    pub at: NaiveDateTime,
    pub author_id: Option<Id>,
    pub text: String,
    /// Internal notes never reach the customer.
    pub internal: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Ticket {
    pub id: Id,
    pub number: String,
    pub kind: TicketKind,
    pub subject: String,
    pub description: String,
    pub customer_id: Option<Id>,
    pub product_id: Option<Id>,
    pub batch: Option<String>,
    pub branch_id: Option<Id>,
    pub priority: Priority,
    pub status: TicketStatus,
    pub created: NaiveDateTime,
    /// SLA deadline.
    pub due: NaiveDateTime,
    pub assigned_to: Option<Id>,
    pub resolved: Option<NaiveDateTime>,
    pub csat: Option<u8>,
    pub comments: Vec<Comment>,
    /// Adverse reactions: reported to the pharmacovigilance regulator.
    pub reported_to_regulator: bool,
}

impl Ticket {
    pub fn is_open(&self) -> bool {
        !matches!(self.status, TicketStatus::Resolved | TicketStatus::Closed)
    }
    pub fn breached(&self, now: NaiveDateTime) -> bool {
        self.is_open() && now > self.due
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Quote {
    pub id: Id,
    pub number: String,
    pub company_id: Id,
    pub deal_id: Option<Id>,
    pub lines: Vec<LineItem>,
    pub status: QuoteStatus,
    pub issued: NaiveDate,
    pub valid_until: NaiveDate,
    pub vat_pct: u8,
    pub notes: String,
    pub owner_id: Id,
    pub paid_on: Option<NaiveDate>,
}

impl Quote {
    pub fn subtotal(&self) -> Money {
        self.lines.iter().map(LineItem::total).sum()
    }
    pub fn vat(&self) -> Money {
        self.subtotal() * self.vat_pct as Money / 100
    }
    pub fn total(&self) -> Money {
        self.subtotal() + self.vat()
    }
}

// ---------------------------------------------------------------- loyalty, goals, notes, audit

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LoyaltyTx {
    pub id: Id,
    pub customer_id: Id,
    pub at: NaiveDateTime,
    /// Positive = earned, negative = spent or expired.
    pub points: i64,
    pub kind: TxKind,
    pub note: String,
    pub branch_id: Option<Id>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TierRule {
    pub tier: Tier,
    /// Lifetime spend needed for the tier.
    pub min_spent: Money,
    pub cashback_pct: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LoyaltySettings {
    pub enabled: bool,
    pub tiers: Vec<TierRule>,
    pub welcome_bonus: i64,
    pub birthday_bonus: i64,
    pub referral_bonus: i64,
    /// Points expire after this many days without a purchase.
    pub expiry_days: u16,
    /// Prescription-only medicines earn no cashback.
    pub exclude_rx: bool,
    /// At most this share of a receipt can be paid with points.
    pub max_redeem_pct: u8,
}

impl Default for LoyaltySettings {
    fn default() -> Self {
        LoyaltySettings {
            enabled: true,
            tiers: vec![
                TierRule { tier: Tier::Bronze, min_spent: 0, cashback_pct: 1.0 },
                TierRule { tier: Tier::Silver, min_spent: 1_200_000, cashback_pct: 2.0 },
                TierRule { tier: Tier::Gold, min_spent: 3_000_000, cashback_pct: 3.0 },
                TierRule { tier: Tier::Platinum, min_spent: 6_000_000, cashback_pct: 5.0 },
            ],
            welcome_bonus: 10_000,
            birthday_bonus: 25_000,
            referral_bonus: 15_000,
            expiry_days: 365,
            exclude_rx: true,
            max_redeem_pct: 30,
        }
    }
}

impl LoyaltySettings {
    pub fn tier_for(&self, spent: Money) -> Tier {
        let mut tier = Tier::Bronze;
        for r in &self.tiers {
            if spent >= r.min_spent {
                tier = r.tier;
            }
        }
        tier
    }
    pub fn cashback(&self, tier: Tier) -> f32 {
        self.tiers.iter().find(|r| r.tier == tier).map(|r| r.cashback_pct).unwrap_or(1.0)
    }
    /// The next tier and how much more spend it needs.
    pub fn next_tier(&self, spent: Money) -> Option<(Tier, Money)> {
        self.tiers.iter().find(|r| r.min_spent > spent).map(|r| (r.tier, r.min_spent - spent))
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Goal {
    pub id: Id,
    pub staff_id: Option<Id>,
    pub branch_id: Option<Id>,
    pub metric: Metric,
    pub target: i64,
    /// "2026-11"
    pub month: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Note {
    pub id: Id,
    pub at: NaiveDateTime,
    pub author_id: Option<Id>,
    pub text: String,
    pub customer_id: Option<Id>,
    pub company_id: Option<Id>,
    pub deal_id: Option<Id>,
    pub pinned: bool,
    /// Health-related: hidden in privacy mode and every view is audited.
    pub sensitive: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AuditEntry {
    pub id: Id,
    pub at: NaiveDateTime,
    pub actor_id: Option<Id>,
    pub text: String,
    pub sensitive: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Notification {
    pub id: Id,
    pub at: NaiveDateTime,
    pub kind: NotifKind,
    pub title: String,
    pub body: String,
    pub read: bool,
    /// App route to open, e.g. "/deals/12".
    pub route: String,
}

// ---------------------------------------------------------------- settings

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct SyncCounts {
    pub branches: u32,
    pub staff: u32,
    pub products: u32,
    pub customers: u32,
    pub defektura: u32,
    pub tasks_pushed: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DaybookLink {
    /// e.g. "https://144.91.81.29.nip.io"
    pub server: String,
    pub connected: bool,
    pub company_name: String,
    pub company_id: Option<i64>,
    pub user_name: String,
    pub access: Option<String>,
    /// The `owner_refresh` cookie value.
    pub refresh: Option<String>,
    pub last_sync: Option<NaiveDateTime>,
    pub pulled: SyncCounts,
    pub server_version: Option<String>,
}

impl Default for DaybookLink {
    fn default() -> Self {
        DaybookLink {
            server: "https://144.91.81.29.nip.io".into(),
            connected: false,
            company_name: String::new(),
            company_id: None,
            user_name: String::new(),
            access: None,
            refresh: None,
            last_sync: None,
            pulled: SyncCounts::default(),
            server_version: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AiSettings {
    pub enabled: bool,
    /// claude-haiku-5-5 by default; Sonnet only when the owner picks it.
    pub model: String,
    pub monthly_cap_usd: f32,
    pub spent_usd: f32,
    pub requests: u32,
}

impl Default for AiSettings {
    fn default() -> Self {
        AiSettings { enabled: true, model: "claude-haiku-5-5".into(), monthly_cap_usd: 20.0, spent_usd: 3.42, requests: 1840 }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Settings {
    pub lang: Lang,
    pub theme: Theme,
    pub company_name: String,
    /// The signed-in staff member.
    pub me: Id,
    pub daybook: DaybookLink,
    pub ai: AiSettings,
    pub loyalty: LoyaltySettings,
    /// Remind this many days before a regular medicine runs out.
    pub refill_lead_days: u16,
    /// No purchase for this many days = at risk.
    pub inactive_days: u16,
    /// Default ticket SLA in hours (adverse reactions always get 4 h).
    pub sla_hours: u16,
    pub compact: bool,
    /// Privacy mode: mask health data and phone numbers on screen.
    pub privacy_mode: bool,
    pub onboarded: bool,
    pub sidebar_collapsed: bool,
}
