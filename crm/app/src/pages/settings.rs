//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn SettingsPage() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.settings") }
            div { class: "card", Empty { icon: "settings", title: t("common.empty") } }
        }
    }
}

#[component]
pub fn DaybookConnect() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.daybook") }
            div { class: "card", Empty { icon: "link-2", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
