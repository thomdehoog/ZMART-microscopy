import React from "react";

// What to say about the last save. Saving is automatic and quick, so most of the
// time this is a quiet "Saved" -- but a failure has to be loud, because an
// unsaved target list looks identical to a saved one until the acquisition is
// reopened and the targets have vanished.
function saveMessage(saveState) {
  if (!saveState || saveState.status === "idle") return null;
  if (saveState.status === "saving") return { text: "Saving…", tone: "quiet" };
  if (saveState.status === "saved") return { text: "Saved beside the image.", tone: "quiet" };
  return { text: `Not saved: ${saveState.message}`, tone: "bad" };
}

// What to say about the last "Go to". There are three good outcomes to tell
// apart: the stage moved, the request was understood but nothing moved (no
// microscope attached, or moves switched off), and the microscope refused.
function gotoMessage(gotoState) {
  if (!gotoState) return null;
  if (gotoState.status === "sending") return { text: "Sending to the microscope…", tone: "quiet" };
  if (gotoState.status === "moved") return { text: gotoState.message || "Stage moved.", tone: "good" };
  if (gotoState.status === "reported") return { text: gotoState.message, tone: "quiet" };
  return { text: gotoState.message, tone: "bad" };
}

/**
 * The list of places the operator has marked, and what can be done with them.
 *
 * Each row is one target: a name you can type into, a button that selects it in
 * the image, "Go to" for a region you want the microscope to visit, and a delete
 * button. Naming is worth the space — "ventricle, double-positive" is far easier
 * to come back to a week later than "Box 3".
 */
export default function TargetsPanel({
  targets,
  activeTool,
  color,
  visible,
  saveState,
  gotoState,
  onTool,
  onColor,
  onVisible,
  onSelect,
  onDelete,
  onGoto,
  onDescribe,
}) {
  const save = saveMessage(saveState);
  const sent = gotoMessage(gotoState);

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
            <button
              style={styles.name}
              onClick={() => onSelect(target.id)}
              title="Show this target in the image"
            >
              {target.type === "point" ? "Point" : "Box"} {index + 1}
            </button>
            <button style={styles.small} onClick={() => onGoto(target)}>
              Go to
            </button>
            <button
              aria-label={`delete target ${index + 1}`}
              style={styles.delete}
              onClick={() => onDelete(target.id)}
            >
              ×
            </button>
            <input
              type="text"
              value={target.description || ""}
              placeholder="name or note…"
              aria-label={`description for target ${index + 1}`}
              onChange={(event) => onDescribe(target.id, event.target.value)}
              style={styles.description}
              maxLength={1000}
            />
          </div>
        ))}
      </div>
      {(save || sent) && (
        <div style={styles.status} aria-live="polite">
          {save && <div style={{ ...styles.statusLine, ...styles[save.tone] }}>{save.text}</div>}
          {sent && <div style={{ ...styles.statusLine, ...styles[sent.tone] }}>{sent.text}</div>}
        </div>
      )}
    </aside>
  );
}

const styles = {
  panel: { width: 250, padding: 12, background: "#11151a", color: "#c9d1d9", borderLeft: "1px solid #252b33", font: "12px system-ui, sans-serif", overflow: "auto", display: "flex", flexDirection: "column" },
  heading: { fontWeight: 700, marginBottom: 10, letterSpacing: ".04em" },
  tools: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  button: { border: "1px solid #303844", borderRadius: 4, background: "#1b2027", color: "#b6c0cc", padding: "5px 9px", cursor: "pointer" },
  active: { borderColor: "#2f81f7", background: "#174a84", color: "white" },
  color: { width: 28, height: 27, padding: 1, border: "1px solid #303844", background: "none" },
  visible: { color: "#99a4b1", display: "flex", gap: 4, alignItems: "center" },
  list: { marginTop: 12, display: "grid", gap: 5 },
  empty: { color: "#747f8d", lineHeight: 1.4, padding: "8px 2px" },
  // Three controls on the first row, then the name field spanning the full width
  // underneath, so a long note has room to be read.
  target: { display: "grid", gridTemplateColumns: "1fr auto auto", gap: 5, alignItems: "center", borderBottom: "1px solid #252b33", paddingBottom: 6 },
  name: { textAlign: "left", border: 0, background: "none", color: "#c9d1d9", cursor: "pointer", padding: 4 },
  small: { border: "1px solid #303844", borderRadius: 3, background: "#1b2027", color: "#9ecbff", padding: "3px 6px", cursor: "pointer" },
  delete: { border: 0, background: "none", color: "#f07178", fontSize: 18, cursor: "pointer" },
  description: { gridColumn: "1 / -1", border: "1px solid #262d36", borderRadius: 3, background: "#0e1216", color: "#aab4c0", padding: "4px 6px", font: "11px system-ui, sans-serif" },
  status: { marginTop: "auto", paddingTop: 10, display: "grid", gap: 3, lineHeight: 1.4 },
  statusLine: { fontSize: 11 },
  quiet: { color: "#748091" },
  good: { color: "#7ee2a8" },
  bad: { color: "#f0888f" },
};
