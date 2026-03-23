import { describe, it, expect } from "vitest";
import {
  COMMON_TIMEZONES,
  localDatetimeToEpoch,
  epochToLocalDatetime,
  formatUtcPreview,
  getTimezoneOffsetMinutes,
  getSystemTimezone,
  formatTimezoneLabel,
  getTimezoneShortLabel,
} from "@/lib/timezone-utils";

describe("timezone-utils", () => {
  describe("COMMON_TIMEZONES", () => {
    it("includes UTC", () => {
      expect(COMMON_TIMEZONES.some((tz) => tz.value === "UTC")).toBe(true);
    });
    it("includes Asia/Tokyo (JST)", () => {
      expect(COMMON_TIMEZONES.some((tz) => tz.value === "Asia/Tokyo")).toBe(true);
    });
    it("includes Asia/Kolkata (IST)", () => {
      expect(COMMON_TIMEZONES.some((tz) => tz.value === "Asia/Kolkata")).toBe(true);
    });
  });

  describe("localDatetimeToEpoch", () => {
    it("converts datetime-local string to epoch using given IANA timezone", () => {
      // 2025-06-01T10:00 in Asia/Tokyo (UTC+9) = 2025-06-01T01:00 UTC
      const epoch = localDatetimeToEpoch("2025-06-01T10:00", "Asia/Tokyo");
      const expected = Math.floor(new Date("2025-06-01T01:00:00Z").getTime() / 1000);
      expect(epoch).toBe(expected);
    });

    it("treats UTC timezone correctly", () => {
      const epoch = localDatetimeToEpoch("2025-06-01T10:00", "UTC");
      expect(epoch).toBe(Math.floor(new Date("2025-06-01T10:00:00Z").getTime() / 1000));
    });

    it("handles IST (UTC+5:30) correctly", () => {
      // 2025-06-01T15:30 in IST = 2025-06-01T10:00 UTC
      const epoch = localDatetimeToEpoch("2025-06-01T15:30", "Asia/Kolkata");
      const expected = Math.floor(new Date("2025-06-01T10:00:00Z").getTime() / 1000);
      expect(epoch).toBe(expected);
    });
  });

  describe("epochToLocalDatetime", () => {
    it("converts epoch to datetime-local string in the given timezone", () => {
      const epoch = Math.floor(new Date("2025-06-01T01:00:00Z").getTime() / 1000);
      const result = epochToLocalDatetime(epoch, "Asia/Tokyo");
      expect(result).toBe("2025-06-01T10:00");
    });

    it("round-trips correctly", () => {
      const original = "2025-06-15T14:30";
      const epoch = localDatetimeToEpoch(original, "Asia/Tokyo");
      const roundTripped = epochToLocalDatetime(epoch, "Asia/Tokyo");
      expect(roundTripped).toBe(original);
    });
  });

  describe("formatUtcPreview", () => {
    it("formats a datetime-local string as a UTC preview string", () => {
      const preview = formatUtcPreview("2025-06-01T10:00", "Asia/Tokyo");
      expect(preview).toContain("01:00");
      expect(preview).toContain("UTC");
    });

    it("returns empty for empty input", () => {
      expect(formatUtcPreview("", "UTC")).toBe("");
    });
  });

  describe("getTimezoneOffsetMinutes", () => {
    it("returns offset minutes for Asia/Tokyo", () => {
      const offset = getTimezoneOffsetMinutes("Asia/Tokyo");
      expect(offset).toBe(540);
    });

    it("returns 0 for UTC", () => {
      expect(getTimezoneOffsetMinutes("UTC")).toBe(0);
    });
  });

  describe("getSystemTimezone", () => {
    it("returns a non-empty IANA timezone string", () => {
      const tz = getSystemTimezone();
      expect(typeof tz).toBe("string");
      expect(tz.length).toBeGreaterThan(0);
      expect(tz === "UTC" || tz.includes("/")).toBe(true);
    });
  });

  describe("formatTimezoneLabel", () => {
    it("formats Asia/Kolkata with offset", () => {
      const label = formatTimezoneLabel("Asia/Kolkata");
      expect(label).toContain("Asia/Kolkata");
      expect(label).toContain("+05:30");
    });

    it("formats UTC correctly", () => {
      const label = formatTimezoneLabel("UTC");
      expect(label).toContain("UTC");
      expect(label).toContain("+00:00");
    });

    it("formats Asia/Tokyo with +09:00", () => {
      const label = formatTimezoneLabel("Asia/Tokyo");
      expect(label).toContain("+09:00");
    });
  });

  describe("getTimezoneShortLabel", () => {
    it("returns JST for Asia/Tokyo", () => {
      expect(getTimezoneShortLabel("Asia/Tokyo")).toBe("JST");
    });

    it("returns IST for Asia/Kolkata", () => {
      expect(getTimezoneShortLabel("Asia/Kolkata")).toBe("IST");
    });

    it("returns UTC for UTC", () => {
      expect(getTimezoneShortLabel("UTC")).toBe("UTC");
    });

    it("returns offset-based label for unknown IANA TZ", () => {
      // Asia/Dhaka is not in COMMON_TIMEZONES → "UTC+06:00"
      const label = getTimezoneShortLabel("Asia/Dhaka");
      expect(label).toMatch(/^UTC[+-]\d{2}:\d{2}$/);
    });
  });
});
