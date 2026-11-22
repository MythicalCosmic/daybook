//! Prints stable record ids of the demo company (for screenshot scripts and demo links).
use chrono::NaiveDate;
use daybook_crm_core::{demo, model::DealStatus};

#[test]
fn print_demo_ids() {
    let now = NaiveDate::from_ymd_opt(2026, 11, 23).unwrap().and_hms_opt(10, 0, 0).unwrap();
    let db = demo::generate(now);
    let vip = db.customers.iter().find(|c| c.first_name == "Gulchehra" && c.last_name == "Karimova").map(|c| c.id);
    let deal = db.deals.iter().find(|d| d.status == DealStatus::Open && !d.lines.is_empty()).map(|d| d.id);
    eprintln!(
        "IDS customer={:?} company={} deal={:?} quote={} ticket={} campaign={} conversation={}",
        vip,
        db.companies[0].id,
        deal,
        db.quotes[1].id,
        db.tickets[0].id,
        db.campaigns[0].id,
        db.conversations[0].id
    );
}
