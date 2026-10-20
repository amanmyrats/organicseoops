import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { environment } from '../../environments/environment';
import { AccountApi } from '../account/account-api';
import { ProjectCruxAlertPreference } from './project-crux-alert-preference';

function response(frequency = 'off', revision = 0, project = 9, availability = 'rollout_off'): { status: number; body: Record<string, unknown> } {
  return { status: 200, body: { project_id: project, preference: { channel: 'email', source_family: 'crux_material',
    frequency, revision, delivery_state: availability } } };
}
function delivery(index = 0): Record<string, unknown> {
  return { id: 100 - index, day_start: `2026-09-${String(30 - index).padStart(2, '0')}`,
    created_at: '2026-10-02T10:00:00.100001+00:00', attempted_at: null, accepted_at: null, state: 'queued', error_category: '' };
}
function historyResponse(rows = [delivery()], hasMore = false, project = 9): { status: number; body: Record<string, unknown> } {
  return { status: 200, body: { project_id: project, method_version: 'own-daily-crux-delivery-history-v1',
    scope: 'own_retained_crux_transport_history_not_recipient_delivery_read_regression_or_current_eligibility', rows, has_more: hasMore } };
}
function setup() {
  const api = { projectCruxAlertPreference: vi.fn(async () => response()),
    saveProjectCruxAlertPreference: vi.fn(async () => response('daily', 1)),
    projectCruxAlertDeliveries: vi.fn(async () => historyResponse()) };
  TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(ProjectCruxAlertPreference), component = fixture.componentInstance;
  component.organizationId = 7; component.projectId = 9;
  return { api, fixture, component };
}

