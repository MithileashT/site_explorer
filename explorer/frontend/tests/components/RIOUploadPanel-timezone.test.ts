import { describe, it, expect } from "vitest";
import { localDatetimeToEpoch, getSystemTimezone, formatTimezoneLabel, getTimezoneShortLabel } from "@/lib/timezone-utils";

describe("RIOUploadPanel timezone conversion", () => {
  it("computes correct epoch for JST time input", () => {
    // User enters 2025-06-01T19:00 and selects Asia/Tokyo (UTC+9)
    // That's 2025-06-01T10:00 UTC
    const epoch = localDatetimeToEpoch("2025-06-01T19:00", "Asia/Tokyo");
    const expected = Math.floor(new Date("2025-06-01T10:00:00Z").getTime() / 1000);
    expect(epoch).toBe(expected);
  });

  it("computes correct epoch for IST time input", () => {
    // User enters 2025-06-01T15:30 and selects Asia/Kolkata (UTC+5:30)
    // That's 2025-06-01T10:00 UTC
    const epoch = localDatetimeToEpoch("2025-06-01T15:30", "Asia/Kolkata");
    const expected = Math.floor(new Date("2025-06-01T10:00:00Z").getTime() / 1000);
    expect(epoch).toBe(expected);
  });

  it("computes correct epoch for UTC time input", () => {
    const epoch = localDatetimeToEpoch("2025-06-01T10:00", "UTC");
    const expected = Math.floor(new Date("2025-06-01T10:00:00Z").getTime() / 1000);
    expect(epoch).toBe(expected);
  });

  it("getSystemTimezone returns current system IANA timezone", () => {
    const tz = getSystemTimezone();
    expect(tz.length).toBeGreaterThan(0);
    expect(tz === "UTC" || tz.includes("/")).toBe(true);
  });

  it("system timezone converts consistently through localDatetimeToEpoch", () => {
    const tz = getSystemTimezone();
    const epoch1 = localDatetimeToEpoch("2025-06-01T12:00", tz);
    const epoch2 = localDatetimeToEpoch("2025-06-01T12:00", tz);
    expect(epoch1).toBe(epoch2);
    expect(epoch1).toBeGreaterThan(0);
  });

  it("formatTimezoneLabel produces a readable label for system timezone", () => {
    const tz = getSystemTimezone();
    const label = formatTimezoneLabel(tz);
    expect(label).toContain(tz);
    expect(label).toContain("UTC");
  });

  it("getTimezoneShortLabel returns JST for Asia/Tokyo", () => {
    expect(getTimezoneShortLabel("Asia/Tokyo")).toBe("JST");
  });

  it("display fields for JST produce correct tar name structure", () => {
    const start = "2026-03-22T10:00";
    const end = "2026-03-22T11:00";
    const label = getTimezoneShortLabel("Asia/Tokyo");
    const fmt = (s: string) => s.replace("T", "_").replace(":", "-");
    const actual = `rosbags_${fmt(start)}_to_${fmt(end)}_${label}.tar.xz`;
    expect(actual).toBe("rosbags_2026-03-22_10-00_to_2026-03-22_11-00_JST.tar.xz");
  });

  it("display fields for IST produce correct tar name structure", () => {
    const start = "2026-03-22T15:30";
    const end = "2026-03-22T16:30";
    const label = getTimezoneShortLabel("Asia/Kolkata");
    const fmt = (s: string) => s.replace("T", "_").replace(":", "-");
    const actual = `rosbags_${fmt(start)}_to_${fmt(end)}_${label}.tar.xz`;
    expect(actual).toBe("rosbags_2026-03-22_15-30_to_2026-03-22_16-30_IST.tar.xz");
  });
});
