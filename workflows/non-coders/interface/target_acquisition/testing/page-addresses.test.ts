/* What a browser spec takes from the page by its address is really there.
 *
 * A spec that runs code inside the page loads modules by their address on the
 * dev server — `await import("/@zmart-workflows/target_acquisition/canvas/viewer.ts")`,
 * where `/@zmart-workflows/` is the folder of workflows, wherever it is — and
 * takes names from them. Nothing that reads imports can follow such an address,
 * so a module moved, or a name made private, breaks the spec without a check
 * turning red. This reads every spec and holds each address to an existing file
 * and each name taken from it to one the file exports. */

import { describe, it, expect } from "vitest";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

/* The folder of workflows this workflow sits in. The dev server hands it out
   at `/@zmart-workflows/`, and the interface's own files at `/zmart_interface/`
   (the interface is found where the unit tests run, in its own checkout). */
const PACKAGE = fileURLToPath(new URL("../..", import.meta.url));
const INTERFACE = join(process.cwd(), "zmart_interface");
const fileAt = (address: string) => address.startsWith("/@zmart-workflows/")
  ? join(PACKAGE, address.slice("/@zmart-workflows/".length))
  : join(INTERFACE, address.slice("/zmart_interface/".length));

const specs = (folder: string): string[] => readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
  const at = join(folder, entry.name);
  if (entry.isDirectory()) return ["built-page", "node_modules", "__pycache__"].includes(entry.name) ? [] : specs(at);
  return /\.spec\.[jt]s$/.test(entry.name) ? [at] : [];
});

/* `const { a, b: c } = await import("/…")`, and `const m = await import("/…")`
   with the names then read off `m.`. */
const DESTRUCTURED = /(?:const|let)\s*\{([^{}]*)\}\s*=\s*await import\(\s*["'](\/(?:zmart_interface|@zmart-workflows)\/[^"']+)["']\s*\)/g;
const WHOLE = /(?:const|let)\s+(\w+)\s*=\s*await import\(\s*["'](\/(?:zmart_interface|@zmart-workflows)\/[^"']+)["']\s*\)/g;

function exportsOf(file: string): Set<string> {
  const text = readFileSync(file, "utf8");
  const names = new Set<string>();
  for (const m of text.matchAll(/^export\s+(?:async\s+)?(?:function\*?|const|let|class)\s+(\w+)/gm)) names.add(m[1]);
  /* `export const { a, b } = ...`: each name taken apart. */
  for (const m of text.matchAll(/^export\s+(?:const|let)\s*\{([^}]*)\}/gm)) {
    for (const part of m[1].split(",")) names.add(part.trim().split(/\s*:\s*/).pop() ?? "");
  }
  for (const m of text.matchAll(/^export\s*\{([^}]*)\}/gm)) {
    for (const part of m[1].split(",")) names.add(part.trim().split(/\s+as\s+/).pop() ?? "");
  }
  if (/^export\s+default\b/m.test(text)) names.add("default");
  return names;
}

function takenBy(spec: string): { address: string; name: string | null }[] {
  const text = readFileSync(spec, "utf8");
  const taken: { address: string; name: string | null }[] = [];
  for (const m of text.matchAll(DESTRUCTURED)) {
    for (const part of m[1].split(",")) {
      const name = part.trim().split(":")[0].trim();
      if (name) taken.push({ address: m[2], name });
    }
  }
  for (const m of text.matchAll(WHOLE)) {
    const names = new Set([...text.matchAll(new RegExp(`\\b${m[1]}\\.(\\w+)`, "g"))].map((n) => n[1]));
    if (!names.size) taken.push({ address: m[2], name: null });
    for (const name of names) taken.push({ address: m[2], name });
  }
  return taken;
}

describe("what the browser specs take from the page by address", () => {
  const all = specs(PACKAGE).flatMap((spec) => takenBy(spec).map((one) => ({ spec, ...one })));

  it("finds some to check", () => {
    expect(all.length).toBeGreaterThan(5);
  });

  for (const { spec, address, name } of all) {
    const where = relative(PACKAGE, spec).replaceAll("\\", "/");
    it(`${where} takes ${name ?? "a module"} from ${address}`, () => {
      const file = fileAt(address);
      expect(existsSync(file), `${address} is not a file`).toBe(true);
      if (name) expect(exportsOf(file).has(name), `${address} does not export ${name}`).toBe(true);
    });
  }
});
