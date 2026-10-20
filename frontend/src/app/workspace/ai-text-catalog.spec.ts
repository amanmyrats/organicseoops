import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { AccountApi } from '../account/account-api';
import { environment } from '../../environments/environment';
import { AIText } from './ai-text';

describe('Exact project AI catalog tier and account source', () => {
  it.each(['en', 'tr'] as const)('rejects enum arrays and preserves scalar unknown disabled and free consent controls without launching a job in %s', async (language) => {
    const api = {
      productLanguage: vi.fn(async () => ({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } })),
      projects: vi.fn(async () => ({ status: 200, body: { projects: [{ id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' }] } })),
      projectAITextCatalog: vi.fn(),
      projectAIRouting: vi.fn(async () => ({ status: 200, body: { policy: null, effective: null } })),
      aiTextHistory: vi.fn(async () => ({ status: 200, body: { jobs: [], has_more: false } })),
      createAIText: vi.fn(),
    };
    TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api },
      { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ organizationId: '7', projectId: '9' })) } }] });
    const screen = async (tier: unknown, source: unknown) => {
      api.projectAITextCatalog.mockResolvedValue({ status: 200, body: {
        models: [{ id: 3, provider_id: 5, name: 'Synthetic model', identifier: 'fixture', max_output_tokens: 200,
          access_tier: tier, price_known: true, privacy_policy_url: 'https://policy.example.invalid' }],
        accounts: [{ id: 4, provider_id: 5, label: 'Synthetic account', source }], cost_status: 'unknown',
      } });
      const fixture = TestBed.createComponent(AIText); fixture.detectChanges();
      await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false)); fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Yapay zekâ metin işi — OrganicSEOOps' : 'AI text job — OrganicSEOOps');
      return fixture;
    };
    for (const [tier, source] of [
      [['unknown'], 'organization'], [['standard'], 'organization'], [['free'], 'organization'],
      ['standard', ['platform']], ['standard', ['organization']],
    ]) {
      const fixture = await screen(tier, source);
      expect(fixture.componentInstance.models()).toEqual([]); expect(fixture.componentInstance.accounts()).toEqual([]);
      expect(fixture.nativeElement.querySelector('form')).toBeNull();
      expect(fixture.nativeElement.textContent).toContain(language === 'tr' ? 'yapay zekâ kataloğu kullanılamıyor' : 'AI catalog is unavailable'); fixture.destroy();
    }
    for (const [tier, source] of [['unknown', 'platform'], ['standard', 'organization'], ['free', 'organization']]) {
      const fixture = await screen(tier, source);
      const model = fixture.nativeElement.querySelector('#ai-model') as HTMLSelectElement;
      expect(model.querySelector<HTMLOptionElement>('option[value="3"]')!.disabled).toBe(tier === 'unknown');
      model.value = '3'; model.dispatchEvent(new Event('change')); fixture.detectChanges();
      const consent = fixture.nativeElement.querySelector('#ai-free-consent') as HTMLInputElement | null;
      expect(consent?.required ?? false).toBe(tier === 'free');
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
      expect(model.querySelector('option[value="3"]')!.getAttribute('lang')).toBe('');
      if (consent) {
        expect(consent.checked).toBe(false);
        expect(fixture.nativeElement.querySelector('label[for="ai-free-consent"]').textContent).toContain(language === 'tr' ? 'açıkça onay veriyorum' : 'explicitly opt in');
        expect(fixture.nativeElement.querySelector('a[target="_blank"]').href).toBe('https://policy.example.invalid/');
        const form = consent.closest('form')!;
        form.querySelector<HTMLSelectElement>('#ai-account')!.value = '4';
        form.querySelector<HTMLTextAreaElement>('#ai-prompt')!.value = 'Synthetic notes';
        form.querySelector<HTMLInputElement>('#ai-max-cost')!.value = '0.010000';
        expect(form.checkValidity()).toBe(false);
        form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
        await fixture.whenStable(); expect(api.createAIText).not.toHaveBeenCalled();
        consent.checked = true; expect(form.checkValidity()).toBe(true);
      }
      expect(fixture.nativeElement.querySelector('#ai-account').textContent).toContain(source);
      const component = fixture.componentInstance, reads = api.projectAITextCatalog.mock.calls.length;
      const prompt = fixture.nativeElement.querySelector('#ai-prompt') as HTMLTextAreaElement;
      prompt.value = 'Synthetic private notes';
      component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'AI text job — OrganicSEOOps' : 'Yapay zekâ metin işi — OrganicSEOOps');
      expect(fixture.nativeElement.querySelector('#ai-model')).toBe(model);
      expect(model.value).toBe('3'); expect(prompt.value).toBe('Synthetic private notes');
      expect(consent?.checked ?? false).toBe(tier === 'free');
      expect(api.projectAITextCatalog).toHaveBeenCalledTimes(reads); expect(api.createAIText).not.toHaveBeenCalled();
      fixture.destroy();
      TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
      component.productLanguage.set(language); TestBed.tick();
      expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
    }
    expect(api.createAIText).not.toHaveBeenCalled();
  });
  it('keeps invalid or unavailable personal AI-text preference and fresh production rendering English', async () => {
    const api = {
      productLanguage: vi.fn(),
      projects: vi.fn(async () => ({ status: 200, body: { projects: [] } })),
      projectAITextCatalog: vi.fn(async () => ({ status: 503, body: {} })),
      projectAIRouting: vi.fn(async () => ({ status: 200, body: { policy: null, effective: null } })),
      aiTextHistory: vi.fn(async () => ({ status: 200, body: { jobs: [], has_more: false } })),
    };
    TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api },
      { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ organizationId: '7', projectId: '9' })) } }] });
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const body of [{}, { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' },
        { language: 'tr', current_ui_language: 'tr', current_email_language: 'tr' },
        { language: 'en', current_ui_language: 'en', current_email_language: 'tr' }]) {
        api.productLanguage.mockResolvedValue({ status: 200, body });
        const fixture = TestBed.createComponent(AIText); fixture.detectChanges();
        await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false)); await fixture.whenStable(); fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('AI text job — OrganicSEOOps');
        expect(fixture.componentInstance.productLanguage()).toBe('en');
        expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en'); fixture.destroy();
      }
      for (const failure of ['status', 'transport']) {
        if (failure === 'status') api.productLanguage.mockResolvedValue({ status: 503, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
        else api.productLanguage.mockRejectedValue(new Error('private transport detail'));
        const fixture = TestBed.createComponent(AIText); fixture.detectChanges();
        await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false)); await fixture.whenStable(); fixture.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('AI text job — OrganicSEOOps');
        expect(fixture.componentInstance.productLanguage()).toBe('en');
        expect(fixture.nativeElement.textContent).not.toContain('private transport detail'); fixture.destroy();
      }
      buildEnvironment.production = true;
      api.productLanguage.mockResolvedValue({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
      const fixture = TestBed.createComponent(AIText); fixture.detectChanges();
        await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false)); await fixture.whenStable(); fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe('AI text job — OrganicSEOOps');
      expect(fixture.componentInstance.productLanguage()).toBe('tr');
      expect(fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
      expect(fixture.nativeElement.querySelector('h1').textContent).toBe('Select a model for this project');
      expect(fixture.nativeElement.textContent).toContain('Project or AI catalog is unavailable.');
      expect(fixture.nativeElement.textContent).not.toContain('incelenmemiş'); fixture.destroy();
    } finally { buildEnvironment.production = production; }
  });
});
