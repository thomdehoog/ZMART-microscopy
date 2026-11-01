/** How far one acquisition is published: how many stores were acquired, how many the viewer has, and its state. */
interface Publication {
  acquired?: number;
  published?: number;
  state?: string;
}

/** Publication acknowledges data available to the viewer, not rendered pixels. */
export function showPublicationStatus(
  note: Pick<HTMLElement, "textContent" | "hidden">,
  status: { publications?: Record<string, Publication>; error?: string } | null | undefined,
): void {
  const pending = Object.entries(status?.publications ?? {})
    .filter(([, progress]) => progress.state !== "ready")
    .map(([name, progress]) => `${name}: ${progress.published}/${progress.acquired} stores available (${progress.state})`);
  if (status?.error) pending.push(status.error);
  note.textContent = pending.join(" · ");
  note.hidden = pending.length === 0;
}
