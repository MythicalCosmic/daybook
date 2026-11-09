# Muammolar va ularni hal qilish

Shu yerdan boshlang — serverda, kod papkasidan (`/opt/davomat`):

```bash
bash deploy/davomat/status.sh
```

U hech narsani o‘zgartirmaydi va xizmatlar, sayt va uning sertifikati, terminallar manzili, worker
va bot, zaxira nusxalar, disk hamda oxirgi xatolarni ko‘rsatadi; oxirida nimaga e’tibor berish
kerakligini yozadi. Quyidagi buyruqlarda `dc` — `docker compose -f docker-compose.davomat.yml`
buyrug‘ining qisqartmasi:

```bash
alias dc='docker compose -f docker-compose.davomat.yml'
dc ps                        # xizmatlar va ularning holati
dc logs --tail 100 backend   # bitta xizmat logi (caddy, backend, worker, beat, bot, db, backup)
dc logs -f backend           # logni kuzatib borish
```

## Sayt ochilmayapti

- **O‘rnatishdan keyin bir necha daqiqa davomida**: birinchi ishga tushishda ma’lumotlar bazasi
  tayyorlanadi. `dc logs backend` buyrug‘i `Applying …` qatorlarini ko‘rsatadi; `Listening at`
  qatori chiqishini kuting.
- **Sertifikat xatolari / tashqaridan «connection refused»**: Caddy sertifikatni Let’s Encrypt
  xizmatidan oladi, Let’s Encrypt esa serverga **internetdan 80 va 443 portlari orqali** ulana olishi
  kerak. Xavfsizlik devorini (`ufw status`), provayderning bulutli xavfsizlik devorini va domenning
  DNS `A` yozuvi serverga yo‘naltirilganini (`getent hosts <domain>`) tekshiring. `dc logs caddy`
  nima ishlamaganini ko‘rsatadi. Tuzatilgach, Caddy o‘zi qayta urinadi (yoki `dc restart caddy`).
- **Sertifikat olishga juda ko‘p muvaffaqiyatsiz urinish bo‘ldi**: beshta muvaffaqiyatsiz urinishdan
  keyin Let’s Encrypt bu nom uchun bir soatga tanaffus qiladi. Sababini tuzating, kuting, so‘ng
  `dc restart caddy`. `<server IP>.nip.io` manzili har doim serverga yo‘naltiriladi, uni sinash
  uchun ishlatish qulay.
- **«Bad Request (400)»**: brauzerdagi manzil `.env` faylidagi manzil bilan mos emas. Davomat faqat
  `DOMAIN` (`DJANGO_ALLOWED_HOSTS`) manziliga javob beradi. Ularni o‘zgartirgandan keyin:
  `bash deploy/davomat/update.sh --here`.
- **Xizmat to‘xtovsiz qayta ishga tushyapti** (`dc ps` natijasida `Restarting`): sababi uning
  logida (`dc logs --tail 100 <service>`); ko‘pincha bu `.env` faylidagi noto‘g‘ri yoki
  yetishmayotgan qiymat.

## Terminal serverga ulana olmayapti

Terminal kartochkasida «Terminalning birinchi hodisasi kutilmoqda» yozuvi o‘zgarmay turibdi.

1. **Terminal tarmog‘idagi kompyuterdan** sozlash sahifasidagi terminal manzilini HTTP orqali
   oching (yoki `curl` bilan tekshiring): `http://<server>/api/v1/devices/hik/<code>/`. Javob
   `{"statusCode": 200, "statusString": "OK", …}` bo‘lishi kerak.
   - Javob keldi: tarmoq joyida, terminal sozlamalari esa noto‘g‘ri (2-qadam).
   - 404: kod noto‘g‘ri (URL manzilini sozlash sahifasidan qayta nusxalang; yangi kod berilsa,
     eskisi ishlamay qoladi).
   - Javob yo‘q: bu tarmoqdan serverga port 80 orqali ulanib bo‘lmayapti (ofis yoki server
     xavfsizlik devori), yoki server manzili noto‘g‘ri.
