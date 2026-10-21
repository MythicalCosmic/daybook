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
| `widgets` | Overview widgets `{ id: "<id>.x", span, order, kind, component }` (props `companyId`, `range`, `compare`) |
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
`KpiStrip`/`KpiCard` (`phone="grid"` or `"compact"` keeps two per row on phones), `ChartCard` around
`LineChart`, `AreaChart`, `BarChart` (`y-max="100"` for percentages, `integer` for counts, a
`target` named in the legend), `DonutChart`, `HeatmapChart`, `SparkLine`, `BulletBar`,
`MoneyText`, `MoneyCell`, `DeltaBadge`. Decisions:
`ApproveRejectButtons`, `ConfirmDialog` / `useConfirm()`, `ExportButton`.

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
(fetched before the first paint) and the Overview page. At the end of Wave 1 (20 modules):

| | gzip |
|---|---|
| Initial JS (entry + static imports) | 160.5 KB |
| + the largest shell dictionary (ru; uz 5.2, en 4.8) | 6.0 KB |
| + the Overview page | 8.8 KB |
| **Shell + Overview** | **175.3 KB** of 180 |

**Every module's `index.ts` is in the first load**, so registries are where the budget goes: today
a registry costs 0.5 KB (groups) to 1.3 KB (projects) to 2.6 KB (finance), measured by building
without it. Waves 2–3 add about ten modules, so:

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
  paint, every visible module's right after (about 20 small requests, ~65 KB gzipped for the
  largest language). The other two languages load only when the person switches.

How the build keeps it small (`vite.config.ts`): framework code is one `vendor` chunk; everything
else the first load needs (shell, every registry, the icons and reka-ui pieces they use) is
grouped into the entry chunk by Rolldown's `$initial` tag, instead of ~60 tiny shared chunks whose
names would repeat in every preload list. That alone took Wave 1 from 191.8 to 174 KB.

Known cost left: reka-ui depends on `@vueuse/core` 14 while the console uses 15, so two copies sit
in the first load (about 4 KB gzipped); aligning the versions would remove one.

vue-i18n runs without its message compiler (`__INTLIFY_DROP_MESSAGE_COMPILER__`);
`src/i18n/compile.ts` compiles messages instead. It supports `{name}`, `{0}`, `{'literal'}` and
plural forms separated by ` | ` (`t(key, { n }, n)`); linked messages (`@:key`) are not
supported, and `@` or `$` are plain text. In development vue-i18n logs once that a custom message
compiler is in use; that is expected.
