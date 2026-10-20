/**
 * Filters, sort, view, drawer and range live in the URL (plan §6.5), so every view can be shared and
 * bookmarked. `useRouteState("status", rs.enum(["open", "done"], "open"))` returns a writable ref
 * bound to `?status=`; default values are left out of the URL, and several writes in the same tick
 * become one `router.replace`.
 */
import { computed, type WritableComputedRef } from "vue";
import { useRoute, useRouter, type LocationQuery, type LocationQueryValue, type Router } from "vue-router";

export type RawQueryValue = LocationQueryValue | LocationQueryValue[] | undefined;
export type SerializedValue = string | string[] | undefined;

export interface Codec<T> {
  parse: (raw: RawQueryValue) => T;
  /** `undefined` removes the key (used for the default value). */
  serialize: (value: T) => SerializedValue;
}

function first(raw: RawQueryValue): string | undefined {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value ?? undefined;
}

function all(raw: RawQueryValue): string[] {
  if (raw === undefined || raw === null) return [];
  const values = Array.isArray(raw) ? raw : [raw];
  return values.flatMap((v) => (v ?? "").split(",")).filter(Boolean);
}

export const rs = {
  string(fallback = ""): Codec<string> {
    return { parse: (raw) => first(raw) ?? fallback, serialize: (v) => (v === fallback || v === "" ? undefined : v) };
  },
  number(fallback: number): Codec<number> {
    return {
      parse: (raw) => {
        const value = Number(first(raw));
        return first(raw) !== undefined && Number.isFinite(value) ? value : fallback;
      },
      serialize: (v) => (v === fallback ? undefined : String(v)),
    };
  },
  optionalNumber(): Codec<number | null> {
    return {
      parse: (raw) => {
        const text = first(raw);
        const value = Number(text);
        return text !== undefined && text !== "" && Number.isFinite(value) ? value : null;
      },
      serialize: (v) => (v === null ? undefined : String(v)),
    };
  },
  boolean(fallback = false): Codec<boolean> {
    return {
      parse: (raw) => {
        const text = first(raw);
        if (text === undefined) return fallback;
        return text === "1" || text === "true";
      },
      serialize: (v) => (v === fallback ? undefined : v ? "1" : "0"),
    };
  },
  enum<T extends string>(values: readonly T[], fallback: T): Codec<T> {
    return {
      parse: (raw) => {
        const text = first(raw);
        return text !== undefined && (values as readonly string[]).includes(text) ? (text as T) : fallback;
      },
      serialize: (v) => (v === fallback ? undefined : v),
    };
  },
  /** `?branch=1&branch=2` and `?branch=1,2` both read as ["1", "2"]; written as repeated keys. */
  list(): Codec<string[]> {
    return { parse: (raw) => all(raw), serialize: (v) => (v.length ? [...v] : undefined) };
  },
  numberList(): Codec<number[]> {
    return {
      parse: (raw) => all(raw).map(Number).filter(Number.isFinite),
      serialize: (v) => (v.length ? v.map(String) : undefined),
    };
  },
  /** A company-local day "YYYY-MM-DD", or null. */
  day(): Codec<string | null> {
    return {
      parse: (raw) => {
        const text = first(raw);
        return text && /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : null;
      },
      serialize: (v) => v ?? undefined,
    };
  },
};

interface PendingPatch {
  patch: Record<string, SerializedValue>;
  push: boolean;
}

const pending = new WeakMap<Router, PendingPatch>();

/** Applies a query patch now; `undefined` deletes a key. */
export function applyQueryPatch(query: LocationQuery, patch: Record<string, SerializedValue>): LocationQuery {
  const next: LocationQuery = { ...query };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined || (Array.isArray(value) && value.length === 0)) delete next[key];
    else next[key] = value;
  }
  return next;
}

/** Queues a query change; every change made in the same tick lands in one navigation. */
export function patchQuery(router: Router, patch: Record<string, SerializedValue>, push = false): void {
  const queued = pending.get(router);
  if (queued) {
    Object.assign(queued.patch, patch);
    queued.push ||= push;
    return;
  }
  const entry: PendingPatch = { patch: { ...patch }, push };
  pending.set(router, entry);
  queueMicrotask(() => {
    pending.delete(router);
    const current = router.currentRoute.value;
    const query = applyQueryPatch(current.query, entry.patch);
    const location = { path: current.path, query, hash: current.hash };
    void (entry.push ? router.push(location) : router.replace(location));
  });
}

export interface RouteStateOptions {
  /** Add a history entry (drawers, so Back closes them). Default: replace. */
  push?: boolean;
}

export function useRouteState<T>(key: string, codec: Codec<T>, options: RouteStateOptions = {}): WritableComputedRef<T> {
  const route = useRoute();
  const router = useRouter();
  return computed({
    get: () => codec.parse(route.query[key]),
    set: (value: T) => patchQuery(router, { [key]: codec.serialize(value) }, options.push),
  });
}

/** Any codec, whatever its value type (serialize takes `never` so every Codec<T> fits). */
interface AnyCodec {
  parse: (raw: RawQueryValue) => unknown;
  serialize: (value: never) => SerializedValue;
}

type StateRefs<S extends Record<string, AnyCodec>> = { [K in keyof S]: WritableComputedRef<ReturnType<S[K]["parse"]>> };

/** Several URL-bound values at once, plus `reset()` that clears them all in one navigation. */
export function useRouteStates<S extends Record<string, AnyCodec>>(schema: S): StateRefs<S> & { reset: () => void } {
  const route = useRoute();
  const router = useRouter();
  const refs = {} as Record<string, WritableComputedRef<unknown>>;
  for (const [key, codec] of Object.entries(schema)) {
    refs[key] = computed({
      get: () => codec.parse(route.query[key]),
      set: (value: unknown) => patchQuery(router, { [key]: codec.serialize(value as never) }),
    });
  }
  const reset = () => patchQuery(router, Object.fromEntries(Object.keys(schema).map((key) => [key, undefined])));
  return Object.assign(refs as StateRefs<S>, { reset });
}
