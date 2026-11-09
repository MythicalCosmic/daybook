/**
 * The product's marks in the browser: the favicon (with a red dot while critical notifications
 * wait), `<html data-edition>` (Davomat's palette, styles/../core/edition.css) and the theme color.
 * Daybook keeps its round check mark; Davomat shows the organization's logo when it has one, else
 * its own mark (a check inside the corners of a face scan).
 */
import { editionInfo, isDavomat, productName } from "@/core/edition";

export const DAYBOOK_FAVICON = "/dashboard/favicon.svg";

const DAYBOOK_BADGED =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50"><circle cx="21" cy="21" r="21" fill="#c67139"/><path d="M12.25 21.9 18.4 28 29.6 15.8" fill="none" stroke="#f5ead8" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="39" cy="11" r="11" fill="#d93a26" stroke="#fff" stroke-width="3"/></svg>';

/** Davomat's mark as SVG markup (the sign-in page and the setup wizard draw the same one). */
export function davomatMark(badged = false): string {
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">' +
    '<defs><linearGradient id="dg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6d6af6"/><stop offset="1" stop-color="#3f3bd0"/></linearGradient></defs>' +
    '<rect width="48" height="48" rx="13" fill="url(#dg)"/>' +
    '<path d="M13.5 19.5v-3.2a2.8 2.8 0 0 1 2.8-2.8h3.2M28.5 13.5h3.2a2.8 2.8 0 0 1 2.8 2.8v3.2M34.5 28.5v3.2a2.8 2.8 0 0 1-2.8 2.8h-3.2M19.5 34.5h-3.2a2.8 2.8 0 0 1-2.8-2.8v-3.2" fill="none" stroke="#fff" stroke-opacity=".82" stroke-width="2.6" stroke-linecap="round"/>' +
    '<path d="M18.6 24.4l3.9 3.9 7.9-8.3" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>' +
    (badged ? '<circle cx="39" cy="9" r="8.5" fill="#e5383b" stroke="#fff" stroke-width="3"/>' : "") +
    "</svg>"
  );
}

const asDataUrl = (svg: string) => `data:image/svg+xml,${encodeURIComponent(svg)}`;

/** A logo with a red dot in its corner, drawn on a canvas (null when it can't be: another origin, no canvas). */
function badgedLogo(src: string): Promise<string | null> {
  return new Promise((resolve) => {
    try {
      const image = new Image();
      image.onload = () => {
        try {
          const size = 64;
          const canvas = document.createElement("canvas");
          canvas.width = size;
          canvas.height = size;
          const context = canvas.getContext("2d");
          if (!context) return resolve(null);
          context.beginPath();
          context.roundRect?.(0, 0, size, size, 14);
          context.clip();
          context.drawImage(image, 0, 0, size, size);
          context.beginPath();
          context.arc(size - 13, 13, 11, 0, Math.PI * 2);
          context.fillStyle = "#e5383b";
          context.fill();
          context.lineWidth = 4;
          context.strokeStyle = "#ffffff";
          context.stroke();
          resolve(canvas.toDataURL("image/png"));
        } catch {
          resolve(null);
        }
      };
      image.onerror = () => resolve(null);
      image.src = src;
    } catch {
      resolve(null);
    }
  });
}

/** The favicon's address for the edition shown now. */
export async function faviconHref(badged: boolean): Promise<string> {
  if (!isDavomat()) return badged ? asDataUrl(DAYBOOK_BADGED) : DAYBOOK_FAVICON;
  const logo = editionInfo.value.organization?.logo_url;
  if (logo) {
    if (!badged) return logo;
    const drawn = await badgedLogo(logo);
    if (drawn) return drawn;
  }
  return asDataUrl(davomatMark(badged));
}

let favicon = 0;

/** Points `<link rel="icon">` at the right mark (the latest call wins when a logo takes a moment). */
export async function setFavicon(badged: boolean): Promise<void> {
  const mine = ++favicon;
  const href = await faviconHref(badged);
  if (mine !== favicon) return;
  const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) return;
  if (href.startsWith("data:image/png") || (!href.startsWith("data:") && isDavomat())) link.removeAttribute("type");
  else link.type = "image/svg+xml";
  link.href = href;
}

export { productName };

/** Marks `<html>` with the edition (its palette) and sets the first title and favicon. Once at startup. */
export function applyBrand(): void {
  const root = document.documentElement;
  root.dataset.edition = editionInfo.value.edition;
  if (isDavomat()) {
    document.title = editionInfo.value.organization ? `${editionInfo.value.organization.name} · ${productName()}` : productName();
    void setFavicon(false);
  }
}
