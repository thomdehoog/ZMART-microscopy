// After the page is built, put neuroglancer's second background worker where it
// is actually loaded from.
//
// Neuroglancer uses a second kind of worker for decompression — unpacking the
// compressed pieces of image. The main worker loads it at run time from
// "../async_computation.bundle.js" relative to its own place, which comes out as
// the root of the site. Vite does not emit that file on its own, so without this
// step the decompression worker is answered with a 404: pieces of image are
// fetched and never decoded, and the picture never fills in. Nothing errors.
//
// `app/page/precompile-workers.mjs` has already compiled a real, self-contained
// worker into the neuroglancer package; this copies it into the built page.

import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { copyFile, stat } from "node:fs/promises";

const here = dirname(fileURLToPath(import.meta.url));
// Up one, because the packages are borrowed from the viewer and linked at the
// top of `parked/` rather than inside this folder. See
// `use-the-viewers-packages.mjs`.
const from = join(
  here, "..", "node_modules", "neuroglancer", "lib", "async_computation.bundle.js",
);
const to = join(here, "dist", "async_computation.bundle.js");

const { size } = await stat(from);
if (size < 50 * 1024) {
  throw new Error(
    `async_computation.bundle.js is only ${Math.round(size / 1024)} KB, which ` +
      "looks like the uncompiled stub rather than a real worker. Run " +
      "app/page/precompile-workers.mjs first — the build script does.",
  );
}
await copyFile(from, to);
console.log(`placed the async-computation worker (${Math.round(size / 1024)} KB)`);
