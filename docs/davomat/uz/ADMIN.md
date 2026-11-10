# Davomatni boshqarish

Tashkilot administratori uchun: tizimga kirish, filiallar, Face ID terminallari, xodimlar,
foydalanuvchilar, Telegram bot va hisobotlar. Serverni o‘rnatish [INSTALL.md](INSTALL.md) faylida
yozilgan.

**Foydalanuvchilar** Davomatga kiradi (tashkilot egasi, administratorlar, menejerlar, kuzatuvchilar).
**Xodimlar** — terminallar taniydigan odamlar: ular tizimga hech qachon kirmaydi, shunchaki terminal
oldidan o‘tadi. Bir kishi ham foydalanuvchi, ham xodim bo‘lishi mumkin.

## 1. Tizimga kirish

Tashkilot manzilini oching (masalan, `https://davomat.example.uz/`) va login hamda parolingiz bilan
kiring. **Meni eslab qol** belgilansa, shu brauzerda tizimda qolasiz; umumiy kompyuterda buni
yoqmang.

- Bitta login uchun ketma-ket beshta noto‘g‘ri parol kiritilsa, bu login shu kompyuterda
  15 daqiqaga bloklanadi.
- Parol unutilsa: administrator yangisini o‘rnatadi (6-bo‘lim). Mavjud parolni hech kim ko‘ra
  olmaydi, hatto server administratori ham; u serverning o‘zida yangi parol o‘rnatishi mumkin
  (TROUBLESHOOTING.md, «Unutilgan parol» bo‘limi).
- O‘z parolingizni o‘zgartirish: Sozlamalar › Hisobingiz.

## 2. Sozlash sahifasi (bir marta)

Yangi o‘rnatilgan tizim sozlash sahifasini ochadi: tashkilot nomi, vaqt mintaqasi va tili, so‘ng
administrator hisobi. Tashkilot bitta filial bilan boshlanadi — «Asosiy»: uni qayta nomlang va
qolganlarini qo‘shing (keyingi bo‘lim). Nomi va logotipi: Sozlamalar › Tashkilot.

## 3. Filiallar, bo‘limlar va lavozimlar

Jamoa › **Filiallar**: o‘z terminallari va o‘z xodimlari bo‘lgan har bir ofis, do‘kon yoki obyekt.
«Asosiy» filialga haqiqiy nomini bering, qolganlarini qo‘shing. Har bir xodim bir yoki bir nechta
filialga tegishli bo‘ladi, har bir terminal esa bitta filialga.

Jamoa › **Bo‘limlar** va **Lavozimlar** — bir marta to‘ldiriladigan ro‘yxatlar; har bir xodim uchun
ulardan tanlanadi. Hisobotlar bo‘limlar va filiallar bo‘yicha guruhlanadi.

## 4. Hikvision terminalini qo‘shish

Yuz orqali kirish (Face ID) › **Terminal qo‘shish**, uch qadam:

1. **Terminal**: nomi («Asosiy kirish», lentada va Telegramda ko‘rinadi), filiali va skanerlashlarni
   qanday hisoblashi:
   - *Kirish*: har bir skanerlash — kelish;
   - *Chiqish*: har bir skanerlash — ketish;
   - *Bitta eshik*: terminal bitta bo‘lsa, odatda shu tanlanadi; uning skanerlashlari nimani
     anglatishi Yuz orqali kirish › Sozlamalar bo‘limida belgilanadi (quyida).
2. **Terminalda**: terminalga kiritiladigan qiymatlar (quyida). Ularni shu sahifadan nusxalang: har
   bir terminalning URL manzilida o‘z maxfiy kodi bor.
3. **Birinchi skanerlash**: terminalda yuzni skanerlang. Birinchi hodisa kelishi bilan sahifa yashil
   rangga o‘tadi. («Yuzni sinab ko‘rish» skanerlash terminalsiz qanday ko‘rinishini ko‘rsatadi; u
   hisobga olinmaydi.)

