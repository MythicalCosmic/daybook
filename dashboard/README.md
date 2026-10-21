# Daybook Console (owner dashboard)

Vue 3 + Vite + TypeScript, served by Django at `/dashboard/`. The plan is `docs/PLAN-OWNER.md` §6 (and §13).

```bash
cd dashboard
npm ci
VITE_MOCK=1 DEV_PORT=28274 npx vite        # shell + modules on demo data, no backend needed
DEV_PORT=28274 API_PORT=28000 npx vite     # against a running Django (dev login at /dashboard/dev/login)
npx vue-tsc --noEmit -p tsconfig.app.json  # typecheck
npx vitest run                             # tests
npm run build                              # typecheck + production build (dist/)
```

Every component, live, in both themes and densities: **`/dashboard/_kitchen`** (dev server only;
`?theme=dark|split&density=compact&lang=ru&only=table`). Look there before building anything.

## How to build a module

A module is one folder, `src/modules/<id>/`. The shell discovers it, builds its routes, puts it in
the sidebar, palette and shortcuts, and loads its translations. **Copy `src/modules/inbox/`**: it is
the reference and uses the whole contract.

```
src/modules/<id>/
  index.ts          export default defineModule({ … })      ← kept tiny: it is in the first bundle
  routes.ts         children of /c/:companyId, lazy pages, meta { title, perm, feature }
  api.ts            typed endpoint functions + vue-query helpers
  types.ts          response shapes, written by hand from the serializers (money and dates are strings)
  pages/            one component per route
  components/       the module's own pieces (promoted to src/components at integration if reused)
  widgets/          Overview widgets (lazy)
  i18n/uz.json ru.json en.json   flat keys, all starting with "<id>."
  __tests__/
```

1. **Find your entry in `src/core/catalog.ts`.** It fixes `id`, `group`, `order`, `perm`,
   `feature`, `hotkey`, the badge counter and the page paths. `registry.test.ts` fails if your
   module drifts from it (ask W0 to change the catalog instead).
2. **`index.ts`**: `defineModule({ id, group, order, icon, title: "<id>.title", routes, messages })`
   with `` messages: (language) => import(`./i18n/${language}.json`) `` (one dictionary per language,
   loaded only when that language is shown), plus what you need from the table below. Import only
   light things here; pages, widgets and the API load lazily (`() => import(...)`, `defineAsyncComponent`).
3. **`routes.ts`**: paths are relative (`"finance/accounts"`), names start with `"<id>."`, every
   route has `meta.title` (breadcrumb and tab title) and `meta.perm` / `meta.feature` when the page
   needs more than the module does. `meta.layout: "full"` for boards and maps that scroll themselves.
4. **`api.ts`**: plain functions `listX(companyId, params): Promise<Page<X>>` over `@/api/http`
   (`http.get(ownerPath(cid, "finance/accounts/"), params)`), and `useX()` helpers with keys from
   `qk(companyId, "<id>", resource, params)`. Mutations update the cache optimistically and roll
   back on error (see `useQueueDecision` in the inbox). Errors with `{detail}` toast by themselves;
   field errors land in `useForm`.
5. **State in the URL**: filters, sort, tab, drawer and period go in the query string —
   `useRouteState`, `useUrlFilters(defs)` with `FilterBar`, `useRangeState` with `DateRangePicker`,
   `useDataTable({ url: true })`, `UiDrawer query-key="x"`.
6. **Strings**: every visible string in uz, ru and en (no empty values). Uzbek writes o‘ and g‘
   with U+2018 and the apostrophe with U+2019 (`i18n-parity.test.ts` checks). Shared words
   (Save, Cancel, Export…) are already in `common.*`.

### Registry fields (`src/core/modules.ts`)

