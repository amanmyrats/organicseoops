import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { AccountApi, ApiResult } from '../account/account-api';
import { VisibilityDiscoverability } from './visibility-discoverability';
import { environment } from '../../environments/environment';

class DiscoverabilityApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  role: unknown = 'owner'; current = true; revision = 0; records = 0; requests: unknown[][] = []; pending: Promise<ApiResult> | null = null; foreign = false;
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: { project: { id: project, organization_id: org, name: 'Synthetic project', role: this.role } } }); }
  page(project = 9, id: number | null = null): ApiResult { return { status: 200, body: {
    method: 'visibility-discoverability-v1', project_id: project, selected_diagnostics_id: id, has_more: false,
    diagnostics: [{ id: 3, project_id: project, crawl_run_id: 2, observed_at: '2026-10-01T00:00:00Z', coverage: 'partial', source_current: this.current }],
    proposals: id === 3 ? [{ id: 4, project_id: this.foreign ? project + 100 : project, subject: 'https://example.invalid/service', detector: 'schema_invalid_syntax_candidate',
      evidence: { snapshot_id: 3, untrusted: '<script>literal</script>' }, source_current: this.current, proposal: 'Review verified facts; no citation guarantee.',
      detected_at: '2026-10-01T00:00:00Z', approval: 'requires_separate_exact_human_action_approval',
      review: this.revision ? { id: 5, revision: this.revision, priority: 'medium', reason: 'Human evidence rationale.' } : null }] : [],
    human_factual_concerns: [{ project_id: project, job_id: 8, review_id: 7, review_revision: 2, reviewed_at: '2026-10-01T01:00:00Z',
      collected_at: '2026-09-30T10:00:00Z', source_current: false, text: '<script>Unverified factual answer</script>', note: 'Check original records.', proposal: 'Human concern, not factual truth.' }],
    content_revisions: [{ project_id: project, item_id: 6, revision_id: 9, revision: 3, title: 'Human current draft', state: 'draft', brief_id: 11,
      reviewed_revision_id: null, created_at: '2026-10-01T01:00:00Z', proposal: 'Review exact sources and expertise; no verified live-page quality.' }],
  } }; }
  visibilityDiscoverability(_org: number, project: number, id: number | null) { return this.pending || Promise.resolve(this.page(project, id)); }
  recordTechnicalFindings(_org: number, project: number, _id: number) { this.records++; return Promise.resolve({ status: 201, body: { project_id: project } }); }
  reviewFinding(...data: unknown[]) { this.requests.push(data); this.revision++; return Promise.resolve({ status: 201, body: { project_id: data[1], approved_action: null } }); }
}

