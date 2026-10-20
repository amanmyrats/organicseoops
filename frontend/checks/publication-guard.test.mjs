import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { assertPublishable, compilePublicAnalyticsPolicy } from './publication-guard.mjs';
import { preparePublicMetadata } from './public-metadata.mjs';
import { publicPaths, publicAnalyticsRoutes } from '../src/app/route-inventory.ts';

const origin = 'https://organicseoops.com';
const makeHtml = (path, lang) => {
  const alternate = lang === 'en' ? 'tr/' : '';
  const body = language => `<html lang="${language}"><head><title>Reviewed sample</title><meta name="description" content="Useful source-aware sample"></head><body><main><h1>Reviewed sample</h1><p>Specific reviewed content.</p><a href="/">Home</a></main></body></html>`;
  return preparePublicMetadata({ routes: [path, alternate], pages: { [path]: { alternate }, [alternate]: { alternate: path } },
    htmlByRoute: { [path]: body(lang), [alternate]: body(lang === 'en' ? 'tr' : 'en') }, origin }).htmlByRoute[path];
};
const sitemapXml = `<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${origin}/</loc></url><url><loc>${origin}/tr/</loc></url></urlset>`;
const hash = (html) => createHash('sha256').update(html).digest('hex');

test('only reviewed matching locale revisions can enter a release', () => {
  const htmlByRoute = { '': makeHtml('', 'en'), 'tr/': makeHtml('tr/', 'tr') };
  const entry = (path, alternate) => ({ state: 'approved', editor: 'founder', publisher: 'founder',
    reviewer: 'named human reviewer', reviewedAt: '2026-09-29T12:00:00Z',
    htmlSha256: hash(htmlByRoute[path]), alternate, history: [{ htmlSha256: hash(htmlByRoute[path]),
      reviewer: 'named human reviewer', reviewedAt: '2026-09-29T12:00:00Z' }] });
  const approvals = { version: 1, routes: { '': entry('', 'tr/'), 'tr/': entry('tr/', '') } };
  const args = { routes: ['', 'tr/', '404'], approvals, htmlByRoute, origin, sitemapXml };
  assert.doesNotThrow(() => assertPublishable(args));
  assert.throws(() => assertPublishable({ ...args, approvals: { ...approvals, version: 2 } }), /Unsupported publication approval version/);
  approvals.routes[''].history.unshift({ htmlSha256: 'a'.repeat(64), reviewer: 'prior human reviewer',
    reviewedAt: '2026-09-28T12:00:00Z' });
  assert.doesNotThrow(() => assertPublishable(args));
  approvals.routes[''].history.push({ htmlSha256: 'a'.repeat(64), reviewer: 'prior human reviewer',
    reviewedAt: '2026-09-28T12:00:00Z' });
  assert.throws(() => assertPublishable(args), /Approval history does not match/);
  approvals.routes[''].history.pop();
  assert.throws(() => assertPublishable({ ...args, htmlByRoute: { ...htmlByRoute, '': htmlByRoute[''] + 'changed' } }),
    /changed since review/);
  assert.throws(() => assertPublishable({ ...args, htmlByRoute: { ...htmlByRoute,
    'tr/': htmlByRoute['tr/'].replace('<head>', '<head><meta name="robots" content="noindex, nofollow">'),
  } }), /changed since review/);
  assert.throws(() => assertPublishable({ ...args, approvals: { version: 1, routes: {
    ...approvals.routes, 'tr/': { ...approvals.routes['tr/'], state: 'draft' },
  } } }), /Unapproved page/);
  assert.throws(() => assertPublishable({ ...args, routes: ['', '404'],
    approvals: { version: 1, routes: { '': approvals.routes[''] } } }), /Turkish pages/);
  for (const [path, change] of [
    ['', html => html.replace(/<link rel="alternate"[^>]+>/g, '')],
    ['tr/', html => html.replace(`hreflang="tr" href="${origin}/tr/"`, `hreflang="tr" href="${origin}/missing"`)],
    ['', html => html.replace(`hreflang="x-default" href="${origin}/"`, `hreflang="x-default" href="${origin}/tr/"`)],
    ['tr/', html => html.replace('</head>', `<link rel="alternate" hreflang="en" href="${origin}/"></head>`)],
  ]) {
    const invalid = approvedFixture();
    invalid.htmlByRoute[path] = change(invalid.htmlByRoute[path]);
    invalid.approvals.routes[path].htmlSha256 = hash(invalid.htmlByRoute[path]);
    invalid.approvals.routes[path].history[0].htmlSha256 = invalid.approvals.routes[path].htmlSha256;
    assert.throws(() => assertPublishable(invalid), /Locale alternates/);
  }
  const sameLocale = approvedFixture();
  for (const [path, lang, alternate] of [['help', 'en', ''], ['tr/help', 'tr', 'tr/']]) {
    sameLocale.routes.push(path);
    sameLocale.htmlByRoute[path] = makeHtml(path, lang);
    sameLocale.approvals.routes[path] = { ...structuredClone(sameLocale.approvals.routes[alternate]),
      alternate, htmlSha256: hash(sameLocale.htmlByRoute[path]) };
    sameLocale.approvals.routes[path].history[0].htmlSha256 = sameLocale.approvals.routes[path].htmlSha256;
    sameLocale.approvals.routes[alternate].alternate = path;
  }
  assert.throws(() => assertPublishable(sameLocale), /Missing opposite locale/);
});

