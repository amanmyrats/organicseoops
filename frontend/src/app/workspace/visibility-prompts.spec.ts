import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { AccountApi, ApiResult } from '../account/account-api';
import { VisibilityPrompts } from './visibility-prompts';
import { environment } from '../../environments/environment';

class MethodApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  role: unknown = 'owner';
  saved: Record<string, unknown>[] = [];
  pending: Promise<ApiResult> | null = null;
  row = { id: 1, project_id: 9, set_id: '11111111-1111-4111-8111-111111111111', revision: 1,
    label: 'Synthetic methodology', language: 'en', market: 'Turkey', source_current: true, collection_available: true,
    created_at: '2026-10-01T00:00:00Z', review_note: 'Human coverage, not measured demand.',
    policy: { max_output_tokens: 128, max_cost_usd: '0.05' },
    prompts: [{ key: 'neutral', kind: 'neutral', text: 'Which service should a buyer consider?', intent_review_id: 7 }] };
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: {
    project: { id: project, organization_id: org, name: 'Synthetic project', role: this.role } } }); }
  visibilityPrompts(_org: number, project: number, setId = '', data?: Record<string, unknown>): Promise<ApiResult> {
    if (data) {
      this.saved.push(data); this.row = { ...this.row, revision: 2, prompts: data['prompts'] as typeof this.row.prompts };
      return Promise.resolve({ status: 201, body: { project_id: project, prompt_set: this.row } });
    }
    if (setId && this.pending) return this.pending;
    return Promise.resolve({ status: 200, body: { project_id: project, method: 'api-text-visibility-v1', collection_available: true,
      prompt_sets: project === 9 ? [this.row] : [], languages: ['en'], brand_aliases: ['Synthetic Brand'], market: 'Turkey',
      intent_reviews: [{ review_id: 7, label: 'Human service intent', language: 'en', market: 'Turkey', source_current: true }] } });
  }
}

