import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { AIText } from './ai-text';

const history = { id: 77, status: 'running', updated_at: '2026-01-01T00:00:00Z', model_id: 3,
  request_status: 'unknown', attempted_units: 1, estimated_cost_usd: null, reported_cost_usd: null };
const usage = { provider_id: 5, model_id: 3, operation_version: 'ai-text-v2', request_status: 'unknown',
  error_category: '', input_tokens: null, output_tokens: null, duration_ms: null, estimated_cost_usd: null,
  reported_cost_usd: null, provider_request_id: '', provider_response_id: '', web_search_used: false, tool_call_count: 0 };
const job = { id: 77, project_id: 9, status: 'running', error_category: '', text: '', attempted_units: 1,
  cancel_requested: false, updated_at: history.updated_at, estimated_max_cost_usd: null, routing_source: 'explicit', fallback_index: 0, usage };

async function screen() {
  const api = {
    projects: vi.fn(async () => ({ status: 200, body: { projects: [{ id: 9, organization_id: 7, name: 'Synthetic project', role: 'member' }] } })),
    projectAITextCatalog: vi.fn(async () => ({ status: 200, body: { models: [], accounts: [], cost_status: 'unknown' } })),
    projectAIRouting: vi.fn(async () => ({ status: 200, body: { policy: null, effective: null } })),
    aiTextHistory: vi.fn(async (): Promise<ApiResult> => ({ status: 200, body: { jobs: [history], has_more: false } })),
    aiTextJob: vi.fn(), createAIText: vi.fn(), cancelAIText: vi.fn(),
  };
  TestBed.configureTestingModule({ providers: [provideRouter([]), { provide: AccountApi, useValue: api },
    { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ organizationId: '7', projectId: '9' })) } }] });
  const fixture = TestBed.createComponent(AIText); fixture.detectChanges();
  await vi.waitFor(() => expect(fixture.componentInstance.loading()).toBe(false));
  await fixture.componentInstance.loadHistory(); fixture.detectChanges();
  return { api, fixture, component: fixture.componentInstance };
}

describe('Exact native AI job and provider-request states', () => {
  it('rejects job, routing and provider-request enum arrays before publishing detail and preserves valid scalar controls', async () => {
    const { api, fixture, component } = await screen();
    const entry = component.history()[0];
    const invalid = [
      ...['queued', 'running', 'succeeded', 'failed', 'cancelled'].map(status => ({ ...job, status: [status] })),
      ...['explicit', 'project', 'system'].map(source => ({ ...job, routing_source: [source] })),
      ...['attempted', 'completed', 'failed', 'unknown'].map(state => ({ ...job, usage: { ...usage, request_status: [state] } })),
    ];
    for (const value of invalid) {
      api.aiTextJob.mockResolvedValue({ status: 200, body: { job: value } });
      await component.openHistory(entry); fixture.detectChanges();
      expect(component.job(), JSON.stringify(value)).toBeNull();
      expect(fixture.nativeElement.querySelector('#ai-job-title')).toBeNull();
      expect(component.error()).toContain('Job detail is unavailable');
    }
    for (const status of ['queued', 'running', 'succeeded', 'failed', 'cancelled']) {
      api.aiTextJob.mockResolvedValue({ status: 200, body: { job: { ...job, status } } });
      await component.openHistory(entry); fixture.detectChanges(); expect(component.job()?.status).toBe(status);
      expect(Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
        .some(button => button.textContent?.includes('Request cancellation'))).toBe(['queued', 'running'].includes(status));
      expect(fixture.nativeElement.textContent).toContain('Provider-reported charge: unknown');
    }
    expect(api.createAIText).not.toHaveBeenCalled(); expect(api.cancelAIText).not.toHaveBeenCalled();
  });

  it('rejects malformed history status arrays and retains valid scalar unknown usage without claiming a charge', async () => {
    const { api, fixture, component } = await screen();
    for (const change of [
      ...['queued', 'running', 'succeeded', 'failed', 'cancelled'].map(status => ({ status: [status] })),
      ...['not_attempted', 'attempted', 'completed', 'failed', 'unknown'].map(state => ({ request_status: [state] })),
    ]) {
      api.aiTextHistory.mockResolvedValue({ status: 200, body: { jobs: [{ ...history, ...change }], has_more: false } });
      await component.loadHistory(); fixture.detectChanges();
      expect(component.history(), JSON.stringify(change)).toEqual([]); expect(component.historyFailed()).toBe(true);
    }
    api.aiTextHistory.mockResolvedValue({ status: 200, body: { jobs: [history], has_more: false } });
    await component.loadHistory(); fixture.detectChanges(); expect(component.historyFailed()).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('provider request unknown');
    expect(fixture.nativeElement.textContent).toContain('provider-reported charge unknown');
    expect(api.aiTextJob).not.toHaveBeenCalled(); expect(api.createAIText).not.toHaveBeenCalled(); expect(api.cancelAIText).not.toHaveBeenCalled();
  });
});
