import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { watchTheRun } from "./watching-the-run.ts";
import type { WatchContext } from "./watching-the-run.ts";
import type { Acquisition } from "../../canvas/engines/neuroglancer-under/viewer.ts";
import type { ViewerPanelElement } from "../../canvas/viewer-panel.ts";

const mocks = vi.hoisted(() => ({ opener: vi.fn(), mountPanel: vi.fn() }));
vi.mock("../../canvas/engines.ts", () => ({ openerFor: mocks.opener }));
vi.mock("../../canvas/viewer-panel.ts", () => ({ mountViewerPanel: mocks.mountPanel }));

const deferred = () => {
  let resolve!: (value: unknown) => void;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
let ctx: WatchContext;
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("window", {});
  vi.stubGlobal("location", { search: "" });
  /* A stand-in page: a plain object for the box, and only what these tests reach. */
  ctx = {
    connected: () => true, viewerSources: async () => [],
    pictureHost: {}, css: () => "#000", view: () => null,
  } as unknown as WatchContext;
  mocks.opener.mockReset();
  mocks.mountPanel.mockReset();
  mocks.mountPanel.mockResolvedValue({ element: {}, destroy: vi.fn(), sourcesChanged: async () => true });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

test("a failed update is reported and the next publication can recover", async () => {
  const viewer = { destroy: vi.fn(), setView: vi.fn(), addSources: vi.fn(async () => true) };
  mocks.opener.mockResolvedValue(async () => viewer);
  const run = watchTheRun(ctx);
  await vi.dynamicImportSettled();
  await settle();
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    ctx.viewerSources = async () => { throw new Error("viewer unavailable"); };
    await run.thePicture.reopenIfTheRunGrew();
    expect(log).toHaveBeenCalledWith(expect.stringContaining("viewer unavailable"));
    ctx.viewerSources = async () => [{ name: "overview", url: "/overview" }];
    await run.thePicture.reopenIfTheRunGrew();
    expect(viewer.addSources).toHaveBeenCalledOnce();
    expect(viewer.destroy).not.toHaveBeenCalled();
  } finally { log.mockRestore(); }
});

test("reset disposes an opening viewer instead of resurrecting the disconnected session", async () => {
  const pending = deferred();
  const viewer = { destroy: vi.fn(), setView: vi.fn() };
  mocks.opener.mockResolvedValue(() => pending.promise);
  const run = watchTheRun(ctx);
  await settle();
  run.thePicture.reset();
  pending.resolve(viewer);
  await settle();
  expect(viewer.destroy).toHaveBeenCalledOnce();
  expect(window.__thePicture).toBeNull();
  expect(mocks.mountPanel).not.toHaveBeenCalled();
});

test("reset during engine import never starts a stale viewer", async () => {
  const pending = deferred();
  const open = vi.fn();
  mocks.opener.mockReturnValue(pending.promise);
  const run = watchTheRun(ctx);
  await settle();
  run.thePicture.reset();
  pending.resolve(open);
  await settle();
  expect(open).not.toHaveBeenCalled();
});

test("an old pending source install cannot block the next session", async () => {
  const pending = deferred();
  const first = { destroy: vi.fn(), setView: vi.fn(), addSources: vi.fn(() => pending.promise) };
  const second = { destroy: vi.fn(), setView: vi.fn(), addSources: vi.fn(async () => true) };
  const open = vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second);
  mocks.opener.mockResolvedValue(open);
  const run = watchTheRun(ctx);
  await settle();
  ctx.viewerSources = async () => [{ name: "focus", url: "/focus" }];
  await vi.dynamicImportSettled();
  const stale = run.thePicture.reopenIfTheRunGrew();
  await settle();
  expect(first.addSources).toHaveBeenCalledOnce();
  run.thePicture.reset();
  ctx.viewerSources = async () => [];
  await run.thePicture.open();
  ctx.viewerSources = async () => [{ name: "overview", url: "/overview" }];
  await run.thePicture.reopenIfTheRunGrew();
  expect(second.addSources).toHaveBeenCalledOnce();
  pending.resolve(true);
  await stale;
  expect(window.__thePicture).toBe(second);
  expect(run.thePicture.shows("overview")).toBe(true);
});

