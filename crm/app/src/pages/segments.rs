//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Segments() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.segments") }
            div { class: "card", Empty { icon: "layers", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
