import React from "react";

export default function TargetsPanel({
  targets,
  activeTool,
  color,
  visible,
  onTool,
  onColor,
  onVisible,
  onSelect,
  onDelete,
  onGoto,
}) {
  return (
    <aside style={styles.panel} aria-label="targets panel">
      <div style={styles.heading}>Targets</div>
      <div style={styles.tools}>
        {[
          ["point", "Point"],
          ["box", "Box"],
        ].map(([key, label]) => (
          <button
            key={key}
            aria-pressed={activeTool === key}
            onClick={() => onTool(activeTool === key ? null : key)}
            style={{ ...styles.button, ...(activeTool === key ? styles.active : null) }}
          >
            {label}
          </button>
        ))}
        <input
          type="color"
          aria-label="target color"
          value={color}
          onChange={(event) => onColor(event.target.value)}
          style={styles.color}
        />
        <label style={styles.visible}>
          <input type="checkbox" checked={visible} onChange={onVisible} /> show
        </label>
      </div>
      <div style={styles.list}>
        {targets.length === 0 && <div style={styles.empty}>Draw a point or box in the image.</div>}
        {targets.map((target, index) => (
          <div key={target.id} style={styles.target}>
            <button style={styles.name} onClick={() => onSelect(target.id)}>
              {target.type === "point" ? "Point" : "Box"} {index + 1}
            </button>
            {target.type === "axis_aligned_bounding_box" && (
              <button style={styles.small} onClick={() => onGoto(target)}>Go to</button>
            )}
            <button aria-label={`delete target ${index + 1}`} style={styles.delete} onClick={() => onDelete(target.id)}>
              ×
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}

const styles = {
  panel: { width: 250, padding: 12, background: "#11151a", color: "#c9d1d9", borderLeft: "1px solid #252b33", font: "12px system-ui, sans-serif", overflow: "auto" },
  heading: { fontWeight: 700, marginBottom: 10, letterSpacing: ".04em" },
  tools: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  button: { border: "1px solid #303844", borderRadius: 4, background: "#1b2027", color: "#b6c0cc", padding: "5px 9px", cursor: "pointer" },
  active: { borderColor: "#2f81f7", background: "#174a84", color: "white" },
  color: { width: 28, height: 27, padding: 1, border: "1px solid #303844", background: "none" },
  visible: { color: "#99a4b1", display: "flex", gap: 4, alignItems: "center" },
  list: { marginTop: 12, display: "grid", gap: 5 },
  empty: { color: "#747f8d", lineHeight: 1.4, padding: "8px 2px" },
  target: { display: "grid", gridTemplateColumns: "1fr auto auto", gap: 5, alignItems: "center", borderBottom: "1px solid #252b33", paddingBottom: 5 },
  name: { textAlign: "left", border: 0, background: "none", color: "#c9d1d9", cursor: "pointer", padding: 4 },
  small: { border: "1px solid #303844", borderRadius: 3, background: "#1b2027", color: "#9ecbff", padding: "3px 6px", cursor: "pointer" },
  delete: { border: 0, background: "none", color: "#f07178", fontSize: 18, cursor: "pointer" },
};
