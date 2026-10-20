import assert from 'node:assert/strict';
import { readFile, readdir, stat } from 'node:fs/promises';
import { test } from 'node:test';
import { JSDOM } from 'jsdom';
import { publicPaths, clientPrefixes } from '../src/app/route-inventory.ts';

const output = new URL('../dist/organicseoops/', import.meta.url);
const browser = new URL('browser/', output);

test('every public route has complete initial HTML, metadata and crawlable links', async () => {
  const generatedHtml = (await readdir(browser, { recursive: true }))
    .filter((file) => file.endsWith('.html')).sort();
  const approvedDevelopmentHtml = [
    'index.csr.html',
    ...publicPaths.map((path) => path ? `${path}/index.html` : 'index.html'),
  ].sort();
  assert.deepEqual(generatedHtml, approvedDevelopmentHtml, 'Unreviewed public routes must not be prerendered');
  for (const path of publicPaths) {
    const html = await readFile(new URL(path ? `${path}/index.html` : 'index.html', browser), 'utf8');
    const document = new JSDOM(html).window.document;
    assert.ok(document.querySelector('main h1')?.textContent.trim(), `Missing heading: /${path}`);
    assert.ok(document.querySelector('main p')?.textContent.trim(), `Missing content: /${path}`);
    assert.ok(document.title.includes('OrganicSEOOps'));
    assert.ok(document.querySelector('meta[name="description"]')?.content);
    assert.equal(document.querySelector('meta[name="robots"]')?.content, 'noindex, nofollow');
    assert.equal(document.querySelector('link[rel="canonical"]'), null, 'Drafts have no approved canonical');
    assert.ok(document.querySelector('main a[href]'), `Missing real link: /${path}`);
    assert.equal(document.querySelector('html').lang, path.startsWith('preview/tr') ? 'tr' : 'en');
    assert.equal(document.querySelector('link[hreflang]'), null, 'Unreviewed locale alternates must not be published');
    if (path === 'preview/tr' || path === 'preview') {
      assert.ok(document.querySelector('main a[href="/preview"][lang="en"]'));
      assert.ok(document.querySelector('main a[href="/preview/tr"][lang="tr"]'));
      assert.equal(document.querySelector('main section').lang, path.startsWith('preview/tr') ? 'tr' : 'en');
      if (path === 'preview/tr') {
        assert.match(document.querySelector('main').textContent, /iki dilli insan incelemesi bekleyen bir taslak/);
        assert.match(document.title, /Türkçe taslak/);
        assert.match(document.querySelector('meta[name="description"]').content, /Türkçe taslak/);
        assert.equal(document.querySelector('body noscript').lang, 'en');
      }
    }
    if (path === '404' || path === 'preview/tr/404') {
      const turkish = path === 'preview/tr/404';
      assert.equal(document.querySelector('main section').lang, turkish ? 'tr' : 'en');
      assert.equal(document.querySelector('main h1').textContent, turkish ? 'Sayfa bulunamadı' : 'Page not found');
      assert.match(document.querySelector('main [role="status"]').textContent, turkish ? /İki dilli insan onayı/ : /Bilingual human approval/);
      assert.ok(document.querySelector('main a[href="/404"][lang="en"]'));
      assert.ok(document.querySelector('main a[href="/preview/tr/404"][lang="tr"]'));
      assert.ok(document.querySelector(turkish ? 'main a[href="/preview/tr/home"]' : 'main a[href="/"]'));
      assert.match(document.querySelector('meta[name="description"]').content, turkish ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
      assert.equal(document.querySelector('body noscript').lang, 'en');
    }
    assert.equal(document.querySelector('form'), null, 'Development preview must not collect credentials');
    const preferences = document.querySelector('footer app-analytics-preferences');
    const turkish = path.startsWith('preview/tr');
    for (const selector of ['header', 'footer', '.skip-link', 'footer details'])
      assert.equal(document.querySelector(selector).lang, turkish ? 'tr' : 'en');
    assert.equal(document.querySelector('body noscript').lang, 'en');
    assert.equal(document.querySelector('.skip-link').textContent, turkish ? 'İçeriğe geç' : 'Skip to content');
    assert.equal(document.querySelector('.skip-link').getAttribute('href'), '#main');
    assert.equal(document.querySelector('header a').getAttribute('href'), turkish ? '/preview/tr/home' : '/');
    assert.equal(document.querySelector('header a').getAttribute('aria-label'), turkish ? 'OrganicSEOOps ana sayfa' : 'OrganicSEOOps home');
    assert.equal(preferences?.querySelector('summary')?.textContent, turkish ? 'Analitik tercihleri' : 'Analytics preferences');
    assert.match(preferences?.querySelector('[role="status"]')?.textContent ?? '', turkish ? /Tercih yok.*analitik kapalı/ : /No choice.*analytics is off/);
    assert.match(preferences?.textContent ?? '', turkish ? /Mevcut taslak yollar analitik toplamaz/ : /current draft routes collect no analytics/i);
    assert.match(preferences?.textContent ?? '', turkish ? /otomatik yenileme yoktur/ : /no automatic renewal/i);
    assert.match(preferences?.textContent ?? '', turkish ? /yetmiş beş dakika/ : /seventy-five minutes/i);
    assert.match(preferences?.textContent ?? '', turkish ? /etkin silmeden sonra bunları otuz beş güne/ : /thirty-five days after active deletion/i);
    assert.equal(preferences?.querySelectorAll('button').length, 3);
  }
  await assert.rejects(stat(new URL('sitemap.xml', browser)), { code: 'ENOENT' });
});

test('the paired agency home drafts are rendered, truthful and excluded from publication', async () => {
  for (const [path, language] of [['', 'en'], ['preview/tr/home', 'tr']]) {
    const html = await readFile(new URL(path ? `${path}/index.html` : 'index.html', browser), 'utf8');
    const document = new JSDOM(html).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('.home-draft').lang, language);
    assert.equal(document.documentElement.lang, language);
    assert.match(main.textContent, language === 'tr' ? /ajans ekipleri/i : /agency teams/i);
    assert.match(main.textContent, language === 'tr' ? /müşteri sonuçları veya canlı rapor değildir/i : /not customer results or a live report/i);
    assert.match(main.textContent, language === 'tr' ? /Herkese açık deneme veya ödeme sunulmaz/i : /No public trial or payment is open/i);
    assert.match(main.querySelector('[role="status"]').textContent, language === 'tr' ? /İki dilli insan onayı/ : /Bilingual human approval/);
    assert.ok(main.querySelector('a[href="/account/register"]'));
    assert.ok(main.querySelector('a[href="/account/login"]'));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr' : '/preview'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/sample-report' : '/sample-report'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/help' : '/preview/help'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/seo-agencies' : '/preview/seo-agencies'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/accessibility' : '/preview/accessibility'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/contact' : '/preview/contact'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/privacy' : '/preview/privacy'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/terms' : '/preview/terms'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/pricing' : '/preview/pricing'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/content-and-keywords' : '/preview/content-and-keywords'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/airport-transfer-seo' : '/preview/airport-transfer-seo'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'}"]`));
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/technical-seo-audits' : '/preview/technical-seo-audits'}"]`));
    assert.ok(main.querySelector('a[href="/"][lang="en"]'));
    assert.ok(main.querySelector('a[href="/preview/tr/home"][lang="tr"]'));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Agency SEO evidence workflow/);
    assert.match(document.querySelector('meta[name="description"]')?.content ?? '', language === 'tr' ? /incelenmemiş Türkçe taslak/ : /agency teams/i);
    assert.equal(document.querySelector('body noscript').lang, 'en');
    assert.equal(document.querySelector('link[rel="canonical"]'), null);
    assert.equal(document.querySelector('link[hreflang]'), null);
    assert.equal(document.querySelector('meta[name="robots"]')?.content, 'noindex, nofollow');
  }
  await assert.rejects(stat(new URL('tr/index.html', browser)), { code: 'ENOENT' });
});

