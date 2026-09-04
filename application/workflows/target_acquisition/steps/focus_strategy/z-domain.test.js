import { describe, expect, it } from "vitest";
import { zColourDomain } from "./z-domain.js";

describe("the physical Z colour domain", () => {
  it("gives a small measured range 100 micrometres rather than the whole palette", () => {
    expect(zColourDomain(5, 30)).toEqual([-32.5, 67.5]);
  });

  it("leaves an exactly 100 micrometre range unchanged", () => {
    expect(zColourDomain(10, 110)).toEqual([10, 110]);
  });

  it("expands to contain a range wider than 100 micrometres", () => {
    expect(zColourDomain(10, 145)).toEqual([10, 145]);
  });

  it("orders reversed measurements without changing their physical span", () => {
    expect(zColourDomain(40, 10)).toEqual([-25, 75]);
  });
});
