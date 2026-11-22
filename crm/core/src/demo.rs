//! The demo company: "Oydin Farm", a fictional pharmacy chain with six branches in Tashkent.
//! Deterministic (same seed, same data) and generated relative to `now`, so it always looks
//! fresh: refills are due this week, leads came in this morning, deals are in motion.
//! Every person, company and distributor here is invented.

use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime};

use crate::db::{Db, DB_VERSION};
use crate::i18n::Lang;
use crate::model::*;
use crate::rng::Rng;

pub const COMPANY_NAME: &str = "Oydin Farm";

fn at(d: NaiveDate, h: u32, m: u32) -> NaiveDateTime {
    d.and_hms_opt(h.min(23), m.min(59), 0).unwrap_or_else(|| d.and_hms_opt(12, 0, 0).unwrap())
}

fn empty(now: NaiveDateTime) -> Db {
    Db {
        version: DB_VERSION,
        generated_on: now.date(),
        next_id: 100,
        settings: Settings {
            lang: Lang::Uz,
            theme: Theme::System,
            company_name: COMPANY_NAME.into(),
            me: 0,
            daybook: DaybookLink::default(),
            ai: AiSettings::default(),
            loyalty: LoyaltySettings::default(),
            refill_lead_days: 3,
            inactive_days: 60,
            sla_hours: 24,
            compact: false,
            privacy_mode: false,
            onboarded: false,
            sidebar_collapsed: false,
        },
        branches: vec![],
        staff: vec![],
        customers: vec![],
        purchases: vec![],
        companies: vec![],
        pipelines: vec![],
        deals: vec![],
        leads: vec![],
        activities: vec![],
        conversations: vec![],
        campaigns: vec![],
        segments: vec![],
        automations: vec![],
        products: vec![],
        waitlist: vec![],
        tickets: vec![],
        quotes: vec![],
        loyalty: vec![],
        goals: vec![],
        notes: vec![],
        audit: vec![],
        notifications: vec![],
    }
}

/// Builds the whole demo company.
pub fn generate(now: NaiveDateTime) -> Db {
    let mut rng = Rng::new(0xDA7B_00C2);
    let mut db = empty(now);
    let g = Gen::new(&mut db, &mut rng, now);
    g.run(&mut db, &mut rng, now);
    db
}

/// Ids of the things later steps refer to.
struct Gen {
    branches: Vec<Id>,
    owner: Id,
    managers: Vec<Id>,
    pharmacists: Vec<Id>,
    call_agent: Id,
    reps: Vec<Id>,
    marketer: Id,
    courier: Id,
}

const BRANCHES: &[(&str, &str, &str, &str, u16, &str)] = &[
    ("Chilonzor", "Chilonzor tumani", "Chilonzor-9, Qatortol ko‘chasi, 45", "+998 71 276 14 20", 24, "24/7"),
    ("Yunusobod", "Yunusobod tumani", "Yunusobod-4, Amir Temur shoh ko‘chasi, 108", "+998 71 224 38 51", 205, "08:00–23:00"),
    ("Mirzo Ulug‘bek", "Mirzo Ulug‘bek tumani", "Buyuk Ipak Yo‘li ko‘chasi, 32", "+998 71 262 90 17", 150, "08:00–22:00"),
    ("Sergeli", "Sergeli tumani", "Sergeli-6, Yangi Sergeli ko‘chasi, 17", "+998 71 289 55 03", 330, "08:00–22:00"),
    ("Yakkasaroy", "Yakkasaroy tumani", "Shota Rustaveli ko‘chasi, 54", "+998 71 255 72 64", 45, "08:00–23:00"),
    ("Olmazor", "Olmazor tumani", "Qorasaroy ko‘chasi, 210", "+998 71 246 03 88", 265, "09:00–21:00"),
];

const STAFF: &[(&str, Role, Option<usize>, &str, u16)] = &[
    ("Javohir Rasulov", Role::Owner, None, "javohir_rasulov", 24),
    ("Sevara Tursunova", Role::Manager, Some(0), "sevara_t", 330),
    ("Dilnoza Karimova", Role::Manager, Some(1), "dilnoza_karimova", 280),
    ("Bekzod Aliyev", Role::Manager, Some(2), "bekzod_aliyev", 205),
    ("Nodira Yusupova", Role::Pharmacist, Some(0), "nodira_farm", 150),
    ("Sardor Rahimov", Role::Pharmacist, Some(1), "sardor_r", 190),
    ("Gulnora Ismoilova", Role::Pharmacist, Some(2), "gulnora_i", 340),
    ("Shahzod Qodirov", Role::Pharmacist, Some(3), "shahzod_q", 100),
    ("Malika Nazarova", Role::Pharmacist, Some(4), "malika_nazarova", 310),
    ("Elena Kim", Role::Pharmacist, Some(5), "elena_kim", 175),
    ("Aziza Sobirova", Role::CallAgent, Some(0), "aziza_call", 12),
    ("Timur Xolmatov", Role::SalesRep, None, "timur_b2b", 220),
    ("Kamola Ergasheva", Role::SalesRep, None, "kamola_b2b", 355),
    ("Rustam Mirzayev", Role::Marketer, None, "rustam_mkt", 60),
    ("Ulug‘bek Saidov", Role::Courier, Some(0), "ulugbek_kuryer", 90),
    ("Madina Umarova", Role::Cashier, Some(0), "madina_kassa", 300),
];

/// (name, generic, form, origin, category, rx, price, popularity, no_bonus)
const PRODUCTS: &[(&str, &str, &str, &str, ProductCategory, bool, Money, u32, bool)] = &[
    ("Amlodipin 5 mg №30", "Amlodipin", "tabletka", "Hindiston", ProductCategory::Rx, true, 18_500, 9, false),
    ("Amlodipin 10 mg №30", "Amlodipin", "tabletka", "Hindiston", ProductCategory::Rx, true, 24_000, 5, false),
    ("Lozartan 50 mg №30", "Lozartan", "tabletka", "Sloveniya", ProductCategory::Rx, true, 39_000, 8, false),
    ("Bisoprolol 5 mg №30", "Bisoprolol", "tabletka", "Germaniya", ProductCategory::Rx, true, 46_000, 6, false),
    ("Enalapril 10 mg №20", "Enalapril", "tabletka", "O‘zbekiston", ProductCategory::Rx, true, 9_800, 6, false),
    ("Indapamid 2,5 mg №30", "Indapamid", "tabletka", "Turkiya", ProductCategory::Rx, true, 27_000, 4, false),
    ("Atorvastatin 20 mg №30", "Atorvastatin", "tabletka", "Hindiston", ProductCategory::Rx, true, 52_000, 7, false),
    ("Rozuvastatin 10 mg №28", "Rozuvastatin", "tabletka", "Sloveniya", ProductCategory::Rx, true, 89_000, 4, false),
    ("Metformin 850 mg №60", "Metformin", "tabletka", "Germaniya", ProductCategory::Rx, true, 34_000, 8, false),
    ("Metformin 1000 mg №60", "Metformin", "tabletka", "Germaniya", ProductCategory::Rx, true, 41_000, 5, false),
    ("Gliklazid MR 60 mg №30", "Gliklazid", "tabletka", "Fransiya", ProductCategory::Rx, true, 63_000, 4, false),
    ("Insulin glargin 100 TB/ml, shprits-ruchka №5", "Insulin glargin", "shprits-ruchka", "Germaniya", ProductCategory::Diabetes, true, 410_000, 3, false),
    ("Insulin aspart 100 TB/ml, shprits-ruchka №5", "Insulin aspart", "shprits-ruchka", "Daniya", ProductCategory::Diabetes, true, 385_000, 2, false),
    ("Levotiroksin 50 mkg №100", "Levotiroksin", "tabletka", "Germaniya", ProductCategory::Rx, true, 38_000, 5, false),
    ("Levotiroksin 100 mkg №100", "Levotiroksin", "tabletka", "Germaniya", ProductCategory::Rx, true, 42_000, 3, false),
    ("Klopidogrel 75 mg №28", "Klopidogrel", "tabletka", "Hindiston", ProductCategory::Rx, true, 58_000, 4, false),
    ("Atsetilsalitsil kislota kardio 100 mg №30", "Atsetilsalitsil kislota", "tabletka", "Germaniya", ProductCategory::Otc, false, 32_000, 7, false),
    ("Salbutamol ingalyator 100 mkg, 200 doza", "Salbutamol", "ingalyator", "Buyuk Britaniya", ProductCategory::Rx, true, 48_000, 4, false),
    ("Budesonid/formoterol 160/4,5 mkg, 120 doza", "Budesonid + formoterol", "ingalyator", "Shvetsiya", ProductCategory::Rx, true, 265_000, 2, false),
    ("Montelukast 10 mg №28", "Montelukast", "tabletka", "Hindiston", ProductCategory::Rx, true, 96_000, 3, false),
    ("Omeprazol 20 mg №30", "Omeprazol", "kapsula", "Sloveniya", ProductCategory::Otc, false, 22_000, 8, false),
    ("Pantoprazol 40 mg №28", "Pantoprazol", "tabletka", "Germaniya", ProductCategory::Rx, true, 69_000, 4, false),
    ("Amoksitsillin 500 mg №16", "Amoksitsillin", "kapsula", "Avstriya", ProductCategory::Rx, true, 31_000, 7, false),
    ("Azitromitsin 500 mg №3", "Azitromitsin", "tabletka", "Xorvatiya", ProductCategory::Rx, true, 45_000, 6, false),
    ("Amoksitsillin + klavulan kislota 875/125 mg №14", "Amoksitsillin + klavulan kislota", "tabletka", "Sloveniya", ProductCategory::Rx, true, 98_000, 5, false),
    ("Paratsetamol 500 mg №10", "Paratsetamol", "tabletka", "O‘zbekiston", ProductCategory::Otc, false, 4_500, 12, false),
    ("Ibuprofen 400 mg №20", "Ibuprofen", "tabletka", "Germaniya", ProductCategory::Otc, false, 21_000, 10, false),
    ("Setirizin 10 mg №10", "Setirizin", "tabletka", "Hindiston", ProductCategory::Otc, false, 14_000, 8, false),
    ("Loratadin 10 mg №10", "Loratadin", "tabletka", "Hindiston", ProductCategory::Otc, false, 12_000, 6, false),
    ("Diklofenak gel 1%, 50 g", "Diklofenak", "gel", "Sloveniya", ProductCategory::Otc, false, 36_000, 7, false),
    ("Ksilometazolin burun spreyi 0,1%", "Ksilometazolin", "sprey", "Germaniya", ProductCategory::Otc, false, 28_000, 9, false),
    ("Regidratatsiya kukuni №10", "Natriy xlorid + glyukoza", "kukun", "O‘zbekiston", ProductCategory::Otc, false, 19_000, 5, false),
    ("Drotaverin 40 mg №20", "Drotaverin", "tabletka", "Vengriya", ProductCategory::Otc, false, 16_000, 7, false),
    ("Pankreatin 25 000 TB №20", "Pankreatin", "kapsula", "Germaniya", ProductCategory::Otc, false, 54_000, 5, false),
    ("Ambroksol siropi 15 mg/5 ml, 100 ml", "Ambroksol", "sirop", "Germaniya", ProductCategory::Otc, false, 33_000, 8, false),
    ("Probiotik kapsula №10", "Laktobakteriyalar", "kapsula", "Polsha", ProductCategory::Otc, false, 72_000, 5, false),
    ("D3 vitamini 2000 ME №60", "Xolekaltsiferol", "kapsula", "AQSH", ProductCategory::Vitamins, false, 85_000, 9, false),
    ("Omega-3 1000 mg №60", "Omega-3", "kapsula", "Norvegiya", ProductCategory::Vitamins, false, 129_000, 6, false),
    ("Magniy B6 №50", "Magniy + piridoksin", "tabletka", "Fransiya", ProductCategory::Vitamins, false, 74_000, 7, false),
    ("Foliy kislotasi 400 mkg №30", "Foliy kislotasi", "tabletka", "O‘zbekiston", ProductCategory::Vitamins, false, 12_000, 4, false),
    ("Temir + foliy kislotasi №30", "Temir sulfat + foliy kislotasi", "kapsula", "Germaniya", ProductCategory::Vitamins, false, 56_000, 4, false),
    ("Homiladorlar uchun multivitamin №30", "Multivitamin", "tabletka", "Germaniya", ProductCategory::Vitamins, false, 168_000, 3, false),
    ("Bolalar multivitamini, chaynaladigan №60", "Multivitamin", "pastila", "AQSH", ProductCategory::Vitamins, false, 115_000, 4, false),
    ("C vitamini 1000 mg, eruvchan №20", "Askorbin kislota", "tabletka", "Polsha", ProductCategory::Vitamins, false, 39_000, 8, false),
    ("Glyukometr test-poloskalari №50", "Test-poloska", "to‘plam", "Shveytsariya", ProductCategory::Diabetes, false, 165_000, 5, false),
    ("Lanset ignalari №100", "Lanset", "to‘plam", "Germaniya", ProductCategory::Diabetes, false, 48_000, 3, false),
    ("Glyukometr to‘plami", "Glyukometr", "qurilma", "Shveytsariya", ProductCategory::Diabetes, false, 290_000, 1, false),
    ("Shprits-ruchka ignalari №100", "Igna", "to‘plam", "Daniya", ProductCategory::Diabetes, false, 120_000, 2, false),
    ("Qon bosimi o‘lchagich, yelkaga", "Tonometr", "qurilma", "Yaponiya", ProductCategory::Devices, false, 520_000, 2, false),
    ("Elektron termometr", "Termometr", "qurilma", "Shveytsariya", ProductCategory::Devices, false, 45_000, 5, false),
    ("Pulsoksimetr", "Pulsoksimetr", "qurilma", "Xitoy", ProductCategory::Devices, false, 185_000, 2, false),
    ("Kompressorli nebulayzer", "Nebulayzer", "qurilma", "Italiya", ProductCategory::Devices, false, 690_000, 1, false),
    ("Elastik bint 10 cm", "Bint", "bint", "O‘zbekiston", ProductCategory::Devices, false, 18_000, 4, false),
    ("Bolalar suti aralashmasi 1 (0–6 oy), 800 g", "Sut aralashmasi", "kukun", "Niderlandiya", ProductCategory::Baby, false, 245_000, 3, true),
    ("Taglik, 3-o‘lcham №52", "Taglik", "qadoq", "Polsha", ProductCategory::Baby, false, 155_000, 4, false),
    ("Bolalar paratsetamol siropi 120 mg/5 ml", "Paratsetamol", "sirop", "Germaniya", ProductCategory::Baby, false, 26_000, 6, false),
    ("Tish chiqarish geli", "Lidokain + romashka", "gel", "Germaniya", ProductCategory::Baby, false, 42_000, 3, false),
    ("Quyoshdan himoya kremi SPF 50", "Quyosh filtri", "krem", "Fransiya", ProductCategory::Cosmetics, false, 210_000, 2, false),
    ("Atopik teri uchun emolent krem, 200 ml", "Emolent", "krem", "Fransiya", ProductCategory::Cosmetics, false, 175_000, 3, false),
    ("Gialuron kislotali namlovchi krem", "Gialuron kislota", "krem", "Koreya", ProductCategory::Cosmetics, false, 145_000, 3, false),
    ("Antiseptik gel, 500 ml", "Etil spirti", "gel", "O‘zbekiston", ProductCategory::Hygiene, false, 28_000, 5, false),
    ("Sezgir tishlar uchun tish pastasi", "Tish pastasi", "pasta", "Germaniya", ProductCategory::Hygiene, false, 39_000, 4, false),
    ("Homiladorlik testi", "Test", "test", "Germaniya", ProductCategory::Hygiene, false, 15_000, 4, false),
    ("Tibbiy niqob №50", "Niqob", "qadoq", "O‘zbekiston", ProductCategory::Hygiene, false, 35_000, 4, false),
];

