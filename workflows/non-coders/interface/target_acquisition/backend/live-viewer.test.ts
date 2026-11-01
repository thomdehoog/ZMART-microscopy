import { afterEach, expect, it, vi } from "vitest";
import { ask, backend } from "./live.ts";
import { showPublicationStatus } from "../canvas/publication-note.ts";
import type { Answer } from "../testing/fake-bridge.ts";

afterEach(() => vi.unstubAllGlobals());

it("keeps valid acquisitions and reports partial publication without another request", async () => {
  const acquisitions = [{ name: "targets", channels: [{ sources: ["/aggregate"] }] }];
  const state = { acquisitions, error: "overview: incompatible sampling", publications: {
    overview: { acquired: 8, published: 2, state: "blocked" },
    targets: { acquired: 10, published: 10, state: "ready" },
  } };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => state })));
  const note = { textContent: "", hidden: false };
  expect(await backend.viewerSources(status => showPublicationStatus(note, status))).toBe(acquisitions);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(note.textContent).toContain("overview: 2/8 stores available (blocked)");
  expect(note.textContent).toContain("incompatible sampling");
  expect(note.hidden).toBe(false);
  showPublicationStatus(note, { publications: { overview: { state: "ready" } } });
  expect(note.hidden).toBe(true);
  showPublicationStatus(note, null);
  expect(note.textContent).toBe("");
});

it("still rejects command errors and does not treat HTTP failure as an empty picture", async () => {
  const fetched = vi.fn(async (): Promise<Answer> => ({ ok: true, json: async () => ({ error: "failed" }) }));
  vi.stubGlobal("fetch", fetched);
  await expect(ask("/api/target_acquisition/connect", {})).rejects.toThrow("failed");
  fetched.mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: "offline" }) });
  const report = vi.fn();
  expect(await backend.viewerSources(report)).toBeNull();
  expect(report).toHaveBeenCalledWith({ error: "Viewer status unavailable: offline" });
});
