import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { AccountApi, ApiResult } from '../account/account-api';
import { VisibilitySchedules } from './visibility-schedules';
import { environment } from '../../environments/environment';

class RepeatApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  role: unknown = 'owner'; failCreate = false; pending: Promise<ApiResult> | null = null;
  requests: { id: number; data?: Record<string, unknown>; query?: Record<string, string> }[] = [];
  sample = { prompt_set_id: 1, prompt_key: 'neutral', model_id: 2, account_id: 3, max_output_tokens: 100, max_cost_usd: '0.01', acknowledge_api_limits: true };
  row = { id: 8, project_id: 9, request_key: 'repeat-test-key', enabled: false, sample: this.sample,
    policy: { method: 'visibility-repeat-schedule-v1', interval_minutes: 1440, max_occurrences: 2, lifetime_days: 7,
      total_max_cost_usd: '0.02', acknowledge_repeat_data_use: true },
    selection: { model_identifier: 'synthetic-native', visibility: { revision: 1, prompt: { text: 'Exact human <script>text</script>' } } },
    expires_at: '2026-10-09T00:00:00Z', next_run_at: null as string | null, last_run_at: null, queued_occurrences: 0,
    skipped_occurrences: 0, attempted_units: 0, blocked_reason: '', last_error_category: '', job_ids: [] as number[] };
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: {
    project: { id: project, organization_id: org, name: 'Synthetic project ' + project, role: this.role } } }); }
  visibilitySamples(_org: number, project: number) { return Promise.resolve({ status: 200, body: { project_id: project,
    models: [{ id: 2, provider_id: 1, name: 'Synthetic model', identifier: 'synthetic-native' }],
    accounts: [{ id: 3, provider_id: 1, label: 'Synthetic account', source: 'organization' }],
    prompt_sets: [{ id: 1, project_id: project, label: 'Human set', revision: 1, source_current: true,
      prompts: [{ key: 'neutral', kind: 'neutral', text: 'Exact human <script>text</script>' }], policy: { max_output_tokens: 128, max_cost_usd: '0.05' } }] } }); }
  visibilitySchedules(_org: number, project: number, id = 0, data?: Record<string, unknown>, query?: Record<string, string>): Promise<ApiResult> {
    this.requests.push({ id, data, query });
    if (data && !id) {
      this.row.request_key = String(data['idempotency_key']);
      if (this.failCreate) return Promise.reject(new Error('uncertain'));
    }
    if (data && id) { this.row.enabled = data['enabled'] === true; this.row.next_run_at = this.row.enabled ? '2026-10-03T00:00:00Z' : null; }
    if (id && this.pending) return this.pending;
    const row = { ...this.row, project_id: project };
    return Promise.resolve({ status: data ? id ? 200 : 201 : 200, body: { project_id: project, method: 'visibility-repeat-schedule-v1',
      ...(id || data ? { schedule: row } : { schedules: project === 9 ? [row] : [], has_more: false, next_before_id: null,
        lookup: query?.['request_key'] ? 'found' : 'not_requested' }) } });
  }
}

