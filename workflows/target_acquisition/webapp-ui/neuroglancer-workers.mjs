/**
 * Getting neuroglancer's two background programs ready before the page is built.
 *
 * One of the three drawing engines this page offers is neuroglancer, and it is
 * the only one that does not do all its work in the page itself. It hands two
 * jobs to background programs — what a browser calls *workers*, which are simply
 * pieces of JavaScript running alongside the page so that heavy work does not
 * freeze what the operator is looking at. One of them fetches pieces of image
 * and keeps track of what is on screen; the other unpacks them, because the
 * pieces arrive compressed and undoing that is slow.
 *
 * Neither of those two is ready to run as it comes out of the box, and this file
 * is what makes them ready. It has to be run before the page is built. The
 * `dev` and `build` commands in `package.json` run it for you, so in normal use
 * there is nothing to remember.
 *
 * ## Why they are not ready
 *
 * Neuroglancer ships each background program as a short *list of imports* rather
 * than as a finished program — about twenty lines naming the pieces that belong
 * in it, written in a shorthand (`#src/…`) that only a build tool can look up. A
 * browser cannot follow that shorthand, so the program throws the moment it
 * starts.
 *
 * You would expect the page's own build tool to sort this out, because it sorts
 * out every other import in the project. It does not. Where neuroglancer asks
 * for a background program, Vite copies the file across exactly as it found it
 * and never looks inside. That was measured rather than assumed, and it is the
 * whole reason this file exists: the twenty-line list gets copied into the page,
 * the browser cannot read it, the program never starts, and — this is the part
 * that costs days — **nothing reports an error**. The description of a run loads
 * perfectly, the box stays black, and it looks exactly like a slow network.
 *
 * So we compile the two lists into two finished programs ourselves, with
 * esbuild, and put them back where neuroglancer expects to find them.
 *
 * ## The one uncomfortable thing this does
 *
 * It writes into `node_modules`, which is the folder npm manages and which
 * nobody should normally touch. There is no way around it: Vite reads the
 * background program straight off the disk at that path, and offers no way for a
 * plugin to hand it something else — that was tried, and Vite never asked.
 *
 * The danger in writing there is that `npm install` and `npm ci` put the
 * original short lists back, silently, and the very next build would produce a
 * page that opens and never draws. Three things guard against that:
 *
 * 1. This runs as part of `npm run dev` and `npm run build`, so a fresh install
 *    followed by either of them is put right before anything is built.
 * 2. It refuses to write anything that is suspiciously small, which is what a
 *    compile that quietly did nothing would produce.
 * 3. `tests/viewer-built.spec.js` photographs the built page and fails if
 *    neuroglancer draws nothing. A picture is the only check this project
 *    trusts, for exactly the reason above.
 *
 * ## Putting the two side by side
 *
 * The fetching program starts the unpacking program itself, at the moment it
 * meets the first compressed piece of image, and looks for it one folder *above*
 * its own. That works in neuroglancer's own layout and not in ours, where the
 * built page and everything beside it sit in one flat folder: one folder up is
 * outside what gets copied to the microscope, so the unpacking program would
 * never be found. Since a page opened straight off the disk resolves that path
 * literally, this is not a theoretical worry — it was measured, and the picture
 * stayed black.
 *
 * So while compiling, the place it looks is changed from "one folder up" to
 * "beside me". If neuroglancer ever renames that file the change stops matching
 * and this stops with a message, rather than compiling something that will fail
 * silently later.
 */

import { build } from "esbuild";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

/** Where neuroglancer keeps the two lists, and where the finished programs go. */
export const WHERE_THE_WORKERS_LIVE = join(here, "node_modules", "neuroglancer", "lib");

/** What the fetching program is called, and what the unpacking one is called. */
export const THE_FETCHING_PROGRAM = "chunk_worker.bundle.js";
export const THE_UNPACKING_PROGRAM = "async_computation.bundle.js";

/**
 * How small a finished program would have to be before we refuse it.
 *
 * The lists neuroglancer ships are well under a kilobyte and the compiled
 * programs are hundreds of them, so anything in between means the compile did
 * not do what it was asked. Refusing here is the difference between a build that
 * stops and says why, and a page that opens and never draws.
 */
const TOO_SMALL_TO_BE_REAL = 50 * 1024;

