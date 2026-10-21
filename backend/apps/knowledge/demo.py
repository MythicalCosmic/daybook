"""Demo data of the knowledge base: a shop's handbook, till rules, warehouse how-tos and the
sales floor standard, in Uzbek, with versions, read receipts and links to routines."""

import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw, ImageFont

from apps.knowledge import services
from apps.knowledge.models import Page, PageAck, PageVersion, Space
from apps.members.models import Position

WELCOME = """
<p>Assalomu alaykum! <strong>Demo Shop</strong> jamoasiga xush kelibsiz. Bu bo‘limda ishning
asosiy qoidalari, kassa, ombor va savdo zali bo‘yicha yo‘riqnomalar jamlangan.</p>
{image}
<h2>Biz haqimizda</h2>
<p>Demo Shop — Toshkentdagi ikki filialli (Chilonzor va Yunusobod) oziq-ovqat va uy-ro‘zg‘or
do‘koni. Har kuni 600 dan ortiq mijozga xizmat ko‘rsatamiz.</p>
<h2>Qadriyatlarimiz</h2>
<ul>
<li><p><strong>Mijoz birinchi o‘rinda.</strong> Har bir mijoz bilan salomlashing va
yordam taklif qiling.</p></li>
<li><p><strong>Halollik.</strong> Kassa, tovar va vaqt — hammasi aniq va ochiq.</p></li>
<li><p><strong>Tartib.</strong> Javonlar to‘la, narxlar ko‘rinadigan, zal toza.</p></li>
</ul>
<div data-callout="info"><p>Savolingiz bo‘lsa, smena boshlig‘i Bekzod Mirzayevga yozing yoki
botda “Vazifa qo‘shish” orqali murojaat qiling.</p></div>
"""

SCHEDULE = """
<p>Do‘kon har kuni ochiq. Har bir xodim o‘z smenasini botdagi jadvaldan ko‘radi.</p>
<table><tbody>
<tr><th><p>Filial</p></th><th><p>Ochilish</p></th><th><p>Yopilish</p></th></tr>
<tr><td><p>Chilonzor</p></td><td><p>09:00</p></td><td><p>21:00</p></td></tr>
<tr><td><p>Yunusobod</p></td><td><p>10:00</p></td><td><p>22:00</p></td></tr>
</tbody></table>
<h2>Smena qoidalari</h2>
<ol>
<li><p>Smenadan <strong>15 daqiqa oldin</strong> keling va botda “📍 Keldim” tugmasini
bosing.</p></li>
<li><p>Tushlik — 30 daqiqa, smena boshlig‘i bilan kelishilgan vaqtda.</p></li>
<li><p>Smenani topshirishda navbatdagi xodimga kassa va zal holatini aytib bering.</p></li>
</ol>
<div data-callout="warning"><p>Kechikish uch martadan oshsa, oylikdan jarima ushlanadi.
Kech qolayotgan bo‘lsangiz, oldindan xabar bering.</p></div>
"""

DRESS = """
<p>Biz mijozlarni toza va bir xil kiyimda kutib olamiz.</p>
<ul data-type="taskList">
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Firma futbolkasi yoki fartugi (ombordan oling)</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Ko‘krak nishoni ism bilan</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Yopiq, toza poyabzal</p></div></li>
</ul>
"""

LEAVE = """
<p>Ta’til va dam olish kunlari botdagi “Ta’til so‘rash” orqali so‘raladi. So‘rov kamida
<strong>3 kun oldin</strong> yuborilishi kerak.</p>
<h2>Kasal bo‘lib qolsangiz</h2>
<ol>
<li><p>Smena boshlanishidan oldin smena boshlig‘iga qo‘ng‘iroq qiling.</p></li>
<li><p>Shifokor ma’lumotnomasini (kasallik varaqasi) rasmga olib, botga yuboring.</p></li>
</ol>
"""

