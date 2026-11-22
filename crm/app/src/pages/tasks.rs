//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Tasks() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.tasks") }
            div { class: "card", Empty { icon: "square-check", title: t("common.empty") } }
        }
    }
}

#[component]
pub fn Calendar() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.calendar") }
            div { class: "card", Empty { icon: "calendar-days", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
