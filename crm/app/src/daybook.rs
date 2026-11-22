//! Talking to a Daybook server, using the same API the owner dashboard uses:
//! * `GET /health/`: status and version.
//! * Telegram login link: `POST /api/v1/owner/auth/login-links/` gives a t.me deep link and a
//!   two-digit number to match; the app polls with `X-Login-Poll` until the owner approves in
//!   the bot, then `POST .../claim/` returns the access token and the `owner_refresh` cookie.
//! * Developer sign-in for local servers (`/api/v1/owner/auth/dev-login/`).
//! * Pulls branches, people, products and B2B customers; pushes CRM tasks to Daybook tasks.
//! Every call is blocking (ureq) and runs on a worker thread via [`background`].

use serde_json::Value;

#[derive(Clone, Debug, PartialEq)]
pub struct Health {
    pub ok: bool,
    pub version: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct LoginLink {
    pub id: String,
    pub poll_token: String,
    pub deep_link: String,
    pub bot_username: String,
    pub match_code: String,
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct Session {
    pub server: String,
    pub access: Option<String>,
    pub refresh: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Me {
    pub name: String,
    pub companies: Vec<(i64, String)>,
}

/// What a sync brought in.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Pulled {
    pub branches: Vec<Value>,
    pub people: Vec<Value>,
    pub products: Vec<Value>,
    pub customers: Vec<Value>,
    pub defektura: usize,
    pub pushed_tasks: Vec<(u32, i64)>,
}

pub fn is_local(server: &str) -> bool {
    server.contains("127.0.0.1") || server.contains("localhost") || server.contains("host.docker.internal")
}

/// Runs blocking work off the UI thread and awaits it.
#[cfg(not(target_arch = "wasm32"))]
pub async fn background<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> T {
    let (tx, rx) = futures_channel::oneshot::channel();
    std::thread::spawn(move || {
        let _ = tx.send(f());
    });
    rx.await.expect("worker thread ended")
}

#[cfg(target_arch = "wasm32")]
pub async fn background<T: 'static>(f: impl FnOnce() -> T + 'static) -> T {
    f()
}

#[cfg(target_arch = "wasm32")]
mod imp {
    use super::*;

    const WEB: &str = "web";

    impl Session {
        pub fn health(&self) -> Result<Health, String> {
            Err(WEB.into())
        }
        pub fn start_login(&self) -> Result<LoginLink, String> {
            Err(WEB.into())
        }
        pub fn wait_for_approval(&mut self, _link: &LoginLink, _cancel: std::sync::Arc<std::sync::atomic::AtomicBool>) -> Result<(), String> {
            Err(WEB.into())
        }
        pub fn dev_login(&mut self, _telegram_id: i64) -> Result<(), String> {
            Err(WEB.into())
        }
        pub fn me(&mut self) -> Result<Me, String> {
            Err(WEB.into())
        }
        pub fn pull(&mut self, _company: i64, _tasks: Vec<(u32, String, String, String)>) -> Result<Pulled, String> {
            Err(WEB.into())
        }
    }
}

#[cfg(not(target_arch = "wasm32"))]
mod imp {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::time::Duration;

    use super::*;

    fn agent() -> ureq::Agent {
        ureq::Agent::config_builder()
            .timeout_global(Some(Duration::from_secs(20)))
            .http_status_as_error(false)
            .build()
            .into()
    }

    fn detail(status: u16, v: &Value) -> String {
        let msg = v.get("detail").and_then(|d| d.as_str()).unwrap_or("");
        let code = v.get("code").and_then(|d| d.as_str()).unwrap_or("");
        format!("HTTP {status} {code} {msg}").trim().to_string()
    }

    fn rows(v: Value) -> Vec<Value> {
        match v {
            Value::Array(a) => a,
            Value::Object(mut o) => match o.remove("results") {
                Some(Value::Array(a)) => a,
                _ => Vec::new(),
            },
            _ => Vec::new(),
        }
    }

    impl Session {
        pub fn base(&self) -> String {
            self.server.trim().trim_end_matches('/').to_string()
        }

        /// "https://host[:port]", what Daybook's FromDashboard check expects in Origin.
        fn origin(&self) -> String {
            let b = self.base();
            match b.find("://") {
                Some(i) => match b[i + 3..].find('/') {
                    Some(j) => b[..i + 3 + j].to_string(),
                    None => b,
                },
                None => b,
            }
        }

