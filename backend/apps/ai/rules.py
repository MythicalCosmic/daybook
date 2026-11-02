"""Task drafts from a dictated or typed instruction without a model: the rules engine.

    draft_tasks(
        "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor. "
        "Bekzod, bugun kechqurun kassani sanab qo‘y.",
        people=people, author_id=12, now=now, lang="uz",
    )
    # [Draft("Muzlatgich haroratini tekshirish", 15, due tomorrow 10:00, proof="photo"),
    #  Draft("Kassani sanash", 12, due today 18:00)]

The fallback whenever Claude can't be asked, and the whole engine without a key (AI_FAKE
included). Deterministic: the same text, people and moment always give the same drafts. Only the
standard library and `apps.tasks.quickadd`, so it is tested as plain functions. The text it is
given is never changed (callers show the transcript as heard); it reads a copy.

Speech comes in lower case, with ASCII apostrophes (o'n, qo'y), names a letter off ("bekmzod")
and words glued or split ("o'naqadir" for o‘nga qadar, "rasmi ni"). So:

1. Instructions: new lines, numbered lists, sentence ends, and the joiners (va, keyin, hamda,
   и, потом, также, and, then) when both sides are whole instructions; a comma only before a
   person's name.
2. Who each one is for: first names and surnames, with Uzbek and Russian endings (Alisherga,
   Алишеру, Мадиной) and honorifics (aka, opa, -jon); Cyrillic is read as Latin. Where a name is
   expected (an instruction's first word, a word before a comma or an honorific) a name a letter
   or two off counts, the nearest person winning. An instruction naming nobody goes to the
   previous one's person; the first one is the author's own (assignee None). A name matching
   nobody, or several people, is kept as `assignee_guess`.
3. Photo proof: "rasmini yubor", "пришли фото", "send a photo"; a sentence that only asks for
   the photo gives it to the task before it.
4. Deadline and urgency through `apps.tasks.quickadd`, wherever they are in the sentence.
5. The rest is the title, the verb as a task's name (tekshirib -> tekshirish,
   проверь -> проверить), the first letter capital.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from apps.tasks import quickadd

MAX_DRAFTS = 10
TITLE_MAX = 200
NORMAL, URGENT = "normal", "urgent"
NO_PROOF, PHOTO = "none", "photo"
NO_MATCH, AMBIGUOUS = "no_assignee_match", "ambiguous_assignee"


@dataclass(frozen=True)
class Person:
    """Someone the speaker may name (a candidate). The author is in the list too."""

    id: int
    first_name: str
    last_name: str


@dataclass
class Draft:
    title: str
    # None: for the author (nobody named, a self word, or a name that matched nobody).
    assignee_id: int | None
    # The name heard when it matched nobody or several people, else "".
    assignee_guess: str = ""
    # Aware, in `now`'s timezone; a moment that has already passed is kept (past_due is the
    # caller's to flag).
    due_at: datetime | None = None
    priority: str = NORMAL
    proof: str = NO_PROOF
    checklist: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


# — Cyrillic to Latin —

_CYRILLIC = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "ғ": "g‘",
    "д": "d",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "қ": "q",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ў": "o‘",
    "ф": "f",
    "х": "x",
    "ҳ": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "’",
    "ы": "i",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "ё": "yo",
}
# After these (or at a word's start) the Cyrillic ye is read "ye": Ертага, Валиев, съезд.
_YE_AFTER = set("аеёиоуэюяўъь")


def to_latin(text: str) -> str:
    """Uzbek/Russian Cyrillic transliterated to Uzbek Latin (o‘ g‘ with ‘); Latin text
    unchanged."""
    out = []
    for index, char in enumerate(text):
        low = char.lower()
        if low == "е":
            before = text[index - 1].lower() if index else ""
            latin = "ye" if not before.isalpha() or before in _YE_AFTER else "e"
        elif low in _CYRILLIC:
            latin = _CYRILLIC[low]
        else:
            out.append(char)
            continue
        if char != low and latin:
            after = text[index + 1] if index + 1 < len(text) else ""
            latin = latin.upper() if after.isalpha() and after.isupper() else latin.capitalize()
        out.append(latin)
    return "".join(out)


_APOSTROPHES = "'‘’ʻʼ`´′‛"
_TO_ASCII_APOSTROPHE = str.maketrans(dict.fromkeys(_APOSTROPHES, "'"))
_NO_APOSTROPHES = str.maketrans("", "", _APOSTROPHES)
_CYRILLIC_LETTER = re.compile(r"[а-яёўқғҳ]", re.IGNORECASE)


def _fold(text: str) -> str:
    """A word for comparing: Latin, lower case, no apostrophes; "kh" and "dj" as Uzbek writes
    them (Khurshid = Xurshid, Джасур = Jasur)."""
    folded = to_latin(text).lower().translate(_NO_APOSTROPHES)
    return folded.replace("kh", "x").replace("dj", "j")


# Uzbek Cyrillic, as opposed to Russian: its own letters or its everyday words.
_UZ_CYRILLIC = re.compile(
    r"[ўқғҳ]|(?<!\w)(?:ва|эртага|бугун|соат|учун|кейин|билан|гача|илтимос|керак)(?!\w)",
    re.IGNORECASE,
)
# "o'naqadir", "o'ngaqadar": a number glued to "qadar" (by ten) by the speech model.
_GLUED_QADAR = re.compile(
    r"(?<![\w'])(o'n(?:\s?(?:bir|ikki))?|bir|ikki|uch|to'rt|besh|olti|yetti|sakkiz|to'qqiz"
    r"|\d{1,2})\s*g?a\s*q[ao]d[ai]r(?!\w)",
    re.IGNORECASE,
)


def _prepare(text: str, lang: str) -> str:
    """The copy of the text that is read: one apostrophe, Uzbek Cyrillic in Latin, glued
    numbers apart."""
    text = text.translate(_TO_ASCII_APOSTROPHE)
    if lang == "uz" and _UZ_CYRILLIC.search(text):
        text = to_latin(text).translate(_TO_ASCII_APOSTROPHE)
    return _GLUED_QADAR.sub(r"\1ga qadar", text)


# — words —

# Around a word, never part of it.
_EDGE = ' \t\n,.;:!?()[]«»"“”„—–-…'
_ADDRESS_MARKS = (",", ":", "—", "–")

# Joiners between two instructions, as written (lower case). Sequence words always split;
# "and"-like ones only with a sign that a new instruction starts (a person, a verb), so
# "muzlatgich va javon" stays one.
_SEQUENCE = {
    "keyin",
    "keyinroq",
    "so'ng",
    "so'ngra",
    "кейин",
    "сўнг",
    "сўнгра",
    "потом",
    "затем",
    "также",
    "then",
}
_COORDINATORS = {"va", "hamda", "ва", "ҳамда", "и", "and"}
_TWO_WORD_JOINERS = {
    ("and", "then"),
    ("а", "также"),
    ("а", "потом"),
    ("и", "потом"),
    ("и", "затем"),
    ("va", "keyin"),
    ("keyin", "esa"),
    ("shundan", "keyin"),
    ("shundan", "so'ng"),
    ("undan", "keyin"),
    ("undan", "so'ng"),
}
_LEADING = _SEQUENCE | _COORDINATORS | {"а", "also", "esa", "shundan", "undan"}

# Folded words that are never part of a task's title.
_FILLERS = {
    "iltimos",
    "pojaluysta",
    "please",
    "pls",
    "plz",
    "ham",
    "endi",
    "mana",
    "xop",
    "okay",
    "ok",
    "pust",
}
_UZ_CASES = ("", "ga", "ni", "ning", "da", "dan", "m", "jon", "jonga", "jonni")
_HONORIFIC_WORDS = {
    f"{word}{case}"
    for word in ("aka", "opa", "xonim", "xola", "uka", "domla", "ustoz", "jon")
    for case in _UZ_CASES
}
_SELF_UZ = {"ozim", "ozimga", "ozimni", "ozimning", "ozimiz"}
_SELF_WORDS = {"сам", "сама", "сами", "себе", "myself", "i'll"}
# Telling someone else to do it: "Alisherga ayt", "скажи Алишеру, чтобы", "ask Jasur to".
_RELAY_BEFORE = {
    "skaji",
    "skajite",
    "pereday",
    "peredayte",
    "poprosi",
    "poprosite",
    "napomni",
    "pust",
    "tell",
    "ask",
    "remind",
}
_RELAY_AFTER = {"ayt", "ayting", "aytib", "aytgin", "aytingchi", "chtobi", "chtob", "to"}

_URGENT = {
    "shoshilinch",
    "shoshilinchda",
    "tezda",
    "tezroq",
    "zudlik",
    "srochno",
    "urgent",
    "urgently",
    "asap",
}
_PHOTO = {
    "rasm",
    "rasmi",
    "rasmini",
    "rasmni",
    "rasmga",
    "rasmlar",
    "rasmlarini",
    "rasmlarni",
    "surat",
    "surati",
    "suratini",
    "suratni",
    "suratga",
    "suratlar",
    "suratlarini",
    "foto",
    "fotosi",
    "fotosini",
    "fotoni",
    "fotoga",
    "fotosurat",
    "fotosurati",
    "fotosuratini",
    "fotosuratga",
    "fotku",
    "fotki",
    "fotochku",
    "fotografiyu",
    "fotografiya",
    "fotografii",
    "sfotografiruy",
    "sfotografiruyte",
    "sfotkay",
    "sfotkayte",
    "snimok",
    "photo",
    "photos",
    "picture",
    "pictures",
    "pic",
    "pics",
    "snapshot",
}
# A photo word a letter off, as speech sometimes hears it ("basmi" for rasmi).
_PHOTO_NEAR = ("rasmi", "rasmini", "rasmni", "rasmga", "surati", "suratini", "suratga", "fotosi")
# Words of the photo request on either side of the photo word (folded).
_PHOTO_BEFORE = {
    "send",
    "take",
    "a",
    "an",
    "with",
    "and",
    "me",
    "us",
    "attach",
    "also",
    "prishli",
    "prishlite",
    "otprav",
    "otpravte",
    "skin",
    "skinte",
    "sdelay",
    "sdelayte",
    "sdelat",
    "prislat",
    "otpravit",
    "skinut",
    "s",
    "i",
    "mne",
    "nam",
    "menga",
    "bizga",
    "va",
}
_PHOTO_AFTER = {
    "yubor",
    "yuboring",
    "yuborgin",
    "yuborsin",
    "yuborib",
    "jonat",
    "jonating",
    "jonatib",
    "ol",
    "olib",
    "oling",
    "olsin",
    "tashla",
    "tashlang",
    "tashlab",
    "bilan",
    "qoy",
    "qoying",
    "prishli",
    "prishlite",
    "otprav",
    "otpravte",
    "skin",
    "skinte",
    "please",
    "too",
    # endings the speech model split off ("rasm ni", "rasmi ni")
    "ni",
    "ini",
    "si",
    "sini",
    "ga",
    "lar",
    "larini",
}
# Single words that may start a date phrase without being one on their own (folded).
_DATE_STARTS = {
    "v",
    "vo",
    "k",
    "ko",
    "do",
    "na",
    "s",
    "posle",
    "cherez",
    "soat",
    "bu",
    "shu",
    "har",
    "keyingi",
    "kelasi",
    "kelgusi",
    "yarim",
    "kun",
    "oy",
    "hafta",
    "at",
    "on",
    "by",
    "in",
    "until",
    "next",
    "this",
    "coming",
    "end",
    "every",
    "the",
    "half",
}
# Words that are not anybody's name, however they are written (folded).
_NOT_NAMES = (
    _FILLERS
    | _SELF_UZ
    | _HONORIFIC_WORDS
    | {_fold(word) for word in _LEADING}
    | {
        "hamma",
        "hammaga",
        "hammangiz",
        "barcha",
        "barchaga",
        "barchangiz",
        "jamoa",
        "jamoaga",
        "xodimlar",
        "vse",
        "vsem",
        "rebyata",
        "kollegi",
        "team",
        "everyone",
        "guys",
        "all",
        "hello",
        "hi",
        "salom",
        "assalomu",
        "privet",
        "zdravstvuyte",
        "xayrli",
        "rahmat",
        "spasibo",
        "thanks",
        "ha",
        "yoq",
        "yes",
        "no",
        "da",
        "net",
        "demak",
        "xullas",
        "mayli",
        "qarang",
        "qara",
        "eshit",
        "eshiting",
        "yaxshi",
        "xosh",
        "hozir",
        "unda",
        "shunday",
        "itak",
        "znachit",
        "slushay",
        "slushayte",
        "smotri",
        "koroche",
        "ladno",
        "xorosho",
        "so",
        "well",
        "listen",
        "look",
        "bekor",  # "bekor qil" (cancel), a letter or two from Bekzod
        # places a pharmacy names in passing ("Chilonzorga dori yetkazib ber")
        "toshkent",
        "chilonzor",
        "yunusobod",
        "sergeli",
        "yakkasaroy",
        "shayxontohur",
        "olmazor",
        "uchtepa",
        "bektemir",
        "yashnobod",
        "mirobod",
        "mirzo",
        "samarqand",
        "buxoro",
        "andijon",
        "namangan",
        "fargona",
        "qarshi",
        "navoiy",
        "nukus",
        "xorazm",
        "urganch",
        "termiz",
        "jizzax",
        "guliston",
        "qoqon",
        "margilon",
        "chirchiq",
        "olmaliq",
        "angren",
        "dorixona",
        "apteka",
        "ombor",
        "sklad",
        "filial",
    }
)
# Uzbek endings after a name (Alisherga, Alisherning, Alisherjon), folded.
_NAME_CASES = ("ning", "niki", "dan", "jon", "xon", "ga", "ka", "qa", "ni", "da")
_NAME_CASES += tuple(f"{honorific}{case}" for honorific in ("jon", "xon") for case in _UZ_CASES)
# Russian endings, read only on Cyrillic words: Алишеру, Алишера, Алишером, Алишере.
_RU_CASES = ("u", "a", "om", "e", "ym", "im", "yu")
# A name ending in -a (Мадина): Мадине, Мадину, Мадиной, Мадины.
_RU_A_CASES = ("e", "u", "oy", "i", "ey", "yu")
# Dative and accusative endings that mark a word as someone addressed ("Sardorga").
_GUESS_ENDINGS = ("ga", "ka", "qa", "ni")


@dataclass
class _Token:
    raw: str  # as written (one apostrophe), with the punctuation around it
    core: str  # without it
    word: str  # core in lower case, still in its own script
    key: str  # _fold(core)
    address: bool  # a comma, colon or dash right after it

    @property
    def is_word(self) -> bool:
        return any(char.isalnum() for char in self.core)

    @property
    def capitalized(self) -> bool:
        return bool(self.core) and self.core[0].isupper()

    @property
    def cyrillic(self) -> bool:
        return bool(_CYRILLIC_LETTER.search(self.core))


def _tokens(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    for raw in text.split():
        core = raw.strip(_EDGE)
        tail = raw[len(raw.rstrip(_EDGE)) :]
        address = any(mark in tail for mark in _ADDRESS_MARKS)
        if not core and address and tokens:  # "Alisher — kassani sanang"
            tokens[-1].address = True
        tokens.append(_Token(raw, core, core.lower(), _fold(core), address))
    return tokens


# — the people —


@dataclass(frozen=True)
class _Target:
    """Whom one draft is for: a person's id (None: the author), what was heard, problems."""

    id: int | None
    guess: str = ""
    problems: tuple[str, ...] = ()


