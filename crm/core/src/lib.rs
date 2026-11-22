//! Daybook CRM core: everything that isn't UI.
//!
//! * [`model`]: the data (customers, deals, inbox, loyalty, ...), plain serde structs.
//! * [`db`]: the in-memory database with lookups and the mutations every screen shares.
//! * [`demo`]: a deterministic pharmacy-chain demo company, generated relative to today.
//! * [`analytics`]: KPIs, RFM, refills, funnels, cohorts, forecasts and smart insights.
//! * [`fmt`]: money, dates, phones and plurals in uz / uz-Cyrillic / ru / en.
//! * [`i18n`]: languages, the shared string table and Uzbek Latin -> Cyrillic.

#[macro_use]
mod macros;

pub mod analytics;
pub mod db;
pub mod demo;
pub mod fmt;
pub mod i18n;
pub mod model;
pub mod rng;

pub use db::Db;
pub use i18n::Lang;
