<script setup lang="ts">
/**
 * The drawer's comment box with @mentions (contract 5): typing "@" lists the task's people (who
 * does it, who gave it, the branch team); picking one writes "@Name" and the comment then tells
 * them in Telegram as well. ↑/↓ move, Enter or Tab picks, Esc closes; ⌘/Ctrl+Enter sends. The
 * field points at the list and its active person (`aria-controls`, `aria-activedescendant`), so a
 * screen reader follows the arrows.
 */
import { AtSign, Send } from "@lucide/vue";
import { computed, nextTick, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import IconButton from "@/components/IconButton.vue";
import TextArea from "@/components/TextArea.vue";
import UserAvatar from "@/components/UserAvatar.vue";

export interface MentionPerson {
  id: number;
  name: string;
  photo_url: string | null;
  subtitle?: string | null;
}

const text = defineModel<string>({ default: "" });
const props = withDefaults(defineProps<{ people: MentionPerson[]; sending?: boolean; placeholder?: string }>(), { sending: false, placeholder: undefined });
const emit = defineEmits<{ send: [mentions: number[]] }>();

const { t } = useI18n();
const area = ref<InstanceType<typeof TextArea> | null>(null);
/** People picked from the list; sent only while their "@Name" is still in the text. */
const picked = ref<Map<number, string>>(new Map());
const query = ref<string | null>(null);
const active = ref(0);
const listId = useId();
const optionId = (index: number) => `${listId}-${index}`;

const fold = (value: string) => value.toLocaleLowerCase().replace(/[‘’ʻʼ'`]/g, "");
const matches = computed(() => {
  if (query.value === null) return [];
  const needle = fold(query.value);
  return props.people.filter((person) => fold(person.name).split(/\s+/).some((word) => word.startsWith(needle)) || fold(person.name).startsWith(needle)).slice(0, 6);
});
const open = computed(() => query.value !== null && matches.value.length > 0);

function textarea(): HTMLTextAreaElement | null {
  return (area.value?.el as HTMLTextAreaElement | null | undefined) ?? null;
}

/** "@ali" right before the caret opens the list for "ali". Read from the field itself: this runs on
 * the same input event as v-model, maybe before the model has the new text. */
function readQuery(): void {
  const el = textarea();
  const value = el?.value ?? text.value;
  const before = value.slice(0, el?.selectionStart ?? value.length);
  const match = /(?:^|\s)@([^\s@]{0,30})$/u.exec(before);
  query.value = match ? match[1]! : null;
  active.value = 0;
}

async function pick(person: MentionPerson): Promise<void> {
  const el = textarea();
  const caret = el?.selectionStart ?? text.value.length;
  const before = text.value.slice(0, caret).replace(/@([^\s@]{0,30})$/u, `@${person.name} `);
  text.value = before + text.value.slice(caret);
  picked.value = new Map(picked.value).set(person.id, person.name);
  query.value = null;
  await nextTick();
  el?.focus();
  el?.setSelectionRange(before.length, before.length);
}

/** The "@" button: start a mention where the caret is. */
async function startMention(): Promise<void> {
  const el = textarea();
  const caret = el?.selectionStart ?? text.value.length;
  const glue = caret > 0 && !/\s$/.test(text.value.slice(0, caret)) ? " @" : "@";
  text.value = text.value.slice(0, caret) + glue + text.value.slice(caret);
  await nextTick();
  el?.focus();
  el?.setSelectionRange(caret + glue.length, caret + glue.length);
  readQuery();
}

function onKeydown(event: KeyboardEvent): void {
  if (!open.value) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    active.value = (active.value + step + matches.value.length) % matches.value.length;
  } else if ((event.key === "Enter" && !event.metaKey && !event.ctrlKey) || event.key === "Tab") {
    event.preventDefault();
    void pick(matches.value[active.value]!);
  } else if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    query.value = null;
  }
}

function send(): void {
  if (!text.value.trim() || props.sending) return;
  const mentions = [...picked.value].filter(([, name]) => text.value.includes(`@${name}`)).map(([id]) => id);
  emit("send", mentions);
}

/** After a send the parent empties the text: forget the picks too. */
function clear(): void {
  picked.value = new Map();
  query.value = null;
}

defineExpose({ clear, focus: () => textarea()?.focus() });
</script>

<template>
  <form class="relative flex items-end gap-2" @submit.prevent="send">
    <!-- The field keeps the focus: the options are picked with the keys or a press, never tabbed to. -->
    <ul
      v-if="open"
      :id="listId"
      class="absolute bottom-full left-0 z-10 mb-1.5 flex max-h-64 w-[min(100%,320px)] flex-col overflow-y-auto rounded-[10px] border border-line bg-surface p-1 shadow-raised"
      role="listbox"
      :aria-label="t('tasks.comments.mention')"
      data-testid="mention-list"
    >
      <li
        v-for="(person, index) in matches"
        :id="optionId(index)"
        :key="person.id"
        role="option"
        :aria-selected="index === active"
        :class="['flex w-full min-w-0 cursor-pointer items-center gap-2 rounded-[7px] px-2 py-1.5 text-left text-sm', index === active ? 'bg-highlight' : 'hover:bg-highlight']"
        @mousedown.prevent="pick(person)"
        @mouseenter="active = index"
      >
        <UserAvatar :name="person.name" :src="person.photo_url" :size="22" />
        <span class="min-w-0 flex-1 truncate font-medium text-fg">{{ person.name }}</span>
        <span v-if="person.subtitle" class="max-w-[45%] shrink-0 truncate text-xs text-muted">{{ person.subtitle }}</span>
      </li>
    </ul>
    <TextArea
      ref="area"
      v-model="text"
      :rows="1"
      :max-rows="6"
      :placeholder="placeholder ?? t('tasks.comments.placeholder')"
      class="flex-1"
      data-testid="comment-text"
      aria-autocomplete="list"
      :aria-controls="open ? listId : undefined"
      :aria-activedescendant="open ? optionId(active) : undefined"
      @input="readQuery"
      @click="readQuery"
      @keydown="onKeydown"
      @blur="query = null"
      @submit="send"
    />
    <IconButton v-if="people.length" :icon="AtSign" :label="t('tasks.comments.mention')" @click="startMention" />
    <IconButton :icon="Send" :label="t('tasks.comments.send')" variant="primary" type="submit" :loading="sending" :disabled="!text.trim()" />
  </form>
</template>
