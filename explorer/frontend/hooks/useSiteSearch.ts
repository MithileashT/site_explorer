/** Pure filter function — testable without React. */
export function filterSites(
  sites: { id: string; name: string }[],
  query: string
): { id: string; name: string }[] {
  const q = query.toLowerCase().trim();
  if (!q) return sites;
  const prefix: { id: string; name: string }[] = [];
  const substring: { id: string; name: string }[] = [];
  for (const s of sites) {
    const label = s.id.toLowerCase();
    if (label.startsWith(q)) prefix.push(s);
    else if (label.includes(q)) substring.push(s);
  }
  return [...prefix, ...substring];
}

import { useState, useMemo } from "react";

/**
 * Manages the search query and filtered site list for the site combobox.
 *
 * @param sites - Full site list from API.
 * @returns query state + setter + filtered results.
 */
export function useSiteSearch(sites: { id: string; name: string }[]) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(
    () => filterSites(sites, query),
    [sites, query]
  );

  return { query, setQuery, filtered };
}
