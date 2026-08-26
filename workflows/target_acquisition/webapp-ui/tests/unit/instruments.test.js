/**
 * The Connect card's lists come from the controller's registry
 * (`get_instruments`): each entry is a connection dict identified by vendor,
 * microscope and api. `choicesFrom` groups them the way the card asks — one
 * microscope, then its APIs — and keeps the entry under each API, because
 * that entry is what `set_instrument` takes.
 */

import { describe, expect, it } from "vitest";
import {
  choicesFrom, describeSession,
} from "../../workflows/target_acquisition/microscope/instruments.js";
import { pretendInstruments } from "../../workflows/target_acquisition/microscope/mock.js";

describe("choicesFrom", () => {
  it("groups the registry's entries into microscopes with their apis, in registry order", () => {
    const choices = choicesFrom([
      { vendor: "mock", microscope: "mock-scope", api: "mock-api", client: "mock-client" },
      { vendor: "leica", microscope: "stellaris5-y42h93", api: "navigator-expert", client: "PythonClient" },
      { vendor: "leica", microscope: "stellaris5-y42h93", api: "pyapi", client: "PythonClient" },
    ]);
    expect(choices.map((m) => m.key)).toEqual(["mock/mock-scope", "leica/stellaris5-y42h93"]);
    expect(choices[1].apis.map((a) => a.key)).toEqual(["navigator-expert", "pyapi"]);
  });

  it("uses the page's words for ids it knows, and the id itself otherwise", () => {
    const [mock, leica] = choicesFrom(pretendInstruments());
    expect(mock.label).toBe("Mock");
    expect(mock.apis[0].label).toBe("Mock API");
    expect(leica.label).toBe("Leica Stellaris 5");
    expect(leica.apis[0].label).toBe("Navigator Expert");
    const [unknown] = choicesFrom([{ vendor: "acme", microscope: "zx-9", api: "rest" }]);
    expect(unknown.label).toBe("zx-9");
    expect(unknown.detail).toBe("acme");
    expect(unknown.apis[0].label).toBe("rest");
  });

  it("keeps the whole entry under each api, untouched, for set_instrument", () => {
    const entry = { vendor: "mock", microscope: "mock-scope", api: "mock-api", client: "mock-client", extra: 1 };
    const [mock] = choicesFrom([entry]);
    expect(mock.apis[0].connection).toEqual(entry);
    expect(mock.apis[0].connection).not.toBe(entry);
  });

  it("describes a session by its entry", () => {
    expect(describeSession({ connection: pretendInstruments()[1] })).toBe("Leica Stellaris 5 · Navigator Expert");
    expect(describeSession({ connection: null })).toBe("not chosen");
  });
});
