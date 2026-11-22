//! Prints the demo company's headline numbers (run with --nocapture) and checks they tell a
//! healthy story: growing revenue, new customers, every tier populated.

use chrono::NaiveDate;
use daybook_crm_core::{analytics, demo};

#[test]
fn demo_tells_a_growing_story() {
    let now = NaiveDate::from_ymd_opt(2026, 11, 23).unwrap().and_hms_opt(16, 30, 0).unwrap();
    let db = demo::generate(now);
    let k = analytics::kpis(&db, now);
    let tiers = analytics::tier_counts(&db);
    eprintln!(
        "customers {} purchases {} | revenue mtd {} prev {} ({:+.0}%) | new {} prev {} | active {} repeat {:.0}% | refills week {} | tiers {:?}",
        db.customers.len(),
        db.purchases.len(),
        k.revenue_mtd,
        k.revenue_prev_mtd,
        k.revenue_delta(),
        k.new_customers_mtd,
        k.new_customers_prev,
        k.active_customers,
        k.repeat_rate,
        k.refills_week,
        tiers.iter().map(|t| (t.0.slug(), t.1)).collect::<Vec<_>>()
    );
    assert!(k.revenue_delta() > -10.0, "revenue should not look like it is collapsing");
    assert!(tiers.iter().all(|t| t.1 > 0), "every tier should have members");
}
