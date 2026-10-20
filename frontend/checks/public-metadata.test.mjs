import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { JSDOM } from 'jsdom';
import { preparePublicMetadata } from './public-metadata.mjs';
import { assertPublishable } from './publication-guard.mjs';

const origin = 'https://synthetic.example.invalid';
function fixture() {
  const routes = ['help', 'tr/yardim', '404'];
  const pages = { help: { alternate: 'tr/yardim' }, 'tr/yardim': { alternate: 'help' } };
  const htmlByRoute = Object.fromEntries(['help', 'tr/yardim'].map(path => [path,
    `<!doctype html><html lang="${path === 'help' ? 'en' : 'tr'}"><head><title>Source &amp; &lt;sample&gt;</title><meta name="description" content="Synthetic &lt;/script&gt; &amp; safe summary"><meta name="robots" content="noindex, nofollow"></head><body><main><h1>Synthetic ${path}</h1><p>Explicit synthetic body, not actual approved copy.</p><a href="/${pages[path].alternate}">Language</a></main><script type="module" src="/main-synthetic.js"></script></body></html>`,
  ]));
  return { routes, pages, htmlByRoute, origin };
}
function approved(candidate, args) {
  const routes = Object.fromEntries(Object.entries(candidate.htmlByRoute).map(([path, html]) => {
    const htmlSha256 = createHash('sha256').update(html).digest('hex');
    const record = { reviewer: 'Synthetic reviewer fixture', reviewedAt: '2026-10-12T00:00:00Z', htmlSha256 };
    return [path, { ...record, state: 'approved', editor: 'founder', publisher: 'founder',
      alternate: args.pages[path].alternate, history: [record] }];
  }));
  return { ...args, ...candidate, approvals: { version: 1, routes } };
}

test('candidate generation preserves initial body/runtime assets and produces reviewable paired SEO artifacts', () => {
  const args = fixture();
  const candidate = preparePublicMetadata(args);
  for (const path of Object.keys(args.pages)) {
    const before = new JSDOM(args.htmlByRoute[path]).window.document;
    const after = new JSDOM(candidate.htmlByRoute[path]).window.document;
    assert.equal(after.body.innerHTML, before.body.innerHTML);
    assert.equal(after.querySelector('link[rel="canonical"]').href, `${origin}/${path}`);
    assert.equal(after.querySelector('meta[name="robots"]'), null);
    assert.equal(after.querySelector('meta[property="og:title"]').content, 'Source & <sample>');
    assert.equal(after.querySelectorAll('script').length, 3, 'Metadata cannot inject a closing script');
    assert.equal(JSON.parse(after.querySelector('script[type="application/ld+json"]').textContent).description,
      'Synthetic </script> & safe summary');
  }
  assert.doesNotThrow(() => assertPublishable(approved(candidate, args)));
  assert.deepEqual(preparePublicMetadata({ ...args, htmlByRoute: candidate.htmlByRoute }), candidate,
    'A candidate rebuild must preserve the reviewed revision hash');
  const sourceSchema = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebSite","name":"Synthetic site"}</script>';
  const withSchema = preparePublicMetadata({ ...args, htmlByRoute: { ...args.htmlByRoute,
    help: args.htmlByRoute.help.replace('</head>', `${sourceSchema}</head>`) } });
  assert.ok(withSchema.htmlByRoute.help.includes(sourceSchema), 'Existing source-owned schema must survive preparation');
  assert.doesNotThrow(() => assertPublishable(approved(withSchema, args)));
  const forged = { ...candidate, htmlByRoute: { ...candidate.htmlByRoute } };
  const document = new JSDOM(forged.htmlByRoute.help).window.document;
  const runtime = document.querySelector('#public-page-runtime');
  const alternateTemplate = runtime.content.querySelector('template[data-path="tr/yardim"]');
  alternateTemplate.content.querySelector('meta[property="og:url"]').content = `${origin}/account`;
  forged.htmlByRoute.help = document.documentElement.outerHTML;
  assert.throws(() => assertPublishable(approved(forged, args)), /Runtime metadata differs/);
  const draft = approved(candidate, args); draft.approvals.routes.help.state = 'draft';
  assert.throws(() => assertPublishable(draft), /Unapproved page/);
});

test('generation refuses private/preview/error paths, wrong language, incomplete locale pairs and missing initial content', () => {
  for (const path of ['account', 'tr/app', 'preview/help', 'tr/preview/help', '404', '../help']) {
    const args = fixture();
    args.routes[0] = path; args.pages[path] = args.pages.help; delete args.pages.help;
    args.pages['tr/yardim'].alternate = path; args.htmlByRoute[path] = args.htmlByRoute.help;
    assert.throws(() => preparePublicMetadata(args));
  }
  for (const change of [
    args => { args.origin = 'http://synthetic.example.invalid'; },
    args => { delete args.pages['tr/yardim']; },
    args => { args.pages['tr/yardim'].alternate = 'missing'; },
    args => { args.htmlByRoute['tr/yardim'] = args.htmlByRoute.help; },
    args => { args.htmlByRoute.help = args.htmlByRoute.help.replace(/<main>.*<\/main>/, '<main></main>'); },
  ]) {
    const args = fixture(); change(args); assert.throws(() => preparePublicMetadata(args));
  }
});

