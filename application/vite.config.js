import path from "node:path";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import {
  THE_UNPACKING_PROGRAM, WHERE_THE_WORKERS_LIVE, theUnpackingProgram,
} from "./neuroglancer-workers.mjs";

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

/* Neuroglancer, the third engine, has to be found a different way. It offers its
   insides under names beginning `neuroglancer/unstable/`, which are not folder
   names: its package description maps them onto a folder called `lib`. Naming
   the package the way the list above does would therefore point at folders that
   do not exist, so the mapping is written out here instead. It says the same
   thing as the list above — whatever the canvas asks of neuroglancer, it gets
   this page's copy — in the one form that resolves. */
const WHERE_NEUROGLANCER_KEEPS_ITS_INSIDES = {
  find: /^neuroglancer\/unstable\//,
  replacement: `${path.join(here, "node_modules", "neuroglancer", "lib")}/`,
};

/**
 * Neuroglancer's two background programs, and what the build has to do about
 * them.
 *
 * One of the three engines does part of its work in background programs, which
 * a browser will only start from a file of its own — never from something folded
 * into the page. `neuroglancer-workers.mjs` explains that at length and gets the
 * two programs ready; these two plugins are the build's side of it.
 *
 * `assetsInlineLimit` below is what keeps the fetching program out of the page.
 * Everything else — every script, every stylesheet, every image — is folded in,
 * because that is what the microscope computer is meant to receive. The two
 * background programs are the exception, and the page will not draw with
 * neuroglancer without them.
 */
const THE_BACKGROUND_PROGRAMS = /\.bundle\.js$/;

/* The fetching program starts the unpacking program itself, so Vite never sees
   it asked for and would not put it in the build. Placing it here means it lands
   beside the page, which is where the fetching program now looks. */
const placeTheUnpackingProgram = {
  name: "zmart:place-neuroglancers-unpacking-program",
  apply: "build",
  async generateBundle() {
    this.emitFile({
      type: "asset",
      fileName: THE_UNPACKING_PROGRAM,
      source: await theUnpackingProgram(),
    });
  },
};

/* Neuroglancer carries two small sign-in pages for image servers we do not use.
   They arrive in the build as extra HTML, and the single-file plugin treats
   every piece of HTML as a page to fold things into and stops with an error it
   cannot explain. Dropping them first is why the build gets as far as the page
   we actually want, and nothing is lost: they belong to sign-in routes this
   application never takes. */
const dropTheSignInPagesWeDoNotUse = {
  name: "zmart:drop-neuroglancers-sign-in-pages",
  apply: "build",
  generateBundle(_options, bundle) {
    for (const name of Object.keys(bundle)) {
      if (name.endsWith(".html") && name !== "index.html") delete bundle[name];
    }
  },
};

/* The microscope PC has no toolchain and no network: the build happens on a
   developer machine and Python hands out the result. Everything is therefore
   folded into one file — close to the shape `workflow/webapp/_page.py` serves
   today.

   Everything, that is, except neuroglancer's two background programs, which a
   browser refuses to start from anything but a file. So what gets copied to the
   microscope is one folder holding three files: `index.html`, which is the whole
   page, and the two programs beside it. The page opens and draws with the two
   Viv engines whether or not those two are there; they are what the third engine
   needs. `README.md` says what that costs and why it was accepted — including
   the one thing genuinely given up, which is that a build with neuroglancer in
   it is no longer a single file a Claude artifact could host. */
export default defineConfig({
  base: "./",
  plugins: [
    placeTheUnpackingProgram,
    dropTheSignInPagesWeDoNotUse,
    /* The single-file plugin normally sets a handful of build options for you,
       one of which folds *everything* into the page — background programs
       included, where they cannot run. Its recommendations are therefore
       declined and written out under `build` below instead, so that the one that
       has to differ can differ, and a reader can see all of them at once. */
    viteSingleFile({ useRecommendedBuildConfig: false }),
  ],
  build: {
    outDir: "framework/window/static",
    emptyOutDir: true,
    /* Fold everything into the page except neuroglancer's background programs,
       which have to stay files of their own. */
    assetsInlineLimit: (file) => !THE_BACKGROUND_PROGRAMS.test(file),
    /* Everything in one folder, rather than the usual `assets/` beneath it.
       This looks like tidiness and is not: put back, the page draws nothing, in
       two different ways.

       Vite works out where the fetching program is *relative to the piece of
       JavaScript that starts it* — and that piece is then folded into
       `index.html`, one folder higher up. The address it was given no longer
       points anywhere. And the fetching program looks for the unpacking one
       beside itself, so the two must in any case share a folder. Both were met
       and measured; both are silent. */
    assetsDir: "",
    cssCodeSplit: false,
    reportCompressedSize: false,
    // One page's worth of JavaScript in one file is large by the usual measure,
    // and being told so on every build helps nobody.
    chunkSizeWarningLimit: 100_000_000,
    rollupOptions: { output: { codeSplitting: false } },
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
      /* Neuroglancer is the one package that must *not* be made ready this way,
         because doing so rewrites the line where it starts its background
         program and the program then never starts. It is left out just below.
         What it needs, though, are these: a handful of older libraries it uses
         which are written in a style browsers cannot read directly. Left alone
         they stop the page with errors that name the library rather than
         neuroglancer — "require is not defined", "CodeMirror is not defined" —
         which is a long way to travel from the real cause. */
      "neuroglancer > codemirror",
      "neuroglancer > codemirror/addon/fold/brace-fold.js",
      "neuroglancer > codemirror/addon/fold/foldcode.js",
      "neuroglancer > codemirror/addon/fold/foldgutter.js",
      "neuroglancer > codemirror/addon/lint/lint.js",
      "neuroglancer > codemirror/mode/javascript/javascript.js",
      "neuroglancer > core-js/actual/symbol/dispose.js",
      "neuroglancer > core-js/actual/symbol/async-dispose.js",
      "neuroglancer > crc-32",
      "neuroglancer > gl-matrix",
      "neuroglancer > msgpackr",
      "neuroglancer > nifti-reader-js",
    ],
    exclude: ["neuroglancer"],
  },
  resolve: {
    alias: [
      WHERE_NEUROGLANCER_KEEPS_ITS_INSIDES,
      ...WHAT_THE_CANVAS_ASKS_FOR.map((name) => ({
        find: name,
        replacement: path.join(here, "node_modules", name),
      })),
    ],
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
    /* The second setting the canvas costs. While the page is being developed,
       Vite serves the files it needs straight off the disk, and it refuses by
       default to serve anything outside this folder — a sensible guard against a
       page reaching for whatever else happens to be on the machine. The canvas
       is outside it, so the top of the repository is named as somewhere this
       page is allowed to read from. */
    fs: { allow: [path.resolve(here, ".."), WHERE_THE_WORKERS_LIVE] },
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
