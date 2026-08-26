import { defineConfig } from "vite";

// The harness shares the viewer's own installed packages rather than keeping a
// second copy of them. `node_modules` here is a link to `app/page/node_modules`,
// so the engine being compared is the exact version the viewer ships, which is
// the only version an answer about it would be worth anything for.
export default defineConfig({
  build: {
    // The engine's background worker must be emitted as a real file and never
    // folded into the page as a data address. A worker loaded that way has no
    // origin of its own, so the absolute-path requests it makes for pieces of
    // image cannot resolve — the description of a store loads and the pixels
    // never do. The same reasoning is written out at length in
    // `app/page/vite.config.js`.
    assetsInlineLimit: 0,
  },
  optimizeDeps: {
    // Vite's dev-mode pre-bundling rewrites neuroglancer's
    // `new Worker(new URL(...))` and breaks it. Leaving neuroglancer out keeps
    // `vite dev` usable and has no effect on the built page.
    exclude: ["neuroglancer"],
  },
});