test('release rejects missing/extra sitemap URLs and reviewed but mismatching share/schema tags', () => {
  const args = fixture();
  const candidate = preparePublicMetadata(args);
  for (const sitemapXml of [undefined, candidate.sitemapXml.replace('<loc>', '<loc>https://other.invalid/'),
    candidate.sitemapXml.replace('</urlset>', '<url><loc>https://synthetic.example.invalid/account</loc></url></urlset>')])
    assert.throws(() => assertPublishable({ ...approved(candidate, args), sitemapXml }));
  for (const change of [
    html => html.replace('property="og:url"', 'property="og:missing"'),
    html => html.replace('"@type":"WebPage"', '"@type":"Review"'),
    html => html.replace('</head>', '<link rel="canonical" href="https://other.invalid/"></head>'),
    html => html.replace('</head>', '<meta name="robots" content="index"><meta name="robots" content="noindex"></head>'),
  ]) {
    const changed = { ...candidate, htmlByRoute: { ...candidate.htmlByRoute, help: change(candidate.htmlByRoute.help) } };
    assert.throws(() => assertPublishable(approved(changed, args)));
  }
});

test('repository configuration remains empty so no development page becomes a publication candidate', async () => {
  assert.deepEqual(JSON.parse(await readFile(new URL('../public-page-metadata.json', import.meta.url), 'utf8')),
    { version: 1, pages: {} });
});

