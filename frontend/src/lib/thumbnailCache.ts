/** Browser-side thumbnail cache ownership.
 *
 * The backend disk cache is already keyed by account, but CacheStorage keys
 * only by URL.  An opaque, server-issued session scope in every thumbnail URL
 * prevents a shared browser from serving account A's response to account B.
 * This token is cache partitioning only; the server session remains the
 * authorization boundary.
 */

let ownerToken = "";

export function setThumbnailCacheOwner(scope: string | null): void {
  ownerToken = scope ?? "";
}

export function getThumbnailCacheOwner(): string {
  return ownerToken;
}

const ACTIVE_CACHE = "thumbs-v2";
const LEGACY_CACHES = new Set(["thumbs"]);

async function deleteMatchingCaches(predicate: (name: string) => boolean) {
  if (!("caches" in globalThis)) return;
  const names = await globalThis.caches.keys();
  await Promise.all(names.filter(predicate).map((name) => globalThis.caches.delete(name)));
}

/** Remove every account's runtime thumbnails on logout/account transition. */
export async function clearThumbnailCaches(): Promise<void> {
  await deleteMatchingCaches(
    (name) => name === ACTIVE_CACHE || LEGACY_CACHES.has(name),
  );
}

/** One-way cleanup for the unpartitioned cache used by older app builds. */
export async function clearLegacyThumbnailCaches(): Promise<void> {
  await deleteMatchingCaches((name) => LEGACY_CACHES.has(name));
}
