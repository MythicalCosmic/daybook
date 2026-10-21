/**
 * The first real node a slot rendered (comments from `v-if` and fragments from `v-for`/`<template>`
 * stepped through): the element a wrapper with no element of its own (UiTooltip, LazyTrigger)
 * adds its listeners and ARIA attributes to with `cloneVNode`.
 */
import { Comment, Fragment, type VNode } from "vue";

export function firstSlotNode(nodes: readonly VNode[]): VNode | null {
  for (const node of nodes) {
    if (node.type === Comment) continue;
    if (node.type === Fragment && Array.isArray(node.children)) {
      const inner = firstSlotNode(node.children as VNode[]);
      if (inner) return inner;
      continue;
    }
    return node;
  }
  return null;
}
