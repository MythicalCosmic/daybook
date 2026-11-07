"""Demo data of stock (docs/PLAN-OWNER.md §14.3, rule 22): Demo Dorixona's medicines, their
batches in both pharmacies, eight weeks of stock documents, and a smaller warehouse stock for
Demo Distribyutor.

The story, as of the day the demo is built:
- a catalogue of 70 items (medicines by INN, strength, form and pack; devices, vitamins,
  hygiene), 26 of them prescription-only (6 antibiotics and 2 systemic hormones in the
  e-prescription group), 3 cold-chain items, 4 controlled and 2 restricted strong-acting items
  held only at Yunusobod (licensed), 8 socially significant, 20 on the mandatory list (one of
  them missing at Chilonzor);
- opening stock eight weeks ago, then six weeks of deliveries from four distributors (one
  waiting for posting, one with a cost jump, one with a short shelf life): 3 batches expired and
  waiting for write-off, 8 expiring within 30 days and 12 within 31-90 days, the rest 6 to 36
  months out;
- 4 transfers (one arrived short, disputed), 3 write-offs (one destroyed by a full commission
  with its act, one approved and waiting with 12 days left, one proposed), 2 applied counts (one
  120 000 so‘m short) and one open, a recalled series found in both pharmacies, 15 defektura
  rows, and the controlled register of last month closed at Yunusobod.

Only invented company and brand names; medicines by their generic names.
"""

from __future__ import annotations

import io
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction

from apps.core import demo_plan
from apps.core.demo_time import moment
from apps.inventory import conf, defaults, engine, register, services
from apps.inventory.models import (
    BatchStock,
    Manufacturer,
    MissingRequest,
    Product,
    SupplierProfile,
)

