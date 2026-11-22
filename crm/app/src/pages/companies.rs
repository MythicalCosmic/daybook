//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Companies() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.companies") }
            div { class: "card", Empty { icon: "building-2", title: t("common.empty") } }
        }
    }
}

#[component]
pub fn CompanyDetail(id: u32) -> Element {
    let _ = id;
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.companies") }
            div { class: "card", Empty { icon: "building-2", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
