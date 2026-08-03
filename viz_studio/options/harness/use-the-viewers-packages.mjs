// Point this page's package lookup at the ones the viewer already installed.
//
// The harness deliberately keeps no packages of its own. It compares three ways
// of drawing, and the only version of an engine an answer is worth anything for
// is the version the viewer actually ships — so it borrows `frontend/node_modules`
// rather than installing a second copy that could drift away from it.
//
// The link is made here, at build time, rather than being kept in the repository,
// because a link into a folder that is not in the repository either would be a
// broken link on a fresh clone and a confusing one to debug. Made this way, the
// build either succeeds or says plainly that the viewer's packages are missing.

import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";
import { existsSync, lstatSync, symlinkSync, unlinkSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
// One link, at the top of `options/`, so that every option folder beneath it
// resolves its packages the ordinary way with no configuration at all.
const options = dirname(here);
const theViewers = join(options, "..", "frontend", "node_modules");
const link = join(options, "node_modules");

if (!existsSync(theViewers)) {
  throw new Error(
    "the viewer's packages are not installed, so there is no engine to build " +
      "against. Install them first:\n\n    npm --prefix viz_studio/frontend install\n",
  );
}
let already = null;
try {
  already = lstatSync(link);
} catch {
  already = null;
}
if (already && !already.isSymbolicLink()) {
  throw new Error(
    `${link} exists and is not a link. The harness expects to borrow the ` +
      "viewer's packages rather than keep its own; remove it and build again.",
  );
}
if (already) unlinkSync(link);
// Windows gets a junction rather than a symbolic link. For a directory the two
// are the same thing to everything that reads them — Node reports a junction as
// a link, so the check above still holds — but a symbolic link needs a
// privilege an ordinary account does not have and a junction does not. The
// microscope computer is an ordinary account, and a build that cannot run there
// is no use to this comparison. A junction has to be given the whole path
// rather than a relative one, which is the only reason the two differ here.
const windows = process.platform === "win32";
symlinkSync(
  windows ? theViewers : relative(options, theViewers),
  link,
  windows ? "junction" : "dir",
);
console.log(`options/node_modules -> ${relative(options, theViewers)}`);
