//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Goals() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.goals") }
            div { class: "card", Empty { icon: "trophy", title: t("common.empty") } }
        }
    }
}

#[component]
pub fn Team() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.team") }
            div { class: "card", Empty { icon: "users-round", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