PHONES = """
<table><tbody>
<tr><th><p>Kim</p></th><th><p>Ism</p></th><th><p>Telefon</p></th></tr>
<tr><td><p>Rahbar</p></td><td><p>Dilnoza Karimova</p></td><td><p>+998 90 111 00 01</p></td></tr>
<tr><td><p>Smena boshlig‘i</p></td><td><p>Bekzod Mirzayev</p></td>
<td><p>+998 90 111 00 02</p></td></tr>
<tr><td><p>Texnik yordam (kassa)</p></td><td><p>Servis markazi</p></td>
<td><p>+998 71 200 33 44</p></td></tr>
<tr><td><p>Qo‘riqlash</p></td><td><p>Navbatchi</p></td><td><p>+998 71 200 55 66</p></td></tr>
</tbody></table>
"""

OPEN_TILL_V1 = """
<p>Kassani ochish 10 daqiqadan oshmasligi kerak.</p>
<ol>
<li><p>Kassa apparatini yoqing va sanani tekshiring.</p></li>
<li><p>Boshlang‘ich qoldiqni (razmen) sanang: 500 000 so‘m.</p></li>
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
<div><p>Boshlang‘ich qoldiqni sanang: <strong>500 000 so‘m</strong> (razmen)</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Terminalni yoqing va sinov to‘lovini bekor qiling</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Chek lentasi zaxirasini tekshiring (kamida 3 rulon)</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Ilovada smenani oching va qoldiqni kiriting</p></div></li>
</ul>
<div data-callout="warning"><p>Qoldiq 500 000 so‘mdan farq qilsa, smenani ochmang —
darhol smena boshlig‘iga xabar bering.</p></div>
<h2>Terminal</h2>
<p>Terminal ulanmasa, “Terminal ishlamasa” sahifasiga qarang. Naqd pul bilan savdo
davom etadi.</p>
"""

CLOSE_TILL = """
<p>Do‘kon yopilgandan keyin 20 daqiqa ichida kassa yopiladi.</p>
<ol>
<li><p>Terminalda kunlik hisobotni (sverka) chiqaring va rasmga oling.</p></li>
<li><p>Kassa apparatida <strong>Z-hisobot</strong> chiqaring va rasmga oling.</p></li>
<li><p>Naqd pulni nominallar bo‘yicha sanang. Ilova sizga kutilgan summani ko‘rsatmaydi —
bu “ko‘r sanash”.</p></li>
<li><p>Pulni seyfga qo‘ying, razmenni ertangi kunga qoldiring.</p></li>
</ol>
<div data-callout="danger"><p>Kassani yopmasdan ketish taqiqlanadi. Bot sizga eslatadi va
rahbarga xabar beradi.</p></div>
"""

TERMINAL = """
<div data-callout="info"><p>Avval terminalni o‘chirib, 30 soniyadan keyin qayta yoqing.
Ko‘p hollarda shu yetarli.</p></div>
<ol>
<li><p>Internet kabelini tekshiring.</p></li>
<li><p>Bank texnik yordamiga qo‘ng‘iroq qiling: +998 71 200 33 44.</p></li>
<li><p>Mijozga naqd yoki Click/Payme orqali to‘lashni taklif qiling.</p></li>
</ol>
"""

RETURNS = """
<p>Qaytarish faqat chek bilan va 14 kun ichida qabul qilinadi.</p>
<ul>
<li><p>Oziq-ovqat mahsulotlari qaytarilmaydi (sifatsiz bo‘lsa — almashtiriladi).</p></li>
<li><p>Pul faqat smena boshlig‘i ruxsati bilan qaytariladi.</p></li>
</ul>
"""

RECEIVE = """
<p>Tovar faqat nakladnaya (yuk xati) bilan qabul qilinadi.</p>
<ul data-type="taskList">
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Nakladnayadagi miqdorni sanab chiqing</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Yaroqlilik muddatini tekshiring (kamida 2/3 qolgan bo‘lsin)</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Nakladnayani rasmga olib, ilovaga yuklang</p></div></li>
<li data-type="taskItem" data-checked="false"><label><input type="checkbox"><span></span></label>
<div><p>Tovarni FIFO bo‘yicha joylang: eskisi oldinda</p></div></li>
</ul>
<div data-callout="warning"><p>Kamomad bo‘lsa, haydovchi bilan birga akt tuzing va
imzolating.</p></div>
"""

