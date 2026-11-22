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
        use dioxus::desktop::tao::window::Icon;
        use dioxus::desktop::{Config, LogicalSize, WindowBuilder};
        const ICON_RGBA: &[u8] = include_bytes!("../assets/icons/icon-64.rgba");
        let window = WindowBuilder::new()
            .with_title("Daybook CRM")
            .with_inner_size(LogicalSize::new(1400.0, 880.0))
            .with_min_inner_size(LogicalSize::new(380.0, 600.0))
            .with_window_icon(Icon::from_rgba(ICON_RGBA.to_vec(), 64, 64).ok());
        // WebView2 keeps its cache in the user's profile, so the app also runs from Program Files.
        let data_dir = dirs::data_local_dir().unwrap_or_else(std::env::temp_dir).join("Daybook CRM").join("webview");
        let cfg = Config::new()
            .with_window(window)
            .with_menu(None)
            .with_data_directory(data_dir)
            .with_background_color((247, 243, 236, 255));
        dioxus::LaunchBuilder::new().with_cfg(cfg).launch(App);
    }
    #[cfg(not(feature = "desktop"))]
    dioxus::launch(App);
}

/// The app icon as a data URI: favicon and the iPhone home-screen icon of the web build.
const TOUCH_ICON: &str = concat!("data:image/png;base64,", include_str!("../assets/icons/icon-192.b64"));

#[component]
fn App() -> Element {
    rsx! {
        document::Title { "Daybook CRM" }
        document::Meta { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover" }
        document::Meta { name: "theme-color", content: "#f7f3ec" }
        document::Meta { name: "apple-mobile-web-app-capable", content: "yes" }
        document::Meta { name: "mobile-web-app-capable", content: "yes" }
        document::Meta { name: "apple-mobile-web-app-title", content: "Daybook CRM" }
        document::Meta { name: "apple-mobile-web-app-status-bar-style", content: "default" }
        document::Link { rel: "icon", href: TOUCH_ICON }
        document::Link { rel: "apple-touch-icon", href: TOUCH_ICON }
        style { {FONTS_CSS} }
        style { {APP_CSS} }
        Router::<routes::Route> {}
    }
}
