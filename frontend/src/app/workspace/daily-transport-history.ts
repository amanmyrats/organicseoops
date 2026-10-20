import { calendar, microseconds } from './utc-date';

export type DailyDelivery = { id: number; day_start: string; created_at: string; attempted_at: string | null;
  accepted_at: string | null; state: 'queued' | 'sending' | 'transport_accepted' | 'skipped' | 'unknown'; error_category: string };
export type DailyHistory = { method_version: string; project_id: number; scope: string; rows: DailyDelivery[]; has_more: boolean };

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function readDailyTransportHistory(body: Record<string, unknown>, project: number, method: string, scope: string): DailyHistory | null {
  if (Object.keys(body).sort().join(',') !== 'has_more,method_version,project_id,rows,scope'
      || body['project_id'] !== project || body['method_version'] !== method || body['scope'] !== scope
      || !Array.isArray(body['rows']) || body['rows'].length > 20 || typeof body['has_more'] !== 'boolean'
      || body['has_more'] && body['rows'].length !== 20) return null;
  const ids = new Set<number>(); let previousDay = Infinity;
  for (const row of body['rows']) {
    if (!record(row) || Object.keys(row).sort().join(',') !== 'accepted_at,attempted_at,created_at,day_start,error_category,id,state'
        || !Number.isSafeInteger(row['id']) || Number(row['id']) < 1 || ids.has(Number(row['id']))
        || typeof row['error_category'] !== 'string') return null;
    const day = calendar(row['day_start']), created = microseconds(row['created_at']),
      attempted = microseconds(row['attempted_at']), accepted = microseconds(row['accepted_at']),
      creationDay = calendar(typeof row['created_at'] === 'string' ? row['created_at'].slice(0, 10) : null);
    if (day === null || creationDay === null || day >= creationDay || day >= previousDay || created === null
        || row['attempted_at'] !== null && attempted === null || row['accepted_at'] !== null && accepted === null
        || attempted !== null && attempted < created || accepted !== null && (attempted === null || accepted < attempted)) return null;
    const state = row['state'], category = row['error_category'];
    if (state === 'queued' ? attempted !== null || accepted !== null || category !== ''
      : state === 'sending' ? attempted === null || accepted !== null || category !== ''
      : state === 'transport_accepted' ? attempted === null || accepted === null || category !== ''
      : state === 'skipped' ? attempted === null || accepted !== null || category !== 'current_source_or_recipient_changed'
      : state === 'unknown' ? attempted === null || accepted !== null || !['delivery_uncertain', 'worker_outcome_unknown'].includes(category)
      : true) return null;
    ids.add(Number(row['id'])); previousDay = day;
  }
  return structuredClone(body) as DailyHistory;
}