/** Where the unpacking program is looked for, and where we want it looked for. */
const NEUROGLANCER_LOOKS_ONE_FOLDER_UP = `"../${THE_UNPACKING_PROGRAM}"`;
const WE_WANT_IT_BESIDE = `"./${THE_UNPACKING_PROGRAM}"`;

/**
 * While compiling the fetching program, change where it looks for the unpacking
 * one. See the note about putting the two side by side, above.
 */
const lookBesideMeInstead = {
  name: "look-for-the-unpacking-program-beside-me",
  setup(esbuild) {
    esbuild.onLoad({ filter: /async_computation[\\/]request\.js$/ }, async ({ path }) => {
      const source = await readFile(path, "utf8");
      if (!source.includes(NEUROGLANCER_LOOKS_ONE_FOLDER_UP)) {
        throw new Error(
          "neuroglancer no longer says where it looks for " +
            `${THE_UNPACKING_PROGRAM} in the way this expects, so the change ` +
            "that puts the two background programs side by side did not " +
            "happen. Read the note in neuroglancer-workers.mjs and look at " +
            `${path} before going further — built as it stands, the page would ` +
            "open and never draw.",
        );
      }
      return {
        contents: source.replace(NEUROGLANCER_LOOKS_ONE_FOLDER_UP, WE_WANT_IT_BESIDE),
        loader: "js",
      };
    });
  },
};

/**
 * Compile one of the two lists into a finished program and put it back.
 *
 * @param name which one, by file name.
 * @param plugins any changes to make while compiling.
 * @returns how large the finished program is, in bytes.
 * @throws if the result is too small to be a real program, which is what a
 *   compile that silently did nothing looks like.
 */
async function compile(name, plugins = []) {
  const compiled = await build({
    entryPoints: [join(WHERE_THE_WORKERS_LIVE, name)],
    bundle: true,
    // These programs are written as modern JavaScript modules and neuroglancer
    // starts them as such, so the finished program has to be one too.
    format: "esm",
    write: false,
    logLevel: "error",
    // How to read neuroglancer's `#src/…` shorthand: its own package description
    // says what each one stands for, and this is the plain reading of it.
    conditions: ["default"],
    legalComments: "none",
    plugins,
  });
  const finished = compiled.outputFiles[0].text;
  if (finished.length < TOO_SMALL_TO_BE_REAL) {
    throw new Error(
      `${name} came out at only ${Math.round(finished.length / 1024)} KB, where ` +
        "a few hundred were expected. That is what the uncompiled list looks " +
        "like rather than a finished program, and a page built with it would " +
        "open and never draw, with nothing reported. Stopping here instead.",
    );
  }
  await writeFile(join(WHERE_THE_WORKERS_LIVE, name), finished);
  return finished.length;
}

/**
 * Get both background programs ready.
 *
 * Safe to run again at any time, and it deliberately does not try to work out
 * whether the work has already been done. Running it on a program that is
 * already compiled simply compiles it a second time, which costs a second or two
 * and produces the same program. Skipping would be faster and would risk
 * something far worse: a program compiled by an older version of this file
 * quietly staying in place.
 *
 * @returns how large each finished program is, in bytes, by file name.
 */
export async function readyTheBackgroundPrograms() {
  const unpacking = await compile(THE_UNPACKING_PROGRAM);
  const fetching = await compile(THE_FETCHING_PROGRAM, [lookBesideMeInstead]);
  return { [THE_UNPACKING_PROGRAM]: unpacking, [THE_FETCHING_PROGRAM]: fetching };
}

/** Read the finished unpacking program, so the build can place it beside the page. */
export async function theUnpackingProgram() {
  const source = await readFile(join(WHERE_THE_WORKERS_LIVE, THE_UNPACKING_PROGRAM), "utf8");
  if (source.length < TOO_SMALL_TO_BE_REAL) {
    throw new Error(
      `${THE_UNPACKING_PROGRAM} is only ${Math.round(source.length / 1024)} KB, ` +
        "which is the uncompiled list rather than a finished program. Run " +
        "`node neuroglancer-workers.mjs` — `npm run build` does it for you.",
    );
  }
  return source;
}

// Run directly (`node neuroglancer-workers.mjs`), this does the preparation and
// says what it produced, so a build log shows plainly that it happened.
if (import.meta.url === `file://${process.argv[1]}`) {
  const sizes = await readyTheBackgroundPrograms();
  for (const [name, bytes] of Object.entries(sizes)) {
    console.log(`neuroglancer's ${name} is ready: ${Math.round(bytes / 1024)} KB`);
  }
}