/// Regular therapies: (condition, product index, dose text, pack days, weight)
const THERAPIES: &[(Condition, usize, &str, u16, f64)] = &[
    (Condition::Hypertension, 0, "1 tabletka ertalab", 30, 3.0),
    (Condition::Hypertension, 2, "1 tabletka kuniga", 30, 2.5),
    (Condition::Hypertension, 3, "1 tabletka ertalab", 30, 1.6),
    (Condition::Hypertension, 4, "1 tabletka 2 mahal", 10, 1.0),
    (Condition::Hypertension, 5, "1 tabletka ertalab", 30, 0.8),
    (Condition::Cholesterol, 6, "1 tabletka kechqurun", 30, 2.0),
    (Condition::Cholesterol, 7, "1 tabletka kechqurun", 28, 1.0),
    (Condition::Diabetes, 8, "1 tabletka 2 mahal", 30, 2.4),
    (Condition::Diabetes, 9, "1 tabletka 2 mahal", 30, 1.2),
    (Condition::Diabetes, 10, "1 tabletka nonushtada", 30, 1.0),
    (Condition::Diabetes, 11, "20 TB kechqurun", 30, 0.9),
    (Condition::Diabetes, 44, "kuniga 2 o‘lchov", 25, 1.4),
    (Condition::Thyroid, 13, "1 tabletka och qoringa", 100, 1.4),
    (Condition::Heart, 15, "1 tabletka kuniga", 28, 0.9),
    (Condition::Heart, 16, "1 tabletka kechqurun", 30, 1.4),
    (Condition::Asthma, 17, "kerak bo‘lganda", 45, 0.9),
    (Condition::Asthma, 18, "2 ingalyatsiya kuniga", 30, 0.6),
    (Condition::Asthma, 19, "1 tabletka kechqurun", 28, 0.5),
    (Condition::Pregnancy, 41, "1 tabletka kuniga", 30, 0.7),
    (Condition::Allergy, 27, "1 tabletka kuniga, mavsumda", 10, 0.6),
];

const MALE: &[&str] = &[
    "Aziz", "Bekzod", "Jasur", "Sardor", "Otabek", "Rustam", "Dilshod", "Sherzod", "Ulug‘bek", "Javlon", "Islom", "Temur",
    "Sanjar", "Farrux", "Akmal", "Bobur", "Doniyor", "Eldor", "Shohruh", "Abdulla", "Jamshid", "Nodir", "Anvar", "Behruz",
    "Oybek", "Alisher", "Mirjalol", "Komil", "Hasan", "Ravshan",
];
const FEMALE: &[&str] = &[
    "Dilnoza", "Malika", "Madina", "Nilufar", "Gulnora", "Sevara", "Kamola", "Shahnoza", "Zarina", "Mohira", "Feruza", "Nodira",
    "Lola", "Dildora", "Munisa", "Sabina", "Gulchehra", "Mavluda", "Iroda", "Yulduz", "Barno", "Ozoda", "Durdona", "Charos",
    "Mohinur", "Rayhona", "Nargiza", "Umida", "Saida", "Zulfiya",
];
const SURNAMES: &[&str] = &[
    "Karimov", "Rahimov", "Yusupov", "Abdullayev", "Toshmatov", "Mirzayev", "Nazarov", "Ismoilov", "Qodirov", "Xolmatov",
    "Saidov", "Ergashev", "Sultonov", "Aliyev", "Hasanov", "Umarov", "Rashidov", "Normatov", "Jo‘rayev", "Valiyev",
    "Sobirov", "Tursunov", "Usmonov", "Bakirov", "Fayzullayev", "Hamidov", "Ibragimov", "Latipov", "Mahmudov", "Nurmatov",
];
const RU_MALE: &[&str] = &["Sergey", "Andrey", "Dmitriy", "Aleksandr", "Viktor", "Igor", "Oleg", "Vladimir"];
const RU_FEMALE: &[&str] = &["Elena", "Olga", "Irina", "Svetlana", "Natalya", "Tatyana", "Marina", "Lyudmila"];
const RU_SURNAMES: &[(&str, &str)] = &[
    ("Ivanov", "Ivanova"), ("Petrov", "Petrova"), ("Smirnov", "Smirnova"), ("Kim", "Kim"), ("Li", "Li"), ("Pak", "Pak"),
    ("Tsoy", "Tsoy"), ("Kuznetsov", "Kuznetsova"), ("Sokolov", "Sokolova"),
];
const PHONE_CODES: &[&str] = &["90", "91", "93", "94", "95", "97", "98", "99", "33", "88", "77", "50"];
const TAGS: &[&str] = &["Nafaqaxo‘r", "Ko‘p bolali", "Yosh ona", "Sportchi", "Allergik", "Shifokor", "Talaba", "Yetkazib berish"];

impl Gen {
    fn new(db: &mut Db, _rng: &mut Rng, _now: NaiveDateTime) -> Gen {
        let mut branches = Vec::new();
        for (name, district, address, phone, hue, hours) in BRANCHES {
            let id = db.new_id();
            db.branches.push(Branch {
                id,
                name: (*name).into(),
                district: (*district).into(),
                address: (*address).into(),
                phone: (*phone).into(),
                manager_id: None,
                hue: *hue,
                open_hours: (*hours).into(),
                daybook_id: None,
            });
            branches.push(id);
        }
        let mut g = Gen {
            branches: branches.clone(),
            owner: 0,
            managers: vec![],
            pharmacists: vec![],
            call_agent: 0,
            reps: vec![],
            marketer: 0,
            courier: 0,
        };
        for (i, (name, role, branch, tg, hue)) in STAFF.iter().enumerate() {
            let id = db.new_id();
            db.staff.push(Staff {
                id,
                name: (*name).into(),
                role: *role,
                branch_id: branch.map(|b| branches[b]),
                phone: format!("99890{:07}", 1_234_500 + i as u32 * 7_919),
                telegram: format!("@{tg}"),
                hue: *hue,
                active: true,
                daybook_id: None,
            });
            match role {
                Role::Owner => g.owner = id,
                Role::Manager => {
                    g.managers.push(id);
                    if let Some(b) = branch {
                        db.branches[*b].manager_id = Some(id);
                    }
                }
                Role::Pharmacist => g.pharmacists.push(id),
                Role::CallAgent => g.call_agent = id,
                Role::SalesRep => g.reps.push(id),
                Role::Marketer => g.marketer = id,
                Role::Courier => g.courier = id,
                Role::Cashier => {}
            }
        }
        // the remaining branches are managed by their senior pharmacist
        for (bi, b) in db.branches.iter_mut().enumerate() {
            if b.manager_id.is_none() {
                b.manager_id = g.pharmacists.get(bi).copied();
            }
        }
        db.settings.me = g.owner;
        g
    }

    fn pharmacist_of(&self, db: &Db, branch: Id) -> Id {
        db.staff
            .iter()
            .find(|s| s.role == Role::Pharmacist && s.branch_id == Some(branch))
            .map(|s| s.id)
            .unwrap_or(self.pharmacists[0])
    }

    fn run(&self, db: &mut Db, rng: &mut Rng, now: NaiveDateTime) {
        let today = now.date();
        self.products(db, rng, today);
        let companies = self.companies(db, rng, today);
        self.customers(db, rng, now, &companies);
        self.pipelines_and_deals(db, rng, now, &companies);
        self.leads(db, rng, now);
        self.activities(db, rng, now);
        self.conversations(db, rng, now);
        self.segments(db);
        self.campaigns(db, now);
        self.automations(db, now);
        self.waitlist(db, rng, now);
        self.tickets(db, rng, now);
        self.quotes(db, rng, today, &companies);
        self.goals(db, today);
        self.notes(db, now);
        self.finish(db, now);
    }

    // ------------------------------------------------------------ catalogue

    fn products(&self, db: &mut Db, rng: &mut Rng, today: NaiveDate) {
        for (i, (name, generic, form, origin, cat, rx, price, pop, no_bonus)) in PRODUCTS.iter().enumerate() {
            let id = db.new_id();
            let stock = self
                .branches
                .iter()
                .enumerate()
                .map(|(bi, b)| {
                    // a few holes in stock make the waitlist and the refill radar real
                    let hole = (i * 7 + bi * 3) % 23 == 0 || (*pop <= 2 && rng.chance(0.35));
                    let qty = if hole { 0 } else { (rng.range(4, 18) as u32) * (*pop).max(1) / 2 + rng.range(0, 6) as u32 };
                    BranchStock { branch_id: *b, qty }
                })
                .collect();
            let months = if i % 11 == 3 { rng.range(1, 2) } else { rng.range(4, 30) };
            db.products.push(Product {
                id,
                name: (*name).into(),
                generic: (*generic).into(),
                form: (*form).into(),
                maker: (*origin).into(),
                category: *cat,
                rx: *rx,
                price: *price,
                stock,
                expiry: today + Duration::days(months * 30 + rng.range(0, 25)),
                no_bonus: *no_bonus,
                barcode: format!("478{:010}", 2_400_000_000u64 + i as u64 * 104_729),
                daybook_id: None,
            });
        }
    }

    fn product_id(&self, db: &Db, index: usize) -> Id {
        db.products[index.min(db.products.len() - 1)].id
    }

    // ------------------------------------------------------------ companies