        fn refresh_cookie(res: &ureq::http::Response<ureq::Body>) -> Option<String> {
            res.headers()
                .get_all("set-cookie")
                .iter()
                .filter_map(|h| h.to_str().ok())
                .find_map(|c| c.strip_prefix("owner_refresh=").map(|rest| rest.split(';').next().unwrap_or("").to_string()))
                .filter(|s| !s.is_empty())
        }

        pub fn health(&self) -> Result<Health, String> {
            let mut res = agent().get(&format!("{}/health/", self.base())).call().map_err(|e| e.to_string())?;
            let v: Value = res.body_mut().read_json().map_err(|e| e.to_string())?;
            Ok(Health {
                ok: v.get("status").and_then(|s| s.as_str()) == Some("ok"),
                version: v.get("version").and_then(|s| s.as_str()).unwrap_or("?").to_string(),
            })
        }

        pub fn start_login(&self) -> Result<LoginLink, String> {
            let mut res = agent()
                .post(&format!("{}/api/v1/owner/auth/login-links/", self.base()))
                .header("X-Requested-With", "dashboard")
                .header("Origin", &self.origin())
                .send_empty()
                .map_err(|e| e.to_string())?;
            let status = res.status().as_u16();
            let v: Value = res.body_mut().read_json().unwrap_or(Value::Null);
            if status != 201 && status != 200 {
                return Err(detail(status, &v));
            }
            let s = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
            Ok(LoginLink {
                id: s("id"),
                poll_token: s("poll_token"),
                deep_link: s("deep_link"),
                bot_username: s("bot_username"),
                match_code: v.get("match_code").map(|m| m.as_str().map(str::to_string).unwrap_or_else(|| m.to_string())).unwrap_or_default(),
            })
        }

        /// Polls every 2 s until the owner approves in Telegram, then claims the session.
        pub fn wait_for_approval(&mut self, link: &LoginLink, cancel: Arc<AtomicBool>) -> Result<(), String> {
            let a = agent();
            for _ in 0..150 {
                if cancel.load(Ordering::Relaxed) {
                    return Err("cancelled".into());
                }
                std::thread::sleep(Duration::from_secs(2));
                let mut res = a
                    .get(&format!("{}/api/v1/owner/auth/login-links/{}/", self.base(), link.id))
                    .header("X-Login-Poll", &link.poll_token)
                    .call()
                    .map_err(|e| e.to_string())?;
                let v: Value = res.body_mut().read_json().unwrap_or(Value::Null);
                match v.get("status").and_then(|s| s.as_str()).unwrap_or("") {
                    "approved" => {
                        let mut res = a
                            .post(&format!("{}/api/v1/owner/auth/login-links/{}/claim/", self.base(), link.id))
                            .header("X-Login-Poll", &link.poll_token)
                            .header("X-Requested-With", "dashboard")
                            .header("Origin", &self.origin())
                            .send_empty()
                            .map_err(|e| e.to_string())?;
                            let status = res.status().as_u16();
                        let refresh = Self::refresh_cookie(&res);
                        let v: Value = res.body_mut().read_json().unwrap_or(Value::Null);
                        let access = v.get("access").and_then(|s| s.as_str()).map(str::to_string);
                        if access.is_none() {
                            return Err(detail(status, &v));
                        }
                        self.access = access;
                        self.refresh = refresh;
                        return Ok(());
                    }
                    "denied" => return Err("denied".into()),
                    "expired" | "consumed" => return Err("expired".into()),
                    _ => {}
                }
            }
            Err("expired".into())
        }

        /// Local development servers only (DEBUG + DASHBOARD_DEV_LOGIN).
        pub fn dev_login(&mut self, telegram_id: i64) -> Result<(), String> {
            let mut res = agent()
                .post(&format!("{}/api/v1/owner/auth/dev-login/", self.base()))
                .header("X-Requested-With", "dashboard")
                .header("Origin", &self.origin())
                .send_json(serde_json::json!({ "telegram_id": telegram_id }))
                .map_err(|e| e.to_string())?;
            let status = res.status().as_u16();
            let refresh = Self::refresh_cookie(&res);
            let v: Value = res.body_mut().read_json().unwrap_or(Value::Null);
            match v.get("access").and_then(|s| s.as_str()) {
                Some(a) => {
                    self.access = Some(a.to_string());
                    self.refresh = refresh;
                    Ok(())
                }
                None => Err(detail(status, &v)),
            }
        }

