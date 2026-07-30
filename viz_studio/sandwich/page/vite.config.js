import { defineConfig } from "vite";

export default defineConfig({
  build: {
    // The engine's background worker must be a real file, never folded into the
    // page as a data address. A worker loaded that way has no origin of its own,
    // so the absolute-path requests it makes for pieces of image cannot resolve
    // — the description of a store would load and the pixels never would. The
    // same reasoning is written out at length in `frontend/vite.config.js`.
    assetsInlineLimit: 0,
  },
});
