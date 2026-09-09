/** Publication acknowledges data available to the viewer, not rendered pixels. */
export function showPublicationStatus(note, status) {
  const pending = Object.entries(status?.publications ?? {})
    .filter(([, progress]) => progress.state !== "ready")
    .map(([name, progress]) => `${name}: ${progress.published}/${progress.acquired} stores available (${progress.state})`);
  if (status?.error) pending.push(status.error);
  note.textContent = pending.join(" · ");
  note.hidden = pending.length === 0;
}
