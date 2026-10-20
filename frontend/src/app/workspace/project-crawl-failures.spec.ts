import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AccountApi } from '../account/account-api';
import { ProjectCrawlFailures } from './project-crawl-failures';

function row(index = 0) {
  return { job_id: 80 - index, source_method: 'crawl-http-v2', created_at: '2026-10-01T10:00:00.100001+00:00',
    status_updated_at: '2026-10-01T10:00:00.100002+00:00', failure_category: 'handler_failed' };
}
function response(rows = [row()], hasMore = false): { status: number; body: Record<string, unknown> } {
  return { status: 200, body: { method_version: 'retained-crawl-failures-v1', project_id: 9,
    scope: 'retained_failed_crawl_jobs_not_current_incident_regression_or_retry_authority',
    assessed_at: '2026-10-01T10:00:00.100003Z', rows, has_more: hasMore } };
}
function setup() {
  const api = { projectCrawlFailures: vi.fn(async () => response()) };
  TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(ProjectCrawlFailures), component = fixture.componentInstance;
  component.organizationId = 7; component.projectId = 9; fixture.detectChanges();
  return { api, fixture, component };
}

describe('Explicit retained crawl failure inspector', () => {
  it.each(['en', 'tr'] as const)('does not read on entry and explicitly renders cloned minimized history, empty and overflow with original meanings (%s)', async (language) => {
    const { api, fixture, component } = setup(); fixture.componentRef.setInput('language', language); component.ngOnChanges();
    expect(api.projectCrawlFailures).not.toHaveBeenCalled(); expect(component.history()).toBeNull();
    fixture.nativeElement.querySelector('button').click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.projectCrawlFailures).toHaveBeenCalledWith(7, 9);
    expect(fixture.nativeElement.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('li span')?.getAttribute('lang')).toBe('en');
    const retained = component.history(), reads = api.projectCrawlFailures.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.history()).toBe(retained); expect(api.projectCrawlFailures).toHaveBeenCalledTimes(reads);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'İş 80' : 'Job 80');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'ilk hata veya tamamlanma zamanını kanıtlamaz' : 'not a proven first-failure or completion time');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'uyarı göndermez, uyarı onayını kaydetmez' : 'does not send an alert, save alert consent');
    const rows = ['handler_failed', 'crawl_deadline', 'robots_unavailable', 'crawl_incomplete', 'unclassified_failure']
      .map((failure_category, i) => ({ ...row(i), failure_category, source_method: i === 0 ? 'crawl-http-v1' : 'crawl-http-v2' }));
    api.projectCrawlFailures.mockResolvedValue(response(rows)); await component.inspect(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Sınıflandırılmamış kayıtlı hata; ayrıntılar kullanılamıyor' : 'Unclassified stored failure; details unavailable');
    rows[0].created_at = 'private mutation'; expect(component.history()?.rows[0].created_at).not.toBe('private mutation');
    api.projectCrawlFailures.mockResolvedValue(response([], false)); await component.inspect(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Eşleşen saklanmış hata yok' : 'No matching retained failures');
    api.projectCrawlFailures.mockResolvedValue(response(Array.from({ length: 20 }, (_, i) => row(i)), true));
    await component.inspect(); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'daha eski eşleşen kayıtlar var' : 'older matching records exist');
  });

  it('fails closed on exact envelope/row/scope/category/calendar/microsecond/order/identity/cap violations and private errors', async () => {
    const { api, component, fixture } = setup();
    const invalid: ReturnType<typeof response>[] = [];
    for (const delta of [{ project_id: 10 }, { method_version: 'v2' }, { scope: 'current_incident' }, { recipient_id: 1 },
      { has_more: 'false' }, { has_more: true }, { rows: null }, { assessed_at: '2026-02-29T10:00:00Z' },
      { assessed_at: '2026-10-01T10:00:00.100001Z' }, { assessed_at: null }]) {
      invalid.push({ ...response(), body: { ...response().body, ...delta } });
    }
    for (const delta of [{ job_id: true }, { job_id: 0 }, { job_id: 2 ** 53 }, { input_snapshot: { secret: true } },
      { source_method: 'diagnostic-v1' }, { failure_category: 'private provider error' }, { failure_category: ['handler_failed'] },
      { created_at: '2026-10-01T10:00:00.100003Z' }, { created_at: '2026-02-30T10:00:00Z' },
      { created_at: '2026-10-01T24:00:00Z' }, { created_at: '2026-10-01T10:00:00+01:00' },
      { created_at: '2026-10-01T10:00:00.1234567Z' }, { status_updated_at: null }]) {
      invalid.push(response([{ ...row(), ...delta }] as ReturnType<typeof row>[]));
    }
    invalid.push(response([row(), row()]), response([row(1), row(0)]),
      response([row(), { ...row(1), status_updated_at: '2026-10-01T10:00:00.100003Z' }]),
      response(Array.from({ length: 21 }, (_, i) => row(i))), { status: 403, body: { message: 'private server text' } });
    for (const value of invalid) {
      api.projectCrawlFailures.mockResolvedValue(value); await component.inspect();
      expect(component.history()).toBeNull(); expect(component.error()).toBe(true);
    }
    api.projectCrawlFailures.mockRejectedValue(new Error('private network text')); await component.inspect(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('unavailable for this project');
    expect(fixture.nativeElement.textContent).not.toContain('private network text');
  });

  it('clears loaded history and rejects overlapping, route-changed, parent-refreshed and destroyed late responses', async () => {
    const { api, component, fixture } = setup(); await component.inspect();
    let resolve!: (value: ReturnType<typeof response>) => void;
    api.projectCrawlFailures.mockImplementation(() => new Promise(done => resolve = done));
    const first = component.inspect(); const finishFirst = resolve;
    expect(component.history()).toBeNull();
    const second = component.inspect(); finishFirst(response()); await first;
    expect(component.history()).toBeNull(); expect(component.busy()).toBe(true);
    resolve(response()); await second; expect(component.history()).not.toBeNull();
    const routed = component.inspect(); component.organizationId = 8; component.projectId = 10; component.ngOnChanges();
    resolve(response()); await routed; expect(component.history()).toBeNull(); expect(component.busy()).toBe(false);
    component.organizationId = 7; component.projectId = 9;
    const destroyed = component.inspect(); fixture.destroy(); resolve(response()); await destroyed;
    expect(component.history()).toBeNull(); expect(component.error()).toBe(false); expect(component.busy()).toBe(false);
  });

  it('does not request an invalid native organization or project scope', async () => {
    const { api, component } = setup();
    for (const invalid of [0, -1, 2 ** 53, NaN]) {
      component.organizationId = invalid; await component.inspect();
      expect(component.error()).toBe(true); expect(component.history()).toBeNull(); expect(component.busy()).toBe(false);
      component.organizationId = 7; component.projectId = invalid; await component.inspect();
      expect(component.error()).toBe(true); expect(component.busy()).toBe(false); component.projectId = 9;
    }
    expect(api.projectCrawlFailures).not.toHaveBeenCalled();
  });
});
