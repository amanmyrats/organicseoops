import assert from 'node:assert/strict';
import { cp, readFile, rm, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';
import { publicPaths } from '../src/app/route-inventory.ts';
import { prepareStaticRouteStack } from './cdn-inventory.mjs';
import { assertPublishable, compileRuntimePublication } from './publication-guard.mjs';

export function preparePublicMetadata({ routes, pages, htmlByRoute, origin }) {
  assert.match(origin, /^https:\/\/[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)+$/);
  assert.ok(origin.length <= 253);
  const paths = routes.filter(path => path !== '404');
  assert.ok(paths.length >= 2 && paths.length <= 64 && new Set(paths).size === paths.length);
  assert.deepEqual(Object.keys(pages).sort(), [...paths].sort(), 'Candidate pages must match the prerender inventory');
  const prepared = {};
  for (const path of paths) {
    assert.ok(typeof path === 'string' && path.length <= 128
      && (path === '' || path === 'tr/' || /^[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(path)));
    assert.ok(path !== 'tr' && !/^(?:account|app|preview|404)(?:\/|$)/.test(path.replace(/^tr\//, '')),
      'Private, preview and error pages cannot become publication candidates');
    assert.deepEqual(Object.keys(pages[path]), ['alternate']);
    const alternate = pages[path].alternate;
    assert.ok(paths.includes(alternate) && alternate !== path && pages[alternate].alternate === path,
      'Candidate pages need reciprocal locale pairs');
    assert.notEqual(path.startsWith('tr/'), alternate.startsWith('tr/'), 'Candidate pages need opposite locales');
    const locale = path.startsWith('tr/') ? 'tr' : 'en';
    const dom = new JSDOM(htmlByRoute[path]);
    const document = dom.window.document;
    assert.equal(document.documentElement.lang, locale, 'Body language must already match the candidate URL');
    assert.ok(document.querySelector('main h1')?.textContent.trim() && document.querySelector('main p')?.textContent.trim()
      && document.querySelector('main a[href]'), 'Candidate needs existing readable Angular content and links');
    const title = document.title.trim();
    const description = document.querySelector('meta[name="description"]')?.content.trim();
    assert.ok(title && description, 'Candidate needs its own title and description');
    // This prepares a privately reviewed candidate; it never writes approval records.
    document.querySelectorAll('head link[rel="canonical"], head link[rel="alternate"][hreflang], head meta[name="robots"], head meta[property^="og:"], head meta[name^="twitter:"], head script#public-page-schema, head template#public-page-runtime, head script[src="/publication.js"]')
      .forEach(node => node.remove());
    const add = (tag, attributes) => {
      const node = document.createElement(tag);
      for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
      document.head.append(node);
      return node;
    };
    const url = `${origin}/${path}`;
    add('link', { rel: 'canonical', href: url });
    const english = locale === 'en' ? path : alternate;
    const turkish = locale === 'tr' ? path : alternate;
    for (const [lang, target] of [['en', english], ['tr', turkish], ['x-default', english]])
      add('link', { rel: 'alternate', hreflang: lang, href: `${origin}/${target}` });
    for (const [property, content] of [['og:type', 'website'], ['og:url', url], ['og:title', title], ['og:description', description]])
      add('meta', { property, content });
    for (const [name, content] of [['twitter:card', 'summary'], ['twitter:title', title], ['twitter:description', description]])
      add('meta', { name, content });
    const schema = add('script', { id: 'public-page-schema', type: 'application/ld+json' });
    schema.textContent = JSON.stringify({ '@context': 'https://schema.org', '@type': 'WebPage',
      url, name: title, description, inLanguage: locale }).replace(/</g, '\\u003c');
    prepared[path] = dom.serialize();
    dom.window.close();
  }
  // Inert head fragments share the same reviewed HTML hash as the initial metadata.
  const documents = Object.fromEntries(Object.entries(prepared).map(([path, html]) => [path, new JSDOM(html)]));
  for (const dom of Object.values(documents)) {
    const runtime = dom.window.document.createElement('template');
    runtime.id = 'public-page-runtime';
    for (const [path, source] of Object.entries(documents)) {
      const page = dom.window.document.createElement('template');
      page.dataset.path = path;
      page.lang = source.window.document.documentElement.lang;
      for (const tag of source.window.document.head.querySelectorAll('title, meta[name="description"], link[rel="canonical"], link[rel="alternate"][hreflang], meta[property^="og:"], meta[name^="twitter:"], script#public-page-schema'))
        page.content.append(tag.cloneNode(true));
      runtime.content.append(page);
    }
    dom.window.document.head.append(runtime);
    const publication = dom.window.document.createElement('script');
    publication.src = '/publication.js';
    dom.window.document.head.append(publication);
  }
  for (const [path, dom] of Object.entries(documents)) { prepared[path] = dom.serialize(); dom.window.close(); }
  const sitemapXml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + [...paths].sort().map(path => `  <url><loc>${origin}/${path}</loc></url>`).join('\n')
    + '\n</urlset>\n';
  return { htmlByRoute: prepared, sitemapXml };
}

async function main() {
  assert.equal(process.argv.length, 2, 'Candidate metadata uses the repository configuration only');
  const config = JSON.parse(await readFile(new URL('../public-page-metadata.json', import.meta.url), 'utf8'));
  assert.deepEqual(Object.keys(config).sort(), ['pages', 'version']);
  assert.equal(config.version, 1);
  assert.ok(config.pages && typeof config.pages === 'object' && !Array.isArray(config.pages));
  const template = JSON.parse(await readFile(new URL('../../deploy/frontend-origin-stack.json', import.meta.url), 'utf8'));
  await writeFile(new URL('../dist/organicseoops/frontend-origin-stack.json', import.meta.url),
    JSON.stringify(prepareStaticRouteStack(template, [...publicPaths]), null, 2) + '\n');
  if (!Object.keys(config.pages).length) return;
  const browser = new URL('../dist/organicseoops/browser/', import.meta.url);
  const htmlByRoute = Object.fromEntries(await Promise.all(publicPaths.filter(path => path !== '404').map(async path => [
    path, await readFile(new URL(path ? `${path}/index.html` : 'index.html', browser), 'utf8'),
  ])));
  const result = preparePublicMetadata({ routes: [...publicPaths], pages: config.pages, htmlByRoute,
    origin: process.env.FRONTEND_PUBLIC_ORIGIN ?? '' });
  const approvals = JSON.parse(await readFile(new URL('../publication-approvals.json', import.meta.url), 'utf8'));
  const approved = Object.keys(config.pages).every(path => approvals.routes[path]?.state === 'approved');
  if (approved) assertPublishable({ ...result, routes: [...publicPaths], approvals, origin: process.env.FRONTEND_PUBLIC_ORIGIN ?? '' });
  // Unapproved candidate HTML must never replace the deployable browser build.
  const publication = compileRuntimePublication(approved ? approvals : { version: 1, routes: {} });
  const target = approved ? browser : new URL('../dist/organicseoops/review-browser/', import.meta.url);
  if (!approved) {
    for (const html of Object.values(htmlByRoute)) {
      const dom = new JSDOM(html);
      assert.ok([...dom.window.document.querySelectorAll('meta[name="robots"]')]
        .some(tag => /\bnoindex\b/i.test(tag.content)), 'Unapproved deployable HTML must remain noindex; rebuild from draft source');
      dom.window.close();
    }
    await rm(target, { recursive: true, force: true });
    await cp(browser, target, { recursive: true });
  }
  for (const [path, html] of Object.entries(result.htmlByRoute))
    await writeFile(new URL(path ? `${path}/index.html` : 'index.html', target), html);
  await writeFile(new URL('sitemap.xml', target), result.sitemapXml);
  await writeFile(new URL('publication.js', target), publication);
  if (approved) {
    const source = new JSDOM(Object.values(result.htmlByRoute)[0]).window.document;
    for (const file of ['index.csr.html', '404/index.html']) {
      const url = new URL(file, target);
      const html = await readFile(url, 'utf8').catch(error => { if (error.code !== 'ENOENT') throw error; return null; });
      if (html === null) continue;
      const dom = new JSDOM(html);
      dom.window.document.querySelectorAll('head #public-page-runtime, head script[src="/publication.js"]').forEach(tag => tag.remove());
      for (const tag of source.querySelectorAll('head #public-page-runtime, head script[src="/publication.js"]'))
        dom.window.document.head.append(tag.cloneNode(true));
      await writeFile(url, dom.serialize());
      dom.window.close();
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
