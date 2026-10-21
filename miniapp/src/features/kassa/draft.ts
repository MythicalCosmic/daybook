/**
 * The close draft: everything a cashier typed while closing a shift, kept on the phone so a
 * reload, a crash or a dead basement signal loses nothing. Text goes to localStorage (read
 * synchronously, so the screen comes back exactly as it was); photos go to IndexedDB, which
 * holds files. Both are conveniences: every call swallows storage errors.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { NoteCounts } from "../../ui";

export const STEPS = ["sales", "z", "cash", "review"] as const;
export type Step = (typeof STEPS)[number];

/** Typing states (digits, as the keypad keeps them) per payment method id. */
export type Line = { sales: string; refunds: string };

export type CloseDraft = {
  v: 1;
  step: Step;
  lines: Record<string, Line>;
  /** The method whose amount the keypad edits. */
  method: number | null;
  receipts: string;
  zNumber: string;
  counts: NoteCounts;
  /** The total typed instead of counting notes (a counting machine), or null. */
  typedCash: string | null;
  note: string;
  /** A send was attempted and not confirmed: try again when the screen comes back. */
  pending: boolean;
  savedAt: string | null;
};

export function emptyDraft(lines: Record<string, Line> = {}, method: number | null = null): CloseDraft {
  return { v: 1, step: "sales", lines, method, receipts: "", zNumber: "", counts: {}, typedCash: null, note: "", pending: false, savedAt: null };
}

export const draftKey = (company: number, shift: number) => `daybook.kassa.close.${company}.${shift}`;

export function readDraft(company: number, shift: number): CloseDraft | null {
  try {
    const raw = localStorage.getItem(draftKey(company, shift));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CloseDraft>;
    if (parsed?.v !== 1 || !STEPS.includes(parsed.step as Step)) return null;
    return { ...emptyDraft(), ...parsed } as CloseDraft;
  } catch {
    return null;
  }
}

export function writeDraft(company: number, shift: number, draft: CloseDraft): void {
  try {
    localStorage.setItem(draftKey(company, shift), JSON.stringify(draft));
  } catch {
    // Full or blocked storage: the draft lives as long as the screen does.
  }
}

export function clearDraft(company: number, shift: number): void {
  try {
    localStorage.removeItem(draftKey(company, shift));
  } catch {
    // Nothing to clear.
  }
  void photoStore.clear(`${company}.${shift}.`);
}

/** Whether the person typed anything worth keeping. */
export function hasContent(draft: CloseDraft): boolean {
  return (
    Object.values(draft.lines).some((line) => line.sales || line.refunds) ||
    Boolean(draft.receipts || draft.zNumber || draft.note || draft.typedCash) ||
    Object.values(draft.counts).some((count) => (count ?? 0) > 0)
  );
}

// — photos —

const DB = "daybook-kassa";
const STORE = "photos";

function openDb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") return resolve(null);
      const request = indexedDB.open(DB, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

async function withStore<T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest | null, fallback: T): Promise<T> {
  const db = await openDb();
  if (!db) return fallback;
  return new Promise<T>((resolve) => {
    try {
      const transaction = db.transaction(STORE, mode);
      const request = work(transaction.objectStore(STORE));
      transaction.oncomplete = () => {
        db.close();
        resolve((request?.result as T | undefined) ?? fallback);
      };
      transaction.onerror = () => {
        db.close();
        resolve(fallback);
      };
    } catch {
      db.close();
      resolve(fallback);
    }
  });
}

type StoredPhoto = { name: string; type: string; blob: Blob };

/** Photos of a close in progress, by key ("12.1043.z"). */
export const photoStore = {
  async get(key: string): Promise<File | null> {
    const stored = await withStore<StoredPhoto | null>("readonly", (store) => store.get(key), null);
    if (!stored?.blob) return null;
    return new File([stored.blob], stored.name, { type: stored.type });
  },
  async put(key: string, file: File | null): Promise<void> {
    await withStore("readwrite", (store) => (file ? store.put({ name: file.name, type: file.type, blob: file } satisfies StoredPhoto, key) : store.delete(key)), null);
  },
  async clear(prefix: string): Promise<void> {
    await withStore(
      "readwrite",
      (store) => store.delete(IDBKeyRange.bound(prefix, `${prefix}￿`)),
      null,
    );
  },
};

export type PhotoKind = "z" | "terminal";
export type Photos = Record<PhotoKind, File | null>;

/**
 * The draft as React state: restored on mount, written on every change. `restoredAt` is when
 * the draft found on the phone was saved (null for a fresh close), for the "draft restored" line.
 */
export function useCloseDraft(company: number, shift: number, fresh: () => CloseDraft) {
  const [state, setState] = useState(() => {
    const saved = readDraft(company, shift);
    return { draft: saved ?? fresh(), restoredAt: saved && hasContent(saved) ? saved.savedAt : null };
  });
  const [photos, setPhotos] = useState<Photos>({ z: null, terminal: null });
  const touched = useRef<Set<PhotoKind>>(new Set());

  useEffect(() => {
    let alive = true;
    for (const kind of ["z", "terminal"] as const) {
      void photoStore.get(`${company}.${shift}.${kind}`).then((file) => {
        // A photo picked while the store was being read wins over the stored one.
        if (alive && file && !touched.current.has(kind)) setPhotos((old) => ({ ...old, [kind]: file }));
      });
    }
    return () => {
      alive = false;
    };
  }, [company, shift]);

  const update = useCallback(
    (patch: Partial<CloseDraft> | ((draft: CloseDraft) => Partial<CloseDraft>)) => {
      setState((old) => {
        const changes = typeof patch === "function" ? patch(old.draft) : patch;
        const draft = { ...old.draft, ...changes, savedAt: new Date().toISOString() };
        writeDraft(company, shift, draft);
        return { ...old, draft };
      });
    },
    [company, shift],
  );

  const setPhoto = useCallback(
    (kind: PhotoKind, file: File | null) => {
      touched.current.add(kind);
      setPhotos((old) => ({ ...old, [kind]: file }));
      void photoStore.put(`${company}.${shift}.${kind}`, file);
    },
    [company, shift],
  );

  const reset = useCallback(() => {
    clearDraft(company, shift);
    touched.current = new Set(["z", "terminal"]);
    setPhotos({ z: null, terminal: null });
    setState({ draft: fresh(), restoredAt: null });
  }, [company, shift, fresh]);

  const dismissRestored = useCallback(() => setState((old) => ({ ...old, restoredAt: null })), []);

  return { draft: state.draft, restoredAt: state.restoredAt, update, photos, setPhoto, reset, dismissRestored };
}