test('synthetic sample separates evidence, recommendation and unknown outcome in both unreviewed locales', async () => {
  for (const [path, language] of [['sample-report', 'en'], ['preview/tr/sample-report', 'tr']]) {
    const html = await readFile(new URL(`${path}/index.html`, browser), 'utf8');
    const document = new JSDOM(html).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(document.documentElement.lang, language);
    const claims = language === 'tr'
      ? [/sentetik geliştirme örneği/i, /bağlı bir Search Console mülkü/i, /öncelik bir insan kararı/i, /arama sonucu: bilinmiyor/i, /tek başına nedenselliği kanıtlamaz/i]
      : [/synthetic development example/i, /not a connected Search Console property/i, /human decision/i, /search outcome: unknown/i, /before\/after numbers alone would not prove causation/i];
    for (const claim of claims) assert.match(main.textContent, claim);
    assert.match(main.querySelector('[role="status"]').textContent, language === 'tr' ? /İki dilli insan onayı/ : /Bilingual human approval/);
    assert.equal(main.querySelector('code[lang="en"]').textContent, 'sample.example.invalid');
    assert.deepEqual([...main.querySelectorAll('tbody [lang="en"]')].map(row => row.textContent), ['airport transfer example', '1,200', '24', '2%']);
    assert.ok(main.querySelector('a[href="/sample-report"][lang="en"]'));
    assert.ok(main.querySelector('a[href="/preview/tr/sample-report"][lang="tr"]'));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Synthetic SEO action example/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed draft/);
    assert.equal(document.querySelector('body noscript').lang, 'en');
    assert.equal(document.querySelector('meta[name="robots"]')?.content, 'noindex, nofollow');
    assert.equal(document.querySelector('link[rel="canonical"]'), null);
    assert.equal(document.querySelector('link[hreflang]'), null);
  }
  await assert.rejects(stat(new URL('tr/ornek-rapor/index.html', browser)), { code: 'ENOENT' });
});

