/**
 * The product's marks in the browser: the favicon (with a red dot while critical notifications
 * wait), `<html data-edition>` (Davomat's palette, styles/../core/edition.css) and the theme color.
 * Daybook keeps its round check mark; Davomat shows the organization's logo when it has one, else
 * its own mark (a bold D with a check cut into it).
 */
import { editionInfo, isDavomat, productName } from "@/core/edition";

export const DAYBOOK_FAVICON = "/dashboard/favicon.svg";

const DAYBOOK_BADGED =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 50"><circle cx="21" cy="21" r="21" fill="#c67139"/><path d="M12.25 21.9 18.4 28 29.6 15.8" fill="none" stroke="#f5ead8" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="39" cy="11" r="11" fill="#d93a26" stroke="#fff" stroke-width="3"/></svg>';

/**
 * Davomat's mark on a 48 × 48 tile: a white D (for Davomat) with a check cut into it (someone came),
 * on an indigo tile lit from the top. The check is painted with the tile's own gradient, so it reads
 * as a cut without a mask. DavomatMark.vue and the server's first paint (apps/core/spa.py) draw the
 * same shapes; a backend test keeps spa.py in step with these.
 */
export const DAVOMAT_MARK = {
  from: "#6c69f7",
  to: "#4136d6",
  d: "M14 15.5A3.5 3.5 0 0 1 17.5 12H22a12 12 0 0 1 0 24h-4.5A3.5 3.5 0 0 1 14 32.5Z",
  check: "M18.6 24.3l3.4 3.4 6.8-7.1",
} as const;

/** Davomat's mark as SVG markup (the favicon and the sidebar; the sign-in page draws DavomatMark.vue). */
export function davomatMark(badged = false): string {
  const { from, to, d, check } = DAVOMAT_MARK;
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">' +
    `<defs><linearGradient id="dg" gradientUnits="userSpaceOnUse" x1="7.2" y1="0" x2="40.8" y2="48"><stop offset="0" stop-color="${from}"/><stop offset="1" stop-color="${to}"/></linearGradient>` +
    '<linearGradient id="dh" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".2"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>' +
    '<rect width="48" height="48" rx="13.5" fill="url(#dg)"/>' +
    `<path d="${d}" fill="#fff"/>` +
    `<path d="${check}" fill="none" stroke="url(#dg)" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>` +
    '<rect width="48" height="48" rx="13.5" fill="url(#dh)"/>' +
    '<rect x=".5" y=".5" width="47" height="47" rx="13" fill="none" stroke="#fff" stroke-opacity=".1"/>' +
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
