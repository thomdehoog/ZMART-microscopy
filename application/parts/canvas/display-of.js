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
        color: typeof asked.color === "string" ? asked.color : null,
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
