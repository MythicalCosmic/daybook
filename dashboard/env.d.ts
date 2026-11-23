/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" serves every API call from src/dev/mock.ts (dev server only; never in a build). */
  readonly VITE_MOCK?: string;
  /** "1" answers Ko‘z's `vision/` calls from src/modules/vision/fixtures (dev server only; never in a build). */
  readonly VITE_VISION_FIXTURES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