**Terminaldan qanday foydalaniladi** (Yuz orqali kirish › Sozlamalar) bitta eshikli terminal
skanerlashlari nimani anglatishini belgilaydi. *Xodimlar faqat kelganda skanerlaydi* (odatiy
tanlov): har bir xodimning kundagi birinchi skanerlashi kelishni belgilaydi, keyingilari esa surati
bilan *Ko‘rildi* deb saqlanadi va davomatni o‘zgartirmaydi. Ketish qayd etilmaydi, shuning uchun kun
o‘zi yopiladi (xodim smenasining oxirida; jadvali yo‘q xodimga ish soati hisoblanmaydi) va hech
kimdan unutilgan ketish haqida so‘ralmaydi. *Xodimlar kelganda ham, ketganda ham skanerlaydi*:
birinchi skanerlash kelish, keyingisi ketish. Har ikki holatda ham ertasi kungi birinchi skanerlash
oldingi kundan ketish emas, yangi kelish hisoblanadi; *Kirish* yoki *Chiqish* deb sozlangan terminal
doim aynan shunday ishlaydi.

### Terminalning veb-sahifasida

1. **Terminal bilan bir tarmoqdagi** kompyuterda brauzer orqali terminal manzilini oching, masalan,
   `http://192.168.1.250` (terminal uni Menu › Communication › Network bo‘limida ko‘rsatadi; yoki
   uni Hikvision kompaniyasining SADP dasturi bilan toping). `admin` sifatida kiring.
2. **Configuration › Network › Advanced Settings › HTTP Listening** bo‘limiga o‘ting (ba’zi
   proshivkalarda (firmware) u Event › Alarm Server yoki Platform Access deb ataladi).
3. Birinchi bo‘sh joyni Davomatdagi sozlash sahifasida ko‘rsatilganidek aynan to‘ldiring, so‘ng
   **Save** (saqlash) tugmasini bosing:

   | Maydon | Qiymat |
   |---|---|
   | Destination IP or Host Name | sozlash sahifasidagi server manzili (masalan, `203.0.113.10`) |
   | URL | `/api/v1/devices/hik/<code>/` (ikkala qiya chiziq bilan) |
   | Port | `80` |
   | Protocol | `HTTP` |

   HTTPS (port 443) faqat terminalda HTTPS haqiqatan ishlaganda tanlanadi: V3.2.x proshivkali
   DS-K1T341AMF buni uddalay olmaydi, shuning uchun u port 80 orqali HTTP ishlatadi. Davomat
   ikkalasini ham qabul qiladi.
4. Sahifada **Test** (sinov) tugmasi bo‘lsa, uni bosing: javob OK bo‘ladi.
5. **Heartbeat** (aloqa signali) sozlamasi bo‘lsa, uni yoqing va oralig‘ini 5 daqiqa qilib
   belgilang: shunda hech kim o‘tmasa ham Davomatdagi terminal holati yangilanib turadi.
6. Har bir skanerlash bilan surat kelishi uchun terminal olgan rasmni yuklashni yoqing (kirishni
   nazorat qilish yoki hodisa sozlamalarida; nomi proshivkaga qarab farq qiladi).

### Terminal soati

Configuration › System › System Settings › **Time Settings** (vaqt sozlamalari):

- **Time zone** (vaqt mintaqasi): `(GMT+05:00)` Tashkent (yoki tashkilotning vaqt mintaqasi);
- **NTP**: yoqilgan, server `pool.ntp.org`, har 60 daqiqada; Save.

Qo‘lda sozlangan terminal soati oyiga bir necha daqiqaga siljiydi. Davomat skanerlash vaqtiga
10 daqiqagacha farq bilan ishonadi; soati bundan ko‘proq oldinda bo‘lgan terminal skanerlashlariga
ular yetib kelgan vaqt yoziladi va terminal kartochkasida soat noto‘g‘riligi ko‘rsatiladi.

### Terminal avval yuboradigan tarix

Terminal birinchi marta ulanganda **xotirasida saqlangan hamma narsani** eng eskisidan boshlab
yuboradi: ko‘pincha o‘n minglab eski skanerlashlarni, sekundiga taxminan bir-ikkitadan, bu esa bir
necha soat davom etishi mumkin. Davomat bir kundan eski yoki terminal qo‘shilishidan oldingi har bir
skanerlashni o‘tkazib yuboradi: ularning hech biri saqlanmaydi, kelish yoki xabarga aylanmaydi,
faqat sanaladi. Terminal kartochkasida soni bilan birga «Terminal avval eski tarixini yubormoqda»
yozuvi chiqadi; jonli skanerlashlar shundan keyin darhol keladi.