    fn companies(&self, db: &mut Db, rng: &mut Rng, today: NaiveDate) -> Vec<Id> {
        #[allow(clippy::type_complexity)]
        let list: &[(&str, OrgKind, usize, u32, Money, u16, Money, u8, &[(&str, &str)])] = &[
            ("Lazurit Med klinikasi", OrgKind::Clinic, 1, 85, 120_000_000, 30, 38_400_000, 86, &[("Shoira Ahmedova", "Bosh shifokor"), ("Anvar Qosimov", "Ta’minot bo‘limi boshlig‘i")]),
            ("Bodomzor oilaviy poliklinikasi", OrgKind::Clinic, 2, 40, 60_000_000, 21, 12_200_000, 78, &[("Farhod Aminov", "Direktor"), ("Lobar Sodiqova", "Katta hamshira")]),
            ("Oltin Kuz shifoxonasi", OrgKind::Hospital, 0, 420, 350_000_000, 45, 141_500_000, 64, &[("Rahim Yo‘ldoshev", "Bosh vrach o‘rinbosari"), ("Nigora Ermatova", "Dorixona mudiri"), ("Botir Xoliqov", "Buxgalter")]),
            ("Sayhun Tekstil MChJ", OrgKind::Corporate, 3, 1_200, 80_000_000, 30, 0, 72, &[("Olim Murodov", "HR direktori"), ("Zuhra Nabiyeva", "Mehnat muhofazasi")]),
            ("Chorvoq Logistika MChJ", OrgKind::Corporate, 4, 310, 40_000_000, 15, 6_800_000, 81, &[("Sherali Qurbonov", "Operatsion direktor")]),
            ("Zilol Sug‘urta", OrgKind::Insurance, 1, 150, 0, 30, 22_600_000, 90, &[("Gavhar Akbarova", "DMS bo‘limi"), ("Dmitriy Lee", "Hamkorlik menejeri")]),
            ("Olmazor 14-son bog‘chasi", OrgKind::Kindergarten, 5, 35, 10_000_000, 10, 1_400_000, 70, &[("Muattar Rasulova", "Mudira")]),
            ("Kelajak xususiy maktabi", OrgKind::School, 2, 90, 15_000_000, 15, 0, 88, &[("Azamat Tojiboyev", "Direktor"), ("Kamila Ortiqova", "Maktab hamshirasi")]),
            ("Tiniq Farm Distribyutsiya", OrgKind::Distributor, 3, 210, 0, 0, 0, 92, &[("Ilhom Sharipov", "Savdo vakili")]),
            ("Kumush Med Ta’minot", OrgKind::Distributor, 0, 75, 0, 0, 0, 84, &[("Marina Pak", "Menejer")]),
            ("Nurli Diagnostika laboratoriyasi", OrgKind::Lab, 4, 28, 25_000_000, 30, 4_900_000, 75, &[("Javlonbek Usmonov", "Rahbar")]),
            ("Ipak Yo‘li mehmonxonasi", OrgKind::Corporate, 4, 140, 20_000_000, 30, 3_200_000, 66, &[("Aleksandr Ten", "Bosh menejer")]),
            ("Asl Tabassum stomatologiyasi", OrgKind::Clinic, 1, 22, 18_000_000, 21, 7_500_000, 58, &[("Dilshod Ruziyev", "Bosh shifokor")]),
            ("7-son bolalar sport maktabi", OrgKind::Government, 0, 60, 12_000_000, 30, 0, 61, &[("Hamza Ergashev", "Direktor o‘rinbosari")]),
            ("Mehnat Qurilish MChJ", OrgKind::Corporate, 3, 640, 50_000_000, 30, 18_900_000, 49, &[("Bahodir Rahmonov", "Ta’minot"), ("Svetlana Kim", "Buxgalter")]),
            ("Tog‘ Havosi reabilitatsiya markazi", OrgKind::Clinic, 5, 55, 45_000_000, 30, 9_100_000, 83, &[("Ulug‘bek Hakimov", "Direktor")]),
            ("Baraka savdo markazi", OrgKind::Corporate, 1, 380, 15_000_000, 30, 0, 74, &[("Nilufar Ganiyeva", "Ma’muriyat")]),
            ("Yangi Avlod tug‘ruqdan oldingi markazi", OrgKind::Clinic, 2, 18, 8_000_000, 14, 0, 79, &[("Mohira Salimova", "Akusher-ginekolog")]),
        ];
        let mut ids = Vec::new();
        for (i, (name, kind, branch, employees, limit, terms, receivable, health, contacts)) in list.iter().enumerate() {
            let id = db.new_id();
            let owner = if *kind == OrgKind::Distributor { self.owner } else { self.reps[i % self.reps.len()] };
            db.companies.push(Company {
                id,
                name: (*name).into(),
                kind: *kind,
                tin: format!("{}", 302_114_000 + i as u64 * 7_331),
                district: BRANCHES[*branch].1.into(),
                address: format!("{}, {}-uy", BRANCHES[*branch].1, 4 + i * 3),
                phone: format!("+998 71 2{:02} {:02} {:02}", 30 + i, 10 + (i * 7) % 89, 11 + (i * 13) % 88),
                email: format!("info@{}.uz", name.split_whitespace().next().unwrap_or("org").to_lowercase().replace(['‘', '’'], "")),
                owner_id: Some(owner),
                credit_limit: *limit,
                terms_days: *terms,
                receivable: *receivable,
                tags: match kind {
                    OrgKind::Clinic | OrgKind::Hospital => vec!["Tibbiyot".into()],
                    OrgKind::Corporate => vec!["Korporativ".into()],
                    OrgKind::Distributor => vec!["Yetkazuvchi".into()],
                    _ => vec![],
                },
                created: today - Duration::days(rng.range(60, 700)),
                employees: *employees,
                contacts: contacts
                    .iter()
                    .enumerate()
                    .map(|(ci, (n, pos))| ContactPerson {
                        name: (*n).into(),
                        position: (*pos).into(),
                        phone: format!("99893{:07}", 4_400_000 + i as u32 * 1_201 + ci as u32 * 77),
                        telegram: if ci == 0 { Some(format!("@{}", n.split_whitespace().next().unwrap_or("x").to_lowercase().replace(['‘', '’'], ""))) } else { None },
                        primary: ci == 0,
                    })
                    .collect(),
                notes: String::new(),
                health: *health,
                daybook_id: None,
            });
            ids.push(id);
        }
        ids
    }

    // ------------------------------------------------------------ customers and their purchases

    fn customers(&self, db: &mut Db, rng: &mut Rng, now: NaiveDateTime, companies: &[Id]) {
        let today = now.date();
        let branch_w = [3.0, 2.6, 2.0, 1.6, 1.4, 1.0];
        let source_w = [(Source::WalkIn, 4.0), (Source::Telegram, 2.2), (Source::Instagram, 1.0), (Source::Referral, 1.2), (Source::Doctor, 1.0), (Source::Website, 0.5), (Source::Call, 0.7), (Source::Corporate, 0.6), (Source::Qr, 1.4)];
        let corporate: Vec<Id> = companies
            .iter()
            .copied()
            .filter(|id| db.company(*id).map(|c| c.kind == OrgKind::Corporate).unwrap_or(false))
            .collect();
        let popularity: Vec<f64> = PRODUCTS.iter().map(|p| if p.5 { p.7 as f64 * 0.25 } else { p.7 as f64 }).collect();
        for i in 0..320usize {
            let female = rng.chance(0.6);
            let russian = rng.chance(0.2);
            let (first, last) = if russian {
                let s = rng.pick(RU_SURNAMES);
                if female {
                    (rng.pick(RU_FEMALE).to_string(), s.1.to_string())
                } else {
                    (rng.pick(RU_MALE).to_string(), s.0.to_string())
                }
            } else {
                let s = rng.pick(SURNAMES).to_string();
                if female {
                    (rng.pick(FEMALE).to_string(), format!("{s}a"))
                } else {
                    (rng.pick(MALE).to_string(), s)
                }
            };
            let age = match rng.weighted(&[2.0, 3.0, 2.8, 2.2]) {
                0 => rng.range(18, 29),
                1 => rng.range(30, 44),
                2 => rng.range(45, 59),
                _ => rng.range(60, 84),
            };
            let birth = NaiveDate::from_ymd_opt(today.year() - age as i32, 1, 1).unwrap() + Duration::days(rng.range(0, 364));
            let created = today - Duration::days((rng.f().powf(1.45) * 780.0) as i64);
            let bi = rng.weighted(&branch_w);
            let home = self.branches[bi];
            let source = source_w[rng.weighted(&source_w.iter().map(|x| x.1).collect::<Vec<_>>())].0;
            let has_tg = rng.chance(0.7);
            let chronic = age >= 40 && rng.chance(0.55) || rng.chance(0.08);
            let mut regimens = Vec::new();
            if chronic {
                let n = 1 + rng.weighted(&[5.0, 3.0, 1.2]);
                let weights: Vec<f64> = THERAPIES.iter().map(|t| t.4).collect();
                for _ in 0..n {
                    let t = THERAPIES[rng.weighted(&weights)];
                    if t.0 == Condition::Pregnancy && (!female || age > 42) {
                        continue;
                    }
                    let pid = self.product_id(db, t.1);
                    if regimens.iter().any(|r: &Regimen| r.product_id == pid) {
                        continue;
                    }
                    regimens.push(Regimen { product_id: pid, condition: t.0, dose: t.2.into(), pack_days: t.3, last_bought: created, remind: true });
                }
            }
            let health_consent = !regimens.is_empty() && rng.chance(0.92);
            let mut tags: Vec<String> = Vec::new();
            if age >= 62 && rng.chance(0.7) {
                tags.push(TAGS[0].into());
            }
            if rng.chance(0.18) {
                let t = TAGS[1 + rng.below(TAGS.len() - 1)];
                if !(t == "Yosh ona" && (!female || age > 40)) {
                    tags.push(t.into());
                }
            }
            let id = db.new_id();
            let phone = format!("998{}{:07}", rng.pick(PHONE_CODES), rng.range(1_000_000, 9_999_999));
            let owner = if rng.chance(0.75) { Some(self.pharmacist_of(db, home)) } else { Some(self.call_agent) };
            db.customers.push(Customer {
                id,
                first_name: first.clone(),
                last_name: last,
                gender: if female { Gender::Female } else { Gender::Male },
                phone,
                telegram: if has_tg { Some(format!("@{}{}", first.to_lowercase().replace(['‘', '’'], ""), rng.range(10, 999))) } else { None },
                birth_date: if rng.chance(0.9) { Some(birth) } else { None },
                district: BRANCHES[bi].1.into(),
                home_branch: home,
                owner_id: owner,
                tags,
                tier: Tier::Bronze,
                points: if source == Source::Qr || rng.chance(0.3) { db.settings.loyalty.welcome_bonus } else { 0 },
                card_no: format!("7801 {:04} {:04}", 1000 + (i * 37) % 9000, rng.range(1000, 9999)),
                source,
                consent: Consent {
                    sms: rng.chance(0.62),
                    telegram: has_tg && rng.chance(0.86),
                    health_data: health_consent,
                    given_on: Some(created),
                },
                regimens: if health_consent { regimens.clone() } else { vec![] },
                allergies: if health_consent && rng.chance(0.15) { vec![rng.pick(&["Penitsillin", "Sulfanilamidlar", "Aspirin", "Laktoza"]).to_string()] } else { vec![] },
                company_id: if source == Source::Corporate || rng.chance(0.05) { Some(*rng.pick(&corporate)) } else { None },
                created,
                lang: if russian || rng.chance(0.08) { Lang::Ru } else { Lang::Uz },
                notes: String::new(),
                nps: if rng.chance(0.4) { Some([10, 10, 9, 9, 9, 8, 8, 7, 6, 4][rng.below(10)]) } else { None },
                total_spent: 0,
                orders: 0,
                first_purchase: None,
                last_purchase: None,
                archived: false,
                referred_by: None,
            });

            // purchases
            let churned = rng.chance(0.13);
            let mut dates: Vec<(NaiveDate, Vec<usize>)> = Vec::new();
            for r in &regimens {
                let start = created.max(today - Duration::days(430));
                let mut d = if churned {
                    today - Duration::days(rng.range(48, 170))
                } else {
                    today - Duration::days(rng.range(0, r.pack_days as i64 + 4))
                };
                let pidx = db.products.iter().position(|p| p.id == r.product_id).unwrap_or(0);
                while d >= start {
                    dates.push((d, vec![pidx]));
                    d -= Duration::days(r.pack_days as i64 + rng.range(-3, 3));
                }
            }
            let extra = match rng.weighted(&[5.5, 3.5, 1.0]) {
                0 => rng.range(2, 6),
                1 => rng.range(6, 16),
                _ => rng.range(16, 40),
            };
            let last_active = if churned { today - Duration::days(rng.range(60, 260)) } else { today };
            let span = (last_active - created).num_days().max(1);
            let extra = extra.min(span / 9 + 1);
            for _ in 0..extra {
                let d = created + Duration::days((rng.f().powf(0.95) * span as f64) as i64);
                let n = 1 + rng.weighted(&[5.0, 3.0, 1.2, 0.4]);
                let items: Vec<usize> = (0..n).map(|_| rng.weighted(&popularity)).collect();
                dates.push((d, items));
            }
            dates.sort_by_key(|x| x.0);
            for (d, items) in dates {
                if d > today {
                    continue;
                }
                let mut lines: Vec<LineItem> = Vec::new();
                for idx in items {
                    let p = &db.products[idx];
                    if let Some(l) = lines.iter_mut().find(|l| l.product_id == p.id) {
                        l.qty += 1;
                    } else {
                        lines.push(LineItem { product_id: p.id, qty: 1, price: p.price, discount_pct: 0 });
                    }
                }
                if rng.chance(0.25) {
                    let p = &db.products[rng.weighted(&popularity)];
                    if !lines.iter().any(|l| l.product_id == p.id) {
                        lines.push(LineItem { product_id: p.id, qty: 1, price: p.price, discount_pct: 0 });
                    }
                }
                let branch = if rng.chance(0.86) { home } else { *rng.pick(&self.branches) };
                let gross: Money = lines.iter().map(LineItem::total).sum();
                let points = db.customer(id).map(|c| c.points).unwrap_or(0);
                let used = if points >= 20_000 && rng.chance(0.14) { points.min(gross * 30 / 100) } else { 0 };
                let hour = 8 + rng.range(0, 13) as u32;
                let channel = match rng.weighted(&[82.0, 8.0, 6.0, 4.0]) {
                    0 => SaleChannel::InStore,
                    1 => SaleChannel::Delivery,
                    2 => SaleChannel::Pickup,
                    _ => SaleChannel::TelegramOrder,
                };
                let cashier = Some(self.pharmacist_of(db, branch));
                let at_time = if d == today { at(d, (now.time().format("%H").to_string().parse::<u32>().unwrap_or(12)).saturating_sub(1).max(8), rng.range(0, 59) as u32) } else { at(d, hour, rng.range(0, 59) as u32) };
                db.add_purchase(Purchase {
                    id: 0,
                    customer_id: id,
                    branch_id: branch,
                    at: at_time,
                    items: lines,
                    total: 0,
                    points_earned: 0,
                    points_used: used,
                    channel,
                    cashier_id: cashier,
                });
            }
        }
        // referrals: a few customers brought friends
        let n = db.customers.len();
        for k in 0..24 {
            let a = (k * 37 + 11) % n;
            let b = (k * 53 + 5) % n;
            if a != b {
                let referrer = db.customers[b].id;
                db.customers[a].referred_by = Some(referrer);
                db.customers[a].source = Source::Referral;
            }
        }
        // two loyal customers the demo story uses
        if let Some(c) = db.customers.iter_mut().find(|c| c.gender == Gender::Female && c.regimens.len() >= 2) {
            c.first_name = "Gulchehra".into();
            c.last_name = "Karimova".into();
            c.tags = vec!["Nafaqaxo‘r".into(), "VIP".into()];
            c.notes = "Faqat ertalab qo‘ng‘iroq qiling. Insulinni sovutgich sumkada yetkazish kerak.".into();
        }
    }

