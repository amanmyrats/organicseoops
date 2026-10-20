import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AccountApi } from '../account/account-api';
import { environment } from '../../environments/environment';
import { ProjectAlertPreference } from './project-alert-preference';

function response(frequency = 'off', revision = 0, sourceFamilies: unknown[] = [], project = 9): { status: number; body: Record<string, unknown> } {
  return { status: 200, body: { project_id: project, preference: { channel: 'email', frequency,
    revision, source_families: sourceFamilies, delivery_state: 'rollout_off' } } };
}

function delivery(index = 0, state = 'queued'): Record<string, unknown> {
  return { id: 1000 + index, day_start: new Date(Date.UTC(2026, 9, 1 - index)).toISOString().slice(0, 10),
    state, error_category: state === 'skipped' ? 'current_source_or_recipient_changed' : state === 'unknown' ? 'delivery_uncertain' : '',
    created_at: '2026-10-02T10:00:00.100001Z', attempted_at: state === 'queued' ? null : '2026-10-02T10:00:00.100002Z',
    accepted_at: state === 'transport_accepted' ? '2026-10-02T10:00:00.100003Z' : null };
}

function historyResponse(rows: unknown[] = [delivery()], hasMore = false, project = 9): { status: number; body: Record<string, unknown> } {
  return { status: 200, body: { method_version: 'own-daily-operational-delivery-history-v1', project_id: project,
    scope: 'own_retained_transport_history_not_recipient_delivery_read_incident_or_current_eligibility', rows, has_more: hasMore } };
}

function setup() {
  const api = { projectAlertPreference: vi.fn(async () => response()),
    saveProjectAlertPreference: vi.fn(async () => response('daily', 1, ['crawl_failure'])),
    projectAlertDeliveries: vi.fn(async () => historyResponse()) };
  TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(ProjectAlertPreference), component = fixture.componentInstance;
  component.organizationId = 7; component.projectId = 9;
  return { api, fixture, component };
}

