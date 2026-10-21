"""Demo data of the knowledge base (docs/PLAN-OWNER.md §14.3): Demo Dorixona's handbook, the
pharmacy rules (receiving, the cold chain, prescription medicines, expired goods, the controlled
register, prices and tags, the night handover), the till and delivery, in Uzbek, with versions,
read receipts and links to routines. The pages describe the pharmacy's own procedures; they never
tell a customer which medicine to take or how much."""

import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw, ImageFont

from apps.core import demo_plan
from apps.knowledge import services
from apps.knowledge.models import Page, PageAck, PageVersion, Space
from apps.members.models import Position

WELCOME = """
<p>Assalomu alaykum! <strong>Demo Dorixona</strong> jamoasiga xush kelibsiz. Bu yerda ish
tartibi, dorixona qoidalari, kassa va yetkazib berish bo‘yicha yo‘riqnomalar jamlangan.</p>
{image}
<h2>Biz haqimizda</h2>
<p>Demo Dorixona — Toshkentdagi ikki dorixona: Chilonzorda har kuni 08:00 dan 22:00 gacha,
Yunusobodda esa kecha-kunduz ishlaymiz. Kuniga 300 dan ortiq xaridorga xizmat ko‘rsatamiz.</p>
<h2>Qadriyatlarimiz</h2>
<ul>
<li><p><strong>Xavfsizlik birinchi o‘rinda.</strong> Har bir dori seriyasi, yaroqlilik muddati
va saqlash sharoiti tekshiriladi.</p></li>
<li><p><strong>Halollik.</strong> Kassa, narx va hujjatlar — hammasi aniq va ochiq.</p></li>
<li><p><strong>Hurmat.</strong> Xaridorni tinglaymiz, tashxis qo‘ymaymiz: kerak bo‘lsa,
shifokorga yo‘naltiramiz.</p></li>
</ul>
<div data-callout="info"><p>Savolingiz bo‘lsa, Chilonzor mudiri Bekzod Mirzayevga yoki
Yunusobod mudiri Farrux Aliyevga yozing.</p></div>
"""

SCHEDULE = """
<p>Har bir xodim o‘z smenasini botdagi jadvaldan ko‘radi.</p>
<table><tbody>
<tr><th><p>Dorixona</p></th><th><p>Ish vaqti</p></th><th><p>Smenalar</p></th></tr>
<tr><td><p>Chilonzor</p></td><td><p>08:00–22:00, har kuni</p></td>
<td><p>08:00–20:00 va 10:00–22:00, 2/2</p></td></tr>
<tr><td><p>Yunusobod</p></td><td><p>Kecha-kunduz</p></td>
<td><p>Kunduzgi 08:00–20:00, tungi 20:00–08:00, 2/2</p></td></tr>
</tbody></table>
<h2>Smena qoidalari</h2>
<ol>
<li><p>Smenadan <strong>10 daqiqa oldin</strong> keling va botda “📍 Keldim” tugmasini
bosing.</p></li>
<li><p>Dorixonada doim kamida bitta farmatsevt yoki provizor bo‘lishi shart: tushlikni
hamkasbingiz bilan kelishib oling.</p></li>
<li><p>Smenani topshirishda kassa, muzlatgich va retseptlar jurnalini birga tekshiring.</p></li>
</ol>
<div data-callout="info"><p>Tungi soatlar (22:00 dan 06:00 gacha) kamida 1,5 baravar
to‘lanadi.</p></div>
"""

DRESS = """
<p>Biz xaridorlarni toza va bir xil kiyimda kutib olamiz.</p>
<ul data-type="taskList">
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Oq xalat (ombordan oling, haftasiga ikki marta almashtiring)</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Ism va lavozim yozilgan bejik</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Yopiq, toza poyabzal</p></div></li>
</ul>
"""

LEAVE = """
<p>Ta’til va dam olish kunlari botdagi “Ta’til so‘rash” orqali so‘raladi. So‘rov kamida
<strong>3 kun oldin</strong> yuborilishi kerak, toki o‘rningizga hamkasbingiz chiqa olsin.</p>
<h2>Kasal bo‘lib qolsangiz</h2>
<ol>
<li><p>Smena boshlanishidan oldin mudirga qo‘ng‘iroq qiling.</p></li>
<li><p>Kasallik varaqasini rasmga olib, botga yuboring.</p></li>
</ol>
"""

