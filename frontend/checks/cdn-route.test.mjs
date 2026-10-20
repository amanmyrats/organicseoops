import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { prepareStaticRouteStack } from './cdn-inventory.mjs';
import { publicPaths, clientPrefixes } from '../src/app/route-inventory.ts';

const template = JSON.parse(await readFile(new URL('../../deploy/frontend-origin-stack.json', import.meta.url)));
const distribution = template.Resources.FrontendDistribution.Properties.DistributionConfig;
const source = template.Resources.StaticRouteFunction.Properties.FunctionCode['Fn::Sub']
  .replaceAll('${FrontendAlias}', 'organicseoops.com');
const route = (uri, host = 'organicseoops.com', querystring = {}) =>
  runInNewContext(`${source}\nhandler({request: ${JSON.stringify({
    uri, headers: { host: { value: host } }, querystring,
  })}})`);

test('noncanonical static hosts use real safe HTTP redirects with acquisition query', () => {
  assert.equal(template.Parameters.FrontendAlias.AllowedPattern, '^[a-z0-9][a-z0-9.-]*[a-z0-9]$');
  const response = route('/preview', 'd111111abcdef8.cloudfront.net', {
    utm_source: { value: 'email' }, campaign: { value: 'one', multiValue: [{ value: 'one' }, { value: 'two' }] },
  });
  assert.equal(response.statusCode, 308);
  assert.equal(response.headers.location.value,
    'https://organicseoops.com/preview?utm_source=email&campaign=one&campaign=two');
  assert.equal(route('/app/overview', 'other.example').headers.location.value,
    'https://organicseoops.com/app/overview');
});

test('only known public HTML routes resolve to prerendered files', () => {
  assert.deepEqual(publicPaths, ['', 'preview', 'preview/tr', 'sample-report', 'preview/tr/sample-report', 'preview/tr/home', 'preview/tr/404', '404', 'preview/help', 'preview/tr/help', 'preview/data-sources', 'preview/tr/data-sources', 'preview/technical-seo-audits', 'preview/tr/technical-seo-audits', 'preview/seo-agencies', 'preview/tr/seo-agencies', 'preview/airport-transfer-seo', 'preview/tr/airport-transfer-seo', 'preview/seo-opportunities', 'preview/tr/seo-opportunities', 'preview/content-and-keywords', 'preview/tr/content-and-keywords', 'preview/pricing', 'preview/tr/pricing', 'preview/contact', 'preview/tr/contact', 'preview/accessibility', 'preview/tr/accessibility', 'preview/data-handling', 'preview/tr/data-handling', 'preview/cancellation', 'preview/tr/cancellation', 'preview/privacy', 'preview/tr/privacy', 'preview/terms', 'preview/tr/terms']);
  for (const path of publicPaths) {
    const uri = path ? `/${path}` : '/';
    assert.equal(route(uri).uri, path ? `/${path}/index.html` : '/index.html');
    if (path) assert.equal(route(`${uri}/`).uri, `/${path}/index.html`);
  }
  for (const uri of ['/terms', '/tr/kullanim-kosullari', '/privacy', '/tr/gizlilik', '/cancellation', '/tr/iptal', '/data-handling', '/tr/veri-isleme', '/accessibility', '/tr/erisilebilirlik', '/contact', '/tr/iletisim', '/pricing', '/tr/fiyatlandirma', '/features/content-and-keywords', '/tr/ozellikler/icerik-ve-anahtar-kelimeler', '/features/seo-opportunities', '/tr/ozellikler/seo-firsatlari', '/use-cases/airport-transfer-seo', '/tr/kullanim-alanlari/havalimani-transfer-seo', '/seo-agencies', '/tr/seo-ajanslari', '/features/technical-seo-audits', '/tr/ozellikler/teknik-seo-denetimleri', '/data-sources', '/tr/veri-kaynaklari', '/help', '/tr/yardim', '/unknown', '/tr/', '/tr/ornek-rapor', '/preview/unknown', '/preview/tr/missing', '/missing/deep/link']) {
    const response = route(uri);
    assert.equal(response.statusCode, 404);
    assert.match(response.body, /<h1>Page not found<\/h1>/);
    assert.equal(response.headers['x-robots-tag'].value, 'noindex');
  }
});

test('CSR only covers extensionless account/app deep links; files and API remain distinct', () => {
  for (const prefix of clientPrefixes) {
    for (const uri of [`/${prefix}`, `/${prefix}/`, `/${prefix}/nested/path`]) {
      assert.equal(route(uri).uri, '/index.csr.html');
    }
    assert.equal(route(`/${prefix}/missing.js`).uri, `/${prefix}/missing.js`);
  }
  for (const uri of ['/missing.css', '/index.js', '/api/health/']) {
    const response = route(uri);
    assert.notEqual(response.uri, '/index.csr.html');
  }
  assert.equal(distribution.DefaultCacheBehavior.FunctionAssociations[0].EventType, 'viewer-request');
  assert.deepEqual(distribution.DefaultCacheBehavior.FunctionAssociations[0].FunctionARN,
    { 'Fn::GetAtt': ['StaticRouteFunction', 'FunctionARN'] });
  assert.ok(distribution.CacheBehaviors.every((behavior) => !behavior.FunctionAssociations));
  assert.equal(distribution.CustomErrorResponses, undefined, 'Do not rewrite API 403/404 globally');
  const policy = template.Resources.FrontendBucketPolicy.Properties.PolicyDocument.Statement;
  assert.deepEqual(policy.map((entry) => entry.Action), ['s3:GetObject', 's3:ListBucket']);
  assert.ok(policy.every((entry) => entry.Principal.Service === 'cloudfront.amazonaws.com'));
  assert.ok(policy.every((entry) => entry.Condition.StringEquals['AWS:SourceArn']));
  assert.equal(route('/missing.js').uri, '/missing.js', 'Missing files rely on S3 404, never a CSR shell');
});


test('generated CDN stack uses the approved paired build inventory without exposing private or unknown public routes', () => {
  const generated = prepareStaticRouteStack(template, ['', 'tr/', 'help', 'tr/yardim', '404']);
  const code = generated.Resources.StaticRouteFunction.Properties.FunctionCode['Fn::Sub'].replaceAll('${FrontendAlias}', 'organicseoops.com');
  const request = uri => runInNewContext(`${code}\nhandler({request: ${JSON.stringify({ uri, headers: { host: { value: 'organicseoops.com' } }, querystring: {} })}})`);
  for (const [uri, html] of [['/', '/index.html'], ['/tr', '/tr/index.html'], ['/tr/', '/tr/index.html'], ['/help', '/help/index.html'], ['/tr/yardim/', '/tr/yardim/index.html']])
    assert.equal(request(uri).uri, html);
  for (const uri of ['/preview/help', '/unknown', '/tr/unknown']) assert.equal(request(uri).statusCode, 404);
  assert.equal(request('/account/login').uri, '/index.csr.html');
  assert.equal(request('/app/project').uri, '/index.csr.html');
  assert.equal(request('/missing.js').uri, '/missing.js');
  const before = structuredClone(template), after = structuredClone(generated);
  delete before.Resources.StaticRouteFunction.Properties.FunctionCode;
  delete after.Resources.StaticRouteFunction.Properties.FunctionCode;
  assert.deepEqual(after, before, 'Network, API, access and cache settings stay source-owned');
  for (const paths of [['account'], ['tr/app'], ['../help'], ['tr', 'tr/'], [''] .concat(Array(64).fill('help'))])
    assert.throws(() => prepareStaticRouteStack(template, paths));
});
