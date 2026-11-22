//! Formatting for people: so‘m amounts, dates, relative times, phones and plurals.

use chrono::{Datelike, NaiveDate, NaiveDateTime, Timelike};

use crate::i18n::{to_cyrillic, Lang};
use crate::model::Money;

const NBSP: char = '\u{00A0}';

/// 12450000 -> "12 450 000" (no-break spaces).
pub fn group(n: i64) -> String {
    let neg = n < 0;
    let digits = n.unsigned_abs().to_string();
    let mut out = String::with_capacity(digits.len() + digits.len() / 3 + 1);
    for (i, ch) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i) % 3 == 0 {
            out.push(NBSP);
        }
        out.push(ch);
    }
    if neg {
        format!("−{out}")
    } else {
        out
    }
}

pub fn currency(lang: Lang) -> &'static str {
    match lang {
        Lang::Uz => "so‘m",
        Lang::UzCyrl => "сўм",
        Lang::Ru => "сум",
        Lang::En => "UZS",
    }
}

/// "12 450 000 so‘m"
pub fn money(v: Money, lang: Lang) -> String {
    format!("{}{NBSP}{}", group(v), currency(lang))
}

fn one_decimal(v: f64, lang: Lang) -> String {
    let s = if (v - v.round()).abs() < 0.05 || v >= 100.0 { format!("{:.0}", v) } else { format!("{:.1}", v) };
    if lang == Lang::En {
        s
    } else {
        s.replace('.', ",")
    }
}

/// "12,4 mln so‘m" / "12,4 млн сум" / "12.4M UZS"
pub fn money_short(v: Money, lang: Lang) -> String {
    let a = v.unsigned_abs() as f64;
    let sign = if v < 0 { "−" } else { "" };
    let (num, unit) = if a >= 1e9 {
        (a / 1e9, ["mlrd", "млрд", "млрд", "B"])
    } else if a >= 1e6 {
        (a / 1e6, ["mln", "млн", "млн", "M"])
    } else if a >= 1e4 {
        (a / 1e3, ["ming", "минг", "тыс.", "K"])
    } else {
        return money(v, lang);
    };
    let idx = match lang {
        Lang::Uz => 0,
        Lang::UzCyrl => 1,
        Lang::Ru => 2,
        Lang::En => 3,
    };
    if lang == Lang::En {
        format!("{sign}{}{} {}", one_decimal(num, lang), unit[idx], currency(lang))
    } else {
        format!("{sign}{}{NBSP}{}{NBSP}{}", one_decimal(num, lang), unit[idx], currency(lang))
    }
}

/// Compact number without currency: 12 400 -> "12,4K" style, for chart axes.
pub fn compact(v: f64, lang: Lang) -> String {
    let a = v.abs();
    let (num, unit) = if a >= 1e9 {
        (v / 1e9, ["mlrd", "млрд", "млрд", "B"])
    } else if a >= 1e6 {
        (v / 1e6, ["mln", "млн", "млн", "M"])
    } else if a >= 1e3 {
        (v / 1e3, ["k", "к", "к", "K"])
    } else {
        return format!("{:.0}", v);
    };
    let idx = match lang {
        Lang::Uz => 0,
        Lang::UzCyrl => 1,
        Lang::Ru => 2,
        Lang::En => 3,
    };
    if lang == Lang::En || idx == 3 {
        format!("{}{}", one_decimal(num, lang), unit[idx])
    } else {
        format!("{}{NBSP}{}", one_decimal(num, lang), unit[idx])
    }
}

pub fn num(n: i64) -> String {
    group(n)
}

/// 42.4 -> "42%", 4.25 -> "4,3%"
pub fn pct(v: f64, lang: Lang) -> String {
    let s = if v.abs() < 10.0 && (v - v.round()).abs() >= 0.05 { format!("{:.1}", v) } else { format!("{:.0}", v) };
    let s = if lang == Lang::En { s } else { s.replace('.', ",") };
    format!("{s}%")
}

/// "+12%" / "−4%"
pub fn delta_pct(v: f64, lang: Lang) -> String {
    if v >= 0.0 {
        format!("+{}", pct(v, lang))
    } else {
        format!("−{}", pct(-v, lang))
    }
}

