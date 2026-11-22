//! Talking to a Daybook server (filled in by the connection work: health, Telegram login link,
//! pulling branches/staff/products/defektura, pushing tasks).

#[derive(Clone, Debug, PartialEq)]
pub struct Health {
    pub ok: bool,
    pub version: String,
}

/// GET /health/ on the server. Native builds only; the web build reports it can't reach it.
#[cfg(not(target_arch = "wasm32"))]
pub fn health(server: &str) -> Result<Health, String> {
    let url = format!("{}/health/", server.trim_end_matches('/'));
    let mut res = ureq::get(&url).call().map_err(|e| e.to_string())?;
    let v: serde_json::Value = res.body_mut().read_json().map_err(|e| e.to_string())?;
    Ok(Health {
        ok: v.get("status").and_then(|s| s.as_str()) == Some("ok"),
        version: v.get("version").and_then(|s| s.as_str()).unwrap_or("?").to_string(),
    })
}

#[cfg(target_arch = "wasm32")]
pub fn health(_server: &str) -> Result<Health, String> {
    Err("web".into())
}