PHONES = """
<table><tbody>
<tr><th><p>Kim</p></th><th><p>Ism</p></th><th><p>Telefon</p></th></tr>
<tr><td><p>Egasi</p></td><td><p>Dilnoza Karimova</p></td><td><p>+998 90 111 00 01</p></td></tr>
<tr><td><p>Chilonzor mudiri</p></td><td><p>Bekzod Mirzayev</p></td>
<td><p>+998 90 111 00 02</p></td></tr>
<tr><td><p>Yunusobod mudiri</p></td><td><p>Farrux Aliyev</p></td>
<td><p>+998 90 123 40 00</p></td></tr>
<tr><td><p>Kassa texnik yordami</p></td><td><p>Servis markazi</p></td>
<td><p>+998 71 200 33 44</p></td></tr>
</tbody></table>
"""

RECEIVING = """
<p>Dori faqat nakladnoy bilan qabul qilinadi. Kirim 30 daqiqadan oshmasligi kerak.</p>
<ul data-type="taskList">
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Nakladnoydagi nom va miqdorni sanab chiqing</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Har bir qatorning seriyasi va yaroqlilik muddatini tekshiring</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Sovuq zanjir dorilari: harorat yorlig‘ini ko‘ring va darhol muzlatgichga qo‘ying</p>
</div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Nakladnoyni rasmga olib, ilovaga yuklang</p></div></li>
</ul>
<div data-callout="warning"><p>Yaroqlilik muddati 6 oydan kam qolgan yoki qadog‘i shikastlangan
dorini qabul qilmang: haydovchi bilan birga dalolatnoma tuzing.</p></div>
"""

COLD_CHAIN = """
<p>Insulin, ba’zi vaksinalar va ko‘z tomchilari kabi issiqqa sezgir dorilar muzlatgichda
<strong>+2 °C dan +8 °C gacha</strong> saqlanadi.</p>
<h2>Har kuni</h2>
<ol>
<li><p>Haroratni kuniga ikki marta — 09:00 da va 20:30 da — botdagi vazifaga yozing.</p></li>
<li><p>Muzlatgich eshigini kerakdan ortiq ochmang, dorilarni devorga tegizmang.</p></li>
</ol>
<div data-callout="danger"><p>Harorat chegaradan chiqsa: darhol mudirga xabar bering, dorilarni
zaxira muzlatgichga o‘tkazing va nima bo‘lganini jurnalga yozing. Bunday dorini mudir
ruxsatisiz sotmang.</p></div>
<p>Xona harorati +15 °C dan +25 °C gacha bo‘lishi kerak.</p>
"""

PRESCRIPTION = """
<p>Retsept bo‘yicha beriladigan dorilar faqat amaldagi retsept (qog‘oz yoki elektron)
ko‘rsatilganda sotiladi. Retseptli dorilar vitrinaga qo‘yilmaydi.</p>
<ol>
<li><p>Retseptning muddati, shifokor imzosi va muhrini tekshiring.</p></li>
<li><p>Dorini ta’sir etuvchi moddasi (XPN) bo‘yicha bering.</p></li>
<li><p>Qog‘oz retseptni dorixonada qoldiring va retseptlar jurnaliga yozing.</p></li>
</ol>
<div data-callout="warning"><p>Antibiotiklar va tizimli gormonlar faqat elektron retsept bilan
beriladi: bemorning ma’lumotini tizimda tekshiring.</p></div>
"""

EXPIRED = """
<p>Muddati o‘tgan yoki sifatsiz deb topilgan dori darhol sotuvdan olinadi.</p>
<ol>
<li><p>Dorini “Karantin” javoniga o‘tkazing va ro‘yxatga yozing.</p></li>
<li><p>Mudir hisobdan chiqarish dalolatnomasini tuzadi.</p></li>
<li><p>Dori komissiya ishtirokida yo‘q qilinadi; dalolatnoma nusxasi saqlanadi.</p></li>
</ol>
<p>Har dushanba muddati 90 kundan kam qolgan dorilarni tekshiramiz va oldingi qatorga
qo‘yamiz.</p>
"""

CONTROLLED = """
<p>Nazoratdagi moddalar faqat Yunusobod dorixonasida, metall seyfda saqlanadi.</p>
<ul>
<li><p>Har bir kirim va sotuv raqamlangan, tikilgan kitobga o‘sha kuni yoziladi.</p></li>
<li><p>Oylik inventarizatsiya keyingi oyning 3-sanasigacha o‘tkaziladi.</p></li>
<li><p>Kamomad aniqlansa, mudir 3 kun ichida tegishli idoralarga xabar beradi.</p></li>
</ul>
"""