_AUTHOR = _Target(None)


def _distance(first: str, second: str, limit: int) -> int:
    """The edit distance of two words, or `limit + 1` as soon as it is surely more."""
    if abs(len(first) - len(second)) > limit:
        return limit + 1
    previous = list(range(len(second) + 1))
    for row, letter in enumerate(first, 1):
        current = [row]
        for column, other in enumerate(second, 1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (letter != other),
                )
            )
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


class _People:
    def __init__(self, people: list[Person]):
        # Each folded name word -> (the people with it, the word as their record writes it).
        self.names: dict[str, tuple[set[int], str]] = {}
        for person in people:
            for part in (person.first_name, person.last_name):
                for word in part.split():
                    shown = word.strip(_EDGE)
                    key = _fold(shown)
                    if len(key) < 2:
                        continue
                    self.names.setdefault(key, (set(), shown))[0].add(person.id)

    def match(self, token: _Token) -> tuple[set[int], str]:
        """Who the word names, and the name as their record writes it; nobody: (set(), "")."""
        word = token.key
        if not word or not token.core[:1].isalpha():
            return set(), ""
        if word in self.names and (len(word) > 3 or token.capitalized):
            ids, shown = self.names[word]
            return set(ids), shown
        found: set[int] = set()
        spellings: set[str] = set()
        for name, (ids, shown) in self.names.items():
            if len(name) <= 3 and not token.capitalized:
                continue  # "nur", "gul", "oy" in lower case are words, not people
            if _names(word, name, russian=token.cyrillic):
                found |= ids
                spellings.add(shown)
        # One form may fit two names (Дилшоде: Dilshod or Dilshoda): all of them, never the
        # first one tried; several people are ambiguous, as the caller says.
        return found, next(iter(spellings)) if len(spellings) == 1 else ""

    def near(self, token: _Token, *, strict: bool) -> tuple[set[int], str]:
        """The people a name a letter or two off may mean (where a name is expected): up to two
        edits for names of five letters or more, one for four, none below; one fewer when
        `strict`. The nearest wins; equally near people are all returned (ambiguous)."""
        if not _may_be_name(token):
            return set(), ""
        stems = _stems(token.key, russian=token.cyrillic)
        nearest: int | None = None
        found: set[int] = set()
        spellings: set[str] = set()
        for name, (ids, shown) in self.names.items():
            limit = (2 if len(name) >= 5 else 1 if len(name) == 4 else 0) - strict
            if limit <= 0:
                continue
            distance = min(_distance(stem, name, limit) for stem in stems)
            if distance > limit:
                continue
            if nearest is None or distance < nearest:
                nearest, found, spellings = distance, set(ids), {shown}
            elif distance == nearest:
                found |= ids
                spellings.add(shown)
        # Two people both named Alisher, heard as "alishr": "Alisher", as their records write it.
        return found, next(iter(spellings)) if len(spellings) == 1 else ""

    def is_person(self, token: _Token) -> bool:
        return bool(self.match(token)[0])


