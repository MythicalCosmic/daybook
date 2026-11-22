//! The UI kit. Pages combine these components with the CSS classes in assets/app.css.

mod charts;
mod icons_gen;
mod kit;

pub use charts::*;
pub use icons_gen::{icon_svg, ICON_NAMES};
pub use kit::*;