DELIVERY = """
<p>Buyurtma 2 soat ichida yetkaziladi. Mijozga 15 daqiqa oldin qo‘ng‘iroq qiling.</p>
<h2>Yo‘lda</h2>
<ul>
<li><p>Muzlatilgan mahsulotlar — faqat termosumkada.</p></li>
<li><p>Naqd pul olgan bo‘lsangiz, o‘sha kuni kassaga topshiring.</p></li>
</ul>
"""

GREETING = """
<p>Har bir mijoz do‘konga kirganda 5 soniya ichida salomlashamiz.</p>
<blockquote><p>“Assalomu alaykum! Xush kelibsiz. Biror narsa topishga yordam
beraymi?”</p></blockquote>
<h2>Qilish kerak</h2>
<ul>
<li><p>Ko‘zga qarab, tabassum bilan gapiring.</p></li>
<li><p>Mahsulot yo‘q bo‘lsa — o‘xshashini taklif qiling.</p></li>
</ul>
<h2>Qilmaslik kerak</h2>
<ul>
<li><p>Mijoz oldida telefonda gaplashish.</p></li>
<li><p>“Bilmayman” deb javob berish — “Hozir aniqlab beraman” deng.</p></li>
</ul>
"""

OLD_TILL = """
<p>Eski kassa dasturida smena <strong>F2</strong> tugmasi bilan ochilardi. Yangi dasturga o‘tilgani
uchun bu sahifa arxivda saqlanadi.</p>
"""

PLANTS = """
<p>Zaldagi gullar haftada ikki marta — dushanba va payshanba kunlari sug‘oriladi.</p>
<ul>
<li><p>Har bir tuvakka 1 stakan suv.</p></li>
<li><p>Kaktuslarga suv bermang.</p></li>
</ul>
"""