D = Decimal
MAKERS = {
    "zarafshon": ("Zarafshon Farm", "UZ"),
    "chorvoq": ("Chorvoq Farmatsevtika", "UZ"),
    "kohna": ("Ko‘hna Shahar Med", "UZ"),
    "turon": ("Turon Medteks", "UZ"),
    "bahor": ("Bahor Vita", "UZ"),
    "helvetor": ("Helvetor Pharma", "CH"),
    "anadolin": ("Anadolin Ilach", "TR"),
    "sindhura": ("Sindhura Generics", "IN"),
    "baltavia": ("Baltavia Pharm", "LV"),
}
# key: (name, inn, form, strength, parts, part label, kind, category, maker, cost per pack, flags)
# flags: rx, erx (e-prescription group), cold, social, must (mandatory list), narcotic, psycho,
# strong (listed), star (restricted channel), cream...
CATALOGUE = {
    "amox": (
        "Amoksitsillin 500 mg kapsula №16",
        "amoxicillin",
        "capsule",
        "500 mg",
        2,
        "blister",
        "medicine",
        "antibiotics",
        "zarafshon",
        18500,
        "rx erx must",
    ),
    "amoxclav": (
        "Amoksitsillin + klavulan kislotasi 875/125 mg tabletka №14",
        "amoxicillin+clavulanic acid",
        "tablet",
        "875/125 mg",
        2,
        "blister",
        "medicine",
        "antibiotics",
        "anadolin",
        42000,
        "rx erx",
    ),
    "azit": (
        "Azitromitsin 500 mg tabletka №3",
        "azithromycin",
        "tablet",
        "500 mg",
        1,
        "",
        "medicine",
        "antibiotics",
        "sindhura",
        24000,
        "rx erx",
    ),
    "cefix": (
        "Sefiksim 400 mg kapsula №6",
        "cefixime",
        "capsule",
        "400 mg",
        1,
        "",
        "medicine",
        "antibiotics",
        "anadolin",
        51000,
        "rx erx",
    ),
    "cipro": (
        "Siprofloksatsin 500 mg tabletka №10",
        "ciprofloxacin",
        "tablet",
        "500 mg",
        1,
        "",
        "medicine",
        "antibiotics",
        "chorvoq",
        9800,
        "rx erx",
    ),
    "ceftri": (
        "Seftriakson 1 g in’eksiya uchun kukun №1",
        "ceftriaxone",
        "powder",
        "1 g",
        1,
        "",
        "medicine",
        "antibiotics",
        "sindhura",
        7900,
        "rx erx",
    ),
    "pred": (
        "Prednizolon 5 mg tabletka №100",
        "prednisolone",
        "tablet",
        "5 mg",
        10,
        "blister",
        "medicine",
        "hormones",
        "chorvoq",
        14200,
        "rx erx",
    ),
    "dexa": (
        "Deksametazon 4 mg/ml in’eksiya eritmasi 1 ml №10",
        "dexamethasone",
        "injection",
        "4 mg/ml",
        10,
        "ampula",
        "medicine",
        "hormones",
        "baltavia",
        16800,
        "rx erx",
    ),
    "metf": (
        "Metformin 850 mg tabletka №60",
        "metformin",
        "tablet",
        "850 mg",
        6,
        "blister",
        "medicine",
        "hormones",
        "zarafshon",
        21000,
        "rx social must",
    ),
    "glarg": (
        "Insulin glargin 100 TB/ml 3 ml shprits-ruchka №5",
        "insulin glargine",
        "injection",
        "100 TB/ml",
        5,
        "ruchka",
        "medicine",
        "hormones",
        "helvetor",
        312000,
        "rx cold social must",
    ),
    "aspart": (
        "Insulin aspart 100 TB/ml 3 ml shprits-ruchka №5",
        "insulin aspart",
        "injection",
        "100 TB/ml",
        5,
        "ruchka",
        "medicine",
        "hormones",
        "helvetor",
        285000,
        "rx cold social",
    ),
    "amlo": (
        "Amlodipin 5 mg tabletka №30",
        "amlodipine",
        "tablet",
        "5 mg",
        3,
        "blister",
        "medicine",
        "heart",
        "kohna",
        12600,
        "rx",
    ),
    "biso": (
        "Bisoprolol 5 mg tabletka №30",
        "bisoprolol",
        "tablet",
        "5 mg",
        3,
        "blister",
        "medicine",
        "heart",
        "baltavia",
        18900,
        "rx social",
    ),
    "lisin": (
        "Lizinopril 10 mg tabletka №30",
        "lisinopril",
        "tablet",
        "10 mg",
        3,
        "blister",
        "medicine",
        "heart",
        "zarafshon",
        9900,
        "rx social must",
    ),
    "lisin2": (
        "Lizinopril-Kohna 10 mg tabletka №20",
        "lisinopril",
        "tablet",
        "10 mg",
        2,
        "blister",
        "medicine",
        "heart",
        "kohna",
        7400,
        "rx social",
    ),
    "atorva": (
        "Atorvastatin 20 mg tabletka №30",
        "atorvastatin",
        "tablet",
        "20 mg",
        3,
        "blister",
        "medicine",
        "heart",
        "anadolin",
        31500,
        "rx",
    ),
    "losar": (
        "Lozartan 50 mg tabletka №30",
        "losartan",
        "tablet",
        "50 mg",
        3,
        "blister",
        "medicine",
        "heart",
        "sindhura",
        22500,
        "rx social",
    ),
    "clopi": (
        "Klopidogrel 75 mg tabletka №28",
        "clopidogrel",
        "tablet",
        "75 mg",
        2,
        "blister",
        "medicine",
        "heart",
        "anadolin",
        27000,
        "rx",
    ),
    "warf": (
        "Varfarin 2,5 mg tabletka №100",
        "warfarin",
        "tablet",
        "2.5 mg",
        10,
        "blister",
        "medicine",
        "heart",
        "baltavia",
        24800,
        "rx",
    ),
    "hctz": (
        "Gidroxlorotiazid 25 mg tabletka №20",
        "hydrochlorothiazide",
        "tablet",
        "25 mg",
        2,
        "blister",
        "medicine",
        "heart",
        "chorvoq",
        6400,
        "rx",
    ),
    "levo": (
        "Levotiroksin natriy 50 mkg tabletka №100",
        "levothyroxine",
        "tablet",
        "50 mkg",
        4,
        "blister",
        "medicine",
        "hormones",
        "helvetor",
        26500,
        "rx",
    ),
    "salb": (
        "Salbutamol 100 mkg/doza ingalyatsiya uchun aerozol 200 doza",
        "salbutamol",
        "spray",
        "100 mkg/doza",
        1,
        "",
        "medicine",
        "cold",
        "baltavia",
        32000,
        "rx",
    ),
    "carba": (
        "Karbamazepin 200 mg tabletka №50",
        "carbamazepine",
        "tablet",
        "200 mg",
        5,
        "blister",
        "medicine",
        "nervous",
        "chorvoq",
        19800,
        "rx",
    ),
    "mome": (
        "Mometazon 0,1 % krem 15 g",
        "mometasone",
        "cream",
        "0.1 %",
        1,
        "",
        "medicine",
        "allergy",
        "anadolin",
        38000,
        "rx",
    ),
    "interf": (
        "Interferon alfa-2b 1 mln XB sham №10",
        "interferon alfa-2b",
        "suppository",
        "1 mln XB",
        2,
        "blister",
        "medicine",
        "cold",
        "kohna",
        64000,
        "rx cold",
    ),
    "morph": (
        "Morfin 10 mg/ml in’eksiya eritmasi 1 ml №10",
        "morphine",
        "injection",
        "10 mg/ml",
        10,
        "ampula",
        "medicine",
        "nervous",
        "chorvoq",
        48000,
        "rx narcotic",
    ),
    "diaz": (
        "Diazepam 5 mg/ml in’eksiya eritmasi 2 ml №10",
        "diazepam",
        "injection",
        "5 mg/ml",
        10,
        "ampula",
        "medicine",
        "nervous",
        "baltavia",
        21000,
        "rx psycho",
    ),
    "tram": (
        "Tramadol 50 mg kapsula №20",
        "tramadol",
        "capsule",
        "50 mg",
        2,
        "blister",
        "medicine",
        "nervous",
        "sindhura",
        17500,
        "rx psycho",
    ),
    "phenob": (
        "Fenobarbital 100 mg tabletka №10",
        "phenobarbital",
        "tablet",
        "100 mg",
        1,
        "",
        "medicine",
        "nervous",
        "chorvoq",
        6200,
        "rx psycho",
    ),
    "pregab": (
        "Pregabalin 75 mg kapsula №14",
        "pregabalin",
        "capsule",
        "75 mg",
        2,
        "blister",
        "medicine",
        "nervous",
        "anadolin",
        39000,
        "rx strong star",
    ),
    "gabap": (
        "Gabapentin 300 mg kapsula №50",
        "gabapentin",
        "capsule",
        "300 mg",
        5,
        "blister",
        "medicine",
        "nervous",
        "sindhura",
        54000,
        "rx strong star",
    ),
    "para": (
        "Paratsetamol 500 mg tabletka №20",
        "paracetamol",
        "tablet",
        "500 mg",
        2,
        "blister",
        "medicine",
        "pain",
        "zarafshon",
        3200,
        "must",
    ),
    "para2": (
        "Paratsetamol-Chorvoq 500 mg tabletka №10",
        "paracetamol",
        "tablet",
        "500 mg",
        1,
        "",
        "medicine",
        "pain",
        "chorvoq",
        1900,
        "",
    ),
    "parasyr": (
        "Paratsetamol 120 mg/5 ml sirop 100 ml",
        "paracetamol",
        "syrup",
        "120 mg/5 ml",
        1,
        "",
        "medicine",
        "pain",
        "kohna",
        9600,
        "must",
    ),
    "ibu": (
        "Ibuprofen 400 mg tabletka №20",
        "ibuprofen",
        "tablet",
        "400 mg",
        2,
        "blister",
        "medicine",
        "pain",
        "zarafshon",
        7800,
        "must",
    ),
    "ibusus": (
        "Ibuprofen 100 mg/5 ml suspenziya 100 ml",
        "ibuprofen",
        "suspension",
        "100 mg/5 ml",
        1,
        "",
        "medicine",
        "pain",
        "anadolin",
        14900,
        "",
    ),
    "asa": (
        "Atsetilsalitsil kislotasi 500 mg tabletka №10",
        "acetylsalicylic acid",
        "tablet",
        "500 mg",
        1,
        "",
        "medicine",
        "pain",
        "chorvoq",
        2100,
        "must",
    ),
    "drot": (
        "Drotaverin 40 mg tabletka №20",
        "drotaverine",
        "tablet",
        "40 mg",
        2,
        "blister",
        "medicine",
        "stomach",
        "zarafshon",
        5400,
        "must",
    ),
    "nime": (
        "Nimesulid 100 mg tabletka №20",
        "nimesulide",
        "tablet",
        "100 mg",
        2,
        "blister",
        "medicine",
        "pain",
        "sindhura",
        9200,
        "",
    ),
    "dicgel": (
        "Diklofenak 1 % gel 40 g",
        "diclofenac",
        "gel",
        "1 %",
        1,
        "",
        "medicine",
        "pain",
        "kohna",
        14500,
        "must",
    ),
    "dicamp": (
        "Diklofenak 75 mg/3 ml in’eksiya eritmasi №5",
        "diclofenac",
        "injection",
        "75 mg/3 ml",
        5,
        "ampula",
        "medicine",
        "pain",
        "chorvoq",
        8600,
        "rx",
    ),
    "ketor": (
        "Ketorolak 30 mg/ml in’eksiya eritmasi 1 ml №10",
        "ketorolac",
        "injection",
        "30 mg/ml",
        10,
        "ampula",
        "medicine",
        "pain",
        "baltavia",
        12400,
        "rx",
    ),
    "lorat": (
        "Loratadin 10 mg tabletka №10",
        "loratadine",
        "tablet",
        "10 mg",
        1,
        "",
        "medicine",
        "allergy",
        "zarafshon",
        4900,
        "must",
    ),
    "cetir": (
        "Setirizin 10 mg tabletka №10",
        "cetirizine",
        "tablet",
        "10 mg",
        1,
        "",
        "medicine",
        "allergy",
        "sindhura",
        5600,
        "",
    ),
    "omep": (
        "Omeprazol 20 mg kapsula №30",
        "omeprazole",
        "capsule",
        "20 mg",
        3,
        "blister",
        "medicine",
        "stomach",
        "sindhura",
        8700,
        "must",
    ),
    "lope": (
        "Loperamid 2 mg kapsula №20",
        "loperamide",
        "capsule",
        "2 mg",
        2,
        "blister",
        "medicine",
        "stomach",
        "chorvoq",
        3900,
        "must",
    ),
    "carbo": (
        "Faollashtirilgan ko‘mir 250 mg tabletka №10",
        "activated charcoal",
        "tablet",
        "250 mg",
        1,
        "",
        "medicine",
        "stomach",
        "zarafshon",
        1500,
        "must",
    ),
    "ors": (
        "Og‘iz orqali regidratatsiya tuzlari kukun №10",
        "oral rehydration salts",
        "powder",
        "18,9 g",
        10,
        "paket",
        "medicine",
        "stomach",
        "kohna",
        9500,
        "must",
    ),
    "mebe": (
        "Mebendazol 100 mg tabletka №6",
        "mebendazole",
        "tablet",
        "100 mg",
        1,
        "",
        "medicine",
        "stomach",
        "chorvoq",
        8200,
        "",
    ),
    "ambro": (
        "Ambroksol 30 mg tabletka №20",
        "ambroxol",
        "tablet",
        "30 mg",
        2,
        "blister",
        "medicine",
        "cold",
        "zarafshon",
        4800,
        "must",
    ),
    "ambsyr": (
        "Ambroksol 15 mg/5 ml sirop 100 ml",
        "ambroxol",
        "syrup",
        "15 mg/5 ml",
        1,
        "",
        "medicine",
        "cold",
        "kohna",
        11200,
        "",
    ),
    "xylo": (
        "Ksilometazolin 0,1 % burun spreyi 10 ml",
        "xylometazoline",
        "nasal",
        "0.1 %",
        1,
        "",
        "medicine",
        "cold",
        "baltavia",
        12800,
        "must",
    ),
    "nacl": (
        "Natriy xlorid 0,9 % infuziya eritmasi 200 ml",
        "sodium chloride",
        "solution",
        "0.9 %",
        1,
        "",
        "medicine",
        "cold",
        "zarafshon",
        6900,
        "must",
    ),
    "clotr": (
        "Klotrimazol 1 % krem 20 g",
        "clotrimazole",
        "cream",
        "1 %",
        1,
        "",
        "medicine",
        "allergy",
        "chorvoq",
        9900,
        "",
    ),
    "chlor": (
        "Xloramfenikol + metiluratsil malham 40 g",
        "chloramphenicol+methyluracil",
        "ointment",
        "7,5/40 mg/g",
        1,
        "",
        "medicine",
        "antibiotics",
        "kohna",
        11900,
        "must",
    ),
    "sulfac": (
        "Sulfatsetamid 20 % ko‘z tomchisi 10 ml",
        "sulfacetamide",
        "eye_drops",
        "20 %",
        1,
        "",
        "medicine",
        "antibiotics",
        "chorvoq",
        6800,
        "",
    ),
    "valer": (
        "Valeriana ildizi ekstrakti 20 mg tabletka №50",
        "valerian",
        "tablet",
        "20 mg",
        5,
        "blister",
        "medicine",
        "nervous",
        "zarafshon",
        7400,
        "",
    ),
    "iron": (
        "Temir (III) gidroksid polimaltozat 100 mg chaynaladigan tabletka №30",
        "iron(iii) hydroxide polymaltose",
        "tablet",
        "100 mg",
        3,
        "blister",
        "medicine",
        "vitamins",
        "helvetor",
        46000,
        "social must",
    ),
    "folic": (
        "Foliy kislotasi 1 mg tabletka №50",
        "folic acid",
        "tablet",
        "1 mg",
        5,
        "blister",
        "medicine",
        "vitamins",
        "chorvoq",
        6500,
        "social",
    ),
    "gluc": (
        "Glyukoza 40 % in’eksiya eritmasi 10 ml №10",
        "glucose",
        "injection",
        "40 %",
        10,
        "ampula",
        "medicine",
        "hormones",
        "zarafshon",
        9800,
        "rx",
    ),
    "vitc": (
        "Askorbin kislotasi 500 mg chaynaladigan tabletka №30",
        "ascorbic acid",
        "tablet",
        "500 mg",
        1,
        "",
        "supplement",
        "vitamins",
        "bahor",
        12500,
        "",
    ),
    "vitd": (
        "Vitamin D3 2000 XB kapsula №60",
        "colecalciferol",
        "capsule",
        "2000 XB",
        1,
        "",
        "supplement",
        "vitamins",
        "bahor",
        58000,
        "",
    ),
    "multi": (
        "Multivitamin kompleks tabletka №30",
        "",
        "tablet",
        "",
        1,
        "",
        "supplement",
        "vitamins",
        "baltavia",
        89000,
        "",
    ),
    "magb6": (
        "Magniy B6 tabletka №50",
        "magnesium+pyridoxine",
        "tablet",
        "",
        5,
        "blister",
        "supplement",
        "vitamins",
        "bahor",
        64000,
        "",
    ),
    "omega": (
        "Omega-3 1000 mg kapsula №60",
        "",
        "capsule",
        "1000 mg",
        1,
        "",
        "supplement",
        "vitamins",
        "bahor",
        120000,
        "",
    ),
    "syringe": (
        "Shprits 5 ml 3 komponentli igna bilan",
        "",
        "",
        "5 ml",
        1,
        "",
        "device",
        "devices",
        "turon",
        900,
        "",
    ),
    "mask": (
        "Tibbiy niqob 3 qavatli №50",
        "",
        "",
        "",
        50,
        "dona",
        "device",
        "devices",
        "turon",
        24000,
        "",
    ),
    "bandage": (
        "Steril bint 7 m x 14 sm",
        "",
        "",
        "",
        1,
        "",
        "device",
        "devices",
        "turon",
        4200,
        "",
    ),
    "thermo": ("Raqamli termometr", "", "", "", 1, "", "device", "devices", "turon", 45000, ""),
    "strips": (
        "Glyukometr test-chiziqlari №50",
        "",
        "",
        "",
        1,
        "",
        "device",
        "devices",
        "helvetor",
        165000,
        "",
    ),
    "plaster": (
        "Leykoplastir 2,5 sm x 5 m",
        "",
        "",
        "",
        1,
        "",
        "device",
        "devices",
        "turon",
        5600,
        "",
    ),
    "diapers": (
        "Bolalar tagligi 4-o‘lcham №44",
        "",
        "",
        "",
        1,
        "",
        "cosmetic",
        "hygiene",
        "bahor",
        135000,
        "",
    ),
    "handgel": (
        "Antiseptik qo‘l geli 250 ml",
        "",
        "gel",
        "",
        1,
        "",
        "cosmetic",
        "hygiene",
        "bahor",
        19000,
        "",
    ),
    "babycream": (
        "Bolalar kremi 50 ml",
        "",
        "cream",
        "",
        1,
        "",
        "cosmetic",
        "hygiene",
        "bahor",
        22000,
        "",
    ),
}
CONTROLLED = {"narcotic": "narcotic", "psycho": "psychotropic", "strong": "strong"}
YUNUSOBOD_ONLY = {"morph", "diaz", "tram", "phenob", "pregab", "gabap"}
MISSING_AT_CHILONZOR = "nacl"  # a mandatory medicine Chilonzor ran out of
# Batches that make the expiry board (days from today): expired, within 30, within 31-90.
EXPIRED = (("C", "asa", -5, 12), ("C", "sulfac", -12, 9), ("Y", "lope", -3, 6))
WITHIN_30 = (
    ("C", "parasyr", 9, 6),
    ("C", "ambsyr", 14, 4),
    ("C", "xylo", 21, 5),
    ("Y", "ibusus", 6, 4),
    ("Y", "cetir", 17, 8),
    ("Y", "mebe", 24, 5),
    ("C", "vitc", 27, 10),
    ("Y", "dicgel", 29, 6),
)
WITHIN_90 = (
    ("C", "nime", 35, 10),
    ("C", "clotr", 41, 6),
    ("C", "drot", 48, 20),
    ("C", "omep", 55, 9),
    ("C", "valer", 63, 8),
    ("C", "multi", 72, 3),
    ("Y", "lorat", 38, 12),
    ("Y", "ambro", 46, 16),
    ("Y", "carbo", 52, 30),
    ("Y", "chlor", 66, 6),
    ("Y", "warf", 79, 4),
    ("Y", "magb6", 88, 5),
)
DISTRIBUTORS = {
    "kokterak": ("Ko‘kterak Farm Distribyutor", 30, True, "+998712004411"),
    "oqtosh": ("Oqtosh Med Ta’minot", 45, True, "+998712004455"),
    "tolzor": ("Tolzor Farm Savdo", 14, False, "+998712004477"),
    "chinorbek": ("Chinorbek Pharma Logistika", None, True, "+998712004499"),
}
COMMISSION = (
    ("Bekzod Mirzayev", "Demo Dorixona", "Dorixona mudiri, rais"),
    ("Madina Saidova", "Demo Dorixona", "Provizor"),
    ("Dilshod Rahimov", "Tuman ekologiya bo‘limi", "Bosh mutaxassis"),
    ("Gulnora Ismoilova", "Tuman sanitariya-epidemiologiya xizmati", "Vrach-gigiyenist"),
    ("Sardor Qosimov", "Farmatsevtika xavfsizligi markazi", "Inspektor"),
)
REQUESTS = (
    ("C", "glarg", None, 2, 13),
    ("C", None, "Insulin detemir 100 TB/ml", 1, 12),
    ("C", "amoxclav", None, 1, 11),
    ("Y", None, "Melatonin 3 mg tabletka", 2, 10),
    ("C", "vitd", None, 1, 9),
    ("Y", None, "Rozuvastatin 10 mg tabletka", 1, 9),
    ("C", None, "Bolalar uchun Ibuprofen sham", 3, 8),
    ("Y", "aspart", None, 1, 7),
    ("C", "strips", None, 2, 6),
    ("Y", None, "Ko‘z uchun sun’iy yosh tomchisi", 1, 5),
    ("C", None, "Ortopedik bilak bog‘ichi", 1, 4),
    ("Y", "omega", None, 2, 3),
    ("C", None, "Pantoprazol 40 mg tabletka", 1, 2),
    ("Y", None, "Vitamin B12 in’eksiya", 1, 1),
    ("C", "babycream", None, 2, 1),
)


