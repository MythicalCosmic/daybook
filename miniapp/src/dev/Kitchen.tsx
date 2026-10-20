import {
  Banknote,
  CalendarCheck,
  Car,
  Clock3,
  FileSignature,
  HandCoins,
  MapPin,
  Package,
  PenLine,
  Plus,
  Receipt,
  SendHorizontal,
  ShoppingBasket,
  UtensilsCrossed,
  Wallet,
  Wrench,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { useI18n, type Lang } from "../i18n";
import { amountFromTyping, compareMoney } from "../lib/money";
import {
  Avatar,
  AvatarStack,
  Badge,
  Banner,
  BottomBar,
  Button,
  Card,
  CardButton,
  CardTitle,
  ChipGroup,
  CountBadge,
  DenominationCounter,
  Dot,
  EmptyState,
  Field,
  IconButton,
  Input,
  ListCard,
  ListRow,
  MoneyInput,
  MoneyText,
  NumberPad,
  PageHeader,
  PdfLink,
  PullToRefresh,
  PhotoInput,
  ProgressBar,
  ProgressRing,
  ScreenSkeleton,
  SectionHead,
  Segmented,
  Select,
  Sheet,
  SheetTitle,
  SkeletonText,
  SlideToConfirm,
  Stat,
  StatGrid,
  Stepper,
  Textarea,
  useToast,
  type NoteCounts,
  type SlideState,
} from "../ui";

const DEMO = {
  en: {
    shift: "Shift 09:00–18:00 · Chilonzor",
    slide: "Slide to check in",
    checkedIn: "Checked in at 08:57",
    earned: "Earned so far in October",
    bonus: "On time 93% → 95% gives +300 000",
    bonusCaption: "2% more this month adds the bonus",
    budget: "Chilonzor opening · budget",
    sign: "2 documents to sign",
    signBody: "Your contract and the safety rules",
    handover: "Aziz handed you 20 000 000 so‘m",
    handoverBody: "Tap to confirm you received it",
    late: "Payslip for September is ready",
    pay: "Pay",
    attendance: "Attendance",
    documents: "Documents",
    expenses: "Expenses",
    days: "21 of 22 days",
    amount: "Amount",
    category: "Category",
    what: "What was it for?",
    whatPlaceholder: "e.g. Taxi to the supplier",
    paidFrom: "Paid from",
    mine: "My own money",
    company: "Company cash I hold",
    hint: "The receipt photo is enough for the accountant.",
    tooBig: "That's more than the 5 000 000 so‘m limit.",
    taxi: "Taxi",
    supplies: "Supplies",
    food: "Food",
    repairs: "Repairs",
    drawer: "Cash in the drawer",
    expected: "Count it without looking at the total",
    emptyTitle: "Nothing due today. Enjoy it",
    emptyBody: "New tasks from your manager show up here and in the bot.",
    emptyAction: "Add a personal task",
    onTime: "on time this month",
    sales: "sales today",
    lateTasks: "late tasks",
    up: "+12% on Tuesday",
    down: "2 more than last week",
    receipt: "Receipt",
    sheetKicker: "New expense",
    sheetTitle: "Taxi to the supplier",
    send: "Send claim",
    later: "Save draft",
    project: "Website relaunch",
    week: "This week",
    month: "This month",
    year: "Year",
    toastPlain: "Request sent. The answer comes in the bot.",
    toastSuccess: "You're checked in. Have a good shift!",
    toastError: "No connection. Your draft is saved.",
    toastUndo: "Task done",
  },
  ru: {
    shift: "Смена 09:00–18:00 · Чиланзар",
    slide: "Проведите, чтобы отметиться",
    checkedIn: "Отмечено в 08:57",
    earned: "Заработано в октябре",
    bonus: "Вовремя 93% → 95% дадут +300 000",
    bonusCaption: "Ещё 2% в этом месяце — и бонус ваш",
    budget: "Открытие в Чиланзаре · бюджет",
    sign: "2 документа на подпись",
    signBody: "Ваш договор и правила безопасности",
    handover: "Азиз передал вам 20 000 000 сум",
    handoverBody: "Нажмите, чтобы подтвердить получение",
    late: "Расчётный лист за сентябрь готов",
    pay: "Зарплата",
    attendance: "Посещаемость",
    documents: "Документы",
    expenses: "Расходы",
    days: "21 из 22 дней",
    amount: "Сумма",
    category: "Категория",
    what: "На что потратили?",
    whatPlaceholder: "Например: такси до поставщика",
    paidFrom: "Чем оплачено",
    mine: "Своими деньгами",
    company: "Наличными компании",
    hint: "Бухгалтеру достаточно фото чека.",
    tooBig: "Это больше лимита в 5 000 000 сум.",
    taxi: "Такси",
    supplies: "Расходники",
    food: "Еда",
    repairs: "Ремонт",
    drawer: "Наличные в кассе",
    expected: "Считайте, не глядя на итог",
    emptyTitle: "На сегодня ничего. Отдыхайте",
    emptyBody: "Новые задачи от руководителя появятся здесь и в боте.",
    emptyAction: "Добавить личную задачу",
    onTime: "вовремя в этом месяце",
    sales: "продажи сегодня",
    lateTasks: "просроченных задач",
    up: "+12% ко вторнику",
    down: "на 2 больше, чем на прошлой неделе",
    receipt: "Чек",
    sheetKicker: "Новый расход",
    sheetTitle: "Такси до поставщика",
    send: "Отправить",
    later: "В черновик",
    project: "Перезапуск сайта",
    week: "Неделя",
    month: "Месяц",
    year: "Год",
    toastPlain: "Запрос отправлен. Ответ придёт в бот.",
    toastSuccess: "Вы отметились. Хорошей смены!",
    toastError: "Нет связи. Черновик сохранён.",
    toastUndo: "Задача выполнена",
  },
  uz: {
    shift: "Smena 09:00–18:00 · Chilonzor",
    slide: "Kelganingizni belgilash uchun suring",
    checkedIn: "08:57 da belgilandi",
    earned: "Oktabrda shu paytgacha topilgan",
    bonus: "O‘z vaqtida 93% → 95% bo‘lsa +300 000",
    bonusCaption: "Bu oy yana 2% — bonus sizniki",
    budget: "Chilonzor ochilishi · byudjet",
    sign: "Imzolash uchun 2 ta hujjat",
    signBody: "Shartnomangiz va xavfsizlik qoidalari",
    handover: "Aziz sizga 20 000 000 so‘m topshirdi",
    handoverBody: "Olganingizni tasdiqlash uchun bosing",
    late: "Sentabr uchun hisob-varaq tayyor",
    pay: "Maosh",
    attendance: "Davomat",
    documents: "Hujjatlar",
    expenses: "Xarajatlar",
    days: "22 kundan 21 kun",
    amount: "Summa",
    category: "Turkum",
    what: "Nimaga sarflandi?",
    whatPlaceholder: "Masalan: yetkazib beruvchiga taksi",
    paidFrom: "Nimadan to‘landi",
    mine: "O‘z pulimdan",
    company: "Kompaniya naqd pulidan",
    hint: "Hisobchiga chek rasmi yetarli.",
    tooBig: "Bu 5 000 000 so‘mlik chegaradan ko‘p.",
    taxi: "Taksi",
    supplies: "Sarf materiallari",
    food: "Ovqat",
    repairs: "Ta’mirlash",
    drawer: "Kassadagi naqd pul",
    expected: "Jami summaga qaramay sanang",
    emptyTitle: "Bugunga hech narsa yo‘q. Dam oling",
    emptyBody: "Rahbaringizdan yangi vazifalar shu yerda va botda chiqadi.",
    emptyAction: "Shaxsiy vazifa qo‘shish",
    onTime: "bu oy o‘z vaqtida",
    sales: "bugungi savdo",
    lateTasks: "kechikkan vazifa",
    up: "seshanbaga nisbatan +12%",
    down: "o‘tgan haftadan 2 ta ko‘p",
    receipt: "Chek",
    sheetKicker: "Yangi xarajat",
    sheetTitle: "Yetkazib beruvchiga taksi",
    send: "Yuborish",
    later: "Qoralama",
    project: "Saytni qayta ishga tushirish",
    week: "Hafta",
    month: "Oy",
    year: "Yil",
    toastPlain: "So‘rov yuborildi. Javob botga keladi.",
    toastSuccess: "Belgilandingiz. Smenangiz xayrli o‘tsin!",
    toastError: "Aloqa yo‘q. Qoralama saqlandi.",
    toastUndo: "Vazifa bajarildi",
  },
} satisfies Record<Lang, Record<string, string>>;

type Demo = (typeof DEMO)["en"];

function Section({ id, title, show, children }: { id: string; title: string; show: string | null; children: ReactNode }) {
  if (show && show !== id) return null;
  return (
    <section className="kitchen-section" id={id}>
      <SectionHead>{title}</SectionHead>
      {children}
    </section>
  );
}

export function Kitchen({ section }: { section: string | null }) {
  const { lang, t } = useI18n();
  const d: Demo = DEMO[lang];
  const toast = useToast();
  const [period, setPeriod] = useState<"week" | "month" | "year">("week");
  const [category, setCategory] = useState<string | null>("taxi");
  const [method, setMethod] = useState<string | null>("cash");
  const [amount, setAmount] = useState("185000");
  const [bigAmount, setBigAmount] = useState("7500000");
  const [pad, setPad] = useState("1250000");
  const [notes, setNotes] = useState<NoteCounts>({ "200000": 12, "100000": 7, "50000": 3, "5000": 4 });
  const [count, setCount] = useState(3);
  const [photo, setPhoto] = useState<File | null>(null);
  const [slide, setSlide] = useState<SlideState>("idle");
  const [sheet, setSheet] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshed, setRefreshed] = useState(0);
  const tooBig = compareMoney(amountFromTyping(bigAmount) ?? "0", "5000000") > 0;

  return (
    <div className="kitchen">
      <PageHeader kicker="Daybook · src/ui" title="Kitchen" subtitle={`${lang.toUpperCase()} · ${document.documentElement.dataset.theme}`} />

      <Section id="hero" title="Home hero and cards" show={section}>
        <Card tone="accent" padding="lg">
          <CardTitle action={<Badge tone="accent" icon={MapPin} size="small">120 m</Badge>}>{d.shift}</CardTitle>
          <SlideToConfirm
            label={d.slide}
            doneLabel={d.checkedIn}
            state={slide}
            onConfirm={() => {
              setSlide("loading");
              window.setTimeout(() => setSlide("done"), 900);
            }}
          />
        </Card>
        <SlideToConfirm label={d.slide} doneLabel={d.checkedIn} state="done" tone="sage" onConfirm={() => undefined} />
        <Banner size="lg" tone="accent" icon={FileSignature} title={d.sign} body={d.signBody} onClick={() => undefined} />
        <Banner size="lg" tone="sage" icon={HandCoins} title={d.handover} body={d.handoverBody} onClick={() => undefined} />
        <Banner icon={Receipt} title={d.late} chevron onClick={() => undefined} />
        <CardButton layout="row" onClick={() => undefined}>
          <ProgressRing value={3} total={8} />
          <span className="row-main">
            <span className="row-title">{d.earned}</span>
            <MoneyText amount="3480000.00" size="lg" />
          </span>
        </CardButton>
      </Section>

      <Section id="buttons" title="Buttons, badges, chips" show={section}>
        <Button variant="primary" size="lg" block icon={CalendarCheck} haptic="success">
          {d.slide}
        </Button>
        <div className="kitchen-row">
          <Button variant="primary">{d.send}</Button>
          <Button>{d.later}</Button>
          <Button variant="ghost">{d.emptyAction}</Button>
        </div>
        <div className="kitchen-row">
          <Button variant="primary" loading={loading} onClick={() => setLoading(true)}>
            {d.send}
          </Button>
          <IconButton icon={SendHorizontal} label={d.send} variant="primary" />
          <IconButton icon={Plus} label={d.emptyAction} />
          <IconButton icon={PenLine} label={d.later} size={40} />
        </div>
        <div className="kitchen-row">
          <Badge tone="sage">Approved</Badge>
          <Badge tone="accent" icon={Clock3}>
            Late 25 min
          </Badge>
          <Badge>Waiting</Badge>
          <Badge size="small" tone="sage">
            ON TRACK
          </Badge>
          <CountBadge count={3} />
          <CountBadge count={128} />
          <Dot />
          <Dot tone="sage" pulse />
        </div>
        <ChipGroup
          label={d.category}
          value={category}
          onChange={setCategory}
          allowNone
          scroll
          options={[
            { value: "taxi", label: d.taxi, icon: Car },
            { value: "supplies", label: d.supplies, icon: Package },
            { value: "food", label: d.food, icon: UtensilsCrossed },
            { value: "repairs", label: d.repairs, icon: Wrench },
            { value: "shop", label: "Korzinka", icon: ShoppingBasket },
          ]}
        />
        <ChipGroup
          value={method}
          onChange={setMethod}
          options={[
            { value: "cash", label: "Naqd / Cash", icon: Banknote },
            { value: "card", label: "Uzcard" },
            { value: "click", label: "Click" },
            { value: "payme", label: "Payme" },
          ]}
        />
        <Segmented
          value={period}
          onChange={setPeriod}
          options={[
            { value: "week", label: d.week },
            { value: "month", label: d.month, count: 4 },
            { value: "year", label: d.year },
          ]}
        />
      </Section>

      <Section id="stats" title="Stats and progress" show={section}>
        <StatGrid>
          <Stat value="93%" label={d.onTime} trend={{ direction: "up", text: "+4%", good: true }} />
          <Stat value={<MoneyText amount="12500000.00" compact size="hero" />} label={d.sales} trend={{ direction: "up", text: d.up, good: true }} />
          <Stat value="5" label={d.lateTasks} tone="accent" trend={{ direction: "up", text: d.down, good: false }} />
          <Stat value="21" label={d.days} icon={CalendarCheck} hint={d.attendance} />
        </StatGrid>
        <Card>
          <ProgressBar value={93} target={95} label={d.bonus} valueLabel="93%" caption={d.bonusCaption} />
          <ProgressBar value={136} total={120} tone="sage" label={d.budget} valueLabel={<MoneyText amount="136000000" compact />} size="sm" />
          <ProgressBar value={64} tone="sage" label={d.project} valueLabel="64%" size="sm" />
        </Card>
        <div className="kitchen-row">
          <ProgressRing value={3} total={8} />
          <ProgressRing value={45} total={60} tone="sage" />
          <ProgressRing value={93} total={100} label="93%" size={48} stroke={5} />
          <ProgressRing value={186} total={240} />
        </div>
      </Section>

      <Section id="rows" title="Rows, avatars" show={section}>
        <ListCard>
          <ListRow icon={Wallet} title={d.pay} value={<MoneyText amount="3480000.00" compact />} badge={1} onClick={() => undefined} />
          <ListRow icon={CalendarCheck} title={d.attendance} value={d.days} onClick={() => undefined} />
          <ListRow icon={FileSignature} title={d.documents} subtitle={d.signBody} badge={2} onClick={() => undefined} />
          <ListRow icon={Receipt} title={d.expenses} onClick={() => undefined} />
        </ListCard>
        <PdfLink title={d.late} subtitle="Paid 5 Oct · 2 pages" href={() => new Promise((resolve) => window.setTimeout(() => resolve("about:blank"), 600))} />
        <ListCard>
          <PdfLink variant="inset" title={d.documents} subtitle={d.signBody} href="about:blank" />
        </ListCard>
        <ListRow variant="card" icon={HandCoins} tone="sage" title={d.handover} subtitle={d.handoverBody} onClick={() => undefined} />
        <ListRow variant="card" icon={Clock3} tone="accent" title={d.late} subtitle="Late 25 min" alert value="09:25" />
        <div className="kitchen-row">
          <Avatar name="Alisher Valiyev" size="xs" />
          <Avatar name="Dilnoza Karimova" size="sm" tone="accent" />
          <Avatar name="Bekzod Mirzayev" />
          <Avatar name="Madina Saidova" size="lg" />
          <AvatarStack people={[{ name: "Ali Valiyev" }, { name: "Nigora Azimova" }, { name: "Jasur Tursunov" }, { name: "Madina S" }, { name: "Sevara T" }, { name: "Bek M" }]} />
        </div>
      </Section>

      <Section id="fields" title="Fields and money" show={section}>
        <Field label={d.amount} hint={d.hint}>
          <MoneyInput value={amount} onChange={setAmount} />
        </Field>
        <Field label={d.amount} error={tooBig ? d.tooBig : undefined}>
          <MoneyInput value={bigAmount} onChange={setBigAmount} size="lg" />
        </Field>
        <Field label={d.what} optional>
          <Input placeholder={d.whatPlaceholder} />
        </Field>
        <Field label={d.paidFrom}>
          <Select defaultValue="mine">
            <option value="mine">{d.mine}</option>
            <option value="company">{d.company}</option>
          </Select>
        </Field>
        <Field label={d.receipt}>
          <PhotoInput value={photo} onChange={setPhoto} capture="environment" />
        </Field>
        <Field label={d.what}>
          <Textarea placeholder={d.whatPlaceholder} />
        </Field>
        <Card padding="sm">
          <MoneyText amount="12500000.00" size="hero" />
          <MoneyText amount="1250.50" currency="USD" size="hero" />
          <div className="kitchen-row">
            <MoneyText amount="300000" sign="always" tone="auto" />
            <MoneyText amount="-150000.00" tone="auto" />
            <MoneyText amount="1250000.75" />
            <MoneyText amount="99.5" currency="USD" />
            <MoneyText amount="2340000000" compact />
          </div>
        </Card>
      </Section>

      <Section id="pad" title="Number pad, notes, stepper" show={section}>
        <Card padding="lg">
          <NumberPad value={pad} onChange={setPad} label={d.drawer} hint={d.expected} />
        </Card>
        <DenominationCounter counts={notes} onChange={setNotes} />
        <div className="kitchen-row">
          <Stepper value={count} onChange={setCount} label={d.attendance} />
          <Stepper value={0} onChange={() => undefined} size="sm" />
        </div>
      </Section>

      <Section id="states" title="Empty, loading, toasts, sheet, bottom bar" show={section}>
        <Card>
          <EmptyState title={d.emptyTitle} body={d.emptyBody} action={{ label: d.emptyAction, onClick: () => undefined, icon: Plus }} />
        </Card>
        <Card>
          <EmptyState compact tone="sage" icon={Receipt} title={d.emptyTitle} />
        </Card>
        <ScreenSkeleton variant="payslip" rows={4} />
        <SkeletonText lines={3} />
        <div className="kitchen-row">
          <Button onClick={() => toast(d.toastPlain)}>Toast</Button>
          <Button onClick={() => toast(d.toastSuccess, { tone: "success" })}>Success</Button>
          <Button onClick={() => toast(d.toastError, { tone: "error" })}>Error</Button>
          <Button onClick={() => toast(d.toastUndo, { action: { label: t("ui.toast.undo"), onPress: () => undefined } })}>Undo</Button>
          <Button variant="primary" onClick={() => setSheet(true)}>
            Sheet
          </Button>
        </div>
        <div className="kitchen-stage kitchen-stage--tall">
          <PullToRefresh className="kitchen-ptr" onRefresh={() => new Promise((resolve) => window.setTimeout(() => resolve(setRefreshed((n) => n + 1)), 800))}>
            <ListRow variant="card" icon={Clock3} title={`Pull down · ${refreshed}`} subtitle={d.emptyBody} />
            <ListRow variant="card" icon={Receipt} title={d.expenses} />
            <ListRow variant="card" icon={Wallet} title={d.pay} />
          </PullToRefresh>
        </div>
        <div className="kitchen-stage">
          <BottomBar primary={{ text: d.send, onClick: () => undefined, icon: SendHorizontal }} secondary={{ text: d.later, onClick: () => undefined }} />
        </div>
      </Section>

      <div className="kitchen-overlay">
        {sheet && (
          <Sheet onClose={() => setSheet(false)}>
            <SheetTitle kicker={d.sheetKicker}>{d.sheetTitle}</SheetTitle>
            <Field label={d.amount}>
              <MoneyInput value={amount} onChange={setAmount} size="lg" />
            </Field>
            <ChipGroup
              value={category}
              onChange={setCategory}
              scroll
              options={[
                { value: "taxi", label: d.taxi, icon: Car },
                { value: "supplies", label: d.supplies, icon: Package },
                { value: "food", label: d.food, icon: UtensilsCrossed },
              ]}
            />
            <Button variant="primary" size="lg" block onClick={() => setSheet(false)}>
              {d.send}
            </Button>
          </Sheet>
        )}
      </div>
    </div>
  );
}