test('current noindex development routes cannot be released', () => {
  const result = spawnSync(process.execPath, ['checks/publication-guard.mjs'], {
    cwd: new URL('../', import.meta.url),
    env: { ...process.env, FRONTEND_PUBLIC_ORIGIN: origin },
    encoding: 'utf8',
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Reviewed Turkish pages/);
});

function approvedFixture() {
  const htmlByRoute = { '': makeHtml('', 'en'), 'tr/': makeHtml('tr/', 'tr') };
  const entry = (path, alternate) => ({ state: 'approved', editor: 'founder', publisher: 'founder',
    reviewer: 'Synthetic named human reviewer', reviewedAt: '2026-10-03T00:00:00Z', htmlSha256: hash(htmlByRoute[path]),
    alternate, history: [{ htmlSha256: hash(htmlByRoute[path]), reviewer: 'Synthetic named human reviewer', reviewedAt: '2026-10-03T00:00:00Z' }] });
  return { routes: ['', 'tr/', '404'], approvals: { version: 1, routes: { '': entry('', 'tr/'), 'tr/': entry('tr/', '') } }, htmlByRoute, origin, sitemapXml };
}
const analyticsFixture = () => [
  { path: '', id: 'HOME', locale: 'en', ctaIds: ['public_trial_cta'] },
  { path: 'tr/', id: 'HOME', locale: 'tr', ctaIds: ['public_trial_cta'] },
];

test('approved exact HTML compiles only minimized policy and matches the actual Python artifact parser', () => {
  const args = approvedFixture();
  const policy = compilePublicAnalyticsPolicy(args, analyticsFixture());
  assert.deepEqual(policy.routes.map(row => row.path), ['', 'tr/']);
  assert.equal(policy.routes[0].html_sha256, hash(args.htmlByRoute['']));
  assert.doesNotMatch(JSON.stringify(policy), /reviewer|history|raw_html|visitor|account|customer|token/);
  assert.deepEqual(compilePublicAnalyticsPolicy(args, analyticsFixture().reverse()), policy);
  const result = spawnSync('python3', ['-c', 'import json,sys; from tenancy.public_analytics_policy import parse_public_analytics_policy; policy,digest=parse_public_analytics_policy(sys.stdin.buffer.read()); print(json.dumps({"policy":policy,"digest":digest}))'], {
    input: JSON.stringify(policy), encoding: 'utf8',
    env: { ...process.env, PYTHONPATH: fileURLToPath(new URL('../../backend/', import.meta.url)) },
  });
  assert.equal(result.status, 0, result.stderr);
  const parsed = JSON.parse(result.stdout);
  assert.deepEqual(parsed.policy, policy);
  const sorted = value => Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
  assert.equal(parsed.digest, hash(JSON.stringify(sorted(policy))));
});

test('public analytics policy rejects stale/draft HTML, private/duplicate/malformed/borrowed route metadata', () => {
  const args = approvedFixture();
  assert.throws(() => compilePublicAnalyticsPolicy({ ...args, htmlByRoute: { ...args.htmlByRoute, '': args.htmlByRoute[''] + 'changed' } }, analyticsFixture()), /changed since review/);
  const draft = approvedFixture(); draft.approvals.routes[''].state = 'draft';
  assert.throws(() => compilePublicAnalyticsPolicy(draft, analyticsFixture()), /Unapproved page/);
  for (const edit of [{ path: 'account' }, { path: 'app/7/9' }, { path: 'preview' }, { path: '404' },
    { path: '//external.example' }, { path: 'tr/account' }, { id: 'raw?token=private' }, { locale: 'de' },
    { path: 'tr/', locale: 'en' }, { ctaIds: ['raw?token=private'] }, { ctaIds: ['repeat', 'repeat'] },
    { ctaIds: ['other_trial_cta'] }, { id: 'OTHER' }, { customer: 'private' }]) {
    const inventory = analyticsFixture(); Object.assign(inventory[0], edit);
    assert.throws(() => compilePublicAnalyticsPolicy(args, inventory));
  }
  const duplicate = analyticsFixture(); duplicate.push(structuredClone(duplicate[0]));
  assert.throws(() => compilePublicAnalyticsPolicy(args, duplicate));
  assert.throws(() => compilePublicAnalyticsPolicy(args, []));
  assert.throws(() => compilePublicAnalyticsPolicy(args, analyticsFixture().slice(0, 1)));
  assert.throws(() => compilePublicAnalyticsPolicy({ ...args, approvals: { ...args.approvals, version: 2 } }, analyticsFixture()));
});

test('actual current draft build cannot produce an analytics publication policy', async () => {
  const approvals = JSON.parse(await readFile(new URL('../publication-approvals.json', import.meta.url)));
  const browser = new URL('../dist/organicseoops/browser/', import.meta.url);
  const htmlByRoute = Object.fromEntries(await Promise.all(publicPaths.filter(path => path !== '404').map(async path => [
    path, await readFile(new URL(path ? `${path}/index.html` : 'index.html', browser), 'utf8'),
  ])));
  assert.throws(() => compilePublicAnalyticsPolicy({ routes: [...publicPaths], approvals, htmlByRoute, origin }, publicAnalyticsRoutes), /Reviewed Turkish pages/);
  const result = spawnSync(process.execPath, ['checks/publication-guard.mjs', '--analytics-policy'], {
    cwd: new URL('../', import.meta.url), env: { ...process.env, FRONTEND_PUBLIC_ORIGIN: origin }, encoding: 'utf8',
  });
  assert.notEqual(result.status, 0); assert.equal(result.stdout, '');
  assert.match(result.stderr, /Reviewed Turkish pages/);
});
