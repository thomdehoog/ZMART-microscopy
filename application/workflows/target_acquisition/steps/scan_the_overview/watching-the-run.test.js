import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { watchTheRun } from "./watching-the-run.js";

const mocks = vi.hoisted(() => ({ opener: vi.fn(), mountPanel: vi.fn() }));
vi.mock("../../../../parts/canvas/engines.js", () => ({ openerFor: mocks.opener }));
vi.mock("../../../../parts/canvas/viewer-panel.js", () => ({ mountViewerPanel: mocks.mountPanel }));

const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
let ctx;
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("window", {});
  vi.stubGlobal("location", { search: "" });
  ctx = {
    connected: () => true, viewerSources: async () => [],
    pictureHost: {}, css: () => "#000", view: () => null,
  };
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

test("a temporarily unavailable product does not erase the requested view", async () => {
  const api = `export const EMBEDDING_API_VERSION=1;
    export const viewChoices=rows=>[{id:'a',keys:rows.map(r=>r.view.type)}];
    export const selectedViews=(rows,wanted)=>wanted;
    export const inSelectedView=(row,wanted)=>row.view.type===wanted.a;`;
  const embeddingUrl = `data:text/javascript,${encodeURIComponent(api)}`;
  let modes = ["slice", "top"];
  ctx.viewerSources = async () => [{name:"a", embeddingUrl, channels:modes.map(type => ({
    view:{acquisition:"a",type}, sources:[`/${type}`], sourceRevisions:[1],
  }))}];
  const element = {};
  mocks.mountPanel.mockResolvedValue({element, destroy:vi.fn(), sourcesChanged:async()=>true});
  const viewer = {destroy:vi.fn(), setView:vi.fn(), addSources:vi.fn(async()=>true)};
  mocks.opener.mockResolvedValue(async()=>viewer);
  const run = watchTheRun(ctx);
  await vi.dynamicImportSettled();
  await settle();
  expect(element.viewMode("a")).toBe("top");
  const changing = deferred();
  viewer.addSources.mockImplementationOnce(() => changing.promise);
  ctx.displayChanged = vi.fn();
  const selection = element.setViewMode("a", "slice");
  expect(ctx.displayChanged).toHaveBeenCalledOnce();
  expect(element.viewMode("a")).toBe("slice");
  await settle();
  changing.resolve(true);
  await selection;
  expect(element.viewMode("a")).toBe("slice");
  modes = ["top"];
  await run.thePicture.reopenIfTheRunGrew();
  expect(element.viewMode("a")).toBe("top");
  modes = ["top", "slice"];
  await run.thePicture.reopenIfTheRunGrew();
  expect(element.viewMode("a")).toBe("slice");
  expect(viewer.addSources.mock.lastCall[0][0].channels[0].view.type).toBe("slice");
});
