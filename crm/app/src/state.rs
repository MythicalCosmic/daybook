//! App-wide state: the database signal, transient UI state, time, translations and helpers
//! every screen uses. Read data with `DB.read()`, change it with `mutate(|db| ...)` (which saves).

use std::str::FromStr;
use std::sync::OnceLock;

use chrono::{NaiveDate, NaiveDateTime};
use crm::i18n::{pick, Catalog, Lang};
use crm::Db;
use dioxus::prelude::*;

use crate::routes::Route;

pub static DB: GlobalSignal<Db> = Signal::global(crate::storage::load);
pub static UI: GlobalSignal<Ui> = Signal::global(Ui::default);

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Ui {
    pub palette: bool,
    pub notifications: bool,
    pub quick_add: Option<QuickAdd>,
    pub toasts: Vec<Toast>,
    pub seq: u32,
    /// A filter passed along with a link, e.g. "rfm=cant_lose" from "/contacts?rfm=cant_lose".
    pub hint: Option<String>,
    pub ai_panel: bool,
    pub sidebar_open: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QuickAdd {
    Customer,
    Deal,
    Task,
    Lead,
    Ticket,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Toast {
    pub id: u32,
    pub text: String,
    pub icon: &'static str,
    pub tone: &'static str,
}

pub fn now() -> NaiveDateTime {
    chrono::Local::now().naive_local()
}

pub fn today() -> NaiveDate {
    now().date()
}

/// The interface language (subscribes the calling component to the database).
pub fn lang() -> Lang {
    DB.read().settings.lang
}

pub fn catalog() -> &'static Catalog {
    static C: OnceLock<Catalog> = OnceLock::new();
    C.get_or_init(|| Catalog::new(crate::i18n::TABLES))
}

/// Translated text for a key from any registered table.
pub fn t(key: &str) -> String {
    catalog().get(lang(), key).into_owned()
}

/// Inline translation for one-off text: `tr("Saqlash", "Сохранить", "Save")`.
pub fn tr(uz: &'static str, ru: &'static str, en: &'static str) -> String {
    pick(lang(), uz, ru, en).into_owned()
}

/// Uzbek text built at runtime (names, numbers), shown in Cyrillic when that's the language.
pub fn uz(s: impl AsRef<str>) -> String {
    if lang() == Lang::UzCyrl {
        crm::i18n::to_cyrillic(s.as_ref())
    } else {
        s.as_ref().to_string()
    }
}

/// Changes the database and saves it.
pub fn mutate(f: impl FnOnce(&mut Db)) {
    {
        let mut db = DB.write();
        f(&mut db);
    }
    crate::storage::save(&DB.peek());
}

/// Shows a short message at the bottom of the screen.
pub fn toast(text: impl Into<String>, icon: &'static str, tone: &'static str) {
    let mut ui = UI.write();
    ui.seq += 1;
    let id = ui.seq;
    ui.toasts.push(Toast { id, text: text.into(), icon, tone });
    if ui.toasts.len() > 3 {
        ui.toasts.remove(0);
    }
}

/// Navigates to an app path such as "/deals/12" or "/contacts?rfm=at_risk".
pub fn go(target: &str) {
    let (path, query) = match target.split_once('?') {
        Some((p, q)) => (p, Some(q.to_string())),
        None => (target, None),
    };
    UI.write().hint = query;
    if let Ok(route) = Route::from_str(path) {
        navigator().push(route);
    }
}

/// Takes the filter hint passed with the last link (once).
pub fn take_hint() -> Option<String> {
    let has = UI.peek().hint.is_some();
    if has {
        UI.write().hint.take()
    } else {
        None
    }
}

/// Money in the interface language: "12 450 000 so‘m".
pub fn money(v: crm::model::Money) -> String {
    crm::fmt::money(v, lang())
}

/// Short money: "12,4 mln so‘m".
pub fn money_short(v: crm::model::Money) -> String {
    crm::fmt::money_short(v, lang())
}

/// A phone number, masked in privacy mode.
pub fn phone(raw: &str) -> String {
    if DB.read().settings.privacy_mode {
        crm::fmt::mask_phone(raw)
    } else {
        crm::fmt::phone(raw)
    }
}

/// Stable hue for an avatar from any text.
pub fn hue_of(s: &str) -> u16 {
    let mut h: u32 = 2166136261;
    for b in s.bytes() {
        h ^= b as u32;
        h = h.wrapping_mul(16777619);
    }
    (h % 360) as u16
}

/// True on the Android / iOS builds (touch-first UI tweaks).
pub const fn is_mobile_build() -> bool {
    cfg!(feature = "mobile")
}