PRICES = """
<p>Har bir dorining narxi ko‘rinib turishi va mas’ul shaxs imzosi bilan tasdiqlanishi kerak.</p>
<ul>
<li><p>Retseptli dorilarga ustama xarid narxidan <strong>20 % dan</strong> oshmaydi va
referent narxdan yuqori bo‘lmaydi.</p></li>
<li><p>Narx yorliqlarini yangi kirimdan keyin seshanba va juma kunlari yangilaymiz.</p></li>
</ul>
"""

NIGHT_HANDOVER = """
<p>Yunusobodda smena 08:00 va 20:00 da almashadi. Topshiruvchi va qabul qiluvchi birga:</p>
<ol>
<li><p>kassani sanaydi va farqni yozadi;</p></li>
<li><p>muzlatgich haroratini tekshiradi;</p></li>
<li><p>retseptlar jurnali va nazoratdagi dorilar kitobini ko‘rib chiqadi;</p></li>
<li><p>navbatchilik jurnaliga imzo qo‘yadi.</p></li>
</ol>
<div data-callout="info"><p>Kechasi eshik qo‘ng‘iroq bilan ochiladi; xaridorga savdo darchasi
orqali xizmat ko‘rsating.</p></div>
"""

OPEN_TILL_V1 = """
<p>Kassani ochish 10 daqiqadan oshmasligi kerak.</p>
<ol>
<li><p>Kassa apparatini yoqing va sanani tekshiring.</p></li>
<li><p>Boshlang‘ich qoldiqni (mayda pul) sanang: 300 000 so‘m.</p></li>
<li><p>Botda smenani oching.</p></li>
</ol>
"""

OPEN_TILL = """
<p>Kassani ochish <strong>10 daqiqadan</strong> oshmasligi kerak. Har bir qadamni belgilab
boring.</p>
<ul data-type="taskList">
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Kassa apparatini yoqing, sana va vaqtni tekshiring</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Boshlang‘ich qoldiqni sanang: <strong>300 000 so‘m</strong> (mayda pul)</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Terminalni yoqing va sinov to‘lovini bekor qiling</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Chek lentasi zaxirasini tekshiring (kamida 3 rulon)</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Ilovada smenani oching va qoldiqni kiriting</p></div></li>
</ul>
<div data-callout="warning"><p>Qoldiq 300 000 so‘mdan farq qilsa, smenani ochmang — darhol
mudirga xabar bering.</p></div>
<h2>Terminal</h2>
<p>Terminal ulanmasa, “Terminal ishlamasa” sahifasiga qarang. Naqd pul bilan savdo davom
etadi.</p>
"""

CLOSE_TILL = """
<p>Smena oxirida kassa 15 daqiqa ichida yopiladi.</p>
<ol>
<li><p>Terminalda kunlik hisobotni (sverka) chiqaring va rasmga oling.</p></li>
<li><p>Kassa apparatida <strong>Z-hisobot</strong> chiqaring va rasmga oling.</p></li>
<li><p>Naqd pulni nominallar bo‘yicha sanang. Ilova sizga kutilgan summani ko‘rsatmaydi —
bu “ko‘r sanash”.</p></li>
<li><p>Mayda pulni keyingi smenaga qoldiring, qolganini egasiga topshiring.</p></li>
</ol>
<div data-callout="danger"><p>Kassani yopmasdan ketish taqiqlanadi. Bot sizga eslatadi va
mudirga xabar beradi.</p></div>
"""

TERMINAL = """
<div data-callout="info"><p>Avval terminalni o‘chirib, 30 soniyadan keyin qayta yoqing.
Ko‘p hollarda shu yetarli.</p></div>
<ol>
<li><p>Internet kabelini tekshiring.</p></li>
<li><p>Bank texnik yordamiga qo‘ng‘iroq qiling: +998 71 200 33 44.</p></li>
<li><p>Xaridorga naqd yoki Click, Payme, Uzum orqali to‘lashni taklif qiling.</p></li>
</ol>
"""

