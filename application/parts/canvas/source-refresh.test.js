import { expect, test, vi } from "vitest";
import { refreshSources } from "../../../viz_studio/options/neuroglancer-under/source-refresh.js";

test("only the changed source is invalidated, once across shared channel readers", () => {
  const changed = { invalidateCache: vi.fn() };
  const unchanged = { invalidateCache: vi.fn() };
  const map = new Map([
    ['{"constructorId":1,"url":"http://viewer/data/0/tile.zarr/0/"}', changed],
    ['{"constructorId":2,"url":"http://viewer/data/0/tile.zarr/0/"}', changed],
    ['{"constructorId":1,"url":"http://viewer/data/0/tile.zarr-other/0/"}', unchanged],
    ['{"url":"http://viewer/data/0/tile.zarr/zarr.json"}', { metadata: true }],
  ]);
  expect(refreshSources({ memoize: { map } }, ["http://viewer/data/0/tile.zarr/|zarr3:"])).toBe(1);
  expect(changed.invalidateCache).toHaveBeenCalledOnce();
  expect(unchanged.invalidateCache).not.toHaveBeenCalled();
  expect(map.size).toBe(4);
});

test("no changed sources does not inspect or invalidate cached readers", () => {
  expect(refreshSources(null, [])).toBe(0);
});
