import { useEffect, useRef } from "react";
import type { RefObject } from "react";

/**
 * Attaches a mousedown listener that calls onClose when the user clicks
 * outside the returned element ref. Only active when `enabled` is true.
 */
export function useOutsideClick<T extends HTMLElement>(
  enabled: boolean,
  onClose: () => void
): RefObject<T | null> {
  const ref = useRef<T>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    if (enabled) {
      document.addEventListener("mousedown", handle);
      return () => document.removeEventListener("mousedown", handle);
    }
  }, [enabled, onClose]);

  return ref;
}
