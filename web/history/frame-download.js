// Convert only the frozen displayed frame; ordinary playback never uses canvas.
export function safeCameraName(name) {
  const cleaned = (typeof name === "string" ? name : "").normalize("NFC")
    .replace(/[\p{Cc}\p{Cf}\p{Cs}<>:"/\\|?*]/gu, "-")
    .replace(/-+/g, "-").replace(/\s+/gu, " ");
  // Bound UTF-8 bytes as well as characters, leaving room for time/sequence.
  const encoder = new TextEncoder(); let limited = "", bytes = 0;
  for (const character of cleaned) {
    const size = encoder.encode(character).length;
    if (bytes + size > 128) break;
    limited += character; bytes += size;
  }
  return limited.replace(/^[-.\s]+|[-.\s]+$/gu, "") || "Camera";
}

export async function downloadFrame(snapshot, aspect) {
  const bitmap = await createImageBitmap(snapshot.blob);
  let canvas;
  try {
    const ratio = aspect === "original" ? bitmap.width / bitmap.height : aspect === "4:3" ? 4 / 3 : 16 / 9;
    // Preserve the native detail, bounded to 16 megapixels for large cameras.
    const width = Math.max(bitmap.width, bitmap.height * ratio);
    const height = width / ratio;
    const scale = Math.min(1, Math.sqrt(16000000 / (width * height)));
    canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error("Could not save this frame.")), "image/png"));
    canvas.width = canvas.height = 0;
    const stamp = new Date(snapshot.position).toISOString().replace(/[-:]/g, "").replace(".000", "");
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    // The prefix also avoids Windows reserved device filenames (CON, NUL, …).
    link.href = url; link.download = `oogies-${safeCameraName(snapshot.cameraName)}_${stamp}_f${snapshot.sequence}.png`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } finally { if (canvas) canvas.width = canvas.height = 0; bitmap.close(); }
}
