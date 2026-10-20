import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { LocalFeedback } from './local-feedback';
import { environment } from '../../environments/environment';

const ID = '00000000-0000-4000-8000-000000000001';
class FeedbackApi {
  language: 'en' | 'tr' = 'en';
  productLanguage(): Promise<ApiResult> { return Promise.resolve({ status: 200, body: {
    language: this.language, current_ui_language: 'en', current_email_language: 'en' } }); }
  commands: Record<string, unknown>[] = []; rows: Record<string, unknown>[] = [];
  canReview = true; current = true; foreign = false; uncertain = false;
  historyPromise: Promise<ApiResult> | null = null; queries: string[] = [];
  result(org = 7, project = 9, reviews = this.rows.slice(-1).reverse()): ApiResult {
    return { status: 200, body: { organization_id: org, project_id: this.foreign ? 999 : project,
      can_review: this.canReview, policy_version: 'local-owned-feedback-v1', configuration_revision: 0,
      verified_origins: this.canReview ? ['https://feedback.example.invalid'] : [],
      assessments: this.canReview ? [{ id: 12, business_name: 'Synthetic service business', location_label: '', eligibility: 'unknown' }] : [],
      sources_has_more: false, reviews: reviews.map((row) => ({ ...row, source_current: this.current,
        is_latest: row['revision'] === this.rows.length, effective_approval: this.current && row['revision'] === this.rows.length
          && ['approved', 'reported'].includes(String(row['state'])) })), has_more: false } };
  }
  localFeedback(org: number, project: number, data?: Record<string, unknown>, id?: string, key?: string): Promise<ApiResult> {
    if (!data) {
      if (key) {
        this.queries.push(key);
        const reviews = this.rows.filter((row) => row['request_key'] === key);
        const result = this.result(org, project, reviews); result.body['lookup'] = reviews.length ? 'found' : 'not_found';
        return Promise.resolve(result);
      }
      return id && this.historyPromise ? this.historyPromise : Promise.resolve(this.result(org, project,
        id ? [...this.rows].reverse() : this.rows.slice(-1)));
    }
    this.commands.push(data);
    const row = { ...data, id: this.rows.length + 1, feedback_id: id || ID, project_id: project,
      revision: this.rows.length + 1, source_current: true, is_latest: true,
      effective_approval: ['approved', 'reported'].includes(String(data['state'])),
      approved_at: ['approved', 'reported'].includes(String(data['state'])) ? new Date().toISOString() : null,
      created_at: new Date().toISOString(), coverage: 'selected_customer_supplied_feedback_not_complete_history',
      execution_state: data['executed_at'] ? 'customer_reported_not_verified' : 'not_reported' };
    this.rows.push(row);
    return this.uncertain ? Promise.reject(new Error('Lost acknowledgement')) : Promise.resolve({ status: id ? 200 : 201,
      body: { organization_id: org, project_id: project, review: row } });
  }
}

