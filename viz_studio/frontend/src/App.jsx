import React from "react";
import NeuroglancerView from "./NeuroglancerView.jsx";

/**
 * The whole application shell.
 *
 * For now this is deliberately just the viewer filling the window, plus a thin
 * header. The control panel (layers, brightness, 2-D/3-D, and so on) will grow
 * on the left in the next step; the point of this stage is to prove the engine
 * mounts and shows the volume inside our own React app.
 */
export default function App() {
  const handleReady = React.useCallback((viewer) => {
    // Expose the live viewer for quick inspection and for the automated browser
    // test. Handy during the spike; not something a shipped build relies on.
    window.zmartViewer = viewer;
  }, []);

  return (
    <div style={{ position: "absolute", inset: 0, color: "#e6e8eb" }}>
      <div style={{ position: "absolute", inset: 0 }}>
        <NeuroglancerView onReady={handleReady} />
      </div>
    </div>
  );
}
