import { readFileSync } from "node:fs";
import { expect, test } from "vitest";

// Exercise the engine's pure range calculation without constructing a WebGL canvas.
const engine = readFileSync(new URL("../../../viz_studio/options/neuroglancer-under/viewer.js", import.meta.url), "utf8");
const start = engine.indexOf("function aggregateDepthIn(");
const end = engine.indexOf("/** Where the depth stands", start);
const range = new Function("UM_PER_M", `${engine.slice(start, end)}; return aggregateDepthIn;`)(1e6);
const space = depth => ({rank:1, names:["z"], scales:[1e-6], boundingBoxes:[{
  box:{lowerBounds:[-0.5], upperBounds:[depth-0.5]}, transform:[1,0],
}]});

test("a flat's slider range does not inherit a stack's combined bounds", () => {
  const own = {rows:[{acquisition:"flat", view:{type:"top"}, managed:{layer:{dataSources:[{
    loadState:{transform:{defaultTransform:{outputSpace:space(1)}, value:{outputSpace:space(61)}}},
  }]}}}]};
  expect(range(own, "flat")).toBeNull();
  own.rows[0].managed.layer.dataSources[0].loadState.transform.defaultTransform.outputSpace = space(3);
  expect(range(own, "flat")).toEqual({lowUm:0, highUm:2, stepUm:1});
});