def _names(word: str, name: str, *, russian: bool) -> bool:
    if word == name:
        return True
    ending = word[len(name) :] if word.startswith(name) else None
    if ending in _NAME_CASES or (russian and ending in _RU_CASES):
        return True
    stem = name[:-1]
    return (
        russian
        and name.endswith("a")
        and len(name) > 3
        and word.startswith(stem)
        and word[len(stem) :] in _RU_A_CASES
    )


def _stems(key: str, *, russian: bool) -> set[str]:
    """The word and the word without one ending: what a misheard name is compared as."""
    stems = {key}
    endings = _NAME_CASES + (_RU_CASES + _RU_A_CASES if russian else ())
    for ending in endings:
        if key.endswith(ending) and len(key) - len(ending) >= 3:
            stems.add(key[: -len(ending)])
    return stems


def _may_be_name(token: _Token) -> bool:
    """A word that could be someone's name: letters only, and not a word this module knows
    (a date, a filler, a joiner, a photo word, a verb)."""
    key = token.key
    return (
        len(key) >= 3
        and all(char.isalpha() or char in "'-" for char in token.core)
        and key not in _NOT_NAMES
        and _without(key, (*_GUESS_ENDINGS, "jon", "xon")) not in _NOT_NAMES
        and token.word not in _LEADING
        and not _is_photo_word(token)
        and key not in _URGENT
        and key not in _UZ_NOUNS
        and key not in _UZ_AUXILIARIES
        and token.word not in _RU_INFINITIVES
        and not _is_date_text(token.core)
    )


