import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { h } from "vue";

import { describeMove, groupItems, moveCard, nextColumn, positionBetween, type KanbanColumn } from "@/components/kanban";
import KanbanBoard from "@/components/KanbanBoard.vue";
import { mountWithProviders, testApp } from "@/test/plugins";

interface Card {
  id: number;
  title: string;
  list: string;
  /** Columns the server allows this card to move to (Tasks' `actions`). */
  allowed: string[];
}

const columns: KanbanColumn[] = [
  { id: "todo", title: "To do" },
  { id: "doing", title: "In progress", wipLimit: 2 },
  { id: "review", title: "Review" },
  { id: "done", title: "Done" },
];

const cards: Card[] = [
  { id: 1, title: "Count stock", list: "todo", allowed: ["doing", "done"] },
  { id: 2, title: "Clean fridge", list: "todo", allowed: ["doing", "review", "done"] },
  { id: 3, title: "Window display", list: "doing", allowed: ["review"] },
  { id: 4, title: "Price tags", list: "doing", allowed: ["todo", "review"] },
];

const key = (card: Card) => String(card.id);
const canDrop = (card: Card, _from: string, to: string) => card.allowed.includes(to);

describe("board logic", () => {
  it("groups cards by column in the given order", () => {
    const lists = groupItems(columns, cards, (c) => c.list);
    expect(Object.keys(lists)).toEqual(["todo", "doing", "review", "done"]);
    expect(lists.todo!.map((c) => c.id)).toEqual([1, 2]);
    expect(lists.done).toEqual([]);
  });

  it("moves a card between and within columns without touching the input", () => {
    const lists = groupItems(columns, cards, (c) => c.list);
    const across = moveCard(lists, "1", "review", 0, key);
    expect(across.review!.map((c) => c.id)).toEqual([1]);
    expect(across.todo!.map((c) => c.id)).toEqual([2]);
    expect(lists.todo!.map((c) => c.id)).toEqual([1, 2]);
    const within = moveCard(lists, "4", "doing", 0, key);
    expect(within.doing!.map((c) => c.id)).toEqual([4, 3]);
  });

  it("skips columns the card may not enter", () => {
    const card = cards[0]!; // todo → doing or done only
    expect(nextColumn(columns, "todo", 1, (to) => canDrop(card, "todo", to))).toBe("doing");
    expect(nextColumn(columns, "doing", 1, (to) => canDrop(card, "todo", to))).toBe("done");
    expect(nextColumn(columns, "todo", -1, (to) => canDrop(card, "todo", to))).toBeNull();
  });

  it("describes where a card landed with its neighbours", () => {
    const lists = moveCard(groupItems(columns, cards, (c) => c.list), "2", "doing", 1, key);
    const move = describeMove(lists, "2", "todo", key)!;
    expect(move).toMatchObject({ from: "todo", to: "doing", index: 1 });
    expect(move.before?.id).toBe(3);
    expect(move.after?.id).toBe(4);
  });

  it("finds a position between neighbours", () => {
    expect(positionBetween(null, null)).toBe(1024);
    expect(positionBetween(1024, 2048)).toBe(1536);
    expect(positionBetween(null, 100)).toBe(-924);
    expect(positionBetween(100, null)).toBe(1124);
  });
});

