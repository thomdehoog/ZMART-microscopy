import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

/* The microscope PC has no toolchain and no network: the build happens on a
   developer machine and Python hands out the result. Everything is therefore
   inlined into one file — the same shape `workflow/webapp/_page.py` serves
   today, and the same shape a Claude artifact can host. */
export default defineConfig({
  base: "./",
  plugins: [viteSingleFile()],
  build: {
    outDir: "../workflow/webapp/static",
    emptyOutDir: true,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    reportCompressedSize: false,
  },
  /* The drawing engine is only reached through a dynamic import — it is fetched
     when there is a run to watch and not before — so the development server does
     not find it while looking over the page at start-up. It would instead meet
     it the first time somebody opened the scan step, prepare it then, and reload
     the page to use it, which throws away whatever the operator was in the
     middle of. Naming the packages here has them made ready before the server
     starts answering. */
  optimizeDeps: {
    include: [
      "@deck.gl/core", "@deck.gl/layers", "@deck.gl/geo-layers",
      "@vivjs/extensions", "@vivjs/layers", "@vivjs/loaders", "@vivjs/views",
    ],
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    watch: {
      /* The browser tests leave photographs here. Vite reloads the page when a
         file in the project changes, which is exactly what you want while
         editing and exactly what you do not want in the middle of a test: the
         page would jump back to its first step and the run being watched would
         be lost. */
      ignored: ["**/test-results/**", "**/playwright-report/**"],
    },
  },
});