def _is_self(token: _Token, lang: str) -> bool:
    if token.word in _SELF_WORDS:
        return True
    if token.key in _SELF_UZ and not token.cyrillic:
        return True
    return lang == "uz" and token.word == "men"


def _address_positions(tokens: list[_Token], people: _People) -> dict[int, bool]:
    """Where a name is expected, and whether a mark says so (a comma, an honorific, a "tell"):
    marked places take a name two letters off, the first word alone one letter."""
    places: dict[int, bool] = {}
    first = next(
        (
            index
            for index, token in enumerate(tokens)
            if token.is_word and token.word not in _LEADING and token.key not in _FILLERS
        ),
        None,
    )
    if first is not None:
        places[first] = False
    for index, token in enumerate(tokens):
        after = tokens[index + 1] if index + 1 < len(tokens) else None
        before = tokens[index - 1] if index else None
        if (
            token.address
            or (after is not None and after.key in _HONORIFIC_WORDS)
            or (after is not None and after.key in _RELAY_AFTER and after.key != "to")
            or (before is not None and before.key in _RELAY_BEFORE)
        ):
            places[index] = True
        elif (
            index >= 2
            and before.word in _COORDINATORS
            and people.is_person(tokens[index - 2])
            and index not in places
        ):
            places[index] = False  # "alisher va madna"
    return places


def _find_people(tokens, used, people: _People, lang: str) -> list[_Target] | None:
    """The targets an instruction names (None: nobody), marking their words used."""
    places = _address_positions(tokens, people)
    targets: list[_Target] = []
    found_self = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        ids, shown = people.match(token)
        if not ids and index in places:
            ids, shown = people.near(token, strict=not places[index])
        if not ids:
            if _is_self(token, lang):
                used[index] = True
                found_self = True
            index += 1
            continue
        run, common = [index], set(ids)
        end = index + 1
        while end < len(tokens):
            nxt = tokens[end]
            if nxt.key in _HONORIFIC_WORDS:
                run.append(end)
                end += 1
                continue
            if tokens[end - 1].address:
                break
            more, _ = people.match(nxt)
            if not more:
                more, _ = people.near(nxt, strict=False)
            if more & common:  # "Alisher Valiyev"
                common &= more
                run.append(end)
                end += 1
                continue
            break
        for position in run:
            used[position] = True
        _mark_relay(tokens, used, run[0], run[-1])
        if len(common) == 1:
            target = _Target(next(iter(common)))
        else:
            heard = shown or _shown_name(token.core)
            target = _Target(None, heard, (AMBIGUOUS,))
        if target not in targets:
            targets.append(target)
        index = end
    if targets:
        return targets
    if guess := _guess(tokens, used):
        return [_Target(None, guess, (NO_MATCH,))]
    return [_AUTHOR] if found_self else None