| Field | What it does |
|---|---|
| `id`, `group`, `order`, `icon`, `title` | Sidebar placement (from the catalog) and the module's name key |
| `perm`, `feature` | Hide the module without the permission (any of a list) or with the company switch off |
| `routes` | Pages under `/c/:companyId` |
| `nav` | Sidebar sub-items `{ key, title, to, perm?, badge? }`; default one item; `[]` hides the module |
| `hotkey` | `g` + this key opens the module |
| `badge` | `counter("finance.claims")` — a pulse counter on the sidebar row |
| `invalidates` | Pulse keys; when one moves (its version or its counter), every query under `[companyId, "<id>"]` refetches. An entry may name a whole app: `"sales"` covers `"sales.shifts"` |
| `commands` | Palette actions `(ctx) => Command[]` (built with `ctx.t`, `ctx.go`, `ctx.can`) |
| `searchResults` | Renderers for your search hit types (prop `hit`) |
| `widgets` | Overview widgets `{ id: "<id>.x", span, order, kind, component }` (props `companyId`, `range`, `compare`); see "The Overview" below for how `kind` and `span` place them |
| `inbox` | Renderers for your notification kinds (prop `notification`) in the drawer and the inbox page |
| `settings` | Settings panels `{ id, title, perm, component }` |
| `personTabs` | Person 360 tabs (prop `memberId`) |
| `extensions` | Components for other modules' slots (below) |
| `deepLinks` | Telegram `startapp` prefixes → route (`shift: (id) => "sales/shifts/" + id`) |
| `rootRoutes` | Signed-in pages outside a company (the portfolio) |
| `publicRoutes` | The auth module only |
| `messages` | `` (language) => import(`./i18n/${language}.json`) ``: one language's dictionary. The shell loads the language shown for every visible module, a page waits for its module's, and a language switch loads the new one first. The palette matches titles in all three languages through `virtual:module-titles` (every key of your namespace written in `index.ts`, built by `scripts/moduleTitles.mjs`), so keep sidebar and palette titles as string keys there |

### W0 modules and the API they read

- **inbox** (reference): `queue/counts/` + `queue/` (fetched together as `fetchQueue` from
  `@/api/shell`: `{ total, kinds, items }`), `inbox/`, `inbox/unread-count/`, `inbox/read/`,
  `inbox/{id}/archive/`, `inbox/{id}/actions/{key}/` (answers `{ message, notification }`).
- **overview** (placeholder until N): serves `/c/:id`, renders every registered widget in
  `order`, hosts `overview.hero`, and has two widgets of its own over `branches/today/` and
  `stream/`.
- **exports**: `exports/`, `exports/kinds/`, `POST exports/` (202 `{ id }`), `exports/{id}/`.
  Tables start exports with `ExportButton` (`kind` = the backend exporter key).
- **auth** (placeholder until A): `/login` and, in development, `/dev/login`.

Pulse keys the W0 backend registers: `console.queue` (Needs you total), `inbox.unread`,
`exports.exports`, `console.saved_views` (constants in `@/core/pulse`). Module keys are
app-prefixed (`"sales.shifts"`), like every backend registry key. Server links (`url` on
notifications, queue items, search hits and stream rows) go through `companyUrl()` from
`@/lib/links`, which accepts `"/c/12/x"` and relative paths and never leaves the app.

### Extension points

The host renders `<ExtensionSlot name="…" :context="…" />`; other modules fill it through
`extensions`. Points: `shell.panel`, `shell.topbar.end`, `shell.nav.top`, `shell.company.create`,
`overview.hero`, `tasks.toolbar`, `tasks.drawer.actions`, `people.profile.actions`,
`comms.composer.tools`, `finance.quickadd.receipt`, `finance.transactions.toolbar`,
`sales.shift.detail`, `payroll.run.toolbar`. A component that throws only hides itself. The host's
attributes go on the slot's wrapper (`class="px-3 pt-2 empty:hidden"`: no gap when nothing renders);
with `as="none"` each extension's root gets them.

### Boundaries

