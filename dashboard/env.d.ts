/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" serves every API call from src/dev/mock.ts (dev server only; never in a build). */
  readonly VITE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
