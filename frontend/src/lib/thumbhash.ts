import { thumbHashToDataURL } from "thumbhash";

/** Decode a base64 thumbhash (from photo_cache) to a blurred data URL.
 * Decoded URLs are memoized — cells re-render often (selection, virtualizer)
 * and decoding is pure.
 */
const cache = new Map<string, string>();

export function thumbhashToUrl(b64: string): string | undefined {
  let url = cache.get(b64);
  if (url) return url;
  try {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    url = thumbHashToDataURL(bytes);
  } catch {
    return undefined; // corrupt hash — fall back to the color placeholder
  }
  cache.set(b64, url);
  return url;
}