Files in `modules/<x>/` import only `@/components`, `@/lib`, `@/api`, `@/core`, `@/stores`,
`@/i18n`, npm packages and their own folder — never another module, the shell, `@/app` or
`@/dev` (`boundaries.test.ts`). Cross-module needs go through the registry or plain links.
`src/components` is W0's: don't edit it in a package; build your own piece in your module and
propose it in your hand-off.

### Components you will reach for

Pages: `PageHeader` (tabs, actions), `PageSection`, `ResponsiveGrid`, `SplitView`,
`StickyActionBar`, `WizardSteps`; a page about one record names it in the breadcrumb and the tab
title with `usePageTitle(() => project.value?.name)` (`@/lib/usePageTitle`). Lists: `DataTable` +
`useDataTable`, `FilterBar` + `useUrlFilters`, `SavedViewsTabs` + `useSavedViews`,
`BulkActionBar`, `KanbanBoard`, `GanttTimeline`, `CalendarMonth`/`CalendarWeek`, `TreeList`,
`TimelineList`, `AuditTrail` (`field-order` when the details have an order to read in), `MapView`
(branch circles and check-in points, or `picker` to choose a place).
Forms: `FormField` around `TextInput`, `MoneyInput` (string values, never floats), `NumberInput`,
`SelectBox`, `ComboBox`, `MultiSelect`, `PersonPicker`, `PositionPicker`, `BranchPicker`,
`DatePicker`, `DateRangePicker`, `TimePicker`, `WeekdayPicker`, `FileDrop`, `CheckBox`,
`ToggleSwitch`, `RadioCards`, `SegmentedControl`, with `useForm(zodSchema)`. Numbers:
`KpiStrip`/`KpiCard` (`phone="grid"` or `"compact"` keeps two per row on phones; `error` + `retry`
keep the tile and its label when the number fails), `ChartCard` around
`LineChart`, `AreaChart`, `BarChart` (`y-max="100"` for percentages, `integer` for counts, a
`target` named in the legend, `partial` for a last point still in progress; `icon` and `to` on the
Overview), `DonutChart`, `HeatmapChart`, `SparkLine` (steps over missing days; a steady series
runs across the middle), `BulletBar`, `MoneyText` ("1,250,000 UZS": the amount first in every
language), `MoneyCell`, `DeltaBadge`. Overview cards: `WidgetCard`.
Decisions: `ApproveRejectButtons`, `ConfirmDialog` / `useConfirm()`, `ExportButton`.
Overlays: `DropdownMenu` (its menu loads on first use or when the browser is idle, see "Budgets";
same API), `UiTooltip` (its own small engine: no provider, no positioning library), `UiPopover`,
`UiDialog`, `UiDrawer`, `BottomSheet`. Text cut short with `truncate` takes `v-truncate-title`
(`@/components/truncateTitle`) to show whole on hover; `DataTable`'s plain cells already do.

### The Overview

The page arranges every registered widget into one cockpit (`modules/overview/layout.ts`):

- **Lead**: cards registered before the first KPI (Get started, Branches today), full width.
- **KPI band**: every `kind: "kpi"` widget, four to a row (two when the page is narrower than
  56rem, phones included). A short last row borrows the first `span: 1` cards (Team, Off today).
- **Cards**: `card` and `chart` widgets packed into rows of four columns in their order; a later
  card fills an earlier gap and a row that still isn't full widens its cards. Neighbours from one
  module that fit in a row together stay together (Projects at risk beside My projects), so a short
  list never sits beside a tall chart. A row is as tall as its tallest card, **at most 22rem**
  (26rem when stacked): build cards whose body scrolls.
- People can drag and hide widgets ("Customize"); the layout is their `overview` SavedView.

So a widget: a KPI tile uses `KpiCard` (or its header with the `kpi-label` utility, the
`kpi-value` number and an `@container` root, like `finance/widgets/CashNowWidget.vue`); a list or
free card uses `WidgetCard` (icon, title, count, `to` for "View all", a body that scrolls with an
edge fade); a chart uses `ChartCard` with `icon` and `to`. Root `h-full`, fail inside your own
frame, use container queries (`@md:`) rather than viewport breakpoints for the inside, and render
nothing (not an empty card) when there is nothing to show, as Get started does once it is done.

