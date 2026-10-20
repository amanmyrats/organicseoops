import { DOCUMENT, isPlatformBrowser } from '@angular/common';
import { DestroyRef, Injectable, PLATFORM_ID, inject, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { publicAnalyticsRoutes, publicPaths } from './route-inventory';

export const ANALYTICS_CONSENT_VERSION = 'first-party-analytics-consent-v1';
type Choice = { version: typeof ANALYTICS_CONSENT_VERSION; allowed: boolean };
export type AnalyticsRoute = { path: string; id: string; locale: 'en' | 'tr'; ctaIds: readonly string[] };
const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;

function reviewed(value: unknown): Record<string, unknown> | null {
  const row = record(value);
  const last = Array.isArray(row?.['history']) ? record(row['history'].at(-1)) : null;
  return row?.['state'] === 'approved' && row['editor'] === 'founder' && row['publisher'] === 'founder'
    && typeof row['reviewer'] === 'string' && row['reviewer'].trim().length > 0
    && typeof row['reviewedAt'] === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(row['reviewedAt'])
    && Number.isFinite(Date.parse(row['reviewedAt'])) && typeof row['htmlSha256'] === 'string'
    && /^[0-9a-f]{64}$/.test(row['htmlSha256']) && last?.['htmlSha256'] === row['htmlSha256']
    && last['reviewer'] === row['reviewer'] && last['reviewedAt'] === row['reviewedAt'] ? row : null;
}

// Pure local policy. No occurrence time, identifier, storage, queue or transport.
export function publicAnalyticsCandidate(choice: unknown, input: unknown,
    inventory: readonly AnalyticsRoute[], manifest: unknown): Record<string, string> | null {
  const consent = record(choice), event = record(input), root = record(manifest);
  if (!consent || Object.keys(consent).length !== 2 || consent['version'] !== ANALYTICS_CONSENT_VERSION
      || consent['allowed'] !== true || !event || root?.['version'] !== 1) return null;
  const isCta = event['event_id'] === 'public_cta_selected';
  const keys = isCta ? ['event_id', 'route_id', 'locale', 'cta_id'] : ['event_id', 'route_id', 'locale'];
  if ((!isCta && event['event_id'] !== 'public_page_view') || Object.keys(event).length !== keys.length
      || !Object.keys(event).every(key => keys.includes(key))) return null;
  const route = inventory.find(row => row.id === event['route_id'] && row.locale === event['locale']);
  if (!route || /^(?:tr\/)?(?:account|app|preview|404)(?:\/|$)/.test(route.path)
      || route.path === 'tr' || (route.path !== '' && route.path !== 'tr/' && !/^[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(route.path))
      || (route.locale === 'tr') !== route.path.startsWith('tr/')) return null;
  const entries = record(root['routes']);
  const approval = reviewed(entries?.[route.path]);
  const alternate = inventory.find(row => row.path === approval?.['alternate'] && row.id === route.id && row.locale !== route.locale);
  const other = reviewed(alternate && entries?.[alternate.path]);
  if (!approval || !alternate || other?.['alternate'] !== route.path
      || (isCta && (typeof event['cta_id'] !== 'string' || !route.ctaIds.includes(event['cta_id'])))) return null;
  return { dictionary_version: 'acquisition-v1', event_id: String(event['event_id']), route_id: route.id,
    locale: route.locale, consent_version: ANALYTICS_CONSENT_VERSION, consent_state: 'granted',
    ...(isCta ? { cta_id: String(event['cta_id']) } : {}) };
}

@Injectable({ providedIn: 'root' })
export class AnalyticsConsent {
  private readonly browser = isPlatformBrowser(inject(PLATFORM_ID));
  private readonly document = inject(DOCUMENT);
  private readonly router = inject(Router, { optional: true });
  private readonly choice = signal<Choice | null>(null);
  readonly preference = this.choice.asReadonly();
  readonly status = signal('No choice — optional analytics is off.');
  private generation = 0;
  private destroyed = false;
  private epoch: { proof: string; deadline: number; csrf: string } | null = null;
  private expiryTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly attempted = new Set<string>();

  constructor() {
    const window = this.browser ? this.document.defaultView : null;
    const clear = () => this.reset();
    window?.addEventListener('pagehide', clear);
    const navigation = this.router?.events.subscribe(event => {
      if (event instanceof NavigationEnd && this.choice()?.allowed) {
        if (!this.currentCandidate('public_page_view')) this.reset();
        else if (this.epoch) void this.observe('public_page_view');
      }
    });
    inject(DestroyRef).onDestroy(() => {
      this.destroyed = true; navigation?.unsubscribe(); window?.removeEventListener('pagehide', clear); this.reset();
    });
  }

  choose(allowed: unknown) {
    this.reset();
    if (!this.browser || this.destroyed || typeof allowed !== 'boolean') return;
    this.generation++; // A previous epoch's late withdrawal cannot overwrite this new choice.
    this.choice.set({ version: ANALYTICS_CONSENT_VERSION, allowed });
    if (!allowed) { this.status.set('Rejected — optional analytics is off.'); return; }
    if (!this.currentCandidate('public_page_view')) {
      this.status.set('Allowed for this open page only — no analytics collected in this preview.'); return;
    }
    void this.grant(this.generation);
  }
  reset() {
    const epoch = this.epoch;
    const generation = ++this.generation;
    this.epoch = null; this.choice.set(null); this.attempted.clear();
    clearTimeout(this.expiryTimer);
    this.status.set('No choice — optional analytics is off.');
    if (epoch) void this.withdraw(epoch).then(confirmed => {
      if (!confirmed && generation === this.generation && !this.destroyed)
        this.status.set('Analytics is off. Withdrawal could not be confirmed; original expiry and cleanup still apply.');
    });
  }
  candidate(input: unknown) {
    if (!this.browser) return null;
    try {
      const approvals = JSON.parse(this.document.querySelector('#public-page-runtime')?.getAttribute('data-approvals') ?? 'null');
      return publicAnalyticsCandidate(this.choice(), input,
        publicAnalyticsRoutes.filter(route => (publicPaths as readonly string[]).includes(route.path)), approvals);
    } catch { return null; }
  }

  private currentCandidate(event: 'public_page_view' | 'public_cta_selected', cta?: string) {
    const url = (this.router?.url ?? this.document.location?.pathname ?? '').split(/[?#]/, 1)[0];
    const route = publicAnalyticsRoutes.find(row => url === '/' + row.path
      || row.path !== '' && url === '/' + row.path + '/');
    return route ? this.candidate({ event_id: event, route_id: route.id, locale: route.locale,
      ...(event === 'public_cta_selected' ? { cta_id: cta } : {}) }) : null;
  }

  private async request(action: 'csrf' | 'grant' | 'receipt' | 'withdraw', body?: unknown, csrf?: string) {
    const response = await fetch(`/api/public-analytics/${action}/`, {
      method: action === 'csrf' ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      referrerPolicy: 'no-referrer', signal: AbortSignal.timeout(10_000), keepalive: action === 'withdraw',
      ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf ?? '' },
        body: JSON.stringify(body) }),
    });
    if (!response.ok) throw new Error();
    return record(await response.json());
  }

  private async withdraw(epoch: { proof: string; csrf: string }) {
    try {
      const result = await this.request('withdraw', { receipt_proof: epoch.proof }, epoch.csrf);
      return result?.['method'] === 'public-consent-epoch-v1' && result['state'] === 'withdrawn'
        && Object.keys(result).length === 2;
    } catch { return false; }
  }

  private async grant(generation: number) {
    const started = Date.now();
    this.status.set('Requesting an optional fifteen-minute consent epoch.');
    let csrf = '', proof = '';
    try {
      const token = await this.request('csrf');
      if (!token || Object.keys(token).length !== 1 || typeof token['csrfToken'] !== 'string'
          || !/^[A-Za-z0-9]{64}$/.test(token['csrfToken'])) throw new Error();
      csrf = token['csrfToken'];
      if (generation !== this.generation || this.destroyed || !this.currentCandidate('public_page_view')) return;
      const issued = await this.request('grant', { allowed: true, consent_version: ANALYTICS_CONSENT_VERSION }, csrf);
      if (typeof issued?.['receipt_proof'] === 'string' && /^[A-Za-z0-9_-]{43}$/.test(issued['receipt_proof']))
        proof = issued['receipt_proof'];
      const expiry = typeof issued?.['expires_at'] === 'string' && /^\d{4}-\d{2}-\d{2}T.*(?:Z|\+00:00)$/.test(issued['expires_at'])
        ? Date.parse(issued['expires_at']) : NaN;
      const deadline = Math.min(expiry, started + 15 * 60_000);
      if (!issued || Object.keys(issued).length !== 5 || issued['method'] !== 'public-consent-epoch-v1'
          || issued['consent_version'] !== ANALYTICS_CONSENT_VERSION || !proof || !Number.isFinite(deadline)
          || deadline <= Date.now() || typeof issued['policy_digest'] !== 'string'
          || !/^[0-9a-f]{64}$/.test(issued['policy_digest'])) throw new Error();
      if (generation !== this.generation || this.destroyed || !this.currentCandidate('public_page_view')) {
        await this.withdraw({ proof, csrf }); return;
      }
      this.epoch = { proof, csrf, deadline };
      this.expiryTimer = setTimeout(() => {
        this.reset(); this.status.set('Original consent epoch expired — allow again explicitly to start a new one.');
      }, deadline - Date.now());
      this.status.set('Optional analytics enabled for this original fifteen-minute epoch.');
      void this.observe('public_page_view');
    } catch {
      if (proof) await this.withdraw({ proof, csrf });
      if (generation === this.generation && !this.destroyed)
        this.status.set('Consent epoch unavailable or unconfirmed — no automatic retry or renewal. Analytics is off.');
    }
  }

  async observe(event: 'public_page_view' | 'public_cta_selected', cta?: string) {
    const epoch = this.epoch, generation = this.generation;
    if (!epoch || this.choice()?.allowed !== true || this.destroyed) return;
    if (Date.now() >= epoch.deadline) { this.reset(); this.status.set('Original consent epoch expired — analytics is off.'); return; }
    const candidate = this.currentCandidate(event, cta);
    if (!candidate) return;
    const key = JSON.stringify(candidate);
    if (this.attempted.has(key)) return;
    this.attempted.add(key); // An uncertain receipt is never automatically replayed.
    try {
      const receipt = await this.request('receipt', { receipt_proof: epoch.proof, candidate }, epoch.csrf);
      if (generation !== this.generation || this.destroyed) return;
      const keys = ['method', 'state', 'event_id', 'route_id', 'locale', 'occurred_at', ...(cta ? ['cta_id'] : [])];
      if (!receipt || Object.keys(receipt).length !== keys.length || !Object.keys(receipt).every(key => keys.includes(key))
          || receipt['method'] !== 'public-observation-receipt-v1' || receipt['state'] !== 'recorded'
          || ['event_id', 'route_id', 'locale', ...(cta ? ['cta_id'] : [])].some(key => receipt[key] !== candidate[key])
          || typeof receipt['occurred_at'] !== 'string' || !Number.isFinite(Date.parse(receipt['occurred_at']))) throw new Error();
    } catch {
      if (generation === this.generation && !this.destroyed)
        this.status.set('Observation unavailable or unconfirmed — it will not be replayed automatically.');
    }
  }
}