describe('Independent own-project optional alert intent', () => {
  it.each(['en', 'tr'] as const)('defaults off, explains source limits, validates daily selection and explicitly saves canonical own intent (%s)', async (language) => {
    const { api, fixture, component } = setup();
    fixture.componentRef.setInput('language', language); await component.load(); fixture.detectChanges();
    expect(component.choice()).toBe('off'); expect(component.selected()).toEqual([]);
    expect(api.saveProjectAlertPreference).not.toHaveBeenCalled();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('section')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('span[lang="en"]')?.textContent).toBe('off');
    expect(element.textContent).toContain(language === 'tr' ? 'haftalık özetlerden ve isteğe bağlı analizlerden bağımsız' : 'independently of weekly summaries and optional analytics');
    expect(element.textContent).toContain(language === 'tr' ? 'Günlük operasyon özeti etkinleştirilmemiş' : 'Daily operational digest rollout is off');
    expect(element.textContent).toContain(language === 'tr' ? 'güncel olaylar veya önemli ciddiyet düzeyi değildir' : 'not current incidents or important severity');
    expect(element.querySelector('label[for="alert-frequency"]')).not.toBeNull();
    const select = element.querySelector<HTMLSelectElement>('#alert-frequency')!;
    select.value = 'daily'; select.dispatchEvent(new Event('change'));
    await component.save(new Event('submit'));
    fixture.detectChanges();
    expect(element.querySelector('[role="alert"]')?.textContent).toContain(language === 'tr' ? 'en az bir kaynak ailesi seçin' : 'at least one source family');
    expect(component.error()).toContain('at least one'); expect(api.saveProjectAlertPreference).not.toHaveBeenCalled();
    element.querySelector<HTMLInputElement>('[name="crawl_failure"]')!.click();
    element.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
    await fixture.whenStable(); fixture.detectChanges();
    expect(api.saveProjectAlertPreference).toHaveBeenCalledWith(7, 9, 'daily', ['crawl_failure'], 0);
    expect(component.saved()?.revision).toBe(1); expect(component.message()).toContain('did not directly schedule or send');
    component.editFamily('integration_health', true); expect(component.message()).toBe('');
    api.saveProjectAlertPreference.mockResolvedValue(response('daily', 2, ['crawl_failure', 'integration_health']));
    await component.save(new Event('submit')); expect(component.saved()?.revision).toBe(2);
    component.editFrequency('off');
    api.saveProjectAlertPreference.mockResolvedValue(response('off', 3, ['crawl_failure', 'integration_health']));
    await component.save(new Event('submit')); expect(component.saved()?.frequency).toBe('off');
    await component.save(new Event('submit')); expect(component.saved()?.revision).toBe(3);
    component.editFrequency('daily'); component.editFamily('integration_health', false);
    const reads = api.projectAlertPreference.mock.calls.length, saves = api.saveProjectAlertPreference.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.choice()).toBe('daily'); expect(component.selected()).toEqual(['crawl_failure']); expect(component.saved()?.revision).toBe(3);
    expect(api.projectAlertPreference).toHaveBeenCalledTimes(reads); expect(api.saveProjectAlertPreference).toHaveBeenCalledTimes(saves);
    const buildEnvironment = environment as { production: boolean }, previous = buildEnvironment.production;
    try {
      buildEnvironment.production = true;
      const production = TestBed.createComponent(ProjectAlertPreference); production.componentRef.setInput('language', 'tr'); production.detectChanges();
      expect(production.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
      expect(production.nativeElement.textContent).toContain('Your optional project alert preference'); production.destroy();
    } finally { buildEnvironment.production = previous; }
    expect(api.projectAlertPreference).toHaveBeenCalledTimes(reads);
  });

  it('clones responses and choices; rejects exact envelope/family/channel/revision/availability violations', async () => {
    const { api, component } = setup();
    const original = response('off', 1, ['integration_health']);
    api.projectAlertPreference.mockResolvedValue(original); await component.load();
    (original.body['preference'] as { source_families: unknown[] }).source_families.push('untrusted');
    expect(component.saved()?.source_families).toEqual(['integration_health']);
    component.editFamily('crawl_failure', true);
    expect(component.selected()).toEqual(['crawl_failure', 'integration_health']);
    expect(component.saved()?.source_families).toEqual(['integration_health']);
    const invalid = [response('weekly', 1), response('daily', 0, ['crawl_failure']), response('daily', 1),
      response('off', -1), response('off', 2 ** 31), response('off', 0, ['crawl_failure']), response('off', 0, [], 99),
      response('off', 1, [true]), response('off', 1, [['crawl_failure']]), response('off', 1, ['regression']),
      response('off', 1, ['crawl_failure', 'crawl_failure']), response('off', 1, ['integration_health', 'crawl_failure'])];
    for (const delta of [{ channel: 'sms' }, { delivery_state: 'not_implemented' }, { revision: true },
      { source_families: 'crawl_failure' }, { source_families: null }, { email: 'private@example.invalid' }]) {
      invalid.push({ ...response(), body: { ...response().body, preference: { ...(response().body['preference'] as object), ...delta } } });
    }
    invalid.push({ ...response(), body: { ...response().body, user_id: 7 } }, { status: 403, body: { message: 'private error' } },
      { ...response(), body: { project_id: 9, preference: [] } });
    for (const value of invalid) {
      api.projectAlertPreference.mockResolvedValue(value); await component.load();
      expect(component.saved()).toBeNull(); expect(component.choice()).toBe('off'); expect(component.selected()).toEqual([]);
      expect(component.error()).toContain('unavailable'); expect(component.busy()).toBe(false);
    }
  });

  it('requires fresh GET after uncertain or mismatched saves without replay or private error text', async () => {
    const { api, component } = setup(); await component.load();
    component.editFrequency('daily'); component.editFamily('crawl_failure', true);
    api.saveProjectAlertPreference.mockRejectedValue(new Error('private SMTP error'));
    await component.save(new Event('submit'));
    expect(component.saved()).toBeNull(); expect(component.error()).toContain('Refresh');
    expect(component.error()).not.toContain('SMTP');
    await component.save(new Event('submit')); expect(api.saveProjectAlertPreference).toHaveBeenCalledTimes(1);
    api.projectAlertPreference.mockResolvedValue(response('daily', 1, ['crawl_failure'])); await component.load();
    expect(component.saved()?.revision).toBe(1); expect(api.saveProjectAlertPreference).toHaveBeenCalledTimes(1);
    for (const invalid of [response('daily', 2, ['crawl_failure']), response('daily', 1, ['integration_health']), response('off', 1)]) {
      await component.load(); api.saveProjectAlertPreference.mockResolvedValue(invalid);
      await component.save(new Event('submit')); expect(component.saved()).toBeNull();
    }
    api.projectAlertPreference.mockRejectedValue(new Error('private account error')); await component.load();
    expect(component.saved()).toBeNull(); expect(component.error()).not.toContain('account error');
  });

  it('clears refresh/route/destroyed late GET and POST and prevents busy edits or repeat submission', async () => {
    const { api, component, fixture } = setup(); await component.load();
    let resolve!: (value: ReturnType<typeof response>) => void;
    api.projectAlertPreference.mockImplementation(() => new Promise(done => resolve = done));
    const old = component.load(), finishOld = resolve;
    const fresh = component.load(); finishOld(response('daily', 1, ['crawl_failure'])); await old;
    expect(component.saved()).toBeNull(); expect(component.busy()).toBe(true);
    resolve(response()); await fresh;
    component.editFrequency('daily'); component.editFamily('crawl_failure', true);
    api.saveProjectAlertPreference.mockImplementation(() => new Promise(done => resolve = done));
    const pending = component.save(new Event('submit')), finishPost = resolve;
    component.editFamily('integration_health', true); component.editFrequency('off');
    await component.save(new Event('submit'));
    expect(api.saveProjectAlertPreference).toHaveBeenCalledTimes(1); expect(component.choice()).toBe('daily');
    expect(component.selected()).toEqual(['crawl_failure']);
    const refreshing = component.load(); finishPost(response('daily', 1, ['crawl_failure'])); await pending;
    expect(component.saved()).toBeNull(); expect(component.message()).toBe(''); resolve(response()); await refreshing;
    const routeGet = component.load(), finishRoute = resolve;
    component.organizationId = 8; component.projectId = 10; component.ngOnChanges();
    finishRoute(response('daily', 1, ['crawl_failure'])); await routeGet;
    expect(component.saved()).toBeNull(); resolve(response('off', 0, [], 10)); await fixture.whenStable();
    const destroyed = component.load(); fixture.destroy(); resolve(response('daily', 1, ['crawl_failure'], 10)); await destroyed;
    expect(component.saved()).toBeNull(); expect(component.busy()).toBe(false); expect(component.message()).toBe('');
  });

  it('rejects invalid scope before requesting and clears stale data without a spinner', async () => {
    const { api, component } = setup(); await component.load(); api.projectAlertPreference.mockClear();
    for (const invalid of [NaN, 0, -1, 2 ** 53]) {
      component.organizationId = invalid; await component.load();
      expect(component.saved()).toBeNull(); expect(component.busy()).toBe(false); expect(component.error()).toContain('authorized project');
    }
    expect(api.projectAlertPreference).not.toHaveBeenCalled();
  });

  it.each(['en', 'tr'] as const)('truthfully shows configured availability and explicitly inspects cloned own transport states, empty and bounded history (%s)', async (language) => {
    const { api, component, fixture } = setup();
    fixture.componentRef.setInput('language', language);
    const pref = response('daily', 1, ['crawl_failure']);
    (pref.body['preference'] as Record<string, unknown>)['delivery_state'] = 'enabled_optional';
    api.projectAlertPreference.mockResolvedValue(pref); await component.load(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'yapılandırmayla etkinleştirilmiş' : 'enabled by configuration');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'canlı e-posta hazırlığının veya güncel uygunluğunuzun doğrulanması değildir' : 'not confirmation of live email readiness');
    expect(api.projectAlertDeliveries).not.toHaveBeenCalled();
    const original = historyResponse(['queued', 'sending', 'transport_accepted', 'skipped', 'unknown'].map((state, i) => delivery(i, state)));
    api.projectAlertDeliveries.mockResolvedValue(original); await component.inspectHistory(); fixture.detectChanges();
    expect(api.projectAlertDeliveries).toHaveBeenCalledWith(7, 9);
    const stored = component.history(), reads = api.projectAlertDeliveries.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.history()).toBe(stored); expect(api.projectAlertDeliveries).toHaveBeenCalledTimes(reads);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Gönderim kalıcı olarak kaydedildi' : 'Sending durably committed');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'teslim edildi veya okundu anlamına gelmez' : 'not delivered or read');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'İletim sonucu bilinmiyor; tekrar gönderilmez' : 'Unknown transport outcome; no replay');
    (original.body['rows'] as Record<string, unknown>[])[0]['id'] = 9999;
    expect(component.history()?.rows[0].id).toBe(1000);
    api.projectAlertDeliveries.mockResolvedValue(historyResponse([])); await component.inspectHistory(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Size ait saklanmış günlük kayıt yok' : 'No retained own daily records');
    api.projectAlertDeliveries.mockResolvedValue(historyResponse(Array.from({ length: 20 }, (_, i) => delivery(i)), true));
    await component.inspectHistory(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'en yeni 20 kayıt' : 'Only the newest 20');
    expect(api.saveProjectAlertPreference).not.toHaveBeenCalled();
  });

  it('rejects exact history envelope, safe identity, canonical day/microsecond, state-category-null and bounds violations', async () => {
    const { api, component } = setup(); await component.load();
    const invalid = [historyResponse([delivery()], false, 99), historyResponse([], true),
      historyResponse(Array.from({ length: 21 }, (_, i) => delivery(i))),
      historyResponse([delivery(), delivery()]), historyResponse([delivery(1), delivery()])];
    for (const delta of [{ id: true }, { id: 2 ** 53 }, { recipient_id: 7 }, { day_start: '2026-02-30' },
      { day_start: '2026-10-02' }, { created_at: '2026-02-30T10:00:00Z' }, { created_at: true },
      { attempted_at: '2026-10-02T10:00:00.100000Z', state: 'sending' },
      { accepted_at: '2026-10-02T10:00:00.100002Z' }, { state: 'unknown', error_category: ['delivery_uncertain'] },
      { state: 'unknown', attempted_at: '2026-10-02T10:00:00.100002Z', error_category: 'private body' },
      { state: 'transport_accepted' }, { state: 'unsupported' }]) {
      invalid.push(historyResponse([{ ...delivery(), ...delta }]));
    }
    for (const delta of [{ method_version: 'unsupported' }, { scope: 'unsupported' }, { has_more: 1 },
      { rows: {} }, { source_fingerprint: 'private' }]) {
      invalid.push({ ...historyResponse(), body: { ...historyResponse().body, ...delta } });
    }
    for (const value of invalid) {
      api.projectAlertDeliveries.mockResolvedValue(value); await component.inspectHistory();
      expect(component.history()).toBeNull(); expect(component.historyError()).toBe(true); expect(component.historyBusy()).toBe(false);
    }
    api.projectAlertDeliveries.mockRejectedValue(new Error('private provider error')); await component.inspectHistory();
    expect(component.history()).toBeNull(); expect(component.historyError()).toBe(true);
  });

  it('clears late overlapping history and family-frequency edits, save, preference refresh, route and destroy', async () => {
    const { api, component, fixture } = setup(); await component.load();
    let resolve!: (value: ReturnType<typeof historyResponse>) => void;
    api.projectAlertDeliveries.mockImplementation(() => new Promise(done => resolve = done));
    const old = component.inspectHistory(), finishOld = resolve;
    const fresh = component.inspectHistory(); finishOld(historyResponse()); await old;
    expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(true);
    resolve(historyResponse()); await fresh; expect(component.history()).not.toBeNull();
    api.saveProjectAlertPreference.mockResolvedValue(response());
    for (const action of [() => component.editFrequency('daily'), () => component.editFamily('crawl_failure', true),
      () => component.save(new Event('submit')), () => component.load()]) {
      await component.load();
      const pending = component.inspectHistory(), finish = resolve;
      await action(); finish(historyResponse()); await pending;
      expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(false);
    }
    const route = component.inspectHistory(), finishRoute = resolve;
    component.organizationId = 8; component.projectId = 10;
    api.projectAlertPreference.mockResolvedValue(response('off', 0, [], 10)); component.ngOnChanges(); await fixture.whenStable();
    finishRoute(historyResponse()); await route; expect(component.history()).toBeNull();
    const destroyed = component.inspectHistory(); fixture.destroy(); resolve(historyResponse([], false, 10)); await destroyed;
    expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(false);
  });

  it('rejects invalid history scope before asynchronous equality or requests and never leaves a spinner', async () => {
    const { api, component } = setup(); await component.load();
    for (const invalid of [NaN, 0, -1, 1.1, 2 ** 53]) {
      component.organizationId = invalid; await component.inspectHistory();
      expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(false); expect(component.historyError()).toBe(true);
    }
    expect(api.projectAlertDeliveries).not.toHaveBeenCalled();
  });
});
