import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AccountApi } from '../account/account-api';
import { environment } from '../../environments/environment';
import { ProjectSummaryPreference } from './project-summary-preference';

function response(frequency = 'off', revision = 0, project = 9, state = 'rollout_off') {
  return { status: 200, body: { project_id: project,
    preference: { channel: 'email', frequency, revision, delivery_state: state } } };
}

function delivery(index = 0) {
  return { id: 100 - index, week_start: new Date(Date.parse('2026-09-28T00:00:00Z') - index * 7 * 86400000).toISOString().slice(0, 10),
    created_at: '2026-09-30T10:00:00.100001+00:00', attempted_at: null as string | null,
    accepted_at: null as string | null, state: 'queued', error_category: '' };
}

function historyResponse(rows = [delivery()], hasMore = false): { status: number; body: Record<string, unknown> } {
  return { status: 200, body: { method_version: 'own-weekly-delivery-history-v1', project_id: 9,
    scope: 'own_retained_transport_history_not_recipient_delivery_read_or_current_eligibility', rows, has_more: hasMore } };
}

function setup() {
  const api = { projectSummaryPreference: vi.fn(async () => response()),
    projectSummaryDeliveries: vi.fn(async () => historyResponse()),
    saveProjectSummaryPreference: vi.fn(async () => response('weekly', 1)) };
  TestBed.configureTestingModule({ providers: [{ provide: AccountApi, useValue: api }] });
  const fixture = TestBed.createComponent(ProjectSummaryPreference), component = fixture.componentInstance;
  component.organizationId = 7; component.projectId = 9;
  return { api, fixture, component };
}

