/** Refresh decoded chunks only for the stores whose published contents changed. */
export function refreshSources(chunkManager, sources) {
  const folders = [...sources].map(url => url.split("|")[0]);
  if (!folders.length) return 0;
  const refreshed = new Set();
  for (const [key, holder] of chunkManager.memoize.map) {
    if (!key.includes('"constructorId"') || !folders.some(folder => key.includes(folder))) continue;
    if (typeof holder?.invalidateCache !== "function" || refreshed.has(holder)) continue;
    holder.invalidateCache();
    refreshed.add(holder);
  }
  return refreshed.size;
}
