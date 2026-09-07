const EASTERN = 'America/New_York';

/** Parse UTC timestamp — naive ISO strings (no Z/offset) are assumed UTC. */
export function toUTCDate(iso: string): Date {
  // PostgreSQL naive datetimes: "2026-08-22T00:27:21.498044" (no Z)
  // JS new Date() would treat these as local time — wrong.
  // Append Z to force UTC parsing.
  const hasTimezone = iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso);
  return new Date(hasTimezone ? iso : iso + 'Z');
}

export function formatDateTime(iso: string): string {
  return toUTCDate(iso).toLocaleString('en-US', { timeZone: EASTERN });
}

export function formatTime(iso: string): string {
  return toUTCDate(iso).toLocaleTimeString('en-US', { timeZone: EASTERN });
}
