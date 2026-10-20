import { Title } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { environment } from '../../environments/environment';
import { JobDashboard } from './job-dashboard';

const job = { id: 77, project_id: 9, status: 'succeeded', progress_percent: 100,
  error_category: '', updated_at: '2026-01-01T00:00:00Z', output: {}, steps: [], citations: [] };

async function screen(detail: Record<string, unknown>, language: 'en' | 'tr' = 'en') {
  TestBed.resetTestingModule();
  const route = new BehaviorSubject(convertToParamMap({ organizationId: '7', projectId: '9', jobId: '77' }));
  const api = {
    productLanguage: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } })),
    projects: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { organization: { id: 7, role: 'member' },
      projects: [{ id: 9, organization_id: 7, name: 'Synthetic project' }] } })),
    jobs: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { jobs: [detail], has_more: false } })),
    jobSchedules: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { schedules: [], has_more: false } })),
    jobDetails: vi.fn(async () => ({ status: 200, body: { job: detail } })),
    createDiagnostic: vi.fn(), cancelJob: vi.fn(), retryJob: vi.fn(), createDiagnosticSchedule: vi.fn(),
  };
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api },
    { provide: ActivatedRoute, useValue: { paramMap: route.asObservable() } }] });
  const fixture = TestBed.createComponent(JobDashboard); fixture.detectChanges();
  await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false));
  return { api, fixture, component: fixture.componentInstance, route };
}