NO_RETURNS = """
<p>Sotilgan dorilar qaytarib olinmaydi va almashtirilmaydi. Xaridorga buni muloyimlik bilan
tushuntiring.</p>
<ul>
<li><p>Agar dori sifatsiz bo‘lsa, uni karantinga qo‘ying va mudirga xabar bering.</p></li>
<li><p>Pulni faqat mudir ruxsati bilan qaytarish mumkin; dori sotuvga qaytmaydi.</p></li>
</ul>
"""

DELIVERY = """
<p>Onlayn buyurtma 2 soat ichida yetkaziladi. Xaridorga 15 daqiqa oldin qo‘ng‘iroq qiling.</p>
<h2>Yo‘lda</h2>
<ul>
<li><p>Retseptli dorilar yetkazib berilmaydi: xaridor retsept bilan dorixonaga keladi.</p></li>
<li><p>Sovuq zanjir dorilari faqat termosumkada, sovutgich elementi bilan.</p></li>
<li><p>Naqd pul olgan bo‘lsangiz, o‘sha kuni kassaga topshiring.</p></li>
</ul>
"""

CUSTOMERS = """
<p>Xaridor dorixonaga kirganda 5 soniya ichida salomlashamiz.</p>
<blockquote><p>“Assalomu alaykum! Sizga qanday yordam bera olaman?”</p></blockquote>
<h2>Qilish kerak</h2>
<ul>
<li><p>Retsept yoki dori nomini diqqat bilan o‘qing, kerak bo‘lsa qayta so‘rang.</p></li>
<li><p>Dori bo‘lmasa — defekturaga yozing va qachon kelishini ayting.</p></li>
</ul>
<h2>Qilmaslik kerak</h2>
<ul>
<li><p>Tashxis qo‘yish yoki dori va dozani o‘zingiz tanlab berish — bu shifokorning ishi.</p></li>
<li><p>“Bilmayman” deyish — “Hozir aniqlab beraman” deng.</p></li>
</ul>
"""

OLD_TILL = """
<p>Eski kassa dasturida smena <strong>F2</strong> tugmasi bilan ochilardi. Yangi dasturga o‘tilgani
uchun bu sahifa arxivda saqlanadi.</p>
"""

PLANTS = """
<p>Dorixonadagi gullar haftada ikki marta — dushanba va payshanba kunlari sug‘oriladi.</p>
<ul>
<li><p>Har bir tuvakka 1 stakan suv.</p></li>
<li><p>Dorilar javoni yonidagi gullarga suv sepmang.</p></li>
</ul>
"""


def _banner() -> SimpleUploadedFile:
    """A calm green banner for the welcome page, drawn here (demo data has no files)."""
    width, height = 1200, 360
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    start, end = (46, 125, 107), (74, 106, 138)
    for x in range(width):
        t = x / (width - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(start, end, strict=True))
        draw.line([(x, 0), (x, height)], fill=colour)
    cx, cy = width - 260, height // 2
    draw.rectangle((cx - 30, cy - 90, cx + 30, cy + 90), fill=(240, 248, 245))  # a cross
    draw.rectangle((cx - 90, cy - 30, cx + 90, cy + 30), fill=(240, 248, 245))
    try:
        title, line = ImageFont.load_default(size=64), ImageFont.load_default(size=26)
    except OSError, TypeError:  # no FreeType: the small bitmap font
        title = line = ImageFont.load_default()
    draw.text((72, 110), "Demo Dorixona", font=title, fill=(240, 248, 245))
    draw.text((76, 200), "Chilonzor  ·  Yunusobod  ·  2026", font=line, fill=(214, 236, 228))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return SimpleUploadedFile("banner.png", buffer.getvalue(), content_type="image/png")


def _ack(page: Page, member, at) -> None:
    PageAck.objects.get_or_create(
        company_id=page.company_id,
        page=page,
        membership=member,
        version=page.version,
        defaults={"at": at},
    )


def _timeline(page: Page, now, *days_ago: float) -> None:
    """Backdate `page`'s story: version n was saved `days_ago[n - 1]` days before `now` (the
    first is also when it was written and, for a published page, published). The author's own
    confirmations move to the version they confirmed, and must-read pages older than a day
    count as already reminded, so the screens read like weeks of use."""
    page.refresh_from_db()
    moments = [now - timedelta(days=days) for days in days_ago]

    def at(version: int):
        return moments[min(max(version, 1), len(moments)) - 1]

    for number, moment in enumerate(moments, start=1):
        PageVersion.objects.filter(page=page, version=number).update(
            created_at=moment, updated_at=moment
        )
    fields = {"created_at": moments[0], "updated_at": moments[-1]}
    if page.published:
        fields["published_at"] = moments[0]
        fields["ack_since"] = at(page.ack_version)
        if page.require_ack and now - fields["ack_since"] > timedelta(days=1):
            fields["reminded_version"] = page.ack_version
    Page.objects.filter(pk=page.pk).update(**fields)
    fresh = now - timedelta(minutes=10)
    for ack in PageAck.objects.filter(page=page, membership_id=page.created_by_id, at__gte=fresh):
        PageAck.objects.filter(pk=ack.pk).update(at=at(ack.version))


