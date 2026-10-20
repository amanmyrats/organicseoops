import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AccountApi } from '../account/account-api';
import { ProjectJobReference } from './project-job-reference';

function response(job: unknown = { id: 11, status: 'queued', created_at: '2026-10-02T10:00:00.100001+00:00',
  updated_at: '2026-10-02T10:00:00.100002Z' }, project = 9): { status: number; body: Record<string, unknown> } {
  return { status: 200, body: { project_id: project, method_version: 'retained-project-job-support-reference-v1',
    scope: 'retained_operational_job_reference_not_completion_incident_seo_outcome_or_retry_authority',
    state: job === null ? 'unavailable_no_retained_project_job' : 'retained_job_reference', job } };
}
function setup() {
  const api = { projectSupportJobReference: vi.fn(async () => response()) };
  TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(ProjectJobReference), component = fixture.componentInstance;
  component.organizationId = 7; component.projectId = 9;
  return { api, fixture, component };
}

describe('Minimized retained project job reference', () => {
  it.each(['en', 'tr'] as const)('uses only a fixed private GET and deliberate native submission, with status dates and no ticket claim (%s)', async (language) => {
    const fetcher = vi.fn(async (_path: string, _options: RequestInit) => ({ status: 200, json: async () => response().body }));
    const apiClient = new AccountApi({ defaultView: { fetch: fetcher } } as unknown as Document);
    await apiClient.projectSupportJobReference(7, 9, 11);
    expect(fetcher.mock.calls).toEqual([['/api/organizations/7/projects/9/support-job-reference/11/',
      { method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' }]]);
    const { api, component, fixture } = setup(); fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(api.projectSupportJobReference).not.toHaveBeenCalled();
    const element = fixture.nativeElement as HTMLElement, input = element.querySelector<HTMLInputElement>('#support-job-id')!;
    expect(element.querySelector('label[for="support-job-id"]')).not.toBeNull();
    input.value = '11'; input.dispatchEvent(new Event('input')); element.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
    await fixture.whenStable(); fixture.detectChanges(); expect(api.projectSupportJobReference).toHaveBeenCalledWith(7, 9, 11);
    expect(element.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('p span')?.getAttribute('lang')).toBe('en');
    for (const text of language === 'tr'
      ? ['İş referansı 11', 'bir SEO sonucu değildir', 'tamamlanma zamanı değildir', 'destek talebi göndermez']
      : ['Job reference 11', 'not an SEO outcome', 'not completion time', 'does not submit a support request']) {
      expect(element.textContent).toContain(text);
    }
    const retained = component.reference(), reads = api.projectSupportJobReference.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.reference()).toBe(retained); expect(component.jobId()).toBe('11');
    expect(api.projectSupportJobReference).toHaveBeenCalledTimes(reads);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    const original = response(); api.projectSupportJobReference.mockResolvedValue(original); await component.inspect();
    (original.body['job'] as Record<string, unknown>)['status'] = 'failed'; expect(component.reference()?.job?.status).toBe('queued');
    api.projectSupportJobReference.mockResolvedValue(response(null)); await component.inspect(); fixture.detectChanges();
    expect(element.textContent).toContain(language === 'tr' ? 'saklanmış iş referansı yok' : 'No retained job reference');
    for (const status of ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded']) {
      api.projectSupportJobReference.mockResolvedValue(response({ ...(response().body['job'] as object), status }));
      await component.inspect(); expect(component.reference()?.job?.status).toBe(status);
    }
  });

  it('rejects forged envelopes, job authority, status, calendar, microsecond order and null inconsistency', async () => {
    const { api, component } = setup(); component.edit('11');
    const invalid = [response(undefined, 99), response([]), response({}), { status: 403, body: { message: 'private error' } }];
    for (const delta of [{ id: 12 }, { id: true }, { status: 'private error' }, { output: {} }, { actor_id: 7 },
      { created_at: '2026-02-30T10:00:00Z' }, { updated_at: '2026-10-02T10:00:00.100000Z' },
      { updated_at: '2026-10-02T10:00:00.1000011Z' }, { created_at: true }, { updated_at: null }]) {
      invalid.push(response({ ...(response().body['job'] as object), ...delta }));
    }
    for (const delta of [{ method_version: 'unknown' }, { scope: 'unsupported' }, { state: 'unavailable_no_retained_project_job' },
      { job: null }, { source_fingerprint: 'private' }]) {
      invalid.push({ ...response(), body: { ...response().body, ...delta } });
    }
    for (const value of invalid) {
      api.projectSupportJobReference.mockResolvedValue(value); await component.inspect();
      expect(component.reference()).toBeNull(); expect(component.busy()).toBe(false);
      expect(component.error()).toContain('unavailable'); expect(component.error()).not.toContain('private');
    }
    api.projectSupportJobReference.mockRejectedValue(new Error('private network error')); await component.inspect();
    expect(component.reference()).toBeNull(); expect(component.error()).not.toContain('network');
  });

  it('denies unsafe scope and non-exact job IDs before requests or busy state', async () => {
    const { api, component } = setup();
    for (const input of ['', '0', '-1', '1.1', '1e1', ' 11', '11 ', '01', '9007199254740992', 'Infinity', 'private error']) {
      component.edit(input); await component.inspect(); expect(component.reference()).toBeNull(); expect(component.busy()).toBe(false);
    }
    component.edit('11');
    for (const id of [NaN, 0, -1, 1.1, 2 ** 53, Infinity]) {
      component.organizationId = id; await component.inspect(); expect(component.busy()).toBe(false);
    }
    expect(api.projectSupportJobReference).not.toHaveBeenCalled();
  });

  it('clears edited, overlapping, refreshed, routed and destroyed late references', async () => {
    const { api, component, fixture } = setup(); component.edit('11');
    let resolve!: (value: ReturnType<typeof response>) => void;
    api.projectSupportJobReference.mockImplementation(() => new Promise(done => resolve = done));
    const first = component.inspect(), finishFirst = resolve, second = component.inspect();
    finishFirst(response()); await first; expect(component.reference()).toBeNull(); expect(component.busy()).toBe(true);
    resolve(response()); await second; expect(component.reference()).not.toBeNull();
    const edited = component.inspect(); component.edit('12'); resolve(response()); await edited;
    expect(component.reference()).toBeNull(); expect(component.busy()).toBe(false);
    const routed = component.inspect(); component.organizationId = 8; component.ngOnChanges(); resolve(response()); await routed;
    expect(component.reference()).toBeNull(); expect(component.jobId()).toBe(''); expect(component.busy()).toBe(false);
    component.edit('11'); const destroyed = component.inspect(); fixture.destroy(); resolve(response()); await destroyed;
    expect(component.reference()).toBeNull(); expect(component.busy()).toBe(false);
  });
});
