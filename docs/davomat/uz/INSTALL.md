# Davomatni o‘rnatish

Davomat — Face ID orqali davomatni hisobga oladigan alohida ilova: eshiklar oldida yuzni taniydigan
Hikvision terminallari, brauzerda kelganlarning jonli lentasi (har bir skanerlash surati bilan), ish
grafiklari, kechikishlar, tabellar, hisobotlar va Telegram bot. Bitta server bitta tashkilotga
xizmat qiladi (uning nechta filiali bo‘lsa, hammasi bilan).

Bu qo‘llanma serverni sozlaydigan kishi uchun. Keyin tashkilotni boshqaradigan xodim
[ADMIN.md](ADMIN.md) faylini o‘qiydi; biror muammo chiqsa — [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## 1. Nima kerak

| | |
|---|---|
| Server | Ubuntu 22.04 yoki 24.04, SSH orqali root huquqlari bilan (istalgan VPS yoki ofisdagi kompyuter) |
| Resurslar | 2 vCPU, 4 GB operativ xotira, 40 GB disk (bir necha yuz xodim uchun; suratlar va zaxira nusxalar vaqt o‘tishi bilan ko‘payadi) |
| Portlar | 80 va 443 portlari internetga ochiq (yoki mahalliy tarmoqqa, 7-bo‘limga qarang) |
| Manzil | DNS `A` yozuvi serverga yo‘naltirilgan domen nomi, masalan, `davomat.example.uz`. Domen bo‘lmasa, `<server IP>.nip.io` ham ishlaydi (masalan, `203.0.113.10.nip.io`), haqiqiy HTTPS sertifikati bilan |
| Terminallar | Hikvision yuzni taniydigan terminallari (MinMoe: DS-K1T341AMF, DS-K1T341, DS-K1T342, DS-K1T343, DS-K1T671, DS-K1T804…); ular ulangan tarmoqdan serverga port 80 orqali ulanish mumkin bo‘lishi kerak |
| Telegram | ixtiyoriy: @BotFather orqali yaratilgan bot (ADMIN.md, 7-bo‘lim) |

Docker o‘rnatilmagan bo‘lsa, o‘rnatish skripti uni o‘zi o‘rnatadi. Boshqa hech narsani qo‘lda
o‘rnatish shart emas.

**Bulutli xavfsizlik devorlari.** Ba’zi provayderlarda (AWS, Google Cloud, Hetzner Cloud, Oracle…)
server oldida o‘zining xavfsizlik devori (firewall) bo‘ladi: TCP 80, TCP 443 va UDP 443 portlarini
u yerda ham oching.

## 2. Kodni serverga joylash

Yoki repozitoriyni klonlang:

```bash
git clone <repository URL> /opt/davomat
```

yoki boshqa kompyuterda tayyorlangan relizni serverga ko‘chirib, arxivdan chiqaring:

```bash
# kod turgan kompyuterda: o‘rnatiladigan commit relizi
git archive --format=tar.gz --prefix=davomat/ -o davomat.tar.gz HEAD
scp davomat.tar.gz root@<server>:/root/

# serverda
mkdir -p /opt/davomat
tar -xzf /root/davomat.tar.gz -C /opt/davomat --strip-components=1
```

`/opt/davomat` — faqat tavsiya: istalgan papka bo‘laveradi, quyidagi barcha buyruqlar shu papkadan
bajariladi.

## 3. O‘rnatish skriptini ishga tushirish

Yig‘ish 5–15 daqiqa davom etadi. O‘rnatish skriptini `tmux` (yoki `screen`) ichida ishga tushiring,
shunda SSH ulanishi uzilib qolsa ham skript to‘xtamaydi:

```bash
cd /opt/davomat
tmux new -s davomat          # agar tmux bo‘lmasa: apt-get install tmux
bash deploy/davomat/install.sh
```

Skript ikkita savol beradi:

1. **Davomat qayerda ochiladi**: internetda (sukut bo‘yicha) yoki faqat mahalliy tarmoqda.
2. **Domen nomi**: `<server IP>.nip.io` uchun Enter tugmasini bosing yoki o‘z domeningizni yozing.

Qolganini o‘zi bajaradi:

- serverni tekshiradi (xotira, disk, soat) va Docker bo‘lmasa, uni rasmiy Docker skripti bilan
  o‘rnatadi (oldin so‘raydi);
- sozlamalarni yangi yaratilgan kalitlar bilan `/opt/davomat/.env` fayliga yozadi (kirish
  huquqlari 600);
- xavfsizlik devori yoqilgan bo‘lsa, `ufw` sozlamalarida 80 va 443 portlarini ochadi (oldin
  so‘raydi);
- obrazni yig‘adi, hammasini ishga tushiradi va sayt HTTPS orqali javob berguncha kutadi (Caddy
  sertifikatni Let’s Encrypt xizmatidan o‘zi oladi);
- ochish kerak bo‘lgan manzilni hamda loglar va zaxira nusxalar qayerda ekanini chiqaradi.

```
==> Davomat is running
    Open https://203.0.113.10.nip.io/ in a browser to set up your organization.
    Face ID terminals post to 203.0.113.10 over HTTP, port 80: Face ID › Add a terminal shows the exact values.
```

O‘rnatish skriptini qayta ishga tushirish xavfsiz: u mavjud `.env` faylini saqlab qoladi (uning
ustidan hech qachon yozmaydi) va faqat ishlamayotgan qismlarni ishga tushiradi. Uning logi:
`/var/log/davomat/install-<date>.log`.

### Savollarsiz

```bash
bash deploy/davomat/install.sh --yes --domain davomat.example.uz
```

tashkilotni brauzerda emas, shu zahoti yaratish uchun esa:

```bash
bash deploy/davomat/install.sh --yes --domain davomat.example.uz \
  --organization "Namuna MChJ" --admin-username admin --admin-password '<a strong password>' \
  --timezone Asia/Tashkent --language uz
```

| Parametr | Vazifasi |
|---|---|
| `--domain NAME` | sayt nomi (sukut bo‘yicha: `<public IP>.nip.io`) |
| `--lan [ADDRESS]` | faqat mahalliy tarmoqdan kiriladigan server (7-bo‘lim) |
| `--http-only` | oddiy HTTP; kompyuterning o‘zida `http://localhost` manzilida sinab ko‘rish uchun |
| `--device-host HOST` | terminallar ma’lumot yuboradigan manzil (sukut bo‘yicha: serverning tashqi IP manzili) |
| `--http-port N`, `--https-port N` | 80 va 443 o‘rniga boshqa portlar (terminallar va sertifikatlar uchun port 80 kerak) |
| `--organization`, `--admin-username`, `--admin-password`, `--admin-first-name`, `--admin-last-name`, `--timezone`, `--language` | tashkilotni hoziroq yaratish (`manage.py davomat_init`) |
| `--image FILE` | obrazni yig‘ish o‘rniga tayyor obrazdan foydalanish (8-bo‘lim) |
| `--no-start` | `.env` faylini yozib, to‘xtash |
| `-y`, `--yes` | savollarsiz: sukut bo‘yicha qiymatlar, Docker bo‘lmasa o‘rnatiladi |

## 4. Birinchi ishga tushirish

Manzilni brauzerda oching. Yangi o‘rnatilgan Davomat **sozlash sahifasini** ochadi:

1. **Tashkilot**: nomi (kirish sahifasida, hisobotlarda va Telegramda ko‘rinadi), vaqt mintaqasi
   (kelish va kechikishlar shu vaqt bo‘yicha hisoblanadi) va til.
2. **Hisobingiz**: administratorning ismi, logini va paroli (kamida 8 belgi, oddiy so‘z emas va
   faqat raqamlardan iborat emas).
3. **Tayyor**: siz tizimga kirgan bo‘lasiz. Birinchi terminalni qo‘shing (ADMIN.md, 4-bo‘lim).

Sozlash sahifasi faqat bir marta ishlaydi: keyin bu manzil kirish sahifasini ochadi. **O‘rnatish
skripti sozlash kodini chiqargan bo‘lsa**, sahifa uni so‘raydi: Davomatni faqat skript natijasini
ko‘rgan kishi sozlay oladi. Kod bo‘lmasa, **buni o‘rnatish skripti tugashi bilanoq bajaring**:
shungacha manzilni birinchi bo‘lib ochgan kishi tashkilotning egasi bo‘lib qoladi. Bunday daqiqa umuman bo‘lmasligi uchun tashkilotni o‘rnatish
skriptining `--organization` parametrlari bilan yarating (3-bo‘lim).

## 5. Nimalar ishlaydi

Hammasi Docker Compose ichida ishlaydi (`docker-compose.davomat.yml`, `davomat` loyihasi):

| Xizmat | Vazifasi |
|---|---|
| `caddy` | HTTPS va uning sertifikati; terminallar uchun oddiy HTTP; logotiplar va xodimlar suratlari |
| `backend` | Davomatning o‘zi (Django va gunicorn): veb-ilova, API, terminallardan keladigan hodisalar. Ishga tushganda ma’lumotlar bazasi migratsiyalarini qo‘llaydi |
| `worker` | fon vazifalari: Telegram xabarlari, eksport, hisobotlar |
| `beat` | jadval bo‘yicha ishlar: kun yakuni, kechikishlar, tozalash |
| `bot` | tashkilotning Telegram boti (Sozlamalar › Telegram bo‘limida token kiritilguncha kutib turadi) |
| `db`, `redis` | PostgreSQL 18 va Redis |
| `backup` | har kecha zaxira nusxa olish (6-bo‘lim) |

Nima qayerda:

| | |
|---|---|
| Sozlamalar | `/opt/davomat/.env` (kirish huquqlari 600). **Nusxasini xavfsiz joyda saqlang**: undagi kalitlarni qaytadan yaratib bo‘lmaydi |
| Zaxira nusxalar | `/opt/davomat/backups/` |
| O‘rnatish va yangilash loglari | `/var/log/davomat/` |
| Ma’lumotlar | Docker volume: `davomat_pgdata` (ma’lumotlar bazasi), `davomat_media` (logotiplar, xodimlar suratlari), `davomat_private_media` (skanerlash suratlari, eksportlar), `davomat_caddy_data` (sertifikatlar) |

Kundalik buyruqlar (`/opt/davomat` papkasidan):

```bash
bash deploy/davomat/status.sh                     # umumiy holat (faqat o‘qiydi)
docker compose -f docker-compose.davomat.yml ps   # xizmatlar
docker compose -f docker-compose.davomat.yml logs -f backend     # xizmat logi
docker compose -f docker-compose.davomat.yml exec backend python manage.py <command>
```

## 6. Yangilash va zaxira nusxalar

### Yangilash

```bash
cd /opt/davomat
bash deploy/davomat/update.sh                          # git orqali olingan kod: git pull
bash deploy/davomat/update.sh --from /root/davomat.tar.gz   # reliz arxivi
```

Skript avval zaxira nusxa oladi, yangi kodni yuklab oladi (`.env`, zaxira nusxalar va loglarga
tegilmaydi), yangi obrazni yig‘adi, qayta ishga tushiradi, migratsiyalarni bajaradi, Caddy fayli
o‘zgargan bo‘lsa Caddy xizmatini qayta ishga tushiradi va sayt javob berguncha kutadi. Yangi
versiya ishga tushmasa, ortga qaytish yo‘lini ko‘rsatadi: oldingi kod,
`update.sh --here --no-backup` va skript olgan zaxira nusxa bilan `restore.sh`.
`update.sh --here` buyrug‘i mavjud kodni qayta yig‘ib, qayta ishga tushiradi (masalan, `.env`
tahrirlangandan keyin).

### Zaxira nusxalar

Har kecha `backup` xizmati `backups/<date>_<time>-nightly/` papkasini yaratadi (soat 02:30,
Toshkent vaqti bilan; `.env` faylidagi `BACKUP_TIME` va `BACKUP_TZ`). Unda:

- `db.sql.gz`: butun ma’lumotlar bazasi;
- `media.tgz`: logotiplar va xodimlar suratlari;
- `private_media.tgz`: skanerlash suratlari va eksportlar;
- `info.txt`: nusxa qachon va nimadan olingani.

Oxirgi 14 kunlik nusxalar saqlanadi (`BACKUP_KEEP_DAYS`). Ularni faqat root o‘qiy oladi: ularda
hammaning ismi, surati va davomati bor.

```bash
bash deploy/davomat/backup.sh            # hozir zaxira nusxa olish (backups/<date>_<time>-manual/)
scp -r root@<server>:/opt/davomat/backups/<folder> .    # bitta nusxani serverdan ko‘chirib olish
```

**Zaxira nusxalarni muntazam ravishda serverdan tashqariga ko‘chiring** (va shifrlangan holda
saqlang): o‘sha diskdagi zaxira nusxa disk ishdan chiqsa, u bilan birga yo‘qoladi.

### Tiklash

```bash
bash deploy/davomat/restore.sh backups/2026-11-10_023000-nightly
```

Skript `restore` so‘zini yozishingizni so‘raydi, joriy holatning ehtiyot nusxasini oladi, Davomatni
to‘xtatadi, o‘sha zaxira nusxadagi ma’lumotlar bazasi va fayllarni joyiga qaytaradi va hammasini
qayta ishga tushiradi. O‘sha zaxira nusxadan keyin sodir bo‘lgan hamma narsa yo‘qoladi.

### Yangi serverga ko‘chish

1. Eski serverda: `bash deploy/davomat/backup.sh`, so‘ng zaxira nusxa papkasini
   **va `.env` faylini** yangi serverga ko‘chiring.
2. Yangi serverda: kodni `/opt/davomat` papkasiga joylang (2-bo‘lim), eski `.env` faylini
   `/opt/davomat/.env` sifatida ko‘chiring (`chmod 600`); manzil o‘zgarsa, `DOMAIN`,
   `DJANGO_ALLOWED_HOSTS`, `DASHBOARD_URL` va `PUBLIC_DEVICE_HOST` qiymatlarini o‘zgartiring.
3. `bash deploy/davomat/install.sh` (u shu `.env` faylini saqlab qoladi), so‘ng
   `bash deploy/davomat/restore.sh <the backup folder>`.
4. Manzil o‘zgargan bo‘lsa, terminallarni yangi manzilga yo‘naltiring (ADMIN.md, 4-bo‘lim).

`.env` faylidagi kalitlar zaxira nusxa olingandagi kalitlar bilan bir xil bo‘lishi shart. Aks holda
Telegram bot tokenini o‘qib bo‘lmaydi va uni qayta kiritishga to‘g‘ri keladi.

## 7. Mahalliy tarmoqdagi server

Server ofisda tursa va unga internetdan hech narsa yetib bormasa, ommaviy sertifikat olib
bo‘lmaydi. Bunday holda uni LAN rejimida o‘rnating:

```bash
bash deploy/davomat/install.sh --lan                # serverning LAN manzili avtomatik aniqlanadi
bash deploy/davomat/install.sh --lan 192.168.1.10   # yoki qo‘lda ko‘rsatiladi
```

Shunda Davomat `https://192.168.1.10/` manzilida o‘z sertifikati bilan ishlaydi. Brauzerlar bir
marta ogohlantiradi («not private», ya’ni ulanish himoyalanmagan): Advanced › Continue (Qo‘shimcha ›
Davom etish) bandlarini tanlang. Ogohlantirish chiqmasligi uchun Caddy ildiz sertifikatini ofis
kompyuterlariga o‘rnating:

```bash
docker compose -f docker-compose.davomat.yml exec caddy cat /data/caddy/pki/authorities/local/root.crt > davomat-root.crt
```

(Windows: faylni ikki marta bosing › Install Certificate (sertifikatni o‘rnatish) › Local Machine
(mahalliy kompyuter) › Trusted Root Certification Authorities (ishonchli ildiz sertifikatlash
markazlari).) Terminallar odatdagidek oddiy HTTP orqali ma’lumot yuboradi. Routerda serverga doimiy
manzil bering (DHCP rezervatsiyasi), aks holda terminallar uni yo‘qotib qo‘yadi.

`--http-only` parametri hammasini oddiy HTTP orqali beradi. U faqat kompyuterning o‘zida
`http://localhost` manzilida sinab ko‘rish uchun: brauzerlar oddiy HTTP orqali tizimga kirishni
faqat localhost uchun saqlab qoladi.

## 8. Tayyor obraz

Yig‘ish uchun taxminan 2 GB operativ xotira va internet (Docker Hub, npm, PyPI) kerak. Kichik yoki
internetsiz serverda obrazni boshqa kompyuterda yig‘ib, serverga ko‘chiring:

```bash
# yig‘ish kompyuterida, o‘sha commit nusxasidan
docker build -t davomat:latest .
docker save davomat:latest | gzip > davomat-image.tar.gz
scp davomat-image.tar.gz root@<server>:/root/

# serverda
bash deploy/davomat/install.sh --image /root/davomat-image.tar.gz
bash deploy/davomat/update.sh --from /root/davomat.tar.gz --image /root/davomat-image.tar.gz   # keyingi yangilanishlar
```

## 9. Xavfsizlik

- `.env` faylida kalitlar saqlanadi: kirish huquqlari 600, faqat root uchun. Uni hech qachon git
  omboriga yoki chatga joylamang.
- Faqat 80 va 443 portlari (va SSH) ochiq bo‘lishi kerak. PostgreSQL va Redis tashqaridan hech
  qachon ochiq bo‘lmaydi.
- root foydalanuvchisi uchun parol o‘rniga SSH kalitlaridan foydalaning va Ubuntu tizimini yangilab
  turing (`apt-get update && apt-get upgrade` yoki `unattended-upgrades`).
- Har bir terminal o‘z maxfiy kodi bo‘lgan manzilga ma’lumot yuboradi: bu manzilni paroldek ehtiyot
  qiling (yangi kod terminal sahifasida bir bosishda olinadi).
- HTTPS ishlay boshlagach, `.env` faylida `DJANGO_SECURE_HSTS_SECONDS=31536000` qiymatini qo‘ying va
  `bash deploy/davomat/update.sh --here` buyrug‘ini bajaring: shunda brauzerlar faqat HTTPS orqali
  ulanadigan bo‘ladi.

## 10. Bitta kompyuterda sinab ko‘rish

`deploy/davomat/demo.sh` butun tizimni Docker o‘rnatilgan noutbuk yoki kompyuterda (root
huquqisiz) alohida loyiha sifatida, o‘z ma’lumotlari bilan `http://localhost:18080` manzilida ishga
tushiradi va unga namuna tashkilotni qo‘shadi (login: `admin`, parol: `Namuna-2026`):

```bash
bash deploy/davomat/demo.sh up        # kerak bo‘lsa obrazni yig‘ish, ishga tushirish, namuna ma’lumotlarni qo‘shish
bash deploy/davomat/demo.sh down      # to‘xtatish (ma’lumotlar qoladi; up yana ishga tushiradi)
bash deploy/davomat/demo.sh wipe      # to‘xtatish va ma’lumotlarni o‘chirish
```

`up --no-seed` namuna ma’lumotlarsiz ishga tushiradi (sozlash sahifasi ochiladi), `up --lan` bilan
shu tarmoqdagi terminal ham unga hodisalarni yubora oladi (terminalda port 18080), `rebuild` yangi
kodni oladi, `seed` namuna ma’lumotlarni yangisiga almashtiradi. U shu kompyuterdagi haqiqiy
o‘rnatishga hech qachon tegmaydi.
