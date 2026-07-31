import path from "node:path";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

/* The canvas — the picture of a run, on the viewer step — is not kept in this
   folder. It lives at the top of the repository in `viz_studio/options/`,
   because it is one viewer written three times over, behind one interface, so
   that the three can be compared; the measurements that compare them live beside
   it and would make no sense in here.

   Reaching across to it costs two settings, and both are here rather than hidden
   because a reader meeting an import that climbs five folders deserves to find
   the reason in the obvious place.

   The first is this list. A file asks for a package by name, and the browser has
   no idea what that means, so the build has to find the folder it stands for.
   The usual rule is to look beside the file that asked and then keep looking
   upwards — which works everywhere inside this project and finds nothing at all
   from `viz_studio/options/`, since that folder installs no packages of its own.
   Naming them here says plainly: whatever the canvas asks for, it gets this
   page's copy.

   That is worth more than a convenience. Two copies of a drawing engine alive in
   one page is not a subtle failure — deck.gl refuses outright and says so — so
   having exactly one copy, this page's, is the arrangement that works. It does
   mean the engines are being compared here on the version this page ships, which
   need not be the version the measurements in `viz_studio/options/RESULTS.md`
   were taken with. */
const WHAT_THE_CANVAS_ASKS_FOR = [
  "@deck.gl/core",
  "@deck.gl/layers",
  "@math.gl/core",
  "@vivjs/extensions",
  "@vivjs/layers",
  "@vivjs/loaders",
];

const here = import.meta.dirname;

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
  resolve: {
    alias: Object.fromEntries(
      WHAT_THE_CANVAS_ASKS_FOR.map((name) => [name, path.join(here, "node_modules", name)]),
    ),
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    /* The second setting the canvas costs. While the page is being developed,
       Vite serves the files it needs straight off the disk, and it refuses by
       default to serve anything outside this folder — a sensible guard against a
       page reaching for whatever else happens to be on the machine. The canvas
       is outside it, so the top of the repository is named as somewhere this
       page is allowed to read from. This has no bearing on the built page, which
       is one file with everything already inside it. */
    fs: { allow: [path.resolve(here, "..", "..", "..")] },
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