describe("KanbanBoard", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  async function board() {
    const app = await testApp("/c/1/projects/1");
    const { inner } = mountWithProviders(KanbanBoard, {
      props: { columns, items: cards, itemKey: (c: Card) => c.id, columnOf: (c: Card) => c.list, canDrop },
      slots: { card: ({ item }: { item: Card }) => h("span", { class: "card-title" }, item.title) },
      plugins: app.plugins,
    });
    await flushPromises();
    return inner;
  }

  const cardEl = (id: number) => document.body.querySelector<HTMLElement>(`[data-card-key="${id}"]`)!;
  const press = async (el: HTMLElement, key: string) => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    await flushPromises();
  };

  it("renders columns with counts and the WIP limit", async () => {
    const wrapper = await board();
    const headers = wrapper.findAll("section header");
    expect(headers.map((h) => h.text())).toEqual(["To do2", "In progress2 / 2", "Review0", "Done0"]);
  });

  it("moves a card by keyboard to the next allowed column and emits its new place", async () => {
    const wrapper = await board();
    await press(cardEl(1), " ");
    await press(cardEl(1), "ArrowRight"); // doing
    await press(cardEl(1), "ArrowRight"); // review is refused → done
    expect(cardEl(1).closest("[data-column]")?.getAttribute("data-column")).toBe("done");
    await press(cardEl(1), " ");
    const move = wrapper.emitted("move")?.[0]?.[0] as { item: Card; from: string; to: string; index: number };
    expect(move).toMatchObject({ from: "todo", to: "done", index: 0 });
    expect(move.item).toBe(cards[0]);
  });

  it("dims refused columns while a card is picked up and cancels with Escape", async () => {
    const wrapper = await board();
    await press(cardEl(3), " "); // Window display may only go to review
    const dimmed = wrapper.findAll("section").filter((section) => section.classes().includes("opacity-45"));
    expect(dimmed.map((section) => section.attributes("aria-label"))).toEqual(["To do", "Done"]);
    await press(cardEl(3), "ArrowLeft"); // to do refused: stays
    expect(cardEl(3).closest("[data-column]")?.getAttribute("data-column")).toBe("doing");
    await press(cardEl(3), "ArrowRight");
    expect(cardEl(3).closest("[data-column]")?.getAttribute("data-column")).toBe("review");
    await press(cardEl(3), "Escape");
    expect(cardEl(3).closest("[data-column]")?.getAttribute("data-column")).toBe("doing");
    expect(wrapper.emitted("move")).toBeUndefined();
  });

  it("puts quick add right after the last card and 'No cards' at the top of an empty column", async () => {
    const app = await testApp("/c/1/projects/1");
    const { inner } = mountWithProviders(KanbanBoard, {
      props: { columns, items: cards, itemKey: (c: Card) => c.id, columnOf: (c: Card) => c.list, canDrop },
      slots: {
        card: ({ item }: { item: Card }) => h("span", { class: "card-title" }, item.title),
        "quick-add": ({ close }: { close: () => void }) => h("button", { class: "quick-form", onClick: close }, "Add it"),
      },
      plugins: app.plugins,
    });
    await flushPromises();
    const sections = inner.findAll("section");
    // A column with cards: the quick add is the list's last child, right after the last card.
    const todoList = sections[0]!.find("[data-column='todo']");
    const children = Array.from(todoList.element.children) as HTMLElement[];
    expect(children.map((el) => el.dataset.cardKey ?? (el.hasAttribute("data-kanban-add") ? "add" : "?"))).toEqual(["1", "2", "add"]);
    expect(sections[0]!.find("[data-kanban-empty]").exists()).toBe(false);
    // An empty column: "No cards" first, above the list, and the quick add opens in the list.
    const review = sections[2]!;
    const empty = review.find("[data-kanban-empty]");
    expect(empty.text()).toBe("No cards");
    expect(empty.element.compareDocumentPosition(review.find("[data-column='review']").element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await review.find("[data-kanban-add] button").trigger("click");
    expect(review.find("[data-column='review'] [data-kanban-add] .quick-form").exists()).toBe(true);
    expect(review.find("[data-kanban-empty]").exists()).toBe(false);
    expect(inner.emitted("add-open")?.[0]?.[0]).toMatchObject({ id: "review" });
    await review.find(".quick-form").trigger("click");
    expect(review.find("[data-kanban-empty]").exists()).toBe(true);
  });

  it("keeps the quick add out of the sortable cards and hides it while a card is dragged", async () => {
    const app = await testApp("/c/1/projects/1");
    const { inner } = mountWithProviders(KanbanBoard, {
      props: { columns, items: cards, itemKey: (c: Card) => c.id, columnOf: (c: Card) => c.list, canDrop },
      slots: { card: ({ item }: { item: Card }) => h("span", item.title), "quick-add": () => h("input") },
      plugins: app.plugins,
    });
    await flushPromises();
    const vm = inner.vm as unknown as { $: { setupState: { onStart: (e: { item: HTMLElement; from: HTMLElement }) => void } } };
    const add = () => document.body.querySelector<HTMLElement>("[data-column='todo'] [data-kanban-add]")!;
    expect(add().style.display).toBe("");
    vm.$.setupState.onStart({ item: cardEl(1), from: cardEl(1).closest<HTMLElement>("[data-column]")! });
    await flushPromises();
    expect(add().style.display).toBe("none");
  });

  it("refuses drags into columns the card may not enter", async () => {
    const wrapper = await board();
    const vm = wrapper.vm as unknown as { $: { setupState: { groupFor: (id: string) => { put: (a: unknown, b: unknown, el: HTMLElement) => boolean }; onStart: (e: { item: HTMLElement; from: HTMLElement }) => void } } };
    const state = vm.$.setupState;
    state.onStart({ item: cardEl(3), from: cardEl(3).closest<HTMLElement>("[data-column]")! });
    expect(state.groupFor("review").put(null, null, cardEl(3))).toBe(true);
    expect(state.groupFor("todo").put(null, null, cardEl(3))).toBe(false);
    expect(state.groupFor("done").put(null, null, cardEl(3))).toBe(false);
  });
});
