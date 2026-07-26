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

function Histogram({ layer }) {
  const counts = layer.histogram?.counts;
  if (!counts?.length) return null;
  const peak = Math.max(...counts, 1);
  return (
    <svg
      viewBox={`0 0 ${counts.length} 24`}
      preserveAspectRatio="none"
      style={styles.histogram}
      role="img"
      aria-label={`histogram ${layer.name}`}
    >
      {counts.map((count, index) => {
        const height = (Math.log1p(count) / Math.log1p(peak)) * 22;
        return (
          <rect
            key={index}
            x={index}
            y={24 - height}
            width="1"
            height={height}
            fill="currentColor"
          />
        );
      })}
    </svg>
  );
}

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
  groupOrder = [],
  groupState = {},
  onToggle,
  onColor,
  onOpacity,
  onWindow,
  onGroupToggle,
  onGroupOpacity,
  onGroupMove,
}) {
  const [openSwatch, setOpenSwatch] = React.useState(null);
  const [collapsed, setCollapsed] = React.useState({});
  const [dragging, setDragging] = React.useState(null);

  // Every row, paired with the position it holds in the panel's own state, so a
  // row can still be controlled after being gathered under its group.
  const rows = layers.map((layer, index) => ({ layer, index }));
  const groups = groupOrder.length
    ? groupOrder
    : [...new Set(layers.map((layer) => layer.group || ""))];

  const renderRow = ({ layer, index }) => {
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
            <div style={styles.histogramRow}>
              <Histogram layer={layer} />
              <button
                type="button"
                onClick={() =>
                  onWindow(index, layer.histogram?.autoWindow || layer.window)
                }
                disabled={!layer.histogram?.autoWindow && !layer.window}
                aria-label={`auto contrast ${layer.name}`}
                style={styles.autoButton}
              >
                Auto
              </button>
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
  };

  return (
    <aside style={styles.panel} aria-label="layer panel">
      <div style={styles.heading}>layers</div>
      {groups.map((group, position) => {
        const members = rows.filter(({ layer }) => (layer.group || "") === group);
        if (!members.length) return null;
        const settings = groupState[group] || { visible: true, opacity: 1 };
        const isCollapsed = collapsed[group];
        // A group with no name is a store that carried no acquisition type in its
        // filename. It still needs to appear, so its rows are shown plainly with
        // no header rather than hidden under an empty heading.
        if (!group) return <div key="ungrouped">{members.map(renderRow)}</div>;
        return (
          <div
            key={group}
            style={{
              ...styles.group,
              ...(dragging === position ? styles.groupDragging : null),
            }}
            draggable
            onDragStart={() => setDragging(position)}
            onDragEnd={() => setDragging(null)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              onGroupMove?.(dragging, position);
              setDragging(null);
            }}
          >
            <div style={styles.groupHead}>
              {/* Dragging a group up or down changes which acquisition type is
                  drawn on top of which, so this is a real control. */}
              <span style={styles.grip} title="Drag to change what is drawn on top">
                ⠿
              </span>
              <button
                onClick={() => setCollapsed((c) => ({ ...c, [group]: !c[group] }))}
                style={styles.disclose}
                aria-label={`${isCollapsed ? "expand" : "collapse"} ${group}`}
                aria-expanded={!isCollapsed}
              >
                {isCollapsed ? "▸" : "▾"}
              </button>
              <button
                onClick={() => onGroupToggle?.(group)}
                style={{ ...styles.eye, opacity: settings.visible ? 1 : 0.35 }}
                aria-label={`toggle group ${group}`}
                title={settings.visible ? "Hide this acquisition" : "Show this acquisition"}
              >
                {settings.visible ? "◉" : "◎"}
              </button>
              <span style={styles.groupName} title={group}>
                {group}
              </span>
              <span style={styles.groupCount}>{members.length}</span>
            </div>
            <label style={styles.control}>
              <span style={styles.controlLabel}>all</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={settings.opacity}
                onChange={(event) => onGroupOpacity?.(group, Number(event.target.value))}
                aria-label={`opacity group ${group}`}
                style={styles.range}
              />
              <output style={styles.value}>{Math.round(settings.opacity * 100)}%</output>
            </label>
            {!isCollapsed && <div style={styles.members}>{members.map(renderRow)}</div>}
          </div>
        );
      })}
    </aside>
  );
}

const styles = {
  group: { borderBottom: "1px solid #1d232b" },
  groupDragging: { opacity: 0.5, background: "#1a2029" },
  groupHead: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "7px 12px 3px",
    cursor: "grab",
  },
  grip: { color: "#4c5764", cursor: "grab", fontSize: 12, userSelect: "none" },
  disclose: {
    background: "none",
    border: "none",
    color: "#7f8a98",
    cursor: "pointer",
    fontSize: 10,
    padding: 0,
    width: 10,
  },
  groupName: {
    flex: 1,
    font: "600 12px/1 system-ui, sans-serif",
    letterSpacing: ".02em",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  groupCount: { color: "#5c6673", fontSize: 10, fontVariantNumeric: "tabular-nums" },
  // Channels are indented so it reads as "these belong to that acquisition".
  members: { paddingLeft: 8, borderLeft: "2px solid #1f2630", marginLeft: 14 },
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
  layer: { position: "relative", padding: "4px 0 8px" },
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
  histogramRow: {
    display: "grid",
    gridTemplateColumns: "1fr 42px",
    alignItems: "end",
    gap: 7,
    padding: "1px 12px 4px 60px",
  },
  histogram: {
    display: "block",
    width: "100%",
    height: 28,
    color: "#53657a",
    background: "#0d1015",
    border: "1px solid #202731",
    borderRadius: 3,
  },
  autoButton: {
    padding: "4px 5px",
    border: "1px solid #303a46",
    borderRadius: 4,
    background: "#1b222b",
    color: "#aab4c0",
    font: "600 10px/1 system-ui, sans-serif",
    cursor: "pointer",
  },
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
