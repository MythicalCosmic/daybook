/**
 * Runs before every test file (vite.config.ts `test.setupFiles`). The app loads the shell's
 * dictionaries one language at a time (src/i18n/index.ts); tests get all three up front, so
 * `setLanguage("ru")` switches at once, as it does in the app once a language has loaded.
 */
import { addShellMessages } from "@/i18n";
import en from "@/i18n/en.json";
import ru from "@/i18n/ru.json";
import uz from "@/i18n/uz.json";

addShellMessages("en", en);
addShellMessages("ru", ru);
addShellMessages("uz", uz);