const MONTHS_UZ: [&str; 12] = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
];
/// Short Uzbek months that stay distinct (iyun and iyul both start with "Iyu").
const MONTHS_UZ_SHORT: [&str; 12] = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn", "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"];
const MONTHS_RU_GEN: [&str; 12] = [
    "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря",
];
const MONTHS_RU_SHORT: [&str; 12] = [
    "янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек.",
];
const MONTHS_RU: [&str; 12] = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];
const MONTHS_EN: [&str; 12] = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December",
];

fn cap(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
        None => String::new(),
    }
}

/// "Noyabr" / "Ноябрь" / "November" (1-based month).
pub fn month_name(m: u32, lang: Lang) -> String {
    let i = (m.clamp(1, 12) - 1) as usize;
    match lang {
        Lang::Uz => cap(MONTHS_UZ[i]),
        Lang::UzCyrl => to_cyrillic(&cap(MONTHS_UZ[i])),
        Lang::Ru => MONTHS_RU[i].to_string(),
        Lang::En => MONTHS_EN[i].to_string(),
    }
}

/// "Noy" / "нояб." / "Nov"
pub fn month_short(m: u32, lang: Lang) -> String {
    let i = (m.clamp(1, 12) - 1) as usize;
    match lang {
        Lang::Uz => MONTHS_UZ_SHORT[i].to_string(),
        Lang::UzCyrl => to_cyrillic(MONTHS_UZ_SHORT[i]),
        Lang::Ru => MONTHS_RU_SHORT[i].to_string(),
        Lang::En => MONTHS_EN[i][..3].to_string(),
    }
}

/// Monday = 0.
pub fn weekday_short(w: u32, lang: Lang) -> String {
    let i = (w % 7) as usize;
    match lang {
        Lang::Uz => ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"][i].to_string(),
        Lang::UzCyrl => ["Ду", "Се", "Чо", "Па", "Жу", "Ша", "Як"][i].to_string(),
        Lang::Ru => ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][i].to_string(),
        Lang::En => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][i].to_string(),
    }
}

pub fn weekday_long(w: u32, lang: Lang) -> String {
    let i = (w % 7) as usize;
    match lang {
        Lang::Uz => ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"][i].to_string(),
        Lang::UzCyrl => to_cyrillic(["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"][i]),
        Lang::Ru => ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][i].to_string(),
        Lang::En => ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][i].to_string(),
    }
}

/// "23-noyabr" / "23 ноября" / "Nov 23", with the year when it isn't this year.
pub fn date(d: NaiveDate, today: NaiveDate, lang: Lang) -> String {
    let m = (d.month() - 1) as usize;
    let same_year = d.year() == today.year();
    let base = match lang {
        Lang::Uz => format!("{}-{}", d.day(), MONTHS_UZ[m]),
        Lang::UzCyrl => to_cyrillic(&format!("{}-{}", d.day(), MONTHS_UZ[m])),
        Lang::Ru => format!("{} {}", d.day(), MONTHS_RU_GEN[m]),
        Lang::En => format!("{} {}", &MONTHS_EN[m][..3], d.day()),
    };
    if same_year {
        base
    } else if lang == Lang::En {
        format!("{base}, {}", d.year())
    } else {
        format!("{base} {}", d.year())
    }
}

/// "23.11.2026"
pub fn date_numeric(d: NaiveDate) -> String {
    format!("{:02}.{:02}.{}", d.day(), d.month(), d.year())
}

/// "14:05"
pub fn time(dt: NaiveDateTime) -> String {
    format!("{:02}:{:02}", dt.hour(), dt.minute())
}

/// "Bugun, 14:05" / "Kecha, 09:12" / "23-noyabr, 14:05"
pub fn datetime(dt: NaiveDateTime, now: NaiveDateTime, lang: Lang) -> String {
    let days = (dt.date() - now.date()).num_days();
    let day = match days {
        0 => word(lang, "Bugun", "Сегодня", "Today"),
        -1 => word(lang, "Kecha", "Вчера", "Yesterday"),
        1 => word(lang, "Ertaga", "Завтра", "Tomorrow"),
        _ => date(dt.date(), now.date(), lang),
    };
    format!("{day}, {}", time(dt))
}