describe('Private API visibility methodology', () => {
  it('rejects malformed visibility roles before source reads and preserves scalar role permissions', async () => {
    const api = new MethodApi();
    TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'visibility/:organizationId/:projectId', component: VisibilityPrompts }]),
      { provide: AccountApi, useValue: api }] });
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/visibility/7/9', VisibilityPrompts); await harness.fixture.whenStable();
    const source = vi.spyOn(api, 'visibilityPrompts');
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      const reads = source.mock.calls.length; api.role = [role]; await component.load(); harness.detectChanges();
      expect(component.canEdit()).toBe(false); expect(component.ready()).toBe(false); expect(component.error()).not.toBe('');
      expect(component.sets()).toEqual([]); expect(component.selected()).toBeNull(); expect(source.mock.calls).toHaveLength(reads);
      expect(harness.routeNativeElement?.querySelector('form')).toBeNull();
      api.role = role; await component.load(); expect(component.ready()).toBe(true); expect(component.error()).toBe('');
      expect(component.sets()).toHaveLength(1); expect(component.canEdit()).toBe(role === 'owner' || role === 'admin');
    }
    expect(api.saved).toEqual([]); source.mockRestore();
  });

  it.each(['en', 'tr'] as const)('saves exact human prompt corrections without collection and discards late foreign-route history in %s', async (language) => {
    const api = new MethodApi();
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'visibility/:organizationId/:projectId', component: VisibilityPrompts }]),
      { provide: AccountApi, useValue: api }] });
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/visibility/7/9', VisibilityPrompts);
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Yalnızca API görünürlüğü istem metodolojisi — OrganicSEOOps' : 'API-only visibility prompt methodology — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'tüketici ChatGPT gözlemleri' : 'not consumer ChatGPT observations');
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Sınırlı manuel API örneği' : 'bounded manual API sample');
    await component.open(api.row.set_id); harness.detectChanges();
    const text = harness.routeNativeElement!.querySelector<HTMLTextAreaElement>('#visibility-text-0')!;
    const exactPrompt = 'Which service should a buyer consider? Keep this <script> literal.';
    text.value = exactPrompt;
    text.dispatchEvent(new Event('input', { bubbles: true }));
    const form = harness.routeNativeElement!.querySelector('form')!;
    const label = form.elements.namedItem('label') as HTMLInputElement;
    const tokens = form.elements.namedItem('max_output_tokens') as HTMLInputElement;
    const cost = form.elements.namedItem('max_cost_usd') as HTMLInputElement;
    const note = form.elements.namedItem('review_note') as HTMLTextAreaElement;
    const acknowledge = form.elements.namedItem('acknowledge') as HTMLInputElement;
    const seoLanguage = form.elements.namedItem('language') as HTMLSelectElement;
    const key = form.querySelector<HTMLInputElement>('#visibility-key-0')!;
    label.value = 'Unsaved exact label'; tokens.value = '96'; cost.value = '0.025'; note.value = 'Unsaved human bias rationale';
    key.value = 'exact-key'; key.dispatchEvent(new Event('input', { bubbles: true }));
    acknowledge.checked = true;
    const history = component.history(), selected = component.selected(), drafts = component.drafts();
    const source = vi.spyOn(api, 'visibilityPrompts');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'API-only visibility prompt methodology — OrganicSEOOps' : 'Yalnızca API görünürlüğü istem metodolojisi — OrganicSEOOps');
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form);
    expect(form.querySelector('#visibility-text-0')).toBe(text); expect(text.value).toBe(exactPrompt);
    expect(form.querySelector('#visibility-key-0')).toBe(key); expect(key.value).toBe('exact-key');
    expect(label.value).toBe('Unsaved exact label'); expect(tokens.value).toBe('96'); expect(cost.value).toBe('0.025');
    expect(note.value).toBe('Unsaved human bias rationale'); expect(acknowledge.checked).toBe(true);
    expect(seoLanguage.value).toBe('en'); expect(component.language()).toBe('en');
    expect(component.history()).toBe(history); expect(component.selected()).toBe(selected); expect(component.drafts()).toBe(drafts);
    expect(source).not.toHaveBeenCalled(); expect(api.saved).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('pre span')!.getAttribute('lang')).toBe('');
    expect(harness.routeNativeElement!.querySelector('summary span')!.getAttribute('lang')).toBe('en');
    source.mockRestore();
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges();
    expect(api.saved[0]['expected_revision']).toBe(1);
    expect(api.saved[0]['request_key']).toEqual(expect.any(String));
    expect(api.saved[0]['label']).toBe('Unsaved exact label'); expect(api.saved[0]['language']).toBe('en');
    expect(api.saved[0]['max_output_tokens']).toBe(96); expect(api.saved[0]['max_cost_usd']).toBe('0.025');
    expect(api.saved[0]['review_note']).toBe('Unsaved human bias rationale');
    expect((api.saved[0]['prompts'] as { key: string }[])[0].key).toBe('exact-key');
    expect((api.saved[0]['prompts'] as { text: string }[])[0].text).toBe(exactPrompt);
    expect(api.saved[0]['acknowledge_api_limits']).toBe(true);
    expect(component.selected()?.revision).toBe(2);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Örnek toplanmadı, model seçilmedi' : 'No sample collected, no model selected');
    expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    let resolve!: (response: ApiResult) => void;
    api.pending = new Promise((done) => resolve = done);
    const pending = component.open(api.row.set_id);
    await harness.navigateByUrl('/visibility/7/10', VisibilityPrompts);
    resolve({ status: 200, body: { project_id: 9, prompt_sets: [api.row] } });
    await pending; await Promise.resolve(); await Promise.resolve(); harness.detectChanges();
    expect(component.history()).toEqual([]); expect(component.selected()).toBeNull();
    expect(harness.routeNativeElement!.textContent).not.toContain('Synthetic methodology');
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it('keeps malformed denied unavailable and production preferences English without exposing private failures', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); const api = new MethodApi(); buildEnvironment.production = mode === 'production';
        api.preference = mode === 'unavailable' ? new Error('private preference error') : mode === 'signed-out' ? { status: 401, body: {} }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'visibility/:organizationId/:projectId', component: VisibilityPrompts }]),
          { provide: AccountApi, useValue: api }] });
        const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/visibility/7/9', VisibilityPrompts);
        await harness.fixture.whenStable(); harness.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('API-only visibility prompt methodology — OrganicSEOOps');
        expect(component.uiLanguage()).toBe('en'); expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('API-text visibility prompt methodology');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe');
        expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        api.role = ['owner']; await component.load(); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role=alert]')!.textContent).toBe('Current project methodology unavailable or access revoked.');
        expect(component.ready()).toBe(false); expect(api.saved).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });

});
