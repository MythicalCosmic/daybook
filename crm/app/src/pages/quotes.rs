//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Quotes() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.quotes") }
            div { class: "card", Empty { icon: "file-text", title: t("common.empty") } }
        }
    }
}

#[component]
pub fn QuoteDetail(id: u32) -> Element {
    let _ = id;
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.quotes") }
            div { class: "card", Empty { icon: "file-text", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