describe('Diagnostic job scalar status and requested identity', () => {
  it.each(['en', 'tr'] as const)('rejects array statuses before string formatting and renders valid scalar states without commands in %s', async (language) => {
    for (const status of ['queued', 'running', 'waiting_provider', 'succeeded', 'failed', 'cancelled', 'partially_succeeded']) {
      const invalid = await screen({ ...job, status: [status] }, language);
      expect(invalid.component.job(), status).toBeNull(); expect(invalid.component.jobs()).toEqual([]);
      invalid.fixture.detectChanges(); expect(invalid.fixture.nativeElement.querySelector('#job-detail-title')).toBeNull();
      invalid.fixture.destroy();
      const valid = await screen({ ...job, status }, language); valid.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Tanılama işi ilerlemesi — OrganicSEOOps' : 'Diagnostic job progress — OrganicSEOOps');
      const reads = valid.api.jobDetails.mock.calls.length;
      valid.component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); valid.fixture.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(language === 'tr' ? 'Diagnostic job progress — OrganicSEOOps' : 'Tanılama işi ilerlemesi — OrganicSEOOps');
      expect(valid.api.jobDetails.mock.calls).toHaveLength(reads);
      valid.component.productLanguage.set(language); valid.fixture.detectChanges();
      expect(valid.component.job()?.status).toBe(status);
      expect(valid.fixture.nativeElement.querySelector('#job-detail-title').textContent).toContain(status.replaceAll('_', ' '));
      expect(Array.from(valid.fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
        .some(button => button.textContent?.includes(language === 'tr' ? 'İptal isteyin' : 'Request cancellation'))).toBe(['queued', 'running', 'waiting_provider'].includes(status));
      expect(valid.api.cancelJob).not.toHaveBeenCalled(); expect(valid.api.retryJob).not.toHaveBeenCalled();
      expect(valid.api.createDiagnostic).not.toHaveBeenCalled(); expect(valid.api.createDiagnosticSchedule).not.toHaveBeenCalled();
      expect(valid.fixture.nativeElement.querySelector('section').getAttribute('lang')).toBe(language);
      expect(valid.fixture.nativeElement.querySelector('#job-detail-title span[lang="en"]').textContent).toBe(status.replaceAll('_', ' '));
      if (status === 'waiting_provider') {
        expect(valid.fixture.nativeElement.textContent).toContain(language === 'tr' ? 'Sağlayıcı yanıtı bekleniyor' : 'Waiting for a provider response');
        valid.api.cancelJob.mockResolvedValue({ status: 202, body: {} });
        valid.api.jobDetails.mockResolvedValue({ status: 200, body: { job: { ...job, status: 'cancelled' } } });
        [...valid.fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>]
          .find(button => button.textContent === (language === 'tr' ? 'İptal isteyin' : 'Request cancellation'))!.click();
        await vi.waitFor(() => expect(valid.component.busy()).toBe(false)); valid.fixture.detectChanges();
        expect(valid.api.cancelJob).toHaveBeenCalledExactlyOnceWith(7, 9, 77);
        expect(valid.fixture.nativeElement.textContent).toContain(language === 'tr' ? 'İptal istendi; bir aşama' : 'Cancellation requested; a stage');
      }
      valid.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
      valid.component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); TestBed.tick();
      expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
    }
  });

  it('rejects same-project wrong-job detail instead of exposing controls for the returned job', async () => {
    const { fixture, component, api } = await screen({ ...job, id: 78, status: 'running' });
    expect(component.job()).toBeNull(); expect(component.jobs()).toEqual([]);
    fixture.detectChanges(); expect(fixture.nativeElement.querySelector('#job-detail-title')).toBeNull();
    expect(component.error()).toContain('Job access changed');
    expect(api.jobDetails).toHaveBeenCalledWith(7, 9, 77); expect(api.cancelJob).not.toHaveBeenCalled();
    fixture.destroy();
  });

  it('withholds refreshed authority and dependent reads for foreign or missing organization/project metadata', async () => {
    const { api, fixture, component } = await screen(job);
    const original = await api.projects();
    expect(component.canLaunch()).toBe(true);
    for (const body of [
      { ...original.body, organization: { id: 8, role: 'member' } },
      { ...original.body, organization: { role: 'member' } },
      { ...original.body, projects: [{ id: 9, organization_id: 8, name: 'Foreign project' }] },
      { ...original.body, projects: [{ id: 9, name: 'Missing scope' }] },
    ]) {
      api.projects.mockResolvedValue({ status: 200, body });
      const reads = [api.jobs.mock.calls.length, api.jobSchedules.mock.calls.length, api.jobDetails.mock.calls.length];
      component.refresh(); expect(component.canLaunch()).toBe(false);
      await vi.waitFor(() => expect(component.loading()).toBe(false)); fixture.detectChanges();
      expect(component.projectName()).toBe(''); expect(component.job()).toBeNull(); expect(component.jobs()).toEqual([]);
      expect([api.jobs.mock.calls.length, api.jobSchedules.mock.calls.length, api.jobDetails.mock.calls.length]).toEqual(reads);
      expect(fixture.nativeElement.querySelector('#new-job-title')).toBeNull();
      expect(component.error()).toContain('project is unavailable');
    }
    api.projects.mockResolvedValue(original); component.refresh();
    await vi.waitFor(() => expect(component.loading()).toBe(false));
    expect(component.canLaunch()).toBe(true); expect(component.job()?.id).toBe(77); fixture.destroy();
  });

  it('rejects invalid numeric route IDs without fetching and keeps an absent job ID as the list route', async () => {
    const { api, fixture, component, route } = await screen(job);
    for (const change of [
      { organizationId: '7.5' }, { organizationId: '0' }, { organizationId: '9007199254740992' },
      { projectId: '9.5' }, { projectId: '' }, { jobId: '77.5' }, { jobId: '0' }, { jobId: 'invalid' },
    ]) {
      const reads = api.projects.mock.calls.length;
      route.next(convertToParamMap({ organizationId: '7', projectId: '9', jobId: '77', ...change }));
      await vi.waitFor(() => expect(component.loading()).toBe(false)); fixture.detectChanges();
      expect(api.projects.mock.calls.length).toBe(reads); expect(component.canLaunch()).toBe(false);
      expect(component.job()).toBeNull(); expect(component.error()).toContain('valid organization, project and job IDs');
    }
    const detailReads = api.jobDetails.mock.calls.length;
    route.next(convertToParamMap({ organizationId: '7', projectId: '9' }));
    await vi.waitFor(() => expect(component.loading()).toBe(false)); fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Diagnostic jobs — OrganicSEOOps');
    component.productLanguage.set('tr'); fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Tanılama işleri — OrganicSEOOps');
    expect(component.jobs()).toHaveLength(1); expect(component.canLaunch()).toBe(true);
    expect(component.job()).toBeNull(); expect(api.jobDetails.mock.calls.length).toBe(detailReads); 
    route.next(convertToParamMap({ organizationId: '7', projectId: '9', jobId: '77' }));
    await vi.waitFor(() => expect(component.loading()).toBe(false)); fixture.detectChanges();
    expect(TestBed.inject(Title).getTitle()).toBe('Tanılama işi ilerlemesi — OrganicSEOOps'); fixture.destroy();
  });

  it('stops stale context chains after either reader and preserves current refresh polling', async () => {
    for (const reader of ['jobs', 'jobSchedules'] as const) {
      const { api, fixture, component } = await screen({ ...job, status: 'running' });
      let release!: (result: ApiResult) => void;
      const pending = new Promise<ApiResult>(resolve => { release = resolve; });
      api[reader].mockReturnValueOnce(pending);
      const oldReads = api[reader].mock.calls.length;
      component.refresh();
      await vi.waitFor(() => expect(api[reader].mock.calls.length).toBe(oldReads + 1));
      const timers = vi.spyOn(globalThis, 'setTimeout');
      const clears = vi.spyOn(globalThis, 'clearTimeout');
      try {
        component.refresh();
        await vi.waitFor(() => expect(component.loading()).toBe(false));
        const timerIndex = timers.mock.calls.findIndex(call => call[1] === 2000);
        expect(timerIndex).toBeGreaterThanOrEqual(0);
        const currentTimer = timers.mock.results[timerIndex].value;
        const reads = [api.jobSchedules.mock.calls.length, api.jobDetails.mock.calls.length];
        release({ status: 200, body: { jobs: [job], schedules: [], has_more: false } });
        await new Promise<void>(resolve => setTimeout(resolve, 0));
        expect([api.jobSchedules.mock.calls.length, api.jobDetails.mock.calls.length]).toEqual(reads);
        expect(clears).not.toHaveBeenCalledWith(currentTimer);
        expect(component.job()?.status).toBe('running');
        expect(component.canLaunch()).toBe(true);
      } finally {
        fixture.destroy(); timers.mockRestore(); clears.mockRestore();
      }
    }
  });

  it('stops an old context chain before dependent reads after an invalid route change', async () => {
    const { api, fixture, component, route } = await screen(job);
    let release!: (result: ApiResult) => void;
    const pending = new Promise<ApiResult>(resolve => { release = resolve; });
    api.jobs.mockReturnValueOnce(pending);
    const oldReads = api.jobs.mock.calls.length;
    component.refresh();
    await vi.waitFor(() => expect(api.jobs.mock.calls.length).toBe(oldReads + 1));
    const reads = [api.projects.mock.calls.length, api.jobSchedules.mock.calls.length, api.jobDetails.mock.calls.length];
    route.next(convertToParamMap({ organizationId: '7', projectId: '9', jobId: '77.5' }));
    release({ status: 200, body: { jobs: [job], has_more: false } });
    await new Promise<void>(resolve => setTimeout(resolve, 0));
    try {
      expect([api.projects.mock.calls.length, api.jobSchedules.mock.calls.length, api.jobDetails.mock.calls.length]).toEqual(reads);
      expect(component.loading()).toBe(false); expect(component.canLaunch()).toBe(false);
      expect(component.job()).toBeNull(); expect(component.projectName()).toBe('');
      expect(component.error()).toContain('valid organization, project and job IDs');
    } finally { fixture.destroy(); }
  });

  it('keeps invalid unavailable preferences and fresh production diagnostics disabled in English', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        buildEnvironment.production = false;
        const { api, fixture } = await screen(job);
        fixture.destroy(); TestBed.resetTestingModule();
        if (mode === 'unavailable') api.productLanguage.mockRejectedValue(new Error('private preference error'));
        else api.productLanguage.mockResolvedValue(mode === 'signed-out' ? { status: 401, body: {} } : { status: 200, body: {
          language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } });
        const reads = api.projects.mock.calls.length;
        buildEnvironment.production = mode === 'production';
        const route = new BehaviorSubject(convertToParamMap({ organizationId: '7', projectId: '9', jobId: '77' }));
        TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api },
          { provide: ActivatedRoute, useValue: { paramMap: route.asObservable() } }] });
        const fresh = TestBed.createComponent(JobDashboard); fresh.detectChanges(); await fresh.whenStable(); fresh.detectChanges();
        expect(TestBed.inject(Title).getTitle()).toBe('Diagnostic job progress — OrganicSEOOps');
        expect(fresh.nativeElement.querySelector('section').getAttribute('lang')).toBe('en');
        expect(fresh.nativeElement.querySelector('h1').textContent).toBe('Project job progress');
        expect(fresh.nativeElement.textContent).not.toContain('private preference error');
        if (mode === 'production') {
          expect(fresh.componentInstance.productLanguage()).toBe('tr');
          expect(api.projects.mock.calls.length).toBe(reads);
          expect(fresh.nativeElement.textContent).toContain('Diagnostic jobs are unavailable here');
          expect(fresh.nativeElement.querySelector('form')).toBeNull();
        }
        for (const action of [api.createDiagnostic, api.cancelJob, api.retryJob, api.createDiagnosticSchedule]) expect(action).not.toHaveBeenCalled();
        fresh.destroy();
      }
    } finally { buildEnvironment.production = production; }
  });
});
