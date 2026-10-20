import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { environment } from '../../environments/environment';
import { AccountApi } from '../account/account-api';
import { ProjectSupport } from './project-support';

const scope = 'own_retained_support_records_not_email_delivery_staff_response_or_job_access_authority';
const date = '2026-10-04T00:00:00.000001+00:00';
function envelope(project = 9, actor = 4) { return { method_version: 'own-project-support-request-v2', scope, project_id: project, actor_id: actor }; }
function row() { return { id: 10, category: 'other', job_id: null, question: 'A plain question', created_at: date,
  revision: 0, status: 'received', updates: [] as Record<string, unknown>[], updates_has_more: false }; }
function history(actor = 4) { return { status: 200, body: { ...envelope(9, actor), requests: [] as Record<string, unknown>[], has_more: false } as Record<string, unknown> }; }
function detail(value: unknown = row()) { return { status: 200, body: { ...envelope(), request: value } as Record<string, unknown> }; }
function setup() {
  const api = { projectSupportRequests: vi.fn(async () => history()), projectSupportRequest: vi.fn(async () => detail()),
    createProjectSupportRequest: vi.fn(async (_organization: number, _project: number, command: Record<string, unknown>) =>
      detail({ ...row(), category: command['category'], question: command['question'], job_id: command['job_id'] })) };
  TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(ProjectSupport), component = fixture.componentInstance;
  component.organizationId = 7; component.projectId = 9;
  const fill = (question = 'A plain question') => { component.edit('question', question); component.edit('declaration', true); };
  return { api, fixture, component, fill };
}

