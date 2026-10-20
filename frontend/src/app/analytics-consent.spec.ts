import { Component, PLATFORM_ID } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { vi } from 'vitest';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { App } from './app';
import { ANALYTICS_CONSENT_VERSION, AnalyticsConsent, AnalyticsRoute, publicAnalyticsCandidate } from './analytics-consent';
import { AnalyticsPreferences } from './analytics-preferences';
import { routes } from './app.routes';
import { AccountApi } from './account/account-api';

@Component({ template: '<h1>Synthetic metadata fixture</h1><p>Fixture content only.</p><a href="/">Home</a>' })
class PublicMetadataFixture {}

const granted = { version: ANALYTICS_CONSENT_VERSION, allowed: true };
const page = { event_id: 'public_page_view', route_id: 'HOME', locale: 'en' };
const inventory: AnalyticsRoute[] = [
  { path: '', id: 'HOME', locale: 'en', ctaIds: ['public_trial_cta'] },
  { path: 'tr/', id: 'HOME', locale: 'tr', ctaIds: ['public_trial_cta'] },
];
function manifest() {
  const approval = { state: 'approved', editor: 'founder', publisher: 'founder', reviewer: 'Synthetic bilingual reviewer',
    reviewedAt: '2026-10-03T00:00:00Z', htmlSha256: 'a'.repeat(64),
    history: [{ reviewer: 'Synthetic bilingual reviewer', reviewedAt: '2026-10-03T00:00:00Z', htmlSha256: 'a'.repeat(64) }] };
  return { version: 1, routes: { '': { ...structuredClone(approval), alternate: 'tr/' }, 'tr/': { ...structuredClone(approval), alternate: '' } } };
}