Shuning uchun imkon bo‘lsa, terminalni u haqiqatan hisoblay boshlashidan **bir kun oldin** ulang
(masalan, kechqurun) va eski tarixdan qutulish uchun terminalni hech qachon zavod sozlamalariga
qaytarmang: bu ro‘yxatga olingan yuzlarni o‘chirib yuboradi.

### Bugungi skanerlashlar hozir: yordamchi dastur

Eski tarix kelayotgan paytda bugun qilingan skanerlash uning ortida navbat kutadi. Yordamchi dastur
bugungi skanerlashlarni darhol yuboradi. Bu — **terminal tarmog‘idagi** kompyuterda (o‘rnatuvchining
noutbukida yoki server shu tarmoqda bo‘lsa, serverning o‘zida) ishlaydigan kichik `catchup.py`
dasturi: u har bir necha soniyada terminaldan eng yangi skanerlashlarni so‘raydi va har birini surati
bilan Davomatga xuddi terminalning o‘zi yuborgandek jo‘natadi. Davomat har bir skanerlashni bir marta
saqlaydi, shuning uchun terminalning o‘z yuklashi ularga yetib kelganda hech narsa qo‘shilmaydi.

1. Terminal kartochkasida (Yuz orqali kirish › Terminallar) **Bugungi skanerlashlarni hozir olish**
   bandini oching (u sozlashning oxirgi qadamida ham bor) va **Yuklab olish: catchup.py** tugmasini
   bosing. Faylga shu terminalning Davomatdagi manzili yozilgan bo‘ladi; unda terminalning maxfiy
   kodi bor, shuning uchun uni sozlash qiymatlari kabi ehtiyot qiling.
