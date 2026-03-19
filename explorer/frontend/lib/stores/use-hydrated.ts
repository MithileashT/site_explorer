import { useEffect, useState } from "react";

/**
 * Returns false on server and on first client render (before hydration),
 * then true after Zustand has rehydrated from sessionStorage.
 */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return hydrated;
}
