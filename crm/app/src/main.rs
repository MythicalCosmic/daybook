//! Daybook CRM: one Rust codebase for Windows, macOS, Linux, Android, iPhone and the web.
#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

mod daybook;
mod i18n;
mod overlays;
mod pages;
mod routes;
mod shell;
mod state;
mod storage;
mod ui;

use dioxus::prelude::*;

/// The design system and the bundled fonts, inlined so the app works fully offline.
pub const APP_CSS: &str = include_str!("../assets/app.css");
pub const FONTS_CSS: &str = include_str!("../assets/fonts.css");

fn main() {
    storage::capture_url();
    #[cfg(feature = "desktop")]
    {
        use dioxus::desktop::{Config, LogicalSize, WindowBuilder};
        let window = WindowBuilder::new()
            .with_title("Daybook CRM")
            .with_inner_size(LogicalSize::new(1400.0, 880.0))
            .with_min_inner_size(LogicalSize::new(380.0, 600.0));
        let cfg = Config::new().with_window(window).with_menu(None).with_background_color((247, 243, 236, 255));
        dioxus::LaunchBuilder::new().with_cfg(cfg).launch(App);
    }
    #[cfg(not(feature = "desktop"))]
    dioxus::launch(App);
}

#[component]
fn App() -> Element {
    rsx! {
        document::Title { "Daybook CRM" }
        document::Meta { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover" }
        document::Meta { name: "theme-color", content: "#f7f3ec" }
        style { {FONTS_CSS} }
        style { {APP_CSS} }
        Router::<routes::Route> {}
    }
}