describe('Private finite opt-in API-text repeats', () => {
  let api: RepeatApi;
  beforeEach(() => { api = new RepeatApi(); TestBed.configureTestingModule({ providers: [
    provideRouter([{ path: 'repeats/:organizationId/:projectId', component: VisibilitySchedules }]), { provide: AccountApi, useValue: api }] }); });
  async function screen(language: 'en' | 'tr' = 'en') {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/repeats/7/9', VisibilitySchedules);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  function fill(harness: RouterTestingHarness, component: VisibilitySchedules) {
    component.setId.set(1); component.modelId.set(2); harness.detectChanges();
    const form = harness.routeNativeElement!.querySelector<HTMLFormElement>('.repeat-create')!;
    const values = { prompt_set_id: '1', prompt_key: 'neutral', model_id: '2', account_id: '3', max_output_tokens: '100',
      max_cost_usd: '0.01', interval_minutes: '1440', max_occurrences: '2', lifetime_days: '7', total_max_cost_usd: '0.02' };
    for (const [key, value] of Object.entries(values)) (form.elements.namedItem(key) as HTMLInputElement).value = value;
    (form.elements.namedItem('acknowledge') as HTMLInputElement).checked = true;
    return form;
  }
  it('rejects malformed visibility roles before source reads and preserves scalar role permissions', async () => {
    const { component, harness } = await screen(); const source = vi.spyOn(api, 'visibilitySchedules');
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      const reads = source.mock.calls.length; api.role = [role]; await component.load(); harness.detectChanges();
      expect(component.canManage()).toBe(false); expect(component.ready()).toBe(false); expect(component.error()).not.toBe('');
      expect(component.schedules()).toEqual([]); expect(source.mock.calls).toHaveLength(reads);
      expect(harness.routeNativeElement?.querySelector('form')).toBeNull(); await component.change(api.row, true);
      expect(source.mock.calls).toHaveLength(reads);
      api.role = role; await component.load(); expect(component.ready()).toBe(true); expect(component.error()).toBe('');
      expect(component.schedules()).toHaveLength(1); expect(component.canManage()).toBe(role === 'owner' || role === 'admin');
    }
    expect(api.requests.filter(row => row.data)).toEqual([]); source.mockRestore();
  });

  it.each(['en', 'tr'] as const)('saves paused with explicit bounded selection; separate acknowledge enable/pause, inert text and no provider command in %s', async (language) => {
    const { harness, component } = await screen(language);
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'İsteğe bağlı özel API metni tekrarları — OrganicSEOOps' : 'Private opt-in API-text repeats — OrganicSEOOps');
    expect(component.setId()).toBe(0); expect(component.modelId()).toBe(0);
    const form = fill(harness, component);
    const controls = [...form.querySelectorAll('input, select')], values = [...new FormData(form)];
    const selected = component.selectedSet(), schedules = component.schedules(); const reads = [...api.requests];
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private opt-in API-text repeats — OrganicSEOOps' : 'İsteğe bağlı özel API metni tekrarları — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('.repeat-create')).toBe(form);
    expect([...form.querySelectorAll('input, select')]).toEqual(controls); expect([...new FormData(form)]).toEqual(values);
    expect(component.selectedSet()).toBe(selected); expect(component.modelId()).toBe(2); expect(component.schedules()).toBe(schedules);
    expect(api.requests).toEqual(reads); component.productLanguage.set(language); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges();
    const write = api.requests.find((row) => row.data)!;
    expect(write.data).toMatchObject({ sample: api.sample, max_occurrences: 2, lifetime_days: 7, total_max_cost_usd: '0.02', acknowledge_repeat_data_use: true });
    expect(component.schedules()[0].enabled).toBe(false);
    expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'toplam üst sınır 0.02' : 'total ceiling 0.02');
    const enable = Array.from(harness.routeNativeElement!.querySelectorAll<HTMLFormElement>('form')).find((row) => row !== form)!;
    const consent = enable.elements.namedItem('acknowledge') as HTMLInputElement; consent.checked = true;
    const paused = component.schedules()[0], policy = paused.policy, expires = paused.expires_at;
    const commands = api.requests.length;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect([...harness.routeNativeElement!.querySelectorAll('form')]).toContain(enable);
    expect(enable.elements.namedItem('acknowledge')).toBe(consent); expect(consent.checked).toBe(true);
    expect(component.schedules()[0]).toBe(paused); expect(paused.policy).toBe(policy); expect(paused.expires_at).toBe(expires);
    expect(api.requests).toHaveLength(commands); component.productLanguage.set(language); harness.detectChanges();
    enable.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges(); expect(component.schedules()[0].enabled).toBe(true);
    await component.change(component.schedules()[0], false); expect(component.schedules()[0].enabled).toBe(false);
    expect(component.schedules()[0].expires_at).toBe(expires); expect(component.schedules()[0].policy).toEqual(policy);
    expect(api.requests.filter((row) => row.data).map((row) => row.id)).toEqual([0, 8, 8]);
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('freezes uncertain creation and reconciles exact key via GET without replay, including refresh in %s', async (language) => {
    const { harness, component } = await screen(language); api.failCreate = true;
    const form = fill(harness, component); form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges(); expect(component.uncertain()).toBe(true);
    const controls = [...form.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select')];
    const values = controls.map(row => [row.value, row instanceof HTMLInputElement ? row.checked : null]);
    const requests = [...api.requests], schedules = component.schedules(), key = api.row.request_key;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('.repeat-create')).toBe(form);
    expect([...form.querySelectorAll('input, select')]).toEqual(controls);
    expect(controls.map(row => [row.value, row instanceof HTMLInputElement ? row.checked : null])).toEqual(values);
    expect(component.schedules()).toBe(schedules); expect(component.uncertain()).toBe(true); expect(api.row.request_key).toBe(key);
    expect(form.querySelector('fieldset')!.disabled).toBe(true); expect(api.requests).toEqual(requests);
    component.productLanguage.set(language); harness.detectChanges();
    await component.change(component.schedules()[0], true); await component.load(); expect(component.uncertain()).toBe(true);
    await component.reconcile(); harness.detectChanges(); expect(component.uncertain()).toBe(false);
    expect(api.requests.filter((row) => row.data).length).toBe(1);
    expect(api.requests.at(-1)?.query?.['request_key']).toBe(api.row.request_key);
  });
  it('keeps member/viewer commands absent and clears late/foreign states on route reuse', async () => {
    api.role = 'member'; const { harness, component } = await screen();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    await component.change(component.schedules()[0], true); expect(api.requests.filter((row) => row.data).length).toBe(0);
    api.role = 'owner'; await component.load();
    let resolve!: (value: ApiResult) => void; api.pending = new Promise((done) => resolve = done);
    const command = component.change(component.schedules()[0], true);
    await harness.navigateByUrl('/repeats/7/10', VisibilitySchedules);
    resolve({ status: 200, body: { project_id: 9, schedule: { ...api.row, enabled: true } } }); await command;
    await harness.fixture.whenStable(); harness.detectChanges(); expect(component.schedules()).toEqual([]);
    expect(harness.routeNativeElement!.textContent).not.toContain('Exact human <script>text</script>');
    expect(component.uncertain()).toBe(false);
  });
  it('does not acknowledge a foreign or changed repeat decision as success', async () => {
    const { component } = await screen();
    api.pending = Promise.resolve({ status: 200, body: { project_id: 9, schedule: { ...api.row, project_id: 10, enabled: true } } });
    await component.change(component.schedules()[0], true); expect(component.uncertain()).toBe(true);
    await component.reconcile(); expect(component.uncertain()).toBe(true);
    expect(api.requests.filter((row) => row.data).length).toBe(1);
  });
  it('keeps malformed denied unavailable and production repeat preferences English', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new RepeatApi(); buildEnvironment.production = mode === 'production';
        api.preference = mode === 'unavailable' ? new Error('private preference error') : mode === 'signed-out' ? { status: 401, body: {} }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'repeats/:organizationId/:projectId', component: VisibilitySchedules }]), { provide: AccountApi, useValue: api }] });
        const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/repeats/7/9', VisibilitySchedules);
        await harness.fixture.whenStable(); harness.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Private opt-in API-text repeats — OrganicSEOOps');
        expect(component.uiLanguage()).toBe('en'); expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Private opt-in API-text repeats');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe'); expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        api.role = ['owner']; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role=alert]')!.textContent).toBe('Current repeat choices/history or project role unavailable.');
        expect(component.ready()).toBe(false); expect(api.requests.filter(row => row.data)).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });

});