describe('Own private support requests', () => {
  it.each(['en', 'tr'] as const)('uses fixed private GET/detail and CSRF POST paths, explicit consent/preflight and inert cloned content (%s)', async (language) => {
    const fetcher = vi.fn(async (_path: string, _options: RequestInit) => ({ status: 200, json: async () => history().body }));
    const client = new AccountApi({ cookie: 'csrftoken=fixture', defaultView: { fetch: fetcher } } as unknown as Document);
    await client.projectSupportRequests(7, 9); await client.projectSupportRequest(7, 9, 10);
    await client.createProjectSupportRequest(7, 9, { expected_actor_id: 4 });
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/organizations/7/projects/9/support-requests/',
      '/api/organizations/7/projects/9/support-requests/10/', '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/support-requests/']);
    expect(fetcher.mock.calls.at(-1)?.[1]).toMatchObject({ method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'X-CSRFToken': 'fixture', 'Content-Type': 'application/json' }, body: '{"expected_actor_id":4}' });
    const { api, fixture, component, fill } = setup(); fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(api.projectSupportRequests).not.toHaveBeenCalled(); expect(api.createProjectSupportRequest).not.toHaveBeenCalled();
    for (const id of ['support-category', 'support-question', 'support-request-job']) expect(fixture.nativeElement.querySelector(`label[for="${id}"]`)).not.toBeNull();
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('#support-category');
    expect([...select.options].map(option => option.value)).toEqual(['job', 'account_billing', 'data_sources', 'accessibility', 'other']);
    expect([...select.options].map(option => option.textContent)).toEqual(language === 'tr'
      ? ['İş', 'Hesap ve faturalama', 'Veri kaynakları', 'Erişilebilirlik', 'Diğer']
      : ['job', 'account billing', 'data sources', 'accessibility', 'other']);
    expect(select.value).toBe('other');
    select.value = 'data_sources'; select.dispatchEvent(new Event('change', { bubbles: true }));
    expect(component.category()).toBe('data_sources');
    const unsafe = '<img src=x onerror=alert(1)>'; fill(unsafe);
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.question()).toBe(unsafe); expect(component.declared()).toBe(true);
    expect(fixture.nativeElement.querySelector('#support-category')).toBe(select); expect(select.value).toBe('data_sources');
    expect(api.projectSupportRequests).not.toHaveBeenCalled(); expect(api.createProjectSupportRequest).not.toHaveBeenCalled();
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    await component.submit(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('textarea')?.getAttribute('lang')).toBe('');
    expect(fixture.nativeElement.querySelector('pre')?.getAttribute('lang')).toBe('');
    expect(fixture.nativeElement.querySelector('h3 span')?.textContent).toBe(language === 'tr' ? 'Alındı' : 'received');
    expect(component.detail()?.status).toBe('received'); expect(component.detail()?.category).toBe('data_sources');
    const retained = component.detail(), reads = api.projectSupportRequests.mock.calls.length, posts = api.createProjectSupportRequest.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.detail()).toBe(retained); expect(api.projectSupportRequests).toHaveBeenCalledTimes(reads);
    expect(api.createProjectSupportRequest).toHaveBeenCalledTimes(posts);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(api.projectSupportRequests).toHaveBeenCalledWith(7, 9);
    expect(api.createProjectSupportRequest.mock.calls[0][2]).toMatchObject({ expected_actor_id: 4, category: 'data_sources', question: unsafe, no_sensitive_data: true, job_id: null });
    expect(component.detail()?.question).toBe(unsafe); expect(fixture.nativeElement.querySelector('img')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Personel yanıtı' : 'not a staff response');
    const original = detail(); api.projectSupportRequest.mockResolvedValue(original); await component.inspect(10);
    (original.body['request'] as Record<string, unknown>)['question'] = 'Changed external reference';
    expect(component.detail()?.question).toBe('A plain question');
    const buildEnvironment = environment as { production: boolean }, previous = buildEnvironment.production;
    try {
      buildEnvironment.production = true; fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
      expect(fixture.nativeElement.textContent).toContain('Your private project support requests');
      expect(select.options[1].textContent).toBe('account billing');
      expect(fixture.nativeElement.querySelector('h3 span')?.textContent).toBe('received');
      expect(component.detail()?.question).toBe('A plain question');
    } finally { buildEnvironment.production = previous; }
  });

  it('rejects unsafe scope, text, identity and missing declaration before submission, and untrusted preflight before POST', async () => {
    const { api, component, fill } = setup();
    for (const question of ['', '   ', 'x'.repeat(2001), 'bad\u202etext', 'bad\ud800text', 'bad\0text']) {
      fill(question); await component.submit(); expect(component.busy()).toBe(false);
    }
    fill(); component.edit('declaration', false); await component.submit();
    fill(); component.edit('job', '01'); component.edit('declaration', true); await component.submit();
    fill(); component.organizationId = NaN; await component.submit();
    expect(api.projectSupportRequests).not.toHaveBeenCalled(); expect(api.createProjectSupportRequest).not.toHaveBeenCalled();
    component.organizationId = 7; component.edit('job', ''); fill();
    api.projectSupportRequests.mockResolvedValue({ status: 200, body: { ...history().body, actor_id: true } });
    await component.submit(); expect(api.createProjectSupportRequest).not.toHaveBeenCalled(); expect(component.pending()).toBeNull();
  });

  it('holds an uncertain original actor/command/key in memory, never auto-replays, and requires fresh read before explicit retry', async () => {
    const { api, component, fixture, fill } = setup(); fill(); api.createProjectSupportRequest.mockRejectedValueOnce(new Error('private transport error'));
    await component.submit(); const original = structuredClone(api.createProjectSupportRequest.mock.calls[0][2]);
    expect(component.pending()).not.toBeNull(); expect(component.retryReady()).toBe(false); expect(component.error()).not.toContain('private');
    const pending = component.pending(), reads = api.projectSupportRequests.mock.calls.length;
    fixture.componentRef.setInput('language', 'tr'); fixture.detectChanges();
    expect(component.pending()).toBe(pending); expect(component.question()).toBe('A plain question'); expect(component.declared()).toBe(true);
    expect(component.retryReady()).toBe(false); expect(api.projectSupportRequests).toHaveBeenCalledTimes(reads);
    expect(api.createProjectSupportRequest).toHaveBeenCalledTimes(1);
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent).toContain('Gönderim doğrulanmadı');
    expect(fixture.nativeElement.querySelector('textarea').disabled).toBe(true);
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('#support-category');
    expect(select.disabled).toBe(true); expect(select.value).toBe(original['category']);
    expect(select.options[4].textContent).toBe('Diğer');
    component.edit('question', 'Forbidden uncertain edit'); expect(component.question()).toBe('A plain question');
    await component.retry(); expect(api.createProjectSupportRequest).toHaveBeenCalledTimes(1);
    await component.refresh(); expect(api.createProjectSupportRequest).toHaveBeenCalledTimes(1); expect(component.retryReady()).toBe(true);
    await component.retry(); expect(api.createProjectSupportRequest).toHaveBeenCalledTimes(2);
    expect(api.createProjectSupportRequest.mock.calls[1][2]).toEqual(original); expect(component.pending()).toBeNull();
    component.edit('declaration', true); api.createProjectSupportRequest.mockRejectedValueOnce(new Error()); await component.submit();
    api.projectSupportRequests.mockResolvedValue(history(5)); await component.refresh();
    expect(component.pending()).toBeNull(); expect(component.question()).toBe(''); expect(component.detail()).toBeNull();
    expect(component.error()).toContain('Account context changed');
  });

  it('clears late preflight/submission/detail responses on edits, new scope, hide and destruction', async () => {
    const { api, component, fixture, fill } = setup();
    let finish!: (value: ReturnType<typeof history>) => void;
    api.projectSupportRequests.mockImplementation(() => new Promise(resolve => finish = resolve));
    fill(); const preflight = component.submit(); component.edit('question', 'Edited question'); finish(history()); await preflight;
    expect(api.createProjectSupportRequest).not.toHaveBeenCalled(); expect(component.busy()).toBe(false);
    api.projectSupportRequests.mockResolvedValue(history());
    let sendFinish!: (value: ReturnType<typeof detail>) => void;
    api.createProjectSupportRequest.mockImplementation(() => new Promise(resolve => sendFinish = resolve));
    fill(); const sending = component.submit(); await vi.waitFor(() => expect(api.createProjectSupportRequest).toHaveBeenCalledTimes(1));
    component.projectId = 11; component.ngOnChanges(); sendFinish(detail()); await sending;
    expect(component.detail()).toBeNull(); expect(component.pending()).toBeNull(); expect(component.question()).toBe('');
    component.projectId = 9;
    let detailFinish!: (value: ReturnType<typeof detail>) => void;
    api.projectSupportRequest.mockImplementation(() => new Promise(resolve => detailFinish = resolve));
    const hidden = component.inspect(10); component.hide(); detailFinish(detail()); await hidden;
    expect(component.detail()).toBeNull();
    const destroyed = component.inspect(10); fixture.destroy(); detailFinish(detail()); await destroyed;
    expect(component.detail()).toBeNull(); expect(component.busy()).toBe(false);
  });

  it('rejects forged own detail, response revisions/state/date/control corruption and extra private fields', async () => {
    const { api, component, fixture } = setup();
    const updated = { ...row(), revision: 1, status: 'in_progress', updates: [{ revision: 1, status: 'in_progress',
      response: 'A staff response', created_at: '2026-10-04T00:00:00.000002Z' }] };
    const invalid = [detail(null), detail([]), detail({ ...row(), id: 11 }), detail({ ...row(), question: 'bad\u202etext' }),
      detail({ ...row(), raw_error: 'private' }), detail({ ...row(), created_at: '2026-02-30T00:00:00Z' }),
      detail({ ...updated, status: 'resolved' }), detail({ ...updated, revision: 2 }),
      detail({ ...updated, updates_has_more: true }), detail({ ...updated, updates: [{ ...updated.updates[0], created_at: date.replace('000001', '000000') }] }),
      { ...detail(), body: { ...detail().body, actor_id: 0 } }, { ...detail(), body: { ...detail().body, project_id: 99 } }];
    for (const value of invalid) {
      api.projectSupportRequest.mockResolvedValue(value); await component.inspect(10);
      expect(component.detail()).toBeNull(); expect(component.busy()).toBe(false); expect(component.error()).not.toContain('private');
    }
    api.projectSupportRequest.mockResolvedValue(detail(updated)); await component.inspect(10);
    expect(component.detail()?.updates[0].response).toBe('A staff response');
    fixture.componentRef.setInput('language', 'tr'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('h3 span')?.textContent).toBe('İşlem sürüyor');
    expect(fixture.nativeElement.textContent).toContain('Personel yanıtı sürümü 1 · İşlem sürüyor');
    expect(component.detail()?.status).toBe('in_progress'); expect(component.detail()?.updates[0].status).toBe('in_progress');
  });

  it('validates exact own history cap/order/calendar/actor/scope and clears displaced retry scope', async () => {
    const { api, component, fill, fixture } = setup();
    const summary = { id: 10, category: 'other', job_id: null, created_at: date, revision: 0, status: 'received' };
    for (const changes of [{ has_more: true }, { requests: [summary, summary] }, { requests: [{ ...summary, question: 'private' }] },
      { requests: [{ ...summary, id: true }] }, { requests: [{ ...summary, revision: 0, status: 'resolved' }] },
      { requests: [{ ...summary, id: 9 }, { ...summary, id: 10 }] }, { scope: 'unsupported' }]) {
      api.projectSupportRequests.mockResolvedValue({ status: 200, body: { ...history().body, ...changes } });
      await component.refresh(); expect(component.history()).toBeNull(); expect(component.busy()).toBe(false);
    }
    api.projectSupportRequests.mockResolvedValue({ status: 200, body: { ...history().body, requests: [summary] } });
    await component.refresh(); expect(component.history()?.[0].id).toBe(10);
    fixture.componentRef.setInput('language', 'tr'); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('li')?.textContent).toContain('Diğer · Alındı');
    expect(component.history()?.[0].category).toBe('other'); expect(component.history()?.[0].status).toBe('received');
    api.createProjectSupportRequest.mockRejectedValueOnce(new Error()); fill(); await component.submit(); await component.refresh();
    component.projectId = 11; await component.retry();
    expect(api.createProjectSupportRequest).toHaveBeenCalledTimes(1); expect(component.pending()).toBeNull(); expect(component.detail()).toBeNull();
  });
});