describe('Separate own-project material CrUX intent', () => {
  it('uses only fixed private GET and CSRF POST with frequency and exact expected revision', async () => {
    const fetcher = vi.fn(async (_path: string, _options: RequestInit) => ({ status: 200, json: async () => response().body }));
    const api = new AccountApi({ defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture-token' } as unknown as Document);
    await api.projectCruxAlertPreference(7, 9); await api.saveProjectCruxAlertPreference(7, 9, 'daily', 0);
    await api.projectCruxAlertDeliveries(7, 9);
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/organizations/7/projects/9/crux-alert-preference/',
      '/_allauth/browser/v1/auth/session', '/api/organizations/7/projects/9/crux-alert-preference/',
      '/api/organizations/7/projects/9/crux-alert-deliveries/']);
    expect(fetcher.mock.calls[0][1]).toEqual({ method: 'GET', headers: {}, body: undefined, credentials: 'same-origin', cache: 'no-store' });
    expect(fetcher.mock.calls[2][1]).toEqual({ method: 'POST', headers: { 'X-CSRFToken': 'fixture-token', 'Content-Type': 'application/json' },
      body: JSON.stringify({ frequency: 'daily', expected_revision: 0 }), credentials: 'same-origin', cache: 'no-store' });
    expect(fetcher.mock.calls[3][1]).toEqual(fetcher.mock.calls[0][1]);
  });

  it.each(['en', 'tr'] as const)('defaults off, labels unknown sample/product floors, and explicitly saves idempotent daily and off intent (%s)', async (language) => {
    const { api, fixture, component } = setup();
    fixture.componentRef.setInput('language', language); await component.load(); fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    expect(api.projectCruxAlertPreference).toHaveBeenCalledWith(7, 9);
    expect(api.saveProjectCruxAlertPreference).not.toHaveBeenCalled(); expect(component.saved()?.revision).toBe(0);
    expect(element.querySelector('section')?.getAttribute('lang')).toBe(language);
    for (const text of language === 'tr'
      ? ['haftalık özetlerden, operasyonel uyarılardan ve isteğe bağlı analizlerden bağımsız', 'CrUX teslimatı etkinleştirilmemiş',
        'Günlük niyet, günlük gönderim', '%20', '500 ms', '50 ms', 'birimsiz 0.05', 'örnek sayıları bilinmiyor',
        'istatistiksel anlamlılık değildir', '28 günlük pencereler örtüşür', 'doğrulanmış SEO gerilemeleri veya nedensel sonuçlar değildir']
      : ['independently of weekly summaries', 'CrUX delivery rollout is off', 'not daily sending',
        '20%', '500 ms LCP', '50 ms INP', '0.05 unitless CLS', 'sample counts remain unknown',
        'statistical significance', '28-day windows overlap', 'not confirmed SEO regressions']) {
      expect(element.textContent).toContain(text);
    }
    expect(element.querySelector('p span')?.getAttribute('lang')).toBe('en');
    expect(element.querySelector('label[for="crux-alert-frequency"]')).not.toBeNull();
    expect(element.querySelector('input[type="checkbox"]')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Saklanmış CrUX iletim geçmişiniz' : 'Your retained CrUX transport history');
    expect(api.projectCruxAlertDeliveries).not.toHaveBeenCalled();
    const select = element.querySelector<HTMLSelectElement>('#crux-alert-frequency')!;
    select.value = 'daily'; select.dispatchEvent(new Event('change'));
    element.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.saveProjectCruxAlertPreference).toHaveBeenCalledWith(7, 9, 'daily', 0);
    expect(component.saved()?.revision).toBe(1); expect(component.message()).toContain('did not directly schedule or send');
    await component.save(new Event('submit')); expect(component.saved()?.revision).toBe(1);
    component.edit('weekly'); expect(component.choice()).toBe('daily');
    component.edit('off'); expect(component.message()).toBe('');
    api.saveProjectCruxAlertPreference.mockResolvedValue(response('off', 2)); await component.save(new Event('submit'));
    expect(component.saved()?.frequency).toBe('off'); expect(component.saved()?.revision).toBe(2);
    component.edit('daily');
    const reads = api.projectCruxAlertPreference.mock.calls.length, saves = api.saveProjectCruxAlertPreference.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.choice()).toBe('daily'); expect(component.saved()?.revision).toBe(2);
    expect(api.projectCruxAlertPreference).toHaveBeenCalledTimes(reads); expect(api.saveProjectCruxAlertPreference).toHaveBeenCalledTimes(saves);
    api.saveProjectCruxAlertPreference.mockResolvedValue(response('daily', 3)); await component.save(new Event('submit'));
    expect(api.saveProjectCruxAlertPreference).toHaveBeenLastCalledWith(7, 9, 'daily', 2);
    expect(component.saved()?.revision).toBe(3);
    const buildEnvironment = environment as { production: boolean }, previous = buildEnvironment.production;
    try {
      buildEnvironment.production = true;
      const production = TestBed.createComponent(ProjectCruxAlertPreference);
      production.componentRef.setInput('language', 'tr'); production.detectChanges();
      expect(production.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
      expect(production.nativeElement.textContent).toContain('Your optional material CrUX alert intent'); production.destroy();
    } finally { buildEnvironment.production = previous; }
    expect(api.projectCruxAlertPreference).toHaveBeenCalledTimes(reads);
  });

  it('clones both GET/POST responses and rejects forged authority, inconsistent defaults and unbounded revisions', async () => {
    const { api, component } = setup(); const original = response();
    api.projectCruxAlertPreference.mockResolvedValue(original); await component.load();
    (original.body['preference'] as Record<string, unknown>)['revision'] = 77;
    expect(component.saved()?.revision).toBe(0);
    const posted = response('daily', 1); api.saveProjectCruxAlertPreference.mockResolvedValue(posted);
    component.edit('daily'); await component.save(new Event('submit'));
    (posted.body['preference'] as Record<string, unknown>)['frequency'] = 'off'; expect(component.saved()?.frequency).toBe('daily');
    const invalid = [response('daily', 0), response('weekly', 1), response('off', -1), response('off', 2 ** 31),
      response('off', 1.1), response('off', NaN), response('off', Infinity), response('off', 0, 99)];
    for (const delta of [{ channel: 'sms' }, { source_family: 'integration_health' }, { source_families: ['crux_material'] },
      { delivery_state: 'not_implemented' }, { delivery_state: 'sent' }, { revision: true }, { revision: '1' },
      { address: 'private@example.invalid' }, { source_fingerprint: 'private source' }]) {
      invalid.push({ ...response(), body: { ...response().body, preference: { ...(response().body['preference'] as object), ...delta } } });
    }
    invalid.push({ ...response(), body: { ...response().body, user_id: 7 } }, { ...response(), body: { project_id: 9, preference: [] } },
      { ...response(), body: { project_id: 9, preference: null } }, { status: 403, body: { message: 'private server error' } });
    for (const value of invalid) {
      api.projectCruxAlertPreference.mockResolvedValue(value); await component.load();
      expect(component.saved()).toBeNull(); expect(component.choice()).toBe('off'); expect(component.busy()).toBe(false);
      expect(component.error()).toContain('unavailable'); expect(component.error()).not.toContain('private');
    }
    api.projectCruxAlertPreference.mockResolvedValue(response('off', 2 ** 31 - 1)); await component.load();
    api.saveProjectCruxAlertPreference.mockClear(); await component.save(new Event('submit'));
    expect(api.saveProjectCruxAlertPreference).not.toHaveBeenCalled(); expect(component.error()).toContain('needs review');
  });

  it('clears uncertain or mismatched saves and reconciles by fresh GET without replay or private error text', async () => {
    const { api, component, fixture } = setup(); await component.load(); component.edit('daily');
    api.saveProjectCruxAlertPreference.mockRejectedValue(new Error('private provider error'));
    await component.save(new Event('submit')); fixture.detectChanges();
    expect(component.saved()).toBeNull(); expect(component.choice()).toBe('off'); expect(component.error()).toContain('Refresh');
    expect(component.error()).not.toContain('provider'); expect(fixture.nativeElement.querySelector('form')).toBeNull();
    await component.save(new Event('submit')); expect(api.saveProjectCruxAlertPreference).toHaveBeenCalledTimes(1);
    api.projectCruxAlertPreference.mockResolvedValue(response('daily', 1)); await component.load();
    expect(component.saved()?.revision).toBe(1); expect(api.saveProjectCruxAlertPreference).toHaveBeenCalledTimes(1);
    for (const value of [response('daily', 2), response('off', 1), response('daily', 1, 10), { status: 409, body: { error: 'private' } }]) {
      await component.load(); api.saveProjectCruxAlertPreference.mockResolvedValue(value);
      await component.save(new Event('submit')); expect(component.saved()).toBeNull(); expect(component.busy()).toBe(false);
      expect(component.message()).toBe(''); expect(component.error()).toContain('no automatic retry');
    }
    api.projectCruxAlertPreference.mockRejectedValue(new Error('private network error')); await component.load();
    expect(component.saved()).toBeNull(); expect(component.error()).not.toContain('network');
  });

  it('discards overlapping GET and refreshed POST; busy controls cannot edit or duplicate submission', async () => {
    const { api, component, fixture } = setup(); await component.load();
    let resolve!: (value: ReturnType<typeof response>) => void;
    api.projectCruxAlertPreference.mockImplementation(() => new Promise(done => resolve = done));
    const first = component.load(), finishFirst = resolve, second = component.load();
    component.edit('daily'); await component.save(new Event('submit'));
    finishFirst(response('daily', 1)); await first; expect(component.saved()).toBeNull(); expect(component.busy()).toBe(true);
    resolve(response()); await second; component.edit('daily');
    api.saveProjectCruxAlertPreference.mockImplementation(() => new Promise(done => resolve = done));
    const pending = component.save(new Event('submit')), finishPost = resolve; fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('select').disabled).toBe(true);
    component.edit('off'); await component.save(new Event('submit'));
    expect(component.choice()).toBe('daily'); expect(api.saveProjectCruxAlertPreference).toHaveBeenCalledTimes(1);
    const refresh = component.load(); finishPost(response('daily', 1)); await pending;
    expect(component.saved()).toBeNull(); expect(component.message()).toBe(''); expect(component.busy()).toBe(true);
    resolve(response()); await refresh; expect(component.saved()?.frequency).toBe('off');
  });

  it('clears late loads and saves on organization/project changes and destroy, including same project ID in another org', async () => {
    const { api, component, fixture } = setup(); await component.load();
    let resolve!: (value: ReturnType<typeof response>) => void;
    api.projectCruxAlertPreference.mockImplementation(() => new Promise(done => resolve = done));
    const old = component.load(), finishOld = resolve;
    component.organizationId = 8; component.ngOnChanges();
    finishOld(response('daily', 1)); await old; expect(component.saved()).toBeNull();
    resolve(response()); await fixture.whenStable(); expect(component.saved()?.frequency).toBe('off');
    component.edit('daily'); api.saveProjectCruxAlertPreference.mockImplementation(() => new Promise(done => resolve = done));
    const pending = component.save(new Event('submit')), finishPost = resolve;
    component.projectId = 10; component.ngOnChanges();
    finishPost(response('daily', 1)); await pending; expect(component.saved()).toBeNull(); expect(component.message()).toBe('');
    resolve(response('off', 0, 10)); await fixture.whenStable();
    component.edit('daily'); const destroyedPost = component.save(new Event('submit'));
    fixture.destroy(); resolve(response('daily', 1, 10)); await destroyedPost;
    expect(component.saved()).toBeNull(); expect(component.busy()).toBe(false); expect(component.message()).toBe('');
  });

  it('denies invalid scope before requests/busy and prevents saving an old loaded revision in changed inputs', async () => {
    const { api, component } = setup();
    for (const invalid of [NaN, 0, -1, 1.1, 2 ** 53, Infinity]) {
      component.organizationId = invalid; await component.load();
      expect(component.saved()).toBeNull(); expect(component.busy()).toBe(false); expect(component.error()).toContain('authorized project');
    }
    expect(api.projectCruxAlertPreference).not.toHaveBeenCalled();
    component.organizationId = 7; await component.load(); component.edit('daily'); component.organizationId = 8;
    await component.save(new Event('submit')); expect(component.saved()).toBeNull(); expect(api.saveProjectCruxAlertPreference).not.toHaveBeenCalled();
    await component.load(); component.projectId = 10; component.edit('daily');
    expect(component.saved()).toBeNull(); expect(component.choice()).toBe('off');
    component.projectId = NaN; await component.load(); expect(component.busy()).toBe(false);
  });

  it('displays configured optional availability without inferring current eligibility or sending', async () => {
    const { api, component, fixture } = setup();
    fixture.componentRef.setInput('language', 'tr');
    api.projectCruxAlertPreference.mockResolvedValue(response('daily', 1, 9, 'enabled_optional'));
    await component.load(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('yapılandırmayla etkinleştirilmiş');
    expect(fixture.nativeElement.textContent).toContain('canlı e-posta hazırlığının veya güncel uygunluğunuzun doğrulanması değildir');
    expect(api.saveProjectCruxAlertPreference).not.toHaveBeenCalled(); expect(api.projectCruxAlertDeliveries).not.toHaveBeenCalled();
  });

  it.each(['en', 'tr'] as const)('deliberately inspects cloned own transport states, empty and capped coverage without sending (%s)', async (language) => {
    const { api, component, fixture } = setup();
    fixture.componentRef.setInput('language', language); await component.load();
    const rows = [delivery(), { ...delivery(1), state: 'sending', attempted_at: '2026-10-02T10:00:00.100002Z' },
      { ...delivery(2), state: 'transport_accepted', attempted_at: '2026-10-02T10:00:00.100002Z', accepted_at: '2026-10-02T10:00:00.100003Z' },
      { ...delivery(3), state: 'skipped', attempted_at: '2026-10-02T10:00:00.100002Z', error_category: 'current_source_or_recipient_changed' },
      { ...delivery(4), state: 'unknown', attempted_at: '2026-10-02T10:00:00.100002Z', error_category: 'worker_outcome_unknown' }];
    const original = historyResponse(rows); api.projectCruxAlertDeliveries.mockResolvedValue(original);
    await component.inspectHistory(); fixture.detectChanges();
    expect(api.projectCruxAlertDeliveries).toHaveBeenCalledWith(7, 9);
    const retained = component.history(), reads = api.projectCruxAlertDeliveries.mock.calls.length;
    const preferenceReads = api.projectCruxAlertPreference.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.history()).toBe(retained); expect(component.saved()?.revision).toBe(0);
    expect(api.projectCruxAlertDeliveries).toHaveBeenCalledTimes(reads);
    expect(api.projectCruxAlertPreference).toHaveBeenCalledTimes(preferenceReads);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    for (const text of language === 'tr'
      ? ['Kuyrukta, gönderilmedi', 'Gönderim kalıcı olarak kaydedildi', 'İletim kabul edildi', 'teslim edildi veya okundu anlamına gelmez',
        'Atlandı: güncel kaynak veya alıcı değişti', 'İletim sonucu bilinmiyor; tekrar gönderilmez', 'kaynak döneminin gerçekleşme zamanı değildir']
      : ['Queued, not sent', 'Sending durably committed', 'Transport accepted', 'not delivered or read',
        'Skipped: current source or recipient changed', 'Unknown transport outcome; no replay', 'not source-period occurrence time']) {
      expect(fixture.nativeElement.textContent).toContain(text);
    }
    rows[0]['id'] = 999; expect(component.history()?.rows[0].id).toBe(100);
    api.projectCruxAlertDeliveries.mockResolvedValue(historyResponse([])); await component.inspectHistory(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Size ait saklanmış CrUX kayıtları yok' : 'No retained own CrUX records');
    api.projectCruxAlertDeliveries.mockResolvedValue(historyResponse(Array.from({ length: 20 }, (_, i) => delivery(i)), true));
    await component.inspectHistory(); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'en yeni 20 CrUX kaydı' : 'Only the newest 20');
    expect(api.saveProjectCruxAlertPreference).not.toHaveBeenCalled();
  });

  it('rejects malformed or foreign-family history, exact microsecond ordering, categories and bounds', async () => {
    const { api, component } = setup(); await component.load();
    const invalid = [historyResponse([delivery()], false, 99), historyResponse([], true),
      historyResponse(Array.from({ length: 21 }, (_, i) => delivery(i))),
      historyResponse([delivery(), delivery()]), historyResponse([delivery(1), delivery()])];
    for (const delta of [{ id: true }, { id: 2 ** 53 }, { source_metadata: {} }, { recipient_id: 7 }, { day_start: '2026-02-30' },
      { day_start: '2026-10-02' }, { created_at: '2026-02-30T10:00:00Z' }, { created_at: true },
      { attempted_at: '2026-10-02T10:00:00.100000Z', state: 'sending' },
      { accepted_at: '2026-10-02T10:00:00.100002Z' }, { state: 'unknown', error_category: ['delivery_uncertain'] },
      { state: 'unknown', attempted_at: '2026-10-02T10:00:00.100002Z', error_category: 'private body' },
      { state: 'transport_accepted' }, { state: 'sent' }, { state: 'skipped', attempted_at: null },
      { state: 'transport_accepted', attempted_at: '2026-10-02T10:00:00.100003Z', accepted_at: '2026-10-02T10:00:00.100002Z' }]) {
      invalid.push(historyResponse([{ ...delivery(), ...delta }]));
    }
    for (const delta of [{ method_version: 'own-daily-operational-delivery-history-v1' }, { scope: 'unsupported' },
      { has_more: 1 }, { rows: {} }, { source_fingerprint: 'private' }]) {
      invalid.push({ ...historyResponse(), body: { ...historyResponse().body, ...delta } });
    }
    invalid.push({ status: 403, body: { message: 'private denial' } });
    for (const value of invalid) {
      api.projectCruxAlertDeliveries.mockResolvedValue(value); await component.inspectHistory();
      expect(component.history()).toBeNull(); expect(component.historyError()).toBe(true); expect(component.historyBusy()).toBe(false);
    }
    api.projectCruxAlertDeliveries.mockRejectedValue(new Error('private network error')); await component.inspectHistory();
    expect(component.history()).toBeNull(); expect(component.historyError()).toBe(true);
  });

  it('clears overlapping or late history on edit, save, preference refresh, route and destroy', async () => {
    const { api, component, fixture } = setup(); await component.load();
    let resolve!: (value: ReturnType<typeof historyResponse>) => void;
    api.projectCruxAlertDeliveries.mockImplementation(() => new Promise(done => resolve = done));
    const old = component.inspectHistory(), finishOld = resolve, fresh = component.inspectHistory();
    finishOld(historyResponse()); await old; expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(true);
    resolve(historyResponse()); await fresh; expect(component.history()).not.toBeNull();
    api.saveProjectCruxAlertPreference.mockResolvedValue(response());
    for (const action of [() => component.edit('daily'), () => component.save(new Event('submit')), () => component.load()]) {
      await component.load(); const pending = component.inspectHistory(), finish = resolve;
      await action(); finish(historyResponse()); await pending;
      expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(false);
    }
    const route = component.inspectHistory(), finishRoute = resolve;
    component.organizationId = 8; component.projectId = 10;
    api.projectCruxAlertPreference.mockResolvedValue(response('off', 0, 10)); component.ngOnChanges(); await fixture.whenStable();
    finishRoute(historyResponse()); await route; expect(component.history()).toBeNull();
    const destroyed = component.inspectHistory(); fixture.destroy(); resolve(historyResponse([], false, 10)); await destroyed;
    expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(false);
  });

  it('denies invalid or displaced loaded history scope before requests and busy', async () => {
    const { api, component } = setup();
    for (const invalid of [NaN, 0, -1, 1.1, 2 ** 53, Infinity]) {
      component.organizationId = 7; component.projectId = 9; await component.load();
      component.organizationId = invalid; await component.inspectHistory();
      expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(false); expect(component.saved()).toBeNull();
    }
    component.organizationId = 7; await component.load(); component.organizationId = 8;
    await component.inspectHistory(); expect(component.saved()).toBeNull(); expect(api.projectCruxAlertDeliveries).not.toHaveBeenCalled();
  });
});