2. Kompyuterda Python 3.9 yoki undan yangi versiyasi bo‘lishi kerak: Linux va macOS tizimlarida u
   bor (`python3 --version`); Windows tizimida uni [python.org](https://www.python.org/downloads/)
   saytidan o‘rnating va «Add python.exe to PATH» belgisini qo‘ying.
3. Fayl turgan papkada terminal oynasini (Windows tizimida — PowerShell) oching va kartochkada
   ko‘rsatilgan buyruqni terminalning o‘z tarmog‘idagi manzili bilan ishga tushiring:

   ```bash
   HIK_PASS=… python3 catchup.py --terminal 192.168.1.250
   ```

   `…` o‘rniga terminalning `admin` parolini yozing yoki uni o‘zgartirmay qoldirib, dastur so‘raganda
   parolni kiriting: shunda parol buyruqlar tarixida qolmaydi. Windows tizimida:
   `py catchup.py --terminal 192.168.1.250`, so‘ng parol. Parol hech qachon ko‘rsatilmaydi va
   saqlanmaydi.
4. Dastur yuborgan har bir skanerlash uchun bitta qator chiqaradi (vaqti, ismi yoki «unknown face»,
   «sent») va har bir necha daqiqada terminalning o‘z yuklashi qayergacha yetganini aytadi. Oynani
   yopmang.
5. Terminal yetib olgach (10 daqiqa davomida eski skanerlash kelmasa), **dastur o‘zi to‘xtaydi**;
   eng ko‘pi bilan 12 soatdan keyin (`--hours`) yoki Ctrl+C bilan ham to‘xtaydi.

Bilib qo‘ying:

- `--check` faqat ikkala ulanishni (terminalga kirishni va Davomat manzilini) tekshiradi va hech
  narsa yubormaydi: birinchi qadam uchun qulay.
- Dastur so‘nggi 10 daqiqadagi skanerlashlardan boshlaydi va undan eskilarini hech qachon
  yubormaydi (`--since 60` bir soat orqaga qaraydi; terminal Davomatga qo‘shilishidan oldingi
  skanerlashlar baribir o‘tkazib yuboriladi).
- Noto‘g‘ri parol dasturni darhol to‘xtatadi va nechta urinish qolganini aytadi: ketma-ket bir
  necha noto‘g‘ri urinish terminalga kirishni taxminan yarim soatga qulflaydi.
- Tarmoq uzilsa, dastur o‘zi qayta urinadi. Agar shu kompyuterdan serverga HTTPS ishlamasa
  (mahalliy o‘rnatishning o‘z sertifikati yoki Python dasturida hali sertifikatlar bo‘lmagan Mac
  kompyuteri), u terminalning o‘zi kabi oddiy HTTP orqali yuboradi va buni aytadi.
- `--user` terminalning boshqa foydalanuvchisi sifatida kiradi; `python3 catchup.py --help` barcha
  sozlamalarni ko‘rsatadi.

### Xodim raqamlari

Terminalda ro‘yxatga olingan har bir odamning **Employee No** (xodim raqami) bor, masalan,
`00000002`. Davomat odamlarni shu raqam orqali taniydi (Jamoa › xodim › **Face ID raqamlari**;
`2` va `00000002` — bir xil raqam). Davomat hali ko‘rmagan raqamdan avtomatik ravishda yangi xodim
yaratiladi, ismi terminaldagidek bo‘ladi: siz faqat ism, lavozim, bo‘lim va filialni to‘g‘rilaysiz.
Yuzlar terminalda qoladi: yangi odamlarni odatdagidek terminalning o‘zida ro‘yxatga oling.

## 5. Xodimlar

Jamoa › **Xodimlar**: surat, lavozim, bo‘lim, filial, bugungi holat (binoda, ketdi, hali kelmagan,
dam olish kuni, ta’tilda), Face ID raqamlari va Telegram ulangan yoki ulanmagani. Qidiruv va
filtrlar yuqorida.

- **Xodim qo‘shish**: ism, telefon, lavozim, bo‘lim, filiallar, ish grafigi, Face ID raqamlari va
  surat.
- **Yuklash** (Excel yoki CSV fayldan): ustunlar — ism, familiya, telefon, lavozim, bo‘lim, filial,
  Face ID raqami. Hech narsa saqlanmasdan turib, ko‘rib chiqish oynasi nima yaratilishini va muammosi
  bor har bir qatorni ko‘rsatadi.
- **Eksport**: ro‘yxatni jadval fayli sifatida yuklab olish.
- **Ishdan ketgan** xodim: uni oching › Ishdan ketdi (sanasi bilan). Uning tarixi hisobotlarda
  qoladi, skanerlashlari esa endi hisobga olinmaydi. **Ishga qaytdi** tugmasi uni yana ishlayotganlar
  qatoriga qaytaradi.

Xodim sahifasida shu oydagi davomati taqvim ko‘rinishida, skanerlashlari suratlari bilan va Telegram
ulanishi ko‘rsatiladi.

## 6. Foydalanuvchilar va rollar

Sozlamalar › **Foydalanuvchilar va rollar**: kim tizimga kiradi va nimalar qila oladi.

| Rol | Nima qila oladi |
|---|---|
| Egasi | hammasi |
| Administrator | egasini o‘zgartirishdan tashqari hammasi |
| Menejer | **o‘z filiallarining** davomati, xodimlari va hisobotlari |
| Kuzatuvchi | faqat ko‘rish: davomat, xodimlar va hisobotlar |

Foydalanuvchini login, parol va rol bilan qo‘shing (menejer uchun filiallarni ham tanlang).
**Yangi parol o‘rnatish** foydalanuvchiga yangi parol beradi; **Kirishni o‘chirish** bilan u darhol
tizimga kira olmay qoladi (tarixi saqlanib qoladi). Ro‘yxatda har bir foydalanuvchi oxirgi marta
qachon kirgani ko‘rinadi.

## 7. Telegram bot

Davomat xabarlarini tashkilotning o‘z boti orqali yuboradi:

1. Telegramda **@BotFather** botini oching, `/newbot` buyrug‘ini yuboring, botga nom bering
   («Namuna Davomat») va `bot` bilan tugaydigan foydalanuvchi nomini tanlang
   (`namuna_davomat_bot`). BotFather **token** bilan javob beradi, masalan: `7123456789:AAH…`.
   Botning rasmi uchun **@BotFather** botida `/setuserpic` buyrug‘ini yuboring, botingizni tanlang
   va `deploy/davomat/brand/telegram-avatar.png` faylini (Davomat belgisi) yoki tashkilot logotipini
   yuboring.
2. Sozlamalar › **Telegram** › tokenni joylang › Tekshirish va saqlash. Davomat uni darhol Telegram
   orqali tekshiradi va bot nomini ko‘rsatadi. Bot bir daqiqa ichida o‘zi ishga tushadi.
3. **Odamlarning Telegramini ulang**: xodim yoki foydalanuvchi sahifasidagi **Telegramni ulash**
   tugmasi bir martalik havola va QR kod beradi (24 soat amal qiladi, bir marta ishlatiladi). Odam
   uni telefonida ochib, **Start** tugmasini bosadi.
   Sozlamalar › Telegram › **Sinovni yuborish**: bot sizga yozadi.

Kim nimani oladi:

- filialni ko‘radigan menejerlar: kelganlar surati bilan, kechikishlar, kun yakuni, notanish yuzlar
  (yoqilgan bo‘lsa);
- xodimlar: o‘zlarining kelishi va ketishi (yoqilgan bo‘lsa).

Bot buyruqlari: `/today` (menejerlar uchun: kim ishda, kim kechikdi, kim hali kelmadi, kim
ta’tilda), `/me` (xodimlar uchun: bugungi kun va shu oy), `/language`, `/help`. Yangi token (xuddi
shunday joylanadi) eskisining o‘rnini egallaydi; bot u bilan o‘zi qayta ishga tushadi.

Terminallar Telegramga nima yuborishi Yuz orqali kirish › Sozlamalar bo‘limida belgilanadi: hech
narsa, har bir xodimning kundagi birinchi skanerlashi yoki har bir skanerlash; notanish yuzlar
haqida xabar; har bir xodimning o‘ziga xabar; suratlar qancha saqlanishi (suratlar shuncha kundan
keyin o‘chiriladi; 0 — suratlar saqlanmaydi).

## 8. «Davomat» bo‘limi

**Davomat** bo‘limida qoidalar va kundalik ish jamlangan:

- **Bugun**: hozir kim ishda, kim qancha kechikdi, kim hali kelmadi.
- **Grafiklar** va **Smenalar**: har bir xodim qachon kutiladi (uning smenalari); kechikish va
  erta ketish shularga nisbatan o‘lchanadi. **Almashuvlar**: xodimlar o‘zaro almashadigan yoki
  bo‘sh qoldiradigan smenalar.
- **Tuzatishlar**: unutilgan ketish yoki noto‘g‘ri skanerlash; ularni menejer tuzatadi va kim
  tuzatgani saqlanib qoladi; tasdiqlashni kutayotgan qo‘shimcha ish ham shu yerda.
- **Tabel**: butun oy, Excel formatida (T-13 shakli ham bor).

Tasdiqlangan ta’til kelmaslik emas, ta’til sifatida hisoblanadi. Xodimning oldingi
skanerlashidan keyin bir necha daqiqa ichidagi skanerlash hech narsani o‘zgartirmaydi
(takroriy).

## 9. Hisobotlar

Davomat › **Hisobotlar**: davrni (sukut bo‘yicha joriy oy), filial va bo‘limni tanlang:

- har bir xodim bo‘yicha: rejadagi, kelgan, kelmagan va ta’tildagi kunlar; ishlangan soatlar;
  kechikishlar soni va daqiqalari; erta ketishlar; qo‘shimcha ish; o‘z vaqtida kelish ko‘rsatkichi;
- har bir bo‘lim va filial bo‘yicha: xuddi shular, jamlangan holda;
- kunlar bo‘yicha dinamika (kelganlar, kechikkanlar, kelmaganlar) va o‘z vaqtida kelish reytingi.

Har bir jadvalni Excel yoki PDF formatida eksport qilish mumkin.

## 10. Maxfiylik

Yuzlar hech qachon terminaldan tashqariga chiqmaydi: Davomat har bir skanerlashning vaqtini,
terminaldagi raqam va ismni hamda suratni saqlaydi; surat Yuz orqali kirish › Sozlamalar bo‘limida
belgilangan kunlardan keyin o‘chiriladi. Xodimlardan Face ID orqali davomat hisobini yuritishga
yozma rozilik oling.
