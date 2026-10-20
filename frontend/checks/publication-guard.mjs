import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';
import { prepareStaticRouteStack } from './cdn-inventory.mjs';
import { publicPaths, publicAnalyticsRoutes } from '../src/app/route-inventory.ts';

const digest = (html) => createHash('sha256').update(html).digest('hex');

export function assertPublishable({ routes, approvals, htmlByRoute, origin, sitemapXml }) {
  assert.equal(approvals.version, 1, 'Unsupported publication approval version');
  assert.match(origin, /^https:\/\/[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)+$/);
  assert.deepEqual(Object.keys(approvals.routes).sort(), routes.filter((path) => path !== '404').sort());
  const pages = routes.filter((path) => path !== '404');
  assert.ok(pages.some((path) => path.startsWith('tr/')), 'Reviewed Turkish pages are required before public release');
  for (const path of pages) {
    assert.ok(typeof path === 'string' && path.length <= 128
      && (path === '' || path === 'tr/' || /^[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(path))
      && path !== 'tr' && !/^(?:account|app|preview|404)(?:\/|$)/.test(path.replace(/^tr\//, '')),
      'Private, preview and error paths cannot enter a publication');
    const approval = approvals.routes[path];
    assert.equal(approval.state, 'approved', `Unapproved page: /${path}`);
    assert.equal(approval.editor, 'founder');
    assert.equal(approval.publisher, 'founder');
    assert.ok(approval.reviewer?.trim() && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(approval.reviewedAt)
      && Number.isFinite(Date.parse(approval.reviewedAt)), `Missing review record: /${path}`);
    assert.match(approval.htmlSha256, /^[0-9a-f]{64}$/);
    assert.equal(approval.history.at(-1)?.htmlSha256, approval.htmlSha256,
      `Approval history does not match: /${path}`);
    assert.equal(approval.history.at(-1)?.reviewer, approval.reviewer);
    assert.equal(approval.history.at(-1)?.reviewedAt, approval.reviewedAt);
    const html = htmlByRoute[path];
    assert.equal(digest(html), approval.htmlSha256, `Page changed since review: /${path}`);
    const document = new JSDOM(html).window.document;
    assert.ok(document.querySelector('main h1')?.textContent.trim());
    assert.ok(document.querySelector('meta[name="description"]')?.content.trim());
    for (const tag of document.querySelectorAll('meta[name="robots"]'))
      assert.doesNotMatch(tag.content, /\bnoindex\b/i, `Noindex publication: /${path}`);
    const canonicals = document.querySelectorAll('head link[rel="canonical"]');
    assert.equal(canonicals.length, 1, `Missing or duplicate canonical: /${path}`);
    assert.equal(canonicals[0].href, `${origin}/${path}`);
    const alternate = approval.alternate;
    assert.ok(pages.includes(alternate) && approval !== approvals.routes[alternate]);
    assert.equal(approvals.routes[alternate].alternate, path, `Missing reciprocal locale: /${path}`);
    assert.equal(document.documentElement.lang, path.startsWith('tr/') ? 'tr' : 'en');
    assert.notEqual(path.startsWith('tr/'), alternate.startsWith('tr/'), `Missing opposite locale: /${path}`);
    const english = path.startsWith('tr/') ? alternate : path;
    const turkish = path.startsWith('tr/') ? path : alternate;
    const alternates = [...document.querySelectorAll('head link[rel="alternate"][hreflang]')]
      .map(link => [link.getAttribute('hreflang'), link.getAttribute('href')]).sort();
    assert.deepEqual(alternates, [['en', `${origin}/${english}`], ['tr', `${origin}/${turkish}`],
      ['x-default', `${origin}/${english}`]], `Locale alternates do not match approved pages: /${path}`);
    const title = document.title.trim();
    const description = document.querySelector('meta[name="description"]').content.trim();
    assert.ok(title, `Missing title: /${path}`);
    for (const [property, content] of [['og:type', 'website'], ['og:url', `${origin}/${path}`], ['og:title', title], ['og:description', description]]) {
      const tags = document.querySelectorAll(`head meta[property="${property}"]`);
      assert.equal(tags.length, 1, `Missing or duplicate share metadata: /${path}`);
      assert.equal(tags[0].content, content, `Share metadata mismatch: /${path}`);
    }
    for (const [name, content] of [['twitter:card', 'summary'], ['twitter:title', title], ['twitter:description', description]]) {
      const tags = document.querySelectorAll(`head meta[name="${name}"]`);
      assert.equal(tags.length, 1, `Missing or duplicate share metadata: /${path}`);
      assert.equal(tags[0].content, content, `Share metadata mismatch: /${path}`);
    }
    const schema = document.querySelectorAll('head script#public-page-schema[type="application/ld+json"]');
    assert.equal(schema.length, 1, `Missing or duplicate page schema: /${path}`);
    assert.deepEqual(JSON.parse(schema[0].textContent), { '@context': 'https://schema.org', '@type': 'WebPage',
      url: `${origin}/${path}`, name: title, description, inLanguage: document.documentElement.lang }, `Page schema mismatch: /${path}`);
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) JSON.parse(script.textContent);
  }
  for (const path of pages) {
    const document = new JSDOM(htmlByRoute[path]).window.document;
    const publication = document.querySelectorAll('head script[src="/publication.js"]');
    assert.equal(publication.length, 1, 'Missing or duplicate postbuild publication script');
    assert.deepEqual(publication[0].getAttributeNames(), ['src']);
    const runtimes = document.querySelectorAll('head template#public-page-runtime');
    assert.equal(runtimes.length, 1, 'Missing or duplicate reviewed runtime metadata');
    const templates = [...runtimes[0].content.children];
    assert.deepEqual(templates.map(tag => tag.getAttribute('data-path')).sort(), [...pages].sort(), 'Runtime routes mismatch');
    for (const tag of templates) {
      assert.equal(tag.tagName, 'TEMPLATE');
      assert.deepEqual(tag.getAttributeNames().sort(), ['data-path', 'lang']);
      const target = new JSDOM(htmlByRoute[tag.getAttribute('data-path')]).window.document;
      assert.equal(tag.lang, target.documentElement.lang);
      const expected = [...target.head.querySelectorAll('title, meta[name="description"], link[rel="canonical"], link[rel="alternate"][hreflang], meta[property^="og:"], meta[name^="twitter:"], script#public-page-schema')].map(node => node.outerHTML).join('');
      assert.equal(tag.innerHTML, expected, 'Runtime metadata differs from reviewed initial HTML');
    }
  }
  assert.ok(typeof sitemapXml === 'string', 'Missing publication sitemap');
  const sitemap = new JSDOM(sitemapXml, { contentType: 'application/xml' });
  const root = sitemap.window.document.documentElement;
  assert.equal(root.localName, 'urlset');
  assert.equal(root.namespaceURI, 'http://www.sitemaps.org/schemas/sitemap/0.9');
  assert.deepEqual([...root.children].map(node => {
    assert.equal(node.localName, 'url');
    assert.equal(node.children.length, 1);
    assert.equal(node.firstElementChild.localName, 'loc');
    return node.firstElementChild.textContent;
  }).sort(), pages.map(path => `${origin}/${path}`).sort(), 'Sitemap must contain exactly the approved locale URLs');
  sitemap.window.close();
}

// Mutable review records are postbuild data, never inputs to hashed Angular assets.
export function compileRuntimePublication(approvals) {
  assert.equal(approvals.version, 1, 'Unsupported publication approval version');
  const routes = Object.fromEntries(Object.entries(approvals.routes).map(([path, row]) => [path, {
    state: row.state, editor: row.editor, publisher: row.publisher, reviewer: row.reviewer,
    reviewedAt: row.reviewedAt, htmlSha256: row.htmlSha256, alternate: row.alternate, history: [{ reviewer: row.history.at(-1).reviewer,
      reviewedAt: row.history.at(-1).reviewedAt, htmlSha256: row.history.at(-1).htmlSha256 }],
  }]));
  const data = JSON.stringify({ version: 1, routes }).replace(/</g, '\\u003c');
  assert.ok(Buffer.byteLength(data, 'utf8') <= 64 * 1024, 'Public review configuration exceeds its runtime bound');
  return `document.getElementById('public-page-runtime').setAttribute('data-approvals', JSON.stringify(${data}));\n`;
}

// Deployment artifact only: callers must never accept route authority from a browser.
export function compilePublicAnalyticsPolicy(args, inventory = publicAnalyticsRoutes) {
  assertPublishable(args);
  assert.equal(args.approvals.version, 1);
  assert.ok(Array.isArray(inventory) && inventory.length >= 2 && inventory.length <= 64);
  assert.ok(args.origin.length <= 253);
  const paths = new Set(), identities = new Set(), ctaOwners = new Map();
  const rows = inventory.map(route => {
    assert.deepEqual(Object.keys(route).sort(), ['ctaIds', 'id', 'locale', 'path']);
    assert.ok(typeof route.path === 'string' && route.path.length <= 128
      && (route.path === '' || route.path === 'tr/' || /^[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(route.path)));
    const local = route.path.replace(/^tr\//, '');
    assert.ok(route.path !== 'tr' && !/^(?:account|app|preview|404)(?:\/|$)/.test(local));
    assert.ok(['en', 'tr'].includes(route.locale));
    assert.equal(route.locale === 'tr', route.path.startsWith('tr/'));
    assert.ok(typeof route.id === 'string' && /^[A-Z][A-Z0-9_]{0,31}$/.test(route.id));
    assert.ok(args.routes.includes(route.path) && args.approvals.routes[route.path]?.state === 'approved');
    assert.ok(!paths.has(route.path) && !identities.has(`${route.id}:${route.locale}`));
    paths.add(route.path); identities.add(`${route.id}:${route.locale}`);
    assert.ok(Array.isArray(route.ctaIds) && route.ctaIds.length <= 16 && new Set(route.ctaIds).size === route.ctaIds.length);
    for (const cta of route.ctaIds) {
      assert.ok(typeof cta === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(cta));
      assert.ok(!ctaOwners.has(cta) || ctaOwners.get(cta) === route.id, 'CTA belongs to a different route ID');
      ctaOwners.set(cta, route.id);
    }
    return { path: route.path, id: route.id, locale: route.locale, cta_ids: [...route.ctaIds].sort(),
      html_sha256: args.approvals.routes[route.path].htmlSha256 };
  });
  for (const row of rows) {
    const equivalent = rows.find(other => other.id === row.id && other.locale !== row.locale);
    assert.ok(equivalent && args.approvals.routes[row.path].alternate === equivalent.path, 'Missing analytics locale equivalent');
    assert.deepEqual(equivalent.cta_ids, row.cta_ids);
  }
  const policy = { version: 'public-analytics-policy-v1', origin: args.origin,
    routes: rows.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0) };
  assert.ok(Buffer.byteLength(JSON.stringify(policy), 'utf8') <= 16 * 1024);
  return policy;
}

async function main() {
  const options = process.argv.slice(2);
  assert.ok(options.length === 0 || (options.length === 1 && options[0] === '--analytics-policy'), 'Unknown publication-guard option');
  const approvals = JSON.parse(await readFile(new URL('../publication-approvals.json', import.meta.url)));
  const browser = new URL('../dist/organicseoops/browser/', import.meta.url);
  const pages = publicPaths.filter((path) => path !== '404');
  const htmlByRoute = Object.fromEntries(await Promise.all(pages.map(async (path) => [
    path, await readFile(new URL(path ? `${path}/index.html` : 'index.html', browser), 'utf8'),
  ])));
  const sitemapXml = await readFile(new URL('sitemap.xml', browser), 'utf8').catch(error => {
    if (error.code !== 'ENOENT') throw error;
    return undefined;
  });
  const template = JSON.parse(await readFile(new URL('../../deploy/frontend-origin-stack.json', import.meta.url), 'utf8'));
  const routing = JSON.parse(await readFile(new URL('../dist/organicseoops/frontend-origin-stack.json', import.meta.url), 'utf8'));
  assert.deepEqual(routing, prepareStaticRouteStack(template, [...publicPaths]), 'Static CDN artifact differs from the current prerender inventory/template');
  const args = { routes: [...publicPaths], approvals, htmlByRoute, sitemapXml, origin: process.env.FRONTEND_PUBLIC_ORIGIN ?? '' };
  assertPublishable(args);
  const runtime = new JSDOM(htmlByRoute[pages[0]]).window.document.querySelector('head #public-page-runtime').outerHTML;
  for (const file of ['index.csr.html', ...(publicPaths.includes('404') ? ['404/index.html'] : [])]) {
    const document = new JSDOM(await readFile(new URL(file, browser), 'utf8')).window.document;
    assert.ok([...document.head.querySelectorAll('meta[name="robots"]')].some(tag => /\bnoindex\b/i.test(tag.content)), 'Private/error entry must stay noindex');
    assert.equal(document.head.querySelector('link[rel="canonical"], link[hreflang], meta[property^="og:"], meta[name^="twitter:"], #public-page-schema'), null);
    assert.equal(document.head.querySelector('#public-page-runtime')?.outerHTML, runtime, 'Private/error runtime differs from the approved route inventory');
    assert.equal(document.head.querySelectorAll('script[src="/publication.js"]').length, 1);
  }
  assert.equal(await readFile(new URL('publication.js', browser), 'utf8'), compileRuntimePublication(approvals),
    'Runtime publication records differ from approved HTML');
  if (options.length) {
    process.stdout.write(JSON.stringify(compilePublicAnalyticsPolicy(args)) + '\n');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
