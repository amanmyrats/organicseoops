import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, OnInit, computed, effect, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi, ApiResult } from '../account/account-api';
import { safeUrl, same } from './authority-links';
import { calendar, microseconds } from './utc-date';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Row = Record<string, unknown>;
type Job = { id: number; status: string; created_at: string; updated_at: string; cancel_requested: boolean; estimate_units: number; error_category: string };
type Scope = { actor: number; project: Row; configuration: Row };
type Preview = { selection: Row & { binding: Row }; selection_digest: string };
type SynthesisPreview = { selection: Row & { input: Row; configuration: Row }; selection_digest: string; comparison: Row };
type TopicSource = { job: Job; observation: Row };
type TopicPreview = { selection: SynthesisPreview['selection']; selection_digest: string; source: TopicSource };
type Pending = { data: Row; key: string; preview: Preview | SynthesisPreview | TopicPreview | null; jobId?: number; synthesis?: boolean; pair?: Pair; topic?: Job };
type Pair = { previous: Job; current: Job };
type Model = { id: number; provider_id: number; name: string; identifier: string; max_output_tokens: number | null; access_tier: string; price_known: boolean; privacy_policy_url: string };
type Account = { id: number; provider_id: number; label: string; source: string };
const SYNTHESIS_METHOD = 'competitor-static-synthesis-v1';
const SYNTHESIS_STATE = 'unverified_ai_interpretations_require_human_review';
const SYNTHESIS_MEANING = 'original_static_facts_separate_from_unverified_cited_ai_notes_not_approval_whole_site_or_causal_evidence';
const INPUT_FIELDS = ['previous_job_id', 'current_job_id', 'ai_processing_permission', 'model_id', 'account_id', 'max_output_tokens', 'max_cost_usd', 'allow_free'];
const TOPIC_INPUT_FIELDS = ['job_id', ...INPUT_FIELDS.slice(2)];
const TOPIC_SOURCE_MEANING = 'original_single_heading_sample_untrusted_ai_input_not_generated_topics_validated_page_topics_content_gaps_intent_freshness_whole_site_provider_or_approval_authority';
const TOPIC_STATE = 'unverified_heading_topic_hypotheses_require_human_review';
const TOPIC_MEANING = 'original_single_heading_facts_separate_from_unverified_cited_topic_hypotheses_not_semantic_truth_page_topics_gaps_intent_freshness_rankings_whole_site_or_approval';
const TOPIC_PAIR_MEANING = 'exact_original_unverified_ai_label_matches_and_unmatched_indices_not_semantic_shared_or_missing_page_topics_content_gaps_intent_freshness_rankings_whole_site_or_approval';
const DESTINATION_INVENTORY_MEANING = 'exact_stored_resolved_supported_destination_uris_in_two_selected_static_samples_not_complete_site_page_or_destination_inventory_fetched_targets_target_health_browser_visibility_indexing_inbound_links_topology_topics_freshness_causality_or_crawl_authority';
const CONFIG_FIELDS = ['provider_id', 'model_identifier', 'provider_kind', 'provider_base_url', 'model_revision', 'model_access_tier',
  'input_price_usd_per_million', 'output_price_usd_per_million', 'estimated_max_cost_usd', 'account_id', 'credential_revision', 'routing_source',
  'routing_policy_id', 'routing_policy_revision', 'fallback_index', 'timeout_seconds', 'method', 'organization_id', 'project_id', 'actor_id',
  'source_method', 'source_selection_digest', 'source_metadata_sha256', 'caller_source_sha256', 'model_selection_sha256', 'prompt_sha256', 'output_schema_sha256'];
const SYNTHESIS_ERRORS = ['invalid_credential', 'egress_denied', 'tls_verification_failed', 'invalid_request', 'malformed_response', 'refused',
  'incomplete_response', 'rate_limited', 'provider_unavailable', 'invalid_response'];
const LAB_METHOD = 'competitor-lighthouse-collect-v1';
const LAB_SOURCE_MEANING = 'current_selected_exact_uri_device_and_declared_google_processing_permission_not_ownership_legal_approval_key_network_commercial_or_observed_lab_authority';
const LAB_SELECTION_MEANING = 'current_source_and_credential_configuration_reference_not_key_validity_provider_access_quota_network_commercial_or_observed_lab_authority';
const LAB_COLLECTION_MEANING = 'one_original_selected_uri_device_provider_returned_lab_sample_not_field_data_current_site_whole_site_rankings_causality_or_live_provider_proof';
const LAB_PAIR_MEANING = 'original_same_uri_device_version_lab_sample_arithmetic_not_controlled_conditions_representative_benchmark_statistical_significance_field_p75_current_site_whole_site_rankings_or_causality';
const LAB_MEANING = 'provider_reported_lab_sample_not_field_p75_core_web_vitals_whole_site_rankings_causality_ownership_current_site_or_live_provider_proof';
const LAB_ERRORS = ['credential_unavailable', 'egress_denied', 'tls_verification_failed', 'quota_limited', 'redirect_denied', 'provider_unavailable', 'provider_request_rejected', 'malformed_response', 'lighthouse_invalid', 'lighthouse_failed'];
const LAB_SCORES = ['performance', 'accessibility', 'best-practices', 'seo'];
const LAB_UNITS: Record<string, string> = { 'largest-contentful-paint': 'ms', 'cumulative-layout-shift': 'unitless', 'total-blocking-time': 'ms', 'speed-index': 'ms' };
const METHOD = 'competitor-static-root-collect-v1';
const DESTINATIONS_METHOD = 'competitor-page-destinations-v1';
const FORMATS_METHOD = 'competitor-page-elements-collect-v1';
const FORMAT_COUNTS = ['p', 'ul', 'ol', 'table', 'img', 'picture', 'video', 'audio'];
const FORMATS_COMPARISON_MEANING = 'dated_selected_nonroot_uri_literal_start_tag_count_changes_not_rendered_formats_loaded_media_semantic_page_types_accessibility_search_features_topics_freshness_whole_site_causality_or_collection_authority';
const FORMATS_STRUCTURE_MEANING = 'two_selected_static_samples_literal_start_tag_counts_not_rendered_formats_loaded_media_semantic_page_types_search_features_accessibility_site_totals_whole_site_freshness_changes_causality_ai_or_collection_authority';
const FORMATS_MEANING = 'literal_start_tags_not_rendered_content_formats_page_types_loaded_media_accessibility_search_result_features_topics_freshness_or_whole_site';
const DATES_METHOD = 'competitor-page-dates-collect-v1';
const DATE_CANDIDATE_MEANING = 'stored_article_date_literal_syntax_candidates_not_validated_publication_change_age_freshness_cadence_page_identity_whole_site_causality_approval_ai_or_source_authority';
const DATE_CANDIDATE_PAIR_MEANING = 'all_same_property_original_declaration_index_pairs_calendar_or_utc_candidate_intervals_not_matched_events_validated_publication_change_age_freshness_cadence_page_identity_whole_site_causality_approval_ai_or_source_authority';
const HEADINGS_METHOD = 'competitor-page-headings-collect-v1';
const HEADINGS_STRUCTURE_MEANING = 'two_selected_static_samples_literal_heading_level_counts_with_original_text_order_truncation_not_rendered_semantic_outline_accessibility_topics_intent_page_identity_freshness_site_totals_whole_site_causality_ai_or_collection_authority';
const HEADING_COUNTS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'];
const PAGE_METHOD = 'competitor-static-page-collect-v1';
const LINKS_METHOD = 'competitor-static-root-links-collect-v1';
const LINK_COUNTS = ['href_anchors', 'same_origin_http', 'other_origin_http', 'unsupported'];
const SCHEMA_METHOD = 'competitor-static-schema-root-collect-v1';
const SCHEMA_TYPES = ['Article', 'NewsArticle', 'BlogPosting', 'WebPage', 'AboutPage', 'ContactPage', 'CollectionPage',
  'FAQPage', 'QAPage', 'Product', 'Service', 'Organization', 'LocalBusiness', 'BreadcrumbList', 'ItemList',
  'VideoObject', 'ImageObject', 'HowTo', 'Event', 'Recipe', 'Person'];
const SOURCE_MEANING = 'customer_selected_public_host_not_ownership_approval_time_network_commercial_or_observation_authority';
const PAGE_SOURCE_MEANING = 'customer_selected_exact_uri_not_page_identity_ownership_approval_time_network_commercial_or_observation_authority';
const COLLECTION_MEANING = 'one_selected_static_root_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks';
const PAGE_COLLECTION_MEANING = 'one_selected_static_nonroot_uri_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks';
const METADATA_MEANING = 'static_syntax_not_rendering_schema_validity_topics_publication_age_traffic_rankings_backlinks_or_whole_site';
const COMPARISON_MEANING = 'dated_selected_root_literal_changes_not_topics_publication_age_schema_validity_traffic_rankings_backlinks_whole_site_or_causality';
const DESTINATIONS_COMPARISON_MEANING = 'dated_selected_nonroot_uri_literal_supported_same_origin_reference_order_changes_not_unique_pages_fetched_targets_link_health_browser_visibility_freshness_whole_site_causality_or_crawl_authority';
const DATES_COMPARISON_MEANING = 'dated_selected_nonroot_uri_literal_article_date_declaration_order_changes_not_validated_dates_publication_change_age_freshness_cadence_page_identity_whole_site_or_causality';
const HEADINGS_COMPARISON_MEANING = 'dated_selected_nonroot_uri_literal_heading_text_order_changes_not_browser_semantic_outline_accessibility_topics_page_identity_freshness_whole_site_or_causality';
const PAGE_COMPARISON_MEANING = 'dated_selected_nonroot_uri_literal_changes_not_page_identity_topics_publication_age_freshness_schema_validity_traffic_rankings_backlinks_whole_site_or_causality';
const COUNTS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'href_anchors', 'json_ld_blocks'];
const EXCLUDED = ['iframe', 'math', 'noembed', 'noframes', 'noscript', 'plaintext', 'script', 'style', 'svg', 'template', 'textarea', 'xmp'];
const ERRORS = ['', 'invalid_url', 'outside_scope', 'invalid_scope', 'non_public_address', 'dns_error', 'timeout', 'network_error',
  'invalid_static_document', 'static_document_unavailable', 'resource_body_unavailable', 'invalid_content_length', 'response_too_large',
  'unsupported_content_encoding', 'invalid_content_encoding', 'incomplete_response_body', 'static_source_robots_denied', 'static_source_robots_unknown',
  'competitor_document_scope', 'competitor_document_deadline', 'competitor_document_http_status', 'competitor_document_result_limit',
  'competitor_document_invalid', 'competitor_document_failed', 'request_outcome_unknown', 'handler_failed', 'cancel_requested', 'source_scope_changed',
  'usage_unreserved', 'broker_unavailable', 'internal_capacity', 'trial_unavailable', 'trial_units_exhausted', 'paid_unavailable', 'billing_review_hold',
  'paid_period_changed', 'paid_units_exhausted', 'actor_revoked', 'unclassified_failure'];
