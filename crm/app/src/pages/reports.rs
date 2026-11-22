//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Reports() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.reports") }
            div { class: "card", Empty { icon: "chart-column", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
