/**
 * How the little test page is built.
 *
 * The page needs a real Neuroglancer in it, and Neuroglancer is not something a
 * browser can be pointed at directly: it is a package of a few thousand source
 * files, some of them written in an older style browsers cannot read at all. So
 * it is gathered into one page beforehand, here.
 *
 * Everything below is the same arrangement that
 * `workflows/target_acquisition/webapp-ui/vite.config.js` arrived at, reduced to
 * what this one page needs. That file explains each decision at length and is
 * worth reading if any of this needs changing; the short version follows.
 *
 * **Where Neuroglancer is.** This folder installs nothing of its own. The
 * packages live under the operator page's `node_modules`, so the two settings
 * below say where to look. Neuroglancer offers its insides under names beginning
 * `neuroglancer/unstable/`, which are not folder names — its package description
 * maps them onto a folder called `lib` — so that mapping is written out rather
 * than left to the usual rules.
 *
 * **The two background programs.** Neuroglancer hands two jobs to programs
 * running alongside the page: one fetches pieces of image, the other unpacks
 * them. A browser will only start such a program from a file of its own, never
 * from something folded into the page, so those two are the one thing here that
 * stays separate. They are also not ready to run as the package ships them, and
 * `webapp-ui/neuroglancer-workers.mjs` is what makes them ready; the build
 * script beside this file runs it first.
 *
 * If this ever goes wrong the symptom is worth knowing in advance, because it
 * looks like nothing: the page loads, the engine reports itself ready, it works
 * out which pieces of image it needs — and then never asks for one, with no
 * error anywhere. The screen simply stays black.
 */

import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  THE_UNPACKING_PROGRAM, theUnpackingProgram,
} from "../../../../workflows/target_acquisition/webapp-ui/neuroglancer-workers.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const OPERATOR_PAGE = path.resolve(
  here, "..", "..", "..", "..", "workflows", "target_acquisition", "webapp-ui",
);
const NEUROGLANCER = path.join(OPERATOR_PAGE, "node_modules", "neuroglancer");

/** The fetching program and the unpacking program, by the shape of their names. */
const THE_BACKGROUND_PROGRAMS = /\.bundle\.js$/;

/* The unpacking program is started by the fetching one rather than by the page,
   so the build never sees it asked for and would leave it out. Placing it here
   puts it beside the page, which is where the fetching program looks for it. */
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

/* Neuroglancer carries two small sign-in pages for image servers this project
   does not use. They arrive in the build as extra HTML and confuse the last
   step; nothing is lost by dropping them. */
const dropTheSignInPagesWeDoNotUse = {
  name: "zmart:drop-neuroglancers-sign-in-pages",
  apply: "build",
  generateBundle(_options, bundle) {
    for (const name of Object.keys(bundle)) {
      if (name.endsWith(".html") && name !== "index.html") delete bundle[name];
    }
  },
};

/* Written out as a plain object rather than wrapped in Vite's own `defineConfig`
   helper. That helper is only there to give an editor something to check the
   spelling of the settings against, and importing it from this folder would mean
   finding the `vite` package from a folder that installs nothing — which it
   cannot do. The settings themselves are exactly the same either way. */
export default {
  root: here,
  base: "./",
  plugins: [placeTheUnpackingProgram, dropTheSignInPagesWeDoNotUse],
  build: {
    outDir: path.join(here, "built"),
    emptyOutDir: true,
    /* Everything in one flat folder rather than the usual `assets/` beneath it.
       This looks like tidiness and is not: the fetching program's address is
       worked out relative to the piece of JavaScript that starts it, and the
       fetching program looks for the unpacking one beside itself. Put back, the
       page draws nothing, silently. */
    assetsDir: "",
    cssCodeSplit: false,
    reportCompressedSize: false,
    chunkSizeWarningLimit: 100_000_000,
    /* Fold everything into the page except the two background programs, which
       have to stay files of their own. */
    assetsInlineLimit: (file) => !THE_BACKGROUND_PROGRAMS.test(file),
  },
  resolve: {
    alias: [
      { find: /^neuroglancer\/unstable\//, replacement: `${path.join(NEUROGLANCER, "lib")}/` },
    ],
  },
};
