// Preserve original Python UTC calendar dates and microseconds in private DTOs.
export function calendar(value: unknown): number | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return null;
  const date = Date.parse(value + 'T00:00:00Z');
  return Number.isFinite(date) && new Date(date).toISOString().slice(0, 10) === value ? date : null;
}

export function microseconds(value: unknown): bigint | null {
  if (typeof value !== 'string') return null;
  const match = /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
  if (!match || calendar(match[1]) === null) return null;
  const millis = Date.parse(value);
  return Number.isFinite(millis) ? BigInt(millis) * 1000n + BigInt(Number((match[2] || '').padEnd(6, '0')) % 1000) : null;
}
