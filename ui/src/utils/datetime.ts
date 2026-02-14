const ISO_WITH_TZ_RE = /(Z|[+-]\d{2}:?\d{2})$/i;

function normalizeIsoTimestamp(input: string): string {
  const value = input.trim();
  if (!value) {
    return value;
  }

  // If timestamp is ISO-like but timezone-naive, assume UTC.
  if (/^\d{4}-\d{2}-\d{2}T/.test(value) && !ISO_WITH_TZ_RE.test(value)) {
    return `${value}Z`;
  }
  return value;
}

export function parseTimestamp(value: string | Date | null | undefined): Date | null {
  if (value == null) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  const normalized = normalizeIsoTimestamp(String(value));
  if (!normalized) return null;
  const dt = new Date(normalized);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

export function formatDateTime(value: string | Date | null | undefined): string {
  const dt = parseTimestamp(value);
  if (!dt) return '-';
  return dt.toLocaleString();
}

export function formatTime(value: string | Date | null | undefined): string {
  const dt = parseTimestamp(value);
  if (!dt) return '-';
  return dt.toLocaleTimeString();
}

export function getLocalTimeZoneLabel(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone || 'Local';
  } catch {
    return 'Local';
  }
}