def _mark_relay(tokens: list[_Token], used: list[bool], first: int, last: int) -> None:
    """ "Скажи Алишеру, чтобы…", "Alisherga ayt…", "ask Jasur to…": the telling isn't the task."""
    if first > 0 and tokens[first - 1].key in _RELAY_BEFORE:
        used[first - 1] = True
    if last + 1 < len(tokens) and tokens[last + 1].key in _RELAY_AFTER:
        used[last + 1] = True


def _guess(tokens: list[_Token], used: list[bool]) -> str:
    """A name heard but matching nobody: the first word before a comma ("sardor, …"), a word
    with an honorific ("sardor aka", "sardorjon"), or a capitalized word someone is told
    something with ("… Sardorga ayt")."""
    for index, token in enumerate(tokens):
        if used[index] or not _may_be_name(token):
            continue
        after = tokens[index + 1] if index + 1 < len(tokens) else None
        stem = _without(token.key, ("jon", "xon"))
        if index == 0 and token.address:
            pass
        elif after is not None and after.key in _HONORIFIC_WORDS:
            used[index + 1] = True
        elif stem != token.key or (
            index > 0 and token.capitalized and _without(token.key, _GUESS_ENDINGS) != token.key
        ):
            pass
        else:
            continue
        used[index] = True
        _mark_relay(tokens, used, index, index)
        return _shown_name(token.core)
    return ""


def _without(word: str, endings: tuple[str, ...]) -> str:
    for ending in sorted(endings, key=len, reverse=True):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def _shown_name(core: str) -> str:
    """The heard name without its case ending, capitalized: sardorga -> Sardor,
    Сардору -> Сардор."""
    if _CYRILLIC_LETTER.search(core):
        endings: tuple[str, ...] = ("ом", "у")
    else:
        endings = ("ning", "jonga", "jonni", "dan", "jon", "xon", "ga", "ka", "qa", "ni", "da")
    for ending in endings:
        if core.lower().endswith(ending) and len(core) - len(ending) >= 3:
            core = core[: -len(ending)]
            break
    return core[:1].upper() + core[1:]


# — dates and urgency —

# Any fixed moment will do to ask whether one word reads as a date.
_PROBE_NOW = datetime.fromisoformat("2026-01-05T12:00:00+05:00")


@lru_cache(maxsize=4096)
def _is_date_text(text: str) -> bool:
    return bool(text) and quickadd.parse(text, now=_PROBE_NOW).found


def _date_start(token: _Token) -> bool:
    return (
        any(char.isdigit() for char in token.core)
        or token.key in _DATE_STARTS
        or _is_date_text(token.core)
    )


@dataclass
class _When:
    due_at: datetime | None
    urgent: bool


def _find_when(tokens: list[_Token], used: list[bool], now: datetime, lang: str) -> _When | None:
    """The deadline wherever it is said: the longest phrases (up to three, six words each) that
    read as dates on their own, read together. Their words are marked used."""
    free = [index for index, flag in enumerate(used) if not flag and tokens[index].is_word]
    spans: list[list[int]] = []
    taken: set[int] = set()
    for _round in range(3):
        best: list[int] = []
        for start in range(len(free)):
            if free[start] in taken or not _date_start(tokens[free[start]]):
                continue
            longest = min(len(free), start + 6)
            for end in range(longest, start, -1):
                if end - start <= len(best):
                    break
                span = free[start:end]
                if any(index in taken for index in span):
                    continue
                if _pure_date(_span_text(tokens, span), now, lang):
                    best = span
                    break
        if not best:
            break
        spans.append(best)
        taken.update(best)
    if not spans:
        return None
    for span in spans:
        for index in span:
            used[index] = True
    ordered = sorted(spans, key=lambda span: span[0])
    found = _pure_date(" ".join(_span_text(tokens, span) for span in ordered), now, lang)
    if found is None:
        found = _pure_date(_span_text(tokens, spans[0]), now, lang)
    due = found.due_at or (found.passed if found.past else None)
    return _When(due, found.priority == URGENT)


def _span_text(tokens: list[_Token], span: list[int]) -> str:
    return " ".join(tokens[index].core for index in span)


def _pure_date(text: str, now: datetime, lang: str) -> quickadd.QuickAdd | None:
    found = quickadd.parse(text, now=now, lang=lang)
    return found if found.found and not found.title else None


def _find_urgency(tokens: list[_Token], used: list[bool]) -> bool:
    urgent = False
    for index, token in enumerate(tokens):
        if "!!" in token.raw:
            urgent = True
        if used[index] or token.key not in _URGENT:
            continue
        used[index] = True
        urgent = True
        if token.key == "zudlik" and index + 1 < len(tokens) and tokens[index + 1].key == "bilan":
            used[index + 1] = True
    return urgent


def _find_photo(tokens: list[_Token], used: list[bool]) -> list[int]:
    """The words of a photo request, marked used (the photo word first)."""
    marked: list[int] = []
    for index, token in enumerate(tokens):
        if used[index]:
            continue
        starts_part = index == 0 or tokens[index - 1].address
        exact = _is_photo_word(token)
        if not exact and not (starts_part and _near_photo_word(token)):
            continue
        request = [index]
        before = index - 1
        while before >= 0 and not used[before] and tokens[before].key in _PHOTO_BEFORE:
            request.append(before)
            before -= 1
        after = index + 1
        while after < len(tokens) and not used[after] and tokens[after].key in _PHOTO_AFTER:
            request.append(after)
            after += 1
        if before < 0 or tokens[before].address:
            # The request is its own part of the sentence (", rasmini yubor"): what the speech
            # model garbled after the photo word ("basmi ni yo'qdor") goes with it.
            rest = []
            while after < len(tokens) and not tokens[after - 1].address:
                rest.append(after)
                after += 1
            if len([position for position in rest if tokens[position].is_word]) <= 2:
                request.extend(rest)
        for position in request:
            used[position] = True
        marked.extend(request)
    return marked


