//! Placeholder until this screen is built.

use crm::i18n::Entry;
use dioxus::prelude::*;

use crate::state::t;
use crate::ui::*;

#[component]
pub fn Inbox() -> Element {
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.inbox") }
            div { class: "card", Empty { icon: "inbox", title: t("common.empty") } }
        }
    }
}

#[component]
pub fn InboxThread(id: u32) -> Element {
    let _ = id;
    rsx! {
        div { class: "page",
            PageHeader { title: t("nav.inbox") }
            div { class: "card", Empty { icon: "inbox", title: t("common.empty") } }
        }
    }
}

pub const STRINGS: &[Entry] = &[];
