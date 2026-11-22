/// A small enum with a stable list of variants and an i18n key per variant.
///
/// `keyed_enum!(Tier, "tier", { Bronze => "bronze", Gold => "gold" });` gives
/// `Tier::ALL`, `Tier::Gold.key() == "tier.gold"` and `Tier::Gold.slug() == "gold"`.
macro_rules! keyed_enum {
    ($(#[$m:meta])* $name:ident, $prefix:literal, { $($var:ident => $key:literal),+ $(,)? }) => {
        $(#[$m])*
        #[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, serde::Serialize, serde::Deserialize)]
        pub enum $name { $($var),+ }

        impl $name {
            pub const ALL: &'static [$name] = &[$($name::$var),+];

            /// Translation key, e.g. `"tier.gold"`.
            pub fn key(self) -> &'static str {
                match self { $($name::$var => concat!($prefix, ".", $key)),+ }
            }

            /// Stable short name, e.g. `"gold"` (used in URLs and CSS classes).
            pub fn slug(self) -> &'static str {
                match self { $($name::$var => $key),+ }
            }

            pub fn from_slug(s: &str) -> Option<$name> {
                match s { $($key => Some($name::$var),)+ _ => None }
            }
        }
    };
}
