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

/**
 * The list of places the operator has marked, and what can be done with them.
 *
 * Each row is one target: a name you can type into, a button that takes the view
 * back to it, and a button that removes it. Naming is worth the space —
 * "ventricle, double-positive" is far easier to come back to a week later than
 * "Box 3".
 *
 * The targets are saved to a file beside the images. Nothing here reaches the
 * microscope: acting on a target belongs to the control application, which reads
 * that file.
 */
export default function TargetsPanel({
  targets,
  activeTool,
  color,
  visible,
  saveState,
  onTool,
  onColor,
  onVisible,
  onSelect,
  onDelete,
  onDescribe,
}) {
  const save = saveMessage(saveState);

  return (
    <section style={styles.panel} aria-label="selection panel">
      <div style={styles.heading}>selection</div>
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
          <input type="checkbox" checked={visible} onChange={onVisible} /> show on image
        </label>
      </div>
      <div style={styles.list}>
        {targets.length === 0 && (
          <div style={styles.empty}>Choose Point or Box, then click in the image.</div>
        )}
        {/* Gathered under a heading, the same shape the image data above uses: a
            group, then the individual places under it. There is one group today —
            the places marked by hand. Places the workflow finds for itself become a
            second group beside it, which is why the shape is here now rather than a
            flat list that would have to be rebuilt. */}
        {targets.length > 0 && (
          <div style={styles.groupHead}>
            <span style={styles.groupName}>marked by hand</span>
            <span style={styles.groupCount}>{targets.length}</span>
          </div>
        )}
        {targets.map((target, index) => (
          <div key={target.id} style={styles.target}>
            <button
              style={styles.name}
              onClick={() => onSelect(target.id)}
              title="Take the view back to this target"
            >
              {/* The name the operator typed wins over a number. A number is a
                  poor label for a place on a specimen, and it moves: delete the
                  second target and what was the third becomes "Box 2", so a note
                  written a week ago about "box 3" now points somewhere else. */}
              {target.description?.trim()
                || `${target.type === "point" ? "Point" : "Box"} ${index + 1}`}
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
      {save && (
        <div style={styles.status} aria-live="polite">
          <div style={{ ...styles.statusLine, ...styles[save.tone] }}>{save.text}</div>
        </div>
      )}
    </section>
  );
}

const styles = {
  // Sits below the layer list inside the single right-hand bar, so it takes the
  // bar's width and is capped in height: the layer list is what grows.
  panel: {
    padding: "14px 12px 12px",
    // A fixed share of the bar rather than however tall the list happens to be, so
    // the images above never get pushed off the top as targets are added.
    height: "34%",
    minHeight: 120,
    background: "var(--card-bg)",
    color: "var(--text-primary)",
    borderTop: "1px solid var(--panel-border)",
    font: "12px system-ui, sans-serif",
    overflow: "auto",
    display: "flex",
    flexDirection: "column",
    flexShrink: 0,
  },
  // The same small, quiet heading the other two sections use, so the bar reads as
  // three parts of one thing rather than as two panels bolted together.
  heading: {
    font: "600 11px/1 system-ui, sans-serif",
    letterSpacing: ".08em",
    textTransform: "uppercase",
    color: "var(--text-faint)",
    marginBottom: 10,
  },
  tools: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  button: {
    border: "1px solid var(--control-border)",
    borderRadius: 4,
    background: "var(--control-bg)",
    color: "var(--text-secondary)",
    padding: "5px 9px",
    cursor: "pointer",
  },
  active: {
    borderColor: "var(--accent)",
    background: "var(--accent-selection)",
    color: "var(--accent-selection-text)",
  },
  color: { width: 28, height: 27, padding: 1, border: "1px solid var(--control-border)", background: "none" },
  visible: { color: "var(--text-secondary)", display: "flex", gap: 4, alignItems: "center" },
  // Scrolls inside its own fixed share of the bar, so a long list of targets stays
  // where it is instead of pushing everything above it off the top.
  list: { marginTop: 10, display: "grid", gap: 5, overflowY: "auto", minHeight: 0 },
  groupHead: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    padding: "2px 0 4px",
    color: "var(--text-primary)",
    font: "600 11px/1 system-ui, sans-serif",
  },
  groupName: { letterSpacing: ".02em" },
  groupCount: { color: "var(--text-faint)", fontSize: 10, fontVariantNumeric: "tabular-nums" },
  empty: { color: "var(--text-muted)", lineHeight: 1.4, padding: "8px 2px" },
  // Three controls on the first row, then the name field spanning the full width
  // underneath, so a long note has room to be read.
  target: {
    marginLeft: 10,
    borderLeft: "2px solid var(--subtle-border)",
    paddingLeft: 6, display: "grid", gridTemplateColumns: "1fr auto", gap: 5, alignItems: "center", borderBottom: "1px solid var(--subtle-border)", paddingBottom: 6 },
  name: { textAlign: "left", border: 0, background: "none", color: "var(--text-primary)", cursor: "pointer", padding: 4 },
  delete: { border: 0, background: "none", color: "var(--danger-text)", fontSize: 18, cursor: "pointer" },
  description: {
    gridColumn: "1 / -1",
    border: "1px solid var(--subtle-border)",
    borderRadius: 3,
    background: "var(--input-bg)",
    color: "var(--text-secondary)",
    padding: "4px 6px",
    font: "11px system-ui, sans-serif",
  },
  status: { marginTop: "auto", paddingTop: 10, display: "grid", gap: 3, lineHeight: 1.4 },
  statusLine: { fontSize: 11 },
  quiet: { color: "var(--text-muted)" },
  bad: { color: "var(--danger-text)" },
};
