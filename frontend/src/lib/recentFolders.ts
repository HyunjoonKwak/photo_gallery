import type { PhotoFolder } from "../api/types";

/** Recently used destination folders (folder picker shortcut).
 * Persisted in localStorage; newest first, deduped by id, capped small —
 * repeat organizing sessions usually target the same few folders.
 */
const KEY = "nasphoto.recentFolders";
const MAX = 6;

export function recentFolders(): PhotoFolder[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((f) => f && f.id && f.name) : [];
  } catch {
    return [];
  }
}

export function rememberFolder(folder: PhotoFolder): void {
  try {
    const next = [
      folder,
      ...recentFolders().filter((f) => f.id !== folder.id),
    ].slice(0, MAX);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // persistence is best-effort
  }
}
