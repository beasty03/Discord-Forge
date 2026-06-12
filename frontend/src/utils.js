/**
 * Format a UTC ISO timestamp string in the given IANA timezone.
 * Returns "YYYY-MM-DD HH:MM" by default, or just date/time when opts restrict it.
 */
export function fmtDate(iso, tz = 'UTC', { timeOnly = false, dateOnly = false } = {}) {
  if (!iso || iso === '—') return iso || '—';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    // en-CA gives YYYY-MM-DD, en-GB gives HH:MM in 24h
    const datePart = !timeOnly
      ? new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d)
      : '';
    const timePart = !dateOnly
      ? new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false }).format(d)
      : '';
    if (timeOnly) return timePart;
    if (dateOnly) return datePart;
    return `${datePart} ${timePart}`;
  } catch {
    return (iso?.slice?.(0, 16) ?? String(iso)).replace('T', ' ');
  }
}