def _photo() -> ContentFile:
    """A plain JPEG standing in for the destruction photo."""
    from PIL import Image

    data = io.BytesIO()
    Image.new("RGB", (640, 480), (196, 186, 170)).save(data, "JPEG", quality=70)
    return ContentFile(data.getvalue(), name="photo.jpg")


class Story:
    def __init__(self, company, people, now):
        self.company = company
        self.people = people
        self.now = now
        self.plan = demo_plan.Plan(company, people, now)
        self.today = self.plan.today
        self.owner = people["owner"]
        self.head = people["manager"]
        self.worker = people.get("worker", self.head)
        self.madina = people.get("madina", self.worker)
        self.nigora = people.get("nigora", self.worker)
        branches = self.plan.branches
        self.chl = branches.get("C") or next(iter(branches.values()))
        self.yns = branches.get("Y") or self.chl
        self.two = self.chl.pk != self.yns.pk
        self.products: dict[str, Product] = {}
        self.suppliers = {}
        self.invoice = 4100

    def at(self, offset: int, hour: int = 10, minute: int = 0) -> datetime:
        return self.plan.at(self.plan.day(offset), time(hour, minute))

    def branch(self, code: str):
        return self.chl if code == "C" or not self.two else self.yns

    # The catalogue and the distributors -------------------------------------------------------

    def catalogue(self) -> None:
        company = self.company
        categories = defaults.categories(company)
        makers = {}
        for key, (name, country) in MAKERS.items():
            makers[key], _made = Manufacturer.objects.get_or_create(
                company=company, name=name, defaults={"country": country}
            )
        with moment(self.at(-60, 9)):
            for index, (key, row) in enumerate(CATALOGUE.items()):
                name, inn, form, strength, parts, label, kind, group, maker, cost, flags = row
                flags = set(flags.split())
                control = next((CONTROLLED[flag] for flag in flags if flag in CONTROLLED), "none")
                self.products[key] = services.create_product(
                    company,
                    by=self.owner,
                    name=name,
                    inn=inn,
                    kind=kind,
                    dosage_form=form,
                    strength=strength,
                    units_per_pack=parts,
                    part_label=label,
                    manufacturer=makers[maker],
                    category=categories[group],
                    rx_required="rx" in flags,
                    e_rx_group="erx" in flags,
                    control_class=control,
                    restricted_channel="star" in flags,
                    storage="cold" if "cold" in flags else "room",
                    socially_significant="social" in flags,
                    mandatory_list="must" in flags,
                    barcode=f"4780{1000000 + index * 37:08d}"[:13],
                    sale_price=D(cost) * D("1.25"),
                    registration_number=f"DV/X {2021 + index % 5}/{1200 + index}",
                    registration_until=self.today + timedelta(days=400 + index * 9),
                )
        # The registry's ceiling for two prescription medicines (typed from its spreadsheet).
        for key, ceiling in (("amox", "21500"), ("atorva", "36000")):
            services.update_product(
                self.products[key],
                by=self.owner,
                reference_price=D(ceiling),
                reference_price_on=self.plan.day(-30),
            )

    def distributors(self) -> None:
        from apps.finance.models import Counterparty

        for key, (name, terms, dealer, phone) in DISTRIBUTORS.items():
            party = Counterparty.objects.filter(company=self.company, name=name).first()
            if party is None:
                party = Counterparty.objects.create(
                    company=self.company, name=name, kind=Counterparty.Kind.SUPPLIER, phone=phone
                )
            services.save_supplier(
                party,
                by=self.owner,
                payment_terms_days=terms,
                official_dealer=dealer,
                delivery_days=1,
                order_channel=SupplierProfile.Channel.TELEGRAM,
                telegram_username=f"{key}_savdo",
            )
            self.suppliers[key] = party

    # Opening stock ----------------------------------------------------------------------------

    def opening(self) -> None:
        """Eight weeks ago: what was on the shelves, by series, with the expiry spread."""
        special = {(code, key): days for code, key, days, _qty in EXPIRED + WITHIN_30 + WITHIN_90}
        quantities = {(code, key): qty for code, key, _days, qty in EXPIRED + WITHIN_30 + WITHIN_90}
        with moment(self.at(-56, 9, 30)):
            for index, (key, product) in enumerate(self.products.items()):
                for code in ("C", "Y") if self.two else ("C",):
                    branch = self.branch(code)
                    if code == "C" and key in YUNUSOBOD_ONLY:
                        continue
                    if not services.is_licensed_for(branch, product):
                        continue
                    if code == "C" and key == MISSING_AT_CHILONZOR and self.two:
                        continue
                    cost = D(CATALOGUE[key][9])
                    days = special.get((code, key))
                    if days is not None:
                        services.add_opening_stock(
                            branch,
                            by=self.owner,
                            product=product,
                            series=f"{key[:3].upper()}{2400 + index}{code}",
                            expires_on=self.today + timedelta(days=days),
                            quantity=D(quantities[(code, key)]) * product.units_per_pack,
                            unit_cost=cost,
                        )
                    months = 6 + (index * 7 + (3 if code == "Y" else 0)) % 30
                    packs = 4 + (index * 5 + (2 if code == "Y" else 0)) % 14
                    services.add_opening_stock(
                        branch,
                        by=self.owner,
                        product=product,
                        series=f"{key[:3].upper()}{2500 + index}{code}",
                        expires_on=self.today + timedelta(days=30 * months + index % 17),
                        quantity=D(packs) * product.units_per_pack,
                        unit_cost=cost,
                    )
        # Minimums for a few fast movers, two of them below it now.
        for key, minimum in (("para", 40), ("ibu", 30), ("lorat", 12), ("omep", 18)):
            product = self.products[key]
            services.set_level_limits(self.chl, product, by=self.head, min_qty=D(minimum))

    # Deliveries ---------------------------------------------------------------------------------

    def receipt(self, offset, code, supplier, lines, *, post=True, submit=True, by=None):
        branch = self.branch(code)
        when = self.at(offset, 11 if code == "C" else 15)
        self.invoice += 7
        by = by or (self.head if code == "C" else self.nigora)
        with moment(when):
            receipt = services.create_receipt(
                self.company,
                by=by,
                branch=branch,
                supplier=self.suppliers[supplier],
                supplier_invoice_number=f"{supplier[:2].upper()}-{self.invoice}",
                supplier_invoice_date=self.plan.day(offset),
                lines=[
                    {
                        "product": self.products[key],
                        "series": series,
                        "expires_on": self.today + timedelta(days=days),
                        "packs": D(packs),
                        "unit_cost": D(cost if cost is not None else CATALOGUE[key][9]),
                    }
                    for key, series, days, packs, cost in lines
                ],
            )
            if submit:
                services.submit_receipt(receipt, by=by)
        if post:
            with moment(when + timedelta(hours=2)):
                receipt = services.post_receipt(
                    receipt, by=self.head if code == "C" else self.owner
                )
        return receipt

    def deliveries(self) -> None:
        rows = (
            (
                -41,
                "C",
                "kokterak",
                [
                    ("amox", "AMX2309", 420, 10, None),
                    ("para", "PRC2311", 610, 30, None),
                    ("ibu", "IBU2310", 540, 20, None),
                ],
            ),
            (
                -39,
                "Y",
                "oqtosh",
                [
                    ("cefix", "SFX2308", 380, 6, None),
                    ("pred", "PRD2305", 700, 4, None),
                    ("glarg", "GLR2310", 300, 3, None),
                ],
            ),
            (
                -34,
                "C",
                "tolzor",
                [
                    ("vitd", "VTD2307", 500, 6, None),
                    ("handgel", "HGL2309", 720, 10, None),
                    ("mask", "MSK2311", 900, 8, None),
                ],
            ),
            (
                -32,
                "Y",
                "kokterak",
                [
                    ("tram", "TRM2306", 640, 6, None),
                    ("diaz", "DZP2304", 590, 3, None),
                    ("morph", "MRF2305", 610, 2, None),
                ],
            ),
            (
                -27,
                "C",
                "oqtosh",
                [("atorva", "ATR2312", 660, 8, None), ("amlo", "AML2308", 590, 12, None)],
            ),
            (
                -25,
                "Y",
                "chinorbek",
                [("metf", "MTF2309", 520, 10, None), ("aspart", "ASP2311", 280, 2, None)],
            ),
            # A cost jump: Oqtosh raised the price of azithromycin by 15 %.
            (
                -20,
                "C",
                "oqtosh",
                [("azit", "AZT2402", 610, 10, 27600), ("cipro", "CPR2403", 560, 10, None)],
            ),
            # A short shelf life: Tolzor brought syrup that expires in four months.
            (
                -18,
                "Y",
                "tolzor",
                [("ambsyr", "AMS2306", 120, 12, None), ("parasyr", "PSR2311", 480, 10, None)],
            ),
            (
                -13,
                "C",
                "kokterak",
                [("lorat", "LRT2310", 450, 10, None), ("omep", "OMP2309", 520, 6, None)],
            ),
            (
                -11,
                "Y",
                "kokterak",
                [("phenob", "PHB2307", 700, 5, None), ("pregab", "PGB2309", 520, 4, None)],
            ),
            (
                -6,
                "C",
                "tolzor",
                [("strips", "TST2312", 400, 3, None), ("thermo", "TRM2401", 1100, 4, None)],
            ),
        )
        for offset, code, supplier, lines in rows:
            branch = self.branch(code)
            if not all(services.is_licensed_for(branch, self.products[row[0]]) for row in lines):
                continue
            self.receipt(offset, code, supplier, lines)
        # Waiting for posting since this morning: the pharmacist entered it from the nakladnoy.
        self.receipt(
            0,
            "C",
            "kokterak",
            [("drot", "DRT2412", 640, 20, None), ("ambro", "AMB2411", 600, 12, None)],
            post=False,
            by=self.worker,
        )

    # Transfers, write-offs, counts, recalls -----------------------------------------------------

    def transfers(self) -> None:
        if not self.two:
            return

        def send(offset, source, target, key, parts, *, short=None, receive=True):
            product = self.products[key]
            with moment(self.at(offset, 12)):
                transfer = services.create_transfer(
                    self.company,
                    by=self.head,
                    from_branch=source,
                    to_branch=target,
                    lines=[{"product": product, "quantity": D(parts)}],
                    note="Yunusobodda tugab qoldi" if target == self.yns else "",
                )
                services.send_transfer(transfer, by=self.head)
            if receive:
                line = transfer.lines.first()
                received = {line.pk: line.quantity_sent - short} if short else None
                with moment(self.at(offset, 18)):
                    services.receive_transfer(transfer, by=self.nigora, received=received)
            return transfer

        send(-30, self.chl, self.yns, "ibu", 10)
        send(-16, self.yns, self.chl, "biso", 3)
        send(-9, self.chl, self.yns, "para", 8, short=2)  # arrived two blisters short
        send(-1, self.chl, self.yns, "drot", 6, receive=False)  # on the way

    def writeoffs(self) -> None:
        company = self.company
        # Destroyed: expired goods approved four weeks ago, destroyed by a full commission.
        old = services.add_opening_stock
        with moment(self.at(-58, 9)):
            batch = old(
                self.chl,
                by=self.owner,
                product=self.products["valer"],
                series="VLR2209C",
                expires_on=self.plan.day(-35),
                quantity=D(30),
                unit_cost=D(7400),
            )
        with moment(self.at(-30, 16)):
            writeoff = services.propose_writeoff(
                company,
                by=self.madina,
                branch=self.chl,
                reason="expired",
                lines=[{"batch": batch, "quantity": D(30)}],
                note="Muddati o‘tgan, sotuvdan olingan",
            )
        with moment(self.at(-29, 10)):
            services.approve_writeoff(writeoff, by=self.head)
            services.add_writeoff_file(writeoff, by=self.head, upload=_photo(), kind="photo")
        with moment(self.at(-8, 15)):
            services.mark_destroyed(
                writeoff,
                by=self.head,
                method="incinerate",
                place="Sergeli tumani, chiqindilarni yoqish maydoni",
                destroyed_at=self.at(-8, 11),
                responsible="Bekzod Mirzayev",
                order_number="17-B",
                commission=[
                    {"name": name, "organisation": org, "role": role}
                    for name, org, role in COMMISSION
                ],
                sent_to=["Tuman ekologiya bo‘limi", "Tuman sanitariya-epidemiologiya xizmati"],
            )
        # Approved 18 days ago: 12 days left to destroy it.
        with moment(self.at(-25, 9)):
            damaged = old(
                self.yns,
                by=self.owner,
                product=self.products["dicamp"],
                series="DCA2311Y",
                expires_on=self.today + timedelta(days=300),
                quantity=D(10),
                unit_cost=D(8600),
            )
        with moment(self.at(-19, 20)):
            waiting = services.propose_writeoff(
                company,
                by=self.nigora,
                branch=self.yns,
                reason="damaged",
                lines=[{"batch": damaged, "quantity": D(5)}],
                note="Quti shikastlangan, ampulalar singan",
                files=[(_photo(), "photo")],
            )
        with moment(self.at(-18, 10)):
            services.approve_writeoff(waiting, by=self.owner)
        # Proposed yesterday: one of the expired batches still on the shelf.
        expired = BatchStock.objects.filter(
            branch=self.chl, batch__product=self.products["asa"], batch__expires_on__lt=self.today
        ).first()
        if expired is not None:
            with moment(self.at(-1, 19)):
                services.propose_writeoff(
                    company,
                    by=self.worker,
                    branch=self.chl,
                    reason="expired",
                    lines=[{"batch": expired.batch, "quantity": expired.quantity}],
                    note="Javondan olindi, karantin zonasida",
                )

    def counts(self) -> None:
        # Applied three weeks ago at Chilonzor: about 120 000 so‘m short (at cost).
        with moment(self.at(-21, 20)):
            count = services.start_count(self.chl, by=self.head, kind="partial", category=None)
        lines = list(count.lines.select_related("batch__product").order_by("order"))
        target = D(120000)
        short = D(0)
        counted = {}
        for line in lines:
            part_cost = engine.part_cost(line.batch)
            if short < target and line.expected >= 2 and 0 < part_cost <= target - short:
                take = max(min(line.expected - 1, (target - short) // part_cost), 1)
                counted[line.pk] = line.expected - take
                short += take * part_cost
            else:
                counted[line.pk] = line.expected
        with moment(self.at(-21, 21)):
            services.record_counted(count, by=self.worker, counted=counted)
            services.submit_count(count, by=self.worker)
        with moment(self.at(-20, 10)):
            services.apply_count(count, by=self.head)
        if self.two:
            # Applied two weeks ago at Yunusobod: one blister more than the books said.
            with moment(self.at(-14, 21)):
                small = services.start_count(
                    self.yns,
                    by=self.owner,
                    kind="partial",
                    category=defaults.categories(self.company)["vitamins"],
                )
            first = small.lines.first()
            if first is not None:
                with moment(self.at(-14, 22)):
                    services.record_counted(
                        small, by=self.nigora, counted={first.pk: first.expected + 1}
                    )
                    services.submit_count(small, by=self.nigora)
                with moment(self.at(-13, 9)):
                    services.apply_count(small, by=self.owner)
        # Open: Yunusobod's full count, started this morning.
        with moment(self.at(0, 8, 15)):
            services.start_count(self.yns if self.two else self.chl, by=self.owner, kind="full")

    def recall(self) -> None:
        """A rejected series of paracetamol tablets, found in both pharmacies."""
        product = self.products["para"]
        series = "PRC2209"
        with moment(self.at(-50, 10)):
            for branch, packs in ((self.chl, 6), (self.yns, 4)):
                services.add_opening_stock(
                    branch,
                    by=self.owner,
                    product=product,
                    series=series,
                    expires_on=self.today + timedelta(days=210),
                    quantity=D(packs) * product.units_per_pack,
                    unit_cost=D(3200),
                    supplier=self.suppliers["tolzor"],
                )
        with moment(self.at(-2, 11)):
            services.register_recall(
                self.company,
                by=self.owner,
                series=series,
                reason="Tarkibi bo‘yicha sifat talablariga mos emas",
                source="Farmatsevtika xavfsizligi markazi, yaroqsiz seriyalar ro‘yxati №41",
                received_on=self.plan.day(-2),
                inn_or_name="paracetamol",
            )

    def defektura(self) -> None:
        for code, key, name, packs, days_ago in REQUESTS:
            branch = self.branch(code)
            when = self.at(-days_ago, 13)
            with moment(when):
                row = services.add_request(
                    branch,
                    by=self.worker if branch == self.chl else self.nigora,
                    product=self.products[key] if key else None,
                    name=name or "",
                    packs=packs,
                )
            status = MissingRequest.Status.FULFILLED if days_ago > 9 else MissingRequest.Status.OPEN
            if days_ago in (5, 6):
                status = MissingRequest.Status.ORDERED
            MissingRequest.objects.filter(pk=row.pk).update(requested_at=when, status=status)

    def controlled(self) -> None:
        """Last month at Yunusobod: dispensed by prescription, written in the log, closed on
        the 2nd with the count matching the register."""
        if not self.two:
            return
        last = register.previous_month(self.today)
        zone = engine.zone_of(self.company)
        dispensed = (
            ("tram", 2, 3),
            ("tram", 1, 9),
            ("diaz", 1, 12),
            ("phenob", 1, 17),
            ("morph", 1, 22),
        )
        for number, (key, parts, day) in enumerate(dispensed, start=1):
            moment_at = datetime.combine(last + timedelta(days=day - 1), time(21, 30), tzinfo=zone)
            if moment_at.date() >= self.today:
                continue
            product = self.products[key]
            # From the stock that was on the shelf then: the opening batch.
            stock = (
                BatchStock.objects.filter(
                    branch=self.yns,
                    batch__product=product,
                    batch__receipt_line__isnull=True,
                    quantity__gte=parts,
                )
                .select_related("batch")
                .order_by("batch__expires_on")
                .first()
            )
            if stock is None:
                continue
            with moment(moment_at):
                kind = "narcotic" if key == "morph" else "psychotropic"
                record = services.record_rx(
                    by=self.nigora,
                    branch=self.yns,
                    product=product,
                    quantity=D(parts),
                    prescription_number=f"148-{3300 + number}",
                    prescribed_on=moment_at.date() - timedelta(days=1),
                    prescriber="Shifokor (onkologiya dispanseri)",
                    facility="Yunusobod tuman ko‘p tarmoqli poliklinikasi",
                    rx_kind=kind,
                    recorded_at=moment_at,
                )
                services.deduct(
                    self.yns,
                    product,
                    D(parts),
                    by=self.nigora,
                    document=("inventory.rxrecord", record.pk if record else number),
                    series=stock.batch.series,
                    reason="prescription",
                )
        closing_day = register.month_start(self.today) + timedelta(days=1)
        if closing_day > self.today:
            return
        with moment(datetime.combine(closing_day, time(9, 30), tzinfo=zone)):
            register.close_month(self.yns, last, by=self.nigora, note="Oylik inventarizatsiya")

    def build(self) -> None:
        conf.get_settings(self.company)
        self.catalogue()
        self.distributors()
        self.opening()
        self.deliveries()
        self.transfers()
        self.writeoffs()
        self.counts()
        self.controlled()
        self.recall()
        self.defektura()
        # Typed prices: the head marked down a syrup close to expiry.
        soon = BatchStock.objects.filter(
            branch=self.chl,
            batch__product=self.products["parasyr"],
            batch__expires_on__lte=self.today + timedelta(days=30),
        ).first()
        if soon is not None:
            with moment(self.at(-1, 18)):
                services.set_markdown(soon.batch, by=self.head, price=D(9900))


def seed(company, people, now) -> None:
    """Demo Dorixona's stock: the catalogue, both pharmacies' batches and eight weeks of
    documents."""
    Story(company, people, now).build()


def seed_small(company, people, now) -> None:
    """Demo Distribyutor's warehouse: part of the catalogue in stock at Sergeli."""
    story = Story(company, people, now)
    story.chl = story.yns = company.branches.order_by("order", "pk").first()
    story.two = False
    conf.get_settings(company)
    story.catalogue()
    story.distributors()
    with moment(story.at(-20, 9)):
        for index, (key, product) in enumerate(story.products.items()):
            if key in YUNUSOBOD_ONLY or product.control_class != "none":
                continue
            services.add_opening_stock(
                story.chl,
                by=story.owner,
                product=product,
                series=f"W{key[:3].upper()}{2600 + index}",
                expires_on=story.today + timedelta(days=200 + (index * 13) % 700),
                quantity=D(40 + (index * 11) % 120) * product.units_per_pack,
                unit_cost=D(CATALOGUE[key][9]) * D("0.9"),
            )


def finish(company, people, now) -> None:
    """Once Finance has its accounts: the deliveries' payables that fell due are paid from the
    bank on their due day, except the latest one, still overdue."""
    if company.slug == demo_plan.DISTRIBUTOR or not company.has_feature("finance"):
        return
    from apps.finance import services as finance
    from apps.finance.models import Debt, MoneyAccount

    bank = (
        MoneyAccount.objects.filter(company=company, kind=MoneyAccount.Kind.BANK)
        .order_by("pk")
        .first()
    )
    if bank is None:
        return
    plan = demo_plan.Plan(company, people, now)
    due = list(
        Debt.objects.filter(
            company=company,
            source_type=services.RECEIPT,
            status=Debt.Status.OPEN,
            due_on__lt=plan.today,
        ).order_by("due_on", "pk")
    )
    from apps.core.exceptions import DomainError

    for debt in due[:-1]:
        try:
            with transaction.atomic(), moment(plan.at(debt.due_on, time(11, 0))):
                finance.pay_debt(
                    debt,
                    by=people["owner"],
                    amount=debt.amount - debt.paid,
                    paid_on=debt.due_on,
                    account=bank,
                )
        except DomainError:
            break  # the bank ran dry (a module's own test): the rest stay open