def _is_photo_word(token: _Token) -> bool:
    key = token.key
    if key == "surat" and "'" in token.core:
        return False  # sur'at: speed
    if key in _PHOTO:
        return True
    return key.startswith(("rasm", "surat", "foto", "photo", "sfotograf")) and not key.startswith(
        ("rasmiy", "rasmona")
    )


def _near_photo_word(token: _Token) -> bool:
    key = token.key
    if len(key) < 5 or key.startswith("rasmiy"):
        return False
    return any(_distance(key, word, 1) <= 1 for word in _PHOTO_NEAR)


# — titles —

# Uzbek: a verb at the end as a task's name. An auxiliary after a converb goes ("sanab qo‘y"),
# the converb becomes the verbal noun (sanab -> sanash), and so do common imperatives.
_UZ_AUXILIARIES = {
    f"{stem}{ending}"
    for stem, endings in {
        "qoy": ("", "ing", "inglar", "gin", "sin", "aman"),
        "chiq": ("", "ing", "inglar", "gin", "sin", "aman"),
        "ber": ("", "ing", "inglar", "gin", "sin", "aman"),
        "tashla": ("", "ng", "nglar", "gin", "sin", "yman"),
        "kor": ("", "ing", "gin", "sin"),
        "yubor": ("", "ing", "gin", "sin"),
        "ol": ("", "ing", "gin", "sin", "aman"),
    }.items()
    for ending in endings
}
# Words ending in -ib/-ab that are not converbs.
_NOT_CONVERBS = {
    "tartib",
    "ajib",
    "garib",
    "golib",
    "nasib",
    "habib",
    "tabib",
    "adib",
    "raqib",
    "kotib",
    "sabab",
    "talab",
    "arab",
    "maktab",
    "rajab",
    "adab",
}
_UZ_VERBS = (
    "tekshir",
    "sana",
    "tozala",
    "yubor",
    "joyla",
    "joylashtir",
    "tayyorla",
    "yetkaz",
    "qil",
    "ol",
    "ter",
    "yoz",
    "o‘lcha",
    "keltir",
    "almashtir",
    "o‘chir",
    "yig‘ishtir",
    "ayt",
    "chiqar",
    "kirit",
    "to‘ldir",
    "yuv",
    "art",
    "tashla",
    "ko‘r",
    "hisobla",
    "jo‘nat",
    "kel",
    "sot",
    "ishla",
    "tuz",
    "tarqat",
    "o‘qi",
    "yangila",
    "kut",
    "o‘tkaz",
    "yop",
    "och",
    "saqla",
    "belgila",
    "o‘rnat",
    "ta’mirla",
)
_VOWEL_FORMS = ("", "ng", "nglar", "ngiz", "gin", "sin", "yman", "ymiz")
_CONSONANT_FORMS = ("", "ing", "inglar", "ingiz", "gin", "sin", "aman", "amiz")
# Alone as a whole title these stay as said: "ol" (take), "kel", "sot", "tuz" are words too.
_LONE_VERBS = {"ol", "kel", "sot", "tuz", "och", "yop", "art", "ter"}


def _uz_nouns() -> dict[str, str]:
    nouns = {}
    for stem in _UZ_VERBS:
        vowel = stem[-1] in "aeiou"
        noun = stem + ("sh" if vowel else "ish")
        for form in _VOWEL_FORMS if vowel else _CONSONANT_FORMS:
            nouns.setdefault(_fold(stem + form), noun)
    return nouns


_UZ_NOUNS = _uz_nouns()

# Russian: an imperative (or "чтобы проверил") as the infinitive a task is named with.
_RU_VERBS = {
    "проверить": ("проверь", "проверьте"),
    "посчитать": ("посчитай", "посчитайте"),
    "пересчитать": ("пересчитай", "пересчитайте"),
    "сделать": ("сделай", "сделайте"),
    "убрать": ("убери", "уберите"),
    "разложить": ("разложи", "разложите"),
    "отправить": ("отправь", "отправьте"),
    "принести": ("принеси", "принесите"),
    "заказать": ("закажи", "закажите"),
    "позвонить": ("позвони", "позвоните"),
    "принять": ("приними", "примите"),
    "выложить": ("выложи", "выложите"),
    "протереть": ("протри", "протрите"),
    "сверить": ("сверь", "сверьте"),
    "подготовить": ("подготовь", "подготовьте"),
    "доставить": ("доставь", "доставьте"),
    "оформить": ("оформи", "оформите"),
    "распечатать": ("распечатай", "распечатайте"),
    "заменить": ("замени", "замените"),
    "почистить": ("почисть", "почистите"),
    "навести": ("наведи", "наведите"),
    "записать": ("запиши", "запишите"),
    "написать": ("напиши", "напишите"),
    "купить": ("купи", "купите"),
    "отнести": ("отнеси", "отнесите"),
    "отвезти": ("отвези", "отвезите"),
    "привезти": ("привези", "привезите"),
    "забрать": ("забери", "заберите"),
    "помыть": ("помой", "помойте"),
    "вымыть": ("вымой", "вымойте"),
    "уточнить": ("уточни", "уточните"),
    "проконтролировать": ("проконтролируй", "проконтролируйте"),
    "расставить": ("расставь", "расставьте"),
    "посмотреть": ("посмотри", "посмотрите"),
    "проследить": ("проследи", "проследите"),
    "сообщить": ("сообщи", "сообщите"),
    "внести": ("внеси", "внесите"),
    "обновить": ("обнови", "обновите"),
    "разобрать": ("разбери", "разберите"),
    "упаковать": ("упакуй", "упакуйте"),
    "провести": ("проведи", "проведите"),
    "получить": ("получи", "получите"),
}


