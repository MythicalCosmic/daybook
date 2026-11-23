//! Daybook CRM: one Rust codebase for Windows, macOS, Linux, Android, iPhone and the web.
#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

mod assistant;
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
        // Opens maximized, and the restored size fits the screen as well: 1400×880 is taller
        // than a 1080p laptop at 125% scaling (816 usable), so its bottom went under the taskbar.
        let (size, position) = desktop_frame::restored(1400.0, 880.0);
        let mut window = WindowBuilder::new()
            .with_title("Daybook CRM")
            .with_inner_size(size)
            .with_min_inner_size(LogicalSize::new(380.0, 600.0))
            .with_maximized(true)
            .with_window_icon(Icon::from_rgba(ICON_RGBA.to_vec(), 64, 64).ok());
        if let Some(position) = position {
            window = window.with_position(position);
        }
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
    // The window builder asks for maximized too; this keeps it so if placing the window undid it.
    #[cfg(feature = "desktop")]
    use_hook(|| dioxus::desktop::window().set_maximized(true));
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

/// Where the desktop window goes when it is not maximized.
#[cfg(feature = "desktop")]
mod desktop_frame {
    use dioxus::desktop::tao::dpi::{LogicalPosition, LogicalSize};

    /// The design size, shrunk to fit the usable screen and centred on it.
    pub fn restored(width: f64, height: f64) -> (LogicalSize<f64>, Option<LogicalPosition<f64>>) {
        let Some((x, y, w, h)) = work_area() else {
            return (LogicalSize::new(width, height), None);
        };
        // Title bar and resize borders, plus a margin all round.
        const CHROME_W: f64 = 16.0;
        const CHROME_H: f64 = 40.0;
        const MARGIN: f64 = 24.0;
        let inner_w = width.min(w - CHROME_W - 2.0 * MARGIN).max(380.0);
        let inner_h = height.min(h - CHROME_H - 2.0 * MARGIN).max(600.0);
        let left = x + ((w - inner_w - CHROME_W) / 2.0).max(0.0);
        let top = y + ((h - inner_h - CHROME_H) / 2.0).max(0.0);
        (LogicalSize::new(inner_w, inner_h), Some(LogicalPosition::new(left, top)))
    }

    /// The primary screen without the taskbar, in logical pixels: (left, top, width, height).
    #[cfg(target_os = "windows")]
    fn work_area() -> Option<(f64, f64, f64, f64)> {
        #[repr(C)]
        struct Rect {
            left: i32,
            top: i32,
            right: i32,
            bottom: i32,
        }
        #[link(name = "user32")]
        unsafe extern "system" {
            fn SystemParametersInfoW(action: u32, param: u32, value: *mut core::ffi::c_void, ini: u32) -> i32;
            fn GetDpiForSystem() -> u32;
        }
        const SPI_GETWORKAREA: u32 = 0x0030;
        let mut r = Rect { left: 0, top: 0, right: 0, bottom: 0 };
        // SAFETY: SPI_GETWORKAREA writes one RECT through the pointer.
        if unsafe { SystemParametersInfoW(SPI_GETWORKAREA, 0, (&raw mut r).cast(), 0) } == 0 {
            return None;
        }
        // Both calls answer in the same units whether or not the process is DPI aware yet,
        // so the division gives logical pixels either way.
        // SAFETY: takes no arguments; present since Windows 10 1607, and WebView2 needs 10.
        let scale = f64::from(unsafe { GetDpiForSystem() }.max(96)) / 96.0;
        let logical = |v: i32| f64::from(v) / scale;
        Some((logical(r.left), logical(r.top), logical(r.right - r.left), logical(r.bottom - r.top)))
    }

    #[cfg(not(target_os = "windows"))]
    fn work_area() -> Option<(f64, f64, f64, f64)> {
        None
    }
}