describe('First-party optional analytics consent boundary', () => {
  afterEach(() => vi.restoreAllMocks());

  it('requires a real explicit versioned opt-in, rejecting malformed and implicit operational consent', () => {
    for (const choice of [null, false, true, [], {}, { ...granted, allowed: false }, { ...granted, allowed: 'true' },
      { ...granted, allowed: 1 }, { ...granted, version: 'old' }, { ...granted, actor_id: 1 },
      { usefulness_acknowledged: true }, { checkout_acknowledged: true }]) {
      expect(publicAnalyticsCandidate(choice, page, inventory, manifest())).toBeNull();
    }
    expect(publicAnalyticsCandidate(granted, page, inventory, manifest())).toEqual({
      dictionary_version: 'acquisition-v1', ...page, consent_version: ANALYTICS_CONSENT_VERSION, consent_state: 'granted',
    });
  });

  it('only accepts matching canonically reviewed routes/history and reciprocal reviewed locale pairs', () => {
    for (const edit of [{ state: 'draft' }, { editor: 'other' }, { publisher: 'other' }, { reviewer: '' },
      { reviewedAt: 'invalid' }, { htmlSha256: 'invalid' }, { history: [] }, { alternate: 'unknown' }]) {
      const approvals = manifest(); Object.assign(approvals.routes[''], edit);
      expect(publicAnalyticsCandidate(granted, page, inventory, approvals)).toBeNull();
    }
    const changed = manifest(); changed.routes[''].history[0].htmlSha256 = 'b'.repeat(64);
    expect(publicAnalyticsCandidate(granted, page, inventory, changed)).toBeNull();
    const unreviewed = manifest(); unreviewed.routes['tr/'].state = 'draft';
    expect(publicAnalyticsCandidate(granted, page, inventory, unreviewed)).toBeNull();
    const nonreciprocal = manifest(); nonreciprocal.routes['tr/'].alternate = 'sample-report';
    expect(publicAnalyticsCandidate(granted, page, inventory, nonreciprocal)).toBeNull();
    for (const malformed of [null, {}, [], { ...manifest(), version: 2 }, { version: 1, routes: [] }]) {
      expect(publicAnalyticsCandidate(granted, page, inventory, malformed)).toBeNull();
    }
    expect(publicAnalyticsCandidate(granted, { ...page, locale: 'tr' }, inventory, manifest())?.['locale']).toBe('tr');
  });

  it('denies private/preview/not-found/unknown routes, wrong locales/events and route-borrowed CTAs', () => {
    for (const input of [null, [], {}, { ...page, event_id: 'paid_activation_confirmed' }, { ...page, route_id: 'UNKNOWN' },
      { ...page, locale: 'de' }, { ...page, route_id: '/account/reset#secret' }, { ...page, cta_id: 'public_trial_cta' },
      { ...page, event_id: 'public_cta_selected' }, { ...page, event_id: 'public_cta_selected', cta_id: 'other_trial_cta' }]) {
      expect(publicAnalyticsCandidate(granted, input, inventory, manifest())).toBeNull();
    }
    for (const path of ['account', 'account/reset', 'app/7/9', 'preview', '404', 'tr/account', 'tr/app/7/9',
      'tr/preview', 'tr/404', '//other.example', '?token=secret']) {
      const rows = [{ ...inventory[0], path }, inventory[1]];
      expect(publicAnalyticsCandidate(granted, page, rows, manifest())).toBeNull();
    }
    const cta = { ...page, event_id: 'public_cta_selected', cta_id: 'public_trial_cta' };
    expect(publicAnalyticsCandidate(granted, cta, inventory, manifest())?.['cta_id']).toBe('public_trial_cta');
    expect(publicAnalyticsCandidate(granted, cta, [{ ...inventory[0], ctaIds: [] }, inventory[1]], manifest())).toBeNull();
  });

  it('rejects extra URL/token/customer/linkage/time properties without copying input or review identity', () => {
    for (const key of ['url', 'referrer', 'query', 'campaign', 'email', 'organization_id', 'project_id', 'property_id',
      'actor_id', 'visitor_id', 'occurred_at', 'password', 'receipt_proof', 'customer_export', '__proto__']) {
      const input = JSON.parse(JSON.stringify(page).slice(0, -1) + `,"${key}":"private-secret-customer-value"}`);
      expect(publicAnalyticsCandidate(granted, input, inventory, manifest())).toBeNull();
    }
    const input = { ...page }; const candidate = publicAnalyticsCandidate(granted, input, inventory, manifest())!;
    input.route_id = 'PRIVATE'; expect(candidate['route_id']).toBe('HOME');
    expect(JSON.stringify(candidate)).not.toMatch(/reviewer|htmlSha256|history|timestamp|linkage|visitor/);
  });

  it('actual native page/CTA candidates match the pure pinned-policy Python source without browser consent authority', () => {
    const publication = manifest();
    const policy = { version: 'public-analytics-policy-v1', origin: 'https://product.example.invalid',
      routes: inventory.map(route => ({ path: route.path, id: route.id, locale: route.locale,
        cta_ids: [...route.ctaIds], html_sha256: publication.routes[route.path as '' | 'tr/'].htmlSha256 })) };
    for (const input of [page, { ...page, event_id: 'public_cta_selected', cta_id: 'public_trial_cta' }]) {
      const candidate = publicAnalyticsCandidate(granted, input, inventory, publication)!;
      expect(candidate).not.toBeNull();
      const result = spawnSync('python3', ['-c',
        'import json,sys; from tenancy.public_analytics_policy import parse_public_analytics_policy; from tenancy.public_analytics_source import public_observation_source; data=json.load(sys.stdin); content=json.dumps(data["policy"]).encode(); digest=parse_public_analytics_policy(content)[1]; source=public_observation_source(data["candidate"],policy_content=content,expected_policy_digest=digest,current_choice=True); print(json.dumps(source))'],
        { input: JSON.stringify({ policy, candidate }), encoding: 'utf8', env: { ...process.env, PYTHONPATH: resolve(process.cwd(), '../backend') } });
      expect(result.status, result.stderr).toBe(0);
      const source = JSON.parse(result.stdout);
      expect(source.method).toBe('public-observation-source-v1');
      expect(source.event_id).toBe(input.event_id); expect(source.route_id).toBe('HOME');
      expect(source.html_sha256).toBe('a'.repeat(64));
      expect(JSON.stringify(source)).not.toMatch(/origin|path|occurred_at|visitor|customer|reviewer/);
    }
  });

  it('native footer follows explicit public locales with equal reject/allow/reset and no anonymous preference, storage or network', async () => {
    const seedMetadata = () => document.head.insertAdjacentHTML('beforeend',
      '<link rel="canonical" href="https://product.example.invalid/old"><link rel="alternate" hreflang="tr" href="https://product.example.invalid/tr/old">'
      + '<meta property="og:url" content="https://product.example.invalid/old"><meta name="twitter:title" content="Old page">'
      + '<script id="public-page-schema" type="application/ld+json">{"@type":"WebPage","url":"https://product.example.invalid/old"}</script>'
      + '<meta name="robots" content="index, follow">');
    const expectDraftMetadata = () => {
      expect(document.head.querySelector('link[rel="canonical"], link[hreflang], meta[property^="og:"], meta[name^="twitter:"], #public-page-schema')).toBeNull();
      expect([...document.head.querySelectorAll<HTMLMetaElement>('meta[name="robots"]')].map(tag => tag.content)).toEqual(['noindex, nofollow']);
    };
    seedMetadata();
    const storage = vi.spyOn(Storage.prototype, 'setItem'); const readStorage = vi.spyOn(Storage.prototype, 'getItem');
    const fetch = vi.spyOn(window, 'fetch');
    const preference = vi.spyOn(AccountApi.prototype, 'productLanguage').mockResolvedValue({ status: 200,
      body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } });
    TestBed.configureTestingModule({ providers: [provideRouter(routes)] });
    const fixture = TestBed.createComponent(App); fixture.detectChanges();
    expectDraftMetadata();
    const router = TestBed.inject(Router);
    await router.navigateByUrl('/'); fixture.detectChanges();
    const consent = TestBed.inject(AnalyticsConsent);
    const root: HTMLElement = fixture.nativeElement;
    expect(root.querySelector('footer summary')?.textContent).toBe('Analytics preferences');
    expect(root.querySelector('footer [role="status"]')?.textContent).toContain('No choice');
    const buttons = root.querySelectorAll<HTMLButtonElement>('footer button');
    expect(buttons.length).toBe(3); expect([...buttons].every(button => !button.disabled)).toBe(true);
    buttons[0].click(); fixture.detectChanges(); expect(consent.preference()?.allowed).toBe(false);
    buttons[1].click(); fixture.detectChanges(); expect(consent.preference()).toEqual(granted);
    expect(root.textContent).toContain('no analytics collected in this preview');
    // Actual canonical approvals are draft: opt-in cannot promote either real route.
    expect(consent.candidate(page)).toBeNull();
    expect(consent.candidate({ ...page, route_id: 'SAMPLE' })).toBeNull();
    const untrusted = document.createElement('template'); untrusted.id = 'public-page-runtime';
    document.head.append(untrusted);
    for (const value of ['not JSON', '{}', '[]', 'null', JSON.stringify(manifest())]) {
      untrusted.setAttribute('data-approvals', value);
      expect(consent.candidate(page)).toBeNull(); // Current registry has no approved opposite-locale route.
    }
    untrusted.remove();
    buttons[2].click(); fixture.detectChanges(); expect(consent.preference()).toBeNull();
    consent.choose('true'); expect(consent.preference()).toBeNull();
    const details = root.querySelector<HTMLDetailsElement>('footer details')!;
    details.open = true;
    buttons[0].focus();
    for (const path of ['/preview/tr', '/preview/tr/home', '/preview/tr/sample-report', '/preview/tr/404', '/preview/tr/help', '/preview/tr/data-sources', '/preview/tr/technical-seo-audits']) {
      seedMetadata();
      await router.navigateByUrl(path + '?language=en#draft'); fixture.detectChanges();
      expectDraftMetadata();
      expect(document.documentElement.lang).toBe('tr');
      expect(document.title).toContain('OrganicSEOOps');
      expect(document.head.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toBeTruthy();
      for (const selector of ['header', 'footer', '.skip-link', 'footer details'])
        expect(root.querySelector(selector)?.getAttribute('lang')).toBe('tr');
      expect(root.querySelector('.skip-link')?.textContent).toBe('İçeriğe geç');
      expect(root.querySelector('header a')?.getAttribute('href')).toBe('/preview/tr/home');
      expect(root.querySelector('header a')?.getAttribute('aria-label')).toBe('OrganicSEOOps ana sayfa');
      expect(root.querySelector('footer summary')?.textContent).toBe('Analitik tercihleri');
      expect(root.querySelector('footer [role="status"]')?.textContent).toContain('Tercih yok');
      expect(root.querySelector('footer details')).toBe(details); expect(details.open).toBe(true);
      expect(root.querySelector('footer button')).toBe(buttons[0]); expect(document.activeElement).toBe(buttons[0]);
    }
    expect(preference).not.toHaveBeenCalled();
    expect([...buttons].map(button => button.textContent)).toEqual([
      'İsteğe bağlı analitiği reddet', 'İsteğe bağlı analitiğe izin ver', 'Tercihi sıfırla']);
    buttons[0].click(); fixture.detectChanges();
    const rejected = consent.preference(); expect(rejected?.allowed).toBe(false);
    expect(root.querySelector('footer [role="status"]')?.textContent).toContain('Reddedildi');
    await router.navigateByUrl('/preview'); fixture.detectChanges();
    expect(consent.preference()).toBe(rejected);
    expect(root.querySelector('footer [role="status"]')?.textContent).toContain('Rejected');
    await router.navigateByUrl('/preview/tr'); fixture.detectChanges();
    buttons[1].click(); fixture.detectChanges(); expect(consent.preference()).toEqual(granted);
    expect(root.querySelector('footer [role="status"]')?.textContent).toContain('bu ön izlemede analitik toplanmaz');
    buttons[2].click(); fixture.detectChanges(); expect(consent.preference()).toBeNull();
    for (const path of ['/', '/sample-report', '/404', '/preview/tr/missing', '/account/missing', '/app/missing']) {
      seedMetadata();
      await router.navigateByUrl(path + '?language=tr'); fixture.detectChanges();
      expectDraftMetadata();
      expect(document.documentElement.lang).toBe('en');
      for (const selector of ['header', 'footer', '.skip-link', 'footer details'])
        expect(root.querySelector(selector)?.getAttribute('lang')).toBe('en');
      expect(root.querySelector('header a')?.getAttribute('href')).toBe('/');
      expect(root.querySelector('footer summary')?.textContent).toBe('Analytics preferences');
    }
    expect(preference).not.toHaveBeenCalled();
    seedMetadata();
    await router.navigateByUrl('/account/login'); fixture.detectChanges(); await fixture.whenStable();
    expectDraftMetadata();
    expect(preference).toHaveBeenCalledOnce();
    expect(root.querySelector('header')?.getAttribute('lang')).toBe('en');
    expect(root.querySelector('footer details')?.getAttribute('lang')).toBe('en');
    expect(storage).not.toHaveBeenCalled(); expect(readStorage).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  });

  it('keeps compiler-reviewed initial head metadata through public locale navigation and restores it after private routes', async () => {
    const pairs = { '': { alternate: 'tr/' }, 'tr/': { alternate: '' }, 'guides/help': { alternate: 'tr/rehber/yardim' }, 'tr/rehber/yardim': { alternate: 'guides/help' } };
    const source = Object.fromEntries(Object.keys(pairs).map(path => [path,
      `<!doctype html><html lang="${path.startsWith('tr/') ? 'tr' : 'en'}"><head><title>Synthetic ${path.startsWith('tr/') ? 'TR' : 'EN'}</title><meta name="description" content="Synthetic ${path.startsWith('tr/') ? 'Turkish' : 'English'} description"></head><body><main><h1>Synthetic metadata fixture</h1><p>Fixture content only.</p><a href="/">Home</a></main></body></html>`]));
    const build = spawnSync(process.execPath, ['--input-type=module', '-e',
      `import { preparePublicMetadata } from './checks/public-metadata.mjs';
       process.stdout.write(preparePublicMetadata(${JSON.stringify({ routes: Object.keys(pairs), pages: pairs, htmlByRoute: source, origin: 'https://synthetic.example.invalid' })}).htmlByRoute['']);`],
      { cwd: resolve('.'), encoding: 'utf8' });
    expect(build.status).toBe(0);
    const parsed = new DOMParser().parseFromString(build.stdout, 'text/html');
    const runtime = document.importNode(parsed.querySelector('#public-page-runtime')!, true);
    document.head.append(runtime);
    const expectPublic = (path: string, language: string) => {
      expect(document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')?.href).toBe('https://synthetic.example.invalid/' + path);
      expect(document.head.querySelectorAll('link[rel="canonical"]').length).toBe(1);
      expect(document.head.querySelectorAll('link[hreflang]').length).toBe(3);
      expect(document.head.querySelector('meta[name="robots"]')).toBeNull();
      expect(document.documentElement.lang).toBe(language);
      expect(document.title).toBe('Synthetic ' + (language === 'en' ? 'EN' : 'TR'));
      expect(document.head.querySelector<HTMLMetaElement>('meta[name="description"]')?.content).toBe('Synthetic ' + (language === 'en' ? 'English' : 'Turkish') + ' description');
      expect(document.head.querySelector<HTMLMetaElement>('meta[property="og:url"]')?.content).toBe('https://synthetic.example.invalid/' + path);
      expect(JSON.parse(document.head.querySelector('#public-page-schema')!.textContent!).inLanguage).toBe(language);
    };
    const providers = [provideRouter([
        { path: 'account', children: [{ path: 'fixture', component: PublicMetadataFixture, title: 'Private fixture' }] },
        { path: '', children: [
          { path: '', pathMatch: 'full', component: PublicMetadataFixture, title: 'Synthetic EN' },
          { path: 'tr', children: [
            { path: '', pathMatch: 'full', component: PublicMetadataFixture, title: 'Synthetic TR', data: { language: 'tr' } },
            { path: 'rehber', children: [{ path: 'yardim', component: PublicMetadataFixture, title: 'Synthetic TR', data: { language: 'tr' } }] },
          ] },
          { path: 'guides', children: [{ path: 'help', component: PublicMetadataFixture, title: 'Synthetic EN' }] },
          { path: '**', component: PublicMetadataFixture, title: 'Unknown fixture' },
        ] },
      ])];
    const initialUrl = window.location.href;
    try {
      TestBed.configureTestingModule({ providers });
      const fixture = TestBed.createComponent(App); fixture.detectChanges();
      expectPublic('', 'en'); // Startup before Angular has activated any route.
      const router = TestBed.inject(Router);
      for (const [path, language] of [['', 'en'], ['tr', 'tr'], ['guides/help', 'en'], ['tr/rehber/yardim', 'tr'], ['', 'en']]) {
        await router.navigateByUrl('/' + path + '?source=fixture#heading'); fixture.detectChanges();
        expectPublic(path === 'tr' ? 'tr/' : path, language);
      }
      for (const path of ['/account/fixture', '/unknown']) {
        await router.navigateByUrl(path); fixture.detectChanges();
        expect(document.head.querySelector('link[rel="canonical"], link[hreflang], meta[property^="og:"], meta[name^="twitter:"], #public-page-schema')).toBeNull();
        expect(document.head.querySelector<HTMLMetaElement>('meta[name="robots"]')?.content).toBe('noindex, nofollow');
      }
      await router.navigateByUrl('/'); fixture.detectChanges(); expectPublic('', 'en');
      for (const path of ['/tr', '/tr/', '/account/fixture', '/unknown']) {
        TestBed.resetTestingModule();
        window.history.replaceState(null, '', path);
        TestBed.configureTestingModule({ providers });
        const startup = TestBed.createComponent(App); startup.detectChanges();
        if (path.startsWith('/tr')) expectPublic('tr/', 'tr');
        else {
          expect(document.head.querySelector('link[rel="canonical"], link[hreflang], #public-page-schema')).toBeNull();
          expect(document.head.querySelector<HTMLMetaElement>('meta[name="robots"]')?.content).toBe('noindex, nofollow');
        }
      }
    } finally {
      window.history.replaceState(null, '', initialUrl);
      runtime.remove();
      document.head.querySelectorAll('link[rel="canonical"], link[hreflang], meta[property^="og:"], meta[name^="twitter:"], #public-page-schema').forEach(tag => tag.remove());
    }
  });

  it('page exit/destruction/recreated documents clear choice and SSR cannot opt in or produce candidates', () => {
    const fixture = TestBed.createComponent(AnalyticsPreferences); fixture.detectChanges();
    const consent = TestBed.inject(AnalyticsConsent); consent.choose(true);
    window.dispatchEvent(new Event('pagehide')); expect(consent.preference()).toBeNull();
    consent.choose(true); TestBed.resetTestingModule(); expect(consent.preference()).toBeNull();
    expect(TestBed.inject(AnalyticsConsent).preference()).toBeNull();
    TestBed.resetTestingModule(); TestBed.configureTestingModule({ providers: [{ provide: PLATFORM_ID, useValue: 'server' }] });
    const server = TestBed.inject(AnalyticsConsent); server.choose(true);
    expect(server.preference()).toBeNull(); expect(server.candidate(page)).toBeNull();
  });
});
