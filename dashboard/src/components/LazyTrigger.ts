/**
 * The trigger of a menu whose code hasn't loaded yet (DropdownMenu, the company switcher): the
 * slot's element as it is, announcing a menu, and asking for it (`activate`) on a click, Enter,
 * Space or the arrow keys, as the real trigger would open it. The host then loads the menu and
 * mounts it open; from there on the real trigger takes over.
 */
import { cloneVNode, defineComponent } from "vue";

import { firstSlotNode } from "./slotNode";

export default defineComponent({
  name: "LazyTrigger",
  emits: { activate: () => true },
  setup(_, { slots, emit }) {
    const activate = (event: Event) => {
      event.preventDefault();
      emit("activate");
    };
    const onKeydown = (event: KeyboardEvent) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") activate(event);
    };
    return () => {
      const node = firstSlotNode(slots.default?.() ?? []);
      return node ? cloneVNode(node, { "aria-haspopup": "menu", "aria-expanded": "false", onClick: activate, onKeydown }, true) : null;
    };
  },
});