2. **Terminalda** (HTTP Listening): host sozlash sahifasidagidek aynan bir xil, URL boshida va
   oxirida `/` belgisi bor, port `80`, protokol `HTTP`, hammasi saqlangan bo‘lishi kerak. O‘z
   tarmog‘idan tashqaridagi biror manzilga ulanishi uchun terminalning tarmoq sozlamalarida
   (Configuration › Network › Basic Settings) **gateway** (shlyuz) ko‘rsatilgan bo‘lishi kerak, host
   nom bilan berilgan bo‘lsa — DNS server ham: IP manzil ishlatilsa, DNS kerak bo‘lmaydi.
3. `dc logs --tail 50 backend | grep devices` terminallardan kelgan har bir so‘rovni ko‘rsatadi.

## Eski proshivkada HTTPS

Ko‘p terminallar bugungi sertifikatlar bilan HTTPS orqali ishlay olmaydi (V3.2.x proshivkali
DS-K1T341AMF qanday sozlanmasin, hech qachon ulanmaydi). **HTTP protokoli va port 80** ishlating:
Davomat terminallar manzilini hech qachon HTTPS manziliga yo‘naltirmaydi va hodisalarni qanday
kelsa, shunday qabul qiladi. Bu manzilni URL ichidagi maxfiy kod himoya qiladi; manzil begonalarga
ma’lum bo‘lib qolsa, terminalga yangi kod bering (terminal sahifasida, bir bosishda) va yangi URL
manzilini terminalga kiriting.

## Terminaldagi eski tarix

Terminal ulangandan keyin bir necha soat davomida «Terminal avval eski tarixini yubormoqda» yozuvi
turishi — odatiy hol: terminal xotirasida saqlangan har bir skanerlashni eng eskisidan boshlab o‘z
sur’atida yuklaydi (sekundiga taxminan bir-ikkitadan; 40 000 eski skanerlash bir ish kunini oladi).
Davomat ularni o‘tkazib yuboradi (kelish ham, xabar ham bo‘lmaydi) va terminal kartochkasida sanab
boradi. Jonli skanerlashlar shundan keyin darhol boshlanadi. Terminalni o‘chirib-yoqmang va
sozlamalarini tiklamang: u tarixni boshidan yuboradi, zavod sozlamalariga qaytarish esa ro‘yxatga
olingan yuzlarni o‘chirib yuboradi.

## Soat

- **«Terminal soati orqada qolgan (daqiqa: N)» yoki «Terminal soati oldinda (daqiqa: N)»**:
  Configuration › System › Time Settings bo‘limida terminal vaqt mintaqasini (Toshkent uchun
  GMT+05:00) va NTP serverini (`pool.ntp.org`) sozlang. Odatda sababi — zavoddan qolgan vaqt
  mintaqasi (ko‘pincha GMT+08:00) yoki qo‘lda qo‘yilgan soat.
- **«Terminal soati ancha orqada: jonli skanerlashlar eski bo‘lib ko‘rinadi va o‘tkazib yuboriladi»**:
  terminal sanasi noto‘g‘ri (bir necha kun yoki undan ham ko‘p farq): uni yuqoridagidek sozlang.
  Skanerlashlar darhol yana saqlana boshlaydi.
- **Server soati**: `timedatectl` buyrug‘i `System clock synchronized: yes` deb ko‘rsatishi kerak;
  aks holda: `timedatectl set-ntp true`.

## Hisobga olinmagan skanerlashlar

- **«Bog‘lanmagan»**: bu raqam hech kimga tegishli emas. Noma’lum raqamlardan yangi xodimlar
  yaratilsa (sukut bo‘yicha shunday), bu faqat chetga qo‘yilgan raqamlarda bo‘ladi; aks holda
  raqamni Yuz orqali kirish › Odamlar sahifasida biriktiring.