    // ------------------------------------------------------------ deals

    fn pipelines_and_deals(&self, db: &mut Db, rng: &mut Rng, now: NaiveDateTime, companies: &[Id]) {
        let today = now.date();
        let defs: &[(&str, &str, &[(&str, u8, u16, u16)])] = &[
            ("B2B ta’minot", "building-2", &[
                ("Yangi so‘rov", 10, 3, 210),
                ("Ehtiyoj aniqlandi", 25, 5, 190),
                ("Taklif yuborildi", 45, 7, 38),
                ("Muzokara", 65, 7, 24),
                ("Shartnoma imzolanmoqda", 85, 5, 145),
            ]),
            ("Korporativ salomatlik", "briefcase", &[
                ("Qiziqish", 10, 5, 265),
                ("Uchrashuv", 30, 7, 230),
                ("Dastur taklifi", 55, 7, 38),
                ("Tasdiqlash", 80, 5, 145),
            ]),
            ("Maxsus buyurtma", "package", &[
                ("So‘rov qabul qilindi", 30, 1, 205),
                ("Yetkazuvchi qidirilmoqda", 50, 2, 38),
                ("Buyurtma berildi", 75, 5, 24),
                ("Keldi, mijozga xabar", 90, 1, 145),
            ]),
        ];
        for (name, icon, stages) in defs {
            let id = db.new_id();
            let stages = stages
                .iter()
                .map(|(n, p, rot, hue)| Stage { id: 0, name: (*n).into(), probability: *p, rot_days: *rot, hue: *hue })
                .collect::<Vec<_>>();
            let mut p = Pipeline { id, name: (*name).into(), icon: (*icon).into(), stages };
            for s in p.stages.iter_mut() {
                s.id = db.new_id();
            }
            db.pipelines.push(p);
        }
        let b2b = db.pipelines[0].clone();
        let corp = db.pipelines[1].clone();
        let special = db.pipelines[2].clone();

        // (pipeline, company index or None, title, value, stage index or 9 = won / 8 = lost, idle days)
        let deals: &[(usize, Option<usize>, &str, Money, usize, i64)] = &[
            (0, Some(0), "Choraklik sarflov materiallari ta’minoti", 85_000_000, 3, 2),
            (0, Some(1), "Insulin va diabet vositalari: yillik shartnoma", 146_000_000, 2, 9),
            (0, Some(2), "Shifoxona dorixonasi uchun antibiotiklar", 230_000_000, 4, 1),
            (0, Some(10), "Test-poloskalar va lansetlar", 24_000_000, 1, 4),
            (0, Some(12), "Stomatologiya anestetiklari", 16_500_000, 2, 11),
            (0, Some(6), "Bog‘cha uchun vitaminlar va birinchi yordam", 7_800_000, 0, 1),
            (0, Some(7), "Maktab tibbiyot xonasi jihozlari", 12_400_000, 1, 2),
            (0, Some(13), "Sport maktabi: shikastlanishga qarshi vositalar", 9_600_000, 0, 5),
            (0, Some(15), "Reabilitatsiya: og‘riq qoldiruvchi va bandajlar", 38_000_000, 3, 3),
            (0, Some(17), "Homiladorlar uchun vitaminlar to‘plami", 11_200_000, 2, 1),
            (0, Some(0), "Laboratoriya sarflovlari: II chorak", 41_000_000, 9, 20),
            (0, Some(2), "Reanimatsiya bo‘limi uchun infuzion eritmalar", 96_000_000, 9, 6),
            (0, Some(12), "Bir martalik shpritslar", 6_200_000, 8, 30),
            (0, Some(10), "Qon olish probirkalari", 18_000_000, 8, 45),
            (1, Some(5), "Zilol Sug‘urta: DMS bo‘yicha hamkorlik", 180_000_000, 2, 3),
            (1, Some(3), "Sayhun Tekstil: xodimlar uchun chegirma kartalari", 60_000_000, 3, 1),
            (1, Some(3), "Sayhun Tekstil: 3 sex uchun aptechkalar", 14_000_000, 9, 12),
            (1, Some(4), "Chorvoq Logistika: haydovchilar aptechkalari", 8_900_000, 1, 8),
            (1, Some(14), "Mehnat Qurilish: qurilish maydonlari aptechkalari", 22_000_000, 2, 10),
            (1, Some(11), "Ipak Yo‘li: mehmonlar uchun dorilar to‘plami", 6_400_000, 0, 2),
            (1, Some(16), "Baraka savdo markazi: tibbiyot xonasi", 11_000_000, 1, 1),
            (1, Some(3), "Gripp mavsumi: sexlarda salomatlik kuni", 18_000_000, 9, 3),
            (1, Some(14), "Mehnat Qurilish: issiq urishiga qarshi to‘plam", 9_500_000, 8, 60),
            (1, Some(4), "Chorvoq Logistika: yillik tibbiy ko‘rik hamkorligi", 27_000_000, 3, 6),
            (2, None, "Semaglutid 1 mg: 3 oylik kurs", 4_200_000, 1, 1),
            (2, None, "Levetiratsetam 1000 mg: import buyurtma", 2_800_000, 2, 3),
            (2, None, "Insulin pompasi sarflov materiallari", 6_500_000, 0, 0),
            (2, None, "Laktozasiz bolalar aralashmasi", 1_900_000, 3, 0),
            (2, None, "Import ko‘z tomchisi (glaukoma)", 900_000, 2, 1),
            (2, None, "Ortopedik bandaj: individual o‘lcham", 1_400_000, 9, 2),
            (2, None, "Gepatit C kursi: buyurtma", 7_800_000, 9, 5),
            (2, None, "Noyob antibiotik: Tsefiksim suspenziya", 650_000, 8, 14),
        ];
        let reasons = ["Narx yuqori", "Raqobatchi arzonroq taklif berdi", "Byudjet qisqardi", "Javob bermay qo‘ydi", "Muddati to‘g‘ri kelmadi"];
        let mut special_customers = db.customers.iter().filter(|c| c.orders >= 8).map(|c| c.id).collect::<Vec<_>>();
        special_customers.truncate(12);
        for (k, (pi, company, title, value, stage, idle)) in deals.iter().enumerate() {
            let pipe = match pi {
                0 => &b2b,
                1 => &corp,
                _ => &special,
            };
            let won = *stage == 9;
            let lost = *stage == 8;
            let st = if won || lost { pipe.stages.len() - 1 } else { (*stage).min(pipe.stages.len() - 1) };
            let created = now - Duration::days(rng.range(*idle + 3, *idle + 50));
            let last = now - Duration::days(*idle) - Duration::hours(rng.range(0, 8));
            let closed = if won || lost { Some(last) } else { None };
            let owner = if *pi == 2 { self.call_agent } else { self.reps[k % self.reps.len()] };
            let id = db.new_id();
            let lines = if *pi == 0 && k % 3 == 0 {
                // a few deals carry product lines (quotes are built from them)
                let picks = [0usize, 8, 44, 25, 22];
                picks
                    .iter()
                    .take(3 + k % 3)
                    .map(|i| {
                        let p = &db.products[*i];
                        let qty = ((*value / 4) / p.price.max(1)).clamp(10, 5_000) as u32;
                        LineItem { product_id: p.id, qty, price: p.price, discount_pct: [5, 8, 10][k % 3] }
                    })
                    .collect()
            } else {
                vec![]
            };
            db.deals.push(Deal {
                id,
                title: (*title).into(),
                pipeline_id: pipe.id,
                stage_id: pipe.stages[st].id,
                company_id: company.map(|c| companies[c]),
                customer_id: if company.is_none() { special_customers.get(k % special_customers.len().max(1)).copied() } else { None },
                value: *value,
                owner_id: owner,
                created,
                stage_since: last - Duration::days(rng.range(0, 3)),
                last_activity: last,
                expected_close: today + Duration::days(rng.range(-3, 55)),
                status: if won {
                    DealStatus::Won
                } else if lost {
                    DealStatus::Lost
                } else {
                    DealStatus::Open
                },
                lost_reason: if lost { Some(reasons[k % reasons.len()].into()) } else { None },
                lines,
                source: if *pi == 2 { Source::Telegram } else { [Source::Referral, Source::Call, Source::Website, Source::Doctor][k % 4] },
                tags: vec![],
                next_step: match st {
                    0 => "Ehtiyojni aniqlash uchun qo‘ng‘iroq".into(),
                    1 => "Narx taklifini tayyorlash".into(),
                    2 => "Taklif bo‘yicha fikr so‘rash".into(),
                    3 => "Chegirma bo‘yicha kelishish".into(),
                    _ => "Shartnomani imzolash".into(),
                },
                closed_at: closed,
                priority: if *value >= 100_000_000 { Priority::High } else { Priority::Normal },
            });
        }
    }

    // ------------------------------------------------------------ leads