def seed(company, people, now) -> None:
    """Add demo rows to `company`. `people` maps owner, manager, worker, madina, jasur
    and nigora to their memberships."""
    owner, manager = people["owner"], people["manager"]
    positions = {position.name: position for position in Position.objects.filter(company=company)}

    def ids(*names):
        return [positions[name].pk for name in names if name in positions]

    qualified = (demo_plan.HEAD, demo_plan.SENIOR, demo_plan.PHARMACIST)
    handbook = Space.objects.filter(company=company).order_by("pk").first()
    if handbook is None:
        handbook = services.create_space(company, by=owner, name="Kompaniya qo‘llanmasi")
    services.update_space(
        handbook,
        by=owner,
        name="Kompaniya qo‘llanmasi",
        icon="📘",
        description="Ish tartibi, qoidalar va yangi xodim bilishi kerak bo‘lgan hamma narsa.",
        audience_all=True,
    )
    rules = services.create_space(
        company,
        by=owner,
        name="Dorixona qoidalari",
        icon="💊",
        description="Kirim, saqlash, retseptli dorilar, muddati o‘tgan dorilar va narxlar.",
        audience_all=False,
        position_ids=ids(*qualified, demo_plan.STOCK),
    )
    till = services.create_space(
        company,
        by=owner,
        name="Kassa",
        icon="💰",
        description="Kassani ochish va yopish, terminal, sotilgan dori qaytarilmasligi.",
        audience_all=False,
        position_ids=ids(*qualified),
    )
    delivery = services.create_space(
        company,
        by=owner,
        name="Yetkazib berish",
        icon="🚚",
        description="Onlayn buyurtmalar va yo‘ldagi qoidalar.",
        audience_all=False,
        position_ids=ids(demo_plan.COURIER, demo_plan.HEAD),
    )

    def page(space, title, emoji, body, *, parent=None, ack=False, publish=True, by=owner):
        return services.create_page(
            space,
            by=by,
            title=title,
            emoji=emoji,
            body=body,
            parent=parent,
            require_ack=ack,
            publish=publish,
            notify_readers=False,
        )

    welcome = page(handbook, "Xush kelibsiz!", "👋", WELCOME.format(image=""))
    try:
        banner = services.upload_image(company, _banner(), by=owner, page=welcome)
        welcome = services.save_page(
            welcome,
            by=owner,
            body=WELCOME.format(image=f'<img data-image-id="{banner.pk}" alt="Demo Dorixona">'),
            note="Muqova rasmi qo‘shildi",
        )
    except Exception:  # pictures are a nicety; the demo works without them
        pass
    schedule = page(handbook, "Ish tartibi va smenalar", "🕘", SCHEDULE, ack=True)
    dress = page(handbook, "Kiyinish qoidalari", "🥼", DRESS, parent=schedule)
    leave = page(handbook, "Ta’til va kasallik varaqasi", "🏖", LEAVE)
    phones = page(handbook, "Muhim telefon raqamlari", "📞", PHONES)
    customers = page(handbook, "Xaridor bilan muloqot", "🙋", CUSTOMERS, ack=True)
    plants = page(handbook, "Gullarni sug‘orish", "🌿", PLANTS)

    receiving = page(rules, "Kirim (nakladnoy): dori qabul qilish", "📥", RECEIVING, ack=True)
    cold = page(rules, "Sovuq zanjir: +2…+8 °C", "❄️", COLD_CHAIN, ack=True)
    rx = page(rules, "Retsept bo‘yicha dorilar", "📋", PRESCRIPTION, ack=True)
    expired = page(rules, "Muddati o‘tgan dorilar", "⏳", EXPIRED)
    controlled = page(rules, "Nazoratdagi moddalar jurnali", "🔐", CONTROLLED, parent=rx)
    prices = page(rules, "Narx va narx yorliqlari", "🏷", PRICES)
    night = page(rules, "Tungi navbatni topshirish", "🌙", NIGHT_HANDOVER)

    typo = OPEN_TILL_V1.replace("tekshiring", "tekshring")
    open_till = page(till, "Kassani ochish tartibi", "🔓", typo, ack=True)
    open_till = services.save_page(open_till, by=owner, body=OPEN_TILL_V1, note="Imlo tuzatildi")
    close_till = page(till, "Kassani yopish va Z-hisobot", "🔒", CLOSE_TILL, ack=True)
    terminal = page(till, "Terminal ishlamasa nima qilish kerak", "💳", TERMINAL, parent=open_till)
    no_returns = page(till, "Dorilar qaytarilmaydi", "🧾", NO_RETURNS, publish=False)

    deliveries = page(delivery, "Yetkazib berish qoidalari", "🚚", DELIVERY, ack=True)

    # Read receipts, backdated so the "who has read it" lists look lived in.
    def read(target, *who, days_ago=3):
        for index, member in enumerate(who):
            _ack(target, member, now - timedelta(days=days_ago, hours=index * 3))

    worker, madina, jasur, nigora = (people[key] for key in ("worker", "madina", "jasur", "nigora"))
    read(welcome, owner, manager, worker, madina, jasur, nigora, days_ago=20)
    read(schedule, manager, worker, madina, jasur, days_ago=12)
    read(close_till, manager, madina, days_ago=6)
    read(receiving, madina, manager, days_ago=4)
    read(cold, worker, madina, nigora, days_ago=8)
    read(rx, madina, worker, days_ago=5)
    read(customers, worker, manager, days_ago=2)
    read(deliveries, jasur, days_ago=7)
    # The till opening page changed: Madina read the old version, so she has to read it again.
    read(open_till, madina, manager, days_ago=9)
    open_till = services.save_page(
        open_till,
        by=owner,
        body=OPEN_TILL,
        note="Terminal va chek lentasi bo‘limi qo‘shildi",
        reread=True,
        notify_readers=False,
    )
    read(open_till, manager, days_ago=1)

    # When each page was written and changed (days ago, one number per version).
    _timeline(welcome, now, 41, 25)
    _timeline(schedule, now, 34)
    _timeline(dress, now, 33)
    _timeline(leave, now, 27)
    _timeline(phones, now, 18.4)
    _timeline(customers, now, 5)
    _timeline(plants, now, 15.5)
    _timeline(receiving, now, 10)
    _timeline(cold, now, 30)
    _timeline(rx, now, 22)
    _timeline(expired, now, 19)
    _timeline(controlled, now, 21)
    _timeline(prices, now, 12)
    _timeline(night, now, 16)
    _timeline(open_till, now, 26, 24.6, 2.2)
    _timeline(close_till, now, 21)
    _timeline(terminal, now, 15)
    _timeline(no_returns, now, 0.15)
    _timeline(deliveries, now, 8.3)

    # The old till software's guide went to the archive when the new one came (nothing is
    # deleted: it waits in the archive).
    old_till = page(till, "Eski kassa dasturi (2025)", "🗄", OLD_TILL)
    _timeline(old_till, now, 60)
    services.archive_page(old_till, by=owner)
    Page.objects.filter(pk=old_till.pk).update(archived_at=now - timedelta(days=9))

    # Links to routines ("How to do this"), when the demo has them.
    from apps.knowledge import targets

    for routine in targets.search(owner, "", limit=40):
        if routine.type != "routine":
            continue
        title = routine.title.lower()
        if "smenani qabul" in title or "tungi navbat" in title:
            services.link_page(night, by=owner, target_type="routine", target_id=routine.id)
        elif "muzlatgich" in title:
            services.link_page(cold, by=owner, target_type="routine", target_id=routine.id)
        elif "kirim" in title:
            services.link_page(receiving, by=owner, target_type="routine", target_id=routine.id)
        elif "yetkaz" in title:
            services.link_page(deliveries, by=owner, target_type="routine", target_id=routine.id)
        elif "buyurtma" in title:
            # The pharmacists read this one, so its "How to do this" shows on their tasks.
            services.link_page(customers, by=owner, target_type="routine", target_id=routine.id)
        elif "kassa" in title:
            services.link_page(close_till, by=owner, target_type="routine", target_id=routine.id)
        elif "gullar" in title:
            services.link_page(plants, by=owner, target_type="routine", target_id=routine.id)