test('paired local HELP drafts have substantive initial guidance without publication or support promises', async () => {
  for (const [path, language] of [['preview/help', 'en'], ['preview/tr/help', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    for (const [path, label] of language === 'tr'
      ? [['/preview/tr/terms', 'Yerel koşullar taslağını okuyun'], ['/preview/tr/privacy', 'Yerel gizlilik taslağını okuyun'], ['/preview/tr', 'Geliştirme durumunu okuyun']]
      : [['/preview/terms', 'Read local terms draft'], ['/preview/privacy', 'Read local privacy draft'], ['/preview', 'Read development status']]) assert.equal(main.querySelector(`a[href="${path}"]`)?.textContent, label);

    assert.equal(main.querySelectorAll('section h2').length, 6);
    const claims = language === 'tr'
      ? [/müşteri verisi girmeyin/i, /Eksik veya kısmi veri sıfır değildir/, /insan onayı gerektirir/, /İptal bir istektir/, /ücretli erişimi doğrulamaz/, /henüz doğrulanmadı/, /yanıt süresi taahhüdü sunmaz/, /OAuth belirteci/]
      : [/Do not enter customer data/, /Missing or partial data is not zero/, /require human approval/, /Cancellation is a request/, /does not confirm paid access/, /acceptance remains unverified/, /no public support endpoint or response-time commitment/, /OAuth tokens/];
    for (const claim of claims) assert.match(main.textContent, claim);
    assert.match(main.querySelector('[role="status"]').textContent, language === 'tr' ? /İki dilli insan onayı/ : /Bilingual human approval/);
    for (const [path, locale] of [['preview/help', 'en'], ['preview/tr/help', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.equal(main.querySelector('form, a[href="/contact"], a[href="/help"], a[href="/tr/yardim"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Help and methodology/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['help', 'tr/yardim']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local SOURCES drafts expose readiness and coverage without live publication claims', async () => {
  for (const [path, language] of [['preview/data-sources', 'en'], ['preview/tr/data-sources', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('tbody th[scope="row"]').length, 5);
    assert.equal(main.querySelectorAll('thead th[scope="col"]').length, 3);
    assert.ok(main.querySelector('caption').textContent.trim());
    const claims = language === 'tr'
      ? [/canlı kullanılabilirliği göstermez/, /gerçek kaynak izinleri ve sağlayıcı kabulü bekleniyor/, /ölçüm kalitesi incelemesi bekleniyor/, /Eksik, bağlantısız, kısmi ve eski/, /rakip trafiğini göstermez/]
      : [/not live availability/, /real source grants and provider acceptance pending/, /measurement-quality review pending/, /Missing, disconnected, partial and stale/, /rankings or competitor traffic/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/data-sources', 'en'], ['preview/tr/data-sources', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/help' : '/preview/help'}"]`));
    assert.equal(main.querySelector('form, a[href="/data-handling"], a[href="/data-sources"], a[href="/tr/veri-kaynaklari"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /SEO data sources/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['data-sources', 'tr/veri-kaynaklari']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local AUDITS drafts distinguish bounded observations, indexation and unknown outcomes', async () => {
  for (const [path, language] of [['preview/technical-seo-audits', 'en'], ['preview/tr/technical-seo-audits', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 4);
    const claims = language === 'tr'
      ? [/müşteri denetimi veya ölçülmüş sonuç içermez/, /eksiksiz site veya tüm web veri kümesi değildir/, /arama motorunun sayfayı nasıl render ettiğini kanıtlamaz/, /hiçbiri bir sonrakini garanti etmez/, /dizine eklenme kanıtı değildir/, /insan onayı/]
      : [/no customer audit or measured result/, /not a complete site or whole-web dataset/, /does not prove how a search engine rendered/, /none guarantees the next/, /not proof of indexing/, /human approval/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/technical-seo-audits', 'en'], ['preview/tr/technical-seo-audits', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'}"]`));
    assert.equal(main.querySelector('form, a[href="/features/technical-seo-audits"], a[href="/tr/ozellikler/teknik-seo-denetimleri"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Technical SEO audit evidence/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['features/technical-seo-audits', 'tr/ozellikler/teknik-seo-denetimleri']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local AGENCY drafts explain client isolation, roles and approval without launch promises', async () => {
  for (const [path, language] of [['preview/seo-agencies', 'en'], ['preview/tr/seo-agencies', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 4);
    const claims = language === 'tr'
      ? [/proje eklemek yeni bir deneme başlatmaz/, /başka bir kuruluşa erişim vermez/, /Görüntüleyiciler iş başlatamaz/, /insan onayı gerektirir/, /otomatik raporlar sunulmaz/, /Herkese açık deneme ve ödeme sunulmaz/]
      : [/adding a project does not start another trial/, /does not grant access to another organization/, /Viewers cannot launch jobs/, /Human approval is required/, /automatic reports are not offered/, /Public trials and payments are not open/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/seo-agencies', 'en'], ['preview/tr/seo-agencies', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'}"]`));
    assert.equal(main.querySelector('form, a[href="/seo-agencies"], a[href="/tr/seo-ajanslari"], a[href="/account/register"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Multi-client agency SEO workflow/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['seo-agencies', 'tr/seo-ajanslari']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local OPPORTUNITIES drafts separate finding evidence, priority, approved work and unknown outcomes', async () => {
  for (const [path, language] of [['preview/seo-opportunities', 'en'], ['preview/tr/seo-opportunities', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 4);
    const claims = language === 'tr'
      ? [/yamyamlaşmayı kanıtlamaz/, /ilgili kaynağa bağlı kontrolleri kullanılamaz/, /insan onayı gerektirir/, /müşteri sitesini düzenlemez/, /eksik satır sıfır değil/, /nedensel artışı kanıtlamaz/]
      : [/prove cannibalization/, /source-dependent checks unavailable/, /require human approval/, /does not edit a customer site/, /missing row in a top-rows export is unknown, not zero/, /do not prove causal uplift/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/seo-opportunities', 'en'], ['preview/tr/seo-opportunities', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'}"]`));
    assert.equal(main.querySelector('form, a[href="/features/seo-opportunities"], a[href="/tr/ozellikler/seo-firsatlari"], a[href="/account/register"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Review SEO opportunities and actions/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['features/seo-opportunities', 'tr/ozellikler/seo-firsatlari']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local CONTENT drafts preserve intent mapping, source-linked briefs and human lifecycle review', async () => {
  for (const [path, language] of [['preview/content-and-keywords', 'en'], ['preview/tr/content-and-keywords', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 4);
    const claims = language === 'tr'
      ? [/Ortak kanıt olmadan/, /yamyamlaşmayı kanıtlamaz/, /kelime sayısı tek başına/, /Atıflar tek başına özgün uzmanlığı/, /yetkili insan onayı gerektirir/, /otomatik yayımlama/]
      : [/human mapping without joint evidence must say so/, /keyword overlap alone does not prove cannibalization/, /word count alone is not a deletion or quality verdict/, /Citations alone do not establish original expertise/, /require authorized human approval/, /does not offer automatic publishing/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/content-and-keywords', 'en'], ['preview/tr/content-and-keywords', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/seo-opportunities' : '/preview/seo-opportunities'}"]`));
    assert.equal(main.querySelector('form, a[href="/features/content-and-keywords"], a[href="/tr/ozellikler/icerik-ve-anahtar-kelimeler"], a[href="/account/register"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Content and keyword workflow/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['features/content-and-keywords', 'tr/ozellikler/icerik-ve-anahtar-kelimeler']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local TRANSFER drafts preserve demand, service eligibility and outcome evidence limits', async () => {
  for (const [path, language] of [['preview/airport-transfer-seo', 'en'], ['preview/tr/airport-transfer-seo', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 4);
    const claims = language === 'tr'
      ? [/arama talebini kanıtlamaz/, /işletme profili uygunluğunu kanıtlamaz/, /konum ve yorum uydurmayın/, /insan onayı alın/, /nedenselliği kanıtlamaz/, /Herkese açık deneme ve ödeme sunulmaz/]
      : [/do not establish search demand/, /does not establish eligibility for a business profile/, /fabricate locations and reviews/, /obtain human approval/, /does not prove causation/, /Public trials and payments are not open/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/airport-transfer-seo', 'en'], ['preview/tr/airport-transfer-seo', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/data-sources' : '/preview/data-sources'}"]`));
    assert.equal(main.querySelector('form, a[href="/use-cases/airport-transfer-seo"], a[href="/tr/kullanim-alanlari/havalimani-transfer-seo"], a[href="/account/register"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Airport-transfer SEO workflow/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['use-cases/airport-transfer-seo', 'tr/kullanim-alanlari/havalimani-transfer-seo']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('CSR entry stays empty and private route HTML is never prerendered', async () => {
  const html = await readFile(new URL('index.csr.html', browser), 'utf8');
  const document = new JSDOM(html).window.document;
  assert.equal(document.querySelector('app-root').textContent.trim(), '');
  assert.equal(document.querySelector('meta[name="robots"]')?.content, 'noindex, nofollow');
  for (const prefix of clientPrefixes) {
    await assert.rejects(stat(new URL(`${prefix}/index.html`, browser)), { code: 'ENOENT' });
  }
  await assert.rejects(stat(new URL('account/login/index.html', browser)), { code: 'ENOENT' });
  await assert.rejects(stat(new URL('tr/index.html', browser)), { code: 'ENOENT' });
});

test('deployment is browser-only and public initial assets exclude account/app code and UI frameworks', async () => {
  await assert.rejects(stat(new URL('server/', output)), { code: 'ENOENT' });
  const files = await readdir(browser);
  assert.equal(files.some((name) => name.endsWith('.mjs')), false);
  const html = await readFile(new URL('index.html', browser), 'utf8');
  const document = new JSDOM(html).window.document;
  const initialAssets = [...document.querySelectorAll('script[src], link[rel="modulepreload"], link[rel="stylesheet"]')]
    .map((element) => element.getAttribute('src') ?? element.getAttribute('href'));
  for (const asset of initialAssets) {
    const contents = await readFile(new URL(asset, browser), 'utf8');
    assert.doesNotMatch(contents, /Sign-in is not implemented yet|Organization: not selected|primeng|bootstrap\.css|tailwindcss/i);
  }
});


test('paired local PRICING drafts disclose planned policy without activating trial or payment', async () => {
  for (const [path, language] of [['preview/pricing', 'en'], ['preview/tr/pricing', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 6);
    const claims = language === 'tr'
      ? [/ayda 149 USD/, /30 gün, kart gerekmez/, /40 dahili birim/, /100 dahili birim/, /satın alınabilir kredi değildir/, /hemen tahsil edilir/, /aylık yenilenir/, /dönem sonunda geçerli olur/, /yedi takvim günüdür/, /90 günlük/, /30 gün içinde/, /en fazla 35 günlük/, /doğrulanmamıştır/, /Paddle satıcı/]
      : [/USD 149/, /30 days, no card required/, /40 internal units/, /100 internal units/, /not money, provider cost or purchasable credits/, /charges immediately/, /renews monthly/, /takes effect at period end/, /seven calendar days/, /90 days/, /within 30 days/, /maximum 35-day/, /remain unverified/, /Paddle seller/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/pricing', 'en'], ['preview/tr/pricing', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.equal(main.querySelector('form, button, a[href="/pricing"], a[href="/tr/fiyatlandirma"], a[href="/account/register"], a[href^="https://"]'), null);
    assert.match(main.querySelector('[role="status"]').textContent, language === 'tr' ? /Herkese açık deneme ve ödeme sunulmaz/ : /Public trials and payments are not open/);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Planned Agency pricing/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['pricing', 'tr/fiyatlandirma']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});


test('paired local CONTACT drafts preserve private support scope without public intake promises', async () => {
  for (const [path, language] of [['preview/contact', 'en'], ['preview/tr/contact', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    for (const [path, label] of language === 'tr'
      ? [['/preview/tr/terms', 'Yerel koşullar taslağını okuyun'], ['/preview/tr/privacy', 'Yerel gizlilik taslağını okuyun'], ['/preview/tr', 'Geliştirme durumunu okuyun']]
      : [['/preview/terms', 'Read local terms draft'], ['/preview/privacy', 'Read local privacy draft'], ['/preview', 'Read development status']]) assert.equal(main.querySelector(`a[href="${path}"]`)?.textContent, label);

    assert.equal(main.querySelectorAll('section h2').length, 5);
    const claims = language === 'tr'
      ? [/herkese açık iletişim gönderim kanalı yoktur/, /soru veya ek toplamaz/, /MFA ile doğrulanmış destek personeli/, /müşteri dışa aktarımına dahil edebilir/, /personel yanıtı, e-posta teslimatı/, /yeni anahtarla yinelenen gönderim yapmayın/, /yanıt süresi taahhüdü/, /hâlâ doğrulanmamıştır/]
      : [/no public contact submission channel/, /collects no question or attachment/, /MFA-authenticated support staff/, /include it in a customer export/, /not staff response, email delivery/, /do not send a duplicate with a new key/, /response-time commitment/, /still unverified/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/contact', 'en'], ['preview/tr/contact', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector('a[href="/account/login"]'));
    assert.match(main.querySelector('app-contact-submission button').textContent, language === 'tr' ? /yerel gönderimi kontrol et/ : /Check configured local intake/);
    assert.match(main.querySelector('app-contact-submission [role="status"]').textContent, language === 'tr' ? /Yerel gönderim açılmadı/ : /Local intake has not been opened/);
    assert.equal(main.querySelector('form, input, textarea, a[href="/contact"], a[href="/tr/iletisim"], a[href="/account/register"], a[href^="mailto:"], a[href^="https://"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Contact and support/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['contact', 'tr/iletisim']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});


test('paired local ACCESSIBILITY drafts distinguish target and automated evidence from unverified manual conformance', async () => {
  for (const [path, language] of [['preview/accessibility', 'en'], ['preview/tr/accessibility', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 4);
    const claims = language === 'tr'
      ? [/uygunluk veya sertifikasyon iddiası değildir/, /WCAG 2.2 AA/, /uygunluğu kanıtlamaz/, /görünür çerçevesi/, /320 CSS piksel/, /%400/, /doğrulanmamıştır/, /test edilmiş tarayıcı\/ekran okuyucu matrisi/, /özel dışa aktarım eklemeyin/, /yanıt süresi taahhüdü yoktur/]
      : [/not a compliance or certification claim/, /WCAG 2.2 AA/, /does not establish conformance/, /visible outline/, /320 CSS-pixel/, /400%/, /remain unverified/, /No tested browser\/screen-reader matrix/, /private exports/, /no public inbox or response-time commitment/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/accessibility', 'en'], ['preview/tr/accessibility', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/contact' : '/preview/contact'}"]`));
    assert.equal(main.querySelector('form, button, input, textarea, a[href="/accessibility"], a[href="/tr/erisilebilirlik"], a[href="/account/register"], a[href^="mailto:"], a[href^="https://"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Accessibility target and evidence/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['accessibility', 'tr/erisilebilirlik']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local DATA-HANDLING drafts explain selected controls and unfinished retention/legal gates', async () => {
  for (const [path, language] of [['preview/data-handling', 'en'], ['preview/tr/data-handling', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 5);
    const claims = language === 'tr'
      ? [/onaylı gizlilik bildirimi veya güvenlik sertifikasyonu değildir/, /şifrelenmiş depolama/, /OAuth/, /sağlayıcı tarafındaki silmeyi kanıtlamaz/, /uygun kullanım ve depolama hakları/, /sıfır saklama sözü verilmez/, /alıcılarında kalır/, /90 gün/, /30 gün/, /35 günlük/, /self servis kapatılması devre dışıdır/]
      : [/not an approved privacy notice or security certification/, /encrypted storage/, /OAuth/, /does not prove provider-side deletion/, /appropriate use and storage rights/, /zero-retention promise/, /remain with their recipients/, /90 days/, /30 days/, /35-day/, /Self-service organization closure remains disabled/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/data-handling', 'en'], ['preview/tr/data-handling', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/contact' : '/preview/contact'}"]`));
    assert.equal(main.querySelector('form, button, input, textarea, a[href="/data-handling"], a[href="/tr/veri-isleme"], a[href="/account/register"], a[href^="mailto:"], a[href^="https://"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Data handling and current limits/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['data-handling', 'tr/veri-isleme']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local CANCELLATION drafts explain cancellation boundaries and unfinished provider/deletion gates', async () => {
  for (const [path, language] of [['preview/cancellation', 'en'], ['preview/tr/cancellation', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 4);
    const claims = language === 'tr'
      ? [/30 günlük kartsız/, /anında tahsilat/, /dönem sonu iptal/, /iptali kanıtlamaz/, /yedi takvim günü/, /otomatik orantılı iade değildir/, /90 gün/, /30 gün/, /35 günlük/, /Self servis kapatma devre dışıdır/]
      : [/30-day no-card/, /immediate charge/, /period-end cancellation/, /does not prove cancellation/, /seven calendar days/, /not an automatic prorated refund/, /90 days/, /30 days/, /35-day/, /Self-service closure remains disabled/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/cancellation', 'en'], ['preview/tr/cancellation', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/contact' : '/preview/contact'}"]`));
    assert.equal(main.querySelector('form, button, input, textarea, a[href="/cancellation"], a[href="/tr/iptal"], a[href="/account/register"], a[href^="mailto:"], a[href^="https://"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Cancellation and retained access/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['cancellation', 'tr/iptal']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local PRIVACY drafts separate data categories and retain legal and hosted gates', async () => {
  for (const [path, language] of [['preview/privacy', 'en'], ['preview/tr/privacy', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 6);
    const claims = language === 'tr'
      ? [/onaylı gizlilik bildirimi değildir/, /hizmet kayıtları/, /ürün edinim gözlemlerinden ayrı/, /OAuth/, /uluslararası aktarımlar/, /taslak yollar isteğe bağlı edinim analitiği toplamaz/, /on beş dakikalık/, /yetmiş beş dakika/, /Kimlik temizleme/, /90 gün/, /30 gün/, /35 günlük/, /self servis kapatılması devre dışıdır/, /veri sorumlusu kimliğini/, /doğrulanmış hak talebi kanalı değildir/]
      : [/not an approved privacy notice/, /service records/, /separate from product acquisition observations/, /OAuth/, /international transfers/, /draft routes collect no optional acquisition analytics/, /fifteen-minute/, /seventy-five minutes/, /Identity cleanup/, /90 days/, /30 days/, /35-day/, /Self-service organization closure remains disabled/, /controller identity/, /not a verified rights-request channel/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/privacy', 'en'], ['preview/tr/privacy', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/contact' : '/preview/contact'}"]`));
    assert.equal(main.querySelector('form, button, input, textarea, a[href="/privacy"], a[href="/tr/gizlilik"], a[href="/account/register"], a[href^="mailto:"], a[href^="https://"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Privacy and data choices/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['privacy', 'tr/gizlilik']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});

test('paired local TERMS drafts explain product boundaries without contract or offer authority', async () => {
  for (const [path, language] of [['preview/terms', 'en'], ['preview/tr/terms', 'tr']]) {
    const document = new JSDOM(await readFile(new URL(`${path}/index.html`, browser), 'utf8')).window.document;
    const main = document.querySelector('main');
    assert.equal(main.querySelector('article').lang, language);
    assert.equal(main.querySelectorAll('section h2').length, 5);
    const claims = language === 'tr'
      ? [/onaylı sözleşme veya mevcut teklif değildir/, /her aktif kuruluştan ayrılın/, /toplama izinlerine/, /satın alınabilir kredi değildir/, /Aktif güvenlik taraması açık kapsam/, /insan onayı gerektirir/, /dönüş sayfasının görüntülenmesi değil/, /anında silme komutu değildir/, /satıcı kimliği/, /yargı yetkisi/, /uygulanabilir yasal söz oluşturmaz/]
      : [/not an approved contract or an available offer/, /leave every active organization/, /an owner must first transfer ownership or deliberately close/, /collection permissions/, /not money or purchasable credits/, /Active security scanning requires explicit scope/, /require human approval/, /not a return-page view/, /not an immediate deletion command/, /seller identity/, /jurisdiction/, /enforceable legal promise/];
    for (const claim of claims) assert.match(main.textContent, claim);
    for (const [path, locale] of [['preview/terms', 'en'], ['preview/tr/terms', 'tr']]) assert.ok(main.querySelector(`a[href="/${path}"][lang="${locale}"]`));
    assert.equal(main.querySelector(`nav a[lang="${language}"]`).getAttribute('aria-current'), 'page');
    assert.ok(main.querySelector(`a[href="${language === 'tr' ? '/preview/tr/contact' : '/preview/contact'}"]`));
    assert.equal(main.querySelector('form, button, input, textarea, a[href="/terms"], a[href="/tr/kullanim-kosullari"], a[href="/account/register"], a[href^="mailto:"], a[href^="https://"]'), null);
    assert.match(document.title, language === 'tr' ? /Türkçe taslak/ : /Product terms and responsibilities/);
    assert.match(document.querySelector('meta[name="description"]').content, language === 'tr' ? /incelenmemiş Türkçe taslak/ : /unreviewed local draft/);
  }
  for (const path of ['terms', 'tr/kullanim-kosullari']) await assert.rejects(stat(new URL(`${path}/index.html`, browser)), { code: 'ENOENT' });
});