test("an unavailable source response does not retire loaded images", async () => {
  const viewer = { destroy: vi.fn(), setView: vi.fn(), addSources: vi.fn() };
  mocks.opener.mockResolvedValue(async () => viewer);
  ctx.viewerSources = async () => [{ name: "focus", url: "/focus" }];
  const run = watchTheRun(ctx);
  await settle();
  await vi.dynamicImportSettled();
  ctx.viewerSources = async () => null;
  await run.thePicture.reopenIfTheRunGrew();
  expect(viewer.destroy).not.toHaveBeenCalled();
  expect(viewer.addSources).not.toHaveBeenCalled();
  expect(window.__thePicture).toBe(viewer);
});

test("the projection is the one product drawn, for every acquisition, now and later", async () => {
  /* The shared viewer names a projection product by its method: the max
     projection is the key "max" on a row whose view type is "projection". */
  const api = `export const EMBEDDING_API_VERSION=1;
    export const viewChoices=rows=>[{id:'a',keys:rows.map(r=>r.view.method??r.view.type)}];
    export const selectedViews=(rows,wanted)=>wanted;
    export const inSelectedView=(row,wanted)=>(row.view.method??row.view.type)===wanted.a;`;
  const embeddingUrl = `data:text/javascript,${encodeURIComponent(api)}`;
  const names = ["overview", "focussing"];
  /* Published sources as the viewer's server sends them: no url of their own. */
  ctx.viewerSources = async () => names.map(name => ({ name, embeddingUrl,
    channels: [{ view: { acquisition: name, type: "projection", method: "max" }, sources: [`/${name}/max`] }] }));
  const element: Partial<ViewerPanelElement> & { setViewMode?: unknown } = {};
  mocks.mountPanel.mockResolvedValue({ element, destroy: vi.fn(), sourcesChanged: async () => true });
  const viewer = {
    destroy: vi.fn(), setView: vi.fn(),
    addSources: vi.fn<(acquisitions: Acquisition[]) => Promise<boolean>>(async () => true),
  };
  mocks.opener.mockResolvedValue(async () => viewer);
  const run = watchTheRun(ctx);
  await vi.dynamicImportSettled(); await settle();
  expect(element.viewModes?.("overview")).toEqual(["projection"]);
  expect(element.viewMode?.()).toBe("projection");
  expect(element.setViewMode).toBeUndefined();
  names.push("targets");
  await run.thePicture.reopenIfTheRunGrew();
  expect(viewer.addSources.mock.lastCall![0].map(a => a.channels![0].view!.method)).toEqual(["max", "max", "max"]);
});

test("an acquisition whose projection is not published yet is left out until it is", async () => {
  const api = `export const EMBEDDING_API_VERSION=1;
    export const viewChoices=rows=>[{id:'a',keys:rows.map(r=>r.view.method??r.view.type)}];
    export const selectedViews=(rows,wanted)=>wanted;
    export const inSelectedView=(row,wanted)=>(row.view.method??row.view.type)===wanted.a;`;
  const embeddingUrl = `data:text/javascript,${encodeURIComponent(api)}`;
  const published = (name: string, method: string) => ({ name, embeddingUrl,
    channels: [{ view: { acquisition: name, type: "projection", method }, sources: [`/${name}/${method}`] }] });
  /* The overview's projection is out; the targets' is not yet -- only its
     raw planes are. Handed on with no address, the engine read one anyway
     and the whole picture failed to update. */
  ctx.viewerSources = async () => [published("overview", "max"), published("targets", "raw")];
  mocks.mountPanel.mockResolvedValue({ element: {}, destroy: vi.fn(), sourcesChanged: async () => true });
  const viewer = {
    destroy: vi.fn(), setView: vi.fn(),
    addSources: vi.fn<(acquisitions: Acquisition[]) => Promise<boolean>>(async () => true),
  };
  const open = vi.fn<(host: unknown, how: { acquisitions: Acquisition[] }) => Promise<typeof viewer>>(async () => viewer);
  mocks.opener.mockResolvedValue(open);
  watchTheRun(ctx);
  await vi.dynamicImportSettled(); await settle();
  const drawn = open.mock.lastCall![1].acquisitions;
  expect(drawn.map((a) => a.name)).toEqual(["overview"]);
  expect(drawn.every((a) => typeof a.url === "string")).toBe(true);
});
