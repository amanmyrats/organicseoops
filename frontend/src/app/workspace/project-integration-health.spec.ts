import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AccountApi } from '../account/account-api';
import { ProjectIntegrationHealth } from './project-integration-health';

function row(index = 0): Record<string, unknown> {
  return { connection_id: 80 + index, provider: 'google_search_console', connection_state: 'active', source_state: 'api_sync_metadata',
    sync: { status: 'succeeded', quota_state: 'available', error_category: '', fresh_through: '2026-09-29',
      last_attempt_at: '2026-10-01T10:00:00.100001Z', last_success_at: '2026-10-01T10:00:00.100002+00:00' } };
}
function response(rows = [row()], hasMore = false): { status: number; body: Record<string, unknown> } {
  return { status: 200, body: { method_version: 'integration-health-metadata-v1', project_id: 9,
    scope: 'bounded_connection_sync_metadata_not_readiness_staleness_regression_or_delivery_authority',
    assessed_at: '2026-10-01T10:00:00.100003Z', rows, has_more: hasMore } };
}
function setup() {
  const api = { projectIntegrationHealth: vi.fn(async () => response()) };
  TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(ProjectIntegrationHealth), component = fixture.componentInstance;
  component.organizationId = 7; component.projectId = 9; fixture.detectChanges();
  return { api, fixture, component };
}