const object = (value: unknown): value is Row => !!value && typeof value === 'object' && !Array.isArray(value);
const exact = (value: unknown, keys: string[]): value is Row => object(value) && same(Object.keys(value).sort(), [...keys].sort());
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const digest = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const dated = (value: unknown) => microseconds(value) !== null && microseconds(value)! <= BigInt(Date.now()) * 1000n;
const ordered = (before: unknown, after: unknown) => dated(before) && dated(after) && microseconds(before)! <= microseconds(after)!;
const originalDate = (value: unknown) => dated(value) && typeof value === 'string' && /\.\d{6}\+00:00$/.test(value);
// Preserve the provider's literal offset while comparing its instant at microsecond precision.
function providerDate(value: unknown): { instant: bigint; normalized: string } | null {
  if (typeof value !== 'string' || value.length > 48) return null;
  const match = /^(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):([0-5]\d):([0-5]\d)(?:\.(\d{1,6}))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
  if (!match || calendar(match[1]) === null) return null;
  const millis = Date.parse(value); if (!Number.isFinite(millis)) return null;
  const fraction = (match[5] || '').padEnd(6, '0');
  const zone = match[6] === 'Z' || match[6] === '-00:00' ? '+00:00' : match[6];
  return { instant: BigInt(millis) * 1000n + BigInt(Number(fraction) % 1000),
    normalized: `${match[1]}T${match[2]}:${match[3]}:${match[4]}${Number(fraction) ? '.' + fraction : ''}${zone}` };
}
function literalText(value: unknown, limit: number): value is string {
  // Match the source's Python str.split whitespace; preserve literal BOMs.
  return typeof value === 'string' && [...value].length <= limit
    && value === value.replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/gu, ' ').replace(/^ | $/g, '')
    && !/[\x00-\x1f\x7f\ud800-\udfff]/u.test(value);
}
function canonical(value: unknown): unknown {
  return Array.isArray(value) ? value.map(canonical) : object(value)
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
}
async function selectionDigest(value: unknown) {
  // This consumer uses collection._encode's UTF-8, ensure_ascii=False contract.
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(canonical(value))));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
}
function canonicalOrigin(value: unknown): value is string {
  if (typeof value !== 'string' || !value || value.length > 240 || /[\s\\?#\x00-\x1f\x7f]/.test(value)) return false;
  try {
    const url = new URL(value);
    return url.origin === value && url.href === value + '/' && !url.port && !url.username && !url.password
      && (url.protocol === 'https:' ? safeUrl(value) === value + '/' : url.protocol === 'http:');
  } catch { return false; }
}
function canonicalPageUrl(value: unknown, origin: string): value is string {
  if (typeof value !== 'string' || !value || value.length > 1024 || /[\s\\?#\x00-\x1f\x7f]/.test(value)) return false;
  try {
    const url = new URL(value);
    return canonicalOrigin(origin) && url.origin === origin && url.href === value && url.pathname !== '/'
      && !url.username && !url.password && !url.port
      && !/[\s\\\x00-\x1f\x7f]/.test(decodeURIComponent(value));
  } catch { return false; }
}


function literalReferenceUrl(value: unknown, origin: string): value is string {
  if (typeof value !== 'string' || value.length > 1024 || !canonicalOrigin(origin) || !value.startsWith(origin + '/')
    || !/^[a-zA-Z0-9/%:@\-._~!$&'()*+,;=]+$/.test(value.slice(origin.length)) || /%(?![a-f0-9]{2})/i.test(value)) return false;
  // Match Python unquote's replacement decoding without browser path repair.
  const decoded = value.replace(/(?:%[a-f0-9]{2})+/gi, part => new TextDecoder().decode(
    Uint8Array.from(part.match(/[a-f0-9]{2}/gi)!, byte => parseInt(byte, 16))));
  return !/[\x00-\x20\x7f\\\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u.test(decoded);
}

const competitorTurkish: Record<string, string> = {
  "Private selected competitor root observations": "Özel seçilen rakip kök gözlemleri",
  "Private selected competitor schema labels": "Özel seçilen rakip şema etiketleri",
  "Private selected competitor root link categories": "Özel seçilen rakip kök bağlantı kategorileri",
  "Private selected competitor page metadata": "Özel seçilen rakip sayfa meta verileri",
  "Private selected competitor page literal headings": "Özel seçilen rakip sayfanın sözcüğü sözcüğüne başlıkları",
  "Private single-heading topic hypotheses": "Özel tek başlık konu hipotezleri",
  "Private selected competitor page same-origin references": "Özel seçilen rakip sayfanın aynı kökenli referansları",
  "Private selected competitor page article date declarations": "Özel seçilen rakip sayfanın makale tarihi beyanları",
  "Private selected competitor static content-element counts": "Özel seçilen rakibin statik içerik öğesi sayıları",
  "Private selected competitor Lighthouse lab sample": "Özel seçilen rakibin Lighthouse laboratuvar örneği",
  "Selected competitor static content-element counts": "Seçilen rakibin statik içerik öğesi sayıları",
  "Topic hypotheses from one saved heading observation": "Kaydedilmiş tek başlık gözleminden konu hipotezleri",
  "Selected competitor Lighthouse lab sample": "Seçilen rakibin Lighthouse laboratuvar örneği",
  "Selected competitor page article date declarations": "Seçilen rakip sayfanın makale tarihi beyanları",
  "Selected competitor page same-origin references": "Seçilen rakip sayfanın aynı kökenli referansları",
  "Selected competitor page literal headings": "Seçilen rakip sayfanın sözcüğü sözcüğüne başlıkları",
  "Selected competitor page metadata": "Seçilen rakip sayfanın meta verileri",
  "Selected competitor root link categories": "Seçilen rakip kökün bağlantı kategorileri",
  "Selected competitor schema type labels": "Seçilen rakibin şema türü etiketleri",
  "Selected competitor root observations": "Seçilen rakip kökün gözlemleri",
  "Organization": "Kuruluş",
  "· project": "· proje",
  "Project evidence": "Proje kanıtları",
  "Edit saved competitors": "Kaydedilmiş rakipleri düzenleyin",
  "Separate metadata observations": "Ayrı meta veri gözlemleri",
  "Separate schema label observations": "Ayrı şema etiketi gözlemleri",
  "Separate link category observations": "Ayrı bağlantı kategorisi gözlemleri",
  "Separate selected page metadata": "Ayrı seçilen sayfa meta verileri",
  "Separate selected Lighthouse lab sample": "Ayrı seçilen Lighthouse laboratuvar örneği",
  "Separate selected page static content-element counts": "Ayrı seçilen sayfanın statik içerik öğesi sayıları",
  "Separate selected page article date declarations": "Ayrı seçilen sayfanın makale tarihi beyanları",
  "Separate selected page literal headings": "Ayrı seçilen sayfanın sözcüğü sözcüğüne başlıkları",
  "Separate selected page same-origin references": "Ayrı seçilen sayfanın aynı kökenli referansları",
  "Verified-account owner/admin only. Select one exact non-root competitor URI and mobile or desktop device. Robots checks and pacing precede a Google PageSpeed Insights request. No redirects, recursive crawl, login, automatic schedule or request replay.": "Yalnızca hesabı doğrulanmış sahip/yönetici. Kök olmayan tek bir tam rakip URI'si ve mobil veya masaüstü cihaz seçin. Google PageSpeed Insights isteğinden önce robots kontrolleri ve hız sınırlaması uygulanır. Yönlendirme, özyinelemeli tarama, oturum açma, otomatik zamanlama veya istek tekrarı yoktur.",
  "Four independent declarations are required; they do not verify legal permission. Google processes the selected URL. One internal operation unit is reserved; attempted or uncertain requests consume it. Google provider quota and charges are separate and unknown here. Configure the supported key in": "Dört bağımsız beyan gerekir; bunlar yasal izni doğrulamaz. Google seçilen URL'yi işler. Bir dahili işlem birimi ayrılır; denenmiş veya belirsiz istekler bunu tüketir. Google sağlayıcı kotası ve ücretleri ayrıdır ve burada bilinmez. Desteklenen anahtarı şurada yapılandırın:",
  "organization provider settings": "kuruluş sağlayıcı ayarları",
  ". Raw provider JSON, screenshots, field data and robots are not retained. A configured competitor is not owned or verified.": ". Ham sağlayıcı JSON'u, ekran görüntüleri, saha verileri ve robots saklanmaz. Yapılandırılmış rakip, sahip olunan veya doğrulanmış bir site değildir.",
  "Verified-account owner/admin only.": "Yalnızca hesabı doğrulanmış sahip/yönetici.",
  "One explicitly selected non-root URI within one saved competitor origin": "Kaydedilmiş tek rakip köken içinde açıkça seçilen, kök olmayan tek URI",
  "One saved competitor origin's root": "Kaydedilmiş tek rakip kökenin kökü",
  ", with robots policy, bounded static HTML and host pacing. No redirects, recursive crawl, rendering, login, automatic schedule or request replay. A configured competitor is not an owned alias or verified ownership.": ", robots politikası, sınırlı statik HTML ve sunucu hız sınırlaması ile. Yönlendirme, özyinelemeli tarama, oluşturma, oturum açma, otomatik zamanlama veya istek tekrarı yoktur. Yapılandırılmış rakip, sahip olunan takma alan adı veya doğrulanmış sahiplik değildir.",
  "Three independent declarations are required; they do not verify legal permission. One internal operation unit is reserved; attempted or uncertain collection consumes it, not a provider charge.": "Üç bağımsız beyan gerekir; bunlar yasal izni doğrulamaz. Bir dahili işlem birimi ayrılır; denenmiş veya belirsiz toplama bunu tüketir, sağlayıcı ücreti değildir.",
  "Raw HTML, robots, original href attributes, off-origin URLs, anchor text and schema bodies are not retained.": "Ham HTML, robots, özgün href öznitelikleri, köken dışı URL'ler, bağlantı metni ve şema gövdeleri saklanmaz.",
  "Raw HTML, robots, href inventories and schema bodies are not retained.": "Ham HTML, robots, href envanterleri ve şema gövdeleri saklanmaz.",
  "Minimized private evidence follows export/closure policy: 90-day retained access after lapse, active deletion within 30 days of closure/expiry, up to 35-day backup rotation after active deletion. Retained status history does not authorize new collection or current evidence use.": "En aza indirilmiş özel kanıt dışa aktarma/kapatma politikasına tabidir: erişim bittikten sonra 90 günlük saklanan erişim, kapatma/süre bitiminden sonraki 30 gün içinde aktif silme, aktif silmeden sonra en fazla 35 günlük yedek rotasyonu. Saklanan durum geçmişi yeni toplamaya veya güncel kanıt kullanımına yetki vermez.",
  "Checking current scope and private state.": "Güncel kapsam ve özel durum kontrol ediliyor.",
  "Refresh saved competitors and private history": "Kaydedilmiş rakipleri ve özel geçmişi yenileyin",
  "No eligible saved competitors. Configure a competitor separately; missing is not zero observations.": "Uygun kaydedilmiş rakip yok. Rakibi ayrı yapılandırın; eksiklik sıfır gözlem değildir.",
  "One exact selected competitor page URI": "Seçilen tek tam rakip sayfa URI'si",
  "One separately selected competitor root": "Ayrı seçilen tek rakip kökü",
  "Saved configured origin": "Kaydedilmiş yapılandırılmış köken",
  "Choose one saved competitor": "Kaydedilmiş tek rakip seçin",
  "Exact public page URL on this saved origin": "Bu kaydedilmiş kökendeki tam herkese açık sayfa URL'si",
  "Enter one full non-root HTTP or HTTPS URL on the exact selected scheme and host. No query, fragment, credentials or custom port.": "Tam seçilen şema ve sunucuda kök olmayan tek tam HTTP veya HTTPS URL'si girin. Sorgu, parça, kimlik bilgisi veya özel port olamaz.",
  "No root fallback or reference following.": "Köke geri dönüş veya referans takibi yoktur.",
  "No root fallback or destination discovery.": "Köke geri dönüş veya hedef keşfi yoktur.",
  "Lighthouse device": "Lighthouse cihazı",
  "Mobile": "Mobil",
  "Desktop": "Masaüstü",
  "I independently have permission for Google to process this exact competitor URL for a lab sample.": "Google'ın bu tam rakip URL'sini laboratuvar örneği için işlemesine bağımsız olarak izin sahibiyim.",
  "I have permission to collect this selected public": "Robots ve hız kısıtlamalarıyla bu seçilen herkese açık kaynağı toplama iznim var:",
  "page URI": "sayfa URI'si",
  "root": "kök",
  "with robots and pacing restrictions.": "; robots ve hız kısıtlamaları geçerlidir.",
  "I independently have permission to use these minimized": "Bu en aza indirilmiş verileri kullanma iznine bağımsız olarak sahibiyim:",
  "literal static content-element counts": "sözcüğü sözcüğüne statik içerik öğesi sayıları",
  "provider-reported Lighthouse lab values": "sağlayıcının bildirdiği Lighthouse laboratuvar değerleri",
  "literal article date declarations": "sözcüğü sözcüğüne makale tarihi beyanları",
  "same-origin static reference URLs and counts": "aynı kökenli statik referans URL'leri ve sayıları",
  "literal heading text and order": "sözcüğü sözcüğüne başlık metni ve sırası",
  "static link occurrence counts": "statik bağlantı oluşum sayıları",
  "schema type labels": "şema türü etiketleri",
  "static metadata": "statik meta veriler",
  "I independently have permission to retain this minimized private evidence under the stated lifecycle.": "Bu en aza indirilmiş özel kanıtı belirtilen yaşam döngüsü altında saklama iznine bağımsız olarak sahibiyim.",
  "Preview exact current source (no site request)": "Tam güncel kaynağı önizleyin (site isteği yok)",
  "Exact": "Tam",
  "· configuration revision": "· yapılandırma revizyonu",
  "· configured": "· yapılandırıldı",
  "(not approval or observation time).": "(onay veya gözlem zamanı değildir).",
  "Device": "Cihaz",
  ". Credential configuration reference is metadata only; it does not verify the key, access, quota or provider readiness.": ". Kimlik bilgisi yapılandırma referansı yalnızca meta veridir; anahtarı, erişimi, kotayı veya sağlayıcı hazırlığını doğrulamaz.",
  "Frozen selected source and canonical command digest": "Dondurulmuş seçilen kaynak ve kanonik komut özeti",
  "Reserve 1 unit and request": "1 birim ayırın ve isteyin:",
  "these exact selected page content-element counts": "bu tam seçilen sayfa içerik öğesi sayıları",
  "this exact URI/device lab sample": "bu tam URI/cihaz laboratuvar örneği",
  "these exact selected page date declarations": "bu tam seçilen sayfa tarihi beyanları",
  "these exact selected page references": "bu tam seçilen sayfa referansları",
  "these exact selected page headings": "bu tam seçilen sayfa başlıkları",
  "this exact selected page": "bu tam seçilen sayfa",
  "these selected link categories": "bu seçilen bağlantı kategorileri",
  "these selected schema labels": "bu seçilen şema etiketleri",
  "this selected root": "bu seçilen kök",
  "Command outcome uncertain. The original source, declarations, command fields, preview and same request key are frozen only in this page's memory. No automatic POST replay; another actor's job cannot reconcile this request.": "Komut sonucu belirsiz. Özgün kaynak, beyanlar, komut alanları, önizleme ve aynı istek anahtarı yalnızca bu sayfanın belleğinde dondurulur. Otomatik POST tekrarı yoktur; başka aktörün işi bu isteği uzlaştıramaz.",
  "Look up the exact original command (GET only)": "Tam özgün komutu arayın (yalnızca GET)",
  "Discard local uncertainty; a saved job may exist": "Yerel belirsizliği atın; kaydedilmiş iş bulunabilir",
  "Private retained job status": "Saklanan özel iş durumu",
  "No retained": "Saklanan iş yok:",
  "competitor-page": "rakip sayfa",
  "link root": "bağlantı kökü",
  "schema root": "şema kökü",
  "competitor-root": "rakip kök",
  "jobs. Uncollected or unavailable is not a clean result.": "işleri. Toplanmamış veya kullanılamayan veri temiz sonuç değildir.",
  "Only the latest 20 jobs are shown.": "Yalnızca son 20 iş gösterilir.",
  "Job": "İş",
  "· created": "· oluşturuldu",
  "· updated": "· güncellendi",
  "Inspect exact private job": "Tam özel işi inceleyin",
  "Inspect saved date syntax candidates": "Kaydedilmiş tarih sözdizimi adaylarını inceleyin",
  "Request cancellation": "İptal isteyin",
  "These are bounded literal start-tag counts for paragraphs, lists, tables, image/picture, video and audio elements in one returned static document. They retain original date and byte provenance; duplicate and self-closing start tags count. CSS-hidden syntax may count. Attributes, text and media URLs are not retained. Observed zero differs from whole-null unavailable counts, including inherited parser limits.": "Bunlar döndürülen tek statik belgedeki paragraf, liste, tablo, img/picture, video ve audio öğeleri için sınırlı sözcüğü sözcüğüne başlangıç etiketi sayılarıdır. Özgün tarih ve bayt kökenini korurlar; yinelenen ve kendiliğinden kapanan başlangıç etiketleri sayılır. CSS ile gizli sözdizimi sayılabilir. Öznitelikler, metin ve medya URL'leri saklanmaz. Gözlenen sıfır, devralınan ayrıştırıcı sınırları dahil, tümü null olan kullanılamayan sayılardan farklıdır.",
  "Counts do not establish rendered content formats, page types, loaded media, accessibility, search result features, topics, freshness or whole-site coverage. Saved-pair differences describe literal counts only. AI processing is unavailable for this family.": "Sayılar oluşturulmuş içerik biçimlerini, sayfa türlerini, yüklenmiş medyayı, erişilebilirliği, arama sonucu özelliklerini, konuları, güncelliği veya tüm site kapsamını kanıtlamaz. Kaydedilmiş çift farkları yalnızca sözcüğü sözcüğüne sayıları açıklar. Bu ailede AI işleme kullanılamaz.",
  "Compare two saved original": "Kaydedilmiş iki özgün gözlemi karşılaştırın:",
  "static content-element counts": "statik içerik öğesi sayıları",
  "Lighthouse lab samples": "Lighthouse laboratuvar örnekleri",
  "page date declarations": "sayfa tarihi beyanları",
  "page references": "sayfa referansları",
  "page headings": "sayfa başlıkları",
  "observations (GET only)": "gözlemleri (yalnızca GET)",
  "Saved Date comparison mode": "Kaydedilmiş tarih karşılaştırma modu",
  "Original declaration text changes": "Özgün beyan metni değişiklikleri",
  "Syntax candidate intervals between all same-property declarations": "Aynı özellikteki tüm beyanlar arasında sözdizimi adayı aralıkları",
  "Saved": "Kaydedilmiş",
  "heading count": "başlık sayısı",
  "element count": "öğe sayısı",
  "reference": "referans",
  "inspection mode": "inceleme modu",
  "Compare earlier and later samples of the same page": "Aynı sayfanın önceki ve sonraki örneklerini karşılaştırın",
  "Inspect literal counts in two different saved pages": "Kaydedilmiş iki farklı sayfadaki sözcüğü sözcüğüne sayıları inceleyin",
  "Inspect references between two different saved pages": "Kaydedilmiş iki farklı sayfa arasındaki referansları inceleyin",
  "Inspect stored resolved destination URIs across two samples": "İki örnekte saklanan çözümlenmiş hedef URI'lerini inceleyin",
  "Choose two succeeded saved": "Başarılı kaydedilmiş iki iş seçin:",
  "jobs for different exact page URIs on one origin. Counts follow the selected first/second order; dates need not increase. Each original static sample retains its own provenance.": "tek kökende farklı tam sayfa URI'leri için işler. Sayılar seçilen birinci/ikinci sırasını izler; tarihler artmak zorunda değildir. Her özgün statik örnek kendi kökenini korur.",
  "Choose an earlier and later succeeded job from this retained list. Only the exact same original source, actor provenance,": "Bu saklanan listeden önceki ve sonraki başarılı işi seçin. Yalnızca tamamen aynı özgün kaynak, aktör kökeni,",
  "selected URI": "seçilen URI",
  "and methods can be compared.": "ve yöntemler karşılaştırılabilir.",
  "The original device and known Lighthouse version must match for arithmetic; provider report times must increase. Same device/version does not establish controlled run conditions.": "Aritmetik için özgün cihaz ve bilinen Lighthouse sürümü eşleşmelidir; sağlayıcı rapor zamanları artmalıdır. Aynı cihaz/sürüm kontrollü çalışma koşullarını kanıtlamaz.",
  "First": "Birinci",
  "Earlier": "Önceki",
  "saved job": "kaydedilmiş iş",
  "Choose": "Seçin:",
  "first": "birinci",
  "earlier": "önceki",
  "observation": "gözlem",
  "Second": "İkinci",
  "Later": "Sonraki",
  "second": "ikinci",
  "later": "sonraki",
  "Read this exact frozen pair": "Bu tam dondurulmuş çifti okuyun",
  "Stored resolved destinations across two saved static samples": "Kaydedilmiş iki statik örnekte saklanan çözümlenmiş hedefler",
  "Literal heading-level counts in two saved static samples": "Kaydedilmiş iki statik örnekte sözcüğü sözcüğüne başlık düzeyi sayıları",
  "Literal element counts in two saved static samples": "Kaydedilmiş iki statik örnekte sözcüğü sözcüğüne öğe sayıları",
  "Reference occurrences between two saved static samples": "Kaydedilmiş iki statik örnek arasındaki referans oluşumları",
  "Original dated selected-": "Özgün tarihli seçilen-",
  "Lighthouse lab sample": "Lighthouse laboratuvar örneği",
  "comparison": "karşılaştırması",
  "Destination strings are the exact stored resolved URI representation from the original collector, not raw HTML href spellings. Columns follow their first occurrence across the two selected samples; each observed row counts original duplicate references. An unavailable entire row is null even when the known URI list is empty, and may hide unknown destinations. All rows observed reports only these two source states, not complete page, site or destination coverage. Original order, dates and provenance stay separate. No target fetch or health, browser visibility, indexing, inbound links, whole-site topology, topics, freshness, causality or authority to crawl is established.": "Hedef dizeleri, ham HTML href yazımları değil, özgün toplayıcıdan saklanan tam çözümlenmiş URI gösterimidir. Sütunlar seçilen iki örnekteki ilk oluşumu izler; gözlenen her satır özgün yinelenen referansları sayar. Bilinen URI listesi boşken bile kullanılamayan tüm satır null olur ve bilinmeyen hedefleri gizleyebilir. Tüm satırların gözlenmesi, tam sayfa, site veya hedef kapsamını değil, yalnızca bu iki kaynak durumunu bildirir. Özgün sıra, tarihler ve köken ayrı kalır. Hedef getirme veya sağlığı, tarayıcı görünürlüğü, dizine ekleme, gelen bağlantılar, tüm site topolojisi, konular, güncellik, nedensellik veya tarama yetkisi kanıtlanmaz.",
  "Two saved-page literal heading counts": "Kaydedilmiş iki sayfanın sözcüğü sözcüğüne başlık sayıları",
  "Two saved-page literal element counts": "Kaydedilmiş iki sayfanın sözcüğü sözcüğüne öğe sayıları",
  "Literal heading-level counts": "Sözcüğü sözcüğüne başlık düzeyi sayıları",
  "Literal start-tag counts": "Sözcüğü sözcüğüne başlangıç etiketi sayıları",
  "in these two saved pages": "bu kaydedilmiş iki sayfada",
  "Saved sample": "Kaydedilmiş örnek",
  "sample": "örnek",
  "Unavailable": "Kullanılamıyor",
  "Each original heading list, duplicate text, order and truncation flag is retained. Text truncation does not erase known literal level counts. Zero is observed; an unavailable whole row stays unknown. All rows observed describes only these two static sample states. These counts do not establish a rendered or semantic outline, accessibility, topics, intent, page identity, freshness, site totals, whole-site coverage or causality. This matrix cannot authorize AI processing; dated same-page synthesis is separate.": "Her özgün başlık listesi, yinelenen metin, sıra ve kesilme bayrağı korunur. Metin kesilmesi bilinen sözcüğü sözcüğüne düzey sayılarını silmez. Sıfır gözlenmiştir; kullanılamayan tüm satır bilinmeyen kalır. Tüm satırların gözlenmesi yalnızca bu iki statik örnek durumunu açıklar. Bu sayılar oluşturulmuş veya anlamsal taslağı, erişilebilirliği, konuları, niyeti, sayfa kimliğini, güncelliği, site toplamlarını, tüm site kapsamını veya nedenselliği kanıtlamaz. Bu matris AI işlemeye yetki veremez; tarihli aynı sayfa sentezi ayrıdır.",
  "Rows retain each original selected URI, date, byte digest/size and opaque collector-bound source. Zero is observed; an unavailable whole row stays unknown. All rows observed describes only these two static samples. The counts are literal syntax, without chronological changes or site totals. They do not establish rendered formats, loaded media, semantic page types, search features, accessibility, freshness, whole-site coverage or causality. AI processing remains unavailable.": "Satırlar her özgün seçilen URI'yi, tarihi, bayt özetini/boyutunu ve opak toplayıcıya bağlı kaynağı korur. Sıfır gözlenmiştir; kullanılamayan tüm satır bilinmeyen kalır. Tüm satırların gözlenmesi yalnızca bu iki statik örneği açıklar. Sayılar kronolojik değişiklikler veya site toplamları olmadan sözcüğü sözcüğüne sözdizimidir. Oluşturulmuş biçimleri, yüklenmiş medyayı, anlamsal sayfa türlerini, arama özelliklerini, erişilebilirliği, güncelliği, tüm site kapsamını veya nedenselliği kanıtlamazlar. AI işleme kullanılamaz.",
  "Rows are the first and second original samples; columns are their exact selected URIs. Counts retain duplicate occurrences without URL normalization. Zero means no exact reference in that returned static sample; unavailable rows stay null. Original order, dates, coverage and opaque actor-bound source SHAs are preserved. This is not unique pages, fetched target health, browser visibility, indexing, inbound links, whole-site topology, topics, freshness, causality or authority to crawl a target.": "Satırlar birinci ve ikinci özgün örneklerdir; sütunlar tam seçilen URI'leridir. Sayılar URL normalleştirmesi olmadan yinelenen oluşumları korur. Sıfır, döndürülen bu statik örnekte tam referans bulunmadığı anlamına gelir; kullanılamayan satırlar null kalır. Özgün sıra, tarihler, kapsam ve aktöre bağlı opak kaynak SHA'ları korunur. Bunlar benzersiz sayfalar, getirilen hedef sağlığı, tarayıcı görünürlüğü, dizine ekleme, gelen bağlantılar, tüm site topolojisi, konular, güncellik, nedensellik veya hedef tarama yetkisi değildir.",
  "Both original dates, body digests/sizes, coverage and literal start-tag counts are preserved. Differences are later minus earlier for the eight selected elements. Observed zero remains known; unavailable evidence has whole-null differences. Body change means returned bytes only. Counts do not establish rendered formats, loaded media, semantic page types, accessibility, search features, topics, freshness, whole-site changes, causality or collection permission. The original actor-bound source SHA is opaque to an independent reader. AI processing remains unavailable.": "Her iki özgün tarih, gövde özeti/boyutu, kapsam ve sözcüğü sözcüğüne başlangıç etiketi sayıları korunur. Farklar seçilen sekiz öğe için sonraki eksi öncekidir. Gözlenen sıfır bilinen kalır; kullanılamayan kanıtın farkları tümü null olur. Gövde değişikliği yalnızca döndürülen baytları ifade eder. Sayılar oluşturulmuş biçimleri, yüklenmiş medyayı, anlamsal sayfa türlerini, erişilebilirliği, arama özelliklerini, konuları, güncelliği, tüm site değişikliklerini, nedenselliği veya toplama iznini kanıtlamaz. Özgün aktöre bağlı kaynak SHA'sı bağımsız okuyucuya opaktır. AI işleme kullanılamaz.",
  "Both original samples preserve request start, local receipt, raw provider-reported time, response digest/size and version. Differences are later minus earlier nullable scores and normative lab metric units; missing is not zero. Incompatible runtime, unknown/changed version or nonincreasing provider timestamps retain original samples with null differences. Provider bytes changed does not establish a site change.": "Her iki özgün örnek istek başlangıcını, yerel alımı, sağlayıcının bildirdiği ham zamanı, yanıt özetini/boyutunu ve sürümü korur. Farklar, nullable puanlar ve normatif laboratuvar metrik birimleri için sonraki eksi öncekidir; eksiklik sıfır değildir. Uyumsuz çalışma, bilinmeyen/değişen sürüm veya artmayan sağlayıcı zaman damgaları özgün örnekleri null farklarla korur. Sağlayıcı baytlarının değişmesi site değişikliğini kanıtlamaz.",
  "Arithmetic between two samples is not a controlled or representative benchmark, statistical significance, field p75 Core Web Vitals, current whole-site measurements, rankings or causality. Separate runs can vary without code changes. No aggregate or grade is generated; AI synthesis remains unavailable.": "İki örnek arasındaki aritmetik, kontrollü veya temsili kıyaslama, istatistiksel anlamlılık, saha p75 Core Web Vitals, güncel tüm site ölçümleri, sıralamalar veya nedensellik değildir. Ayrı çalışmalar kod değişikliği olmadan değişebilir. Toplam veya not üretilmez; AI sentezi kullanılamaz.",
  "Each row compares a previous and current declaration index with the same exact property. All combinations and duplicates are retained; these are not matched actual publishing events. Calendar candidates yield signed calendar-day differences and known-offset candidates exact signed UTC microseconds. Mixed, unsupported or truncated candidates stay unavailable. A wholly unavailable declaration side makes all rows unknown; observed empty stays empty. These intervals do not establish publication/update cadence, age, freshness, page identity, whole-site changes or causality.": "Her satır aynı tam özelliğe sahip önceki ve güncel beyan indeksini karşılaştırır. Tüm kombinasyonlar ve yinelenenler korunur; bunlar eşleşmiş gerçek yayın olayları değildir. Takvim adayları işaretli takvim günü farkları, bilinen saat farkı adayları tam işaretli UTC mikrosaniyeleri verir. Karma, desteklenmeyen veya kesilmiş adaylar kullanılamaz kalır. Tamamen kullanılamayan bir beyan tarafı tüm satırları bilinmeyen yapar; gözlenen boş durum boş kalır. Bu aralıklar yayın/güncelleme sıklığını, yaşı, güncelliği, sayfa kimliğini, tüm site değişikliklerini veya nedenselliği kanıtlamaz.",
  "Original declaration pairs unavailable; intervals unknown.": "Özgün beyan çiftleri kullanılamıyor; aralıklar bilinmiyor.",
  "Stored Date candidate interval table": "Saklanan tarih adayı aralık tablosu",
  "All same-property original declaration index combinations; current minus previous": "Aynı özellikteki tüm özgün beyan indeksi kombinasyonları; güncel eksi önceki",
  "Previous index (from zero)": "Önceki indeks (sıfırdan)",
  "Current index (from zero)": "Güncel indeks (sıfırdan)",
  "Candidate state": "Aday durumu",
  "Calendar days": "Takvim günleri",
  "UTC microseconds": "UTC mikrosaniyeleri",
  "Both original observation times, body digests/sizes and ordered duplicate-preserving article date declarations are preserved. Exact untruncated property-value order equality describes literal text only. Observed empty and empty values remain known; unavailable or truncated declarations have null differences. Body change means returned bytes only. Declared text is not validated publication or change time, age, freshness, publishing cadence, page identity, whole-site evidence or causality. The original actor-bound source SHA is opaque to an independent reader. AI processing remains unavailable.": "Her iki özgün gözlem zamanı, gövde özeti/boyutu ve sıralı yinelenenleri koruyan makale tarihi beyanları korunur. Tam kesilmemiş özellik-değer sıra eşitliği yalnızca sözcüğü sözcüğüne metni açıklar. Gözlenen boş durum ve boş değerler bilinen kalır; kullanılamayan veya kesilmiş beyanların farkları null olur. Gövde değişikliği yalnızca döndürülen baytları ifade eder. Beyan metni doğrulanmış yayın veya değişim zamanı, yaş, güncellik, yayın sıklığı, sayfa kimliği, tüm site kanıtı veya nedensellik değildir. Özgün aktöre bağlı kaynak SHA'sı bağımsız okuyucuya opaktır. AI işleme kullanılamaz.",
  "Both original dates, body digests/sizes and ordered duplicate-preserving same-origin references are preserved. Exact literal URL order equality and later-minus-earlier four category counts describe static references only. An observed empty supported list can retain nonzero other-origin or unsupported counts; whole unavailable evidence has null differences. Body change means returned bytes only. No unique pages, fetched targets, link health, browser visibility, freshness, whole-site changes, causality or target crawling authority is established. The original actor-bound source SHA is opaque to an independent reader.": "Her iki özgün tarih, gövde özeti/boyutu ve sıralı yinelenenleri koruyan aynı kökenli referanslar korunur. Tam sözcüğü sözcüğüne URL sıra eşitliği ve sonraki eksi önceki dört kategori sayısı yalnızca statik referansları açıklar. Gözlenen boş desteklenen liste sıfır olmayan diğer köken veya desteklenmeyen sayıları koruyabilir; tümü kullanılamayan kanıtın farkları null olur. Gövde değişikliği yalnızca döndürülen baytları ifade eder. Benzersiz sayfalar, getirilen hedefler, bağlantı sağlığı, tarayıcı görünürlüğü, güncellik, tüm site değişiklikleri, nedensellik veya hedef tarama yetkisi kanıtlanmaz. Özgün aktöre bağlı kaynak SHA'sı bağımsız okuyucuya opaktır.",
  "Both original dates, body digests/sizes and ordered literal heading occurrences are preserved. Exact untruncated heading text/level/order equality and later-minus-earlier six counts describe static syntax only. Observed empty remains empty/zero; unavailable or truncated heading text has null differences. Body change means returned bytes only, not browser visibility, semantic outline, accessibility correctness, topics, page identity, freshness, whole-site changes or causality. The original actor-bound source SHA is opaque to an independent reader.": "Her iki özgün tarih, gövde özeti/boyutu ve sıralı sözcüğü sözcüğüne başlık oluşumları korunur. Tam kesilmemiş başlık metni/düzeyi/sıra eşitliği ve sonraki eksi önceki altı sayı yalnızca statik sözdizimini açıklar. Gözlenen boş durum boş/sıfır kalır; kullanılamayan veya kesilmiş başlık metninin farkları null olur. Gövde değişikliği yalnızca döndürülen baytları ifade eder; tarayıcı görünürlüğü, anlamsal taslak, erişilebilirlik doğruluğu, konular, sayfa kimliği, güncellik, tüm site değişiklikleri veya nedensellik değildir. Özgün aktöre bağlı kaynak SHA'sı bağımsız okuyucuya opaktır.",
  "Both original dates, body digests/sizes and literal reference-category counts are preserved. Differences are later minus earlier counts, with observed empty as zero and unavailable evidence as null. No destination URLs, unique pages, browser visibility, link health, inbound links, whole-site structure, freshness or causality are established. Body change means returned bytes changed only. The original actor-bound source SHA is opaque to an independent reader.": "Her iki özgün tarih, gövde özeti/boyutu ve sözcüğü sözcüğüne referans kategorisi sayıları korunur. Farklar sonraki eksi önceki sayılardır; gözlenen boş durum sıfır, kullanılamayan kanıt null olur. Hedef URL'ler, benzersiz sayfalar, tarayıcı görünürlüğü, bağlantı sağlığı, gelen bağlantılar, tüm site yapısı, güncellik veya nedensellik kanıtlanmaz. Gövde değişikliği yalnızca döndürülen baytların değişmesini ifade eder. Özgün aktöre bağlı kaynak SHA'sı bağımsız okuyucuya opaktır.",
  "Both original dates, body digests/sizes and lexical JSON-LD labels are preserved. Added/removed labels and later-minus-earlier counts describe declarations only, not resolved schema validity, actual page type, rich results, topics, freshness or whole-site changes. Unavailable evidence has null differences; an observed empty set remains empty/zero. Original actor-bound source SHA is opaque to an independent reader. Body change means returned bytes changed only.": "Her iki özgün tarih, gövde özeti/boyutu ve sözcüksel JSON-LD etiketleri korunur. Eklenen/çıkarılan etiketler ve sonraki eksi önceki sayılar yalnızca beyanları açıklar; çözümlenmiş şema geçerliliği, gerçek sayfa türü, zengin sonuçlar, konular, güncellik veya tüm site değişiklikleri değildir. Kullanılamayan kanıtın farkları null olur; gözlenen boş küme boş/sıfır kalır. Özgün aktöre bağlı kaynak SHA'sı bağımsız okuyucuya opaktır. Gövde değişikliği yalnızca döndürülen baytların değişmesini ifade eder.",
  "Both original UTC microseconds, body digests/sizes and literal metadata are preserved. Body change means returned bytes changed only. Differences are later minus earlier selected lexical counts and literal title/description equality, not topics, publication age, schema validity, whole-site coverage, traffic, rankings, backlinks or causality. Unavailable or truncated metadata is incomparable with null differences; observed empty is comparable. The original actor-bound source SHA is opaque, not the independent reader's digest.": "Her iki özgün UTC mikrosaniyesi, gövde özeti/boyutu ve sözcüğü sözcüğüne meta veriler korunur. Gövde değişikliği yalnızca döndürülen baytların değişmesini ifade eder. Farklar sonraki eksi önceki seçilen sözcüksel sayılar ve sözcüğü sözcüğüne başlık/açıklama eşitliğidir; konular, yayın yaşı, şema geçerliliği, tüm site kapsamı, trafik, sıralamalar, geri bağlantılar veya nedensellik değildir. Kullanılamayan veya kesilmiş meta veriler null farklarla karşılaştırılamaz; gözlenen boş durum karşılaştırılabilir. Özgün aktöre bağlı kaynak SHA'sı opaktır; bağımsız okuyucunun özeti değildir.",
  "The same selected URI does not establish page identity, publication or update time, freshness or whole-site changes.": "Aynı seçilen URI sayfa kimliğini, yayın veya güncelleme zamanını, güncelliği veya tüm site değişikliklerini kanıtlamaz.",
  "Unverified topic hypotheses from one original sample": "Tek özgün örnekten doğrulanmamış konu hipotezleri",
  "Private AI interpretations of an original saved pair": "Özgün kaydedilmiş çiftin özel AI yorumları",
  "Choose one retained observation for a first heading-topic hypothesis. Indexed quote matches do not verify a topic label, page topics, content gaps, intent, freshness, rankings, whole-page/site coverage or approval. Human review is required.": "İlk başlık-konu hipotezi için saklanan tek gözlem seçin. İndeksli alıntı eşleşmeleri konu etiketini, sayfa konularını, içerik boşluklarını, niyeti, güncelliği, sıralamaları, tüm sayfa/site kapsamını veya onayı doğrulamaz. İnsan incelemesi gerekir.",
  "Interpretations concern only retained literal heading text. They do not establish verified page topics, content gaps, semantic outline, freshness or whole-site coverage; human review is required.": "Yorumlar yalnızca saklanan sözcüğü sözcüğüne başlık metnine ilişkindir. Doğrulanmış sayfa konularını, içerik boşluklarını, anlamsal taslağı, güncelliği veya tüm site kapsamını kanıtlamazlar; insan incelemesi gerekir.",
  "Separately permit AI processing of": "AI işlemeye ayrı izin verin:",
  "one selected saved job": "seçilen tek kaydedilmiş iş",
  "the two selected saved jobs": "seçilen iki kaydedilmiş iş",
  ". This sends only minimized original facts to the selected provider, never a new site request. The text-model catalog is not proof of reasoning, structured output, context, price or provider readiness; the exact server preview checks eligibility. One internal AI unit is reserved; a committed attempt consumes it even if the result is unknown. No retry, schedule, fallback or automatic replay.": ". Bu, seçilen sağlayıcıya yalnızca en aza indirilmiş özgün gerçekleri gönderir; yeni site isteği göndermez. Metin modeli kataloğu akıl yürütme, yapılandırılmış çıktı, bağlam, fiyat veya sağlayıcı hazırlığı kanıtı değildir; tam sunucu önizlemesi uygunluğu kontrol eder. Bir dahili AI birimi ayrılır; sonuç bilinmese bile kesinleşen deneme bunu tüketir. Yeniden deneme, zamanlama, yedek sağlayıcı veya otomatik tekrar yoktur.",
  "Refresh synthesis history and model choices": "Sentez geçmişini ve model seçeneklerini yenileyin",
  "No current model/account choices. Retained status and cancellation remain separate from source/model availability.": "Güncel model/hesap seçeneği yok. Saklanan durum ve iptal, kaynak/model kullanılabilirliğinden ayrı kalır.",
  "Explicit single-observation topic command": "Açık tek gözlem konu komutu",
  "Explicit original-pair AI command": "Açık özgün çift AI komutu",
  "Original saved heading observation": "Özgün kaydedilmiş başlık gözlemi",
  "Choose one saved observation": "Kaydedilmiş tek gözlem seçin",
  "Earlier job": "Önceki iş",
  "not selected": "seçilmedi",
  "· later job": "· sonraki iş",
  ". Choose both using the saved-job controls above.": ". İkisini yukarıdaki kaydedilmiş iş kontrolleriyle seçin.",
  "I separately have permission for AI processing of": "AI işleme için ayrı iznim var:",
  "this minimized original observation": "bu en aza indirilmiş özgün gözlem",
  "this minimized original pair": "bu en aza indirilmiş özgün çift",
  "under the selected provider's policy.": "; seçilen sağlayıcının politikasına tabidir.",
  "Explicit model (eligibility checked by preview)": "Açık model (uygunluk önizlemeyle kontrol edilir)",
  "Choose model": "Model seçin",
  "Matching provider account": "Eşleşen sağlayıcı hesabı",
  "Choose account": "Hesap seçin",
  "Free-tier data retention/training/reliability differ. Review the": "Ücretsiz katmanda veri saklama/eğitim/güvenilirlik farklıdır. Şunu inceleyin:",
  "provider policy": "sağlayıcı politikası",
  "I explicitly opt in to free-tier processing for this request.": "Bu istek için ücretsiz katman işlemeye açıkça izin veriyorum.",
  "Maximum output tokens (128–2048)": "En fazla çıktı token sayısı (128–2048)",
  "Maximum estimated USD (greater than zero, up to 100)": "En fazla tahmini USD (sıfırdan büyük, en fazla 100)",
  "Preview exact original": "Tam özgün kaynağı önizleyin:",
  "pair": "çift",
  "and model budget (no provider request)": "ve model bütçesi (sağlayıcı isteği yok)",
  "Maximum operator-price estimate USD": "En yüksek operatör fiyatı tahmini USD",
  "; this is not a charge or guaranteed provider cost.": "; bu ücret veya garantili sağlayıcı maliyeti değildir.",
  "Frozen original AI command and canonical digest": "Dondurulmuş özgün AI komutu ve kanonik özet",
  "Reserve 1 AI unit and request this exact synthesis": "1 AI birimi ayırın ve bu tam sentezi isteyin",
  "Frozen original topic command and canonical digest": "Dondurulmuş özgün konu komutu ve kanonik özet",
  "Reserve 1 AI unit and request these unverified topic hypotheses": "1 AI birimi ayırın ve bu doğrulanmamış konu hipotezlerini isteyin",
  "No retained synthesis jobs; missing notes or metering are unknown, not zero.": "Saklanan sentez işi yok; eksik notlar veya ölçümler bilinmeyendir, sıfır değildir.",
  "Only the latest 20 synthesis jobs are shown.": "Yalnızca son 20 sentez işi gösterilir.",
  "Synthesis job": "Sentez işi",
  "Inspect original synthesis job": "Özgün sentez işini inceleyin",
  "Request synthesis cancellation": "Sentez iptali isteyin",
  "Compare two saved topic-hypothesis results": "Kaydedilmiş iki konu hipotezi sonucunu karşılaştırın",
  "Choose results for two different original page URIs on the same origin. This reads saved results and makes no new AI or site request.": "Aynı kökende farklı iki özgün sayfa URI'si için sonuç seçin. Bu, kaydedilmiş sonuçları okur; yeni AI veya site isteği yapmaz.",
  "Two original unverified samples": "İki özgün doğrulanmamış örnek",
  "First saved topic result": "Birinci kaydedilmiş konu sonucu",
  "Choose first result": "Birinci sonucu seçin",
  "Second saved topic result": "İkinci kaydedilmiş konu sonucu",
  "Choose second result": "İkinci sonucu seçin",
  "Read exact original label matches": "Tam özgün etiket eşleşmelerini okuyun",
  "Literal matches between unverified AI labels — human review required": "Doğrulanmamış AI etiketleri arasındaki sözcüğü sözcüğüne eşleşmeler — insan incelemesi gerekir",
  "Index pairs refer to the first and second original topic lists, starting at zero. Duplicates, case and Unicode spelling are retained. Unmatched indices mean only no identical label in the other returned sample; they do not establish shared or missing actual topics, content gaps, intent, freshness, rankings, whole-page/site coverage or approval. Original heading quotes, collection dates, generation dates and configured model/account provenance remain separate.": "İndeks çiftleri sıfırdan başlayan birinci ve ikinci özgün konu listelerine başvurur. Yinelenenler, büyük/küçük harf ve Unicode yazımı korunur. Eşleşmeyen indeksler yalnızca diğer döndürülen örnekte aynı etiket bulunmadığını ifade eder; ortak veya eksik gerçek konuları, içerik boşluklarını, niyeti, güncelliği, sıralamaları, tüm sayfa/site kapsamını veya onayı kanıtlamaz. Özgün başlık alıntıları, toplama tarihleri, üretim tarihleri ve yapılandırılmış model/hesap kökeni ayrı kalır.",
  "Latest synthesis command status: job": "Son sentez komut durumu: iş",
  ". Inspect evidence separately.": ". Kanıtı ayrı inceleyin.",
  "Original saved AI command and separate nullable provider observations": "Özgün kaydedilmiş AI komutu ve ayrı nullable sağlayıcı gözlemleri",
  "Attempt/finish times and nullable tokens/duration/estimated or separately reported USD are local provider observations, not original source dates, invoices, customer charges or approval.": "Deneme/bitiş zamanları ve nullable token/süre/tahmini veya ayrıca bildirilen USD, yerel sağlayıcı gözlemleridir; özgün kaynak tarihleri, faturalar, müşteri ücretleri veya onay değildir.",
  "Original deterministic static facts": "Özgün deterministik statik gerçekler",
  "Unverified indexed topic hypotheses — human review required": "Doğrulanmamış indeksli konu hipotezleri — insan incelemesi gerekir",
  "Unverified cited AI interpretations — human review required": "Doğrulanmamış atıflı AI yorumları — insan incelemesi gerekir",
  "Generated": "Üretildi",
  ". Exact reference syntax does not prove semantic truth, usefulness or human approval. Selected model/account are configured/requested, not proof of actual provider behavior or live readiness. No publication or remediation is approved.": ". Tam referans sözdizimi anlamsal doğruluğu, yararlılığı veya insan onayını kanıtlamaz. Seçilen model/hesap yapılandırılmış/istenmiştir; gerçek sağlayıcı davranışı veya canlı hazırlık kanıtı değildir. Yayın veya düzeltme onaylanmaz.",
  "No current private synthesis; missing, failed, cancelled and uncertain are not zero conclusions.": "Güncel özel sentez yok; eksik, başarısız, iptal edilmiş ve belirsiz durumlar sıfır sonuç değildir.",
  "Exact job": "Tam iş",
  "Original UTC microseconds and source SHA are preserved. The opaque SHA binds hidden original actor provenance; it is not reconstructible proof of the current reader's authority or of the raw body.": "Özgün UTC mikrosaniyeleri ve kaynak SHA'sı korunur. Opak SHA gizli özgün aktör kökenini bağlar; güncel okuyucunun yetkisinin veya ham gövdenin yeniden oluşturulabilir kanıtı değildir.",
  "Eight literal static start-tag counts preserve duplicate and self-closing occurrences. Observed zero differs from whole-null unavailable counts; inherited parser limits can make the whole sample unavailable.": "Sekiz sözcüğü sözcüğüne statik başlangıç etiketi sayısı, yinelenen ve kendiliğinden kapanan oluşumları korur. Gözlenen sıfır tümü null olan kullanılamayan sayılardan farklıdır; devralınan ayrıştırıcı sınırları tüm örneği kullanılamaz yapabilir.",
  "The original URI, collection date and byte digest/size are retained. Counts do not establish rendered formats, actual page types, loaded media, accessibility, search result features, topics, freshness or whole-site coverage. No attributes, text or media URLs are retained. Saved-pair comparison retains these same literal limits. AI processing remains unavailable.": "Özgün URI, toplama tarihi ve bayt özeti/boyutu korunur. Sayılar oluşturulmuş biçimleri, gerçek sayfa türlerini, yüklenmiş medyayı, erişilebilirliği, arama sonucu özelliklerini, konuları, güncelliği veya tüm site kapsamını kanıtlamaz. Öznitelikler, metin veya medya URL'leri saklanmaz. Kaydedilmiş çift karşılaştırması aynı sözcüğü sözcüğüne sınırları korur. AI işleme kullanılamaz.",
  "One provider-reported lab sample for the original exact URI and device. Request start, server receipt, original provider-reported time, Lighthouse version and response digest/size are preserved separately. Provider time may predate this request.": "Özgün tam URI ve cihaz için sağlayıcının bildirdiği tek laboratuvar örneği. İstek başlangıcı, sunucu alımı, sağlayıcının bildirdiği özgün zaman, Lighthouse sürümü ve yanıt özeti/boyutu ayrı korunur. Sağlayıcı zamanı bu istekten önce olabilir.",
  "Four nullable scores and four lab values retain units and observed zero. Missing values and whole-runtime unavailable/null are not zero. These are not field p75 Core Web Vitals, current-site or whole-site measurements, rankings, causality or a security assessment. Saved-pair arithmetic requires a separate deliberate GET; AI synthesis remains unavailable.": "Dört nullable puan ve dört laboratuvar değeri, birimleri ve gözlenen sıfırı korur. Eksik değerler ve tüm çalışma için kullanılamayan/null durum sıfır değildir. Bunlar saha p75 Core Web Vitals, güncel site veya tüm site ölçümleri, sıralamalar, nedensellik veya güvenlik değerlendirmesi değildir. Kaydedilmiş çift aritmetiği ayrı kasıtlı GET gerektirir; AI sentezi kullanılamaz.",
  "At most 10 literal article:published_time and article:modified_time declarations are retained in original order, including duplicates and empty values. Values are bounded to 80 characters with explicit truncation. Observed empty differs from unavailable/null.": "En fazla 10 sözcüğü sözcüğüne article:published_time ve article:modified_time beyanı, yinelenenler ve boş değerler dahil özgün sırada saklanır. Değerler açık kesilmeyle 80 karakterle sınırlıdır. Gözlenen boş durum kullanılamayan/null durumdan farklıdır.",
  "The original observation time records collection only. Declared values are unverified text, not validated timestamps, publication or change time, page identity, age, freshness, publishing cadence or whole-site evidence. Saved-pair comparison is a separate deliberate read of two originals. AI processing remains unavailable for this family.": "Özgün gözlem zamanı yalnızca toplamayı kaydeder. Beyan edilen değerler doğrulanmamış metindir; doğrulanmış zaman damgaları, yayın veya değişim zamanı, sayfa kimliği, yaş, güncellik, yayın sıklığı veya tüm site kanıtı değildir. Kaydedilmiş çift karşılaştırması iki özgünün ayrı kasıtlı okumasıdır. Bu ailede AI işleme kullanılamaz.",
  "At most 10 supported same-origin static href occurrences are retained in original order, including duplicates. Original category counts retain unsupported and other-origin denominators. Observed empty differs from unavailable/null; base-dependent, ambiguous or over-limit documents have no partial inventory.": "En fazla 10 desteklenen aynı kökenli statik href oluşumu, yinelenenler dahil özgün sırada saklanır. Özgün kategori sayıları desteklenmeyen ve diğer köken paydalarını korur. Gözlenen boş durum kullanılamayan/null durumdan farklıdır; base bağımlı, belirsiz veya sınır aşan belgelerde kısmi envanter yoktur.",
  "These literal URI joins are displayed as text. No referenced destination is requested or approved for crawling. They do not establish unique pages, link health, browser visibility, topics, freshness or whole-site structure. Saved-pair comparison is a separate deliberate read of two originals. AI synthesis remains unavailable for this family.": "Bu sözcüğü sözcüğüne URI birleşimleri metin olarak gösterilir. Referans verilen hiçbir hedef istenmez veya tarama için onaylanmaz. Benzersiz sayfaları, bağlantı sağlığını, tarayıcı görünürlüğünü, konuları, güncelliği veya tüm site yapısını kanıtlamazlar. Kaydedilmiş çift karşılaştırması iki özgünün ayrı kasıtlı okumasıdır. Bu ailede AI sentezi kullanılamaz.",
  "At most 10 original literal h1–h6 occurrences are retained in document order, including duplicates and empty text. Each text is bounded to 80 characters with explicit truncation; six counts match the retained occurrences. Observed empty differs from unavailable/null.": "En fazla 10 özgün sözcüğü sözcüğüne h1–h6 oluşumu, yinelenenler ve boş metin dahil belge sırasında saklanır. Her metin açık kesilmeyle 80 karakterle sınırlıdır; altı sayı saklanan oluşumlarla eşleşir. Gözlenen boş durum kullanılamayan/null durumdan farklıdır.",
  "These static text levels do not establish browser visibility, semantic outline, accessibility correctness, topics, page identity, publication age, freshness or whole-site structure. Comparisons and AI synthesis remain separate.": "Bu statik metin düzeyleri tarayıcı görünürlüğünü, anlamsal taslağı, erişilebilirlik doğruluğunu, konuları, sayfa kimliğini, yayın yaşını, güncelliği veya tüm site yapısını kanıtlamaz. Karşılaştırmalar ve AI sentezi ayrı kalır.",
  "Counts describe HTML-decoded href occurrences from one returned static document, excluding inert/raw-text/foreign descendants. Only bounded no-base URI references are joined against its original URL: same scheme and host origin, other HTTP/HTTPS origin, or unsupported. Unsupported references remain in the inspected denominator. Repeated links are occurrences, not unique pages; no destination, anchor text or rel is retained.": "Sayılar, etkisiz/ham metin/yabancı alt öğeler hariç döndürülen tek statik belgedeki HTML çözülmüş href oluşumlarını açıklar. Yalnızca sınırlı base olmayan URI referansları özgün URL ile birleştirilir: aynı şema ve sunucu kökeni, diğer HTTP/HTTPS kökeni veya desteklenmeyen. Desteklenmeyen referanslar incelenen paydada kalır. Yinelenen bağlantılar benzersiz sayfalar değil oluşumlardır; hedef, bağlantı metni veya rel saklanmaz.",
  "Observed zero differs from unavailable/null. Any active base, ambiguous markup or limit makes the whole summary unavailable. These categories do not establish browser visibility, link health, inbound links or whole-site structure, and remain separate from metadata comparisons and AI synthesis.": "Gözlenen sıfır kullanılamayan/null durumdan farklıdır. Herhangi bir aktif base, belirsiz işaretleme veya sınır tüm özeti kullanılamaz yapar. Bu kategoriler tarayıcı görünürlüğünü, bağlantı sağlığını, gelen bağlantıları veya tüm site yapısını kanıtlamaz; meta veri karşılaştırmalarından ve AI sentezinden ayrı kalır.",
  "Only fixed lexical JSON-LD type labels from one returned static document are retained. No context expansion, arbitrary identifiers, properties or schema bodies are retained. An observed empty type list differs from unavailable/null; unrecognized declarations are counted without their text.": "Döndürülen tek statik belgeden yalnızca sabit sözcüksel JSON-LD tür etiketleri saklanır. Bağlam genişletmesi, keyfi tanımlayıcılar, özellikler veya şema gövdeleri saklanmaz. Gözlenen boş tür listesi kullanılamayan/null durumdan farklıdır; tanınmayan beyanlar metinleri olmadan sayılır.",
  "These declarations do not prove actual page type, schema validity, applicable required properties, consistency with visible content, rich-result eligibility or search appearance. They are separate from metadata comparisons and AI synthesis, with no whole-site coverage.": "Bu beyanlar gerçek sayfa türünü, şema geçerliliğini, geçerli gerekli özellikleri, görünür içerikle tutarlılığı, zengin sonuç uygunluğunu veya arama görünümünü kanıtlamaz. Tüm site kapsamı olmadan meta veri karşılaştırmalarından ve AI sentezinden ayrıdırlar.",
  "Title/description are literal untrusted static text with explicit truncation. Observed empty is different from unavailable/null. Counts concern bounded selected lexical starts only, excluding inert/raw-text/foreign descendants. JSON-LD block count is not schema validity. No topics, publication age, whole-site comparison, performance, traffic, ranking or inbound backlink coverage is established.": "Başlık/açıklama açık kesilmeyle sözcüğü sözcüğüne güvenilmeyen statik metindir. Gözlenen boş durum kullanılamayan/null durumdan farklıdır. Sayılar yalnızca sınırlı seçilen sözcüksel başlangıçlarla ilgilidir; etkisiz/ham metin/yabancı alt öğeler hariçtir. JSON-LD blok sayısı şema geçerliliği değildir. Konular, yayın yaşı, tüm site karşılaştırması, performans, trafik, sıralama veya gelen geri bağlantı kapsamı kanıtlanmaz.",
  "The saved URI describes the exact request and returned static bytes. It does not establish page identity, publication or update time, topics or whole-site coverage. AI synthesis remains separate.": "Kaydedilmiş URI tam isteği ve döndürülen statik baytları açıklar. Sayfa kimliğini, yayın veya güncelleme zamanını, konuları veya tüm site kapsamını kanıtlamaz. AI sentezi ayrı kalır.",
  "No current private observation. Failed, cancelled, unknown and missing are not zero facts.": "Güncel özel gözlem yok. Başarısız, iptal edilmiş, bilinmeyen ve eksik durumlar sıfır gerçek değildir.",
  "Stored date syntax candidates — unverified declarations": "Saklanan tarih sözdizimi adayları — doğrulanmamış beyanlar",
  "Calendar-only literals have no timezone or instant. Supported known-offset literals retain UTC microseconds; later than observation describes that literal instant only. Unsupported and truncated literals stay unavailable. Empty observed declarations differ from a wholly unavailable sample. These candidates do not establish publication or change time, age, freshness, cadence, page identity, whole-site coverage or approval.": "Yalnızca takvim olan metinlerin saat dilimi veya zaman anı yoktur. Desteklenen bilinen saat farkı metinleri UTC mikrosaniyelerini korur; gözlemden sonraki durum yalnızca bu metnin zaman anını açıklar. Desteklenmeyen ve kesilmiş metinler kullanılamaz kalır. Gözlenen boş beyanlar tümü kullanılamayan örnekten farklıdır. Bu adaylar yayın veya değişim zamanını, yaşı, güncelliği, sıklığı, sayfa kimliğini, tüm site kapsamını veya onayı kanıtlamaz.",
  "Original declarations unavailable; candidates unknown.": "Özgün beyanlar kullanılamıyor; adaylar bilinmiyor.",
  "Stored date syntax candidate table": "Saklanan tarih sözdizimi adayı tablosu",
  "Each original declaration in saved order, including duplicates": "Yinelenenler dahil kaydedilmiş sırada her özgün beyan",
  "Declaration index (from zero)": "Beyan indeksi (sıfırdan)",
  "Syntax state": "Sözdizimi durumu",
  "Calendar date": "Takvim tarihi",
  "UTC instant": "UTC anı",
  "Literal later than observation": "Metin gözlemden sonra",
  "Yes": "Evet",
  "No": "Hayır",
  "Original collection and separate syntax candidates": "Özgün toplama ve ayrı sözdizimi adayları",
  "Current actor, role, project configuration or credential reference unavailable. Private facts and local uncertainty cleared; stored jobs may still exist. No replay.": "Güncel aktör, rol, proje yapılandırması veya kimlik bilgisi referansı kullanılamıyor. Özel gerçekler ve yerel belirsizlik temizlendi; saklanan işler hâlâ bulunabilir. Tekrar yoktur.",
  "Local uncertainty discarded. Stored jobs may still exist; refresh history.": "Yerel belirsizlik atıldı. Saklanan işler hâlâ bulunabilir; geçmişi yenileyin.",
  "Choose an authorized exact organization and project.": "Yetkilendirilmiş tam kuruluş ve proje seçin.",
  "Current saved competitor source and private history unavailable.": "Güncel kaydedilmiş rakip kaynak ve özel geçmiş kullanılamıyor.",
  "Exact current source, three declarations or collection allowance unavailable. No collection command sent.": "Tam güncel kaynak, üç beyan veya toplama hakkı kullanılamıyor. Toplama komutu gönderilmedi.",
  "Exact command acknowledged. Refresh metadata or deliberately inspect private evidence.": "Tam komut alındı. Meta verileri yenileyin veya özel kanıtı kasıtlı olarak inceleyin.",
  "Current original source or credential unavailable after acknowledgment. Private state and uncertainty cleared; a stored job may exist. No replay.": "Alım onayından sonra güncel özgün kaynak veya kimlik bilgisi kullanılamıyor. Özel durum ve belirsizlik temizlendi; saklanan iş bulunabilir. Tekrar yoktur.",
  "Current command scope unavailable. Local uncertainty cleared; stored jobs may still exist. No replay.": "Güncel komut kapsamı kullanılamıyor. Yerel belirsizlik temizlendi; saklanan işler hâlâ bulunabilir. Tekrar yoktur.",
  "No saved own-actor request at this lookup. Outcome remains uncertain; no replay.": "Bu aramada kendi aktörünüze ait kaydedilmiş istek yok. Sonuç belirsiz kalır; tekrar yoktur.",
  "Exact original command reconciled. No POST replayed.": "Tam özgün komut uzlaştırıldı. POST tekrarlanmadı.",
  "Exact lookup/current source unavailable. Local uncertainty cleared; stored jobs may still exist. No replay.": "Tam arama/güncel kaynak kullanılamıyor. Yerel belirsizlik temizlendi; saklanan işler hâlâ bulunabilir. Tekrar yoktur.",
  "Exact private observation/current source unavailable. Missing is not zero facts.": "Tam özel gözlem/güncel kaynak kullanılamıyor. Eksiklik sıfır gerçek değildir.",
  "Current original Date candidates unavailable. Private state cleared; unknown is not zero.": "Güncel özgün tarih adayları kullanılamıyor. Özel durum temizlendi; bilinmeyen sıfır değildir.",
  "Current synthesis history or model catalog unavailable. Private state cleared.": "Güncel sentez geçmişi veya model kataloğu kullanılamıyor. Özel durum temizlendi.",
  "Current original topic samples, models or private scope unavailable. Comparison cleared; unmatched is not missing topics. No new request or replay.": "Güncel özgün konu örnekleri, modeller veya özel kapsam kullanılamıyor. Karşılaştırma temizlendi; eşleşmeyen eksik konu değildir. Yeni istek veya tekrar yoktur.",
  "Original citable heading sample, separate AI permission or exact model budget unavailable. No AI command sent.": "Özgün alıntılanabilir başlık örneği, ayrı AI izni veya tam model bütçesi kullanılamıyor. AI komutu gönderilmedi.",
  "Exact topic command acknowledged. Inspect its original private result separately.": "Tam konu komutu alındı. Özgün özel sonucunu ayrı inceleyin.",
  "Original source/model authority lost after acknowledgment. Private facts and uncertainty cleared; a stored job may exist. No replay.": "Alım onayından sonra özgün kaynak/model yetkisi kayboldu. Özel gerçekler ve belirsizlik temizlendi; saklanan iş bulunabilir. Tekrar yoktur.",
  "Current original topic hypotheses, source or model unavailable. Private state cleared; missing is not zero.": "Güncel özgün konu hipotezleri, kaynak veya model kullanılamıyor. Özel durum temizlendi; eksiklik sıfır değildir.",
  "Exact pair, separate AI permission or model budget unavailable. No AI command sent.": "Tam çift, ayrı AI izni veya model bütçesi kullanılamıyor. AI komutu gönderilmedi.",
  "Original source or model changed after the command. Private facts and uncertainty cleared; a stored job may exist. No replay.": "Komuttan sonra özgün kaynak veya model değişti. Özel gerçekler ve belirsizlik temizlendi; saklanan iş bulunabilir. Tekrar yoktur.",
  "Exact synthesis command acknowledged. Deliberately refresh history or inspect its original private result.": "Tam sentez komutu alındı. Geçmişi kasıtlı olarak yenileyin veya özgün özel sonucunu inceleyin.",
  "Current original source or model unavailable after acknowledgment. Private state and uncertainty cleared; a stored job may exist. No replay.": "Alım onayından sonra güncel özgün kaynak veya model kullanılamıyor. Özel durum ve belirsizlik temizlendi; saklanan iş bulunabilir. Tekrar yoktur.",
  "Current original synthesis, source or model unavailable. Private result and uncertainty cleared; missing is not zero.": "Güncel özgün sentez, kaynak veya model kullanılamıyor. Özel sonuç ve belirsizlik temizlendi; eksiklik sıfır değildir.",
  "No saved own-actor synthesis at this lookup. Outcome remains uncertain; no replay.": "Bu aramada kendi aktörünüze ait kaydedilmiş sentez yok. Sonuç belirsiz kalır; tekrar yoktur.",
  "Exact original synthesis command reconciled. No POST replayed; inspect evidence separately.": "Tam özgün sentez komutu uzlaştırıldı. POST tekrarlanmadı; kanıtı ayrı inceleyin.",
  "Exact synthesis lookup/current actor unavailable. Local uncertainty cleared; a stored job may exist. No replay.": "Tam sentez araması/güncel aktör kullanılamıyor. Yerel belirsizlik temizlendi; saklanan iş bulunabilir. Tekrar yoktur.",
  "Exact original pair/current private scope unavailable. Comparison cleared; missing is not zero. No collection or replay.": "Tam özgün çift/güncel özel kapsam kullanılamıyor. Karşılaştırma temizlendi; eksiklik sıfır değildir. Toplama veya tekrar yoktur.",
  "Unreviewed Turkish competitor interface draft in local development. Original source text and protocol metadata retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe rakip arayüzü taslağı. Özgün kaynak metni ve protokol meta verileri özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-competitor-roots', imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="competitor-title">
      <h1 id="competitor-title">{{ formats ? t("Selected competitor static content-element counts") : topics ? t("Topic hypotheses from one saved heading observation") : lighthouse ? t("Selected competitor Lighthouse lab sample") : dates ? t("Selected competitor page article date declarations") : destinations ? t("Selected competitor page same-origin references") : headings ? t("Selected competitor page literal headings") : page ? t("Selected competitor page metadata") : links ? t("Selected competitor root link categories") : schema ? t("Selected competitor schema type labels") : t("Selected competitor root observations") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish competitor interface draft in local development. Original source text and protocol metadata retain their original language; bilingual approval is pending.") }}</p> }
      <p>{{ t("Organization") }} <span lang="en">{{ organizationId }}</span> {{ t("· project") }} <span lang="en">{{ projectId }}</span> · <a [routerLink]="['/app/dashboard', organizationId, projectId]">{{ t("Project evidence") }}</a>
        · <a [routerLink]="['/app/onboarding', organizationId, projectId]">{{ t("Edit saved competitors") }}</a>
        · <a [routerLink]="[schema ? '/app/competitor-roots' : '/app/competitor-schema-roots', organizationId, projectId]">{{ schema ? t("Separate metadata observations") : t("Separate schema label observations") }}</a>
        @if (links || page) { · <a [routerLink]="['/app/competitor-roots', organizationId, projectId]">{{ t("Separate metadata observations") }}</a> }
        @else { · <a [routerLink]="['/app/competitor-links-roots', organizationId, projectId]">{{ t("Separate link category observations") }}</a> }
        @if (!page || lighthouse || dates || headings || destinations) { · <a [routerLink]="['/app/competitor-pages', organizationId, projectId]">{{ t("Separate selected page metadata") }}</a> }
        @if (!lighthouse) { · <a [routerLink]="['/app/competitor-lighthouse', organizationId, projectId]">{{ t("Separate selected Lighthouse lab sample") }}</a> }
        @if (!formats) { · <a [routerLink]="['/app/competitor-page-formats', organizationId, projectId]">{{ t("Separate selected page static content-element counts") }}</a> }
        @if (!dates) { · <a [routerLink]="['/app/competitor-page-dates', organizationId, projectId]">{{ t("Separate selected page article date declarations") }}</a> }
        @if (!headings) { · <a [routerLink]="['/app/competitor-page-headings', organizationId, projectId]">{{ t("Separate selected page literal headings") }}</a> }
        @if (!destinations) { · <a [routerLink]="['/app/competitor-page-destinations', organizationId, projectId]">{{ t("Separate selected page same-origin references") }}</a> }</p>
      @if (lighthouse) {
        <p>{{ t("Verified-account owner/admin only. Select one exact non-root competitor URI and mobile or desktop device. Robots checks and pacing precede a Google PageSpeed Insights request. No redirects, recursive crawl, login, automatic schedule or request replay.") }}</p>
        <p>{{ t("Four independent declarations are required; they do not verify legal permission. Google processes the selected URL. One internal operation unit is reserved; attempted or uncertain requests consume it. Google provider quota and charges are separate and unknown here. Configure the supported key in") }} <a [routerLink]="['/app/provider-accounts', organizationId]">{{ t("organization provider settings") }}</a>{{ t(". Raw provider JSON, screenshots, field data and robots are not retained. A configured competitor is not owned or verified.") }}</p>
      } @else {
        <p>{{ t("Verified-account owner/admin only.") }} {{ page ? t("One explicitly selected non-root URI within one saved competitor origin") : t("One saved competitor origin's root") }}{{ t(", with robots policy, bounded static HTML and host pacing. No redirects, recursive crawl, rendering, login, automatic schedule or request replay. A configured competitor is not an owned alias or verified ownership.") }}</p>
        <p>{{ t("Three independent declarations are required; they do not verify legal permission. One internal operation unit is reserved; attempted or uncertain collection consumes it, not a provider charge.") }} {{ destinations ? t("Raw HTML, robots, original href attributes, off-origin URLs, anchor text and schema bodies are not retained.") : t("Raw HTML, robots, href inventories and schema bodies are not retained.") }}</p>
      }
      <p>        {{ t("Minimized private evidence follows export/closure policy: 90-day retained access after lapse, active deletion within 30 days of closure/expiry, up to 35-day backup rotation after active deletion. Retained status history does not authorize new collection or current evidence use.") }}</p>
      @if (busy()) { <p role="status">{{ t("Checking current scope and private state.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="t(error()) === error() ? 'en' : uiLanguage()">{{ t(error()) }}</p> }
      @if (message()) { <p role="status" [attr.lang]="t(message()) === message() ? 'en' : uiLanguage()">{{ t(message()) }}</p> }
      <button type="button" (click)="load()" [disabled]="busy() || !!pending()">{{ t("Refresh saved competitors and private history") }}</button>
      @if (ready()) {
        @if (!origins().length) { <p>{{ t("No eligible saved competitors. Configure a competitor separately; missing is not zero observations.") }}</p> }
        <form (submit)="preview($event)"><fieldset [disabled]="busy() || !!pending()"><legend>{{ page ? t("One exact selected competitor page URI") : t("One separately selected competitor root") }}</legend>
          <label for="competitor-origin">{{ t("Saved configured origin") }}</label>
          <select id="competitor-origin" required [value]="origin()" (change)="editOrigin($any($event.target).value)">
            <option value="">{{ t("Choose one saved competitor") }}</option>@for (item of origins(); track item) { <option lang="" [value]="item">{{ item }}</option> }
          </select>
          @if (page) {
            <label for="competitor-page-url">{{ t("Exact public page URL on this saved origin") }}</label>
            <input lang="en" id="competitor-page-url" name="url" type="url" required maxlength="1024" [value]="url()" (input)="editUrl($any($event.target).value)" aria-describedby="competitor-page-scope" />
            <p id="competitor-page-scope">{{ t("Enter one full non-root HTTP or HTTPS URL on the exact selected scheme and host. No query, fragment, credentials or custom port.") }} {{ destinations ? t("No root fallback or reference following.") : t("No root fallback or destination discovery.") }}</p>
          }
          @if (lighthouse) {
            <label for="competitor-device">{{ t("Lighthouse device") }}</label>
            <select id="competitor-device" required [value]="strategy()" (change)="editStrategy($any($event.target).value)"><option value="mobile">{{ t("Mobile") }}</option><option value="desktop">{{ t("Desktop") }}</option></select>
            <label><input type="checkbox" name="processing" required [checked]="processingPermission()" (change)="editProcessing($any($event.target).checked)" />{{ t("I independently have permission for Google to process this exact competitor URL for a lab sample.") }}</label>
          }
          <label><input type="checkbox" name="collection" required [checked]="collectionPermission()" (change)="editPermission('collection', $any($event.target).checked)" />
            {{ t("I have permission to collect this selected public") }} {{ page ? t("page URI") : t("root") }} {{ t("with robots and pacing restrictions.") }}</label>
          <label><input type="checkbox" name="use" required [checked]="usePermission()" (change)="editPermission('use', $any($event.target).checked)" />
            {{ t("I independently have permission to use these minimized") }} {{ formats ? t("literal static content-element counts") : lighthouse ? t("provider-reported Lighthouse lab values") : dates ? t("literal article date declarations") : destinations ? t("same-origin static reference URLs and counts") : headings ? t("literal heading text and order") : links ? t("static link occurrence counts") : schema ? t("schema type labels") : t("static metadata") }}.</label>
          <label><input type="checkbox" name="storage" required [checked]="storagePermission()" (change)="editPermission('storage', $any($event.target).checked)" />
            {{ t("I independently have permission to retain this minimized private evidence under the stated lifecycle.") }}</label>
          <button type="submit">{{ t("Preview exact current source (no site request)") }}</button>
        </fieldset></form>
        @if (selection(); as item) {
          <p>{{ t("Exact") }} {{ page ? t("page URI") : t("root") }} <span lang="">{{ page ? previewPage(item)['url'] : previewPage(item)['origin'] + '/' }}</span> {{ t("· configuration revision") }} <span lang="en">{{ previewPage(item)['configuration_revision'] }}</span>
            {{ t("· configured") }} <span lang="en">{{ previewPage(item)['configuration_updated_at'] }}</span> {{ t("(not approval or observation time).") }}</p>
          @if (lighthouse) { <p>{{ t("Device") }} <span lang="en">{{ strategy() }}</span>{{ t(". Credential configuration reference is metadata only; it does not verify the key, access, quota or provider readiness.") }}</p> }
          <details><summary>{{ t("Frozen selected source and canonical command digest") }}</summary><pre><span lang="en">{{ json(item) }}</span></pre></details>
          <button type="button" (click)="launch()" [disabled]="busy() || !!pending()">{{ t("Reserve 1 unit and request") }} {{ formats ? t("these exact selected page content-element counts") : lighthouse ? t("this exact URI/device lab sample") : dates ? t("these exact selected page date declarations") : destinations ? t("these exact selected page references") : headings ? t("these exact selected page headings") : page ? t("this exact selected page") : links ? t("these selected link categories") : schema ? t("these selected schema labels") : t("this selected root") }}</button>
        }
        @if (pending()) {
           <p>{{ t("Command outcome uncertain. The original source, declarations, command fields, preview and same request key are frozen only in this page's memory. No automatic POST replay; another actor's job cannot reconcile this request.") }}</p>
          <button type="button" (click)="reconcile()" [disabled]="busy()">{{ t("Look up the exact original command (GET only)") }}</button>
          <button type="button" (click)="discard()" [disabled]="busy()">{{ t("Discard local uncertainty; a saved job may exist") }}</button>
        }
        <h2>{{ t("Private retained job status") }}</h2>
        @if (!jobs().length) { <p>{{ t("No retained") }} {{ page ? t("competitor-page") : links ? t("link root") : schema ? t("schema root") : t("competitor-root") }} {{ t("jobs. Uncollected or unavailable is not a clean result.") }}</p> }
        @if (hasMore()) { <p>{{ t("Only the latest 20 jobs are shown.") }}</p> }
        <ul>@for (job of jobs(); track job.id) { <li>{{ t("Job") }} {{ job.id }} · <span lang="en">{{ job.status }}</span> {{ t("· created") }} <span lang="en">{{ job.created_at }}</span> {{ t("· updated") }} <span lang="en">{{ job.updated_at }}</span> · <span lang="en">{{ job.error_category }}</span>
          <button type="button" (click)="inspect(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect exact private job") }}</button>
          @if (dates && job.status === 'succeeded' && !job.cancel_requested) {
            <button type="button" (click)="inspectDateCandidates(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect saved date syntax candidates") }}</button>
          }
          @if (['queued', 'running'].includes(job.status) && !job.cancel_requested) {
            <button type="button" (click)="cancel(job.id)" [disabled]="busy() || !!pending()">{{ t("Request cancellation") }}</button>
          }
        </li> }</ul>
        @if (formats) {
          <p>{{ t("These are bounded literal start-tag counts for paragraphs, lists, tables, image/picture, video and audio elements in one returned static document. They retain original date and byte provenance; duplicate and self-closing start tags count. CSS-hidden syntax may count. Attributes, text and media URLs are not retained. Observed zero differs from whole-null unavailable counts, including inherited parser limits.") }}</p>
          <p>{{ t("Counts do not establish rendered content formats, page types, loaded media, accessibility, search result features, topics, freshness or whole-site coverage. Saved-pair differences describe literal counts only. AI processing is unavailable for this family.") }}</p>
        }
        <form (submit)="compare($event)"><fieldset [disabled]="busy() || !!pending()"><legend>{{ t("Compare two saved original") }} {{ formats ? t("static content-element counts") : lighthouse ? t("Lighthouse lab samples") : dates ? t("page date declarations") : destinations ? t("page references") : headings ? t("page headings") : links ? t("link root") : schema ? t("schema root") : page ? t("page URI") : t("root") }} {{ t("observations (GET only)") }}</legend>
          @if (dates) {
            <fieldset><legend>{{ t("Saved Date comparison mode") }}</legend>
              <label><input type="radio" name="date-comparison-mode" [checked]="!dateCandidatePairMode()" (change)="editDateCandidatePair(false)" />{{ t("Original declaration text changes") }}</label>
              <label><input type="radio" name="date-comparison-mode" [checked]="dateCandidatePairMode()" (change)="editDateCandidatePair(true)" />{{ t("Syntax candidate intervals between all same-property declarations") }}</label>
            </fieldset>
          }
          @if (destinations || formats || headings && !topics) {
            <fieldset><legend>{{ t("Saved") }} {{ headings ? t("heading count") : formats ? t("element count") : t("reference") }} {{ t("inspection mode") }}</legend>
              <label for="competitor-reference-dated"><input id="competitor-reference-dated" name="competitor-reference-mode" type="radio" [checked]="!referenceStructureMode() && !referenceInventoryMode()" (change)="editReferenceInventory(false)"> {{ t("Compare earlier and later samples of the same page") }}</label>
              <label for="competitor-reference-structure"><input id="competitor-reference-structure" name="competitor-reference-mode" type="radio" [checked]="referenceStructureMode()" (change)="editReferenceStructure($any($event.target).checked)"> {{ formats || headings ? t("Inspect literal counts in two different saved pages") : t("Inspect references between two different saved pages") }}</label>
              @if (destinations) {
              <label for="competitor-destination-inventory"><input id="competitor-destination-inventory" name="competitor-reference-mode" type="radio" [checked]="referenceInventoryMode()" (change)="editReferenceInventory($any($event.target).checked)"> {{ t("Inspect stored resolved destination URIs across two samples") }}</label>
              }
            </fieldset>
          }
          @if (referenceStructureMode() || referenceInventoryMode()) {
            <p>{{ t("Choose two succeeded saved") }} {{ headings ? t("heading count") : formats ? t("element count") : t("reference") }} {{ t("jobs for different exact page URIs on one origin. Counts follow the selected first/second order; dates need not increase. Each original static sample retains its own provenance.") }}</p>
          } @else {
            <p>{{ t("Choose an earlier and later succeeded job from this retained list. Only the exact same original source, actor provenance,") }} {{ page ? t("selected URI") : t("root") }} {{ t("and methods can be compared.") }} {{ lighthouse ? t("The original device and known Lighthouse version must match for arithmetic; provider report times must increase. Same device/version does not establish controlled run conditions.") : '' }}</p>
          }
          <label for="competitor-previous">{{ referenceStructureMode() || referenceInventoryMode() ? t("First") : t("Earlier") }} {{ t("saved job") }}</label>
          <select id="competitor-previous" required [value]="previousJobId()" (change)="editPair('previous', $any($event.target).value)">
            <option value="0">{{ t("Choose") }} {{ referenceStructureMode() || referenceInventoryMode() ? t("first") : t("earlier") }} {{ t("observation") }}</option>@for (job of jobs(); track job.id) {
              @if (job.status === 'succeeded' && !job.cancel_requested) { <option lang="en" [value]="job.id">Job {{ job.id }} · {{ job.updated_at }}</option> }
            }
          </select>
          <label for="competitor-current">{{ referenceStructureMode() || referenceInventoryMode() ? t("Second") : t("Later") }} {{ t("saved job") }}</label>
          <select id="competitor-current" required [value]="currentJobId()" (change)="editPair('current', $any($event.target).value)">
            <option value="0">{{ t("Choose") }} {{ referenceStructureMode() || referenceInventoryMode() ? t("second") : t("later") }} {{ t("observation") }}</option>@for (job of jobs(); track job.id) {
              @if (job.status === 'succeeded' && !job.cancel_requested) { <option lang="en" [value]="job.id">Job {{ job.id }} · {{ job.updated_at }}</option> }
            }
          </select>
          <button type="submit" [disabled]="!previousJobId() || !currentJobId() || previousJobId() === currentJobId()">{{ t("Read this exact frozen pair") }}</button>
        </fieldset></form>
        @if (comparison(); as item) {
          @if (referenceInventoryMode()) { <h3>{{ t("Stored resolved destinations across two saved static samples") }}</h3> }
          @else if (referenceStructureMode()) { <h3>{{ headings ? t("Literal heading-level counts in two saved static samples") : formats ? t("Literal element counts in two saved static samples") : t("Reference occurrences between two saved static samples") }}</h3> }
          @else { <h3>{{ t("Original dated selected-") }}{{ formats ? t("static content-element counts") : lighthouse ? t("Lighthouse lab sample") : dates ? t("page date declarations") : destinations ? t("page references") : headings ? t("page headings") : links ? t("link root") : schema ? t("schema root") : page ? t("page URI") : t("root") }} {{ t("comparison") }}</h3> }
          <pre><span lang="en">{{ json(item) }}</span></pre>
          @if (referenceInventoryMode()) {
            <p>{{ t("Destination strings are the exact stored resolved URI representation from the original collector, not raw HTML href spellings. Columns follow their first occurrence across the two selected samples; each observed row counts original duplicate references. An unavailable entire row is null even when the known URI list is empty, and may hide unknown destinations. All rows observed reports only these two source states, not complete page, site or destination coverage. Original order, dates and provenance stay separate. No target fetch or health, browser visibility, indexing, inbound links, whole-site topology, topics, freshness, causality or authority to crawl is established.") }}</p>
          } @else if (referenceStructureMode()) {
            @if (formats || headings) {
              <div class="element-counts" role="region" [attr.aria-label]="headings ? t('Two saved-page literal heading counts') : t('Two saved-page literal element counts')" tabindex="0">
              <table><caption>{{ headings ? t("Literal heading-level counts") : t("Literal start-tag counts") }} {{ t("in these two saved pages") }}</caption>
                <thead><tr><th scope="col">{{ t("Saved sample") }}</th>@for (name of $any(item)[headings ? 'heading_levels' : 'element_names']; track name) { <th scope="col"><span lang="en">{{ name }}</span></th> }</tr></thead>
                <tbody>@for (row of $any(item)[headings ? 'selected_heading_occurrences' : 'selected_element_occurrences']; track $index) {
                  <tr><th scope="row">{{ $index === 0 ? t("First") : t("Second") }} {{ t("sample") }}</th>@for (count of row; track $index) { <td [attr.lang]="count === null ? uiLanguage() : 'en'">{{ count === null ? t("Unavailable") : count }}</td> }</tr>
                }</tbody>
              </table>
              </div>
              @if (headings) {
                <p>{{ t("Each original heading list, duplicate text, order and truncation flag is retained. Text truncation does not erase known literal level counts. Zero is observed; an unavailable whole row stays unknown. All rows observed describes only these two static sample states. These counts do not establish a rendered or semantic outline, accessibility, topics, intent, page identity, freshness, site totals, whole-site coverage or causality. This matrix cannot authorize AI processing; dated same-page synthesis is separate.") }}</p>
              } @else {
              <p>{{ t("Rows retain each original selected URI, date, byte digest/size and opaque collector-bound source. Zero is observed; an unavailable whole row stays unknown. All rows observed describes only these two static samples. The counts are literal syntax, without chronological changes or site totals. They do not establish rendered formats, loaded media, semantic page types, search features, accessibility, freshness, whole-site coverage or causality. AI processing remains unavailable.") }}</p>
              }
            } @else {
            <p>{{ t("Rows are the first and second original samples; columns are their exact selected URIs. Counts retain duplicate occurrences without URL normalization. Zero means no exact reference in that returned static sample; unavailable rows stay null. Original order, dates, coverage and opaque actor-bound source SHAs are preserved. This is not unique pages, fetched target health, browser visibility, indexing, inbound links, whole-site topology, topics, freshness, causality or authority to crawl a target.") }}</p>
            }
          } @else if (formats) {
            <p>{{ t("Both original dates, body digests/sizes, coverage and literal start-tag counts are preserved. Differences are later minus earlier for the eight selected elements. Observed zero remains known; unavailable evidence has whole-null differences. Body change means returned bytes only. Counts do not establish rendered formats, loaded media, semantic page types, accessibility, search features, topics, freshness, whole-site changes, causality or collection permission. The original actor-bound source SHA is opaque to an independent reader. AI processing remains unavailable.") }}</p>
          } @else if (lighthouse) {
            <p>{{ t("Both original samples preserve request start, local receipt, raw provider-reported time, response digest/size and version. Differences are later minus earlier nullable scores and normative lab metric units; missing is not zero. Incompatible runtime, unknown/changed version or nonincreasing provider timestamps retain original samples with null differences. Provider bytes changed does not establish a site change.") }}</p>
            <p>{{ t("Arithmetic between two samples is not a controlled or representative benchmark, statistical significance, field p75 Core Web Vitals, current whole-site measurements, rankings or causality. Separate runs can vary without code changes. No aggregate or grade is generated; AI synthesis remains unavailable.") }}</p>
          } @else if (dates) {
            @if (dateCandidatePairMode()) {
              <p>{{ t("Each row compares a previous and current declaration index with the same exact property. All combinations and duplicates are retained; these are not matched actual publishing events. Calendar candidates yield signed calendar-day differences and known-offset candidates exact signed UTC microseconds. Mixed, unsupported or truncated candidates stay unavailable. A wholly unavailable declaration side makes all rows unknown; observed empty stays empty. These intervals do not establish publication/update cadence, age, freshness, page identity, whole-site changes or causality.") }}</p>
              @if (item['declaration_pair_candidates'] === null) { <p>{{ t("Original declaration pairs unavailable; intervals unknown.") }}</p> }
              @else {
                <div class="element-counts" role="region" tabindex="0" [attr.aria-label]="t('Stored Date candidate interval table')">
                  <table><caption>{{ t("All same-property original declaration index combinations; current minus previous") }}</caption>
                    <thead><tr><th scope="col">{{ t("Previous index (from zero)") }}</th><th scope="col">{{ t("Current index (from zero)") }}</th><th scope="col">{{ t("Candidate state") }}</th><th scope="col">{{ t("Calendar days") }}</th><th scope="col">{{ t("UTC microseconds") }}</th></tr></thead>
                    <tbody>@for (row of dateIntervalRows(item); track $index) {
                      <tr><th scope="row"><span lang="en">{{ row['previous_declaration_index'] }}</span></th><td><span lang="en">{{ row['current_declaration_index'] }}</span></td><td><span lang="en">{{ row['state'] }}</span></td><td [attr.lang]="row['calendar_day_delta'] === null ? uiLanguage() : 'en'">{{ row['calendar_day_delta'] ?? t("Unavailable") }}</td><td [attr.lang]="row['utc_microsecond_delta'] === null ? uiLanguage() : 'en'">{{ row['utc_microsecond_delta'] ?? t("Unavailable") }}</td></tr>
                    }</tbody>
                  </table>
                </div>
              }
            }
            <p>{{ t("Both original observation times, body digests/sizes and ordered duplicate-preserving article date declarations are preserved. Exact untruncated property-value order equality describes literal text only. Observed empty and empty values remain known; unavailable or truncated declarations have null differences. Body change means returned bytes only. Declared text is not validated publication or change time, age, freshness, publishing cadence, page identity, whole-site evidence or causality. The original actor-bound source SHA is opaque to an independent reader. AI processing remains unavailable.") }}</p>
          } @else if (destinations) {
            <p>{{ t("Both original dates, body digests/sizes and ordered duplicate-preserving same-origin references are preserved. Exact literal URL order equality and later-minus-earlier four category counts describe static references only. An observed empty supported list can retain nonzero other-origin or unsupported counts; whole unavailable evidence has null differences. Body change means returned bytes only. No unique pages, fetched targets, link health, browser visibility, freshness, whole-site changes, causality or target crawling authority is established. The original actor-bound source SHA is opaque to an independent reader.") }}</p>
          } @else if (headings) {
            <p>{{ t("Both original dates, body digests/sizes and ordered literal heading occurrences are preserved. Exact untruncated heading text/level/order equality and later-minus-earlier six counts describe static syntax only. Observed empty remains empty/zero; unavailable or truncated heading text has null differences. Body change means returned bytes only, not browser visibility, semantic outline, accessibility correctness, topics, page identity, freshness, whole-site changes or causality. The original actor-bound source SHA is opaque to an independent reader.") }}</p>
          } @else if (links) {
            <p>{{ t("Both original dates, body digests/sizes and literal reference-category counts are preserved. Differences are later minus earlier counts, with observed empty as zero and unavailable evidence as null. No destination URLs, unique pages, browser visibility, link health, inbound links, whole-site structure, freshness or causality are established. Body change means returned bytes changed only. The original actor-bound source SHA is opaque to an independent reader.") }}</p>
          } @else if (schema) {
            <p>{{ t("Both original dates, body digests/sizes and lexical JSON-LD labels are preserved. Added/removed labels and later-minus-earlier counts describe declarations only, not resolved schema validity, actual page type, rich results, topics, freshness or whole-site changes. Unavailable evidence has null differences; an observed empty set remains empty/zero. Original actor-bound source SHA is opaque to an independent reader. Body change means returned bytes changed only.") }}</p>
          } @else {
          <p>{{ t("Both original UTC microseconds, body digests/sizes and literal metadata are preserved. Body change means returned bytes changed only. Differences are later minus earlier selected lexical counts and literal title/description equality, not topics, publication age, schema validity, whole-site coverage, traffic, rankings, backlinks or causality. Unavailable or truncated metadata is incomparable with null differences; observed empty is comparable. The original actor-bound source SHA is opaque, not the independent reader's digest.") }}</p>
          @if (page) { <p>{{ t("The same selected URI does not establish page identity, publication or update time, freshness or whole-site changes.") }}</p> }
          }
        }
        @if (supportsSynthesis) {
        <h2>{{ topics ? t("Unverified topic hypotheses from one original sample") : t("Private AI interpretations of an original saved pair") }}</h2>
        @if (topics) { <p>{{ t("Choose one retained observation for a first heading-topic hypothesis. Indexed quote matches do not verify a topic label, page topics, content gaps, intent, freshness, rankings, whole-page/site coverage or approval. Human review is required.") }}</p> }
        @if (headings) { <p>{{ t("Interpretations concern only retained literal heading text. They do not establish verified page topics, content gaps, semantic outline, freshness or whole-site coverage; human review is required.") }}</p> }
        <p>{{ t("Separately permit AI processing of") }} {{ topics ? t("one selected saved job") : t("the two selected saved jobs") }}{{ t(". This sends only minimized original facts to the selected provider, never a new site request. The text-model catalog is not proof of reasoning, structured output, context, price or provider readiness; the exact server preview checks eligibility. One internal AI unit is reserved; a committed attempt consumes it even if the result is unknown. No retry, schedule, fallback or automatic replay.") }}</p>
        <button type="button" (click)="loadSyntheses()" [disabled]="busy() || !!pending()">{{ t("Refresh synthesis history and model choices") }}</button>
        @if (synthesisLoaded()) {
          @if (!models().length || !accounts().length) { <p>{{ t("No current model/account choices. Retained status and cancellation remain separate from source/model availability.") }}</p> }
          <form (submit)="previewSynthesis($event)"><fieldset [disabled]="busy() || !!pending()"><legend>{{ topics ? t("Explicit single-observation topic command") : t("Explicit original-pair AI command") }}</legend>
            @if (topics) {
              <label for="competitor-topic-source">{{ t("Original saved heading observation") }}</label>
              <select id="competitor-topic-source" required [value]="topicJobId()" (change)="editTopicJob($any($event.target).value)">
                <option value="0">{{ t("Choose one saved observation") }}</option>
                @for (job of jobs(); track job.id) { <option lang="en" [value]="job.id" [disabled]="job.status !== 'succeeded' || job.cancel_requested">Job {{ job.id }} · {{ job.updated_at }}</option> }
              </select>
            } @else { <p>{{ t("Earlier job") }} {{ previousJobId() || t("not selected") }} {{ t("· later job") }} {{ currentJobId() || t("not selected") }}{{ t(". Choose both using the saved-job controls above.") }}</p> }
            <label><input type="checkbox" name="ai_processing" required [checked]="aiPermission()" (change)="editSynthesis('permission', $any($event.target).checked)" />
              {{ t("I separately have permission for AI processing of") }} {{ topics ? t("this minimized original observation") : t("this minimized original pair") }} {{ t("under the selected provider's policy.") }}</label>
            <label for="competitor-model">{{ t("Explicit model (eligibility checked by preview)") }}</label>
            <select id="competitor-model" required [value]="modelId()" (change)="editSynthesis('model', $any($event.target).value)">
              <option value="0">{{ t("Choose model") }}</option>@for (model of models(); track model.id) {
                <option lang="" [value]="model.id" [disabled]="!model.price_known || model.access_tier === 'unknown'">{{ model.name }} · {{ model.access_tier }}</option>
              }
            </select>
            <label for="competitor-account">{{ t("Matching provider account") }}</label>
            <select id="competitor-account" required [value]="accountId()" (change)="editSynthesis('account', $any($event.target).value)">
              <option value="0">{{ t("Choose account") }}</option>@for (account of matchingAccounts(); track account.id) { <option lang="" [value]="account.id">{{ account.label }} · {{ account.source }}</option> }
            </select>
            @if (selectedModel()?.access_tier === 'free') {
              <p>{{ t("Free-tier data retention/training/reliability differ. Review the") }} <a [href]="selectedModel()!.privacy_policy_url" target="_blank" rel="noopener noreferrer">{{ t("provider policy") }}</a>.</p>
              <label><input type="checkbox" name="free_processing" required [checked]="allowFree()" (change)="editSynthesis('free', $any($event.target).checked)" />{{ t("I explicitly opt in to free-tier processing for this request.") }}</label>
            }
            <label for="competitor-tokens">{{ t("Maximum output tokens (128–2048)") }}</label>
            <input lang="en" id="competitor-tokens" type="number" min="128" max="2048" required [value]="outputTokens()" (input)="editSynthesis('tokens', $any($event.target).value)" />
            <label for="competitor-cost">{{ t("Maximum estimated USD (greater than zero, up to 100)") }}</label>
            <input lang="en" id="competitor-cost" inputmode="decimal" required [value]="maxCost()" (input)="editSynthesis('cost', $any($event.target).value)" />
            <button type="submit">{{ t("Preview exact original") }} {{ topics ? t("observation") : t("pair") }} {{ t("and model budget (no provider request)") }}</button>
          </fieldset></form>
          @if (synthesisSelection(); as item) {
            <p>{{ t("Maximum operator-price estimate USD") }} <span lang="en">{{ item.selection.configuration['estimated_max_cost_usd'] }}</span>{{ t("; this is not a charge or guaranteed provider cost.") }}</p>
            <details><summary>{{ t("Frozen original AI command and canonical digest") }}</summary><pre><span lang="en">{{ json(item) }}</span></pre></details>
            <button type="button" (click)="launchSynthesis()" [disabled]="busy() || !!pending()">{{ t("Reserve 1 AI unit and request this exact synthesis") }}</button>
          }
          @if (topicSelection(); as item) {
            <p>{{ t("Maximum operator-price estimate USD") }} <span lang="en">{{ item.selection.configuration['estimated_max_cost_usd'] }}</span>{{ t("; this is not a charge or guaranteed provider cost.") }}</p>
            <details><summary>{{ t("Frozen original topic command and canonical digest") }}</summary><pre><span lang="en">{{ json(item) }}</span></pre></details>
            <button type="button" (click)="launchSynthesis()" [disabled]="busy() || !!pending()">{{ t("Reserve 1 AI unit and request these unverified topic hypotheses") }}</button>
          }
          @if (!synthesisJobs().length) { <p>{{ t("No retained synthesis jobs; missing notes or metering are unknown, not zero.") }}</p> }
          @if (synthesisHasMore()) { <p>{{ t("Only the latest 20 synthesis jobs are shown.") }}</p> }
          <ul>@for (job of synthesisJobs(); track job.id) { <li>{{ t("Synthesis job") }} {{ job.id }} · <span lang="en">{{ job.status }}</span> · <span lang="en">{{ job.updated_at }}</span> · <span lang="en">{{ job.error_category }}</span>
            <button type="button" (click)="inspectSynthesis(job.id)" [disabled]="busy() || !!pending()">{{ t("Inspect original synthesis job") }}</button>
            @if (['queued', 'running'].includes(job.status) && !job.cancel_requested) {
              <button type="button" (click)="cancelSynthesis(job.id)" [disabled]="busy() || !!pending()">{{ t("Request synthesis cancellation") }}</button>
            }
          </li> }</ul>
          @if (topics) {
            <h3>{{ t("Compare two saved topic-hypothesis results") }}</h3>
            <p>{{ t("Choose results for two different original page URIs on the same origin. This reads saved results and makes no new AI or site request.") }}</p>
            <form (submit)="compareTopics($event)"><fieldset [disabled]="busy() || !!pending()"><legend>{{ t("Two original unverified samples") }}</legend>
              <label for="competitor-topic-first">{{ t("First saved topic result") }}</label>
              <select id="competitor-topic-first" [value]="firstTopicJobId()" (change)="editTopicPair('previous', $any($event.target).value)">
                <option value="0">{{ t("Choose first result") }}</option>@for (job of synthesisJobs(); track job.id) {
                  @if (job.status === 'succeeded' && !job.cancel_requested) { <option lang="en" [value]="job.id">Job {{ job.id }} · {{ job.updated_at }}</option> }
                }
              </select>
              <label for="competitor-topic-second">{{ t("Second saved topic result") }}</label>
              <select id="competitor-topic-second" [value]="secondTopicJobId()" (change)="editTopicPair('current', $any($event.target).value)">
                <option value="0">{{ t("Choose second result") }}</option>@for (job of synthesisJobs(); track job.id) {
                  @if (job.status === 'succeeded' && !job.cancel_requested) { <option lang="en" [value]="job.id">Job {{ job.id }} · {{ job.updated_at }}</option> }
                }
              </select>
              <button type="submit" [disabled]="!firstTopicJobId() || !secondTopicJobId() || firstTopicJobId() === secondTopicJobId()">{{ t("Read exact original label matches") }}</button>
            </fieldset></form>
          }
        }
        @if (topicComparison(); as item) {
          <h3>{{ t("Literal matches between unverified AI labels — human review required") }}</h3>
          <p>{{ t("Index pairs refer to the first and second original topic lists, starting at zero. Duplicates, case and Unicode spelling are retained. Unmatched indices mean only no identical label in the other returned sample; they do not establish shared or missing actual topics, content gaps, intent, freshness, rankings, whole-page/site coverage or approval. Original heading quotes, collection dates, generation dates and configured model/account provenance remain separate.") }}</p>
          <pre><span lang="en">{{ json(item) }}</span></pre>
        }
        @if (synthesisSelected(); as job) { <p>{{ t("Latest synthesis command status: job") }} {{ job.id }} · <span lang="en">{{ job.status }}</span> · <span lang="en">{{ job.updated_at }}</span>{{ t(". Inspect evidence separately.") }}</p> }
        @if (synthesisDetail(); as item) {
          <h3>{{ t("Original saved AI command and separate nullable provider observations") }}</h3>
          <pre><span lang="en">{{ json(item['selection']) }}</span></pre><pre><span lang="en">{{ json(item['usage']) }}</span></pre>
          <p>{{ t("Attempt/finish times and nullable tokens/duration/estimated or separately reported USD are local provider observations, not original source dates, invoices, customer charges or approval.") }}</p>
          @if (synthesisEvidence(); as item) {
            <h3>{{ t("Original deterministic static facts") }}</h3><pre><span lang="en">{{ json(item[topics ? 'observation' : 'comparison']) }}</span></pre>
            <h3>{{ topics ? t("Unverified indexed topic hypotheses — human review required") : t("Unverified cited AI interpretations — human review required") }}</h3><pre><span lang="en">{{ json(item[topics ? 'topics' : 'interpretations']) }}</span></pre>
            <p>{{ t("Generated") }} <span lang="en">{{ item['generated_at'] }}</span>{{ t(". Exact reference syntax does not prove semantic truth, usefulness or human approval. Selected model/account are configured/requested, not proof of actual provider behavior or live readiness. No publication or remediation is approved.") }}</p>
          } @else { <p>{{ t("No current private synthesis; missing, failed, cancelled and uncertain are not zero conclusions.") }}</p> }
        }
        }
        @if (selected(); as job) {
          <h3>{{ t("Exact job") }} {{ job.id }} · <span lang="en">{{ job.status }}</span></h3>
          @if (evidence(); as item) {
            <pre><span lang="en">{{ json(item) }}</span></pre>
            <p>{{ t("Original UTC microseconds and source SHA are preserved. The opaque SHA binds hidden original actor provenance; it is not reconstructible proof of the current reader's authority or of the raw body.") }}</p>
            @if (formats) {
              <p>{{ t("Eight literal static start-tag counts preserve duplicate and self-closing occurrences. Observed zero differs from whole-null unavailable counts; inherited parser limits can make the whole sample unavailable.") }}</p>
              <p>{{ t("The original URI, collection date and byte digest/size are retained. Counts do not establish rendered formats, actual page types, loaded media, accessibility, search result features, topics, freshness or whole-site coverage. No attributes, text or media URLs are retained. Saved-pair comparison retains these same literal limits. AI processing remains unavailable.") }}</p>
            } @else if (lighthouse) {
              <p>{{ t("One provider-reported lab sample for the original exact URI and device. Request start, server receipt, original provider-reported time, Lighthouse version and response digest/size are preserved separately. Provider time may predate this request.") }}</p>
              <p>{{ t("Four nullable scores and four lab values retain units and observed zero. Missing values and whole-runtime unavailable/null are not zero. These are not field p75 Core Web Vitals, current-site or whole-site measurements, rankings, causality or a security assessment. Saved-pair arithmetic requires a separate deliberate GET; AI synthesis remains unavailable.") }}</p>
            } @else if (dates) {
              <p>{{ t("At most 10 literal article:published_time and article:modified_time declarations are retained in original order, including duplicates and empty values. Values are bounded to 80 characters with explicit truncation. Observed empty differs from unavailable/null.") }}</p>
              <p>{{ t("The original observation time records collection only. Declared values are unverified text, not validated timestamps, publication or change time, page identity, age, freshness, publishing cadence or whole-site evidence. Saved-pair comparison is a separate deliberate read of two originals. AI processing remains unavailable for this family.") }}</p>
            } @else if (destinations) {
              <p>{{ t("At most 10 supported same-origin static href occurrences are retained in original order, including duplicates. Original category counts retain unsupported and other-origin denominators. Observed empty differs from unavailable/null; base-dependent, ambiguous or over-limit documents have no partial inventory.") }}</p>
              <p>{{ t("These literal URI joins are displayed as text. No referenced destination is requested or approved for crawling. They do not establish unique pages, link health, browser visibility, topics, freshness or whole-site structure. Saved-pair comparison is a separate deliberate read of two originals. AI synthesis remains unavailable for this family.") }}</p>
            } @else if (headings) {
              <p>{{ t("At most 10 original literal h1–h6 occurrences are retained in document order, including duplicates and empty text. Each text is bounded to 80 characters with explicit truncation; six counts match the retained occurrences. Observed empty differs from unavailable/null.") }}</p>
              <p>{{ t("These static text levels do not establish browser visibility, semantic outline, accessibility correctness, topics, page identity, publication age, freshness or whole-site structure. Comparisons and AI synthesis remain separate.") }}</p>
            } @else if (links) {
              <p>{{ t("Counts describe HTML-decoded href occurrences from one returned static document, excluding inert/raw-text/foreign descendants. Only bounded no-base URI references are joined against its original URL: same scheme and host origin, other HTTP/HTTPS origin, or unsupported. Unsupported references remain in the inspected denominator. Repeated links are occurrences, not unique pages; no destination, anchor text or rel is retained.") }}</p>
              <p>{{ t("Observed zero differs from unavailable/null. Any active base, ambiguous markup or limit makes the whole summary unavailable. These categories do not establish browser visibility, link health, inbound links or whole-site structure, and remain separate from metadata comparisons and AI synthesis.") }}</p>
            } @else if (schema) {
              <p>{{ t("Only fixed lexical JSON-LD type labels from one returned static document are retained. No context expansion, arbitrary identifiers, properties or schema bodies are retained. An observed empty type list differs from unavailable/null; unrecognized declarations are counted without their text.") }}</p>
              <p>{{ t("These declarations do not prove actual page type, schema validity, applicable required properties, consistency with visible content, rich-result eligibility or search appearance. They are separate from metadata comparisons and AI synthesis, with no whole-site coverage.") }}</p>
            } @else {
            <p>{{ t("Title/description are literal untrusted static text with explicit truncation. Observed empty is different from unavailable/null. Counts concern bounded selected lexical starts only, excluding inert/raw-text/foreign descendants. JSON-LD block count is not schema validity. No topics, publication age, whole-site comparison, performance, traffic, ranking or inbound backlink coverage is established.") }}</p>
            @if (page) { <p>{{ t("The saved URI describes the exact request and returned static bytes. It does not establish page identity, publication or update time, topics or whole-site coverage. AI synthesis remains separate.") }}</p> }
            }
          } @else { <p>{{ t("No current private observation. Failed, cancelled, unknown and missing are not zero facts.") }}</p> }
        }
        @if (dateCandidates(); as item) {
          <h3>{{ t("Stored date syntax candidates — unverified declarations") }}</h3>
          <p>{{ t("Calendar-only literals have no timezone or instant. Supported known-offset literals retain UTC microseconds; later than observation describes that literal instant only. Unsupported and truncated literals stay unavailable. Empty observed declarations differ from a wholly unavailable sample. These candidates do not establish publication or change time, age, freshness, cadence, page identity, whole-site coverage or approval.") }}</p>
          @if (item['candidates'] === null) { <p>{{ t("Original declarations unavailable; candidates unknown.") }}</p> }
          @else {
            <div class="element-counts" role="region" tabindex="0" [attr.aria-label]="t('Stored date syntax candidate table')">
              <table><caption>{{ t("Each original declaration in saved order, including duplicates") }}</caption>
                <thead><tr><th scope="col">{{ t("Declaration index (from zero)") }}</th><th scope="col">{{ t("Syntax state") }}</th><th scope="col">{{ t("Calendar date") }}</th><th scope="col">{{ t("UTC instant") }}</th><th scope="col">{{ t("Literal later than observation") }}</th></tr></thead>
                <tbody>@for (row of candidateRows(item); track row['declaration_index']) {
                  <tr><th scope="row"><span lang="en">{{ row['declaration_index'] }}</span></th><td><span lang="en">{{ row['state'] }}</span></td><td [attr.lang]="row['calendar_date'] === null ? uiLanguage() : 'en'">{{ row['calendar_date'] ?? t("Unavailable") }}</td><td [attr.lang]="row['utc_instant'] === null ? uiLanguage() : 'en'">{{ row['utc_instant'] ?? t("Unavailable") }}</td><td>{{ row['after_observation'] === null ? t("Unavailable") : row['after_observation'] ? t("Yes") : t("No") }}</td></tr>
                }</tbody>
              </table>
            </div>
          }
          <details><summary>{{ t("Original collection and separate syntax candidates") }}</summary><pre><span lang="en">{{ json(item) }}</span></pre></details>
        }
      }
    </section>`,
  styles: `fieldset { display: grid; gap: .6rem; max-width: 48rem; margin-block: 1rem; min-width: 0; }
    select { min-width: 0; max-width: 100%; } pre { white-space: pre-wrap; overflow-wrap: anywhere; } li { margin-block: .8rem; }
    .element-counts { overflow-x: auto; } th, td { padding: .25rem; text-align: left; }`,
})
export class CompetitorRoots implements OnInit {
  readonly documentTitle = signal('Private selected competitor root observations');
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? competitorTurkish[text] ?? text : text; }
  protected schema = false;
  protected links = false;
  protected page = false;
  protected destinations = false;
  protected headings = false;
  protected topics = false;
  protected formats = false;
  protected dates = false;
  protected lighthouse = false;
  protected get supportsSynthesis() { return this.headings && !this.referenceStructureMode() || !this.page && !this.schema && !this.links; }
  private get synthesisMethod() { return this.topics ? 'competitor-heading-topics-v1' : this.headings ? 'competitor-heading-synthesis-v1' : SYNTHESIS_METHOD; }
  private get synthesisSourceMethod() { return this.topics ? 'competitor-heading-topics-source-v1' : this.headings ? 'competitor-heading-ai-source-v1' : 'competitor-static-synthesis-source-v1'; }
  private get synthesisMeaning() { return this.headings ? 'original_static_heading_facts_separate_from_unverified_cited_ai_notes_not_page_topics_content_gaps_approval_freshness_whole_site_or_causal_evidence' : SYNTHESIS_MEANING; }
  private get synthesisSourceMeaning() { return this.headings ? 'original_static_heading_pair_untrusted_ai_input_not_generated_analysis_observed_page_topics_content_gaps_provider_permission_or_whole_site_evidence' : 'original_static_pair_untrusted_ai_input_not_generated_analysis_provider_permission_or_whole_site_evidence'; }

  private get method() { return this.formats ? FORMATS_METHOD : this.lighthouse ? LAB_METHOD : this.dates ? DATES_METHOD : this.destinations ? DESTINATIONS_METHOD : this.headings ? HEADINGS_METHOD : this.page ? PAGE_METHOD : this.links ? LINKS_METHOD : this.schema ? SCHEMA_METHOD : METHOD; }
  readonly ready = signal(false); readonly busy = signal(false); readonly error = signal(''); readonly message = signal('');
  readonly origins = signal<string[]>([]); readonly origin = signal('');
  readonly url = signal('');
  readonly strategy = signal('mobile'); readonly processingPermission = signal(false);
  readonly collectionPermission = signal(false); readonly usePermission = signal(false); readonly storagePermission = signal(false);
  readonly selection = signal<Preview | null>(null); readonly pending = signal<Pending | null>(null);
  readonly jobs = signal<Job[]>([]); readonly hasMore = signal(false); readonly selected = signal<Job | null>(null); readonly evidence = signal<Row | null>(null);
  readonly dateCandidates = signal<Row | null>(null);
  readonly previousJobId = signal(0); readonly currentJobId = signal(0);
  readonly referenceStructureMode = signal(false); readonly referenceInventoryMode = signal(false);
  readonly dateCandidatePairMode = signal(false);
  readonly frozenPair = signal<Pair | null>(null); readonly comparison = signal<Row | null>(null);
  readonly synthesisLoaded = signal(false); readonly models = signal<Model[]>([]); readonly accounts = signal<Account[]>([]);
  readonly modelId = signal(0); readonly accountId = signal(0); readonly aiPermission = signal(false); readonly allowFree = signal(false);
  readonly outputTokens = signal('512'); readonly maxCost = signal('');
  readonly synthesisSelection = signal<SynthesisPreview | null>(null); readonly synthesisJobs = signal<Job[]>([]); readonly synthesisHasMore = signal(false);
  readonly synthesisSelected = signal<Job | null>(null);
  readonly topicJobId = signal(0); readonly topicSelection = signal<TopicPreview | null>(null);
  readonly firstTopicJobId = signal(0); readonly secondTopicJobId = signal(0);
  readonly topicComparison = signal<Row | null>(null);
  readonly synthesisDetail = signal<Row | null>(null); readonly synthesisEvidence = signal<Row | null>(null);
  protected organizationId = 0; protected projectId = 0;
  private epoch = 0; private current: Scope | null = null;
  constructor(private readonly api: AccountApi, private readonly route: ActivatedRoute, private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t(this.documentTitle())} — OrganicSEOOps`));
    destroyRef.onDestroy(() => this.reset());
  }
  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      // Fixed route data chooses the separate permission/command family.
      this.schema = this.route.snapshot.data['competitorObservation'] === 'schema';
      this.links = this.route.snapshot.data['competitorObservation'] === 'links';
      this.destinations = this.route.snapshot.data['competitorObservation'] === 'destinations';
      this.topics = this.route.snapshot.data['competitorObservation'] === 'topics';
      this.headings = this.topics || this.route.snapshot.data['competitorObservation'] === 'headings';
      this.formats = this.route.snapshot.data['competitorObservation'] === 'formats';
      this.dates = this.route.snapshot.data['competitorObservation'] === 'dates';
      this.lighthouse = this.route.snapshot.data['competitorObservation'] === 'lighthouse';
      this.page = this.formats || this.lighthouse || this.dates || this.destinations || this.headings || this.route.snapshot.data['competitorObservation'] === 'page';
      this.documentTitle.set(
        this.lighthouse ? 'Private selected competitor Lighthouse lab sample' :
        this.formats ? 'Private selected competitor static content-element counts' :
        this.dates ? 'Private selected competitor page article date declarations' :
        this.destinations ? 'Private selected competitor page same-origin references' :
        this.topics ? 'Private single-heading topic hypotheses' :
        this.headings ? 'Private selected competitor page literal headings' :
        this.page ? 'Private selected competitor page metadata' :
        this.links ? 'Private selected competitor root link categories' :
        this.schema ? 'Private selected competitor schema labels' :
        'Private selected competitor root observations');
      this.reset(); this.organizationId = Number(params.get('organizationId')); this.projectId = Number(params.get('projectId'));
      void this.load();
    });
  }
  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }
  json(value: unknown) { return JSON.stringify(value, null, 2); }
  private clear() { ++this.epoch; this.busy.set(false); this.selection.set(null); this.pending.set(null); this.selected.set(null); this.evidence.set(null); this.dateCandidates.set(null);
    this.topicSelection.set(null); this.topicJobId.set(0);
    this.firstTopicJobId.set(0); this.secondTopicJobId.set(0); this.topicComparison.set(null);
    this.synthesisSelection.set(null); this.synthesisSelected.set(null); this.synthesisDetail.set(null); this.synthesisEvidence.set(null);
    this.previousJobId.set(0); this.currentJobId.set(0); this.frozenPair.set(null); this.comparison.set(null); this.error.set(''); this.message.set(''); }
  private reset() {
    this.dateCandidatePairMode.set(false);
    this.referenceStructureMode.set(false); this.referenceInventoryMode.set(false);
    this.clear(); this.current = null; this.ready.set(false); this.origins.set([]); this.origin.set(''); this.url.set(''); this.strategy.set('mobile'); this.processingPermission.set(false);
    this.collectionPermission.set(false); this.usePermission.set(false); this.storagePermission.set(false); this.jobs.set([]); this.hasMore.set(false);
    this.synthesisLoaded.set(false); this.models.set([]); this.accounts.set([]); this.modelId.set(0); this.accountId.set(0);
    this.aiPermission.set(false); this.allowFree.set(false); this.outputTokens.set('512'); this.maxCost.set(''); this.synthesisJobs.set([]); this.synthesisHasMore.set(false);
  }
  private lost(): never { this.reset(); this.error.set('Current actor, role, project configuration or credential reference unavailable. Private facts and local uncertainty cleared; stored jobs may still exist. No replay.'); throw new Error(); }
  editOrigin(value: string) { this.clear(); this.origin.set(this.origins().includes(value) ? value : '');
    this.url.set(''); this.processingPermission.set(false);
    this.aiPermission.set(false); this.allowFree.set(false);
    this.collectionPermission.set(false); this.usePermission.set(false); this.storagePermission.set(false); }
  editUrl(value: string) {
    this.clear(); this.url.set(value); this.processingPermission.set(false); this.aiPermission.set(false); this.allowFree.set(false);
    this.collectionPermission.set(false); this.usePermission.set(false); this.storagePermission.set(false);
  }
  editStrategy(value: string) {
    this.clear(); this.strategy.set(['mobile', 'desktop'].includes(value) ? value : '');
    this.processingPermission.set(false); this.collectionPermission.set(false); this.usePermission.set(false); this.storagePermission.set(false);
  }
  editProcessing(value: boolean) { this.clear(); this.processingPermission.set(value === true); }
  previewPage(item: Preview): Row {
    return this.lighthouse ? (item.selection.binding['source'] as Row)['page_source'] as Row : item.selection.binding;
  }
  editPermission(kind: 'collection' | 'use' | 'storage', value: boolean) {
    this.aiPermission.set(false); this.allowFree.set(false);
    this.clear(); (kind === 'collection' ? this.collectionPermission : kind === 'use' ? this.usePermission : this.storagePermission).set(value === true);
  }
  discard() { if (!this.busy()) { this.clear(); this.message.set('Local uncertainty discarded. Stored jobs may still exist; refresh history.'); } }
  editReferenceStructure(value: boolean) { this.clear(); this.referenceInventoryMode.set(false); this.referenceStructureMode.set((this.destinations || this.formats || this.headings && !this.topics) && value === true); }
  editDateCandidatePair(value: boolean) { this.clear(); this.dateCandidatePairMode.set(this.dates && value === true); }
  editReferenceInventory(value: boolean) { this.clear(); this.referenceStructureMode.set(false); this.referenceInventoryMode.set(this.destinations && value === true); }
  private request(data?: Row, id?: number, key?: string, selection = false) {
    return this.formats ? this.api.competitorPageFormats(this.organizationId, this.projectId, data, id, key, selection)
      : this.lighthouse ? this.api.competitorLighthouse(this.organizationId, this.projectId, data, id, key, selection)
      : this.dates ? this.api.competitorPageDates(this.organizationId, this.projectId, data, id, key, selection)
      : this.destinations ? this.api.competitorPageDestinations(this.organizationId, this.projectId, data, id, key, selection)
      : this.headings ? this.api.competitorPageHeadings(this.organizationId, this.projectId, data, id, key, selection)
      : this.page ? this.api.competitorPages(this.organizationId, this.projectId, data, id, key, selection)
      : this.links ? this.api.competitorLinksRoots(this.organizationId, this.projectId, data, id, key, selection)
      : this.schema ? this.api.competitorSchemaRoots(this.organizationId, this.projectId, data, id, key, selection)
      : this.api.competitorRoots(this.organizationId, this.projectId, data, id, key, selection);
  }
  private scope(result: ApiResult, status = 200) {
    if ([401, 403, 404].includes(result.status)) this.lost();
    if (result.status !== status || result.body['organization_id'] !== this.organizationId || result.body['project_id'] !== this.projectId) throw new Error();
    return result.body;
  }
  private async readScope(epoch: number): Promise<Scope | null> {
    const session = await this.api.session(); if (epoch !== this.epoch) return null;
    const data = session.body['data']; const meta = session.body['meta'];
    if (session.status !== 200 || !object(data) || !object(data['user']) || !positive(data['user']['id']) || !object(meta) || meta['is_authenticated'] !== true) this.lost();
    const result = await this.api.projectOnboarding(this.organizationId, this.projectId); if (epoch !== this.epoch) return null;
    const project = result.body['project']; const config = result.body['configuration'];
    if (result.status !== 200 || !object(project) || project['id'] !== this.projectId || project['organization_id'] !== this.organizationId
      || typeof project['role'] !== 'string' || !['owner', 'admin'].includes(project['role']) || typeof project['access_restricted'] !== 'boolean'
      || !canonicalOrigin(project['canonical_origin']) || !Array.isArray(project['aliases']) || project['aliases'].length > 100
      || !project['aliases'].every(canonicalOrigin) || new Set(project['aliases']).size !== project['aliases'].length
      || !object(config) || config['project_id'] !== this.projectId || config['canonical_origin'] !== project['canonical_origin']
      || !positive(config['revision']) || !dated(config['updated_at'])
      || typeof config['source_choice'] !== 'string' || !['undecided', 'connect_search_console', 'import_search_console', 'skip'].includes(config['source_choice'])
      || !Array.isArray(config['competitor_origins']) || config['competitor_origins'].length > 50
      || !config['competitor_origins'].every(canonicalOrigin) || new Set(config['competitor_origins']).size !== config['competitor_origins'].length) this.lost();
    const scope = { actor: Number(data['user']['id']), project: Object.fromEntries(['id', 'organization_id', 'role', 'access_restricted', 'canonical_origin', 'aliases'].map(key => [key, project[key]])),
      configuration: Object.fromEntries(['project_id', 'canonical_origin', 'revision', 'updated_at', 'source_choice', 'competitor_origins'].map(key => [key, config[key]])) };
    if (this.current && !same(scope, this.current)) this.lost();
    return structuredClone(scope);
  }
  private job(value: unknown, synthesis = false): Job {
    if (!exact(value, ['id', 'status', 'created_at', 'updated_at', 'cancel_requested', 'estimate_units', 'error_category']) || !positive(value['id'])
      || typeof value['status'] !== 'string' || !['queued', 'running', 'succeeded', 'failed', 'cancelled'].includes(value['status']) || !ordered(value['created_at'], value['updated_at'])
      || typeof value['cancel_requested'] !== 'boolean' || value['estimate_units'] !== 1 || typeof value['error_category'] !== 'string'
      || ![...ERRORS, ...(synthesis ? SYNTHESIS_ERRORS : this.lighthouse ? LAB_ERRORS : [])].includes(value['error_category'])) throw new Error();
    return structuredClone(value) as Job;
  }
  private list(result: ApiResult, key: string | null = null, synthesis = false) {
    const row = this.scope(result);
    if (!exact(row, ['organization_id', 'project_id', 'jobs', 'has_more', 'lookup']) || !Array.isArray(row['jobs']) || row['jobs'].length > 20
      || typeof row['has_more'] !== 'boolean' || row['lookup'] !== key) throw new Error();
    const jobs = row['jobs'].map(value => this.job(value, synthesis));
    if (jobs.some((job, i) => i > 0 && jobs[i - 1].id <= job.id) || row['has_more'] && jobs.length !== 20 || key !== null && (jobs.length > 1 || row['has_more'])) throw new Error();
    return { jobs, more: row['has_more'] };
  }
  async load() {
    if (this.busy() || this.pending()) return;
    this.reset(); if (!positive(this.organizationId) || !positive(this.projectId)) { this.error.set('Choose an authorized exact organization and project.'); return; }
    const epoch = this.epoch; this.busy.set(true);
    try {
      const scope = await this.readScope(epoch); if (!scope || epoch !== this.epoch) return; this.current = scope;
      // The private history endpoint independently checks current verified-account manager authority.
      const result = await this.request(); if (epoch !== this.epoch) return; const history = this.list(result);
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const own = [scope.project['canonical_origin'], ...scope.project['aliases'] as string[]].map(value => new URL(String(value)).hostname);
      this.origins.set((scope.configuration['competitor_origins'] as string[]).filter(value => !own.includes(new URL(value).hostname)));
      this.jobs.set(history.jobs); this.hasMore.set(history.more); this.ready.set(true);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Current saved competitor source and private history unavailable.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private data(): Row {
    if (!this.ready() || !this.origins().includes(this.origin()) || !this.collectionPermission() || !this.usePermission() || !this.storagePermission()) throw new Error();
    if (this.lighthouse && (!this.processingPermission() || !['mobile', 'desktop'].includes(this.strategy()))) throw new Error();
    if (this.page && !canonicalPageUrl(this.url(), this.origin())) throw new Error();
    return { origin: this.origin(), ...(this.page ? { url: this.url() } : {}), ...(this.lighthouse ? { strategy: this.strategy(), provider_processing_permission: true } : {}), collection_permission: true, use_permission: true, storage_permission: true };
  }
  private async labPage(value: unknown, data: Row): Promise<Row> {
    if (!exact(value, ['method_version', 'source', 'performance_credential', 'interpretation', 'selection_sha256'])
      || value['method_version'] !== 'competitor-lighthouse-selection-v1' || value['interpretation'] !== LAB_SELECTION_MEANING
      || !digest(value['selection_sha256'])) throw new Error();
    const source = value['source'], credential = value['performance_credential'];
    if (!exact(source, ['method_version', 'provider', 'page_source', 'strategy', 'provider_processing_permission', 'interpretation', 'source_sha256'])
      || source['method_version'] !== 'competitor-lighthouse-source-v1' || source['provider'] !== 'google_pagespeed_insights'
      || source['strategy'] !== data['strategy'] || typeof source['strategy'] !== 'string' || !['mobile', 'desktop'].includes(source['strategy'])
      || source['provider_processing_permission'] !== true || data['provider_processing_permission'] !== true
      || source['interpretation'] !== LAB_SOURCE_MEANING || !digest(source['source_sha256'])
      || !exact(credential, ['source', 'revision', 'state'])) throw new Error();
    if (credential['source'] === 'environment') {
      if (credential['revision'] !== '' || credential['state'] !== 'unverified') throw new Error();
    } else if (typeof credential['source'] !== 'string' || !['organization', 'platform'].includes(credential['source']) || credential['state'] !== 'active'
      || !dated(credential['revision']) || typeof credential['revision'] !== 'string'
      || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?\+00:00$/.test(credential['revision'])) throw new Error();
    if (await selectionDigest(Object.fromEntries(Object.entries(source).filter(([key]) => key !== 'source_sha256'))) !== source['source_sha256']
      || await selectionDigest(Object.fromEntries(Object.entries(value).filter(([key]) => key !== 'selection_sha256'))) !== value['selection_sha256']
      || new TextEncoder().encode(JSON.stringify(value)).length > 8192 || !object(source['page_source'])) throw new Error();
    return source['page_source'];
  }
  private async readPreview(data: Row, epoch: number): Promise<Preview | null> {
    if (!await this.readScope(epoch) || epoch !== this.epoch) return null;
    const result = await this.request(data, undefined, undefined, true); if (epoch !== this.epoch) return null; const row = this.scope(result);
    const selection = row['selection'];
    if (!exact(row, ['organization_id', 'project_id', 'selection', 'selection_digest', 'estimate_units']) || row['estimate_units'] !== 1
      || !exact(selection, ['method', 'binding', 'use_permission', 'storage_permission']) || selection['method'] !== this.method
      || selection['use_permission'] !== true || selection['storage_permission'] !== true || !digest(row['selection_digest'])) throw new Error();
    const binding = selection['binding'];
    const b = this.lighthouse ? await this.labPage(binding, data) : binding; const config = this.current!.configuration;
    if (!exact(b, ['method_version', 'organization_id', 'project_id', 'actor_id', 'origin', 'hostname', 'scope_kind', 'collection_permission',
      'configuration_revision', 'configuration_updated_at', 'source_sha256', 'interpretation', ...(this.page ? ['url'] : [])])
      || b['method_version'] !== (this.page ? 'competitor-page-source-v1' : 'competitor-source-v1')
      || b['organization_id'] !== this.organizationId || b['project_id'] !== this.projectId || b['actor_id'] !== this.current!.actor
      || b['origin'] !== data['origin'] || !this.origins().includes(String(b['origin'])) || b['hostname'] !== new URL(String(b['origin'])).hostname
      || b['scope_kind'] !== (this.page ? 'selected_competitor_exact_same_origin_default_port_nonroot_uri_no_query_fragment' : 'selected_competitor_hostname_default_http_https_only')
      || this.page && (b['url'] !== data['url'] || !canonicalPageUrl(b['url'], String(b['origin']))) || b['collection_permission'] !== true
      || b['configuration_revision'] !== config['revision'] || b['configuration_updated_at'] !== config['updated_at']
      || !digest(b['source_sha256']) || b['interpretation'] !== (this.page ? PAGE_SOURCE_MEANING : SOURCE_MEANING)) throw new Error();
    if (await selectionDigest(selection) !== row['selection_digest']) throw new Error();
    if (!await this.readScope(epoch) || epoch !== this.epoch) return null;
    return structuredClone({ selection, selection_digest: row['selection_digest'] }) as Preview;
  }
  async preview(event?: Event) {
    event?.preventDefault(); if (this.busy() || this.pending()) return;
    this.clear(); const epoch = this.epoch; this.busy.set(true);
    try { const info = await this.readPreview(this.data(), epoch); if (epoch === this.epoch && info) this.selection.set(info); }
    catch { if (epoch === this.epoch) this.error.set('Exact current source, three declarations or collection allowance unavailable. No collection command sent.'); }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async launch() {
    if (this.busy() || this.pending() || !this.selection()) return;
    const preview = structuredClone(this.selection()!); const data = this.data(); const key = crypto.randomUUID();
    await this.send({ preview, key, data: { ...data, selection_digest: preview.selection_digest, idempotency_key: key } });
  }
  private async send(command: Pending) {
    this.clear(); const epoch = this.epoch; this.busy.set(true); let sent = false; let acknowledged = false;
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      if (!command.jobId) {
        const fresh = await this.readPreview(Object.fromEntries(['origin', 'collection_permission', 'use_permission', 'storage_permission', ...(this.page ? ['url'] : []), ...(this.lighthouse ? ['strategy', 'provider_processing_permission'] : [])].map(key => [key, command.data[key]])), epoch);
        if (epoch !== this.epoch) return; if (!fresh || !same(fresh, command.preview)) { if (this.lighthouse) this.lost(); throw new Error(); }
      }
      this.pending.set(structuredClone(command)); sent = true;
      const result = await this.request(command.data, command.jobId); if (epoch !== this.epoch) return;
      const row = this.scope(result, 202); if (!exact(row, ['organization_id', 'project_id', 'job'])) throw new Error();
      const job = this.job(row['job']); if (command.jobId && job.id !== command.jobId) throw new Error();
      acknowledged = true;
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      if (this.lighthouse && !command.jobId) {
        const latest = await this.readPreview(Object.fromEntries(['origin', 'url', 'strategy', 'provider_processing_permission', 'collection_permission', 'use_permission', 'storage_permission'].map(key => [key, command.data[key]])), epoch);
        if (epoch !== this.epoch) return; if (!latest || !same(latest, command.preview)) this.lost();
      }
      this.pending.set(null); this.selected.set(job); this.message.set('Exact command acknowledged. Refresh metadata or deliberately inspect private evidence.');
    } catch {
      if (epoch === this.epoch) {
        if (this.lighthouse && acknowledged && !command.jobId) { this.reset(); this.error.set('Current original source or credential unavailable after acknowledgment. Private state and uncertainty cleared; a stored job may exist. No replay.'); return; }
        if (sent) { try { if (!await this.readScope(epoch) || epoch !== this.epoch) return; } catch {
          if (epoch === this.epoch) { this.reset(); this.error.set('Current command scope unavailable. Local uncertainty cleared; stored jobs may still exist. No replay.'); } return;
        } }
        this.error.set(sent ? 'Command outcome uncertain. Use the frozen exact GET lookup; no replay.' : 'Current selection changed. No collection command sent; preview again.');
      }
    } finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async cancel(id: number) {
    if (this.busy() || this.pending() || !this.ready() || !this.jobs().some(job => job.id === id && ['queued', 'running'].includes(job.status) && !job.cancel_requested)) return;
    await this.send({ data: {}, key: '', preview: null, jobId: id });
  }
  private detail(result: ApiResult, id: number) {
    const row = this.scope(result); if (!exact(row, ['organization_id', 'project_id', 'job', 'evidence'])) throw new Error();
    const job = this.job(row['job']); if (job.id !== id) throw new Error();
    const evidence = row['evidence'];
    if (job.status === 'succeeded' ? evidence === null : evidence !== null) throw new Error();
    if (evidence !== null) this.validateEvidence(evidence, job);
    return { job, evidence: evidence === null ? null : structuredClone(evidence) as Row };
  }
  async reconcile() {
    if (this.busy() || !this.pending()) return;
    if (this.pending()!.synthesis) { await this.reconcileSynthesis(); return; }
    const command = structuredClone(this.pending()!); const epoch = ++this.epoch; this.busy.set(true); this.error.set(''); this.message.set(''); this.selected.set(null); this.evidence.set(null);
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const result = await this.request(undefined, command.jobId, command.jobId ? undefined : command.key); if (epoch !== this.epoch) return;
      const job = command.jobId ? this.detail(result, command.jobId).job : this.list(result, command.key).jobs[0];
      if (command.jobId && !job.cancel_requested && !['cancelled', 'succeeded', 'failed'].includes(job.status)) throw new Error();
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      if (!job) { this.message.set('No saved own-actor request at this lookup. Outcome remains uncertain; no replay.'); return; }
      this.pending.set(null); this.selected.set(job); this.message.set('Exact original command reconciled. No POST replayed.');
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Exact lookup/current source unavailable. Local uncertainty cleared; stored jobs may still exist. No replay.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async inspect(id: number) {
    if (this.busy() || this.pending() || !this.ready() || !this.jobs().some(job => job.id === id)) return;
    this.clear(); const epoch = this.epoch; this.busy.set(true);
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const result = await this.request(undefined, id); if (epoch !== this.epoch) return; const info = this.detail(result, id);
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      if (this.lighthouse && info.evidence) {
        // Recheck the owning API's current key/source fence after the separate client scope check.
        const confirmed = await this.request(undefined, id); if (epoch !== this.epoch) return;
        if (!same(this.detail(confirmed, id), info)) this.lost();
        if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      }
      this.selected.set(info.job); this.evidence.set(info.evidence);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Exact private observation/current source unavailable. Missing is not zero facts.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  candidateRows(item: Row) { return item['candidates'] as Row[]; }
  private validateDateCandidates(result: ApiResult, original: Job) {
    const row = this.scope(result);
    if (!exact(row, ['organization_id', 'project_id', 'job', 'candidates']) || !same(this.job(row['job']), original)) throw new Error();
    const item = row['candidates'];
    if (!exact(item, ['job_id', 'collection', 'source_current', 'method_version', 'candidates', 'interpretation'])
      || item['method_version'] !== 'competitor-date-literal-candidates-v1' || item['interpretation'] !== DATE_CANDIDATE_MEANING
      || new TextEncoder().encode(JSON.stringify(item)).length > 24576) throw new Error();
    this.validateEvidence({ job_id: item['job_id'], collection: item['collection'], source_current: item['source_current'] }, original);
    const evidence = (item['collection'] as Row)['evidence'] as Row;
    this.validateDateCandidateList(evidence, item['candidates']);
    return structuredClone(item);
  }
  private validateDateCandidateList(evidence: Row, candidates: unknown) {
    const declarations = evidence['declarations'] as Row[] | null;
    if (declarations === null) { if (candidates !== null) throw new Error(); }
    else {
      if (!Array.isArray(candidates) || candidates.length !== declarations.length) throw new Error();
      for (const [index, literal] of declarations.entries()) {
        const candidate = candidates[index];
        if (!exact(candidate, ['declaration_index', 'state', 'calendar_date', 'utc_instant', 'after_observation']) || candidate['declaration_index'] !== index) throw new Error();
        const value = String(literal['value']);
        const instant = !literal['truncated'] && !value.endsWith('-00:00') ? providerDate(value)?.instant : undefined;
        const supportedInstant = instant !== undefined && instant >= microseconds('0001-01-01T00:00:00Z')! && instant <= microseconds('9999-12-31T23:59:59.999999Z')!;
        if (literal['truncated'] || calendar(value) === null && !supportedInstant) {
          if (candidate['state'] !== (literal['truncated'] ? 'truncated_literal' : 'unsupported_literal')
            || ['calendar_date', 'utc_instant', 'after_observation'].some(key => candidate[key] !== null)) throw new Error();
        } else if (calendar(value) !== null) {
          if (candidate['state'] !== 'calendar_literal' || candidate['calendar_date'] !== value || candidate['utc_instant'] !== null || candidate['after_observation'] !== null) throw new Error();
        } else if (candidate['state'] !== 'offset_literal' || candidate['calendar_date'] !== null
          || typeof candidate['utc_instant'] !== 'string' || !/\.\d{6}\+00:00$/.test(candidate['utc_instant']) || microseconds(candidate['utc_instant']) !== instant
          || candidate['after_observation'] !== (instant! > microseconds(evidence['observed_at'])!)) throw new Error();
      }
    }
  }
  async inspectDateCandidates(id: number) {
    const saved = this.jobs().find(job => job.id === id && job.status === 'succeeded' && !job.cancel_requested);
    if (!this.dates || this.busy() || this.pending() || !this.ready() || !saved) return;
    const original = structuredClone(saved); this.clear(); const epoch = this.epoch; this.busy.set(true);
    const history = async () => {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return false;
      const current = await this.request(); if (epoch !== this.epoch) return false;
      if (!same(original, this.list(current).jobs.find(job => job.id === id))) throw new Error();
      return !!await this.readScope(epoch) && epoch === this.epoch;
    };
    try {
      if (!await history()) return;
      const first = await this.api.competitorPageDateCandidates(this.organizationId, this.projectId, id); if (epoch !== this.epoch) return;
      const item = this.validateDateCandidates(first, original);
      if (!await history()) return;
      const final = await this.api.competitorPageDateCandidates(this.organizationId, this.projectId, id); if (epoch !== this.epoch) return;
      if (!same(item, this.validateDateCandidates(final, original))) throw new Error();
      if (!await history()) return;
      this.selected.set(original); this.evidence.set({ job_id: item['job_id'], collection: item['collection'], source_current: true }); this.dateCandidates.set(item);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Current original Date candidates unavailable. Private state cleared; unknown is not zero.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  editPair(kind: 'previous' | 'current', value: string) {
    this.aiPermission.set(false); this.allowFree.set(false);
    const previous = this.previousJobId(); const current = this.currentJobId(); this.clear();
    const id = Number(value); const valid = /^[1-9][0-9]*$/.test(value);
    const selected = valid && positive(id) && this.jobs().some(job => job.id === id && job.status === 'succeeded' && !job.cancel_requested) ? id : 0;
    this.previousJobId.set(kind === 'previous' ? selected : previous); this.currentJobId.set(kind === 'current' ? selected : current);
  }
  private async readPair(pair: Pair, epoch: number) {
    if (!await this.readScope(epoch) || epoch !== this.epoch) return false;
    const result = await this.request(); if (epoch !== this.epoch) return false;
    const history = this.list(result);
    if (![pair.previous, pair.current].every(job => same(job, history.jobs.find(row => row.id === job.id)))) throw new Error();
    return !!await this.readScope(epoch) && epoch === this.epoch;
  }
  selectedModel() { return this.models().find(row => row.id === this.modelId()); }
  matchingAccounts() { return this.accounts().filter(row => row.provider_id === this.selectedModel()?.provider_id); }
  editSynthesis(kind: 'permission' | 'model' | 'account' | 'tokens' | 'cost' | 'free', value: string | boolean) {
    const previous = this.previousJobId(), current = this.currentJobId(), topic = this.topicJobId(); this.clear(); this.topicJobId.set(topic);
    this.previousJobId.set(previous); this.currentJobId.set(current);
    if (kind === 'permission') this.aiPermission.set(value === true);
    if (kind === 'free') this.allowFree.set(value === true);
    if (kind === 'model') {
      this.modelId.set(this.models().some(row => String(row.id) === value) ? Number(value) : 0);
      this.accountId.set(0); this.allowFree.set(false);
    }
    if (kind === 'account') this.accountId.set(this.matchingAccounts().some(row => String(row.id) === value) ? Number(value) : 0);
    if (kind === 'tokens') this.outputTokens.set(String(value));
    if (kind === 'cost') this.maxCost.set(String(value));
  }
  private synthesisRequest(data?: Row, id?: number, key?: string, preview = false) {
    return this.topics ? this.api.competitorHeadingTopics(this.organizationId, this.projectId, data, id, key, preview)
      : this.headings ? this.api.competitorHeadingSyntheses(this.organizationId, this.projectId, data, id, key, preview)
      : this.api.competitorSyntheses(this.organizationId, this.projectId, data, id, key, preview);
  }
  private async catalog(epoch: number) {
    const result = await this.api.projectAITextCatalog(this.organizationId, this.projectId); if (epoch !== this.epoch) return null;
    if ([401, 403, 404].includes(result.status)) this.lost(); const row = result.body;
    if (result.status !== 200 || !exact(row, ['models', 'accounts', 'has_more', 'estimate_units', 'cost_status'])
      || !Array.isArray(row['models']) || row['models'].length > 100 || !Array.isArray(row['accounts']) || row['accounts'].length > 200
      || typeof row['has_more'] !== 'boolean' || row['estimate_units'] !== 1 || row['cost_status'] !== 'unknown') throw new Error();
    const text = (value: unknown, limit: number) => typeof value === 'string' && value.length > 0 && [...value].length <= limit;
    const models = row['models'].map(value => {
      if (!exact(value, ['id', 'provider_id', 'name', 'identifier', 'max_output_tokens', 'access_tier', 'price_known', 'privacy_policy_url'])
        || !positive(value['id']) || !positive(value['provider_id']) || !text(value['name'], 120) || !text(value['identifier'], 160)
        || value['max_output_tokens'] !== null && !positive(value['max_output_tokens']) || typeof value['price_known'] !== 'boolean'
        || typeof value['access_tier'] !== 'string' || !['standard', 'free', 'unknown'].includes(value['access_tier'])
        || typeof value['privacy_policy_url'] !== 'string' || value['privacy_policy_url'] !== '' && !safeUrl(value['privacy_policy_url'])) throw new Error();
      return structuredClone(value) as Model;
    });
    const accounts = row['accounts'].map(value => {
      if (!exact(value, ['id', 'provider_id', 'label', 'source']) || !positive(value['id']) || !positive(value['provider_id'])
        || !text(value['label'], 120) || typeof value['source'] !== 'string' || !['platform', 'organization'].includes(value['source'])) throw new Error();
      return structuredClone(value) as Account;
    });
    if (new Set(models.map(row => row.id)).size !== models.length || new Set(accounts.map(row => row.id)).size !== accounts.length) throw new Error();
    return { models, accounts };
  }
  async loadSyntheses() {
    if (!this.supportsSynthesis) return;
    if (this.busy() || this.pending() || !this.ready()) return;
    this.clear(); this.aiPermission.set(false); this.allowFree.set(false); this.modelId.set(0); this.accountId.set(0);
    this.synthesisLoaded.set(false); this.models.set([]); this.accounts.set([]); this.synthesisJobs.set([]); this.synthesisHasMore.set(false);
    const epoch = this.epoch; this.busy.set(true);
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const result = await this.synthesisRequest(); if (epoch !== this.epoch) return; const history = this.list(result, null, true);
      const choices = await this.catalog(epoch); if (!choices || !await this.readScope(epoch) || epoch !== this.epoch) return;
      this.models.set(choices.models); this.accounts.set(choices.accounts); this.synthesisJobs.set(history.jobs); this.synthesisHasMore.set(history.more); this.synthesisLoaded.set(true);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Current synthesis history or model catalog unavailable. Private state cleared.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private synthesisInput(value: unknown): Row {
    if (!exact(value, this.topics ? TOPIC_INPUT_FIELDS : INPUT_FIELDS)
      || !(this.topics ? ['job_id', 'model_id', 'account_id'] : ['previous_job_id', 'current_job_id', 'model_id', 'account_id']).every(key => positive(value[key]))
      || !this.topics && value['previous_job_id'] === value['current_job_id'] || value['ai_processing_permission'] !== true || typeof value['allow_free'] !== 'boolean'
      || !Number.isSafeInteger(value['max_output_tokens']) || Number(value['max_output_tokens']) < 128 || Number(value['max_output_tokens']) > 2048
      || typeof value['max_cost_usd'] !== 'string' || !/^[0-9]{1,3}(\.[0-9]{1,6})?$/.test(value['max_cost_usd'])
      || Number(value['max_cost_usd']) <= 0 || Number(value['max_cost_usd']) > 100) throw new Error();
    return structuredClone(value);
  }
  private validateSynthesisSelection(value: unknown, data?: Row): asserts value is SynthesisPreview['selection'] {
    if (!exact(value, ['input', 'configuration'])) throw new Error(); const input = this.synthesisInput(value['input']); const c = value['configuration'];
    const money = (value: unknown) => typeof value === 'string' && /^[0-9]{1,6}(\.[0-9]{1,6})?$/.test(value);
    if (data && !same(input, data) || !exact(c, CONFIG_FIELDS) || c['method'] !== this.synthesisMethod || c['organization_id'] !== this.organizationId
      || c['project_id'] !== this.projectId || !positive(c['actor_id']) || !positive(c['provider_id']) || c['account_id'] !== input['account_id']
      || c['source_method'] !== this.synthesisSourceMethod || c['routing_source'] !== 'explicit'
      || c['routing_policy_id'] !== null || c['routing_policy_revision'] !== null || c['fallback_index'] !== 0 || c['timeout_seconds'] !== 30
      || typeof c['model_identifier'] !== 'string' || !c['model_identifier'] || c['model_identifier'].length > 160 || !dated(c['model_revision'])
      || c['credential_revision'] !== '' && !dated(c['credential_revision'])
      || typeof c['model_access_tier'] !== 'string' || !['standard', 'free'].includes(c['model_access_tier']) || input['allow_free'] !== (c['model_access_tier'] === 'free')
      || (c['provider_kind'] === 'openai' ? c['provider_base_url'] !== '' : c['provider_kind'] !== 'openai_compatible'
        || typeof c['provider_base_url'] !== 'string' || !safeUrl(c['provider_base_url']))
      || !['input_price_usd_per_million', 'output_price_usd_per_million', 'estimated_max_cost_usd'].every(key => money(c[key]))
      || Number(c['estimated_max_cost_usd']) > Number(input['max_cost_usd'])
      || !['source_selection_digest', 'source_metadata_sha256', 'caller_source_sha256', 'model_selection_sha256', 'prompt_sha256', 'output_schema_sha256'].every(key => digest(c[key]))) throw new Error();
  }
  private async synthesisPair(data: Row, epoch: number): Promise<Pair | null> {
    if (!await this.readScope(epoch) || epoch !== this.epoch) return null;
    const pair = {} as Pair;
    for (const key of ['previous', 'current'] as const) {
      const id = Number(data[key + '_job_id']); const result = await this.request(undefined, id); if (epoch !== this.epoch) return null;
      pair[key] = this.detail(result, id).job;
    }
    return pair;
  }
  private async readSynthesisPreview(data: Row, pair: Pair, epoch: number): Promise<SynthesisPreview | null> {
    if (!await this.readScope(epoch) || epoch !== this.epoch) return null;
    const before = await this.synthesisPair(data, epoch); if (!before || epoch !== this.epoch) return null; if (!same(before, pair)) throw new Error();
    const choices = await this.catalog(epoch); if (!choices || epoch !== this.epoch) return null;
    const model = choices.models.find(row => row.id === data['model_id']), account = choices.accounts.find(row => row.id === data['account_id']);
    if (!model || !account || model.provider_id !== account.provider_id || !model.price_known || model.access_tier === 'unknown'
      || data['allow_free'] !== (model.access_tier === 'free') || model.access_tier === 'free' && !model.privacy_policy_url
      || model.max_output_tokens !== null && Number(data['max_output_tokens']) > model.max_output_tokens) throw new Error();
    const original = this.headings ? await this.api.competitorPageHeadingsComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
      : await this.api.competitorRootComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id);
    if (epoch !== this.epoch) return null; const originalRow = this.scope(original);
    if (!exact(originalRow, ['organization_id', 'project_id', 'comparison'])) throw new Error();
    const comparison = structuredClone(originalRow['comparison']); this.validateComparison(comparison, pair);
    const result = await this.synthesisRequest(data, undefined, undefined, true); if (epoch !== this.epoch) return null; const row = this.scope(result);
    if (!exact(row, ['organization_id', 'project_id', 'selection', 'selection_digest', 'estimate_units']) || row['estimate_units'] !== 1 || !digest(row['selection_digest'])) throw new Error();
    const selection = structuredClone(row['selection']); this.validateSynthesisSelection(selection, data); const c = selection.configuration;
    const sourceDigest = await selectionDigest({ method_version: this.synthesisSourceMethod, organization_id: this.organizationId,
      project_id: this.projectId, source_current: true, ai_processing_permission: true, comparison,
      interpretation: this.synthesisSourceMeaning });
    if (c['actor_id'] !== this.current!.actor || c['provider_id'] !== model.provider_id || c['model_identifier'] !== model.identifier
      || c['model_access_tier'] !== model.access_tier || c['source_selection_digest'] !== sourceDigest
      || await selectionDigest(selection) !== row['selection_digest']) throw new Error();
    const after = await this.synthesisPair(data, epoch); const latest = await this.catalog(epoch);
    if (!after || !latest || !await this.readScope(epoch) || epoch !== this.epoch) return null;
    if (!same(pair, after) || !same(model, latest.models.find(row => row.id === model.id)) || !same(account, latest.accounts.find(row => row.id === account.id))) throw new Error();
    return { selection, selection_digest: String(row['selection_digest']), comparison: comparison as Row };
  }
  editTopicJob(value: string) {
    this.clear(); this.aiPermission.set(false); this.allowFree.set(false);
    this.topicJobId.set(this.jobs().some(job => String(job.id) === value && job.status === 'succeeded' && !job.cancel_requested) ? Number(value) : 0);
  }
  editTopicPair(kind: 'previous' | 'current', value: string) {
    const first = this.firstTopicJobId(), second = this.secondTopicJobId(); this.clear();
    const id = Number(value);
    const selected = this.topics && /^[1-9][0-9]*$/.test(value) && positive(id)
      && this.synthesisJobs().some(job => job.id === id && job.status === 'succeeded' && !job.cancel_requested) ? id : 0;
    this.firstTopicJobId.set(kind === 'previous' ? selected : first); this.secondTopicJobId.set(kind === 'current' ? selected : second);
  }
  private async topicPairHistory(pair: Pair, epoch: number) {
    if (!await this.readScope(epoch) || epoch !== this.epoch) return false;
    const result = await this.synthesisRequest(); if (epoch !== this.epoch) return false;
    const history = this.list(result, null, true);
    if (![pair.previous, pair.current].every(job => same(job, history.jobs.find(row => row.id === job.id)))) throw new Error();
    return !!await this.readScope(epoch) && epoch === this.epoch;
  }
  private async topicPairDetails(pair: Pair, epoch: number) {
    if (!await this.topicPairHistory(pair, epoch)) return null;
    const details: Row[] = [];
    for (const job of [pair.previous, pair.current]) {
      const result = await this.synthesisRequest(undefined, job.id); if (epoch !== this.epoch) return null;
      const row = await this.synthesisDetailRow(result, job.id); if (epoch !== this.epoch) return null;
      if (!same(row['job'], job)) throw new Error();
      const selection = row['selection'] as TopicPreview['selection'];
      const source = await this.topicSource(Number(selection.input['job_id']), epoch); if (!source || epoch !== this.epoch) return null;
      if (await selectionDigest({ method_version: this.synthesisSourceMethod, organization_id: this.organizationId,
        project_id: this.projectId, source_current: true, ai_processing_permission: true, observation: source.observation,
        interpretation: TOPIC_SOURCE_MEANING }) !== selection.configuration['source_selection_digest']) throw new Error();
      this.validateTopicEvidence(row, { selection, selection_digest: String(row['selection_digest']), source });
      details.push(row);
    }
    return await this.topicPairHistory(pair, epoch) ? details : null;
  }
  async compareTopics(event?: Event) {
    event?.preventDefault();
    if (!this.topics || this.busy() || this.pending() || !this.ready() || !this.synthesisLoaded()) return;
    const first = this.synthesisJobs().find(job => job.id === this.firstTopicJobId()), second = this.synthesisJobs().find(job => job.id === this.secondTopicJobId());
    if (!first || !second || first.id === second.id || [first, second].some(job => job.status !== 'succeeded' || job.cancel_requested)) return;
    const pair = structuredClone({ previous: first, current: second }); this.clear();
    this.firstTopicJobId.set(first.id); this.secondTopicJobId.set(second.id); const epoch = this.epoch; this.busy.set(true);
    try {
      const details = await this.topicPairDetails(pair, epoch); if (!details || epoch !== this.epoch) return;
      const result = await this.api.competitorHeadingTopicsComparison(this.organizationId, this.projectId, first.id, second.id);
      if (epoch !== this.epoch) return; const row = this.scope(result);
      if (!exact(row, ['organization_id', 'project_id', 'comparison'])) throw new Error();
      const original = structuredClone(row['comparison']); this.validateTopicComparison(original, details);
      const current = await this.topicPairDetails(pair, epoch); if (!current || epoch !== this.epoch) return;
      if (!same(details, current)) throw new Error();
      const result2 = await this.api.competitorHeadingTopicsComparison(this.organizationId, this.projectId, first.id, second.id);
      if (epoch !== this.epoch) return; const confirmed = this.scope(result2);
      if (!exact(confirmed, ['organization_id', 'project_id', 'comparison']) || !same(original, confirmed['comparison'])) throw new Error();
      this.validateTopicComparison(confirmed['comparison'], current);
      if (!await this.topicPairHistory(pair, epoch) || epoch !== this.epoch) return;
      this.topicComparison.set(original as Row);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Current original topic samples, models or private scope unavailable. Comparison cleared; unmatched is not missing topics. No new request or replay.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateTopicComparison(value: unknown, details: Row[]) {
    if (!exact(value, ['method_version', 'organization_id', 'project_id', 'source_current', 'samples', 'exact_label_match_indices', 'unmatched_topic_indices', 'interpretation'])
      || value['method_version'] !== 'competitor-heading-topic-label-pair-v1' || value['organization_id'] !== this.organizationId || value['project_id'] !== this.projectId
      || value['source_current'] !== true || value['interpretation'] !== TOPIC_PAIR_MEANING || new TextEncoder().encode(JSON.stringify(value)).length > 102400
      || !same(value['samples'], details.map(row => row['evidence']))) throw new Error();
    const samples = details.map(row => (row['evidence'] as Row)['synthesis'] as Row);
    const urls = samples.map(sample => ((sample['observation'] as Row)['collection'] as Row)['url'] as string);
    if (urls[0] === urls[1] || new URL(urls[0]).origin !== new URL(urls[1]).origin) throw new Error();
    const labels = samples.map(sample => (sample['topics'] as Row[]).map(topic => topic['label']));
    const matches = labels[0].flatMap((label, first) => labels[1].flatMap((other, second) => label === other ? [[first, second]] : []));
    const unmatched = labels.map((side, index) => side.flatMap((label, i) => labels[1 - index].includes(label) ? [] : [i]));
    if (!same(value['exact_label_match_indices'], matches) || !same(value['unmatched_topic_indices'], unmatched)) throw new Error();
  }
  private async topicSource(id: number, epoch: number): Promise<TopicSource | null> {
    const result = await this.request(undefined, id); if (epoch !== this.epoch) return null;
    const item = this.detail(result, id);
    if (item.job.status !== 'succeeded' || item.job.cancel_requested || !item.evidence) throw new Error();
    const facts = (item.evidence['collection'] as Row)['evidence'] as Row;
    if (facts['state'] !== 'observed' || !(facts['headings'] as Row[]).some(row => row['text'] && row['truncated'] === false)) throw new Error();
    return { job: item.job, observation: item.evidence };
  }
  private async readTopicPreview(data: Row, original: Job, epoch: number): Promise<TopicPreview | null> {
    if (!await this.readScope(epoch) || epoch !== this.epoch) return null;
    const before = await this.topicSource(Number(data['job_id']), epoch); if (!before || epoch !== this.epoch) return null;
    if (!same(before.job, original)) throw new Error();
    const choices = await this.catalog(epoch); if (!choices || epoch !== this.epoch) return null;
    const model = choices.models.find(row => row.id === data['model_id']), account = choices.accounts.find(row => row.id === data['account_id']);
    if (!model || !account || model.provider_id !== account.provider_id || !model.price_known || model.access_tier === 'unknown'
      || data['allow_free'] !== (model.access_tier === 'free') || model.access_tier === 'free' && !model.privacy_policy_url
      || model.max_output_tokens !== null && Number(data['max_output_tokens']) > model.max_output_tokens) throw new Error();
    const result = await this.synthesisRequest(data, undefined, undefined, true); if (epoch !== this.epoch) return null;
    const row = this.scope(result);
    if (!exact(row, ['organization_id', 'project_id', 'selection', 'selection_digest', 'estimate_units']) || row['estimate_units'] !== 1 || !digest(row['selection_digest'])) throw new Error();
    const selection = structuredClone(row['selection']); this.validateSynthesisSelection(selection, data); const c = selection.configuration;
    const sourceDigest = await selectionDigest({ method_version: this.synthesisSourceMethod, organization_id: this.organizationId,
      project_id: this.projectId, source_current: true, ai_processing_permission: true, observation: before.observation, interpretation: TOPIC_SOURCE_MEANING });
    if (c['actor_id'] !== this.current!.actor || c['provider_id'] !== model.provider_id || c['model_identifier'] !== model.identifier
      || c['model_access_tier'] !== model.access_tier || c['source_selection_digest'] !== sourceDigest
      || await selectionDigest(selection) !== row['selection_digest']) throw new Error();
    const after = await this.topicSource(original.id, epoch), latest = await this.catalog(epoch);
    if (!after || !latest || !await this.readScope(epoch) || epoch !== this.epoch) return null;
    if (!same(before, after) || !same(model, latest.models.find(row => row.id === model.id)) || !same(account, latest.accounts.find(row => row.id === account.id))) throw new Error();
    return { selection, selection_digest: String(row['selection_digest']), source: before };
  }
  private async previewTopics(event?: Event) {
    event?.preventDefault(); if (this.busy() || this.pending() || !this.ready() || !this.synthesisLoaded()) return;
    const original = this.jobs().find(row => row.id === this.topicJobId()); if (!original || original.status !== 'succeeded' || original.cancel_requested) return;
    const data = { job_id: original.id, ai_processing_permission: this.aiPermission(), model_id: this.modelId(), account_id: this.accountId(),
      max_output_tokens: Number(this.outputTokens()), max_cost_usd: this.maxCost(), allow_free: this.allowFree() };
    this.clear(); this.topicJobId.set(original.id); const epoch = this.epoch; this.busy.set(true);
    try { const info = await this.readTopicPreview(this.synthesisInput(data), original, epoch); if (info && epoch === this.epoch) this.topicSelection.set(info); }
    catch { if (epoch === this.epoch) { this.topicSelection.set(null); this.error.set('Original citable heading sample, separate AI permission or exact model budget unavailable. No AI command sent.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private async sendTopics(command: Pending) {
    this.clear(); const epoch = this.epoch; this.busy.set(true); let sent = false, acknowledged = false;
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const data = command.jobId ? null : this.synthesisInput(Object.fromEntries(TOPIC_INPUT_FIELDS.map(key => [key, command.data[key]])));
      if (data) {
        const info = await this.readTopicPreview(data, command.topic!, epoch); if (epoch !== this.epoch) return;
        if (!info || !same(info, command.preview)) throw new Error();
      }
      this.pending.set(structuredClone(command)); sent = true;
      const result = await this.synthesisRequest(command.data, command.jobId); if (epoch !== this.epoch) return;
      const row = this.scope(result, 202); if (!exact(row, ['organization_id', 'project_id', 'job'])) throw new Error();
      const job = this.job(row['job'], true); if (command.jobId && job.id !== command.jobId) throw new Error(); acknowledged = true;
      if (data) {
        const info = await this.readTopicPreview(data, command.topic!, epoch); if (epoch !== this.epoch) return;
        if (!info || !same(info, command.preview)) this.lost();
      }
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      this.pending.set(null); this.synthesisSelected.set(job); this.message.set('Exact topic command acknowledged. Inspect its original private result separately.');
    } catch {
      if (epoch === this.epoch) {
        if (acknowledged) { this.reset(); this.error.set('Original source/model authority lost after acknowledgment. Private facts and uncertainty cleared; a stored job may exist. No replay.'); return; }
        if (sent) { try { if (!await this.readScope(epoch) || epoch !== this.epoch) return; } catch { return; } }
        this.error.set(sent ? 'Topic outcome uncertain. Look up the frozen own-key GET only; no replay.' : 'Original source or model changed. No AI command sent; preview again.');
      }
    } finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateTopicEvidence(row: Row, preview: TopicPreview) {
    const evidence = row['evidence'], selection = row['selection'] as TopicPreview['selection'], input = selection.input, c = selection.configuration;
    if (!exact(evidence, ['job_id', 'synthesis', 'source_current']) || evidence['job_id'] !== (row['job'] as Row)['id'] || evidence['source_current'] !== true) throw new Error();
    const s = evidence['synthesis'];
    if (!exact(s, ['method_version', 'organization_id', 'project_id', 'source_selection_digest', 'model_id', 'account_id', 'generated_at', 'observation', 'topics', 'state', 'interpretation'])
      || s['method_version'] !== this.synthesisMethod || s['organization_id'] !== this.organizationId || s['project_id'] !== this.projectId
      || s['model_id'] !== input['model_id'] || s['account_id'] !== input['account_id'] || s['source_selection_digest'] !== c['source_selection_digest']
      || s['state'] !== TOPIC_STATE || s['interpretation'] !== TOPIC_MEANING || !originalDate(s['generated_at'])
      || !ordered((row['usage'] as Row)['attempted_at'], s['generated_at']) || !ordered(s['generated_at'], (row['job'] as Row)['updated_at'])
      || !ordered(s['generated_at'], (row['usage'] as Row)['finished_at'])
      || new TextEncoder().encode(JSON.stringify(s)).length > 49152 || !same(s['observation'], preview.source.observation)) throw new Error();
    // The original job actor and independent reader may differ; their source/caller hashes are separate.
    if (!same(input, preview.selection.input) || CONFIG_FIELDS.filter(key => !['actor_id', 'caller_source_sha256'].includes(key))
      .some(key => !same(c[key], preview.selection.configuration[key]))) throw new Error();
    const collection = preview.source.observation['collection'] as Row;
    if (preview.source.job.id !== input['job_id'] || !ordered(collection['observed_at'], s['generated_at'])
      || !Array.isArray(s['topics']) || s['topics'].length < 1 || s['topics'].length > 10 || new TextEncoder().encode(JSON.stringify({ topics: s['topics'] })).length > 8192) throw new Error();
    const headings = (collection['evidence'] as Row)['headings'] as Row[];
    for (const note of s['topics']) {
      if (!exact(note, ['label', 'reference', 'quote']) || typeof note['reference'] !== 'string' || !/^heading_[0-9]$/.test(note['reference'])
        || ['label', 'quote'].some(key => typeof note[key] !== 'string' || !note[key] || [...String(note[key])].length > 80
          || note[key] !== String(note[key]).trim() || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(String(note[key])))) throw new Error();
      const original = headings[Number(note['reference'].slice(8))];
      if (!original || original['truncated'] || typeof original['text'] !== 'string' || !original['text'] || !original['text'].includes(String(note['quote']))) throw new Error();
    }
  }
  private async inspectTopics(id: number) {
    if (this.busy() || this.pending() || !this.ready() || !this.synthesisJobs().some(row => row.id === id)) return;
    this.clear(); const epoch = this.epoch; this.busy.set(true);
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const first = await this.synthesisRequest(undefined, id); if (epoch !== this.epoch) return;
      const row = await this.synthesisDetailRow(first, id); if (epoch !== this.epoch) return;
      if ((row['job'] as Job).status === 'succeeded') {
        const data = (row['selection'] as TopicPreview['selection']).input;
        const source = await this.topicSource(Number(data['job_id']), epoch); if (!source || epoch !== this.epoch) return;
        const preview = await this.readTopicPreview(data, source.job, epoch); if (!preview || epoch !== this.epoch) return;
        this.validateTopicEvidence(row, preview);
        const finalPreview = await this.readTopicPreview(data, source.job, epoch); if (!finalPreview || epoch !== this.epoch) return;
        if (!same(preview, finalPreview)) throw new Error();
      }
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      // Current source/model authority is confirmed by the same exact private GET after the separate client scope read.
      const final = await this.synthesisRequest(undefined, id); if (epoch !== this.epoch) return;
      const confirmed = await this.synthesisDetailRow(final, id); if (epoch !== this.epoch) return;
      if (!same(row, confirmed)) throw new Error();
      this.synthesisDetail.set(row); this.synthesisEvidence.set(row['evidence'] === null ? null : (row['evidence'] as Row)['synthesis'] as Row);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Current original topic hypotheses, source or model unavailable. Private state cleared; missing is not zero.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async previewSynthesis(event?: Event) {
    if (this.topics) { await this.previewTopics(event); return; }
    if (!this.supportsSynthesis) { event?.preventDefault(); return; }
    event?.preventDefault(); if (this.busy() || this.pending() || !this.ready() || !this.synthesisLoaded()) return;
    const previous = this.jobs().find(row => row.id === this.previousJobId()), current = this.jobs().find(row => row.id === this.currentJobId());
    if (!previous || !current || previous.id === current.id || [previous, current].some(row => row.status !== 'succeeded' || row.cancel_requested)) return;
    const pair = structuredClone({ previous, current }); this.clear(); this.previousJobId.set(previous.id); this.currentJobId.set(current.id);
    const epoch = this.epoch; this.busy.set(true);
    try {
      const data = this.synthesisInput({ previous_job_id: previous.id, current_job_id: current.id, ai_processing_permission: this.aiPermission(),
        model_id: this.modelId(), account_id: this.accountId(), max_output_tokens: Number(this.outputTokens()), max_cost_usd: this.maxCost(), allow_free: this.allowFree() });
      const info = await this.readSynthesisPreview(data, pair, epoch); if (info && epoch === this.epoch) { this.frozenPair.set(pair); this.synthesisSelection.set(info); }
    } catch { if (epoch === this.epoch) { this.synthesisSelection.set(null); this.frozenPair.set(null); this.error.set('Exact pair, separate AI permission or model budget unavailable. No AI command sent.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async launchSynthesis() {
    if (this.topics) {
      if (this.busy() || this.pending() || !this.topicSelection()) return;
      const preview = structuredClone(this.topicSelection()!), key = crypto.randomUUID();
      await this.sendTopics({ synthesis: true, preview, topic: preview.source.job, key,
        data: { ...preview.selection.input, selection_digest: preview.selection_digest, idempotency_key: key } }); return;
    }
    if (!this.supportsSynthesis) return;
    if (this.busy() || this.pending() || !this.synthesisSelection() || !this.frozenPair()) return;
    const preview = structuredClone(this.synthesisSelection()!), pair = structuredClone(this.frozenPair()!), key = crypto.randomUUID();
    await this.sendSynthesis({ synthesis: true, preview, pair, key, data: { ...preview.selection.input, selection_digest: preview.selection_digest, idempotency_key: key } });
  }
  private async sendSynthesis(command: Pending) {
    if (this.topics) { await this.sendTopics(command); return; }
    this.clear(); const epoch = this.epoch; this.busy.set(true); let sent = false; let acknowledged = false;
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const data = command.jobId ? null : this.synthesisInput(Object.fromEntries(INPUT_FIELDS.map(key => [key, command.data[key]])));
      if (data) {
        const fresh = await this.readSynthesisPreview(data, command.pair!, epoch); if (epoch !== this.epoch) return;
        if (!fresh || !same(fresh, command.preview)) throw new Error();
      }
      this.pending.set(structuredClone(command)); sent = true;
      const result = await this.synthesisRequest(command.data, command.jobId); if (epoch !== this.epoch) return; const row = this.scope(result, 202);
      if (!exact(row, ['organization_id', 'project_id', 'job'])) throw new Error(); const job = this.job(row['job'], true);
      if (command.jobId && job.id !== command.jobId) throw new Error();
      acknowledged = true;
      if (data) {
        const fresh = await this.readSynthesisPreview(data, command.pair!, epoch); if (epoch !== this.epoch) return;
        if (!fresh || !same(fresh, command.preview)) { this.reset(); this.error.set('Original source or model changed after the command. Private facts and uncertainty cleared; a stored job may exist. No replay.'); return; }
      }
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      this.pending.set(null); this.synthesisSelected.set(job); this.message.set('Exact synthesis command acknowledged. Deliberately refresh history or inspect its original private result.');
    } catch {
      if (epoch === this.epoch) {
        if (acknowledged) { this.reset(); this.error.set('Current original source or model unavailable after acknowledgment. Private state and uncertainty cleared; a stored job may exist. No replay.'); return; }
        if (sent) { try { if (!await this.readScope(epoch) || epoch !== this.epoch) return; } catch { return; } }
        this.error.set(sent ? 'Synthesis outcome uncertain. Look up the frozen own-key GET only; no replay.' : 'Current original pair or model changed. No AI command sent; preview again.');
      }
    } finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async cancelSynthesis(id: number) {
    if (!this.supportsSynthesis) return;
    if (this.busy() || this.pending() || !this.ready() || !this.synthesisJobs().some(row => row.id === id && ['queued', 'running'].includes(row.status) && !row.cancel_requested)) return;
    await this.sendSynthesis({ synthesis: true, data: {}, key: '', preview: null, jobId: id });
  }
  private async synthesisDetailRow(result: ApiResult, id: number) {
    const row = this.scope(result);
    if (!exact(row, ['organization_id', 'project_id', 'job', 'selection', 'selection_digest', 'usage', 'evidence']) || !digest(row['selection_digest'])) throw new Error();
    const job = this.job(row['job'], true); if (job.id !== id) throw new Error();
    this.validateSynthesisSelection(row['selection']); if (await selectionDigest(row['selection']) !== row['selection_digest']) throw new Error();
    const usage = row['usage'];
    if (usage !== null) {
      if (!exact(usage, ['status', 'input_tokens', 'output_tokens', 'duration_ms', 'estimated_cost_usd', 'reported_cost_usd', 'attempted_at', 'finished_at'])
        || typeof usage['status'] !== 'string' || !['attempted', 'completed', 'failed', 'unknown'].includes(usage['status']) || !ordered(job.created_at, usage['attempted_at'])
        || (usage['status'] === 'attempted') !== (usage['finished_at'] === null)
        || usage['finished_at'] !== null && !ordered(usage['attempted_at'], usage['finished_at'])
        || ['input_tokens', 'output_tokens', 'duration_ms'].some(key => usage[key] !== null && (!Number.isSafeInteger(usage[key]) || Number(usage[key]) < 0 || Number(usage[key]) > (key === 'duration_ms' ? 120000 : 100000000)))
        || ['estimated_cost_usd', 'reported_cost_usd'].some(key => usage[key] !== null && (typeof usage[key] !== 'string' || !/^[0-9]{1,6}\.[0-9]{6}$/.test(String(usage[key]))))) throw new Error();
    }
    if (job.status === 'succeeded' ? row['evidence'] === null || job.cancel_requested || usage === null || usage['status'] !== 'completed' : row['evidence'] !== null) throw new Error();
    return structuredClone(row);
  }
  private validateSynthesisEvidence(row: Row, pair: Pair, preview: SynthesisPreview) {
    const evidence = row['evidence'], selection = row['selection'] as SynthesisPreview['selection'], input = selection.input, c = selection.configuration;
    if (!exact(evidence, ['job_id', 'synthesis', 'source_current']) || evidence['job_id'] !== (row['job'] as Row)['id'] || evidence['source_current'] !== true) throw new Error();
    const s = evidence['synthesis'];
    if (!exact(s, ['method_version', 'organization_id', 'project_id', 'source_selection_digest', 'model_id', 'account_id', 'generated_at', 'comparison', 'interpretations', 'state', 'interpretation'])
      || s['method_version'] !== this.synthesisMethod || s['organization_id'] !== this.organizationId || s['project_id'] !== this.projectId
      || s['model_id'] !== input['model_id'] || s['account_id'] !== input['account_id'] || s['source_selection_digest'] !== c['source_selection_digest']
      || s['state'] !== SYNTHESIS_STATE || s['interpretation'] !== this.synthesisMeaning || !originalDate(s['generated_at'])
      || !ordered((row['usage'] as Row)['attempted_at'], s['generated_at']) || !ordered(s['generated_at'], (row['job'] as Row)['updated_at'])
      || !ordered(s['generated_at'], (row['usage'] as Row)['finished_at'])
      || new TextEncoder().encode(JSON.stringify(s)).length > 49152 || !same(s['comparison'], preview.comparison)) throw new Error();
    this.validateComparison(s['comparison'], pair); const comparison = s['comparison'] as Row;
    if (!ordered(((comparison['current'] as Row)['evidence'] as Row)['observed_at'], (row['usage'] as Row)['attempted_at'])) throw new Error();
    // Independent readers regenerate their own actor/caller pins; never replace the saved original actor provenance.
    const original = Object.fromEntries(Object.entries(c).filter(([key]) => !['actor_id', 'caller_source_sha256'].includes(key)));
    const current = Object.fromEntries(Object.entries(preview.selection.configuration).filter(([key]) => !['actor_id', 'caller_source_sha256'].includes(key)));
    if (!same(selection.input, preview.selection.input) || !same(original, current)) throw new Error();
    const refs: Record<string, { value: string; substring: boolean }> = {
      comparison_state: { value: String(comparison['state']), substring: false }, body_changed: { value: JSON.stringify(comparison['body_changed']), substring: false },
    };
    if (comparison['comparable']) for (const key of [this.headings ? 'headings_changed' : 'metadata_changed', 'count_deltas']) refs[key] = { value: JSON.stringify(canonical(comparison[key])), substring: false };
    for (const key of ['previous', 'current']) {
      const m = (comparison[key] as Row)['evidence'] as Row;
      if (m['state'] !== 'observed') continue;
      if (this.headings) {
        for (const [index, heading] of (m['headings'] as Row[]).entries()) {
          if (heading['text'] && !heading['truncated']) refs[key + '_heading_' + index] = { value: String(heading['text']), substring: true };
        }
      } else for (const field of ['title', 'description']) {
        const meta = m['metadata'] as Row; if (meta[field] && !meta[field + '_truncated']) refs[key + '_' + field] = { value: String(meta[field]), substring: true };
      }
    }
    const notes = s['interpretations'];
    if (!Array.isArray(notes) || notes.length < 1 || notes.length > 10 || new TextEncoder().encode(JSON.stringify({ interpretations: notes })).length > 8192) throw new Error();
    for (const note of notes) {
      if (!exact(note, ['text', 'reference', 'quote']) || typeof note['reference'] !== 'string' || !Object.hasOwn(refs, note['reference'])
        || ['text', 'quote'].some(key => typeof note[key] !== 'string' || [...String(note[key])].length < 1 || [...String(note[key])].length > (key === 'text' ? 500 : 300)
          || note[key] !== String(note[key]).trim() || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(String(note[key])))) throw new Error();
      const ref = refs[note['reference']]; if (ref.substring ? !ref.value.includes(String(note['quote'])) : ref.value !== note['quote']) throw new Error();
    }
  }
  async inspectSynthesis(id: number) {
    if (this.topics) { await this.inspectTopics(id); return; }
    if (!this.supportsSynthesis) return;
    if (this.busy() || this.pending() || !this.ready() || !this.synthesisJobs().some(row => row.id === id)) return;
    this.clear(); const epoch = this.epoch; this.busy.set(true);
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const result = await this.synthesisRequest(undefined, id); if (epoch !== this.epoch) return;
      const row = await this.synthesisDetailRow(result, id); if (epoch !== this.epoch) return;
      if ((row['job'] as Job).status === 'succeeded') {
        const data = (row['selection'] as SynthesisPreview['selection']).input; const pair = await this.synthesisPair(data, epoch); if (!pair || epoch !== this.epoch) return;
        const preview = await this.readSynthesisPreview(data, pair, epoch); if (!preview || epoch !== this.epoch) return;
        this.validateSynthesisEvidence(row, pair, preview);
        const finalPreview = await this.readSynthesisPreview(data, pair, epoch); if (!finalPreview || epoch !== this.epoch) return;
        const finalResult = await this.synthesisRequest(undefined, id); if (epoch !== this.epoch) return;
        const finalRow = await this.synthesisDetailRow(finalResult, id); if (epoch !== this.epoch) return;
        if (!same(row, finalRow) || !same(preview, finalPreview)) throw new Error();
      }
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      this.synthesisDetail.set(row); this.synthesisEvidence.set(row['evidence'] === null ? null : (row['evidence'] as Row)['synthesis'] as Row);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Current original synthesis, source or model unavailable. Private result and uncertainty cleared; missing is not zero.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private async reconcileSynthesis() {
    const command = structuredClone(this.pending()!); const epoch = ++this.epoch; this.busy.set(true); this.error.set(''); this.message.set('');
    this.synthesisSelected.set(null); this.synthesisDetail.set(null); this.synthesisEvidence.set(null);
    try {
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      const result = await this.synthesisRequest(undefined, command.jobId, command.jobId ? undefined : command.key); if (epoch !== this.epoch) return;
      let job: Job | undefined;
      if (command.jobId) {
        const row = await this.synthesisDetailRow(result, command.jobId); if (epoch !== this.epoch) return;
        job = row['job'] as Job; if (!job.cancel_requested && !['cancelled', 'succeeded', 'failed'].includes(job.status)) throw new Error();
      } else job = this.list(result, command.key, true).jobs[0];
      if (!await this.readScope(epoch) || epoch !== this.epoch) return;
      if (!job) { this.message.set('No saved own-actor synthesis at this lookup. Outcome remains uncertain; no replay.'); return; }
      this.pending.set(null); this.synthesisSelected.set(job); this.message.set('Exact original synthesis command reconciled. No POST replayed; inspect evidence separately.');
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Exact synthesis lookup/current actor unavailable. Local uncertainty cleared; a stored job may exist. No replay.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  async compare(event?: Event) {
    event?.preventDefault(); if (this.busy() || this.pending() || !this.ready()) return;
    const previous = this.jobs().find(job => job.id === this.previousJobId()); const current = this.jobs().find(job => job.id === this.currentJobId());
    if (!previous || !current || previous.id === current.id || [previous, current].some(job => job.status !== 'succeeded' || job.cancel_requested)) return;
    const structure = (this.destinations || this.formats || this.headings && !this.topics) && this.referenceStructureMode();
    const inventory = this.destinations && this.referenceInventoryMode();
    const dateCandidates = this.dates && this.dateCandidatePairMode();
    if (structure && inventory) return;
    const pair = structuredClone({ previous, current }); this.clear(); const epoch = this.epoch; this.busy.set(true);
    this.previousJobId.set(previous.id); this.currentJobId.set(current.id); this.frozenPair.set(pair);
    try {
      if (!await this.readPair(pair, epoch) || epoch !== this.epoch) return;
      const result = await (inventory ? this.api.competitorPageDestinationInventory(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : structure && this.headings ? this.api.competitorPageHeadingsStructure(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : structure && this.formats ? this.api.competitorPageFormatsStructure(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : structure ? this.api.competitorPageReferenceStructure(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.formats ? this.api.competitorPageFormatsComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.lighthouse ? this.api.competitorLighthouseComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : dateCandidates ? this.api.competitorPageDateCandidateComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.dates ? this.api.competitorPageDatesComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.destinations ? this.api.competitorPageDestinationsComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.headings ? this.api.competitorPageHeadingsComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.links ? this.api.competitorLinksRootComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.schema ? this.api.competitorSchemaRootComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.page ? this.api.competitorPageComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
        : this.api.competitorRootComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id));
      if (epoch !== this.epoch) return; const row = this.scope(result);
      const field = inventory ? 'inventory' : structure ? 'structure' : 'comparison';
      if (!exact(row, ['organization_id', 'project_id', field])) throw new Error();
      const original = structuredClone(row[field]);
      if (inventory) this.validateDestinationInventory(original, pair); else if (structure) this.validateReferenceStructure(original, pair); else this.validateComparison(original, pair);
      if (!await this.readPair(pair, epoch) || epoch !== this.epoch) return;
      if (dateCandidates || this.formats || this.lighthouse || structure || inventory) {
        const confirmed = await (dateCandidates ? this.api.competitorPageDateCandidateComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
          : inventory ? this.api.competitorPageDestinationInventory(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
          : structure && this.headings ? this.api.competitorPageHeadingsStructure(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
          : structure && this.formats ? this.api.competitorPageFormatsStructure(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
          : structure ? this.api.competitorPageReferenceStructure(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
          : this.formats ? this.api.competitorPageFormatsComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id)
          : this.api.competitorLighthouseComparison(this.organizationId, this.projectId, pair.previous.id, pair.current.id));
        if (epoch !== this.epoch) return; const latest = this.scope(confirmed);
        if (!exact(latest, ['organization_id', 'project_id', field]) || !same(latest[field], original)) this.lost();
        if (dateCandidates) this.validateDateCandidateComparison(latest[field], pair); else if (inventory) this.validateDestinationInventory(latest[field], pair); else if (structure) this.validateReferenceStructure(latest[field], pair); else if (this.formats) this.validateComparison(latest[field], pair); else this.validateLabComparison(latest[field], pair);
        if (!await this.readPair(pair, epoch) || epoch !== this.epoch) return;
      }
      this.comparison.set(original as Row);
    } catch { if (epoch === this.epoch) { this.reset(); this.error.set('Exact original pair/current private scope unavailable. Comparison cleared; missing is not zero. No collection or replay.'); } }
    finally { if (epoch === this.epoch) this.busy.set(false); }
  }
  private validateDestinationInventory(value: unknown, pair: Pair) {
    if (!exact(value, ['method_version', 'organization_id', 'project_id', 'source_current', 'pages', 'destinations', 'destination_reference_occurrences', 'all_rows_observed', 'interpretation'])
      || value['method_version'] !== 'competitor-two-sample-destination-inventory-v1' || value['organization_id'] !== this.organizationId || value['project_id'] !== this.projectId
      || value['source_current'] !== true || value['interpretation'] !== DESTINATION_INVENTORY_MEANING
      || new TextEncoder().encode(JSON.stringify(value)).length > 32768 || !Array.isArray(value['pages']) || value['pages'].length !== 2) throw new Error();
    const pages = value['pages']; this.validateEvidence(pages[0], pair.previous); this.validateEvidence(pages[1], pair.current);
    const urls = pages.map(page => page.collection.url as string);
    if (urls[0] === urls[1] || new URL(urls[0]).origin !== new URL(urls[1]).origin) throw new Error();
    const rows = pages.map(page => page.collection.evidence.destinations as string[] | null);
    const destinations = [...new Set(rows.flatMap(row => row ?? []))];
    const counts = rows.map(row => row === null ? null : destinations.map(url => row.filter(reference => reference === url).length));
    if (destinations.length > 20 || !same(value['destinations'], destinations) || !same(value['destination_reference_occurrences'], counts)
      || value['all_rows_observed'] !== rows.every(row => row !== null)) throw new Error();
  }
  private validateReferenceStructure(value: unknown, pair: Pair) {
    const field = this.headings ? 'selected_heading_occurrences' : this.formats ? 'selected_element_occurrences' : 'selected_uri_reference_occurrences';
    if (!exact(value, ['method_version', 'organization_id', 'project_id', 'source_current', 'pages', field, 'interpretation', ...(this.headings ? ['heading_levels', 'all_rows_observed'] : this.formats ? ['element_names', 'all_rows_observed'] : [])])
      || value['method_version'] !== (this.headings ? 'competitor-two-page-headings-v1' : this.formats ? 'competitor-two-page-elements-v1' : 'competitor-two-page-references-v1') || value['organization_id'] !== this.organizationId || value['project_id'] !== this.projectId
      || value['source_current'] !== true || value['interpretation'] !== (this.headings ? HEADINGS_STRUCTURE_MEANING : this.formats ? FORMATS_STRUCTURE_MEANING : 'two_selected_static_samples_exact_reference_occurrences_not_unique_pages_target_health_browser_visibility_indexing_inbound_links_whole_site_topology_topics_freshness_causality_or_crawl_authority')
      || new TextEncoder().encode(JSON.stringify(value)).length > 24576 || !Array.isArray(value['pages']) || value['pages'].length !== 2) throw new Error();
    const pages = value['pages']; this.validateEvidence(pages[0], pair.previous); this.validateEvidence(pages[1], pair.current);
    const urls = pages.map(page => page.collection.url as string);
    if (urls[0] === urls[1] || new URL(urls[0]).origin !== new URL(urls[1]).origin) throw new Error();
    const counts = pages.map(page => this.formats || this.headings ? (this.headings ? HEADING_COUNTS : FORMAT_COUNTS).map(name => page.collection.evidence.counts[name]) : page.collection.evidence.state === 'observed'
      ? urls.map(url => (page.collection.evidence.destinations as string[]).filter(reference => reference === url).length) : [null, null]);
    if (!same(value[field], counts) || (this.formats || this.headings) && (!same(value[this.headings ? 'heading_levels' : 'element_names'], this.headings ? HEADING_COUNTS : FORMAT_COUNTS)
      || value['all_rows_observed'] !== pages.every(page => page.collection.evidence.state === 'observed'))) throw new Error();
  }
  private validateLabComparison(value: unknown, pair: Pair) {
    if (!exact(value, ['method_version', 'organization_id', 'project_id', 'source_current', 'collection_method', 'parser_method', 'url', 'strategy', 'selection_sha256',
      'previous', 'current', 'state', 'reason', 'body_changed', 'score_deltas', 'audit_deltas', 'interpretation'])
      || value['method_version'] !== 'competitor-lighthouse-pair-v1' || value['organization_id'] !== this.organizationId || value['project_id'] !== this.projectId
      || value['source_current'] !== true || value['collection_method'] !== LAB_METHOD || value['parser_method'] !== 'competitor-pagespeed-lab-v1'
      || value['interpretation'] !== LAB_PAIR_MEANING || new TextEncoder().encode(JSON.stringify(value)).length > 32768) throw new Error();
    for (const key of ['previous', 'current'] as const) {
      const item = value[key];
      if (!exact(item, ['job_id', 'robots', 'request_started_at', 'evidence']) || item['job_id'] !== pair[key].id) throw new Error();
      this.validateEvidence({ job_id: item['job_id'], source_current: true, collection: { method_version: LAB_METHOD, state: 'collected',
        selection_sha256: value['selection_sha256'], url: value['url'], strategy: value['strategy'], robots: item['robots'], request_started_at: item['request_started_at'],
        evidence: item['evidence'], interpretation: LAB_COLLECTION_MEANING } }, pair[key]);
    }
    const previous = value['previous'] as Row, current = value['current'] as Row;
    const before = previous['evidence'] as Row, after = current['evidence'] as Row;
    if (microseconds(previous['request_started_at'])! >= microseconds(current['request_started_at'])!
      || microseconds(before['received_at'])! >= microseconds(after['received_at'])!) throw new Error();
    const first = before['lab'] as Row | null, second = after['lab'] as Row | null;
    const reason = before['state'] !== 'observed' || after['state'] !== 'observed' ? 'lab_unavailable'
      : first!['lighthouse_version'] === 'unknown' || first!['lighthouse_version'] !== second!['lighthouse_version'] ? 'lighthouse_version_unavailable_or_changed'
      : providerDate(before['provider_reported_at'])!.instant >= providerDate(after['provider_reported_at'])!.instant ? 'provider_report_time_not_increasing' : '';
    const scores = Object.fromEntries(LAB_SCORES.map(key => {
      const earlier = !reason ? (first!['scores'] as Row)[key] : null, later = !reason ? (second!['scores'] as Row)[key] : null;
      return [key, earlier !== null && later !== null ? Number(later) - Number(earlier) : null];
    }));
    const audits = Object.fromEntries(Object.entries(LAB_UNITS).map(([key, unit]) => {
      const earlier = !reason ? ((first!['audits'] as Row)[key] as Row)['value'] : null, later = !reason ? ((second!['audits'] as Row)[key] as Row)['value'] : null;
      return [key, { value: earlier !== null && later !== null ? Number(later) - Number(earlier) : null, unit }];
    }));
    if (value['reason'] !== reason || value['state'] !== (reason ? 'incomparable_lab_samples' : 'arithmetic_original_lab_samples')
      || value['body_changed'] !== (before['response_sha256'] !== after['response_sha256']) || !same(value['score_deltas'], scores) || !same(value['audit_deltas'], audits)) throw new Error();
  }
  dateIntervalRows(item: Row) { return item['declaration_pair_candidates'] as Row[]; }
  private validateDateCandidateComparison(value: unknown, pair: Pair) {
    if (!exact(value, ['method_version', 'organization_id', 'project_id', 'source_current', 'comparison', 'previous_candidates', 'current_candidates', 'declaration_pair_candidates', 'interpretation'])
      || value['method_version'] !== 'competitor-date-candidate-pair-v1' || value['organization_id'] !== this.organizationId || value['project_id'] !== this.projectId
      || value['source_current'] !== true || value['interpretation'] !== DATE_CANDIDATE_PAIR_MEANING || new TextEncoder().encode(JSON.stringify(value)).length > 49152) throw new Error();
    this.validateComparison(value['comparison'], pair, false);
    const original = value['comparison'] as Row;
    for (const key of ['previous', 'current']) this.validateDateCandidateList((original[key] as Row)['evidence'] as Row, value[key + '_candidates']);
    const previous = value['previous_candidates'] as Row[] | null, current = value['current_candidates'] as Row[] | null;
    if (previous === null || current === null) { if (value['declaration_pair_candidates'] !== null) throw new Error(); return; }
    const rows: Row[] = [];
    const before = ((original['previous'] as Row)['evidence'] as Row)['declarations'] as Row[], after = ((original['current'] as Row)['evidence'] as Row)['declarations'] as Row[];
    for (const [first, candidate] of previous.entries()) for (const [second, other] of current.entries()) {
      if (before[first]['property'] !== after[second]['property']) continue;
      const row: Row = { previous_declaration_index: first, current_declaration_index: second, state: 'incomparable_literal_candidates', calendar_day_delta: null, utc_microsecond_delta: null };
      if (candidate['state'] === 'calendar_literal' && other['state'] === 'calendar_literal') {
        row['state'] = 'calendar_candidates'; row['calendar_day_delta'] = (calendar(other['calendar_date'])! - calendar(candidate['calendar_date'])!) / 86400000;
      } else if (candidate['state'] === 'offset_literal' && other['state'] === 'offset_literal') {
        row['state'] = 'offset_candidates'; row['utc_microsecond_delta'] = String(microseconds(other['utc_instant'])! - microseconds(candidate['utc_instant'])!);
      }
      rows.push(row);
    }
    if (!same(rows, value['declaration_pair_candidates'])) throw new Error();
  }
  private validateComparison(value: unknown, pair: Pair, dateCandidates = this.dates && this.dateCandidatePairMode()) {
    if (dateCandidates) { this.validateDateCandidateComparison(value, pair); return; }
    if (this.lighthouse) { this.validateLabComparison(value, pair); return; }
    if (!exact(value, ['method_version', 'organization_id', 'project_id', 'source_current', 'collection_method', 'parser_method', 'url', 'source_sha256',
      'previous', 'current', 'comparable', 'state', 'body_changed', ...(this.formats || this.links ? [] : [this.dates ? 'declarations_changed' : this.destinations ? 'destinations_changed' : this.headings ? 'headings_changed' : this.schema ? 'type_changes' : 'metadata_changed']), ...(this.dates ? [] : ['count_deltas']), 'interpretation'])
      || value['method_version'] !== (this.formats ? 'competitor-page-elements-pair-v1' : this.dates ? 'competitor-page-dates-pair-v1' : this.destinations ? 'competitor-page-references-pair-v1' : this.headings ? 'competitor-page-headings-comparison-v1' : this.links ? 'competitor-static-link-categories-comparison-v1' : this.schema ? 'competitor-static-schema-comparison-v1' : this.page ? 'competitor-static-page-comparison-v1' : 'competitor-static-comparison-v1') || value['organization_id'] !== this.organizationId || value['project_id'] !== this.projectId
      || value['source_current'] !== true || value['collection_method'] !== this.method || value['parser_method'] !== (this.formats ? 'competitor-static-content-elements-v1' : this.dates ? 'competitor-static-dates-v1' : this.destinations ? 'competitor-static-destinations-v1' : this.headings ? 'competitor-static-headings-v1' : this.links ? 'competitor-static-link-categories-v1' : this.schema ? 'competitor-static-schema-types-v1' : 'competitor-static-metadata-v1')
      || this.formats && new TextEncoder().encode(JSON.stringify(value)).length > 24576
      || value['interpretation'] !== (this.formats ? FORMATS_COMPARISON_MEANING : this.dates ? DATES_COMPARISON_MEANING : this.destinations ? DESTINATIONS_COMPARISON_MEANING : this.headings ? HEADINGS_COMPARISON_MEANING : this.links ? 'dated_selected_root_literal_reference_category_changes_not_destinations_unique_pages_browser_visibility_link_health_inbound_links_whole_site_structure_freshness_or_causality' : this.schema ? 'dated_selected_root_lexical_label_changes_not_resolved_schema_validity_actual_page_type_rich_results_topics_freshness_whole_site_or_causality' : this.page ? PAGE_COMPARISON_MEANING : COMPARISON_MEANING)) throw new Error();
    for (const key of ['previous', 'current'] as const) {
      const item = value[key]; const job = pair[key];
      if (!exact(item, ['job_id', 'robots', 'evidence']) || !object(item['evidence']) || item['job_id'] !== job.id) throw new Error();
      this.validateEvidence({ job_id: job.id, source_current: true, collection: { method_version: value['collection_method'], state: 'collected',
        requested_url: value['url'], url: value['url'], observed_at: item['evidence']['observed_at'], robots: item['robots'], source_sha256: value['source_sha256'],
        evidence: item['evidence'], interpretation: this.page ? PAGE_COLLECTION_MEANING : COLLECTION_MEANING } }, job);
    }
    const before = (value['previous'] as Row)['evidence'] as Row; const after = (value['current'] as Row)['evidence'] as Row;
    if (microseconds(before['observed_at'])! >= microseconds(after['observed_at'])!) throw new Error();
    if (this.dates) {
      const comparable = [before, after].every(item => item['state'] === 'observed'
        && !(item['declarations'] as Row[]).some(declaration => declaration['truncated']));
      const changed = comparable ? !same(before['declarations'], after['declarations']) : null;
      if (value['comparable'] !== comparable || value['state'] !== (comparable ? 'comparable_original_static_article_date_declarations' : 'incomparable_unavailable_or_truncated_article_date_declarations')
        || value['body_changed'] !== (before['body_sha256'] !== after['body_sha256']) || value['declarations_changed'] !== changed) throw new Error();
      return;
    }
    const comparable = [before, after].every(item => item['state'] === 'observed'
      && (this.headings ? !(item['headings'] as Row[]).some(heading => heading['truncated'])
        : this.formats || this.destinations || this.links || this.schema || !(item['metadata'] as Row)['title_truncated'] && !(item['metadata'] as Row)['description_truncated']));
    let changes: Row | boolean | null = null;
    if (comparable && !this.formats && !this.links) {
      if (this.destinations) changes = !same(before['destinations'], after['destinations']);
      else if (this.headings) changes = !same(before['headings'], after['headings']);
      else if (this.schema) {
        const previous = (before['summary'] as Row)['types'] as string[]; const current = (after['summary'] as Row)['types'] as string[];
        changes = { added: current.filter(label => !previous.includes(label)), removed: previous.filter(label => !current.includes(label)) };
      } else changes = Object.fromEntries(['title', 'description'].map(key => [key, (before['metadata'] as Row)[key] !== (after['metadata'] as Row)[key]]));
    }
    const keys = this.formats ? FORMAT_COUNTS : this.headings ? HEADING_COUNTS : this.destinations || this.links ? LINK_COUNTS : this.schema ? ['json_ld_blocks', 'typed_nodes', 'unrecognized_type_count'] : COUNTS;
    const field = this.schema ? 'summary' : 'counts';
    const counts = comparable ? Object.fromEntries(keys.map(key => [key, Number((after[field] as Row)[key]) - Number((before[field] as Row)[key])])) : null;
    const state = this.formats ? (comparable ? 'comparable_original_static_content_element_counts' : 'incomparable_unavailable_content_element_counts')
      : this.destinations ? (comparable ? 'comparable_original_static_supported_same_origin_references' : 'incomparable_unavailable_supported_same_origin_references')
      : this.headings ? (comparable ? 'comparable_original_static_heading_text_and_order' : 'incomparable_unavailable_or_truncated_heading_text')
      : this.links ? (comparable ? 'comparable_original_static_link_categories' : 'incomparable_unavailable_link_categories')
      : this.schema ? (comparable ? 'comparable_original_static_schema_labels' : 'incomparable_unavailable_schema_labels')
      : (comparable ? 'comparable_original_static_metadata' : 'incomparable_unavailable_or_truncated_metadata');
    if (value['comparable'] !== comparable || value['state'] !== state
      || value['body_changed'] !== (before['body_sha256'] !== after['body_sha256']) || !this.formats && !this.links && !same(value[this.destinations ? 'destinations_changed' : this.headings ? 'headings_changed' : this.schema ? 'type_changes' : 'metadata_changed'], changes) || !same(value['count_deltas'], counts)) throw new Error();
  }
  private validateEvidence(value: unknown, job: Job) {
    if (!exact(value, ['job_id', 'collection', 'source_current']) || value['job_id'] !== job.id || value['source_current'] !== true
      || job.status !== 'succeeded' || job.cancel_requested) throw new Error();
    const c = value['collection'];
    if (this.lighthouse) { this.validateLab(c, job); return; }
    if (!exact(c, ['method_version', 'state', 'requested_url', 'url', 'observed_at', 'robots', 'source_sha256', 'evidence', 'interpretation'])
      || c['method_version'] !== this.method || c['state'] !== 'collected' || typeof c['url'] !== 'string'
      || !this.origins().some(origin => this.page ? canonicalPageUrl(c['url'], origin) : c['url'] === origin + '/') || c['requested_url'] !== c['url']
      || !originalDate(c['observed_at']) || !ordered(job.created_at, c['observed_at']) || !ordered(c['observed_at'], job.updated_at)
      || !ordered(this.current!.configuration['updated_at'], c['observed_at']) || !digest(c['source_sha256'])
      || typeof c['robots'] !== 'string' || !['available', 'missing_http_404_or_410'].includes(c['robots'])
      || c['interpretation'] !== (this.page ? PAGE_COLLECTION_MEANING : COLLECTION_MEANING)
      || new TextEncoder().encode(JSON.stringify(c)).length > 8192) throw new Error();
    // Original actor-derived SHA is opaque. Never compare it to a different reader's preview SHA.
    const m = c['evidence'];
    if (this.formats) { this.validateFormats(m, c); return; }
    if (this.dates) { this.validateDates(m, c); return; }
    if (this.destinations) { this.validateDestinations(m, c); return; }
    if (this.headings) { this.validateHeadings(m, c); return; }
    if (this.links) { this.validateLinks(m, c); return; }
    if (this.schema) { this.validateSchema(m, c); return; }
    if (!exact(m, ['method_version', 'url', 'observed_at', 'body_sha256', 'body_size_bytes', 'state', 'reason', 'metadata', 'counts', 'coverage', 'excluded_containers', 'interpretation'])
      || m['method_version'] !== 'competitor-static-metadata-v1' || m['url'] !== c['url'] || m['observed_at'] !== c['observed_at']
      || !digest(m['body_sha256']) || !positive(m['body_size_bytes']) || Number(m['body_size_bytes']) > 131072
      || m['coverage'] !== 'one_complete_returned_static_document_selected_lexical_metadata_only' || m['interpretation'] !== METADATA_MEANING
      || !same(m['excluded_containers'], EXCLUDED) || !exact(m['counts'], COUNTS)) throw new Error();
    const counts = Object.values(m['counts']); const metadata = m['metadata'];
    if (m['state'] === 'unavailable') {
      if (typeof m['reason'] !== 'string' || !['ambiguous_markup', 'element_limit'].includes(m['reason']) || metadata !== null || counts.some(value => value !== null)) throw new Error();
    } else if (m['state'] === 'observed') {
      if (m['reason'] !== '' || !exact(metadata, ['title', 'description', 'title_truncated', 'description_truncated'])
        || counts.some(value => !Number.isSafeInteger(value) || Number(value) < 0 || Number(value) > 1000)
        || counts.reduce<number>((total, value) => total + Number(value), 0) > 1000) throw new Error();
      for (const [key, limit] of [['title', 500], ['description', 1000]] as const) {
        const text = metadata[key]; const truncated = metadata[key + '_truncated'];
        if (!literalText(text, limit) || typeof truncated !== 'boolean' || truncated && !text) throw new Error();
      }
    } else throw new Error();
  }
  private validateFormats(value: unknown, c: Row) {
    if (!exact(value, ['method_version', 'url', 'observed_at', 'body_sha256', 'body_size_bytes', 'state', 'reason', 'counts', 'coverage', 'excluded_containers', 'interpretation'])
      || value['method_version'] !== 'competitor-static-content-elements-v1' || value['url'] !== c['url'] || value['observed_at'] !== c['observed_at']
      || !digest(value['body_sha256']) || !positive(value['body_size_bytes']) || Number(value['body_size_bytes']) > 131072
      || value['coverage'] !== 'one_complete_returned_static_document_non_inert_selected_start_tag_occurrences_only'
      || value['interpretation'] !== FORMATS_MEANING || !same(value['excluded_containers'], EXCLUDED) || !exact(value['counts'], FORMAT_COUNTS)) throw new Error();
    const counts = Object.values(value['counts']);
    if (value['state'] === 'unavailable') {
      if (typeof value['reason'] !== 'string' || !['ambiguous_markup', 'element_limit'].includes(value['reason']) || counts.some(count => count !== null)) throw new Error();
    } else if (value['state'] === 'observed') {
      if (value['reason'] !== '' || counts.some(count => !Number.isSafeInteger(count) || Number(count) < 0 || Number(count) > 1000)
        || counts.reduce<number>((sum, count) => sum + Number(count), 0) > 1000) throw new Error();
    } else throw new Error();
  }
  private validateLab(c: unknown, job: Job) {
    if (!exact(c, ['method_version', 'state', 'selection_sha256', 'url', 'strategy', 'robots', 'request_started_at', 'evidence', 'interpretation'])
      || c['method_version'] !== LAB_METHOD || c['state'] !== 'collected' || !digest(c['selection_sha256'])
      || !this.origins().some(origin => canonicalPageUrl(c['url'], origin)) || typeof c['strategy'] !== 'string' || !['mobile', 'desktop'].includes(c['strategy'])
      || typeof c['robots'] !== 'string' || !['available', 'missing_http_404_or_410'].includes(c['robots']) || !originalDate(c['request_started_at'])
      || !ordered(job.created_at, c['request_started_at']) || !ordered(this.current!.configuration['updated_at'], c['request_started_at'])
      || c['interpretation'] !== LAB_COLLECTION_MEANING || new TextEncoder().encode(JSON.stringify(c)).length > 8192) throw new Error();
    const e = c['evidence'];
    if (!exact(e, ['method_version', 'url', 'strategy', 'received_at', 'response_sha256', 'response_size_bytes', 'provider_reported_at', 'state', 'reason', 'lab', 'coverage', 'interpretation'])
      || e['method_version'] !== 'competitor-pagespeed-lab-v1' || e['url'] !== c['url'] || e['strategy'] !== c['strategy']
      || !originalDate(e['received_at']) || !ordered(c['request_started_at'], e['received_at']) || !ordered(e['received_at'], job.updated_at)
      || !digest(e['response_sha256']) || !positive(e['response_size_bytes']) || Number(e['response_size_bytes']) > 2097152
      || e['coverage'] !== 'one_complete_provider_json_selected_exact_nonroot_uri_lighthouse_lab_sample_only' || e['interpretation'] !== LAB_MEANING) throw new Error();
    const reported = providerDate(e['provider_reported_at']);
    if (!reported || reported.instant > microseconds(e['received_at'])!) throw new Error();
    if (e['state'] === 'unavailable') {
      if (e['reason'] !== 'runtime_failed' || e['lab'] !== null) throw new Error(); return;
    }
    const lab = e['lab'];
    if (e['state'] !== 'observed' || e['reason'] !== ''
      || !exact(lab, ['source', 'kind', 'status', 'requested_url', 'final_url', 'strategy', 'lighthouse_version', 'observed_at', 'scores', 'audits', 'score_method', 'field_data'])
      || lab['source'] !== 'pagespeed_insights' || lab['kind'] !== 'lighthouse_lab' || lab['status'] !== 'observed'
      || lab['requested_url'] !== c['url'] || lab['final_url'] !== c['url'] || lab['strategy'] !== c['strategy']
      || lab['observed_at'] !== reported.normalized || lab['field_data'] !== 'not_used' || lab['score_method'] !== 'lighthouse_lab_score_not_field_p75'
      || typeof lab['lighthouse_version'] !== 'string' || lab['lighthouse_version'].length > 32
      || lab['lighthouse_version'] !== 'unknown' && !/^[0-9]+(?:\.[0-9]+){1,3}$/.test(lab['lighthouse_version'])
      || !exact(lab['scores'], LAB_SCORES) || !exact(lab['audits'], Object.keys(LAB_UNITS))) throw new Error();
    for (const value of Object.values(lab['scores'])) {
      if (value !== null && (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1)) throw new Error();
    }
    for (const [key, unit] of Object.entries(LAB_UNITS)) {
      const item = lab['audits'][key];
      if (!exact(item, ['value', 'unit', 'state']) || item['unit'] !== unit
        || item['state'] !== (item['value'] === null ? 'unavailable' : 'observed')
        || item['value'] !== null && (typeof item['value'] !== 'number' || !Number.isFinite(item['value']) || item['value'] < 0 || item['value'] > 10000000)) throw new Error();
    }
    // The original actor-bound selection SHA remains opaque to an independent reader.
  }
  private validateDates(value: unknown, collection: Row) {
    if (!exact(value, ['method_version', 'url', 'observed_at', 'body_sha256', 'body_size_bytes', 'state', 'reason', 'declarations',
      'coverage', 'excluded_containers', 'interpretation']) || value['method_version'] !== 'competitor-static-dates-v1'
      || value['url'] !== collection['url'] || value['observed_at'] !== collection['observed_at'] || !digest(value['body_sha256'])
      || !positive(value['body_size_bytes']) || Number(value['body_size_bytes']) > 131072
      || value['coverage'] !== 'one_complete_returned_static_document_two_exact_article_meta_properties_only'
      || value['interpretation'] !== 'literal_meta_declarations_not_validated_dates_page_identity_publication_change_age_freshness_publishing_cadence_or_whole_site'
      || !same(value['excluded_containers'], EXCLUDED)) throw new Error();
    if (value['state'] === 'unavailable') {
      if (typeof value['reason'] !== 'string' || !['ambiguous_markup', 'element_limit', 'declaration_limit', 'result_limit'].includes(value['reason'])
        || value['declarations'] !== null) throw new Error();
    } else if (value['state'] === 'observed') {
      if (value['reason'] !== '' || !Array.isArray(value['declarations']) || value['declarations'].length > 10) throw new Error();
      for (const item of value['declarations']) {
        if (!exact(item, ['property', 'value', 'truncated']) || typeof item['property'] !== 'string' || !['article:published_time', 'article:modified_time'].includes(item['property'])
          || !literalText(item['value'], 80) || typeof item['truncated'] !== 'boolean' || item['truncated'] && !item['value']) throw new Error();
      }
    } else throw new Error();
  }
  private validateDestinations(value: unknown, collection: Row) {
    if (!exact(value, ['method_version', 'url', 'observed_at', 'body_sha256', 'body_size_bytes', 'state', 'reason', 'destinations', 'counts',
      'coverage', 'excluded_containers', 'interpretation']) || value['method_version'] !== 'competitor-static-destinations-v1'
      || value['url'] !== collection['url'] || value['observed_at'] !== collection['observed_at'] || !digest(value['body_sha256'])
      || !positive(value['body_size_bytes']) || Number(value['body_size_bytes']) > 131072
      || value['coverage'] !== 'one_complete_returned_static_document_non_inert_same_origin_href_occurrences_no_base_stdlib_join_in_original_order'
      || value['interpretation'] !== 'resolved_static_same_origin_references_not_unique_pages_fetched_destinations_link_health_crawl_authority_browser_visibility_topics_or_whole_site_structure'
      || !same(value['excluded_containers'], EXCLUDED) || !exact(value['counts'], LINK_COUNTS)) throw new Error();
    const counts = value['counts'];
    if (value['state'] === 'unavailable') {
      if (typeof value['reason'] !== 'string' || !['ambiguous_markup', 'element_limit', 'base_dependent_references', 'destination_limit', 'result_limit'].includes(value['reason'])
        || value['destinations'] !== null || Object.values(counts).some(count => count !== null)) throw new Error();
    } else if (value['state'] === 'observed') {
      const origin = new URL(String(collection['url'])).origin;
      if (value['reason'] !== '' || !Array.isArray(value['destinations']) || value['destinations'].length > 10
        || !value['destinations'].every(url => literalReferenceUrl(url, origin))
        || Object.values(counts).some(count => !Number.isSafeInteger(count) || Number(count) < 0 || Number(count) > 1000)
        || Number(counts['same_origin_http']) !== value['destinations'].length
        || Number(counts['href_anchors']) !== LINK_COUNTS.slice(1).reduce((total, key) => total + Number(counts[key]), 0)) throw new Error();
    } else throw new Error();
  }
  private validateHeadings(value: unknown, collection: Row) {
    if (!exact(value, ['method_version', 'url', 'observed_at', 'body_sha256', 'body_size_bytes', 'state', 'reason', 'headings', 'counts',
      'coverage', 'excluded_containers', 'interpretation']) || value['method_version'] !== 'competitor-static-headings-v1'
      || value['url'] !== collection['url'] || value['observed_at'] !== collection['observed_at'] || !digest(value['body_sha256'])
      || !positive(value['body_size_bytes']) || Number(value['body_size_bytes']) > 131072
      || value['coverage'] !== 'one_complete_returned_static_document_non_inert_heading_occurrences_in_original_order'
      || value['interpretation'] !== 'literal_text_levels_not_browser_visibility_semantic_outline_accessibility_topics_page_identity_publication_age_freshness_or_whole_site'
      || !same(value['excluded_containers'], EXCLUDED) || !exact(value['counts'], HEADING_COUNTS)) throw new Error();
    if (value['state'] === 'unavailable') {
      if (typeof value['reason'] !== 'string' || !['ambiguous_markup', 'element_limit', 'heading_limit', 'result_limit'].includes(value['reason'])
        || value['headings'] !== null || Object.values(value['counts']).some(count => count !== null)) throw new Error();
    } else if (value['state'] === 'observed') {
      if (value['reason'] !== '' || !Array.isArray(value['headings']) || value['headings'].length > 10) throw new Error();
      const counts: Row = Object.fromEntries(HEADING_COUNTS.map(key => [key, 0]));
      for (const item of value['headings']) {
        if (!exact(item, ['level', 'text', 'truncated']) || !Number.isSafeInteger(item['level']) || Number(item['level']) < 1 || Number(item['level']) > 6
          || !literalText(item['text'], 80) || typeof item['truncated'] !== 'boolean' || item['truncated'] && !item['text']) throw new Error();
        const key = 'h' + item['level']; counts[key] = Number(counts[key]) + 1;
      }
      if (Object.values(value['counts']).some(count => !Number.isSafeInteger(count)) || !same(value['counts'], counts)) throw new Error();
    } else throw new Error();
  }
  private validateLinks(value: unknown, collection: Row) {
    if (!exact(value, ['method_version', 'url', 'observed_at', 'body_sha256', 'body_size_bytes', 'state', 'reason', 'counts',
      'coverage', 'excluded_containers', 'interpretation']) || value['method_version'] !== 'competitor-static-link-categories-v1'
      || value['url'] !== collection['url'] || value['observed_at'] !== collection['observed_at'] || !digest(value['body_sha256'])
      || !positive(value['body_size_bytes']) || Number(value['body_size_bytes']) > 131072
      || value['coverage'] !== 'one_complete_returned_static_document_non_inert_html_decoded_href_occurrences_no_base_stdlib_uri_join_only'
      || value['interpretation'] !== 'static_reference_categories_not_unique_pages_browser_visibility_link_health_inbound_links_or_whole_site_structure'
      || !same(value['excluded_containers'], EXCLUDED) || !exact(value['counts'], LINK_COUNTS)) throw new Error();
    const counts = value['counts'];
    if (value['state'] === 'unavailable') {
      if (typeof value['reason'] !== 'string' || !['ambiguous_markup', 'element_limit', 'base_dependent_references'].includes(value['reason'])
        || Object.values(counts).some(value => value !== null)) throw new Error();
    } else if (value['state'] === 'observed') {
      if (value['reason'] !== '' || Object.values(counts).some(value => !Number.isSafeInteger(value) || Number(value) < 0 || Number(value) > 1000)
        || Number(counts['href_anchors']) !== LINK_COUNTS.slice(1).reduce((total, key) => total + Number(counts[key]), 0)) throw new Error();
    } else throw new Error();
  }
  private validateSchema(value: unknown, collection: Row) {
    if (!exact(value, ['method_version', 'url', 'observed_at', 'body_sha256', 'body_size_bytes', 'state', 'reason', 'summary',
      'coverage', 'excluded_containers', 'interpretation']) || value['method_version'] !== 'competitor-static-schema-types-v1'
      || value['url'] !== collection['url'] || value['observed_at'] !== collection['observed_at'] || !digest(value['body_sha256'])
      || !positive(value['body_size_bytes']) || Number(value['body_size_bytes']) > 131072
      || value['coverage'] !== 'one_complete_returned_static_document_non_inert_json_ld_fixed_type_labels_only'
      || value['interpretation'] !== 'lexical_declarations_not_resolved_schema_validity_actual_page_type_rich_results_visible_consistency_or_whole_site'
      || !same(value['excluded_containers'], EXCLUDED)) throw new Error();
    const summary = value['summary'];
    if (value['state'] === 'unavailable') {
      if (summary !== null || typeof value['reason'] !== 'string'
        || !['ambiguous_markup', 'element_limit', 'block_limit', 'size_limit', 'invalid_json', 'shape_limit', 'type_shape'].includes(value['reason'])) throw new Error();
    } else if (value['state'] === 'observed') {
      if (value['reason'] !== '' || !exact(summary, ['json_ld_blocks', 'typed_nodes', 'types', 'unrecognized_type_count'])
        || !Array.isArray(summary['types']) || summary['types'].length > SCHEMA_TYPES.length
        || summary['types'].some(label => typeof label !== 'string' || !SCHEMA_TYPES.includes(label))
        || new Set(summary['types']).size !== summary['types'].length || !same(summary['types'], [...summary['types']].sort())
        || ![['json_ld_blocks', 20], ['typed_nodes', 500], ['unrecognized_type_count', 10000]].every(([key, limit]) =>
          Number.isSafeInteger(summary[String(key)]) && Number(summary[String(key)]) >= 0 && Number(summary[String(key)]) <= Number(limit))
        || Number(summary['unrecognized_type_count']) + summary['types'].length > Number(summary['typed_nodes']) * 20
        || !summary['json_ld_blocks'] && summary['typed_nodes'] !== 0) throw new Error();
    } else throw new Error();
  }

}
