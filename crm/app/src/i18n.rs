//! Every translation table in the app. Each screen keeps its strings next to its code
//! (`pub const STRINGS`) and is listed here once.

use crm::i18n::Entry;

use crate::pages;

pub static TABLES: &[&[Entry]] = &[
    crm::i18n::CORE,
    crm::analytics::STRINGS,
    crate::shell::STRINGS,
    crate::overlays::STRINGS,
    crate::assistant::STRINGS,
    pages::home::STRINGS,
    pages::inbox::STRINGS,
    pages::tasks::STRINGS,
    pages::contacts::STRINGS,
    pages::companies::STRINGS,
    pages::leads::STRINGS,
    pages::segments::STRINGS,
    pages::deals::STRINGS,
    pages::quotes::STRINGS,
    pages::products::STRINGS,
    pages::campaigns::STRINGS,
    pages::automations::STRINGS,
    pages::loyalty::STRINGS,
    pages::refills::STRINGS,
    pages::waitlist::STRINGS,
    pages::tickets::STRINGS,
    pages::reports::STRINGS,
    pages::team::STRINGS,
    pages::settings::STRINGS,
];

#[cfg(test)]
mod tests {
    #[test]
    fn no_duplicate_keys() {
        let c = crm::i18n::Catalog::new(super::TABLES);
        assert!(c.duplicates().is_empty(), "duplicate translation keys: {:?}", c.duplicates());
    }
}