describe('Self-owned project summary preference', () => {
  it.each(['en', 'tr'] as const)('defaults off and explicitly saves own weekly intent without delivery or replay (%s)', async (language) => {
    const { api, fixture, component } = setup();
    fixture.componentRef.setInput('language', language);
    await component.load(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
    expect(fixture.nativeElement.querySelector('span[lang="en"]').textContent).toBe('off');
    expect(component.choice()).toBe('off'); expect(api.saveProjectSummaryPreference).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'doğrudan e-posta planlamaz veya göndermez' : 'does not directly schedule or send mail');
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Haftalık teslimat etkinleştirilmemiş' : 'rollout is off');
    expect(fixture.nativeElement.querySelector('label[for="summary-frequency"]')).not.toBeNull();
    component.edit('weekly'); await component.save(new Event('submit')); fixture.detectChanges();
    expect(api.saveProjectSummaryPreference).toHaveBeenCalledWith(7, 9, 'weekly', 0);
    expect(component.revision()).toBe(1); expect(component.message()).toContain('did not directly schedule or send');
    component.edit('off'); expect(component.message()).toBe('');
    api.saveProjectSummaryPreference.mockResolvedValue(response('off', 2));
    await component.save(new Event('submit')); expect(component.savedFrequency()).toBe('off');
    component.edit('weekly'); const reads = api.projectSummaryPreference.mock.calls.length, saves = api.saveProjectSummaryPreference.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.choice()).toBe('weekly'); expect(component.savedFrequency()).toBe('off'); expect(component.revision()).toBe(2);
    expect(api.projectSummaryPreference).toHaveBeenCalledTimes(reads); expect(api.saveProjectSummaryPreference).toHaveBeenCalledTimes(saves);
    const buildEnvironment = environment as { production: boolean }, previous = buildEnvironment.production;
    try {
      buildEnvironment.production = true;
      const production = TestBed.createComponent(ProjectSummaryPreference); production.componentRef.setInput('language', 'tr'); production.detectChanges();
      expect(production.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
      expect(production.nativeElement.textContent).toContain('Your optional project summary preference'); production.destroy();
    } finally { buildEnvironment.production = previous; }
    expect(api.projectSummaryPreference).toHaveBeenCalledTimes(reads);
  });

  it('reconciles uncertain saves by fresh GET without replay and rejects malformed revision or foreign scope', async () => {
    const { api, component } = setup(); await component.load(); component.edit('weekly');
    api.saveProjectSummaryPreference.mockRejectedValue(new Error('unknown transport'));
    await component.save(new Event('submit'));
    expect(component.revision()).toBeNull(); expect(component.choice()).toBe('off');
    expect(component.error()).toContain('Refresh');
    await component.save(new Event('submit')); expect(api.saveProjectSummaryPreference).toHaveBeenCalledTimes(1);
    api.projectSummaryPreference.mockResolvedValue(response('weekly', 1)); await component.load();
    expect(component.savedFrequency()).toBe('weekly'); expect(api.saveProjectSummaryPreference).toHaveBeenCalledTimes(1);
    for (const invalid of [response('weekly', 0), response('daily', 1), response('off', -1), response('off', 1, 99)]) {
      api.projectSummaryPreference.mockResolvedValue(invalid); await component.load();
      expect(component.revision()).toBeNull(); expect(component.savedFrequency()).toBe('off');
    }
    api.projectSummaryPreference.mockResolvedValue(response()); await component.load(); component.edit('weekly');
    api.saveProjectSummaryPreference.mockResolvedValue(response('weekly', 2));
    await component.save(new Event('submit')); expect(component.revision()).toBeNull();
  });

  it('reports configured optional availability without claiming recipient eligibility or live readiness', async () => {
    const { api, component, fixture } = setup();
    api.projectSummaryPreference.mockResolvedValue(response('weekly', 1, 9, 'enabled_optional'));
    await component.load(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('enabled by configuration');
    expect(fixture.nativeElement.textContent).toContain('not confirmation of live email readiness');
    expect(api.projectSummaryDeliveries).not.toHaveBeenCalled();
    api.projectSummaryPreference.mockResolvedValue(response('off', 0, 9, 'not_implemented'));
    await component.load(); expect(component.revision()).toBeNull(); expect(component.deliveryState()).toBeNull();
  });

  it.each(['en', 'tr'] as const)('explicitly inspects cloned own transport states, empty and newest20 overflow without a send or replay (%s)', async (language) => {
    const { api, component, fixture } = setup();
    fixture.componentRef.setInput('language', language); await component.load(); fixture.detectChanges();
    expect(api.projectSummaryDeliveries).not.toHaveBeenCalled();
    const rows = ['queued', 'sending', 'transport_accepted', 'skipped', 'unknown'].map((state, index) => ({
      ...delivery(index), state, attempted_at: state === 'queued' ? null : '2026-09-30T10:00:00.100002Z',
      accepted_at: state === 'transport_accepted' ? '2026-09-30T10:00:00.100003+00:00' : null,
      error_category: state === 'skipped' ? 'current_source_or_recipient_changed' : state === 'unknown' ? 'worker_outcome_unknown' : '',
    }));
    api.projectSummaryDeliveries.mockResolvedValue(historyResponse(rows));
    fixture.nativeElement.querySelectorAll('button')[2].click(); await fixture.whenStable(); fixture.detectChanges();
    expect(api.projectSummaryDeliveries).toHaveBeenCalledWith(7, 9);
    expect(component.history()?.rows).toHaveLength(5);
    const stored = component.history(), reads = api.projectSummaryDeliveries.mock.calls.length;
    fixture.componentRef.setInput('language', language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
    expect(component.history()).toBe(stored); expect(api.projectSummaryDeliveries).toHaveBeenCalledTimes(reads);
    fixture.componentRef.setInput('language', language); fixture.detectChanges();
    for (const text of language === 'tr' ? ['Kuyrukta, gönderilmedi', 'Gönderim kalıcı olarak kaydedildi', 'teslim edildi veya okundu anlamına gelmez', 'Atlandı:', 'tekrar gönderilmez'] :
      ['Queued, not sent', 'Sending durably committed', 'not delivered or read', 'Skipped:', 'no replay']) {
      expect(fixture.nativeElement.textContent).toContain(text);
    }
    rows[0].created_at = 'untrusted mutation'; expect(component.history()?.rows[0].created_at).not.toBe('untrusted mutation');
    api.projectSummaryDeliveries.mockResolvedValue(historyResponse([], false)); await component.inspectHistory(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Size ait saklanmış haftalık kayıt yok' : 'No retained own weekly records');
    api.projectSummaryDeliveries.mockResolvedValue(historyResponse(Array.from({ length: 20 }, (_, i) => delivery(i)), true));
    await component.inspectHistory(); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'daha eski kayıtlar var' : 'older records exist');
    expect(api.saveProjectSummaryPreference).not.toHaveBeenCalled();
  });

  it('rejects extra/foreign fields, impossible UTC dates, microsecond reversal, inconsistent state and identity/order/cap', async () => {
    const { api, component } = setup(); await component.load();
    const invalidRows = [
      { id: 0 }, { id: true }, { id: 2 ** 53 }, { user_id: 7 }, { week_start: '2026-09-29' },
      { week_start: '2026-02-30' }, { week_start: '0000-01-03' }, { created_at: '2026-02-30T10:00:00Z' },
      { created_at: '2026-09-30T24:00:00Z' }, { created_at: '2026-09-30T10:00:00+01:00' },
      { created_at: '2026-09-30T10:00:00.1234567Z' }, { created_at: null }, { attempted_at: 'garbage' },
      { state: 'sending' }, { state: 'transport_accepted', attempted_at: '2026-09-30T10:00:00.100002Z' },
      { state: 'sending', attempted_at: '2026-09-30T10:00:00.100000Z' },
      { state: 'transport_accepted', attempted_at: '2026-09-30T10:00:00.100003Z', accepted_at: '2026-09-30T10:00:00.100002Z' },
      { state: 'skipped', attempted_at: '2026-09-30T10:00:00.100002Z', error_category: '<secret error>' },
      { state: 'unknown', attempted_at: '2026-09-30T10:00:00.100002Z', error_category: '' },
      { state: 'unknown', attempted_at: '2026-09-30T10:00:00.100002Z', error_category: ['delivery_uncertain'] },
      { error_category: 'worker_outcome_unknown' }, { accepted_at: '2026-09-30T10:00:00Z' }, { state: 'sent' },
    ];
    const invalid = invalidRows.map(delta => historyResponse([{ ...delivery(), ...delta }] as ReturnType<typeof delivery>[]));
    for (const delta of [{ project_id: 10 }, { scope: 'all_recipients' }, { method_version: 'v2' }, { has_more: 'false' },
      { has_more: true }, { address: 'private@example.invalid' }, { rows: null }]) {
      invalid.push({ ...historyResponse(), body: { ...historyResponse().body, ...delta } });
    }
    invalid.push(historyResponse([delivery(1), delivery(0)]), historyResponse([delivery(0), { ...delivery(1), id: 100 }]),
      historyResponse([delivery(0), { ...delivery(1), week_start: delivery(0).week_start }]),
      historyResponse(Array.from({ length: 21 }, (_, i) => delivery(i))), { status: 403, body: { message: 'private server copy' } });
    for (const value of invalid) {
      api.projectSummaryDeliveries.mockResolvedValue(value); await component.inspectHistory();
      expect(component.history()).toBeNull(); expect(component.historyError()).toBe(true);
    }
    api.projectSummaryDeliveries.mockRejectedValue(new Error('private network copy')); await component.inspectHistory();
    expect(component.history()).toBeNull(); expect(component.historyError()).toBe(true);
  });

  it('clears history and discards late results after edit/save, overlapping inspection, preference refresh, route and destroy', async () => {
    const { api, component, fixture } = setup(); await component.load(); await component.inspectHistory();
    component.edit('weekly'); expect(component.history()).toBeNull();
    let resolve!: (value: ReturnType<typeof historyResponse>) => void;
    api.projectSummaryDeliveries.mockImplementation(() => new Promise(done => resolve = done));
    const edited = component.inspectHistory(); const finishEdited = resolve;
    component.edit('off'); finishEdited(historyResponse()); await edited; expect(component.history()).toBeNull();
    const saving = component.inspectHistory(); const finishSaving = resolve;
    await component.save(new Event('submit')); finishSaving(historyResponse()); await saving; expect(component.history()).toBeNull();
    await component.load();
    const first = component.inspectHistory(); const finishFirst = resolve;
    const second = component.inspectHistory(); finishFirst(historyResponse()); await first;
    expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(true);
    resolve(historyResponse()); await second; expect(component.history()).not.toBeNull();
    const refreshing = component.inspectHistory(); const finishRefreshing = resolve;
    await component.load(); finishRefreshing(historyResponse()); await refreshing; expect(component.history()).toBeNull();
    const routed = component.inspectHistory(); const finishRoute = resolve;
    component.organizationId = 8; component.projectId = 10; component.ngOnChanges();
    finishRoute(historyResponse()); await routed; expect(component.history()).toBeNull();
    await fixture.whenStable(); component.projectId = 9; component.organizationId = 7; await component.load();
    const destroyed = component.inspectHistory(); fixture.destroy(); resolve(historyResponse()); await destroyed;
    expect(component.history()).toBeNull(); expect(component.historyBusy()).toBe(false); expect(component.historyError()).toBe(false);
  });

  it('clears late GET and POST after project change, refresh, and destruction', async () => {
    const { api, fixture, component } = setup(); await component.load();
    let resolve!: (value: ReturnType<typeof response>) => void;
    api.projectSummaryPreference.mockImplementation(() => new Promise(done => resolve = done));
    const oldGet = component.load();
    const finishOldGet = resolve;
    component.projectId = 10; component.ngOnChanges();
    finishOldGet(response('weekly', 1)); await oldGet;
    expect(component.revision()).toBeNull();
    resolve(response('off', 0, 10)); await fixture.whenStable();
    await Promise.resolve(); expect(component.revision()).toBe(0);
    component.edit('weekly');
    api.saveProjectSummaryPreference.mockImplementation(() => new Promise(done => resolve = done));
    const pending = component.save(new Event('submit'));
    const finishPost = resolve;
    const refreshing = component.load(); finishPost(response('weekly', 1, 10)); await pending;
    expect(component.revision()).toBeNull();
    fixture.destroy(); resolve(response('off', 0, 10)); await refreshing;
    expect(component.revision()).toBeNull(); expect(component.message()).toBe(''); expect(component.choice()).toBe('off');
  });
});
