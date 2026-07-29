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
  server: {
    host: "127.0.0.1",
    port: 5174,
  },
});
