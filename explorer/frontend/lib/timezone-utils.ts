/** A timezone option for dropdowns. */
export interface TimezoneOption {
  value: string;   // IANA timezone ID e.g. "Asia/Tokyo"
  label: string;   // Display label e.g. "JST (Asia/Tokyo, UTC+09:00)"
  offset: number;  // UTC offset in minutes (for sorting)
}

/**
 * Common warehouse timezones covering all current OKS deployment regions.
 * Ordered by UTC offset ascending.
 */
export const COMMON_TIMEZONES: TimezoneOption[] = [
  { value: "America/Los_Angeles", label: "PT (Los Angeles, UTC-08/-07)", offset: -480 },
  { value: "America/New_York",    label: "ET (New York, UTC-05/-04)",    offset: -300 },
  { value: "UTC",                 label: "UTC",                          offset: 0 },
  { value: "Europe/London",       label: "GMT (Europe/London)",          offset: 0 },
  { value: "Europe/Berlin",       label: "CET (Europe/Berlin, UTC+01)",  offset: 60 },
  { value: "Asia/Kolkata",        label: "IST (Asia/Kolkata, UTC+05:30)", offset: 330 },
  { value: "Asia/Singapore",      label: "SGT (Asia/Singapore, UTC+08)", offset: 480 },
  { value: "Asia/Tokyo",          label: "JST (Asia/Tokyo, UTC+09:00)",  offset: 540 },
  { value: "Australia/Sydney",    label: "AEST (Sydney, UTC+10/+11)",    offset: 600 },
];

/**
 * Convert a `datetime-local` input value (e.g. "2025-06-01T10:00")
 * into a Unix epoch (seconds), interpreting the time as being in `tz`.
 *
 * Uses the Intl API to compute the correct offset for that specific instant
 * (handles DST transitions correctly).
 */
export function localDatetimeToEpoch(datetimeLocal: string, tz: string): number {
  const [datePart, timePart] = datetimeLocal.split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute] = timePart.split(":").map(Number);

  // Treat the input as UTC first, then adjust by the TZ offset
  const utcGuess = Date.UTC(year, month - 1, day, hour, minute, 0);
  const offsetMs = getOffsetAtInstant(utcGuess, tz);

  // wall = utc + offset → utc = wall - offset
  const epochMs = utcGuess - offsetMs;

  // Re-check: offset might differ at the actual instant (DST edge case)
  const offsetMs2 = getOffsetAtInstant(epochMs, tz);
  const epochMs2 = utcGuess - offsetMs2;

  return Math.floor(epochMs2 / 1000);
}

/**
 * Convert a Unix epoch (seconds) to a `datetime-local` string
 * in the given timezone.
 */
export function epochToLocalDatetime(epoch: number, tz: string): string {
  const d = new Date(epoch * 1000);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);

  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

/**
 * Given a datetime-local string and timezone, return a human-readable
 * UTC equivalent like "2025-06-01 01:00 UTC".
 */
export function formatUtcPreview(datetimeLocal: string, tz: string): string {
  if (!datetimeLocal) return "";
  const epoch = localDatetimeToEpoch(datetimeLocal, tz);
  const d = new Date(epoch * 1000);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
  );
}

/**
 * Get the current UTC offset in minutes for a timezone.
 * Positive = east of UTC (e.g. JST = +540).
 */
export function getTimezoneOffsetMinutes(tz: string): number {
  return Math.round(getOffsetAtInstant(Date.now(), tz) / 60_000) || 0;
}

/**
 * Map a device's utc_offset_minutes (from backend) to the best
 * matching IANA timezone from COMMON_TIMEZONES.
 */
export function offsetMinutesToIana(offsetMinutes: number): string {
  const match = COMMON_TIMEZONES.find((t) => t.offset === offsetMinutes);
  return match?.value ?? "UTC";
}

/**
 * Detect the system/browser's IANA timezone.
 * e.g. "Asia/Kolkata", "America/New_York", "Europe/Berlin"
 */
export function getSystemTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

/**
 * Format an IANA timezone ID into a human-readable label with UTC offset.
 * e.g. "Asia/Kolkata (UTC+05:30)" or "UTC (UTC+00:00)"
 */
export function formatTimezoneLabel(tz: string): string {
  const offsetMin = getTimezoneOffsetMinutes(tz);
  const sign = offsetMin >= 0 ? "+" : "-";
  const absMin = Math.abs(offsetMin);
  const h = Math.floor(absMin / 60).toString().padStart(2, "0");
  const m = (absMin % 60).toString().padStart(2, "0");
  return `${tz} (UTC${sign}${h}:${m})`;
}

/**
 * Return a short display label for a timezone, suitable for use in filenames.
 * Uses the known label from COMMON_TIMEZONES (e.g. "JST") if available,
 * otherwise falls back to "UTC+HH:MM" format.
 */
export function getTimezoneShortLabel(tz: string): string {
  const match = COMMON_TIMEZONES.find((t) => t.value === tz);
  if (match) {
    // label format: "JST (Asia/Tokyo, UTC+09:00)" — take the first word
    return match.label.split(" ")[0];
  }
  // Unknown TZ — format as UTC±HH:MM
  const offsetMin = getTimezoneOffsetMinutes(tz);
  const sign = offsetMin >= 0 ? "+" : "-";
  const absMin = Math.abs(offsetMin);
  const h = Math.floor(absMin / 60).toString().padStart(2, "0");
  const m = (absMin % 60).toString().padStart(2, "0");
  return `UTC${sign}${h}:${m}`;
}

// ── Internal ────────────────────────────────────────────────────────────────

/**
 * Compute the UTC offset (in milliseconds) for a given IANA timezone
 * at a specific instant (UTC ms timestamp).
 */
function getOffsetAtInstant(utcMs: number, tz: string): number {
  const d = new Date(utcMs);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    second: "numeric",
    hour12: false,
  }).formatToParts(d);

  const get = (type: string) => parseInt(parts.find((p) => p.type === type)?.value ?? "0", 10);
  const localMs = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour") === 24 ? 0 : get("hour"),
    get("minute"),
    get("second"),
  );
  return localMs - utcMs;
}
