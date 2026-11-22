//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Refills() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.refills") }
            div { class: "card", Empty { icon: "repeat", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