describe('Private independent feedback source and exact human reply journey', () => {
  let api: FeedbackApi;
  beforeEach(() => { api = new FeedbackApi(); TestBed.configureTestingModule({ providers: [provideRouter([
    { path: 'feedback/:organizationId/:projectId', component: LocalFeedback },
    { path: 'away', component: LocalFeedback },
  ]), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create();
    const component = await harness.navigateByUrl('/feedback/7/9', LocalFeedback);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  function fillDraft(harness: RouterTestingHarness, rights = true) {
    const form = harness.routeNativeElement!.querySelector('form:has([name="feedback_excerpt"])') as HTMLFormElement;
    for (const [key, value] of Object.entries({ source_url: 'https://feedback.example.invalid/own-feedback',
      feedback_reference: 'own-feedback-1', received_at: '2026-10-01T10:00:00+03:00',
      feedback_excerpt: 'Original <img src=x onerror=evil()> &amp; text', theme: 'Human interpretation only',
      reply_draft: 'Exact human reply <script>literal</script>', evidence_note: 'Independent source, selected excerpt only.', reason: 'Human decision' })) {
      (form.elements.namedItem(key) as HTMLInputElement).value = value;
    }
    for (const key of ['storage_permission', 'not_api_derived']) (form.elements.namedItem(key) as HTMLInputElement).checked = rights;
    return form;
  }
  async function submit(harness: RouterTestingHarness, form: HTMLFormElement) {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await harness.fixture.whenStable(); harness.detectChanges();
  }
  async function decision(harness: RouterTestingHarness, component: LocalFeedback) {
    await component.inspect(ID); harness.detectChanges();
    const form = harness.routeNativeElement!.querySelector('form:has([name="exact"])') as HTMLFormElement;
    (form.elements.namedItem('reason') as HTMLTextAreaElement).value = 'Human reviewed exactly this revision.';
    (form.elements.namedItem('exact') as HTMLInputElement).checked = true;
    return form;
  }
  it.each(['en', 'tr'] as const)('requires separate independent storage rights and approves only the unchanged displayed source/text (%s)', async (language) => {
    api.language = language;
    const { harness, component } = await screen();
    const element = harness.routeNativeElement!;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel müşteriye ait geri bildirim incelemesi — OrganicSEOOps' : 'Private customer-owned feedback review — OrganicSEOOps');
    expect(element.querySelector('[aria-labelledby="feedback-title"]')?.getAttribute('lang')).toBe(language);
    expect(element.querySelector('h1')?.textContent).toBe(language === 'tr' ? 'Müşterinin kendi sitesinden geri bildirim ve insan yanıtları' : 'Customer-owned website feedback and human replies');
    expect(element.querySelector('ul')?.getAttribute('aria-label')).toBe(language === 'tr' ? 'En son müşteri geri bildirim kararları' : 'Latest customer feedback decisions');
    expect(element.textContent).toContain(language === 'tr' ? 'tüm yorum geçmişi veya ölçülmüş tema sıklığı değildir' : 'not complete review history or measured theme frequency');
    expect(element.textContent).toContain(language === 'tr' ? '90 günlük erişim' : '90-day retained access');
    expect(element.textContent).toContain(language === 'tr' ? '30 gün içinde etkin silme' : 'within 30 days');
    expect(element.textContent).toContain(language === 'tr' ? 'en fazla 35 günlük yedek' : '35-day backup');
    expect(Array.from(element.querySelectorAll('[lang="en"]')).some(node => node.textContent === 'unknown')).toBe(true);
    const unsaved = fillDraft(harness); const reads = vi.spyOn(api, 'localFeedback');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private customer-owned feedback review — OrganicSEOOps' : 'Özel müşteriye ait geri bildirim incelemesi — OrganicSEOOps');
    expect(element.querySelector('form:has([name="feedback_excerpt"])')).toBe(unsaved);
    expect((unsaved.elements.namedItem('reply_draft') as HTMLTextAreaElement).value).toBe('Exact human reply <script>literal</script>');
    expect((unsaved.elements.namedItem('storage_permission') as HTMLInputElement).checked).toBe(true);
    expect(reads).not.toHaveBeenCalled(); component.productLanguage.set(language); harness.detectChanges(); reads.mockRestore();
    for (const name of ['source_url', 'feedback_reference', 'received_at', 'feedback_excerpt', 'theme', 'reply_draft', 'evidence_note', 'reason']) {
      expect(unsaved.querySelector(`[name="${name}"]`)?.getAttribute('lang')).toBe('');
    }
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    await submit(harness, fillDraft(harness, false)); expect(api.commands).toEqual([]);
    await submit(harness, fillDraft(harness)); expect(api.commands[0]['state']).toBe('draft');
    const intake = api.commands[0]['intake'];
    await submit(harness, await decision(harness, component));
    expect(api.commands[1]['state']).toBe('review'); expect(api.commands[1]['expected_revision']).toBe(1);
    await submit(harness, await decision(harness, component));
    expect(api.commands[2]['state']).toBe('approved'); expect(api.commands[2]['intake']).toEqual(intake);
    expect(api.commands[2]['executed_at']).toBeNull();
    await component.inspect(ID); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain('Exact human reply <script>literal</script>');
    expect(harness.routeNativeElement!.querySelector('script, img, iframe')).toBeNull();
    expect(element.textContent).toContain(language === 'tr' ? 'Google API içeriği' : 'No Google API content');
    expect(element.textContent).toContain(language === 'tr' ? 'Onay bir yanıt göndermez' : 'Approval does not send a reply');
    expect(element.textContent).toContain(language === 'tr' ? 'Yenileme anında tam onay güncel; otomatik uygulama yok' : 'Exact approval current at refresh; no automated execution');
    expect(element.querySelector('details summary')?.textContent).toBe(language === 'tr' ? 'Değiştirilemez kaynak/metin/onay geçmişi (en yeni 20)' : 'Immutable source/text/approval history (newest 20)');
    expect(element.querySelector('#feedback-selected-title')?.textContent).toContain(language === 'tr' ? 'Tam geri bildirim' : 'Exact feedback');
    for (const text of ['Original <img src=x onerror=evil()> &amp; text', 'Human interpretation only', 'Exact human reply <script>literal</script>', 'Human reviewed exactly this revision.']) {
      expect(Array.from(element.querySelectorAll('[lang=""]')).some(node => node.textContent === text)).toBe(true);
    }
    expect(element.querySelector('#feedback-selected-title ~ p [lang="en"]')?.textContent).toBe('approved');
    const report = await decision(harness, component);
    (report.elements.namedItem('executed_at') as HTMLInputElement).value = '2026-10-01T14:30';
    (report.elements.namedItem('execution_note') as HTMLTextAreaElement).value = 'Actual manual execution reported by user.';
    await submit(harness, report); expect(api.commands[3]['state']).toBe('reported');
    expect(api.commands[3]['executed_at']).toBe(new Date('2026-10-01T14:30').toISOString());
    await component.inspect(ID); harness.detectChanges(); component.edit(component.selected()!); harness.detectChanges();
    const correction = fillDraft(harness); (correction.elements.namedItem('reply_draft') as HTMLTextAreaElement).value = 'Edited reply';
    await submit(harness, correction);
    expect(api.commands[4]['state']).toBe('draft'); expect(api.commands[4]['expected_revision']).toBe(4);
    expect(api.commands[4]['executed_at']).toBeNull(); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    await component.inspect(ID); harness.detectChanges();
    const current = structuredClone(component.selected()!); current.intake.theme = ''; current.intake.reply_draft = '';
    component.selected.set(current); harness.detectChanges();
    expect(element.textContent).toContain(language === 'tr' ? 'Yok; tema üretilmedi' : 'Absent; no theme generated');
    expect(element.textContent).toContain(language === 'tr' ? 'Yok; yanıt üretilmedi' : 'Absent; no reply generated');
    if (language === 'tr') {
      const preference = vi.spyOn(api, 'productLanguage');
      async function reload() {
        await harness.navigateByUrl('/away', LocalFeedback);
        await harness.navigateByUrl('/feedback/7/9', LocalFeedback);
        await harness.fixture.whenStable(); harness.detectChanges();
        return harness.routeNativeElement!;
      }
      for (const result of [
        { status: 503, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: ['tr'], current_ui_language: 'en', current_email_language: 'en' } },
        { status: 200, body: { language: 'tr', current_ui_language: 'tr', current_email_language: 'en' } },
      ]) {
        preference.mockResolvedValue(result);
        expect((await reload()).querySelector('[aria-labelledby="feedback-title"]')?.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private customer-owned feedback review — OrganicSEOOps');
      }
      preference.mockRejectedValue(new Error('private preference unavailable'));
      const fallback = await reload();
      expect(fallback.querySelector('[aria-labelledby="feedback-title"]')?.getAttribute('lang')).toBe('en');
      expect(TestBed.inject(Title).getTitle()).toBe('Private customer-owned feedback review — OrganicSEOOps');
      expect(fallback.textContent).not.toContain('private preference unavailable'); preference.mockRestore();
      const buildEnvironment = environment as { production: boolean }; const production = buildEnvironment.production;
      try {
        buildEnvironment.production = true; const productionElement = await reload();
        expect(harness.routeDebugElement!.componentInstance.productLanguage()).toBe('tr');
        expect(productionElement.querySelector('[aria-labelledby="feedback-title"]')?.getAttribute('lang')).toBe('en');
        expect(TestBed.inject(Title).getTitle()).toBe('Private customer-owned feedback review — OrganicSEOOps');
        expect(productionElement.querySelector('h1')?.textContent).toBe('Customer-owned website feedback and human replies');
        expect(productionElement.textContent).not.toContain('iki dilli onay bekleniyor');
      } finally { buildEnvironment.production = production; }
    }
    const titleOwner = harness.routeDebugElement!.componentInstance as LocalFeedback;
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    titleOwner.productLanguage.set(titleOwner.productLanguage() === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('reconciles a lost acknowledgement from immutable request history without replay (%s)', async (language) => {
    api.language = language;
    const { harness, component } = await screen(); api.uncertain = true;
    await submit(harness, fillDraft(harness)); expect(component.pending()).not.toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Belirsiz kaydı kontrol et' : 'Check uncertain save');
    const frozen = component.pending(); const reads = vi.spyOn(api, 'localFeedback');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toBe(frozen); expect(reads).not.toHaveBeenCalled();
    component.productLanguage.set(language); harness.detectChanges();
    const missing = api.result(7, 9, []); missing.body['lookup'] = 'not_found'; reads.mockResolvedValueOnce(missing);
    await component.reconcile(); harness.detectChanges();
    expect(component.pending()).toBe(frozen); expect(api.commands).toHaveLength(1);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Aynı komutu yeniden dene' : 'Retry the same exact command');
    reads.mockRestore();
    await component.reconcile(); harness.detectChanges();
    expect(api.commands.length).toBe(1); expect(api.queries).toEqual([api.commands[0]['request_key']]);
    expect(component.pending()).toBeNull(); expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'komut yeniden çalıştırılmadı' : 'no command replayed');
  });
  it.each(['en', 'tr'] as const)('keeps member/viewer history read-only and removes reply decisions after current source loss (%s)', async (language) => {
    api.language = language;
    api.canReview = false; const { harness, component } = await screen();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Salt okunur geçmiş' : 'Read-only history');
    api.canReview = true; await component.load(); harness.detectChanges(); await submit(harness, fillDraft(harness));
    api.current = false; await component.inspect(ID); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('[name="exact"]')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Yeni inceleme, onay ve elle kullanım bildirimi reddedilir' : 'New review, approval and manual-use reporting are denied');
    api.canReview = false; await component.inspect(ID); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    api.foreign = true; await component.load(); expect(component.context()).toBeNull();
  });
  it('discards late foreign-project/history responses and clears private records on route reuse', async () => {
    const { harness, component } = await screen(); await submit(harness, fillDraft(harness));
    let resolve!: (value: ApiResult) => void; api.historyPromise = new Promise((done) => resolve = done);
    const pending = component.inspect(ID); const old = api.result(7, 9, [...api.rows]);
    api.rows = []; await harness.navigateByUrl('/feedback/7/10', LocalFeedback); resolve(old); await pending;
    expect(component.selected()).toBeNull(); expect(component.historyRows()).toEqual([]); expect(component.editing()).toBeNull();
    expect(component.pending()).toBeNull(); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).not.toContain('Exact human reply <script>literal</script>');
  });
});