describe('Deliberate integration metadata inspector', () => {
  it.each(['en', 'tr'] as const)('reads only explicitly and clones bounded states with honest missing, GA4, original-date and overflow meanings (%s)', async (language) => {
    const { api, fixture, component } = setup(); fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(api.projectIntegrationHealth).not.toHaveBeenCalled();
    fixture.nativeElement.querySelector('button').click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.projectIntegrationHealth).toHaveBeenCalledWith(7, 9);
    expect(fixture.nativeElement.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('li span')?.getAttribute('lang')).toBe('en');
    const retained = component.health(), reads = api.projectIntegrationHealth.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.health()).toBe(retained); expect(api.projectIntegrationHealth).toHaveBeenCalledTimes(reads);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Son kaydedilmiş başarılı toplama' : 'Last recorded successful collection');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'uyarı göndermez, uyarı onayını kaydetmez' : 'does not send alerts, save alert consent');
    const rows = ['api_sync_metadata', 'csv_only', 'reconnect_required', 'disconnected', 'unavailable',
      'scope_unavailable', 'authorization_unavailable', 'exact_origin_attribution_unavailable'].map((source_state, i) =>
      ({ ...row(i), source_state, sync: null, connection_state: ['disconnected', 'unavailable'].includes(source_state) ? source_state : 'active',
        provider: source_state === 'exact_origin_attribution_unavailable' ? 'google_analytics_4' : 'google_search_console' }));
    api.projectIntegrationHealth.mockResolvedValue(response(rows)); await component.inspect(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Senkronizasyon imleci kaydedilmemiş' : 'No sync cursor recorded');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'GA4 tam kaynak kökeni ilişkilendirmesi kullanılamıyor' : 'GA4 exact-origin attribution unavailable');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'nedenini kanıtlamaz' : 'does not establish why');
    rows[0].source_state = 'private mutation'; expect(component.health()?.rows[0].source_state).toBe('api_sync_metadata');
    const states = ['idle', 'running', 'waiting_provider', 'succeeded', 'partially_succeeded', 'failed', 'unavailable'];
    const syncRows = states.map((status, i) => ({ ...row(i), sync: { ...(row()['sync'] as object), status,
      last_success_at: null, error_category: ['idle', 'running', 'succeeded'].includes(status) ? '' : 'unclassified_failure',
      quota_state: ['available', 'limited', 'exhausted', 'unavailable'][i % 4] } }));
    api.projectIntegrationHealth.mockResolvedValue(response(syncRows)); await component.inspect(); fixture.detectChanges();
    expect(component.error()).toBe(false); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Başarılı toplama zaman damgası kaydedilmemiş' : 'No successful collection timestamp recorded');
    // Original successful dates can precede a later attempt; neither is the other one's coverage.
    api.projectIntegrationHealth.mockResolvedValue(response([{ ...row(), sync: { ...(row()['sync'] as object),
      last_success_at: '2026-09-01T10:00:00Z', fresh_through: '2026-09-30' } }]));
    await component.inspect(); expect(component.error()).toBe(false);
    api.projectIntegrationHealth.mockResolvedValue(response([], false)); await component.inspect(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'saklanmış bağlantı yok' : 'No retained connections');
    api.projectIntegrationHealth.mockResolvedValue(response(Array.from({ length: 50 }, (_, i) => row(i)), true));
    await component.inspect(); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'başka bağlantılar var' : 'additional connections exist');
  });

  it('rejects envelope, source-state, cursor, category, calendar, microsecond, identity and cap corruption without error prose', async () => {
    const { api, fixture, component } = setup();
    const invalid: ReturnType<typeof response>[] = [];
    for (const delta of [{ project_id: 10 }, { method_version: 'v2' }, { scope: 'readiness' }, { property: 'secret' },
      { has_more: 'false' }, { has_more: true }, { rows: null }, { assessed_at: '2026-02-29T10:00:00Z' }]) {
      invalid.push({ ...response(), body: { ...response().body, ...delta } });
    }
    for (const delta of [{ connection_id: true }, { connection_id: 0 }, { connection_id: 2 ** 53 }, { provider: 'unsupported' },
      { source_state: ['api_sync_metadata'] }, { source_state: 'toString' }, { credential_reference: 'secret' },
      { connection_state: 'disconnected' }, { source_state: 'csv_only' }, { source_state: 'disconnected' },
      { provider: 'google_analytics_4', source_state: 'exact_origin_attribution_unavailable' }, { sync: undefined }]) {
      invalid.push(response([{ ...row(), ...delta }]));
    }
    for (const delta of [{ status: 'unknown' }, { error_category: 'private provider error' }, { error_category: [''] },
      { quota_state: ['available'] }, { position: { secret: true } }, { status: 'failed', error_category: '' },
      { status: 'succeeded', error_category: 'handler_failed' }, { fresh_through: '2026-02-30' },
      { last_attempt_at: '2026-10-01T10:00:00.100004Z' }, { last_success_at: '2026-10-01T10:00:00.1234567Z' },
      { last_success_at: '2026-10-01T24:00:00Z' }, { last_success_at: '2026-10-01T10:00:00+01:00' }]) {
      invalid.push(response([{ ...row(), sync: { ...(row()['sync'] as object), ...delta } }]));
    }
    invalid.push(response([row(), row()]), response([row(1), row()]), response(Array.from({ length: 51 }, (_, i) => row(i))),
      { status: 403, body: { message: 'private server error' } });
    for (const value of invalid) {
      api.projectIntegrationHealth.mockResolvedValue(value); await component.inspect();
      expect(component.health()).toBeNull(); expect(component.error()).toBe(true); expect(component.busy()).toBe(false);
    }
    api.projectIntegrationHealth.mockRejectedValue(new Error('private network error')); await component.inspect(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('private network error');
    expect(fixture.nativeElement.textContent).toContain('unavailable for this project');
  });

  it('clears overlapping refresh, original scope mutation, parent refresh and destroyed late results', async () => {
    const { api, fixture, component } = setup(); await component.inspect();
    let resolve!: (value: ReturnType<typeof response>) => void;
    api.projectIntegrationHealth.mockImplementation(() => new Promise(done => resolve = done));
    const first = component.inspect(), finishFirst = resolve; expect(component.health()).toBeNull();
    const second = component.inspect(); finishFirst(response()); await first;
    expect(component.health()).toBeNull(); expect(component.busy()).toBe(true);
    resolve(response()); await second; expect(component.health()).not.toBeNull();
    const changed = component.inspect(); component.organizationId = 8; component.projectId = 10; component.ngOnChanges();
    resolve(response()); await changed; expect(component.health()).toBeNull(); expect(component.busy()).toBe(false);
    component.organizationId = 7; component.projectId = 9;
    const refreshed = component.inspect(); component.ngOnChanges(); resolve(response()); await refreshed;
    expect(component.health()).toBeNull();
    const destroyed = component.inspect(); fixture.destroy(); resolve(response()); await destroyed;
    expect(component.health()).toBeNull(); expect(component.error()).toBe(false); expect(component.busy()).toBe(false);
  });

  it('denies invalid native scope before requesting or entering loading state', async () => {
    const { api, component } = setup();
    for (const invalid of [0, -1, NaN, 2 ** 53]) {
      component.organizationId = invalid; await component.inspect(); expect(component.error()).toBe(true);
      component.organizationId = 7; component.projectId = invalid; await component.inspect();
      expect(component.health()).toBeNull(); expect(component.busy()).toBe(false); component.projectId = 9;
    }
    expect(api.projectIntegrationHealth).not.toHaveBeenCalled();
  });
});