- **«Takroriy»**: oldingisidan keyin bir necha daqiqa ichidagi ikkinchi skanerlash; hech narsa
  o‘zgarmaydi. Bu odatiy hol.
- **Ishdan ketgan xodim**: uning skanerlashlari qayd etiladi, lekin hisobga olinmaydi.

## Telegram

- **Sozlamalar › Telegram bo‘limida token yaroqsiz deb ko‘rsatilgan**: token bekor qilingan yoki
  xato kiritilgan: BotFather › `/mybots` › bot › API Token, so‘ng tokenni qayta joylang.
- **Bot javob bermayapti**: `dc logs --tail 50 bot`. «No Telegram bot token yet» — tokenni joylang.
  «Conflict: terminated by other getUpdates request» — shu tokendan boshqa dastur ham foydalanmoqda
  (eski server, sinov): uni to‘xtating yoki BotFather orqali tokenni bekor qilib, yangisini joylang.
  Server `api.telegram.org` manziliga HTTPS orqali ulana olishi kerak (chiquvchi ulanish).
- **Kimgadir xabar kelmayapti**: u o‘z havolasini ochib, Start tugmasini bosgan va botni bloklamagan
  bo‘lishi kerak; uning sahifasida Telegram ulangan deb ko‘rsatilgan bo‘lishi kerak.

## Unutilgan parol

Yangi parolni administrator Sozlamalar › Foydalanuvchilar va rollar bo‘limida o‘rnatadi. Hech kim
tizimga kira olmasa, serverda:

```bash
cd /opt/davomat
docker compose -f docker-compose.davomat.yml exec backend python manage.py changepassword <username>
```

Tizimga kira oladigan loginlar:

```bash
docker compose -f docker-compose.davomat.yml exec backend python manage.py shell -c \
  "from django.contrib.auth import get_user_model as U; print([u.username for u in U().objects.filter(is_active=True) if u.has_usable_password()])"
```

Beshta noto‘g‘ri parol bu loginni o‘sha kompyuterdan 15 daqiqaga bloklaydi: shu vaqt o‘tishini
kuting.

## Disk va xotira

- `df -h` va `docker system df`: eski obrazlar `docker image prune -f` buyrug‘i bilan o‘chiriladi.
- `du -sh backups`: zaxira nusxalar 14 kun saqlanadi (`.env` faylidagi `BACKUP_KEEP_DAYS`); ularni
  boshqa joyga ko‘chirib, keraksizlarini o‘chiring.
- Skanerlash suratlari Yuz orqali kirish › Sozlamalar bo‘limida belgilangan kunlardan keyin
  o‘chiriladi.
- Operativ xotira kamida 4 GB bo‘lmasa, yig‘ish xato bilan tugashi mumkin: swap qo‘shing
  (`fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`) yoki
  tayyor obrazdan foydalaning (INSTALL.md, 8-bo‘lim).

## Yangilash muvaffaqiyatsiz bo‘ldi

Yangi versiya ishga tushmasa, `update.sh` ortga qaytish yo‘lini ko‘rsatadi. Qisqacha:

```bash
git -C /opt/davomat checkout <the previous commit>     # yoki oldingi relizni arxivdan chiqaring
bash deploy/davomat/update.sh --here --no-backup
bash deploy/davomat/restore.sh backups/<date>_<time>-pre-update   # faqat ma’lumotlarni ham qaytarish kerak bo‘lsa
```

## Hammasini boshidan boshlash

Hammasini o‘chirib tashlash uchun (barcha ma’lumotlar qaytarib bo‘lmaydigan tarzda o‘chadi), `.env`
faylini saqlab qolgan holda:

```bash
docker compose -f docker-compose.davomat.yml down -v
bash deploy/davomat/install.sh
```

## Yordam so‘rash

`bash deploy/davomat/status.sh` natijasini va muammoli xizmat logining oxirgi qatorlarini
(`dc logs --tail 200 <service>`) yuboring. `.env` faylini hech qachon yubormang: unda kalitlar
saqlanadi.
