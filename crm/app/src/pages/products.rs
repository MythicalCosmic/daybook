//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Products() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.products") }
            div { class: "card", Empty { icon: "pill", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
