//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Campaigns() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.campaigns") }
            div { class: "card", Empty { icon: "megaphone", title: t("common.empty") } }
        }
    }
}

#[component]
pub fn CampaignDetail(id: u32) -> Element {
    let _ = id;
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.campaigns") }
            div { class: "card", Empty { icon: "megaphone", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
