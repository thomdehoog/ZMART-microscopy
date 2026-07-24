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
export default function LayerPanel({
  layers,
  state,
  mode,
  onToggle,
  onColor,
  onOpacity,
  onWindow,
}) {
  const [openSwatch, setOpenSwatch] = React.useState(null);

  return (
    <aside style={styles.panel}>
      <div style={styles.heading}>layers</div>
      {layers.map((layer, index) => {
        const { visible, color, opacity, window: windowOverride } = state[index];
        const measuredWindow =
          mode === "volume" ? layer.volumeWindow || layer.window : layer.window;
        const window_ = windowOverride || measuredWindow || { low: 0, high: 65535 };
        const sliderMax = Math.max(1, 65535, Math.ceil(window_.high));
        const setLow = (low) =>
          onWindow(index, { low: Math.min(low, window_.high - 1), high: window_.high });
        const setHigh = (high) =>
          onWindow(index, { low: window_.low, high: Math.max(high, window_.low + 1) });
        return (
          <div key={layer.name} style={styles.layer}>
            <div style={styles.row}>
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
            <label style={styles.control}>
              <span style={styles.controlLabel}>black</span>
              <input
                type="range"
                min="0"
                max={sliderMax}
                step="1"
                value={window_.low}
                onChange={(event) => setLow(Number(event.target.value))}
                aria-label={`black ${layer.name}`}
                style={styles.range}
              />
              <output style={styles.value}>{Math.round(window_.low)}</output>
            </label>
            <label style={styles.control}>
              <span style={styles.controlLabel}>white</span>
              <input
                type="range"
                min="1"
                max={sliderMax}
                step="1"
                value={window_.high}
                onChange={(event) => setHigh(Number(event.target.value))}
                aria-label={`white ${layer.name}`}
                style={styles.range}
              />
              <output style={styles.value}>{Math.round(window_.high)}</output>
            </label>
            <label style={styles.control}>
              <span style={styles.controlLabel}>opacity</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={opacity}
                onChange={(event) => onOpacity(index, Number(event.target.value))}
                aria-label={`opacity ${layer.name}`}
                style={styles.range}
              />
              <output style={styles.value}>{Math.round(opacity * 100)}%</output>
            </label>
          </div>
        );
      })}
    </aside>
  );
}

const styles = {
  panel: {
    width: 260,
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
  layer: { position: "relative", padding: "4px 0 10px", borderBottom: "1px solid #1d232b" },
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
  control: {
    display: "grid",
    gridTemplateColumns: "42px 1fr 42px",
    alignItems: "center",
    gap: 6,
    padding: "2px 12px",
    color: "#7f8a98",
    fontSize: 10,
  },
  controlLabel: { textTransform: "uppercase", letterSpacing: ".04em" },
  range: { width: "100%", accentColor: "#2f81f7", cursor: "pointer" },
  value: { color: "#aab4c0", textAlign: "right", fontVariantNumeric: "tabular-nums" },
};