def _banner() -> SimpleUploadedFile:
    """A warm banner for the welcome page, drawn here (demo data has no files of its own)."""
    width, height = 1200, 360
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    start, end = (168, 90, 39), (95, 122, 69)  # terracotta to sage, the brand ramps
    for x in range(width):
        t = x / (width - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(start, end, strict=True))
        draw.line([(x, 0), (x, height)], fill=colour)
    for index in range(7):
        radius = 60 + index * 26
        draw.ellipse(
            [
                width - 260 - radius,
                height // 2 - radius,
                width - 260 + radius,
                height // 2 + radius,
            ],
            outline=(255, 242, 235),
            width=2,
        )
    try:
        title, line = ImageFont.load_default(size=64), ImageFont.load_default(size=26)
    except OSError, TypeError:  # no FreeType: the small bitmap font
        title = line = ImageFont.load_default()
    draw.text((72, 110), "Demo Shop", font=title, fill=(255, 242, 235))
    draw.text((76, 200), "Chilonzor  ·  Yunusobod  ·  2026", font=line, fill=(255, 226, 208))
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
    till = services.create_space(
        company,
        by=owner,
        name="Kassa",
        icon="💰",
        description="Kassani ochish, yopish, terminal va qaytarish qoidalari.",
        audience_all=False,
        position_ids=ids("Cashier", "Shift lead"),
    )
    stock = services.create_space(
        company,
        by=owner,
        name="Ombor va yetkazib berish",
        icon="📦",
        description="Tovar qabul qilish, saqlash va mijozga yetkazish.",
        audience_all=False,
        position_ids=ids("Stock & warehouse", "Delivery"),
    )
    floor = services.create_space(
        company,
        by=owner,
        name="Savdo zali",
        icon="🛍",
        description="Mijozga xizmat ko‘rsatish standartlari va zal tartibi.",
        audience_all=False,
        position_ids=ids("Sales floor", "Shift lead", "Cashier"),
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
            body=WELCOME.format(image=f'<img data-image-id="{banner.pk}" alt="Demo Shop">'),
            note="Muqova rasmi qo‘shildi",
        )
    except Exception:  # pictures are a nicety; the demo works without them
        pass
    schedule = page(handbook, "Ish tartibi va jadval", "🕘", SCHEDULE, ack=True)
    dress = page(handbook, "Kiyinish qoidalari", "👕", DRESS, parent=schedule)
    leave = page(handbook, "Ta’til va kasallik varaqasi", "🏖", LEAVE)
    phones = page(handbook, "Muhim telefon raqamlari", "📞", PHONES)

    typo = OPEN_TILL_V1.replace("tekshiring", "tekshring")
    open_till = page(till, "Kassani ochish tartibi", "🔓", typo, ack=True)
    open_till = services.save_page(open_till, by=owner, body=OPEN_TILL_V1, note="Imlo tuzatildi")
    close_till = page(till, "Kassani yopish va Z-hisobot", "🔒", CLOSE_TILL, ack=True)
    terminal = page(till, "Terminal ishlamasa nima qilish kerak", "💳", TERMINAL, parent=open_till)
    returns = page(till, "Qaytarish (vozvrat) qoidalari", "🧾", RETURNS, publish=False)

    receive = page(stock, "Tovar qabul qilish (nakladnaya)", "📥", RECEIVE, ack=True)
    delivery = page(stock, "Yetkazib berish standartlari", "🚚", DELIVERY)

    greeting = page(floor, "Mijozni kutib olish standarti", "🙋", GREETING, ack=True)
    plants = page(floor, "Gullarni sug‘orish", "🌿", PLANTS)

    # Read receipts, backdated so the "who has read it" lists look lived in.
    def read(target, *who, days_ago=3):
        for index, member in enumerate(who):
            _ack(target, member, now - timedelta(days=days_ago, hours=index * 3))

    read(welcome, owner, manager, people["worker"], people["madina"], people["jasur"], days_ago=20)
    read(schedule, manager, people["worker"], people["madina"], people["jasur"], days_ago=12)
    read(close_till, manager, people["madina"], days_ago=6)
    read(receive, people["jasur"], days_ago=4)
    read(greeting, people["worker"], manager, days_ago=2)
    # The till opening page changed: Madina read the old version, so she has to read it again.
    read(open_till, people["madina"], manager, days_ago=9)
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
    _timeline(open_till, now, 26, 24.6, 2.2)
    _timeline(close_till, now, 21)
    _timeline(terminal, now, 15)
    _timeline(returns, now, 0.15)
    _timeline(receive, now, 10)
    _timeline(delivery, now, 8.3)
    _timeline(greeting, now, 5)
    _timeline(plants, now, 15.5)

    # The old till software's guide went to the archive when the new one came (nothing is
    # deleted: it waits in the archive).
    old_till = page(till, "Eski kassa dasturi (2025)", "🗄", OLD_TILL)
    _timeline(old_till, now, 60)
    services.archive_page(old_till, by=owner)
    Page.objects.filter(pk=old_till.pk).update(archived_at=now - timedelta(days=9))

    # Links to routines ("How to do this"), when the demo has them.
    from apps.knowledge import targets

    for routine in targets.search(owner, "", limit=20):
        if routine.type != "routine":
            continue
        if "Opening" in routine.title or "Open" in routine.title:
            services.link_page(open_till, by=owner, target_type="routine", target_id=routine.id)
        elif any(word in routine.title.lower() for word in ("customer", "mijoz")):
            # The sales floor reads this one, so its "How to do this" shows on their tasks.
            services.link_page(greeting, by=owner, target_type="routine", target_id=routine.id)
        elif "plants" in routine.title.lower():
            services.link_page(plants, by=owner, target_type="routine", target_id=routine.id)