- KPI labels take two lines rather than "Выполнено с…" (`kpi-label`); in a tile two to a row on a
  phone both lines are kept, so the numbers of a row stay level. Say a number once: "9" over "of 10
  on shift", not "9 / 10" over it as well.
- A `KpiCard` with `spark` in a row made tall by richer tiles draws the trend across the free
  height, with `spark-labels` (its first and last day) under it, like Cash now; in a short tile it
  sits beside the delta. The trend ends on the day the number is about.
- Card headers (`WidgetCard`, `ChartCard`) show only the arrow of "View all" below 24rem, so a long
  Russian or Uzbek title stays whole on a phone.

- Loading: `useWidgetSkeleton(() => query.isPending.value)` shows your skeleton at once (the cell
  showed a placeholder of the same shape while your code loaded), not after the page's 150 ms.
- Today is still in progress: a trend that ends today passes `partial` to `LineChart` (dashed into a
  hollow point, "so far" in the tooltip), and a sparkline leaves today out.
- Say what you count: the tasks tiles count one-off work (`routines=without`) and say so; routine
  work has its own tile ("Routines today", `overview.routines`, from `routines/day/`).

Money is a decimal string end to end (`lib/money.ts`, `lib/decimal.ts`); dates are company-local
(`lib/dates.ts`, `useFormat()`); never `parseFloat` a sum.

### Testing

- `vitest` on jsdom. Stub `fetch` and call your `api.ts` functions (URLs, params, bodies).
- Mount pages with `mountWithProviders(Page, { plugins: (await testApp(path)).plugins })` from
  `@/test/plugins` (pinia with a signed-in owner, a memory router, i18n, vue-query).
- Import `"@/core/modules"` first in a test that imports your module's `index.ts` (the registry is
  what loads modules in the app).
- Test the two or three most complex behaviours of your page (optimistic updates and rollback,
  URL state, permission-gated actions), like `modules/inbox/__tests__/inbox.test.ts`.
- The shared tests run on every module: `registry.test.ts` (contract, catalog, unique ids, nav
  resolves), `boundaries.test.ts`, `i18n-parity.test.ts`.

### Mock mode

`VITE_MOCK=1` answers the API from `src/dev/mock.ts` and `src/dev/mockData.ts` (dev server only,
never in a build) and shows a placeholder for every catalog module that hasn't landed; your real
module replaces its placeholder automatically. The mock answers in the W0 serializers' shapes and
covers the shell's endpoints, the inbox, branches today, the stream, exports, audit history,
people, positions and saved views. For your own endpoints, work against
the real backend (`API_PORT`) or ask W0 for mock data.

### Budgets (plan §6.5)

Initial JS (shell + Overview) ≤ 180 KB gzipped, each module chunk ≤ 80 KB. Heavy libraries load
lazily on their own: charts (ECharts), `MarkdownView` (markdown-it + DOMPurify), `QrCode`, Tiptap,
Leaflet (`MapView`), the drag library behind `WidgetGrid`'s Customize.

