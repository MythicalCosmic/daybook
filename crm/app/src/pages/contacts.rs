//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Contacts() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.contacts") }
            div { class: "card", Empty { icon: "users", title: t("common.empty") } }
        }
    }
}

#[component]
pub fn ContactDetail(id: u32) -> Element {
    let _ = id;
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.contacts") }
            div { class: "card", Empty { icon: "user", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
