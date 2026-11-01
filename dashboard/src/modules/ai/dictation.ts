/**
 * Opens the dictate dialog from anywhere (New task's "Dictate" and "Smart add", the Agents page,
 * the palette). The dialog itself lives in the module's shell host (`shell.panel`), so closing
 * the New task dialog that asked for it doesn't take it down too.
 */
import { reactive } from "vue";

export type DictationMode = "voice" | "text";

export const dictation = reactive({
  open: false,
  mode: "voice" as DictationMode,
  /** Text to start Smart add with (what was already typed as a title). */
  text: "",
  /** Bumped on every open, so a second open starts the dialog afresh. */
  session: 0,
});

export function openDictation(mode: DictationMode, options: { text?: string } = {}): void {
  dictation.mode = mode;
  dictation.text = options.text?.trim() ?? "";
  dictation.session += 1;
  dictation.open = true;
}

export function closeDictation(): void {
  dictation.open = false;
}
