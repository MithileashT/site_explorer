/**
 * vitest setup — provides a sessionStorage mock compatible with happy-dom
 * and resets it between every test so stores start clean.
 */
import { beforeEach } from "vitest";

// happy-dom provides sessionStorage but we reset it before each test
beforeEach(() => {
  sessionStorage.clear();
});