describe('Source-supported human discoverability consumer', () => {
  let api: DiscoverabilityApi;
  beforeEach(() => { api = new DiscoverabilityApi(); TestBed.configureTestingModule({ providers: [
    provideRouter([{ path: 'guidance/:organizationId/:projectId', component: VisibilityDiscoverability }]), { provide: AccountApi, useValue: api }] }); });
  async function screen(preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } }) {
    api.preference = preference;
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/guidance/7/9', VisibilityDiscoverability);
    await harness.fixture.whenStable(); harness.detectChanges(); return { harness, component };
  }
  it('rejects malformed visibility roles before source reads and preserves scalar role permissions', async () => {
    const { component, harness } = await screen(); await component.load(3); const source = vi.spyOn(api, 'visibilityDiscoverability');
    for (const role of ['owner', 'admin', 'member', 'viewer']) {
      const reads = source.mock.calls.length; api.role = [role]; await component.load(3); harness.detectChanges();
      expect(component.canReview()).toBe(false); expect(component.evidence()).toBeNull(); expect(component.error()).not.toBe('');
      expect(source.mock.calls).toHaveLength(reads); expect(harness.routeNativeElement?.querySelector('form')).toBeNull();
      await component.materialize(); expect(api.records).toBe(0);
      api.role = role; await component.load(3); expect(component.error()).toBe(''); expect(component.evidence()?.proposals).toHaveLength(1);
      expect(component.canReview()).toBe(role === 'owner' || role === 'admin');
    }
    expect(api.requests).toEqual([]); source.mockRestore();
  });

  it.each(['en', 'tr'] as const)('separates bot purposes and unknown access, exact human/content sources and untrusted literal evidence in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); await component.load(3); harness.detectChanges();
    const text = harness.routeNativeElement!.textContent!;
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Özel keşfedilebilirlik önerileri — OrganicSEOOps' : 'Private discoverability proposals — OrganicSEOOps');
    expect(text).toContain(language === 'tr' ? 'GPTBot: olası eğitim' : 'GPTBot: potential training'); expect(text).toContain(language === 'tr' ? 'robots kuralları geçerli olmayabilir' : 'robots rules may not apply');
    expect(text).toContain(language === 'tr' ? 'bu aracıların erişimini kanıtlayamaz' : 'cannot establish any of these agents'); expect(text).toContain(language === 'tr' ? 'Onaylanmış iş gerçeği kaydı yok' : 'No approved business-fact registry');
    expect(text).toContain('<script>literal</script>'); expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('details pre')!.getAttribute('lang')).toBe('');
    expect(harness.routeNativeElement!.querySelector('a[href="/app/visibility-samples/7/9/8"]')).not.toBeNull();
    expect(text).toContain(language === 'tr' ? 'Bağlı brief 11' : 'Linked brief 11'); expect(api.records).toBe(0); expect(api.requests).toEqual([]);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(language === 'tr' ? 'Kaynakla desteklenen keşfedilebilirlik önerileri' : 'Source-supported discoverability proposals');
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    const source = harness.routeNativeElement!.querySelector<HTMLSelectElement>('#discoverability-source')!;
    expect(source.value).toBe('3'); expect(source.querySelector('option[value="3"]')!.getAttribute('lang')).toBe('en');
    expect(source.querySelector('option[value="3"]')!.textContent).toContain('Diagnostics 3');
    const retained = component.evidence(), reads = vi.spyOn(api, 'visibilityDiscoverability');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Private discoverability proposals — OrganicSEOOps' : 'Özel keşfedilebilirlik önerileri — OrganicSEOOps');
    expect(component.evidence()).toBe(retained); expect(component.selectedId).toBe(3);
    expect(harness.routeNativeElement!.querySelector('#discoverability-source')).toBe(source); expect(source.value).toBe('3');
    expect(reads).not.toHaveBeenCalled(); expect(api.records).toBe(0); expect(api.requests).toEqual([]); reads.mockRestore();
    component.productLanguage.set(language); harness.detectChanges();
    harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
    expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
  });
  it.each(['en', 'tr'] as const)('explicitly records technical candidates and human priority, leaving exact action approval separate in %s', async (language) => {
    const { harness, component } = await screen({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } }); await component.load(3); await component.materialize(); harness.detectChanges();
    expect(api.records).toBe(1);
    const form = harness.routeNativeElement!.querySelector<HTMLFormElement>('form')!;
    (form.elements.namedItem('reason') as HTMLTextAreaElement).value = 'Human evidence rationale.';
    (form.elements.namedItem('priority') as HTMLSelectElement).value = 'medium';
    expect(form.querySelector('label')!.textContent).toBe(language === 'tr' ? 'İnsan önceliği' : 'Human priority');
    expect(form.querySelector('option[value=medium]')!.textContent).toBe(language === 'tr' ? 'Orta' : 'Medium');
    const rationale = form.elements.namedItem('reason') as HTMLTextAreaElement;
    expect(rationale.required).toBe(true); expect(rationale.maxLength).toBe(240); expect(rationale.getAttribute('lang')).toBe('');
    const retained = component.evidence(), reads = vi.spyOn(api, 'visibilityDiscoverability');
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBe(form); expect(form.elements.namedItem('reason')).toBe(rationale);
    expect(rationale.value).toBe('Human evidence rationale.'); expect((form.elements.namedItem('priority') as HTMLSelectElement).value).toBe('medium');
    expect((form.elements.namedItem('effort') as HTMLSelectElement).value).toBe('unknown'); expect((form.elements.namedItem('value') as HTMLSelectElement).value).toBe('unknown');
    expect(component.evidence()).toBe(retained); expect(reads).not.toHaveBeenCalled(); expect(api.records).toBe(1); expect(api.requests).toEqual([]); reads.mockRestore();
    component.productLanguage.set(language); harness.detectChanges();
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(component.evidence()?.proposals[0].review?.revision).toBe(1)); harness.detectChanges();
    expect(api.requests[0]).toEqual([7, 9, 4, 0, 'medium', 'unknown', 'unknown', 'Human evidence rationale.']);
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'Bu onaylanmış web sitesi değişikliği değildir' : 'This is not an approved website change');
    expect(harness.routeNativeElement!.querySelector('a[href="/app/actions/7/9"]')).not.toBeNull();
  });
  it('keeps viewer/stale scope read-only and clears foreign or late scope evidence', async () => {
    api.role = 'viewer'; const { harness, component } = await screen(); await component.load(3); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull(); await component.materialize(); expect(api.records).toBe(0);
    api.role = 'owner'; api.current = false; await component.load(3); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('form')).toBeNull();
    let resolve!: (value: ApiResult) => void; api.pending = new Promise((done) => resolve = done);
    const late = component.load(3); await Promise.resolve(); await Promise.resolve(); api.pending = null;
    await harness.navigateByUrl('/guidance/7/10', VisibilityDiscoverability); resolve(api.page(9, 3)); await late;
    await harness.fixture.whenStable(); expect(component.evidence()?.project_id).toBe(10);
    api.foreign = true; await component.load(3); expect(component.evidence()).toBeNull(); expect(component.error()).toContain('unavailable');
  });
  it('keeps invalid incompatible denied unavailable and production discoverability preferences English', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); api = new DiscoverabilityApi();
        TestBed.configureTestingModule({ providers: [provideRouter([{ path: 'guidance/:organizationId/:projectId', component: VisibilityDiscoverability }]), { provide: AccountApi, useValue: api }] });
        buildEnvironment.production = mode === 'production';
        const preference: ApiResult | Error = mode === 'unavailable' ? new Error('private preference error') : mode === 'signed-out' ? { status: 401, body: {} }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(preference);
        expect(TestBed.inject(Title).getTitle()).toBe('Private discoverability proposals — OrganicSEOOps');
        expect(component.uiLanguage()).toBe('en'); expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe('Source-supported discoverability proposals');
        expect(harness.routeNativeElement!.textContent).not.toContain('incelenmemiş Türkçe'); expect(harness.routeNativeElement!.textContent).not.toContain('private preference error');
        api.foreign = true; await component.load(3); harness.detectChanges();
        expect(harness.routeNativeElement!.querySelector('[role=alert]')!.textContent).toBe('Discoverability source evidence unavailable or access revoked. Refresh current scope.');
        expect(component.evidence()).toBeNull(); expect(api.records).toBe(0); expect(api.requests).toEqual([]); harness.fixture.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });

});
