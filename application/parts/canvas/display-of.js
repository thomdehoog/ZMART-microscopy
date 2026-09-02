/**
 * The picture's display settings, as a request for a copy drawn with them.
 *
 * The Neuroglancer picture draws each channel through a linear window and
 * its own colour, added together. The small copies the bridge makes wear a
 * scan-wide stretch instead, so the preview in the Discover panel and the
 * gallery's pairs showed the operator a different sample from the one on the
 * canvas. A copy asked for with the panel's own state -- one entry per
 * channel row of the acquisition, its visibility, window and colour -- is
 * drawn by the bridge exactly as the canvas draws it.
 */

/**
 * A colour as `#rrggbb`, from the panel's own forms: the viewer's triple of
 * 0..1, or a CSS `rgb(r,g,b)` / `#rrggbb` string. Null when there is none.
 * The bridge reads six hex digits and draws white for anything else, which
 * is how every copy came back grey.
 */
export function hexColour(colour, color) {
  const hex = (parts) => `#${parts.map((v) => Math.round(Math.min(255, Math.max(0, v)))
    .toString(16).padStart(2, "0")).join("")}`;
  if (Array.isArray(colour) && colour.length === 3 && colour.every(Number.isFinite)) {
    return hex(colour.map((v) => v * 255));
  }
  if (typeof color !== "string") return null;
  const rgb = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(color);
  if (rgb) return hex([Number(rgb[1]), Number(rgb[2]), Number(rgb[3])]);
  return /^#[0-9a-f]{6}$/i.test(color) ? color.toLowerCase() : null;
}

/** The channel index a row's name carries: "channel 2" -> 2, else null. */
const channelIndexOf = (name) => {
  const found = /channel\s+(\d+)/i.exec(String(name ?? ""));
  return found ? Number(found[1]) : null;
};

/**
 * The display entries for one acquisition, from the panel's snapshot; `[]`
 * when the panel has no rows for it. Requested state is what the operator
 * asked for, which is what the canvas is told to draw.
 */
export function displayFor(snapshot, acquisition) {
  const rows = snapshot?.channels ?? [];
  return rows
    .filter((row) => row.acquisition === acquisition && channelIndexOf(row.name) !== null)
    .map((row) => {
      const asked = row.requested ?? {};
      /* The panel keeps a window as the engine does, `low` to `high`. */
      const window = asked.window && Number.isFinite(asked.window.low) && Number.isFinite(asked.window.high)
        ? [asked.window.low, asked.window.high] : null;
      return {
        c: channelIndexOf(row.name),
        visible: asked.effectiveVisible ?? asked.visible ?? true,
        window,
        color: hexColour(asked.colour, asked.color),
      };
    })
    .filter((one) => one.window !== null);
}

/**
 * The query to append to a copy's address so the bridge draws it with these
 * settings, or "" when there is nothing to ask with -- then the copy as the
 * bridge made it is the honest fallback.
 */
export function displayQueryFor(snapshot, acquisition) {
  const display = displayFor(snapshot, acquisition);
  return display.length ? `?display=${encodeURIComponent(JSON.stringify(display))}` : "";
}
