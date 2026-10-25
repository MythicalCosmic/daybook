/**
 * Runs before every test file (vite.config.ts `test.setupFiles`). The app loads the shell's
 * dictionaries one language at a time (src/i18n/index.ts); tests get all three up front, so
 * `setLanguage("ru")` switches at once, as it does in the app once a language has loaded.
 *
 * DropdownMenu's menu loads lazily too (components/lazyPart.ts): the app fetches it once the first
 * page has painted, and tests start with it loaded, as every page after the first one does. The
 * lazy path itself is tested in components/__tests__/lazyMenus.test.ts.
 */
import { menuPanel } from "@/components/lazyPart";
import { addShellMessages, i18n } from "@/i18n";
import en from "@/i18n/en.json";
import ru from "@/i18n/ru.json";
import uz from "@/i18n/uz.json";

addShellMessages("en", en);
addShellMessages("ru", ru);
addShellMessages("uz", uz);
// The app speaks Uzbek until it knows better (src/i18n/index.ts initialLanguage); the tests read
// English unless they switch, as they did when jsdom's English browser picked the language.
i18n.global.locale.value = "en";

await menuPanel.load();
