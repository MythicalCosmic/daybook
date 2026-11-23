/**
 * Fixture mode: the dev server started with `VITE_VISION_FIXTURES=1` answers every `vision/` call
 * from `./fixtures` (a drawn pharmacy scene that moves with the clock) while everything else still
 * talks to the backend. `import.meta.env.DEV` is false in a build, so the fixtures and this switch
 * never ship: the constant folds to `false` and the branches that import them are dropped.
 */
export const FIXTURES = import.meta.env.DEV && import.meta.env.VITE_VISION_FIXTURES === "1";
