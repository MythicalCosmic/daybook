/**
 * Shrink a phone photo before it travels: a 12-megapixel Z-report shot is 4–6 MB, which a
 * basement connection may never get through, and 1600 px is plenty to read every line. The
 * server re-encodes images anyway. Anything that can't be decoded here goes as it is.
 */

const MAX_SIDE = 1600;
const QUALITY = 0.82;
/** Small enough already: leave it alone. */
const SMALL = 700 * 1024;

async function decode(file: File): Promise<{ source: CanvasImageSource; width: number; height: number; done: () => void } | null> {
  if (typeof createImageBitmap === "function") {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      return { source: bitmap, width: bitmap.width, height: bitmap.height, done: () => bitmap.close() };
    } catch {
      // Fall through to an <img>, which more engines decode.
    }
  }
  if (typeof Image === "undefined" || typeof URL.createObjectURL !== "function") return null;
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return { source: image, width: image.naturalWidth, height: image.naturalHeight, done: () => URL.revokeObjectURL(url) };
  } catch {
    URL.revokeObjectURL(url);
    return null;
  }
}

export async function downscale(file: File, maxSide = MAX_SIDE): Promise<File> {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  const image = await decode(file);
  if (!image) return file;
  try {
    const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
    if (scale === 1 && file.size <= SMALL) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(image.source, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", QUALITY));
    if (!blob || blob.size >= file.size) return file;
    const name = file.name.replace(/\.[^.]+$/, "") || "photo";
    return new File([blob], `${name}.jpg`, { type: "image/jpeg", lastModified: file.lastModified });
  } catch {
    return file;
  } finally {
    image.done();
  }
}
