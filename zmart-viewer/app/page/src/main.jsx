import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
// The named colours both themes are built from; every component's styles
// refer to these names rather than to hex values.
import "./theme.css";

// Put the remembered theme on before anything is drawn. The choice lives in
// the browser's localStorage (under the same key the Light/Dark button
// writes), and reading it here -- before React renders a single element --
// means a page that was left light comes back light, with no dark flash on
// the way. Dark is the default: microscopy is looked at in dark rooms.
document.documentElement.dataset.theme =
  localStorage.getItem("zmart-theme") === "light" ? "light" : "dark";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
