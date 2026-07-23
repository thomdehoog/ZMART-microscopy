import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The visualization engine (neuroglancer) ships as a modern bundle that
// creates its own background workers with `new Worker(new URL(...))`. Vite
// understands that idiom natively when building — but its dev-mode
// "pre-bundling" optimizer rewrites those URLs and breaks the workers. The
// documented fix is simply to leave neuroglancer out of pre-bundling, so Vite
// serves it as-is. This one line is the difference between a blank canvas and
// a working viewer in development.
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    exclude: ["neuroglancer"],
  },
  // neuroglancer's workers are ES-module workers; match that so the built
  // output loads them the same way.
  worker: {
    format: "es",
  },
  server: {
    // During local development the frontend runs on Vite's own port. Anything
    // the app asks for under /data (the image volume) or /api (the Python
    // backend) is forwarded to the Python server, so the browser sees a single
    // origin and there is no cross-site friction. In the shipped app the Python
    // server serves everything itself, so this proxy is a dev-only convenience.
    proxy: {
      "/data": "http://127.0.0.1:8848",
      "/api": "http://127.0.0.1:8848",
    },
  },
});
