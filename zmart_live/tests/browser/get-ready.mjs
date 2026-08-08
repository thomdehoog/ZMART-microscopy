/**
 * Build the viewer page once, before any test starts.
 *
 * Gathering Neuroglancer into a page takes a couple of seconds, and doing it
 * inside a test would count against that test's own time limit and confuse a
 * failure about the page with a failure about the run. So it happens here, where
 * a problem building the page stops everything with a message about building the
 * page.
 */

import { buildThePage } from "./build-the-page.mjs";

export default function getReady() {
  buildThePage();
}
