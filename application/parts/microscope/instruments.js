/**
 * What can be connected to, and what this page calls it.
 *
 * The list is the controller's: `get_instruments` answers with one entry per
 * registered driver, and an entry is the connection dict `set_instrument`
 * takes — identified by vendor, microscope and api, with whatever
 * driver-specific extras it carries. The page never invents an instrument;
 * it only groups the entries the way the Connect card asks, and puts
 * friendlier words on the ids it happens to know.
 */

export const MICROSCOPES = {
  "mock-scope": { label: "Mock", detail: "the controller's fake driver" },
  "stellaris5-y42h93": { label: "Leica Stellaris 5", detail: "y42h93" },
};

export const APIS = {
  "mock-api": { label: "Mock API", detail: "in-process · made-up data" },
  "navigator-expert": { label: "Navigator Expert", detail: "CAM socket 8895 · LAS X 4.9" },
};

/**
 * The registry's entries, grouped the way the Connect card asks: one
 * microscope, then the APIs registered for it, each API carrying the entry
 * to connect with. Registry order is kept.
 */
export function choicesFrom(instruments) {
  const microscopes = [];
  for (const entry of instruments ?? []) {
    const key = `${entry.vendor}/${entry.microscope}`;
    let scope = microscopes.find((m) => m.key === key);
    if (!scope) {
      const known = MICROSCOPES[entry.microscope];
      scope = {
        key,
        vendor: entry.vendor,
        microscope: entry.microscope,
        label: known?.label ?? entry.microscope,
        detail: known?.detail ?? entry.vendor,
        apis: [],
      };
      microscopes.push(scope);
    }
    const api = APIS[entry.api];
    scope.apis.push({
      key: entry.api,
      label: api?.label ?? entry.api,
      detail: api?.detail ?? "",
      connection: { ...entry },
    });
  }
  return microscopes;
}

export const DEFAULT_SESSION = {
  /* Chosen once the instruments are listed: the first the registry offers,
     which is the mock, so a page opened by accident drives nothing. */
  microscope: null,
  api: null,
  /* Empty on purpose. It used to be prefilled so the mock could be clicked
     through without typing, but the same page is the one a real instrument
     is driven from, and a default credential is not a convenience: it is a
     credential everybody has. Connect stays disabled until one is typed. */
  password: "",
};

export const describeSession = ({ connection }) => {
  if (!connection) return "not chosen";
  const scope = MICROSCOPES[connection.microscope]?.label ?? connection.microscope;
  const api = APIS[connection.api]?.label ?? connection.api;
  return `${scope} · ${api}`;
};