fn word(lang: Lang, uz: &str, ru: &str, en: &str) -> String {
    match lang {
        Lang::Uz => uz.to_string(),
        Lang::UzCyrl => to_cyrillic(uz),
        Lang::Ru => ru.to_string(),
        Lang::En => en.to_string(),
    }
}

/// Russian plural: 1 клиент, 2 клиента, 5 клиентов.
pub fn plural_ru<'a>(n: i64, one: &'a str, few: &'a str, many: &'a str) -> &'a str {
    let n = n.abs();
    let (d10, d100) = (n % 10, n % 100);
    if d10 == 1 && d100 != 11 {
        one
    } else if (2..=4).contains(&d10) && !(12..=14).contains(&d100) {
        few
    } else {
        many
    }
}

/// Picks a plural from "uz|ru one|ru few|ru many|en one|en other".
pub fn plural(n: i64, lang: Lang, forms: &str) -> String {
    let f: Vec<&str> = forms.split('|').collect();
    let get = |i: usize| f.get(i).copied().unwrap_or("");
    let w = match lang {
        Lang::Uz => get(0).to_string(),
        Lang::UzCyrl => to_cyrillic(get(0)),
        Lang::Ru => plural_ru(n, get(1), get(2), get(3)).to_string(),
        Lang::En => if n.abs() == 1 { get(4).to_string() } else { get(5).to_string() },
    };
    format!("{}{NBSP}{w}", group(n))
}

/// "3 kun" / "3 дня" / "3 days"
pub fn days(n: i64, lang: Lang) -> String {
    plural(n, lang, "kun|день|дня|дней|day|days")
}

/// "hozirgina", "5 daqiqa oldin", "2 soat oldin", "kecha", "3 kun oldin", or a date.
pub fn relative(dt: NaiveDateTime, now: NaiveDateTime, lang: Lang) -> String {
    let mins = (now - dt).num_minutes();
    if mins < 0 {
        return relative_future(dt, now, lang);
    }
    let days = (now.date() - dt.date()).num_days();
    if mins < 1 {
        word(lang, "hozirgina", "только что", "just now")
    } else if mins < 60 {
        match lang {
            Lang::Uz => format!("{mins} daqiqa oldin"),
            Lang::UzCyrl => to_cyrillic(&format!("{mins} daqiqa oldin")),
            Lang::Ru => format!("{mins} мин назад"),
            Lang::En => format!("{mins} min ago"),
        }
    } else if days == 0 {
        let h = mins / 60;
        match lang {
            Lang::Uz => format!("{h} soat oldin"),
            Lang::UzCyrl => to_cyrillic(&format!("{h} soat oldin")),
            Lang::Ru => format!("{h} ч назад"),
            Lang::En => format!("{h} h ago"),
        }
    } else if days == 1 {
        word(lang, "kecha", "вчера", "yesterday")
    } else if days < 7 {
        match lang {
            Lang::Uz => format!("{days} kun oldin"),
            Lang::UzCyrl => to_cyrillic(&format!("{days} kun oldin")),
            Lang::Ru => format!("{} назад", self::days(days, lang)),
            Lang::En => format!("{days} days ago"),
        }
    } else {
        date(dt.date(), now.date(), lang)
    }
}

fn relative_future(dt: NaiveDateTime, now: NaiveDateTime, lang: Lang) -> String {
    let mins = (dt - now).num_minutes();
    let days = (dt.date() - now.date()).num_days();
    if mins < 60 {
        match lang {
            Lang::Uz => format!("{mins} daqiqadan keyin"),
            Lang::UzCyrl => to_cyrillic(&format!("{mins} daqiqadan keyin")),
            Lang::Ru => format!("через {mins} мин"),
            Lang::En => format!("in {mins} min"),
        }
    } else if days == 0 {
        let h = mins / 60;
        match lang {
            Lang::Uz => format!("{h} soatdan keyin"),
            Lang::UzCyrl => to_cyrillic(&format!("{h} soatdan keyin")),
            Lang::Ru => format!("через {h} ч"),
            Lang::En => format!("in {h} h"),
        }
    } else if days == 1 {
        word(lang, "ertaga", "завтра", "tomorrow")
    } else if days < 7 {
        match lang {
            Lang::Uz => format!("{days} kundan keyin"),
            Lang::UzCyrl => to_cyrillic(&format!("{days} kundan keyin")),
            Lang::Ru => format!("через {}", self::days(days, lang)),
            Lang::En => format!("in {days} days"),
        }
    } else {
        date(dt.date(), now.date(), lang)
    }
}