def _ru_infinitives() -> dict[str, str]:
    forms = {}
    for infinitive, imperatives in _RU_VERBS.items():
        for form in imperatives:
            forms[form] = infinitive
        if infinitive.endswith("ть"):  # "чтобы проверил", "проверила"
            for ending in ("л", "ла", "ли"):
                forms.setdefault(infinitive[:-2] + ending, infinitive)
    return forms


_RU_INFINITIVES = _ru_infinitives()
_DANGLING = {"в", "во", "к", "ко", "до", "на", "at", "on", "by", "in", "until", "soat", "соат"}
_UZ_OKINA = re.compile(r"(?<=[oOgG])'")
_UZ_TUTUQ = re.compile(r"(?<=\w)'(?=\w)")


def _make_title(tokens: list[_Token], used: list[bool], lang: str) -> str:
    words = [token.raw for index, token in enumerate(tokens) if not used[index]]
    text = " ".join(words).replace("!!", "")
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(\s*[,;:])+", r"\1", text)
    text = _trim(text)
    if not any(char.isalpha() for char in text):
        return ""  # a list number or a time left alone is no task
    uzbek_latin = lang == "uz" and not _CYRILLIC_LETTER.search(text)
    if uzbek_latin:
        text = _uz_title(text)
    text = _ru_title(text)
    if uzbek_latin:  # o‘ g‘ with ‘, the tutuq belgisi with ’
        text = _UZ_TUTUQ.sub("’", _UZ_OKINA.sub("‘", text))
    text = text[:1].upper() + text[1:]
    return text[:TITLE_MAX].rstrip()


def _trim(text: str) -> str:
    parts = text.strip(_EDGE).split()
    while parts and parts[-1].lower().strip(_EDGE) in _DANGLING:
        parts.pop()
    while parts and parts[0].lower().strip(_EDGE) in _DANGLING:
        parts.pop(0)
    return " ".join(parts).strip(_EDGE)


def _uz_title(text: str) -> str:
    words = text.split()
    if len(words) >= 2 and _fold(words[-1]) in _UZ_AUXILIARIES and _is_converb(words[-2]):
        words.pop()
    last = words[-1]
    key = _fold(last)
    if _is_converb(last):
        words[-1] = last[:-2] + "ish" if key.endswith("ib") else last[:-1] + "sh"
    elif key in _UZ_NOUNS and (len(words) > 1 or key not in _LONE_VERBS):
        words[-1] = _UZ_NOUNS[key]
    return " ".join(words)


def _is_converb(word: str) -> bool:
    key = _fold(word)
    return len(key) >= 4 and key.endswith(("ib", "ab")) and key not in _NOT_CONVERBS


def _ru_title(text: str) -> str:
    words = text.split()
    for position in dict.fromkeys((0, len(words) - 1)):
        core = words[position].strip(_EDGE)
        infinitive = _RU_INFINITIVES.get(core.lower())
        if infinitive:
            words[position] = words[position].replace(core, infinitive)
            break
    return " ".join(words)


# — splitting into instructions —

_MARKER = re.compile(r"(?:^|(?<=\s))(\d{1,2})[.)\-](?=\s)")
_BULLET = re.compile(r"^\s*[-•*–—]\s+")
_LINE_MARKER = re.compile(r"^\s*\d{1,2}[.)\-]\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?;…])\s+")
_DETERMINERS = {
    "the",
    "a",
    "an",
    "all",
    "some",
    "any",
    "my",
    "our",
    "your",
    "his",
    "her",
    "their",
    "its",
    "this",
    "that",
    "these",
    "those",
    "every",
    "each",
    "both",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    "to",
    "of",
}
_RU_IMPERATIVE = re.compile(r"(?:[йь]|и|[ий]те|ьте)$")


def _numbered(line: str) -> list[str]:
    """A line split at its list markers (1. 2. 3., 1) 2), 1- 2-), when they count from 1."""
    accepted, want = [], 1
    for match in _MARKER.finditer(line):
        if int(match.group(1)) == want:
            accepted.append(match)
            want += 1
    if not accepted or (len(accepted) == 1 and line[: accepted[0].start()].strip()):
        return [line]
    items, start = [], 0
    for match in accepted:
        items.append(line[start : match.start()])
        start = match.end()
    items.append(line[start:])
    return [item for item in items if item.strip()]