        /// New access token from the refresh cookie (rotates the cookie).
        fn renew(&mut self) -> Result<(), String> {
            let Some(cookie) = self.refresh.clone() else { return Err("signed out".into()) };
            let mut res = agent()
                .post(&format!("{}/api/v1/owner/auth/refresh/", self.base()))
                .header("X-Requested-With", "dashboard")
                .header("Origin", &self.origin())
                .header("Cookie", &format!("owner_refresh={cookie}"))
                .send_empty()
                .map_err(|e| e.to_string())?;
            let status = res.status().as_u16();
            if let Some(c) = Self::refresh_cookie(&res) {
                self.refresh = Some(c);
            }
            let v: Value = res.body_mut().read_json().unwrap_or(Value::Null);
            match v.get("access").and_then(|s| s.as_str()) {
                Some(a) => {
                    self.access = Some(a.to_string());
                    Ok(())
                }
                None => Err(detail(status, &v)),
            }
        }

        /// GET with the access token, renewing it once on 401.
        fn get_json(&mut self, path: &str) -> Result<Value, String> {
            for attempt in 0..2 {
                let token = self.access.clone().unwrap_or_default();
                let mut res = agent()
                    .get(&format!("{}{}", self.base(), path))
                    .header("Authorization", &format!("Bearer {token}"))
                    .header("Accept-Language", "uz")
                    .call()
                    .map_err(|e| e.to_string())?;
                let status = res.status().as_u16();
                if status == 401 && attempt == 0 {
                    self.renew()?;
                    continue;
                }
                let v: Value = res.body_mut().read_json().unwrap_or(Value::Null);
                if status >= 400 {
                    return Err(detail(status, &v));
                }
                return Ok(v);
            }
            Err("unauthorized".into())
        }

        fn post_json(&mut self, path: &str, body: Value) -> Result<Value, String> {
            for attempt in 0..2 {
                let token = self.access.clone().unwrap_or_default();
                let mut res = agent()
                    .post(&format!("{}{}", self.base(), path))
                    .header("Authorization", &format!("Bearer {token}"))
                    .send_json(body.clone())
                    .map_err(|e| e.to_string())?;
                let status = res.status().as_u16();
                if status == 401 && attempt == 0 {
                    self.renew()?;
                    continue;
                }
                let v: Value = res.body_mut().read_json().unwrap_or(Value::Null);
                if status >= 400 {
                    return Err(detail(status, &v));
                }
                return Ok(v);
            }
            Err("unauthorized".into())
        }

        pub fn me(&mut self) -> Result<Me, String> {
            let v = self.get_json("/api/v1/owner/me/")?;
            let name = ["full_name", "name", "first_name"]
                .iter()
                .find_map(|k| v.get(*k).and_then(|x| x.as_str()).filter(|s| !s.is_empty()))
                .or_else(|| v.get("user").and_then(|u| u.get("full_name")).and_then(|x| x.as_str()))
                .unwrap_or("")
                .to_string();
            let list = v.get("companies").cloned().map(rows).unwrap_or_default();
            let companies = list
                .iter()
                .filter_map(|c| {
                    let id = c.get("id").and_then(|x| x.as_i64()).or_else(|| c.get("company").and_then(|x| x.get("id")).and_then(|x| x.as_i64()))?;
                    let name = c
                        .get("name")
                        .and_then(|x| x.as_str())
                        .or_else(|| c.get("company").and_then(|x| x.get("name")).and_then(|x| x.as_str()))
                        .unwrap_or("Daybook")
                        .to_string();
                    Some((id, name))
                })
                .collect();
            Ok(Me { name, companies })
        }

