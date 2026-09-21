/** Keep a failed preview distinguishable from an image with no signal. */
export function previewMessage(paint, width, height, message) {
  paint.save();
  paint.fillStyle = "#05090e";
  paint.fillRect(0, 0, width, height);
  paint.fillStyle = "#ffffff";
  paint.font = `${Math.max(12, Math.round(width / 24))}px sans-serif`;
  paint.textAlign = "center";
  paint.textBaseline = "middle";
  paint.fillText(message, width / 2, height / 2, width * 0.9);
  paint.restore();
}