test('actual build poststep writes a synthetic candidate which the final HTML/sitemap release command verifies', async () => {
  const workspace = await mkdtemp(join(tmpdir(), 'organicseoops-public-metadata-'));
  const root = join(workspace, 'frontend');
  try {
    const args = fixture();
    await mkdir(join(root, 'checks'), { recursive: true });
    await mkdir(join(workspace, 'deploy'));
    await copyFile(new URL('../../deploy/frontend-origin-stack.json', import.meta.url), join(workspace, 'deploy/frontend-origin-stack.json'));
    await mkdir(join(root, 'src/app'), { recursive: true });
    await symlink(fileURLToPath(new URL('../node_modules', import.meta.url)), join(root, 'node_modules'));
    await writeFile(join(root, 'package.json'), '{"type":"module"}');
    await writeFile(join(root, 'src/app/route-inventory.ts'),
      `export const publicPaths = ${JSON.stringify(args.routes)}; export const publicAnalyticsRoutes = [];`);
    for (const file of ['public-metadata.mjs', 'publication-guard.mjs', 'cdn-inventory.mjs'])
      await copyFile(new URL(file, import.meta.url), join(root, 'checks', file));
    await writeFile(join(root, 'public-page-metadata.json'), JSON.stringify({ version: 1, pages: args.pages }));
    await writeFile(join(root, 'publication-approvals.json'), JSON.stringify({ version: 1,
      routes: Object.fromEntries(Object.keys(args.pages).map(path => [path, { state: 'draft' }])) }));
    const browser = join(root, 'dist/organicseoops/browser');
    for (const [path, html] of Object.entries(args.htmlByRoute)) {
      await mkdir(join(browser, path), { recursive: true });
      await writeFile(join(browser, path, 'index.html'), html);
    }
    const run = file => spawnSync(process.execPath, [`checks/${file}`], { cwd: root,
      env: { ...process.env, FRONTEND_PUBLIC_ORIGIN: origin }, encoding: 'utf8' });
    await writeFile(join(browser, 'index.csr.html'), '<!doctype html><html><head><title>Private CSR entry</title><meta name="robots" content="noindex, nofollow"></head><body><app-root></app-root></body></html>');
    await mkdir(join(browser, '404'), { recursive: true });
    await writeFile(join(browser, '404/index.html'), '<!doctype html><html><head><title>Not found</title><meta name="robots" content="noindex, nofollow"></head><body><main><h1>Not found</h1></main></body></html>');
    const build = run('public-metadata.mjs');
    assert.equal(build.status, 0, build.stderr);
    const review = join(root, 'dist/organicseoops/review-browser');
    const candidate = { htmlByRoute: {}, sitemapXml: await readFile(join(review, 'sitemap.xml'), 'utf8') };
    for (const path of Object.keys(args.pages)) {
      candidate.htmlByRoute[path] = await readFile(join(review, path, 'index.html'), 'utf8');
      assert.equal(await readFile(join(browser, path, 'index.html'), 'utf8'), args.htmlByRoute[path]);
    }
    await assert.rejects(readFile(join(browser, 'sitemap.xml')), { code: 'ENOENT' });
    assert.deepEqual(candidate, preparePublicMetadata(args));
    const staleApprovals = approved(candidate, args).approvals;
    staleApprovals.routes.help.htmlSha256 = 'a'.repeat(64);
    staleApprovals.routes.help.history[0].htmlSha256 = 'a'.repeat(64);
    await writeFile(join(root, 'publication-approvals.json'), JSON.stringify(staleApprovals));
    const denied = run('public-metadata.mjs');
    assert.notEqual(denied.status, 0); assert.match(denied.stderr, /Page changed since review/);
    assert.equal(await readFile(join(browser, 'help/index.html'), 'utf8'), args.htmlByRoute.help);
    await assert.rejects(readFile(join(browser, 'sitemap.xml')), { code: 'ENOENT' });
    const oversized = approved(candidate, args).approvals;
    oversized.routes.help.reviewer = 'X'.repeat(65536);
    oversized.routes.help.history[0].reviewer = oversized.routes.help.reviewer;
    await writeFile(join(root, 'publication-approvals.json'), JSON.stringify(oversized));
    const tooLarge = run('public-metadata.mjs');
    assert.notEqual(tooLarge.status, 0); assert.match(tooLarge.stderr, /runtime bound/);
    assert.equal(await readFile(join(browser, 'help/index.html'), 'utf8'), args.htmlByRoute.help);
    await assert.rejects(readFile(join(browser, 'publication.js')), { code: 'ENOENT' });
    await writeFile(join(root, 'publication-approvals.json'), JSON.stringify(approved(candidate, args).approvals));
    const promote = run('public-metadata.mjs');
    assert.equal(promote.status, 0, promote.stderr);
    const csr = new JSDOM(await readFile(join(browser, 'index.csr.html'), 'utf8')).window.document;
    assert.ok(csr.querySelector('template#public-page-runtime'));
    assert.ok(csr.querySelector('script[src="/publication.js"]'));
    assert.match(csr.querySelector('meta[name="robots"]').content, /noindex/);
    assert.equal(csr.querySelector('link[rel="canonical"]'), null);
    const notFound = new JSDOM(await readFile(join(browser, '404/index.html'), 'utf8')).window.document;
    assert.ok(notFound.querySelector('template#public-page-runtime'));
    assert.ok(notFound.querySelector('script[src="/publication.js"]'));
    assert.match(notFound.querySelector('meta[name="robots"]').content, /noindex/);
    assert.equal(notFound.querySelector('link[rel="canonical"]'), null);
    const policy = await readFile(join(browser, 'publication.js'), 'utf8');
    runInNewContext(policy, { document: csr });
    assert.deepEqual(JSON.parse(csr.querySelector('#public-page-runtime').getAttribute('data-approvals')), approved(candidate, args).approvals);
    assert.ok(!candidate.htmlByRoute.help.includes('Synthetic reviewer fixture'), 'Mutable records cannot enter reviewed HTML');
    const release = run('publication-guard.mjs');
    assert.equal(release.status, 0, release.stderr);
    await writeFile(join(browser, 'publication.js'), policy.replace('Synthetic reviewer fixture', 'Changed fixture reviewer'));
    const badPublication = run('publication-guard.mjs');
    assert.notEqual(badPublication.status, 0); assert.match(badPublication.stderr, /Runtime publication records differ/);
    await writeFile(join(browser, 'publication.js'), policy);
    const originalCsr = await readFile(join(browser, 'index.csr.html'), 'utf8');
    await writeFile(join(browser, 'index.csr.html'), originalCsr.replace('id="public-page-runtime"', 'id="missing-runtime"'));
    const badCsr = run('publication-guard.mjs');
    assert.notEqual(badCsr.status, 0); assert.match(badCsr.stderr, /Private\/error runtime differs/);
    await writeFile(join(browser, 'index.csr.html'), originalCsr);
    const stackPath = join(root, 'dist/organicseoops/frontend-origin-stack.json');
    const stack = await readFile(stackPath, 'utf8');
    await writeFile(stackPath, stack.replace('tr/yardim', 'unknown'));
    const badRoute = run('publication-guard.mjs');
    assert.notEqual(badRoute.status, 0); assert.match(badRoute.stderr, /Static CDN artifact differs/);
    await writeFile(stackPath, stack);
    await writeFile(join(browser, 'sitemap.xml'), candidate.sitemapXml.replace('tr/yardim', 'account'));
    const stale = run('publication-guard.mjs');
    assert.notEqual(stale.status, 0); assert.match(stale.stderr, /Sitemap must contain exactly/);
  } finally { await rm(workspace, { recursive: true, force: true }); }
});