def _sentences(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        items = _numbered(_BULLET.sub("", line))
        if len(items) == 1:  # one item of a list written a line each: "2. Madina, …"
            items = [_LINE_MARKER.sub("", items[0])]
        for item in items:
            out.extend(part for part in _SENTENCE_END.split(item) if part.strip())
    return out


def _clauses(sentence: str, people: _People) -> list[list[_Token]]:
    tokens = _tokens(sentence)
    clauses: list[list[_Token]] = [[]]
    index = 0
    while index < len(tokens):
        size = _joiner_size(tokens, index)
        if size and _splits(tokens, clauses[-1], index, size, people):
            clauses.append([])
            index += size
            continue
        token = tokens[index]
        clauses[-1].append(token)
        if (
            token.address
            and index + 1 < len(tokens)
            and people.is_person(tokens[index + 1])
            and _content(clauses[-1], people)
        ):
            clauses.append([])  # "…, Madina omborni tekshirsin"
        index += 1
    return [clause for clause in clauses if any(token.is_word for token in clause)]


def _joiner_size(tokens: list[_Token], index: int) -> int:
    word = tokens[index].word
    if index + 1 < len(tokens) and (word, tokens[index + 1].word) in _TWO_WORD_JOINERS:
        return 2
    return 1 if word in _SEQUENCE or word in _COORDINATORS else 0


def _splits(tokens: list[_Token], clause: list[_Token], index: int, size: int, people) -> bool:
    """Whether the joiner at `index` starts a new instruction."""
    left = [token for token in clause if token.is_word]
    right: list[_Token] = []
    position = index + size
    while position < len(tokens):
        if right and _joiner_size(tokens, position):
            break
        if tokens[position].is_word:
            right.append(tokens[position])
        position += 1
    if len(left) < 2 or len(right) < 2:
        return False
    first = tokens[index].word
    if size == 1 and first in ("keyin", "so'ng", "кейин", "сўнг") and left[-1].key.endswith("dan"):
        return False  # "soatdan keyin", "tushdan keyin": a time, not a new instruction
    if size == 2 or first in _SEQUENCE:
        return True
    names_left, names_right = people.is_person(left[-1]), people.is_person(right[0])
    if names_left and names_right:
        return False  # "Alisher va Madina"
    if names_right or _is_photo_word(right[0]):
        return True
    if first == "and":
        return right[0].key not in _DETERMINERS
    if first == "и":  # a verb after it starts a new instruction
        return len(right[0].core) >= 4 and bool(_RU_IMPERATIVE.search(right[0].word))
    return _is_converb(left[-1].core) or left[-1].key in _UZ_NOUNS


def _content(clause: list[_Token], people: _People) -> bool:
    """Whether a clause says more than names."""
    return any(
        token.is_word and not people.is_person(token) and token.key not in _HONORIFIC_WORDS
        for token in clause
    )


# — reading one instruction —


@dataclass
class _Reading:
    targets: list[_Target] | None
    title: str
    # The title with the photo words kept, for a sentence that is nothing but the request.
    request_title: str
    when: _When | None
    urgent: bool
    photo: bool


def _read(clause: list[_Token], people: _People, now: datetime, lang: str) -> _Reading:
    used = [False] * len(clause)
    targets = _find_people(clause, used, people, lang)
    photo = _find_photo(clause, used)
    urgent = _find_urgency(clause, used)
    when = _find_when(clause, used, now, lang)
    for index, token in enumerate(clause):
        if token.key in _FILLERS or token.key in _HONORIFIC_WORDS:
            used[index] = True
    for index, token in enumerate(clause):  # "Keyin …", "Потом …", "Then …"
        if used[index] or not token.is_word:
            continue
        if token.word in _LEADING:
            used[index] = True
            continue
        break
    title = _make_title(clause, used, lang)
    request_title = ""
    if not title and photo:
        for index in photo:
            used[index] = False
        request_title = _make_title(clause, used, lang)
    return _Reading(
        targets,
        title,
        request_title,
        when,
        urgent or bool(when and when.urgent),
        bool(photo),
    )


def draft_tasks(
    text: str, *, people: list[Person], author_id: int, now: datetime, lang: str
) -> list[Draft]:
    """At most MAX_DRAFTS drafts, in the order spoken. Deterministic. `author_id` is the
    speaker's own id: a draft for them says so by name, or by None when nobody was named."""
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware, in the company's timezone.")
    lang = (lang or "")[:2].lower()
    known = _People(people)
    drafts: list[Draft] = []
    carried: list[_Target] = [_AUTHOR]
    waiting_targets: list[_Target] | None = None  # "Alisher!" before the task itself
    waiting: _Reading | None = None  # a deadline or "srochno" said before the task
    previous: list[Draft] = []
    for sentence in _sentences(_prepare(text, lang)):
        for clause in _clauses(sentence, known):
            reading = _read(clause, known, now, lang)
            targets = reading.targets
            if waiting_targets:
                extra = [target for target in targets or [] if target not in waiting_targets]
                targets, waiting_targets = waiting_targets + extra, None
            title = reading.title
            if not title:
                if reading.photo and previous and targets is None:
                    _complete(previous, reading)  # "Keyin rasmini yubor."
                    continue
                if reading.photo and reading.request_title:
                    title = reading.request_title  # "Rasmini yubor" said on its own
                else:
                    if targets:
                        waiting_targets = targets
                    if reading.when or reading.urgent:
                        if previous and targets is None:
                            _complete(previous, reading)  # "Kassani sana. Ertaga."
                        else:
                            waiting = reading
                    continue
            if targets is None:
                targets = carried
            carried = targets
            group = []
            for target in targets[: MAX_DRAFTS - len(drafts)]:
                draft = Draft(
                    title=title,
                    assignee_id=target.id,
                    assignee_guess=target.guess,
                    due_at=reading.when.due_at if reading.when else None,
                    priority=URGENT if reading.urgent else NORMAL,
                    proof=PHOTO if reading.photo else NO_PROOF,
                    problems=list(target.problems),
                )
                if waiting is not None:
                    _complete([draft], waiting)
                group.append(draft)
            waiting = None
            drafts.extend(group)
            previous = group or previous
            if len(drafts) >= MAX_DRAFTS:
                return drafts
    return drafts


def _complete(drafts: list[Draft], reading: _Reading) -> None:
    """What a sentence without a task of its own adds to the drafts it belongs to."""
    for draft in drafts:
        if reading.when and reading.when.due_at and draft.due_at is None:
            draft.due_at = reading.when.due_at
        if reading.urgent:
            draft.priority = URGENT
        if reading.photo:
            draft.proof = PHOTO