    fn leads(&self, db: &mut Db, rng: &mut Rng, now: NaiveDateTime) {
        let list: &[(&str, Channel, &str, &str, Option<&str>, Money, u8, LeadStatus, i64)] = &[
            ("Shohruh Abdurahmonov", Channel::Telegram, "Assalomu alaykum! 40 kishilik ofisimiz uchun aptechka va oylik dori ta’minoti kerak edi.", "Korporativ aptechka", Some("Silk Media agentligi"), 3_500_000, 82, LeadStatus::New, 25),
            ("Sog‘lom Yurak kardiologiya markazi", Channel::Web, "Klinikamiz uchun oylik sarflov materiallari bo‘yicha tijorat taklifi yuboring.", "B2B ta’minot", Some("Sog‘lom Yurak kardiologiya markazi"), 40_000_000, 88, LeadStatus::New, 190),
            ("Dilfuza", Channel::Instagram, "Vitamin D3 2000 bormi? Narxi qancha?", "D3 vitamini", None, 85_000, 38, LeadStatus::New, 45),
            ("Andrey Lim", Channel::Telegram, "Здравствуйте, есть ли у вас Монтелукаст 10 мг? Нужно 2 упаковки.", "Montelukast", None, 192_000, 55, LeadStatus::New, 300),
            ("Algoritm Soft", Channel::Web, "Корпоративное сотрудничество для IT-компании на 120 человек: скидки и доставка в офис.", "Korporativ salomatlik", Some("Algoritm Soft"), 24_000_000, 79, LeadStatus::New, 160),
            ("Bahrom aka", Channel::Phone, "Insulin glargin doimiy kerak bo‘ladi, har oy uyga yetkazib berasizmi?", "Insulin yetkazib berish", None, 4_900_000, 74, LeadStatus::New, 95),
            ("Zebiniso", Channel::Telegram, "Homiladorlar uchun vitaminlar haqida maslahat kerak", "Homiladorlik vitaminlari", None, 340_000, 47, LeadStatus::New, 12),
            ("Markaziy bozor do‘konlari", Channel::Phone, "Do‘kondorlar uchun chegirmali dori kartasi bormi?", "Korporativ karta", Some("Markaziy bozor do‘konlari"), 9_000_000, 61, LeadStatus::New, 240),
            ("Aziza Qosimova", Channel::Instagram, "Atopik teri uchun krem tavsiya qiling, bolam 2 yoshda", "Emolent krem", None, 175_000, 42, LeadStatus::New, 70),
            ("Orzu Fitness", Channel::Web, "Zalimiz a’zolari uchun sport vitaminlari va aptechka bo‘yicha hamkorlik", "Korporativ salomatlik", Some("Orzu Fitness"), 7_500_000, 66, LeadStatus::Contacted, 600),
            ("Jamshid", Channel::Telegram, "Glyukometr va 3 oylik test-poloska narxi?", "Diabet to‘plami", None, 785_000, 68, LeadStatus::Contacted, 900),
            ("Natalya Ten", Channel::Phone, "Нужна доставка лекарств для мамы раз в месяц, она не выходит из дома.", "Oylik yetkazib berish", None, 1_200_000, 77, LeadStatus::Contacted, 1500),
            ("Nur Ota-Ona maktabi", Channel::Email, "Bolalar uchun birinchi yordam darsiga farmatsevt taklif qilmoqchimiz", "Hamkorlik", Some("Nur Ota-Ona maktabi"), 2_000_000, 52, LeadStatus::Contacted, 2600),
            ("Mirzo Med xususiy klinikasi", Channel::Web, "Har oy 200 dona insulin shprits-ruchkasi va ignalar kerak", "B2B ta’minot", Some("Mirzo Med xususiy klinikasi"), 32_000_000, 91, LeadStatus::Qualified, 3000),
            ("Sardorbek", Channel::Web, "Sodiqlik kartasini ochmoqchiman", "Sodiqlik kartasi", None, 0, 35, LeadStatus::Qualified, 400),
            ("Yangi Hayot nogironlar jamiyati", Channel::Email, "A’zolarimiz uchun doimiy chegirma imkoniyati", "Ijtimoiy hamkorlik", Some("Yangi Hayot jamiyati"), 15_000_000, 70, LeadStatus::Qualified, 4300),
            ("Ra’no", Channel::Telegram, "Tug‘ruqdan keyingi vitaminlar bormi?", "Vitaminlar", None, 168_000, 45, LeadStatus::Qualified, 5000),
            ("Ozoda Raximova", Channel::Telegram, "Bonuslarim qancha qolgan?", "Sodiqlik", None, 0, 22, LeadStatus::Converted, 6200),
            ("Temur Saidov", Channel::Phone, "Bisoprolol 5 mg bron qilish", "Bron", None, 46_000, 40, LeadStatus::Converted, 7000),
            ("Viktoriya", Channel::Instagram, "Quyoshdan himoya kremi SPF 50 bormi?", "Kosmetika", None, 210_000, 36, LeadStatus::Converted, 8800),
            ("Spam Bot", Channel::Web, "Biz sizga SEO xizmatlarini taklif qilamiz", "—", None, 0, 2, LeadStatus::Junk, 9000),
            ("Noma’lum raqam", Channel::Phone, "Qo‘ng‘iroq uzildi", "—", None, 0, 5, LeadStatus::Junk, 11000),
        ];
        for (k, (name, channel, msg, interest, company, estimate, score, status, minutes_ago)) in list.iter().enumerate() {
            let id = db.new_id();
            db.leads.push(Lead {
                id,
                name: (*name).into(),
                phone: format!("998{}{:07}", PHONE_CODES[k % PHONE_CODES.len()], 2_000_000 + k as u32 * 345_677 % 7_000_000),
                channel: *channel,
                message: (*msg).into(),
                interest: (*interest).into(),
                at: now - Duration::minutes(*minutes_ago),
                status: *status,
                owner_id: if *status == LeadStatus::New && k % 3 == 0 { None } else { Some(if company.is_some() { self.reps[k % 2] } else { self.call_agent }) },
                score: *score,
                company_name: company.map(|c| c.to_string()),
                estimate: *estimate,
                converted_customer: if *status == LeadStatus::Converted { db.customers.get(k * 3).map(|c| c.id) } else { None },
                converted_deal: None,
            });
            let _ = rng.f();
        }
    }

    // ------------------------------------------------------------ activities

    fn activities(&self, db: &mut Db, rng: &mut Rng, now: NaiveDateTime) {
        let today = now.date();
        let deal_ids: Vec<(Id, Option<Id>, Id)> =
            db.deals.iter().filter(|d| d.status == DealStatus::Open).map(|d| (d.id, d.company_id, d.owner_id)).collect();
        // the owner's day: what "Today" opens with
        let me = self.owner;
        let mine: &[(ActivityKind, &str, u32, u32, i64, Priority, usize)] = &[
            (ActivityKind::Call, "Lazurit Med: taklif bo‘yicha fikr so‘rash", 10, 0, 0, Priority::High, 0),
            (ActivityKind::Meeting, "Oltin Kuz shifoxonasi: shartnoma bo‘yicha uchrashuv", 11, 30, 0, Priority::Urgent, 2),
            (ActivityKind::Task, "Qishki aksiya uchun segmentni tasdiqlash", 14, 0, 0, Priority::Normal, 99),
            (ActivityKind::Call, "Zilol Sug‘urta: DMS shartlari", 15, 30, 0, Priority::High, 14),
            (ActivityKind::Task, "Sayhun Tekstil shartnomasini ko‘rib chiqish", 17, 30, 0, Priority::Normal, 15),
            (ActivityKind::Task, "Yunusobod filiali: defektura ro‘yxatini tekshirish", 9, 0, -1, Priority::Normal, 99),
            (ActivityKind::Call, "Mehnat Qurilish: qarzdorlik bo‘yicha", 16, 0, -2, Priority::High, 18),
            (ActivityKind::Meeting, "Tiniq Farm: yangi narxlar", 10, 0, 1, Priority::Normal, 99),
            (ActivityKind::Visit, "Bodomzor poliklinikasiga tashrif", 12, 0, 2, Priority::High, 1),
            (ActivityKind::Task, "Oylik hisobotni Daybook’ga yuborish", 18, 0, 3, Priority::Normal, 99),
            (ActivityKind::Call, "Chorvoq Logistika: tibbiy ko‘rik taklifi", 11, 0, 4, Priority::Normal, 23),
        ];
        for (kind, title, h, m, day, prio, deal_idx) in mine {
            let deal = db.deals.get(*deal_idx).map(|d| (d.id, d.company_id));
            db.add_activity(Activity {
                id: 0,
                kind: *kind,
                title: (*title).into(),
                notes: String::new(),
                due: at(today + Duration::days(*day), *h, *m),
                done: false,
                done_at: None,
                owner_id: me,
                customer_id: None,
                company_id: deal.and_then(|d| d.1),
                deal_id: deal.map(|d| d.0),
                ticket_id: None,
                priority: *prio,
                outcome: None,
                duration_min: if *kind == ActivityKind::Meeting { 60 } else { 15 },
                daybook_task: None,
            });
        }
        // refill calls by the call centre and pharmacists, done over the last month
        let outcomes = ["Eslatildi, ertaga keladi", "Bron qilindi", "Javob bermadi", "Yetkazib berish so‘radi", "Boshqa dorixonadan oldi", "Dori o‘zgartirildi, shifokor yozdi"];
        let refill_customers: Vec<(Id, Id)> =
            db.customers.iter().filter(|c| !c.regimens.is_empty()).map(|c| (c.id, c.home_branch)).take(90).collect();
        for (k, (cid, branch)) in refill_customers.iter().enumerate() {
            let owner = if k % 3 == 0 { self.call_agent } else { self.pharmacist_of(db, *branch) };
            let past = k % 5 != 0;
            let due = if past {
                now - Duration::days(rng.range(0, 28)) - Duration::hours(rng.range(1, 6))
            } else {
                at(today + Duration::days(rng.range(0, 5)), 9 + rng.range(0, 8) as u32, [0, 15, 30, 45][k % 4])
            };
            let name = db.customer_name(Some(*cid));
            db.add_activity(Activity {
                id: 0,
                kind: ActivityKind::Call,
                title: format!("{name}: dori eslatmasi"),
                notes: String::new(),
                due,
                done: past,
                done_at: if past { Some(due + Duration::minutes(4)) } else { None },
                owner_id: owner,
                customer_id: Some(*cid),
                company_id: None,
                deal_id: None,
                ticket_id: None,
                priority: Priority::Normal,
                outcome: if past { Some(outcomes[k % outcomes.len()].into()) } else { None },
                duration_min: 3 + (k % 5) as u16,
                daybook_task: None,
            });
        }
        // B2B follow-ups by the reps
        for (k, (deal, company, owner)) in deal_ids.iter().enumerate() {
            for j in 0..2 {
                let past = j == 0;
                let due = if past { now - Duration::days(rng.range(1, 20)) } else { at(today + Duration::days(rng.range(-1, 7)), 10 + (k % 7) as u32, 0) };
                let kind = [ActivityKind::Call, ActivityKind::Email, ActivityKind::Meeting, ActivityKind::Visit][(k + j) % 4];
                db.add_activity(Activity {
                    id: 0,
                    kind,
                    title: if past { "Taklif muhokamasi".into() } else { "Keyingi qadam: kelishuvni yakunlash".into() },
                    notes: String::new(),
                    due,
                    done: past,
                    done_at: if past { Some(due) } else { None },
                    owner_id: *owner,
                    customer_id: None,
                    company_id: *company,
                    deal_id: Some(*deal),
                    ticket_id: None,
                    priority: Priority::Normal,
                    outcome: if past { Some("Qiziqish bildirdi, narxni kutmoqda".into()) } else { None },
                    duration_min: 20,
                    daybook_task: None,
                });
            }
        }
        // courier deliveries today and tomorrow
        let delivery_customers: Vec<Id> = db.customers.iter().filter(|c| c.tags.iter().any(|t| t == "Yetkazib berish" || t == "Nafaqaxo‘r")).map(|c| c.id).take(6).collect();
        for (k, cid) in delivery_customers.iter().enumerate() {
            let name = db.customer_name(Some(*cid));
            db.add_activity(Activity {
                id: 0,
                kind: ActivityKind::Delivery,
                title: format!("{name}: buyurtmani yetkazish"),
                notes: "Naqd to‘lov".into(),
                due: at(today + Duration::days((k / 4) as i64), 12 + k as u32, 0),
                done: false,
                done_at: None,
                owner_id: self.courier,
                customer_id: Some(*cid),
                company_id: None,
                deal_id: None,
                ticket_id: None,
                priority: Priority::Normal,
                outcome: None,
                duration_min: 40,
                daybook_task: None,
            });
        }
    }

    // ------------------------------------------------------------ inbox

