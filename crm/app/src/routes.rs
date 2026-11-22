#![allow(unreachable_code)]
//! Every screen of the app. The `Shell` layout wraps them all (sidebar, top bar, tab bar).

use dioxus::prelude::*;

use crate::pages::automations::Automations;
use crate::pages::campaigns::{CampaignDetail, Campaigns};
use crate::pages::companies::{Companies, CompanyDetail};
use crate::pages::contacts::{ContactDetail, Contacts};
use crate::pages::deals::{DealDetail, Deals};
use crate::pages::home::Home;
use crate::pages::inbox::{Inbox, InboxThread};
use crate::pages::leads::Leads;
use crate::pages::loyalty::Loyalty;
use crate::pages::products::Products;
use crate::pages::quotes::{QuoteDetail, Quotes};
use crate::pages::refills::Refills;
use crate::pages::reports::Reports;
use crate::pages::segments::Segments;
use crate::pages::settings::{DaybookConnect, SettingsPage};
use crate::pages::tasks::{Calendar, Tasks};
use crate::pages::team::{Goals, Team};
use crate::pages::tickets::{TicketDetail, Tickets};
use crate::pages::waitlist::Waitlist;
use crate::shell::{More, NotFound, Shell};

#[derive(Routable, Clone, PartialEq, Debug)]
#[rustfmt::skip]
#[allow(clippy::enum_variant_names)]
pub enum Route {
    #[layout(Shell)]
        #[route("/")]
        Home {},
        #[route("/inbox")]
        Inbox {},
        #[route("/inbox/:id")]
        InboxThread { id: u32 },
        #[route("/tasks")]
        Tasks {},
        #[route("/calendar")]
        Calendar {},
        #[route("/contacts")]
        Contacts {},
        #[route("/contacts/:id")]
        ContactDetail { id: u32 },
        #[route("/companies")]
        Companies {},
        #[route("/companies/:id")]
        CompanyDetail { id: u32 },
        #[route("/leads")]
        Leads {},
        #[route("/segments")]
        Segments {},
        #[route("/deals")]
        Deals {},
        #[route("/deals/:id")]
        DealDetail { id: u32 },
        #[route("/quotes")]
        Quotes {},
        #[route("/quotes/:id")]
        QuoteDetail { id: u32 },
        #[route("/products")]
        Products {},
        #[route("/campaigns")]
        Campaigns {},
        #[route("/campaigns/:id")]
        CampaignDetail { id: u32 },
        #[route("/automations")]
        Automations {},
        #[route("/loyalty")]
        Loyalty {},
        #[route("/refills")]
        Refills {},
        #[route("/waitlist")]
        Waitlist {},
        #[route("/tickets")]
        Tickets {},
        #[route("/tickets/:id")]
        TicketDetail { id: u32 },
        #[route("/reports")]
        Reports {},
        #[route("/goals")]
        Goals {},
        #[route("/team")]
        Team {},
        #[route("/settings")]
        SettingsPage {},
        #[route("/settings/daybook")]
        DaybookConnect {},
        #[route("/more")]
        More {},
        #[route("/:..segments")]
        NotFound { segments: Vec<String> },
}

impl Route {
    /// The navigation section a screen belongs to (for highlighting the sidebar).
    pub fn section(&self) -> &'static str {
        match self {
            Route::Home {} => "home",
            Route::Inbox {} | Route::InboxThread { .. } => "inbox",
            Route::Tasks {} => "tasks",
            Route::Calendar {} => "calendar",
            Route::Contacts {} | Route::ContactDetail { .. } => "contacts",
            Route::Companies {} | Route::CompanyDetail { .. } => "companies",
            Route::Leads {} => "leads",
            Route::Segments {} => "segments",
            Route::Deals {} | Route::DealDetail { .. } => "deals",
            Route::Quotes {} | Route::QuoteDetail { .. } => "quotes",
            Route::Products {} => "products",
            Route::Campaigns {} | Route::CampaignDetail { .. } => "campaigns",
            Route::Automations {} => "automations",
            Route::Loyalty {} => "loyalty",
            Route::Refills {} => "refills",
            Route::Waitlist {} => "waitlist",
            Route::Tickets {} | Route::TicketDetail { .. } => "tickets",
            Route::Reports {} => "reports",
            Route::Goals {} => "goals",
            Route::Team {} => "team",
            Route::SettingsPage {} | Route::DaybookConnect {} => "settings",
            Route::More {} => "more",
            Route::NotFound { .. } => "",
        }
    }
}
