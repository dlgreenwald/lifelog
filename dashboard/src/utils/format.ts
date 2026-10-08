/** Module-level user timezone — set once at app boot from user settings. */
let userTz: string = 'America/New_York';

/** Set the user's configured timezone. Call from App.tsx after fetching settings. */
export function setTimezone(tz: string): void {
  userTz = tz;
}

/** Get the current user timezone. */
export function getTimezone(): string {
  return userTz;
}

/**
 * Return today's date as a 'yyyy-MM-dd' string in the user's configured timezone.
 * Use this for API calls and URL params.
 */
export function todayKey(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: userTz });
}

/**
 * Convert a Date to a 'yyyy-MM-dd' string in the user's configured timezone.
 * Use for deriving day keys from arbitrary Date objects.
 */
export function dateKey(date: Date): string {
  return date.toLocaleDateString('en-CA', { timeZone: userTz });
}

/**
 * Format a 'yyyy-MM-dd' date string as a human-readable label (e.g. "Saturday, October 7")
 * in the user's configured timezone. Safe for date strings that are already in user-tz.
 */
export function formatDateLabel(dateStr: string): string {
  const [year, month, day] = dateStr.split('-').map(Number);
  return new Date(year, month - 1, day).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    timeZone: userTz,
  });
}

/**
 * Extract hours and minutes in the user's timezone from a UTC naive ISO string.
 * Returns an object with `h` (0-23) and `m` (0-59).
 */
export function getTimeParts(iso: string): { h: number; m: number } {
  const d = toUTCDate(iso);
  const str = d.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    timeZone: userTz,
  });
  const [h, m] = str.split(':').map(Number);
  return { h, m };
}

/**
 * Format a UTC naive ISO timestamp as 'HH:mm' in the user's timezone.
 */
export function formatTimeInTz(iso: string): string {
  const { h, m } = getTimeParts(iso);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/** Parse UTC timestamp — naive ISO strings (no Z/offset) are assumed UTC. */
export function toUTCDate(iso: string): Date {
  // PostgreSQL naive datetimes: "2026-08-22T00:27:21.498044" (no Z/offset)
  // JS new Date() would treat these as local time — wrong.
  // Append Z to force UTC parsing.
  const hasTimezone = iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso);
  return new Date(hasTimezone ? iso : iso + 'Z');
}

export function formatDateTime(iso: string): string {
  return toUTCDate(iso).toLocaleString('en-US', { timeZone: userTz });
}

export function formatTime(iso: string): string {
  return toUTCDate(iso).toLocaleTimeString('en-US', { timeZone: userTz });
}