    fn conversations(&self, db: &mut Db, rng: &mut Rng, now: NaiveDateTime) {
        // (customer pick, channel, assigned pharmacist index, status, unread, messages: (inbound, minutes ago, kind, text))
        type Thread = (usize, Channel, usize, ConvStatus, u16, &'static [(bool, i64, MsgKind, &'static str)]);
        let threads: &[Thread] = &[
            (3, Channel::Telegram, 0, ConvStatus::Open, 2, &[
                (true, 48, MsgKind::Text, "Assalomu alaykum! Amlodipin 10 mg bormi? Yunusobod filialida"),
                (false, 44, MsgKind::Text, "Va alaykum assalom! Ha, Yunusobodda bor, 24 000 so‘m. Bron qilib qo‘yaymi?"),
                (true, 41, MsgKind::Text, "Ha, iltimos 2 ta. Kechqurun olib ketaman"),
                (true, 38, MsgKind::Photo, "Retsept rasmi"),
            ]),
            (7, Channel::Telegram, 1, ConvStatus::Open, 1, &[
                (true, 15, MsgKind::Text, "Здравствуйте! Инсулин гларгин пришёл? Я записывалась в дефектуру"),
            ]),
            (12, Channel::WhatsApp, 2, ConvStatus::Open, 0, &[
                (true, 300, MsgKind::Text, "Onamga qon bosimi o‘lchagich olmoqchiman, qaysi birini tavsiya qilasiz?"),
                (false, 290, MsgKind::Text, "Yelkaga taqiladigan avtomatik tonometr aniqroq. Hozir 520 000 so‘m, 2 yil kafolat bilan."),
                (true, 286, MsgKind::Text, "Yetkazib bera olasizmi? Sergeli"),
                (false, 280, MsgKind::Text, "Albatta, bugun 18:00 gacha yetkazamiz. Yetkazish bepul."),
                (false, 279, MsgKind::Note, "Kuryer Ulug‘bekka topshirildi"),
            ]),
            (18, Channel::Telegram, 3, ConvStatus::Pending, 0, &[
                (true, 1500, MsgKind::Text, "Bonuslarim nechta? Karta raqamim 7801…"),
                (false, 1490, MsgKind::Text, "Hisobingizda 48 200 ball bor. Keyingi xariddan 30% gacha to‘lashingiz mumkin 🙂"),
                (true, 1480, MsgKind::Text, "Rahmat!"),
            ]),
            (25, Channel::Instagram, 4, ConvStatus::Open, 3, &[
                (true, 95, MsgKind::Text, "Salom! Bolaga atopik dermatit uchun krem kerak"),
                (true, 94, MsgKind::Text, "2 yoshda"),
                (true, 70, MsgKind::Photo, "Teri rasmi"),
            ]),
            (31, Channel::Sms, 5, ConvStatus::Resolved, 0, &[
                (false, 4000, MsgKind::Text, "Hurmatli mijoz! Metformin 850 mg dori zaxirangiz 3 kunda tugaydi. Oydin Farm: bron uchun 1-tugmani bosing."),
                (true, 3950, MsgKind::Text, "1"),
                (false, 3949, MsgKind::System, "Bron yaratildi: Chilonzor filiali"),
            ]),
            (40, Channel::Telegram, 0, ConvStatus::Open, 1, &[
                (true, 600, MsgKind::Text, "Kecha olgan dorimdan keyin toshma chiqdi, nima qilay?"),
                (false, 590, MsgKind::Text, "Dorini hozircha to‘xtating. Qaysi dori va qachon ichdingiz? Farmatsevtimiz qo‘ng‘iroq qiladi."),
                (true, 580, MsgKind::Text, "Amoksitsillin, kecha kechqurun"),
                (false, 575, MsgKind::Note, "Nojo‘ya ta’sir murojaati ochildi, provizor qo‘ng‘iroq qiladi"),
                (true, 32, MsgKind::Text, "Rahmat, hozir yaxshiroq. Shifokorga bordim"),
            ]),
            (47, Channel::Phone, 6, ConvStatus::Resolved, 0, &[
                (true, 2900, MsgKind::Voice, "Ovozli xabar, 0:42"),
                (false, 2880, MsgKind::Text, "Qo‘ng‘iroq: Omega-3 va D3 bron qilindi, ertaga olib ketadi."),
            ]),
            (55, Channel::Telegram, 2, ConvStatus::Open, 2, &[
                (true, 140, MsgKind::Text, "Qanday qilib Telegram orqali buyurtma beraman?"),
                (true, 139, MsgKind::Text, "Ro‘yxatni yozsam bo‘ladimi?"),
            ]),
            (63, Channel::Email, 1, ConvStatus::Pending, 0, &[
                (true, 5200, MsgKind::Text, "Iltimos, oxirgi 6 oylik xaridlarim bo‘yicha chek nusxalarini yuboring (soliq imtiyozi uchun)."),
                (false, 5100, MsgKind::File, "Xaridlar_6_oy.pdf"),
            ]),
            (72, Channel::Telegram, 4, ConvStatus::Open, 1, &[
                (true, 8, MsgKind::Text, "Yakkasaroyda Budesonid/formoterol ingalyator bormi? Shoshilinch"),
            ]),
            (81, Channel::WhatsApp, 5, ConvStatus::Resolved, 0, &[
                (true, 9000, MsgKind::Text, "Kuryer 2 soat kechikdi"),
                (false, 8990, MsgKind::Text, "Uzr so‘raymiz! Keyingi buyurtmangizga 15 000 bonus ball qo‘shdik."),
                (true, 8900, MsgKind::Text, "Yaxshi, rahmat"),
            ]),
        ];
        let customers: Vec<(Id, String, Option<String>, String)> =
            db.customers.iter().map(|c| (c.id, c.name(), c.telegram.clone(), c.phone.clone())).collect();
        for (pick, channel, ph, status, unread, msgs) in threads {
            let (cid, name, tg, phone) = customers[(*pick * 3) % customers.len()].clone();
            let id = db.new_id();
            let mut messages = Vec::new();
            for (inbound, ago, kind, text) in msgs.iter() {
                let mid = db.new_id();
                messages.push(Message {
                    id: mid,
                    inbound: *inbound,
                    author_id: if *inbound { None } else { Some(self.pharmacists[*ph % self.pharmacists.len()]) },
                    text: (*text).into(),
                    at: now - Duration::minutes(*ago),
                    kind: *kind,
                });
            }
            db.conversations.push(Conversation {
                id,
                channel: *channel,
                customer_id: Some(cid),
                lead_id: None,
                title: name,
                handle: match channel {
                    Channel::Telegram | Channel::Instagram => tg.unwrap_or_else(|| "@mijoz".into()),
                    _ => crate::fmt::phone(&phone),
                },
                assigned_to: Some(self.pharmacists[*ph % self.pharmacists.len()]),
                status: *status,
                unread: *unread,
                messages,
                tags: vec![],
                starred: *pick == 40,
            });
        }
        // leads that wrote in
        let new_leads: Vec<(Id, String, Channel, String, NaiveDateTime)> = db
            .leads
            .iter()
            .filter(|l| l.status == LeadStatus::New && matches!(l.channel, Channel::Telegram | Channel::Instagram))
            .map(|l| (l.id, l.name.clone(), l.channel, l.message.clone(), l.at))
            .collect();
        for (lid, name, channel, text, at_time) in new_leads {
            let id = db.new_id();
            let mid = db.new_id();
            db.conversations.push(Conversation {
                id,
                channel,
                customer_id: None,
                lead_id: Some(lid),
                title: name,
                handle: "@yangi_mijoz".into(),
                assigned_to: None,
                status: ConvStatus::Open,
                unread: 1,
                messages: vec![Message { id: mid, inbound: true, author_id: None, text, at: at_time, kind: MsgKind::Text }],
                tags: vec!["Lid".into()],
                starred: false,
            });
        }
        let _ = rng.f();
    }

    // ------------------------------------------------------------ marketing

    fn segments(&self, db: &mut Db) {
        let r = |field: Field, op: Op, value: &str| Rule { field, op, value: value.into() };
        let list: Vec<(&str, &str, Vec<Rule>, bool, u16, &str)> = vec![
            ("VIP mijozlar", "Oltin va Platina darajasidagilar", vec![r(Field::Tier, Op::Eq, "gold"), r(Field::Tier, Op::Eq, "platinum")], false, 42, "crown"),
            ("Surunkali bemorlar", "Doimiy dori ichadiganlar: radarning asosi", vec![r(Field::RefillDueInDays, Op::Lt, "400")], true, 24, "heart-pulse"),
            ("Diabet", "Qandli diabet bilan yashaydiganlar", vec![r(Field::Condition, Op::Eq, "diabetes")], true, 205, "activity"),
            ("Gipertoniya", "Qon bosimi dorilarini oladiganlar", vec![r(Field::Condition, Op::Eq, "hypertension")], true, 350, "heart"),
            ("Uzoq vaqt kelmaganlar", "60 kundan beri xarid yo‘q", vec![r(Field::DaysSinceLast, Op::Gt, "60")], true, 0, "hourglass"),
            ("Yangi mijozlar", "Oxirgi 30 kunda birinchi xarid", vec![r(Field::Orders, Op::Lt, "3"), r(Field::DaysSinceLast, Op::Lt, "30")], true, 150, "sparkles"),
            ("Shu hafta tug‘ilganlar", "7 kun ichida tug‘ilgan kun", vec![r(Field::BirthdayInDays, Op::Lt, "8")], true, 300, "cake"),
            ("Telegramga roziligi bor", "Xabar yuborish mumkin", vec![r(Field::ConsentTelegram, Op::IsTrue, "")], true, 205, "send"),
            ("Korporativ mijozlar", "Tashkilot xodimlari", vec![r(Field::Corporate, Op::IsTrue, "")], true, 230, "briefcase"),
            ("Onalar va homiladorlar", "Yosh onalar va homiladorlik vitaminlari", vec![r(Field::Tag, Op::Contains, "ona"), r(Field::Condition, Op::Eq, "pregnancy")], false, 330, "baby"),
            ("Ballari ko‘p", "100 000 balldan ortiq", vec![r(Field::Points, Op::Gt, "100000")], true, 265, "gift"),
            ("Nafaqaxo‘rlar", "60 yoshdan katta", vec![r(Field::Age, Op::Gt, "59")], true, 24, "users"),
        ];
        for (i, (name, desc, rules, all, hue, icon)) in list.into_iter().enumerate() {
            let id = db.new_id();
            db.segments.push(Segment {
                id,
                name: name.into(),
                description: desc.into(),
                rules,
                match_all: all,
                hue,
                system: i < 9,
                icon: icon.into(),
            });
        }
    }

    fn campaigns(&self, db: &mut Db, now: NaiveDateTime) {
        let today = now.date();
        let seg = |db: &Db, name: &str| db.segments.iter().find(|s| s.name == name).map(|s| s.id).unwrap_or(0);
        #[allow(clippy::type_complexity)]
        let list: &[(&str, Channel, &str, &str, CampaignStatus, i64, u32, f64, f64, f64, f64, Money, i64)] = &[
            ("Qishga tayyorgarlik: D3 va C vitaminlari", Channel::Telegram, "Telegramga roziligi bor", "Assalomu alaykum, {ism}! Qish oldidan immunitetni mustahkamlang: D3 va C vitaminlariga 15% chegirma va ikki baravar ball. Faqat shu haftada, Oydin Farm’ning barcha filiallarida.", CampaignStatus::Done, -12, 1640, 0.97, 0.81, 0.19, 0.078, 21_400_000, 0),
            ("Diabet maktabi: bepul qand o‘lchash kuni", Channel::Sms, "Diabet", "Shanba kuni 10:00–14:00 da istalgan filialimizda qand miqdorini bepul o‘lchab beramiz. Farmatsevt bilan maslahat ham bepul.", CampaignStatus::Done, -20, 214, 0.99, 0.0, 0.0, 0.21, 6_800_000, 0),
            ("Ballaringizni ishlating", Channel::Telegram, "Ballari ko‘p", "{ism}, hisobingizda {ball} ball bor. Keyingi xaridning 30% gacha qismini ball bilan to‘lang!", CampaignStatus::Done, -5, 63, 1.0, 0.9, 0.33, 0.41, 4_900_000, 0),
            ("Olmazor filiali ochildi", Channel::Telegram, "Telegramga roziligi bor", "Yangi Olmazor filialimiz ochildi! Ochilish haftasida barcha xaridlarga ikki baravar ball.", CampaignStatus::Done, -60, 1580, 0.96, 0.74, 0.11, 0.05, 12_900_000, 0),
            ("Gipertoniya: bepul qon bosimini o‘lchash", Channel::Telegram, "Gipertoniya", "Har dushanba qon bosimingizni bepul o‘lchab, dorilaringizni tekshirib beramiz. Kelganingizda 5 000 bonus ball!", CampaignStatus::Scheduled, 2, 0, 0.0, 0.0, 0.0, 0.0, 0, 5_000),
            ("Allergiya mavsumiga tayyorgarlik", Channel::Telegram, "Telegramga roziligi bor", "Bahor yaqin: allergiyaga qarshi vositalarni oldindan oling va farmatsevt bilan maslahatlashing.", CampaignStatus::Draft, 0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0),
            ("Onalar uchun: bolalar vitaminlari", Channel::Instagram, "Onalar va homiladorlar", "Bolalar multivitaminlari va emolent kremlarga maxsus narx.", CampaignStatus::Paused, -3, 120, 0.94, 0.52, 0.08, 0.025, 690_000, 0),
            ("VIP: shaxsiy farmatsevt xizmati", Channel::Telegram, "VIP mijozlar", "Siz uchun shaxsiy farmatsevt: savollaringizni shu chatga yozing, javob 15 daqiqada.", CampaignStatus::Running, 0, 96, 0.98, 0.62, 0.21, 0.09, 3_100_000, 0),
        ];
        for (name, channel, segment, msg, status, day, audience, deliv, read, click, conv, revenue, bonus) in list.iter() {
            let id = db.new_id();
            let sent = if matches!(status, CampaignStatus::Draft | CampaignStatus::Scheduled) { 0 } else { *audience };
            db.campaigns.push(Campaign {
                id,
                name: (*name).into(),
                channel: *channel,
                segment_id: seg(db, segment),
                message: (*msg).into(),
                status: *status,
                scheduled: if *status == CampaignStatus::Scheduled { Some(at(today + Duration::days(*day), 10, 0)) } else if *day != 0 { Some(at(today + Duration::days(*day), 10, 0)) } else { None },
                created: at(today + Duration::days((*day).min(0) - 2), 15, 0),
                owner_id: self.marketer,
                audience: *audience,
                sent,
                delivered: (sent as f64 * deliv) as u32,
                read: (sent as f64 * read) as u32,
                clicked: (sent as f64 * click) as u32,
                converted: (sent as f64 * conv) as u32,
                revenue: *revenue,
                cost: match channel {
                    Channel::Sms => sent as Money * 85,
                    _ => 0,
                },
                bonus_points: *bonus,
            });
        }
    }

    fn automations(&self, db: &mut Db, now: NaiveDateTime) {
        let today = now.date();
        let first_stage = |db: &Db, i: usize| db.pipelines[0].stages.get(i).map(|s| s.id).unwrap_or(0);
        let list: Vec<(&str, &str, Trigger, Vec<Action>, bool, u32, u32, &str)> = vec![
            ("Dori tugashidan oldin eslatma", "Doimiy dori tugashidan 3 kun oldin Telegram xabar va bron taklifi", Trigger::RefillDue { days_before: 3 },
                vec![Action::SendTelegram { text: "{ism}, {dori} 3 kunda tugaydi. {filial} filialida bor: bron qilaylikmi?".into() }, Action::ReserveStock, Action::Wait { days: 2 }, Action::CreateTask { title: "Javob bermadi: qo‘ng‘iroq qilish".into(), role: Role::CallAgent, due_days: 0 }],
                true, 1_842, 1_127, "refill"),
            ("Tug‘ilgan kun tabrigi", "Tabrik va 25 000 bonus ball", Trigger::Birthday { days_before: 0 },
                vec![Action::SendTelegram { text: "Tug‘ilgan kuningiz bilan, {ism}! Sizga 25 000 bonus ball sovg‘a qildik 🎉".into() }, Action::GiveBonus { points: 25_000 }],
                true, 412, 188, "birthday"),
            ("Qaytaramiz: 60 kun", "60 kun kelmagan mijozga shaxsiy taklif", Trigger::Inactive { days: 60 },
                vec![Action::SendTelegram { text: "{ism}, sizni sog‘indik! Keyingi xaridingizga 2 baravar ball.".into() }, Action::Wait { days: 7 }, Action::CreateTask { title: "Shaxsiy qo‘ng‘iroq".into(), role: Role::Pharmacist, due_days: 1 }],
                true, 236, 41, "winback"),
            ("Antibiotikdan keyin 3-kun", "Antibiotik kursi bo‘yicha holidan xabar olish", Trigger::AfterPurchase { days: 3 },
                vec![Action::SendTelegram { text: "{ism}, o‘zingizni qanday his qilyapsiz? Kursni oxirigacha davom ettiring. Savollar bo‘lsa, yozing.".into() }],
                true, 318, 0, "day3"),
            ("Defektura keldi", "Kutilgan dori kelganda xabar berish va bron", Trigger::WaitlistArrived,
                vec![Action::ReserveStock, Action::SendTelegram { text: "{ism}, siz kutgan {dori} keldi va {filial} filialida siz uchun ajratildi.".into() }],
                true, 154, 129, "waitlist"),
            ("Yangi lid: 15 daqiqada javob", "Lidni call-markazga biriktirish va vazifa", Trigger::NewLead,
                vec![Action::CreateTask { title: "Lid bilan bog‘lanish".into(), role: Role::CallAgent, due_days: 0 }, Action::NotifyManager { text: "Yangi lid: {ism}".into() }],
                true, 96, 34, "lead"),
            ("Nojo‘ya ta’sir: 4 soatlik qoida", "Provizorga vazifa, mudirga xabar, farmakonazorat shakli", Trigger::TicketCreated,
                vec![Action::NotifyManager { text: "Nojo‘ya ta’sir: {ism}, {dori}".into() }, Action::CreateTask { title: "Mijozga qo‘ng‘iroq va farmakonazorat shakli".into(), role: Role::Pharmacist, due_days: 0 }],
                true, 7, 0, "adverse"),
            ("Daraja oshdi", "Yangi darajani tabriklash", Trigger::TierUp,
                vec![Action::SendTelegram { text: "Tabriklaymiz, {ism}! Endi siz {daraja} darajadasiz: keshbek {foiz}%.".into() }],
                true, 58, 0, "tier"),
            ("Past baho: mudir qo‘ng‘irog‘i", "6 va undan past baho bergan mijozga qo‘ng‘iroq", Trigger::LowNps,
                vec![Action::CreateTask { title: "Past baho: mijoz bilan gaplashish".into(), role: Role::Manager, due_days: 1 }],
                false, 12, 0, "nps"),
            ("Taklifdan keyin eslatma", "Taklif yuborilgach 3 kunda keyingi qadam", Trigger::DealStage { stage_id: first_stage(db, 2) },
                vec![Action::Wait { days: 3 }, Action::CreateTask { title: "Taklif bo‘yicha fikr so‘rash".into(), role: Role::SalesRep, due_days: 0 }],
                true, 23, 9, "deal"),
        ];
        for (k, (name, desc, trigger, actions, enabled, runs, conv, recipe)) in list.into_iter().enumerate() {
            let id = db.new_id();
            db.automations.push(Automation {
                id,
                name: name.into(),
                description: desc.into(),
                trigger,
                conditions: if recipe == "refill" { vec![Rule { field: Field::ConsentTelegram, op: Op::IsTrue, value: String::new() }] } else { vec![] },
                actions,
                enabled,
                runs,
                conversions: conv,
                last_run: if enabled { Some(now - Duration::minutes(7 + k as i64 * 41)) } else { None },
                recipe: Some(recipe.into()),
                created: today - Duration::days(30 + k as i64 * 9),
            });
        }
    }

    // ------------------------------------------------------------ waitlist, tickets, quotes

    fn waitlist(&self, db: &mut Db, rng: &mut Rng, now: NaiveDateTime) {
        let today = now.date();
        let items: &[(&str, Option<usize>, u32, Money, WaitStatus)] = &[
            ("Insulin glargin 100 TB/ml, shprits-ruchka №5", Some(11), 2, 820_000, WaitStatus::Waiting),
            ("Semaglutid 1 mg, shprits-ruchka", None, 1, 1_450_000, WaitStatus::Waiting),
            ("Budesonid/formoterol 160/4,5 mkg, 120 doza", Some(18), 1, 265_000, WaitStatus::Waiting),
            ("Levetiratsetam 500 mg №50", None, 2, 640_000, WaitStatus::Waiting),
            ("Montelukast 10 mg №28", Some(19), 2, 192_000, WaitStatus::Arrived),
            ("Kompressorli nebulayzer", Some(51), 1, 690_000, WaitStatus::Waiting),
            ("Insulin aspart 100 TB/ml, shprits-ruchka №5", Some(12), 1, 385_000, WaitStatus::Arrived),
            ("Tsefiksim suspenziya 100 mg/5 ml", None, 1, 98_000, WaitStatus::Waiting),
            ("B12 vitamini, in’eksiya №5", None, 2, 76_000, WaitStatus::Notified),
            ("Rozuvastatin 10 mg №28", Some(7), 1, 89_000, WaitStatus::Waiting),
            ("Pulsoksimetr", Some(50), 1, 185_000, WaitStatus::Reserved),
            ("Laktozasiz bolalar aralashmasi, 400 g", None, 3, 540_000, WaitStatus::Waiting),
            ("Gliklazid MR 60 mg №30", Some(10), 2, 126_000, WaitStatus::Arrived),
            ("Kalsiy + D3 chaynaladigan №60", None, 1, 92_000, WaitStatus::Waiting),
            ("Ko‘z tomchisi (glaukoma), 5 ml", None, 1, 310_000, WaitStatus::Notified),
            ("Omega-3 1000 mg №60", Some(37), 2, 258_000, WaitStatus::PickedUp),
            ("Enoksaparin 40 mg №10", None, 1, 520_000, WaitStatus::Waiting),
            ("Bolalar uchun Ibuprofen suspenziyasi", None, 2, 64_000, WaitStatus::Reserved),
            ("Melatonin 3 mg №30", None, 1, 87_000, WaitStatus::Waiting),
            ("Ferment kompleksi (laktaza)", None, 1, 135_000, WaitStatus::Cancelled),
            ("Insulin glargin 100 TB/ml, shprits-ruchka №5", Some(11), 1, 410_000, WaitStatus::Waiting),
            ("Salbutamol ingalyator 100 mkg", Some(17), 1, 48_000, WaitStatus::Notified),
        ];
        for (k, (name, product, qty, value, status)) in items.iter().enumerate() {
            let c = &db.customers[(k * 11 + 4) % db.customers.len()];
            let (cid, branch) = (c.id, c.home_branch);
            let id = db.new_id();
            let requested = now - Duration::hours(rng.range(2, 24 * 12));
            db.waitlist.push(WaitItem {
                id,
                customer_id: cid,
                product_id: product.map(|i| self.product_id(db, i)),
                product_name: (*name).into(),
                branch_id: branch,
                qty: *qty,
                at: requested,
                status: *status,
                eta: if *status == WaitStatus::Waiting { Some(today + Duration::days(rng.range(1, 9))) } else { None },
                note: if k % 4 == 0 { "Mijoz kelgunicha saqlab turing".into() } else { String::new() },
                notified_at: if matches!(status, WaitStatus::Notified | WaitStatus::Reserved | WaitStatus::PickedUp) { Some(now - Duration::hours(rng.range(1, 30))) } else { None },
                value: *value,
            });
        }
    }

    fn tickets(&self, db: &mut Db, rng: &mut Rng, now: NaiveDateTime) {
        let list: &[(TicketKind, &str, &str, Option<usize>, Option<&str>, Priority, TicketStatus, i64, Option<u8>)] = &[
            (TicketKind::AdverseReaction, "Amoksitsillindan keyin toshma", "Mijoz kecha kechqurun Amoksitsillin 500 mg ichgan, ertalab qo‘llarida toshma. Dori to‘xtatildi, shifokorga yo‘naltirildi.", Some(22), Some("AMX-2611-B"), Priority::Urgent, TicketStatus::InProgress, 10, None),
            (TicketKind::Quality, "Blister ichida singan tabletkalar", "Lozartan 50 mg qadog‘ida 3 ta tabletka singan. Partiya raqami yozib olindi.", Some(2), Some("LZT-0925-14"), Priority::High, TicketStatus::New, 3, None),
            (TicketKind::Delivery, "Yetkazish 2 soat kechikdi", "Sergeli: buyurtma 16:00 ga va’da qilingan, 18:10 da yetkazildi.", None, None, Priority::Normal, TicketStatus::Resolved, 52, Some(4)),
            (TicketKind::Return, "Ochilmagan qadoqni qaytarish", "Shifokor dorini almashtirdi, mijoz ochilmagan Bisoprolol 5 mg ni qaytarmoqchi.", Some(3), None, Priority::Normal, TicketStatus::Waiting, 26, None),
            (TicketKind::Question, "Analog dori bormi?", "Rozuvastatin narxi qimmat, arzonroq analog so‘ramoqda.", Some(7), None, Priority::Low, TicketStatus::Resolved, 80, Some(5)),
            (TicketKind::Complaint, "Navbat uzun bo‘ldi", "Yunusobod filialida kechqurun 25 daqiqa navbat kutgan.", None, None, Priority::Normal, TicketStatus::InProgress, 30, None),
            (TicketKind::Praise, "Farmatsevtga minnatdorchilik", "Nodira opa juda yaxshi tushuntirdi, rahmat!", None, None, Priority::Low, TicketStatus::Closed, 120, Some(5)),
            (TicketKind::AdverseReaction, "Metformindan keyin ko‘ngil aynishi", "Yangi boshlangan Metformin 850 mg dan keyin ko‘ngil aynishi. Ovqat bilan ichish tushuntirildi, shifokor xabardor.", Some(8), Some("MTF-1026-03"), Priority::High, TicketStatus::Resolved, 75, Some(5)),
            (TicketKind::Quality, "Termometr ishlamayapti", "Sotib olinganiga 2 kun bo‘ldi, ekran yonmayapti. Almashtirish kerak.", Some(49), None, Priority::Normal, TicketStatus::New, 5, None),
            (TicketKind::Complaint, "Bonus ballar tushmadi", "Oxirgi xariddan keyin ballar hisobga tushmagan.", None, None, Priority::Normal, TicketStatus::New, 30, None),
            (TicketKind::Delivery, "Noto‘g‘ri dori yetkazildi", "Metformin 1000 o‘rniga 850 yetkazilgan. Kuryer almashtirib berdi.", Some(9), None, Priority::High, TicketStatus::Resolved, 140, Some(3)),
            (TicketKind::Question, "Homiladorlikda qaysi vitaminlar?", "Birinchi trimestr, shifokor tavsiyasi bilan maslahat kerak.", Some(41), None, Priority::Low, TicketStatus::InProgress, 20, None),
        ];
        for (k, (kind, subject, desc, product, batch, prio, status, hours_ago, csat)) in list.iter().enumerate() {
            let c = &db.customers[(k * 17 + 9) % db.customers.len()];
            let (cid, branch) = (c.id, c.home_branch);
            let id = db.new_id();
            let created = now - Duration::hours(*hours_ago) - Duration::minutes(rng.range(0, 50));
            let sla = if *kind == TicketKind::AdverseReaction { 4 } else { db.settings.sla_hours as i64 };
            let resolved = matches!(status, TicketStatus::Resolved | TicketStatus::Closed);
            db.tickets.push(Ticket {
                id,
                number: format!("MRJ-{}", 1031 + k),
                kind: *kind,
                subject: (*subject).into(),
                description: (*desc).into(),
                customer_id: Some(cid),
                product_id: product.map(|i| self.product_id(db, i)),
                batch: batch.map(|b| b.to_string()),
                branch_id: Some(branch),
                priority: *prio,
                status: *status,
                created,
                due: created + Duration::hours(sla),
                assigned_to: Some(self.pharmacist_of(db, branch)),
                resolved: if resolved { Some(created + Duration::hours(rng.range(1, sla.max(2)))) } else { None },
                csat: *csat,
                comments: vec![Comment {
                    at: created + Duration::minutes(20),
                    author_id: Some(self.pharmacist_of(db, branch)),
                    text: "Mijoz bilan bog‘lanildi, ma’lumotlar yozib olindi.".into(),
                    internal: true,
                }],
                reported_to_regulator: *kind == TicketKind::AdverseReaction && resolved,
            });
        }
    }

    fn quotes(&self, db: &mut Db, rng: &mut Rng, today: NaiveDate, companies: &[Id]) {
        let statuses = [
            QuoteStatus::Paid, QuoteStatus::Sent, QuoteStatus::Overdue, QuoteStatus::Accepted, QuoteStatus::Draft, QuoteStatus::Invoiced,
            QuoteStatus::Paid, QuoteStatus::Overdue, QuoteStatus::Sent, QuoteStatus::Rejected, QuoteStatus::Paid, QuoteStatus::Invoiced,
        ];
        let buyers = [0usize, 2, 14, 1, 7, 4, 12, 15, 10, 13, 3, 11];
        let line_sets: [&[usize]; 4] = [&[0, 2, 8, 20], &[22, 23, 24, 25], &[44, 45, 47], &[52, 49, 60, 61]];
        for (k, st) in statuses.iter().enumerate() {
            let company = companies[buyers[k] % companies.len()];
            let deal = db.deals.iter().find(|d| d.company_id == Some(company)).map(|d| d.id);
            let lines = line_sets[k % 4]
                .iter()
                .map(|i| {
                    let p = &db.products[*i % db.products.len()];
                    LineItem { product_id: p.id, qty: rng.range(20, 400) as u32, price: p.price, discount_pct: [0, 5, 7, 10][k % 4] }
                })
                .collect();
            let issued = today - Duration::days(rng.range(2, 70));
            let id = db.new_id();
            db.quotes.push(Quote {
                id,
                number: format!("TK-{}-{:04}", today.year(), 131 + k),
                company_id: company,
                deal_id: deal,
                lines,
                status: *st,
                issued,
                valid_until: issued + Duration::days(if *st == QuoteStatus::Overdue { 14 } else { 30 }),
                vat_pct: 12,
                notes: "Yetkazib berish bepul. Dorilar sovuq zanjirda saqlanadi va yetkaziladi.".into(),
                owner_id: self.reps[k % self.reps.len()],
                paid_on: if *st == QuoteStatus::Paid { Some(issued + Duration::days(rng.range(5, 25))) } else { None },
            });
        }
    }

    fn goals(&self, db: &mut Db, today: NaiveDate) {
        let month = crate::fmt::month_key(today);
        let last = crate::analytics::monthly_revenue(db, today, 2);
        let base = last.first().map(|x| x.1).unwrap_or(100_000_000);
        let shares = [0.27, 0.22, 0.18, 0.13, 0.12, 0.08];
        for (i, b) in self.branches.clone().iter().enumerate() {
            let id = db.new_id();
            db.goals.push(Goal { id, staff_id: None, branch_id: Some(*b), metric: Metric::Revenue, target: ((base as f64 * shares[i] * 1.12) as i64 / 1_000_000) * 1_000_000, month: month.clone() });
        }
        for (k, rep) in self.reps.clone().iter().enumerate() {
            let id = db.new_id();
            db.goals.push(Goal { id, staff_id: Some(*rep), branch_id: None, metric: Metric::DealsWon, target: [250_000_000, 180_000_000][k % 2], month: month.clone() });
        }
        let id = db.new_id();
        db.goals.push(Goal { id, staff_id: Some(self.call_agent), branch_id: None, metric: Metric::Calls, target: 120, month: month.clone() });
        for ph in self.pharmacists.clone().iter().take(3) {
            let id = db.new_id();
            db.goals.push(Goal { id, staff_id: Some(*ph), branch_id: None, metric: Metric::NewCustomers, target: 12, month: month.clone() });
        }
    }

    fn notes(&self, db: &mut Db, now: NaiveDateTime) {
        let texts: &[(&str, bool, bool)] = &[
            ("Faqat rus tilida gaplashadi. Ertalab qo‘ng‘iroq qilmang.", true, false),
            ("Insulinni sovutgich sumkada yetkazish kerak.", true, true),
            ("Nevarasi uchun bolalar vitaminlarini so‘rab turadi.", false, false),
            ("Penitsillinga allergiyasi bor: antibiotik tavsiya qilishda e’tibor bering.", true, true),
            ("Har oy 5-sanada pensiya olgach keladi.", false, false),
            ("Korporativ karta: Sayhun Tekstil xodimi.", false, false),
        ];
        let ids: Vec<Id> = db.customers.iter().filter(|c| c.orders >= 6).map(|c| c.id).take(texts.len()).collect();
        for (k, (text, pinned, sensitive)) in texts.iter().enumerate() {
            if let Some(cid) = ids.get(k) {
                let id = db.new_id();
                db.notes.push(Note {
                    id,
                    at: now - Duration::days(3 + k as i64 * 9),
                    author_id: Some(self.pharmacists[k % self.pharmacists.len()]),
                    text: (*text).into(),
                    customer_id: Some(*cid),
                    company_id: None,
                    deal_id: None,
                    pinned: *pinned,
                    sensitive: *sensitive,
                });
            }
        }
        let company_notes: &[&str] = &[
            "Bosh shifokor bilan faqat seshanba va payshanba uchrashish mumkin.",
            "To‘lovlar har doim 40–45 kun kechikadi: kredit limitini oshirmang.",
            "Tender e’lon qilinishi kutilmoqda (dekabr).",
        ];
        for (k, text) in company_notes.iter().enumerate() {
            let id = db.new_id();
            let cid = db.companies[[0usize, 2, 14][k]].id;
            db.notes.push(Note {
                id,
                at: now - Duration::days(2 + k as i64 * 5),
                author_id: Some(self.reps[k % self.reps.len()]),
                text: (*text).into(),
                customer_id: None,
                company_id: Some(cid),
                deal_id: None,
                pinned: k == 1,
                sensitive: false,
            });
        }
    }

    fn finish(&self, db: &mut Db, now: NaiveDateTime) {
        // keep the ledger to the last five months (balances are on the customers)
        let cut = now - Duration::days(150);
        db.loyalty.retain(|t| t.at >= cut);
        db.notifications.clear();
        let lead = db.leads.iter().find(|l| l.status == LeadStatus::New).map(|l| (l.name.clone(), l.interest.clone()));
        let conv = db.conversations.iter().find(|c| c.unread > 0).map(|c| (c.id, c.title.clone(), c.last_text().to_string()));
        let ticket = db.tickets.iter().find(|t| t.kind == TicketKind::AdverseReaction && t.is_open()).map(|t| (t.id, t.number.clone(), t.subject.clone()));
        let wait = db.waitlist.iter().find(|w| w.status == WaitStatus::Arrived).map(|w| w.product_name.clone());
        let won = db.deals.iter().find(|d| d.status == DealStatus::Won).map(|d| (d.id, d.title.clone()));
        if let Some((n, i)) = lead {
            db.notify(now - Duration::minutes(25), NotifKind::Lead, n, i, "/leads");
        }
        if let Some((id, t, b)) = conv {
            db.notify(now - Duration::minutes(15), NotifKind::Message, t, b, format!("/inbox/{id}"));
        }
        if let Some((id, n, s)) = ticket {
            db.notify(now - Duration::minutes(600), NotifKind::Ticket, n, s, format!("/tickets/{id}"));
        }
        if let Some(w) = wait {
            db.notify(now - Duration::hours(3), NotifKind::Waitlist, w, "", "/waitlist");
        }
        if let Some((id, t)) = won {
            db.notify(now - Duration::days(1), NotifKind::Deal, t, "", format!("/deals/{id}"));
        }
        let refills = crate::analytics::refills(db, now.date(), 3).len();
        db.notify(now - Duration::hours(1), NotifKind::Refill, format!("{refills}"), "", "/refills");
        db.notifications.sort_by(|a, b| b.at.cmp(&a.at));
        for n in db.notifications.iter_mut().skip(4) {
            n.read = true;
        }
        db.audit.clear();
        let entries = [
            "Kampaniya yuborildi: Ballaringizni ishlating",
            "Bitim yutildi: Reanimatsiya bo‘limi uchun infuzion eritmalar",
            "Segment yangilandi: VIP mijozlar",
            "Avtomatlashtirish yoqildi: Dori tugashidan oldin eslatma",
            "Sog‘liq ma’lumotlari ko‘rildi: mijoz kartasi",
            "Daybook bilan sinxronlash: 6 filial, 16 xodim",
        ];
        for (k, e) in entries.iter().enumerate() {
            let id = db.new_id();
            db.audit.push(AuditEntry { id, at: now - Duration::hours(k as i64 * 5 + 1), actor_id: Some(self.owner), text: (*e).into(), sensitive: e.contains("Sog‘liq") });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn demo_is_rich_and_consistent() {
        let now = NaiveDate::from_ymd_opt(2026, 11, 23).unwrap().and_hms_opt(9, 30, 0).unwrap();
        let db = generate(now);
        assert_eq!(db.branches.len(), 6);
        assert!(db.customers.len() >= 250);
        assert!(db.purchases.len() > 1500, "purchases: {}", db.purchases.len());
        assert!(db.deals.len() >= 30);
        let k = crate::analytics::kpis(&db, now);
        assert!(k.revenue_mtd > 0);
        assert!(k.refills_week > 5, "refills: {}", k.refills_week);
        for c in &db.customers {
            let spent: Money = db.purchases.iter().filter(|p| p.customer_id == c.id).map(|p| p.total).sum();
            assert_eq!(spent, c.total_spent);
        }
        let json = serde_json::to_string(&db).unwrap();
        assert!(json.len() < 3_000_000, "json is {} bytes", json.len());
        let back: Db = serde_json::from_str(&json).unwrap();
        assert_eq!(back.customers.len(), db.customers.len());
    }
}