**Measure it** after `npm run build` with `node scripts/budget.mjs` (exits 1 when over). It counts
the entry chunk and everything it imports statically, plus the shell dictionary of one language
(fetched before the first paint) and the Overview page. After the Wave 1 visual pass (20 modules,
with w1v/work's routine pages):

| | gzip |
|---|---|
| Initial JS (entry + static imports) | 136.5 KB |
| + the largest shell dictionary (ru; uz 5.2, en 4.9) | 6.1 KB |
| + the Overview page (cockpit layout, Customize) | 11.7 KB |
| **Shell + Overview** | **154.3 KB** of 180 (25.7 KB left) |

Menus and tooltips are not in it. reka-ui's menu and tooltip and their positioning library
(floating-ui) were 24.5 KB of the first load, and no first paint needs them:

- `UiTooltip` has its own small engine (`components/tooltip.ts`): hover pause, keyboard focus,
  flipping and keeping inside the window, no provider.
- `DropdownMenu` and the company switcher load their menus (`DropdownMenuPanel.vue`,
  `shell/CompanySwitcherMenu.vue`, through `components/lazyPart.ts`) once the browser is idle after
  the first paint (AppShell), or on first use. A menu mounted before that renders its trigger as
  it is (`LazyTrigger`); using it loads the menu and opens it. Keep reka-ui popups (menus,
  popovers, selects, dialogs) out of anything the shell renders on its own: put them behind a lazy
  component, as these are, or the whole library comes back into the first load.

**Every module's `index.ts` is in the first load**, so registries are where the budget goes: a
registry costs 0.5 KB (groups) to 1.3 KB (projects) to 2.6 KB (finance), measured by building
without it. Waves 2–3 add about ten modules: **each new module may add at most 1.5 KB gzipped to
shell + Overview** (its `index.ts`, `routes.ts`, the icons they name and the preload lists of its
lazy imports; check with `scripts/budget.mjs` before and after), which keeps ten of them within
the 25.7 KB left with room for the shell. So:

- `index.ts` and `routes.ts` hold metadata only. Pages, widgets, panels, tabs, search hits, inbox
  renderers and extensions are `defineAsyncComponent(() => import(...))` / `() => import(...)`;
  never import a component, the API, a store-heavy helper or a library there.
- Each lazy import also puts its **preload list** in the first load (`__vite__mapDeps`: the chunk
  and every chunk it needs, about 40–80 bytes gzipped per import). Register what the person can
  reach; don't split one page into many lazy pieces from the registry, and prefer one widget that
  shows two numbers to two tiny widgets.
- Each distinct icon named in `index.ts` (module, nav items, commands, settings panels) is inlined
  into the first load (~0.1–0.15 KB each). Reuse the module's icon or a common one (`Plus`) for
  commands rather than a new icon per command.
- Palette commands: `ctx.t` titles and 3–5 short `keywords`, not long lists.
- Dictionaries load one language at a time (`src/i18n/index.ts`): the shell's before the first
  paint, every visible module's right after (20 small requests: 58 KB gzipped in English, 63 KB
  in Uzbek, 76 KB in Russian, where all three languages used to cost 60 requests and 196 KB). The
  other two languages load only when the person switches.

How the build keeps it small (`vite.config.ts`): framework code is one `vendor` chunk; everything
else the first load needs (shell, every registry, the icons and reka-ui pieces they use) is
grouped into the entry chunk by Rolldown's `$initial` tag, instead of ~60 tiny shared chunks whose
names would repeat in every preload list. That alone took Wave 1 from 191.8 to 174 KB.

`@vueuse/core` is pinned to the 14.x that reka-ui depends on, so one copy ships (the duplicate
cost 0.9 KB of the first load); `@vueuse/router` was never imported and is gone. Bump it together
with reka-ui.

Fonts: Figtree and Caprasimo have no Cyrillic, so `styles/fonts.css` adds Onest (body) and
Literata Black (display, declared at weight 400 like Caprasimo) for Cyrillic letters only, each
behind its `unicode-range`: Latin pages never download them (Russian pages add 15.5 KB, plus 10.8 KB
where a display heading shows; the four `@font-face` rules are 0.3 KB of everyone's CSS). Font
files are never inlined into the CSS (`assetsInlineLimit`). The mini app does the same from Google
Fonts, in a second stylesheet that doesn't block its first paint (`miniapp/index.html`).

vue-i18n runs without its message compiler (`__INTLIFY_DROP_MESSAGE_COMPILER__`);
`src/i18n/compile.ts` compiles messages instead. It supports `{name}`, `{0}`, `{'literal'}` and
plural forms separated by ` | ` (`t(key, { n }, n)`); linked messages (`@:key`) are not
supported, and `@` or `$` are plain text. In development vue-i18n logs once that a custom message
compiler is in use; that is expected.
