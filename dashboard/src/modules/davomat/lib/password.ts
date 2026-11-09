/**
 * Passwords on the client: a strength estimate for the meter (the server's Django validators have
 * the last word: length 8+, not common, not only digits, not like the username) and a generator for
 * admins who set a password for someone else.
 */
export type Strength = 0 | 1 | 2 | 3 | 4;
export const STRENGTH_KEYS = ["weak", "weak", "fair", "good", "strong"] as const;

/** Words people pick first; a password made of one of them (with digits) is weak whatever its length. */
const COMMON = ["password", "parol", "qwerty", "admin", "davomat", "daybook", "123456", "111111", "iloveyou", "welcome", "pass", "user", "test", "parol123"];

export const MIN_LENGTH = 8;

/** 0 (empty or very weak) … 4 (strong). */
export function passwordStrength(password: string, username = ""): Strength {
  if (!password) return 0;
  const lower = password.toLowerCase();
  if (password.length < MIN_LENGTH) return 1;
  if (/^\d+$/.test(password)) return 1;
  if (/^(.)\1+$/.test(password)) return 1;
  if (username && lower.includes(username.toLowerCase()) && username.length >= 3) return 1;
  if (COMMON.some((word) => lower.replace(/[\d\W_]+/g, "") === word || lower === word)) return 1;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((pattern) => pattern.test(password)).length;
  let score = 1;
  if (password.length >= 10) score++;
  if (password.length >= 14) score++;
  if (classes >= 3) score++;
  else if (classes <= 1) score--;
  return Math.max(1, Math.min(4, score)) as Strength;
}

/** The meter's tone for a score. */
export function strengthTone(score: Strength): "danger" | "warning" | "info" | "success" {
  return score <= 1 ? "danger" : score === 2 ? "warning" : score === 3 ? "info" : "success";
}

// No look-alikes (0/O, 1/l/I) so a password read aloud or copied by hand survives.
const LETTERS = "abcdefghijkmnpqrstuvwxyz";
const UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ";
const DIGITS = "23456789";

function pick(alphabet: string, random: Uint32Array, index: number): string {
  return alphabet[random[index]! % alphabet.length]!;
}

/** A strong, readable password: three groups of letters and digits ("kXm4-p7Rt-w2Qa"). */
export function generatePassword(): string {
  const random = new Uint32Array(12);
  crypto.getRandomValues(random);
  const groups: string[] = [];
  for (let g = 0; g < 3; g++) {
    const at = g * 4;
    groups.push(pick(LETTERS, random, at) + pick(UPPER, random, at + 1) + pick(LETTERS, random, at + 2) + pick(DIGITS, random, at + 3));
  }
  return groups.join("-");
}

/** A username suggested from a name: lower case Latin letters, "ali.valiyev". */
export function suggestUsername(first: string, last: string): string {
  const latin = (text: string) =>
    text
      .toLowerCase()
      .replace(/[‘’'`ʻʼ]/g, "")
      .replace(/[аәбвгғдеёжзиийкқлмнңоөпрстуүұфхһцчшщъыьэюяў]/g, (ch) => CYRILLIC[ch] ?? "")
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "");
  return [latin(first), latin(last)].filter(Boolean).join(".").slice(0, 30);
}

const CYRILLIC: Record<string, string> = {
  а: "a", ә: "a", б: "b", в: "v", г: "g", ғ: "g", д: "d", е: "e", ё: "yo", ж: "j", з: "z", и: "i", й: "y", к: "k", қ: "q", л: "l", м: "m",
  н: "n", ң: "n", о: "o", ө: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ү: "u", ұ: "u", ф: "f", х: "x", һ: "h", ц: "ts", ч: "ch",
  ш: "sh", щ: "sh", ъ: "", ы: "i", ь: "", э: "e", ю: "yu", я: "ya", ў: "o",
};

/** The pattern the server accepts for a username (Django's: letters, digits and @ . + - _). */
export const USERNAME_PATTERN = /^[A-Za-z0-9.@+_-]{3,150}$/;
