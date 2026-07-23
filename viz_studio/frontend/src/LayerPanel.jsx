import React from "react";

// A small, deliberately limited palette. Green and magenta lead because that is
// the pairing that reads best on a dark background and stays legible to a
// colour-blind viewer, unlike red/green.
export const PALETTE = [
  { name: "green", rgb: [0.0, 1.0, 0.4] },
  { name: "magenta", rgb: [1.0, 0.2, 1.0] },
  { name: "cyan", rgb: [0.2, 0.8, 1.0] },
  { name: "amber", rgb: [1.0, 0.75, 0.1] },
  { name: "blue", rgb: [0.3, 0.45, 1.0] },
  { name: "grey", rgb: null },
];

const css = (rgb) =>
  rgb ? `rgb(${rgb.map((v) => Math.round(v * 255)).join(",")})` : "#d8dee6";

/**
 * The layer list, in napari's shape: one row per layer, an eye to hide it, a
 * swatch to recolour it.
 *
 * Deliberately the only chrome on screen. Everything the engine would otherwise
 * put up -- its own layer panel, top bar and dialogs -- is off, so this is the
 * single place layers are controlled and there is no second owner to fight.
 */
export default function LayerPanel({ layers, state, onToggle, onColor }) {
  const [openSwatch, setOpenSwatch] = React.useState(null);

  return (
    <aside style={styles.panel}>
      <div style={styles.heading}>layers</div>
      {layers.map((layer, index) => {
        const { visible, color } = state[index];
        return (
          <div key={layer.name} style={styles.row}>
            <button
              onClick={() => onToggle(index)}
              style={{ ...styles.eye, opacity: visible ? 1 : 0.35 }}
              title={visible ? "Hide this layer" : "Show this layer"}
              aria-label={`toggle ${layer.name}`}
            >
              {visible ? "◉" : "◎"}
            </button>
            <button
              onClick={() => setOpenSwatch(openSwatch === index ? null : index)}
              style={{ ...styles.swatch, background: css(color) }}
              title="Colour"
              aria-label={`colour ${layer.name}`}
            />
            <span style={styles.name} title={layer.name}>
              {layer.name}
            </span>
            {openSwatch === index && (
              <div style={styles.palette}>
                {PALETTE.map((entry) => (
                  <button
                    key={entry.name}
                    onClick={() => {
                      onColor(index, entry.rgb);
                      setOpenSwatch(null);
                    }}
                    style={{ ...styles.paletteDot, background: css(entry.rgb) }}
                    title={entry.name}
                    aria-label={`${entry.name} for ${layer.name}`}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </aside>
  );
}

const styles = {
  panel: {
    width: 200,
    flexShrink: 0,
    background: "#12161c",
    borderRight: "1px solid #232a33",
    padding: "10px 0",
    overflowY: "auto",
    font: "13px/1.4 system-ui, -apple-system, 'Segoe UI', sans-serif",
    color: "#c9d1d9",
  },
  heading: {
    padding: "0 12px 8px",
    font: "600 11px/1 system-ui, sans-serif",
    letterSpacing: ".08em",
    textTransform: "uppercase",
    color: "#6b7684",
  },
  row: { position: "relative", display: "flex", alignItems: "center", gap: 8, padding: "5px 12px" },
  eye: { background: "none", border: "none", color: "#c9d1d9", cursor: "pointer", fontSize: 13, padding: 0 },
  swatch: { width: 13, height: 13, borderRadius: 3, border: "1px solid #39424e", cursor: "pointer", padding: 0 },
  name: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  palette: {
    position: "absolute",
    left: 34,
    top: 26,
    zIndex: 20,
    display: "flex",
    gap: 4,
    padding: 5,
    background: "#1b212a",
    border: "1px solid #2f3843",
    borderRadius: 5,
    boxShadow: "0 2px 8px rgba(0,0,0,.6)",
  },
  paletteDot: { width: 15, height: 15, borderRadius: 3, border: "1px solid #39424e", cursor: "pointer", padding: 0 },
};
