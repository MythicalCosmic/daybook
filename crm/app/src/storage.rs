//! Saving the database on the device: localStorage on the web, a JSON file on desktop and
//! mobile (app data folder). Demo data older than a few days is regenerated so the demo
//! always looks fresh; the person's settings survive that.

use crm::Db;

const KEY: &str = "daybook-crm-v1";

pub fn load() -> Db {
    let now = crate::state::now();
    let saved = read().and_then(|s| serde_json::from_str::<Db>(&s).ok()).filter(|db| db.version == crm::db::DB_VERSION);
    let mut db = match saved {
        Some(db) if db.settings.daybook.connected || (now.date() - db.generated_on).num_days() < 4 => db,
        Some(old) => {
            let mut fresh = crm::demo::generate(now);
            fresh.settings = old.settings;
            fresh
        }
        None => crm::demo::generate(now),
    };
    apply_url_overrides(&mut db);
    db
}

pub fn save(db: &Db) {
    if let Ok(s) = serde_json::to_string(db) {
        write(&s);
    }
}

/// A brand-new demo company, keeping the person's settings.
pub fn reset(keep: &Db) -> Db {
    let mut db = crm::demo::generate(crate::state::now());
    db.settings = keep.settings.clone();
    db.settings.daybook = Default::default();
    save(&db);
    db
}

// ---------------------------------------------------------------- web

#[cfg(target_arch = "wasm32")]
fn read() -> Option<String> {
    web_sys::window()?.local_storage().ok()??.get_item(KEY).ok()?
}

#[cfg(target_arch = "wasm32")]
fn write(s: &str) {
    if let Some(st) = web_sys::window().and_then(|w| w.local_storage().ok().flatten()) {
        let _ = st.set_item(KEY, s);
    }
}

#[cfg(target_arch = "wasm32")]
static URL_SEARCH: std::sync::OnceLock<String> = std::sync::OnceLock::new();

/// Remembers the page's `?query` at startup, before the router rewrites the address.
#[cfg(target_arch = "wasm32")]
pub fn capture_url() {
    let s = web_sys::window().and_then(|w| w.location().search().ok()).unwrap_or_default();
    let _ = URL_SEARCH.set(s);
}

#[cfg(not(target_arch = "wasm32"))]
pub fn capture_url() {}

/// `?theme=dark&lang=ru&reset=1&privacy=1` for screenshots and demos (web only, not saved).
#[cfg(target_arch = "wasm32")]
fn apply_url_overrides(db: &mut Db) {
    let Some(search) = URL_SEARCH.get().cloned() else { return };
    let Ok(params) = web_sys::UrlSearchParams::new_with_str(&search) else { return };
    if params.get("reset").is_some() {
        let settings = db.settings.clone();
        *db = crm::demo::generate(crate::state::now());
        db.settings = settings;
    }
    if let Some(t) = params.get("theme") {
        if let Some(theme) = crm::model::Theme::from_slug(&t) {
            db.settings.theme = theme;
        }
    }
    if let Some(l) = params.get("lang") {
        if let Some(lang) = crm::i18n::Lang::from_code(&l) {
            db.settings.lang = lang;
        }
    }
    if params.get("privacy").is_some() {
        db.settings.privacy_mode = true;
    }
    if params.get("onboard").is_some() {
        db.settings.onboarded = false;
    } else if params.get("theme").is_some() || params.get("lang").is_some() {
        db.settings.onboarded = true;
    }
}

// ---------------------------------------------------------------- desktop and mobile

#[cfg(not(target_arch = "wasm32"))]
fn data_dir() -> Option<std::path::PathBuf> {
    #[cfg(target_os = "android")]
    {
        // /proc/self/cmdline holds the package name; the app's private files live under it.
        let cmd = std::fs::read_to_string("/proc/self/cmdline").ok()?;
        let pkg = cmd.split('\0').next()?.trim().to_string();
        if pkg.is_empty() {
            return None;
        }
        Some(std::path::PathBuf::from(format!("/data/data/{pkg}/files")))
    }
    #[cfg(target_os = "ios")]
    {
        Some(std::path::PathBuf::from(std::env::var("HOME").ok()?).join("Documents"))
    }
    #[cfg(not(any(target_os = "android", target_os = "ios")))]
    {
        Some(dirs::data_local_dir()?.join("Daybook CRM"))
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn read() -> Option<String> {
    std::fs::read_to_string(data_dir()?.join("crm.json")).ok()
}

#[cfg(not(target_arch = "wasm32"))]
fn write(s: &str) {
    let Some(dir) = data_dir() else { return };
    let _ = std::fs::create_dir_all(&dir);
    let tmp = dir.join("crm.json.tmp");
    if std::fs::write(&tmp, s).is_ok() {
        let _ = std::fs::rename(&tmp, dir.join("crm.json"));
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn apply_url_overrides(_db: &mut Db) {}