/// "in 3 days" / "3 days ago" / "today" for a date relative to today.
pub fn due_in(d: NaiveDate, today: NaiveDate, lang: Lang) -> String {
    let n = (d - today).num_days();
    match n {
        0 => word(lang, "bugun", "сегодня", "today"),
        1 => word(lang, "ertaga", "завтра", "tomorrow"),
        -1 => word(lang, "kecha", "вчера", "yesterday"),
        n if n > 1 => match lang {
            Lang::Uz => format!("{n} kundan keyin"),
            Lang::UzCyrl => to_cyrillic(&format!("{n} kundan keyin")),
            Lang::Ru => format!("через {}", days(n, lang)),
            Lang::En => format!("in {n} days"),
        },
        n => match lang {
            Lang::Uz => format!("{} kun oldin", -n),
            Lang::UzCyrl => to_cyrillic(&format!("{} kun oldin", -n)),
            Lang::Ru => format!("{} назад", days(-n, lang)),
            Lang::En => format!("{} days ago", -n),
        },
    }
}

/// "+998 90 123 45 67" from any spelling of an Uzbek number.
pub fn phone(raw: &str) -> String {
    let d: String = raw.chars().filter(|c| c.is_ascii_digit()).collect();
    let d = if d.len() == 9 { format!("998{d}") } else { d };
    if d.len() == 12 && d.starts_with("998") {
        format!("+998 {} {} {} {}", &d[3..5], &d[5..8], &d[8..10], &d[10..12])
    } else if raw.is_empty() {
        String::new()
    } else {
        raw.to_string()
    }
}

/// "+998 90 ••• •• 67" for privacy mode.
pub fn mask_phone(raw: &str) -> String {
    let p = phone(raw);
    if p.len() >= 17 {
        format!("{} ••• •• {}", &p[..7], &p[p.len() - 2..])
    } else {
        "••• •• ••".into()
    }
}

/// Digits only, for tel: links: "+998901234567".
pub fn tel_href(raw: &str) -> String {
    let d: String = raw.chars().filter(|c| c.is_ascii_digit()).collect();
    format!("tel:+{d}")
}

pub fn initials(name: &str) -> String {
    name.split_whitespace().filter_map(|w| w.chars().next()).take(2).collect::<String>().to_uppercase()
}

/// "2026-11" for a date.
pub fn month_key(d: NaiveDate) -> String {
    format!("{}-{:02}", d.year(), d.month())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn money_formats() {
        assert_eq!(money(12_450_000, Lang::Uz), "12\u{a0}450\u{a0}000\u{a0}so‘m");
        assert_eq!(money_short(12_450_000, Lang::Uz), "12,4\u{a0}mln\u{a0}so‘m");
        assert_eq!(money_short(12_450_000, Lang::En), "12.4M UZS");
        assert_eq!(money_short(2_000_000_000, Lang::Ru), "2\u{a0}млрд\u{a0}сум");
    }

    #[test]
    fn plurals() {
        assert_eq!(plural_ru(1, "a", "b", "c"), "a");
        assert_eq!(plural_ru(3, "a", "b", "c"), "b");
        assert_eq!(plural_ru(11, "a", "b", "c"), "c");
        assert_eq!(plural_ru(22, "a", "b", "c"), "b");
    }

    #[test]
    fn phones() {
        assert_eq!(phone("998901234567"), "+998 90 123 45 67");
        assert_eq!(phone("90 123 45 67"), "+998 90 123 45 67");
        assert_eq!(mask_phone("998901234567"), "+998 90 ••• •• 67");
    }
}