        /// Pulls the company's data and pushes tasks: (crm activity id, title, due ISO, owner name).
        pub fn pull(&mut self, company: i64, tasks: Vec<(u32, String, String, String)>) -> Result<Pulled, String> {
            let o = format!("/api/v1/owner/companies/{company}");
            let mut p = Pulled::default();
            p.branches = rows(self.get_json(&format!("{o}/branches/"))?);
            p.people = self.get_json(&format!("{o}/people/")).map(rows).unwrap_or_default();
            p.products = self.get_json(&format!("{o}/stock/products/")).map(rows).unwrap_or_default();
            p.customers = self.get_json(&format!("{o}/sales/customers/")).map(rows).unwrap_or_default();
            p.defektura = self.get_json(&format!("{o}/stock/defektura/")).map(rows).map(|r| r.len()).unwrap_or(0);
            for (crm_id, title, due, owner) in tasks {
                // Daybook wants people, positions or branches: the owner by name, else the first branch.
                let person = p.people.iter().find(|x| x.get("full_name").and_then(|n| n.as_str()).map(|n| n.eq_ignore_ascii_case(&owner)).unwrap_or(false)).and_then(|x| x.get("id")).and_then(|x| x.as_i64());
                let branch = p.branches.first().and_then(|b| b.get("id")).and_then(|x| x.as_i64());
                let mut body = serde_json::json!({ "title": title, "due_at": due, "description": "Daybook CRM" });
                match (person, branch) {
                    (Some(id), _) => body["assignee_ids"] = serde_json::json!([id]),
                    (None, Some(b)) => body["branch_ids"] = serde_json::json!([b]),
                    _ => continue,
                }
                if let Ok(v) = self.post_json(&format!("{o}/tasks/"), body) {
                    let id = v.get("id").and_then(|x| x.as_i64()).or_else(|| v.get("ids").and_then(|x| x.as_array()).and_then(|a| a.first()).and_then(|x| x.as_i64()));
                    if let Some(id) = id {
                        p.pushed_tasks.push((crm_id, id));
                    }
                }
            }
            Ok(p)
        }
    }
}

/// Folds pulled data into the CRM database (upserts by Daybook id, then by name).
pub fn apply(db: &mut crm::Db, pulled: &Pulled) -> crm::model::SyncCounts {
    use crm::model::*;
    let s = |v: &Value, keys: &[&str]| -> String {
        keys.iter().find_map(|k| v.get(*k).and_then(|x| x.as_str()).filter(|s| !s.is_empty()).map(str::to_string)).unwrap_or_default()
    };
    let num = |v: &Value, k: &str| -> f64 {
        match v.get(k) {
            Some(Value::String(x)) => x.parse().unwrap_or(0.0),
            Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0),
            Some(Value::Object(o)) => o.get("amount").and_then(|a| a.as_str().and_then(|s| s.parse().ok()).or(a.as_f64())).unwrap_or(0.0),
            _ => 0.0,
        }
    };
    let mut counts = SyncCounts::default();
    for b in &pulled.branches {
        let Some(did) = b.get("id").and_then(|x| x.as_i64()) else { continue };
        let name = s(b, &["name"]);
        let existing = db.branches.iter().position(|x| x.daybook_id == Some(did)).or_else(|| db.branches.iter().position(|x| x.name.eq_ignore_ascii_case(&name)));
        match existing {
            Some(i) => {
                let br = &mut db.branches[i];
                br.daybook_id = Some(did);
                if !name.is_empty() {
                    br.name = name;
                }
                let addr = s(b, &["address"]);
                if !addr.is_empty() {
                    br.address = addr;
                }
            }
            None => {
                let id = db.new_id();
                let hue = (id * 47 % 360) as u16;
                db.branches.push(Branch {
                    id,
                    name,
                    district: String::new(),
                    address: s(b, &["address"]),
                    phone: s(b, &["phone"]),
                    manager_id: None,
                    hue,
                    open_hours: if b.get("open_24h").and_then(|x| x.as_bool()).unwrap_or(false) { "24/7".into() } else { String::new() },
                    daybook_id: Some(did),
                });
            }
        }
        counts.branches += 1;
    }
    for p in &pulled.people {
        let Some(did) = p.get("id").and_then(|x| x.as_i64()) else { continue };
        let name = s(p, &["full_name", "name"]);
        if name.is_empty() {
            continue;
        }
        if let Some(st) = db.staff.iter_mut().find(|x| x.daybook_id == Some(did) || x.name.eq_ignore_ascii_case(&name)) {
            st.daybook_id = Some(did);
        } else {
            let id = db.new_id();
            let role_text = p.get("role").map(|r| r.to_string().to_lowercase()).unwrap_or_default();
            let role = if role_text.contains("owner") || role_text.contains("ega") {
                Role::Owner
            } else if role_text.contains("manager") || role_text.contains("mudir") {
                Role::Manager
            } else if role_text.contains("cash") || role_text.contains("kassir") {
                Role::Cashier
            } else if role_text.contains("courier") || role_text.contains("kuryer") {
                Role::Courier
            } else {
                Role::Pharmacist
            };
            db.staff.push(Staff {
                id,
                name: name.clone(),
                role,
                branch_id: None,
                phone: s(p, &["phone"]),
                telegram: s(p, &["username"]),
                hue: crate::state::hue_of(&name),
                active: true,
                daybook_id: Some(did),
            });
        }
        counts.staff += 1;
    }
    for pr in &pulled.products {
        let Some(did) = pr.get("id").and_then(|x| x.as_i64()) else { continue };
        let name = s(pr, &["name", "trade_name"]);
        if name.is_empty() {
            continue;
        }
        let price = num(pr, "reference_price").round() as Money;
        if let Some(x) = db.products.iter_mut().find(|x| x.daybook_id == Some(did) || x.name.eq_ignore_ascii_case(&name)) {
            x.daybook_id = Some(did);
            if price > 0 {
                x.price = price;
            }
        } else {
            let id = db.new_id();
            let rx = pr.get("rx_required").and_then(|x| x.as_bool()).unwrap_or(false);
            let today = crate::state::today();
            db.products.push(Product {
                id,
                name: name.clone(),
                generic: s(pr, &["inn", "name"]),
                form: s(pr, &["dosage_form"]),
                maker: pr.get("manufacturer").and_then(|m| m.get("name")).and_then(|x| x.as_str()).unwrap_or("").to_string(),
                category: if rx { ProductCategory::Rx } else { ProductCategory::Otc },
                rx,
                price,
                stock: vec![],
                expiry: today + chrono::Duration::days(365),
                no_bonus: false,
                barcode: s(pr, &["barcode"]),
                daybook_id: Some(did),
            });
        }
        counts.products += 1;
    }
    for c in &pulled.customers {
        let Some(did) = c.get("id").and_then(|x| x.as_i64()) else { continue };
        let name = s(c, &["name"]);
        if name.is_empty() {
            continue;
        }
        let owed = num(c, "owed").round() as Money;
        let limit = num(c, "credit_limit").round() as Money;
        if let Some(x) = db.companies.iter_mut().find(|x| x.daybook_id == Some(did) || x.name.eq_ignore_ascii_case(&name)) {
            x.daybook_id = Some(did);
            x.receivable = owed;
            if limit > 0 {
                x.credit_limit = limit;
            }
        } else {
            let id = db.new_id();
            let contact = s(c, &["contact_person"]);
            db.companies.push(Company {
                id,
                name,
                kind: OrgKind::Corporate,
                tin: s(c, &["tin"]),
                district: String::new(),
                address: s(c, &["address"]),
                phone: s(c, &["phone"]),
                email: String::new(),
                owner_id: Some(db.settings.me),
                credit_limit: limit,
                terms_days: 30,
                receivable: owed,
                tags: vec!["Daybook".into()],
                created: crate::state::today(),
                employees: 0,
                contacts: if contact.is_empty() {
                    vec![]
                } else {
                    vec![ContactPerson { name: contact, position: String::new(), phone: s(c, &["phone"]), telegram: None, primary: true }]
                },
                notes: s(c, &["notes"]),
                health: 75,
                daybook_id: Some(did),
            });
        }
        counts.customers += 1;
    }
    counts.defektura = pulled.defektura as u32;
    for (crm_id, daybook_id) in &pulled.pushed_tasks {
        if let Some(a) = db.activity_mut(*crm_id) {
            a.daybook_task = Some(*daybook_id);
        }
        counts.tasks_pushed += 1;
    }
    counts
}

/// SVG path (one unit per module) for a QR code of `text`, and its size in modules.
pub fn qr_path(text: &str) -> Option<(String, usize)> {
    let code = qrcode::QrCode::new(text.as_bytes()).ok()?;
    let w = code.width();
    let colors = code.to_colors();
    let mut d = String::with_capacity(w * w * 4);
    for y in 0..w {
        for x in 0..w {
            if colors[y * w + x] == qrcode::Color::Dark {
                d.push_str(&format!("M{x} {y}h1v1h-1z"));
            }
        }
    }
    Some((d, w))
}
