import { Title } from '@angular/platform-browser';
import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';
import { AccountApi, ApiResult } from '../account/account-api';
import { CompetitorRoots } from './competitor-roots';
import { workspaceRoutes } from './workspace.routes';
import { environment } from '../../environments/environment';

type Row = Record<string, any>;
const ORIGIN = 'https://competitor.example.invalid';
const OWN = 'https://own.example.invalid';
const DATE = '2026-01-01T00:00:00.000001+00:00';
const OBSERVED = '2026-01-01T00:00:00.000002+00:00';
const LATER = '2026-01-01T00:00:00.000003+00:00';
const AI_CREATED = '2026-01-01T00:00:00.000004+00:00';
const ATTEMPT = '2026-01-01T00:00:00.000005+00:00';
const GENERATED = '2026-01-01T00:00:00.000006+00:00';
const FINISHED = '2026-01-01T00:00:00.000007+00:00';
const synthesisJob = () => ({ ...job(), id: 61, created_at: AI_CREATED, updated_at: FINISHED });
const model = () => ({ id: 31, provider_id: 51, name: 'Configured reasoning candidate', identifier: 'fixture-model', max_output_tokens: 2048,
  access_tier: 'standard', price_known: true, privacy_policy_url: '' });
const account = () => ({ id: 41, provider_id: 51, label: 'Platform fixture', source: 'platform' });
const aiInput = () => ({ previous_job_id: 21, current_job_id: 22, ai_processing_permission: true, model_id: 31, account_id: 41,
  max_output_tokens: 512, max_cost_usd: '1.000001', allow_free: false });
async function aiSelection(data: Row, original = comparison(), actor = 1): Promise<Row> {
  const headings = original['parser_method'] === 'competitor-static-headings-v1';
  const sourceMethod = headings ? 'competitor-heading-ai-source-v1' : 'competitor-static-synthesis-source-v1';
  const source = { method_version: sourceMethod, organization_id: 7, project_id: 9, source_current: true,
    ai_processing_permission: true, comparison: original,
    interpretation: headings ? 'original_static_heading_pair_untrusted_ai_input_not_generated_analysis_observed_page_topics_content_gaps_provider_permission_or_whole_site_evidence' : 'original_static_pair_untrusted_ai_input_not_generated_analysis_provider_permission_or_whole_site_evidence' };
  return { input: structuredClone(data), configuration: { provider_id: 51, model_identifier: 'fixture-model', provider_kind: 'openai', provider_base_url: '',
    model_revision: DATE, model_access_tier: data['allow_free'] ? 'free' : 'standard', input_price_usd_per_million: '0.100000', output_price_usd_per_million: '0.100000',
    estimated_max_cost_usd: '0.003000', account_id: data['account_id'], credential_revision: DATE, routing_source: 'explicit', routing_policy_id: null,
    routing_policy_revision: null, fallback_index: 0, timeout_seconds: 30, method: headings ? 'competitor-heading-synthesis-v1' : 'competitor-static-synthesis-v1', organization_id: 7, project_id: 9, actor_id: actor,
    source_method: sourceMethod, source_selection_digest: await sha(source), source_metadata_sha256: 'a'.repeat(64),
    caller_source_sha256: String(actor).repeat(64), model_selection_sha256: 'b'.repeat(64), prompt_sha256: 'c'.repeat(64), output_schema_sha256: 'd'.repeat(64) } };
}
async function aiDetail(headings = false): Promise<Row> {
  const original = headings ? headingsComparison() : comparison();
  const selection = await aiSelection(aiInput(), original);
  return { organization_id: 7, project_id: 9, job: { ...synthesisJob(), status: 'succeeded' }, selection, selection_digest: await sha(selection),
    usage: { status: 'completed', input_tokens: null, output_tokens: null, duration_ms: null, estimated_cost_usd: null, reported_cost_usd: null,
      attempted_at: ATTEMPT, finished_at: FINISHED }, evidence: { job_id: 61, source_current: true, synthesis: {
      method_version: headings ? 'competitor-heading-synthesis-v1' : 'competitor-static-synthesis-v1', organization_id: 7, project_id: 9, source_selection_digest: selection['configuration'].source_selection_digest,
      model_id: 31, account_id: 41, generated_at: GENERATED, comparison: original, state: 'unverified_ai_interpretations_require_human_review',
      interpretation: headings ? 'original_static_heading_facts_separate_from_unverified_cited_ai_notes_not_page_topics_content_gaps_approval_freshness_whole_site_or_causal_evidence' : 'original_static_facts_separate_from_unverified_cited_ai_notes_not_approval_whole_site_or_causal_evidence',
      interpretations: [{ text: '<img src=x onerror=alert(1)> is unverified AI text.', reference: headings ? 'current_heading_0' : 'current_title', quote: 'Changed' },
        { text: 'Literal returned bytes differ; review meaning.', reference: 'body_changed', quote: 'true' }],
    } } };
}
const topicInput = () => ({ job_id: 21, ai_processing_permission: true, model_id: 31, account_id: 41,
  max_output_tokens: 512, max_cost_usd: '1.000001', allow_free: false });
async function topicSelection(data: Row, observation = headingsEvidence(), actor = 1): Promise<Row> {
  const selection = await aiSelection(data, undefined, actor);
  Object.assign(selection['configuration'], { method: 'competitor-heading-topics-v1', source_method: 'competitor-heading-topics-source-v1',
    source_selection_digest: await sha({ method_version: 'competitor-heading-topics-source-v1', organization_id: 7, project_id: 9,
      source_current: true, ai_processing_permission: true, observation,
      interpretation: 'original_single_heading_sample_untrusted_ai_input_not_generated_topics_validated_page_topics_content_gaps_intent_freshness_whole_site_provider_or_approval_authority' }) });
  return selection;
}
async function topicDetail(): Promise<Row> {
  const row = await aiDetail(); const selection = await topicSelection(topicInput());
  return { ...row, selection, selection_digest: await sha(selection), evidence: { job_id: 61, source_current: true, synthesis: {
    method_version: 'competitor-heading-topics-v1', organization_id: 7, project_id: 9,
    source_selection_digest: selection['configuration'].source_selection_digest, model_id: 31, account_id: 41, generated_at: GENERATED,
    observation: headingsEvidence(), topics: [{ label: '<img src=x onerror=alert(1)> is unverified', reference: 'heading_1', quote: 'Same' }],
    state: 'unverified_heading_topic_hypotheses_require_human_review',
    interpretation: 'original_single_heading_facts_separate_from_unverified_cited_topic_hypotheses_not_semantic_truth_page_topics_gaps_intent_freshness_rankings_whole_site_or_approval' } } };
}
const job = () => ({ id: 21, status: 'queued', created_at: DATE, updated_at: LATER, cancel_requested: false, estimate_units: 1, error_category: '' });
function canonical(value: any): any {
  return Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
}
async function sha(value: any) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(canonical(value))))),
    byte => byte.toString(16).padStart(2, '0')).join('');
}
function evidence(origin = ORIGIN): Row {
  return { job_id: 21, source_current: true, collection: { method_version: 'competitor-static-root-collect-v1', state: 'collected',
    requested_url: origin + '/', url: origin + '/', observed_at: OBSERVED, robots: 'available', source_sha256: 'a'.repeat(64),
    interpretation: 'one_selected_static_root_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks', evidence: {
      method_version: 'competitor-static-metadata-v1', url: origin + '/', observed_at: OBSERVED, body_sha256: 'b'.repeat(64), body_size_bytes: 100,
      state: 'observed', reason: '', metadata: { title: '<script>literal only</script>', description: 'Dated static description', title_truncated: false, description_truncated: false },
      counts: { h1: 1, h2: 0, h3: 0, h4: 0, h5: 0, h6: 0, href_anchors: 2, json_ld_blocks: 1 },
      coverage: 'one_complete_returned_static_document_selected_lexical_metadata_only',
      excluded_containers: ['iframe', 'math', 'noembed', 'noframes', 'noscript', 'plaintext', 'script', 'style', 'svg', 'template', 'textarea', 'xmp'],
      interpretation: 'static_syntax_not_rendering_schema_validity_topics_publication_age_traffic_rankings_backlinks_or_whole_site',
    } } };
}
function pageEvidence(origin = ORIGIN, path = '/selected/article'): Row {
  const result = evidence(origin); const c = result['collection'];
  c.method_version = 'competitor-static-page-collect-v1'; c.requested_url = c.url = c.evidence.url = origin + path;
  c.interpretation = 'one_selected_static_nonroot_uri_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks';
  return result;
}
function headingsEvidence(origin = ORIGIN): Row {
  const result = pageEvidence(origin); const original = result['collection'].evidence;
  const { metadata: _metadata, ...fields } = original;
  result['collection'].method_version = 'competitor-page-headings-collect-v1';
  result['collection'].evidence = { ...fields, method_version: 'competitor-static-headings-v1',
    headings: [{ level: 2, text: '<img src=x onerror=alert(1)>', truncated: false }, { level: 1, text: 'Same', truncated: false },
      { level: 1, text: 'Same', truncated: false }, { level: 6, text: '🙂'.repeat(80), truncated: true }],
    counts: { h1: 2, h2: 1, h3: 0, h4: 0, h5: 0, h6: 1 },
    coverage: 'one_complete_returned_static_document_non_inert_heading_occurrences_in_original_order',
    interpretation: 'literal_text_levels_not_browser_visibility_semantic_outline_accessibility_topics_page_identity_publication_age_freshness_or_whole_site' };
  return result;
}
function formatsEvidence(origin = ORIGIN): Row {
  const result = pageEvidence(origin); const { metadata: _metadata, counts: _counts, ...fields } = result['collection'].evidence;
  result['collection'].method_version = 'competitor-page-elements-collect-v1';
  result['collection'].evidence = { ...fields, method_version: 'competitor-static-content-elements-v1',
    counts: { p: 2, ul: 1, ol: 0, table: 1, img: 2, picture: 0, video: 0, audio: 0 },
    coverage: 'one_complete_returned_static_document_non_inert_selected_start_tag_occurrences_only',
    interpretation: 'literal_start_tags_not_rendered_content_formats_page_types_loaded_media_accessibility_search_result_features_topics_freshness_or_whole_site' };
  return result;
}
function formatsStructure(pages?: Row[]): Row {
  if (!pages) {
    pages = [formatsEvidence(), formatsEvidence()];
    pages.forEach((page, i) => {
      page['job_id'] = 21 + i; const collection = page['collection'];
      collection.url = collection.requested_url = collection.evidence.url = ORIGIN + (i ? '/selected/b' : '/selected/a');
      collection.source_sha256 = (i ? 'c' : 'a').repeat(64);
    });
  }
  const element_names = ['p', 'ul', 'ol', 'table', 'img', 'picture', 'video', 'audio'];
  return { method_version: 'competitor-two-page-elements-v1', organization_id: 7, project_id: 9, source_current: true, pages,
    element_names, selected_element_occurrences: pages.map(page => element_names.map(name => page['collection'].evidence.counts[name])),
    all_rows_observed: pages.every(page => page['collection'].evidence.state === 'observed'),
    interpretation: 'two_selected_static_samples_literal_start_tag_counts_not_rendered_formats_loaded_media_semantic_page_types_search_features_accessibility_site_totals_whole_site_freshness_changes_causality_ai_or_collection_authority' };
}
function datesEvidence(origin = ORIGIN): Row {
  const result = pageEvidence(origin); const { metadata: _metadata, counts: _counts, ...fields } = result['collection'].evidence;
  result['collection'].method_version = 'competitor-page-dates-collect-v1';
  result['collection'].evidence = { ...fields, method_version: 'competitor-static-dates-v1',
    declarations: [{ property: 'article:published_time', value: '2099-01-01', truncated: false },
      { property: 'article:modified_time', value: '<img src=x onerror=alert(1)>', truncated: false },
      { property: 'article:published_time', value: '', truncated: false }],
    coverage: 'one_complete_returned_static_document_two_exact_article_meta_properties_only',
    interpretation: 'literal_meta_declarations_not_validated_dates_page_identity_publication_change_age_freshness_publishing_cadence_or_whole_site' };
  return result;
}
function dateCandidatePacket(): Row {
  return { ...datesEvidence(), method_version: 'competitor-date-literal-candidates-v1',
    interpretation: 'stored_article_date_literal_syntax_candidates_not_validated_publication_change_age_freshness_cadence_page_identity_whole_site_causality_approval_ai_or_source_authority',
    candidates: [
      { declaration_index: 0, state: 'calendar_literal', calendar_date: '2099-01-01', utc_instant: null, after_observation: null },
      ...[1, 2].map(declaration_index => ({ declaration_index, state: 'unsupported_literal', calendar_date: null, utc_instant: null, after_observation: null }))] };
}
function destinationsEvidence(origin = ORIGIN): Row {
  const result = pageEvidence(origin); const { metadata: _metadata, ...fields } = result['collection'].evidence;
  result['collection'].method_version = 'competitor-page-destinations-v1';
  result['collection'].evidence = { ...fields, method_version: 'competitor-static-destinations-v1',
    destinations: [origin + '/one', origin + '/one', origin + '/a&b'],
    counts: { href_anchors: 5, same_origin_http: 3, other_origin_http: 1, unsupported: 1 },
    coverage: 'one_complete_returned_static_document_non_inert_same_origin_href_occurrences_no_base_stdlib_join_in_original_order',
    interpretation: 'resolved_static_same_origin_references_not_unique_pages_fetched_destinations_link_health_crawl_authority_browser_visibility_topics_or_whole_site_structure' };
  return result;
}
function headingsStructure(pages?: Row[]): Row {
  if (!pages) {
    pages = [headingsEvidence(), headingsEvidence()];
    pages.forEach((page, index) => {
      page['job_id'] = 21 + index; const collection = page['collection'];
      collection.url = collection.requested_url = collection.evidence.url = ORIGIN + (index ? '/selected/b' : '/selected/a');
    });
    pages[1]['collection'].evidence.headings = [{ level: 3, text: 'Second', truncated: false }, { level: 6, text: 'x'.repeat(80), truncated: true }];
    pages[1]['collection'].evidence.counts = { h1: 0, h2: 0, h3: 1, h4: 0, h5: 0, h6: 1 };
  }
  const levels = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'];
  return { method_version: 'competitor-two-page-headings-v1', organization_id: 7, project_id: 9, source_current: true, pages,
    heading_levels: levels, selected_heading_occurrences: pages.map(page => levels.map(name => page['collection'].evidence.counts[name])),
    all_rows_observed: pages.every(page => page['collection'].evidence.state === 'observed'),
    interpretation: 'two_selected_static_samples_literal_heading_level_counts_with_original_text_order_truncation_not_rendered_semantic_outline_accessibility_topics_intent_page_identity_freshness_site_totals_whole_site_causality_ai_or_collection_authority' };
}
function referenceStructure(): Row {
  const pages = [destinationsEvidence(), destinationsEvidence()];
  const urls = [ORIGIN + '/selected/a', ORIGIN + '/selected/b'];
  pages.forEach((page, i) => {
    page['job_id'] = 21 + i; const collection = page['collection'];
    collection.url = collection.requested_url = collection.evidence.url = urls[i];
    collection.source_sha256 = (i ? 'c' : 'a').repeat(64);
    collection.evidence.destinations = i ? [urls[0]] : [urls[1], urls[1], urls[1] + '/', ORIGIN + '/selected/%62'];
    collection.evidence.counts = { href_anchors: i ? 3 : 6, same_origin_http: i ? 1 : 4, other_origin_http: 1, unsupported: 1 };
  });
  return { method_version: 'competitor-two-page-references-v1', organization_id: 7, project_id: 9, source_current: true, pages,
    selected_uri_reference_occurrences: [[0, 2], [1, 0]],
    interpretation: 'two_selected_static_samples_exact_reference_occurrences_not_unique_pages_target_health_browser_visibility_indexing_inbound_links_whole_site_topology_topics_freshness_causality_or_crawl_authority' };
}
function destinationInventory(pages: Row[] = referenceStructure()['pages']): Row {
  const rows = pages.map(page => page['collection'].evidence.destinations as string[] | null);
  const destinations = [...new Set(rows.flatMap(row => row ?? []))];
  return { method_version: 'competitor-two-sample-destination-inventory-v1', organization_id: 7, project_id: 9, source_current: true, pages,
    destinations, destination_reference_occurrences: rows.map(row => row === null ? null : destinations.map(url => row.filter(reference => reference === url).length)),
    all_rows_observed: rows.every(row => row !== null),
    interpretation: 'exact_stored_resolved_supported_destination_uris_in_two_selected_static_samples_not_complete_site_page_or_destination_inventory_fetched_targets_target_health_browser_visibility_indexing_inbound_links_topology_topics_freshness_causality_or_crawl_authority' };
}
function labEvidence(origin = ORIGIN, strategy = 'mobile'): Row {
  const url = origin + '/selected/article';
  return { job_id: 21, source_current: true, collection: { method_version: 'competitor-lighthouse-collect-v1', state: 'collected',
    selection_sha256: 'a'.repeat(64), url, strategy, robots: 'available', request_started_at: DATE,
    interpretation: 'one_original_selected_uri_device_provider_returned_lab_sample_not_field_data_current_site_whole_site_rankings_causality_or_live_provider_proof',
    evidence: { method_version: 'competitor-pagespeed-lab-v1', url, strategy, received_at: OBSERVED, response_sha256: 'b'.repeat(64), response_size_bytes: 100,
      provider_reported_at: '2025-12-31T03:00:00+03:00', state: 'observed', reason: '',
      coverage: 'one_complete_provider_json_selected_exact_nonroot_uri_lighthouse_lab_sample_only',
      interpretation: 'provider_reported_lab_sample_not_field_p75_core_web_vitals_whole_site_rankings_causality_ownership_current_site_or_live_provider_proof',
      lab: { source: 'pagespeed_insights', kind: 'lighthouse_lab', status: 'observed', requested_url: url, final_url: url, strategy,
        observed_at: '2025-12-31T03:00:00+03:00', lighthouse_version: '12.5.0', scores: { performance: 0.75, accessibility: 0, 'best-practices': null, seo: null },
        audits: { 'largest-contentful-paint': { value: 3000, unit: 'ms', state: 'observed' }, 'cumulative-layout-shift': { value: 0, unit: 'unitless', state: 'observed' },
          'total-blocking-time': { value: null, unit: 'ms', state: 'unavailable' }, 'speed-index': { value: null, unit: 'ms', state: 'unavailable' } },
        score_method: 'lighthouse_lab_score_not_field_p75', field_data: 'not_used' } } } };
}
function schemaEvidence(origin = ORIGIN): Row {
  return { job_id: 21, source_current: true, collection: {
    method_version: 'competitor-static-schema-root-collect-v1', state: 'collected', requested_url: origin + '/', url: origin + '/',
    observed_at: OBSERVED, robots: 'available', source_sha256: 'a'.repeat(64),
    interpretation: 'one_selected_static_root_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks', evidence: {
      method_version: 'competitor-static-schema-types-v1', url: origin + '/', observed_at: OBSERVED,
      body_sha256: 'b'.repeat(64), body_size_bytes: 100, state: 'observed', reason: '',
      summary: { json_ld_blocks: 1, typed_nodes: 2, types: ['Article', 'Organization'], unrecognized_type_count: 1 },
      coverage: 'one_complete_returned_static_document_non_inert_json_ld_fixed_type_labels_only',
      excluded_containers: ['iframe', 'math', 'noembed', 'noframes', 'noscript', 'plaintext', 'script', 'style', 'svg', 'template', 'textarea', 'xmp'],
      interpretation: 'lexical_declarations_not_resolved_schema_validity_actual_page_type_rich_results_visible_consistency_or_whole_site',
    },
  } };
}
function linksEvidence(origin = ORIGIN): Row {
  return { job_id: 21, source_current: true, collection: {
    method_version: 'competitor-static-root-links-collect-v1', state: 'collected', requested_url: origin + '/', url: origin + '/',
    observed_at: OBSERVED, robots: 'available', source_sha256: 'a'.repeat(64),
    interpretation: 'one_selected_static_root_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks', evidence: {
      method_version: 'competitor-static-link-categories-v1', url: origin + '/', observed_at: OBSERVED,
      body_sha256: 'b'.repeat(64), body_size_bytes: 100, state: 'observed', reason: '',
      counts: { href_anchors: 3, same_origin_http: 1, other_origin_http: 1, unsupported: 1 },
      coverage: 'one_complete_returned_static_document_non_inert_html_decoded_href_occurrences_no_base_stdlib_uri_join_only',
      excluded_containers: ['iframe', 'math', 'noembed', 'noframes', 'noscript', 'plaintext', 'script', 'style', 'svg', 'template', 'textarea', 'xmp'],
      interpretation: 'static_reference_categories_not_unique_pages_browser_visibility_link_health_inbound_links_or_whole_site_structure',
    },
  } };
}
function comparison(): Row {
  const before = evidence()['collection']['evidence']; const after = structuredClone(before);
  after.observed_at = LATER; after.body_sha256 = 'e'.repeat(64); after.body_size_bytes = 120;
  after.metadata.title = 'Changed <img src=x onerror=alert(1)>'; after.counts.h1 = 0; after.counts.href_anchors = 4;
  return { method_version: 'competitor-static-comparison-v1', organization_id: 7, project_id: 9, source_current: true,
    collection_method: 'competitor-static-root-collect-v1', parser_method: 'competitor-static-metadata-v1', url: ORIGIN + '/', source_sha256: 'a'.repeat(64),
    previous: { job_id: 21, robots: 'available', evidence: before }, current: { job_id: 22, robots: 'missing_http_404_or_410', evidence: after },
    comparable: true, state: 'comparable_original_static_metadata', body_changed: true, metadata_changed: { title: true, description: false },
    count_deltas: { h1: -1, h2: 0, h3: 0, h4: 0, h5: 0, h6: 0, href_anchors: 2, json_ld_blocks: 0 },
    interpretation: 'dated_selected_root_literal_changes_not_topics_publication_age_schema_validity_traffic_rankings_backlinks_whole_site_or_causality' };
}
function pageComparison(): Row {
  const result = comparison(); const url = ORIGIN + '/selected/article';
  result['method_version'] = 'competitor-static-page-comparison-v1'; result['collection_method'] = 'competitor-static-page-collect-v1'; result['url'] = url;
  result['previous'].evidence.url = result['current'].evidence.url = url;
  result['interpretation'] = 'dated_selected_nonroot_uri_literal_changes_not_page_identity_topics_publication_age_freshness_schema_validity_traffic_rankings_backlinks_whole_site_or_causality';
  return result;
}
function schemaComparison(): Row {
  const before = schemaEvidence()['collection']['evidence']; const after = structuredClone(before);
  after.observed_at = LATER; after.body_sha256 = 'e'.repeat(64); after.body_size_bytes = 120;
  after.summary = { json_ld_blocks: 1, typed_nodes: 1, types: ['VideoObject', 'WebPage'], unrecognized_type_count: 0 };
  const result = comparison(); delete result['metadata_changed'];
  return { ...result, method_version: 'competitor-static-schema-comparison-v1', collection_method: 'competitor-static-schema-root-collect-v1',
    parser_method: 'competitor-static-schema-types-v1', previous: { job_id: 21, robots: 'available', evidence: before },
    current: { job_id: 22, robots: 'missing_http_404_or_410', evidence: after }, state: 'comparable_original_static_schema_labels',
    type_changes: { added: ['VideoObject', 'WebPage'], removed: ['Article', 'Organization'] },
    count_deltas: { json_ld_blocks: 0, typed_nodes: -1, unrecognized_type_count: -1 },
    interpretation: 'dated_selected_root_lexical_label_changes_not_resolved_schema_validity_actual_page_type_rich_results_topics_freshness_whole_site_or_causality' };
}
function linksComparison(): Row {
  const before = linksEvidence()['collection']['evidence']; const after = structuredClone(before);
  after.observed_at = LATER; after.body_sha256 = 'e'.repeat(64); after.body_size_bytes = 120;
  after.counts = { href_anchors: 2, same_origin_http: 0, other_origin_http: 2, unsupported: 0 };
  const result = comparison(); delete result['metadata_changed'];
  return { ...result, method_version: 'competitor-static-link-categories-comparison-v1', collection_method: 'competitor-static-root-links-collect-v1',
    parser_method: 'competitor-static-link-categories-v1', previous: { job_id: 21, robots: 'available', evidence: before },
    current: { job_id: 22, robots: 'missing_http_404_or_410', evidence: after }, state: 'comparable_original_static_link_categories',
    count_deltas: { href_anchors: -1, same_origin_http: -1, other_origin_http: 1, unsupported: -1 },
    interpretation: 'dated_selected_root_literal_reference_category_changes_not_destinations_unique_pages_browser_visibility_link_health_inbound_links_whole_site_structure_freshness_or_causality' };
}
function headingsComparison(): Row {
  const before = headingsEvidence()['collection'].evidence; before.headings[3].truncated = false;
  const after = structuredClone(before); after.observed_at = LATER; after.body_sha256 = 'e'.repeat(64);
  after.headings[0].text = 'Changed <img src=x onerror=alert(1)>'; after.headings.pop(); after.counts.h6 = 0;
  const result = pageComparison(); delete result['metadata_changed'];
  return { ...result, method_version: 'competitor-page-headings-comparison-v1', collection_method: 'competitor-page-headings-collect-v1',
    parser_method: 'competitor-static-headings-v1', previous: { job_id: 21, robots: 'available', evidence: before },
    current: { job_id: 22, robots: 'missing_http_404_or_410', evidence: after }, state: 'comparable_original_static_heading_text_and_order',
    headings_changed: true, count_deltas: { h1: 0, h2: 0, h3: 0, h4: 0, h5: 0, h6: -1 },
    interpretation: 'dated_selected_nonroot_uri_literal_heading_text_order_changes_not_browser_semantic_outline_accessibility_topics_page_identity_freshness_whole_site_or_causality' };
}
function destinationsComparison(): Row {
  const before = destinationsEvidence()['collection'].evidence;
  const after = structuredClone(before); after.observed_at = LATER; after.body_sha256 = 'e'.repeat(64);
  after.destinations = [ORIGIN + '/a&b', ORIGIN + '/one', ORIGIN + '/one'];
  const result = pageComparison(); delete result['metadata_changed'];
  return { ...result, method_version: 'competitor-page-references-pair-v1', collection_method: 'competitor-page-destinations-v1',
    parser_method: 'competitor-static-destinations-v1', previous: { job_id: 21, robots: 'available', evidence: before },
    current: { job_id: 22, robots: 'missing_http_404_or_410', evidence: after }, state: 'comparable_original_static_supported_same_origin_references',
    destinations_changed: true, count_deltas: { href_anchors: 0, same_origin_http: 0, other_origin_http: 0, unsupported: 0 },
    interpretation: 'dated_selected_nonroot_uri_literal_supported_same_origin_reference_order_changes_not_unique_pages_fetched_targets_link_health_browser_visibility_freshness_whole_site_causality_or_crawl_authority' };
}
function formatsComparison(): Row {
  const before = formatsEvidence()['collection'].evidence; const after = structuredClone(before);
  after.observed_at = LATER; after.body_sha256 = 'e'.repeat(64); after.body_size_bytes = 120;
  after.counts = { p: 1, ul: 0, ol: 1, table: 2, img: 0, picture: 1, video: 1, audio: 1 };
  const result = pageComparison(); delete result['metadata_changed'];
  return { ...result, method_version: 'competitor-page-elements-pair-v1', collection_method: 'competitor-page-elements-collect-v1',
    parser_method: 'competitor-static-content-elements-v1', previous: { job_id: 21, robots: 'available', evidence: before },
    current: { job_id: 22, robots: 'missing_http_404_or_410', evidence: after }, state: 'comparable_original_static_content_element_counts',
    count_deltas: { p: -1, ul: -1, ol: 1, table: 1, img: -2, picture: 1, video: 1, audio: 1 },
    interpretation: 'dated_selected_nonroot_uri_literal_start_tag_count_changes_not_rendered_formats_loaded_media_semantic_page_types_accessibility_search_features_topics_freshness_whole_site_causality_or_collection_authority' };
}
function datesComparison(): Row {
  const before = datesEvidence()['collection'].evidence; const after = structuredClone(before);
  after.observed_at = LATER; after.body_sha256 = 'e'.repeat(64); after.body_size_bytes = 120; after.declarations.reverse();
  const result = pageComparison(); delete result['metadata_changed']; delete result['count_deltas'];
  return { ...result, method_version: 'competitor-page-dates-pair-v1', collection_method: 'competitor-page-dates-collect-v1',
    parser_method: 'competitor-static-dates-v1', previous: { job_id: 21, robots: 'available', evidence: before },
    current: { job_id: 22, robots: 'missing_http_404_or_410', evidence: after }, state: 'comparable_original_static_article_date_declarations',
    declarations_changed: true,
    interpretation: 'dated_selected_nonroot_uri_literal_article_date_declaration_order_changes_not_validated_dates_publication_change_age_freshness_cadence_page_identity_whole_site_or_causality' };
}
function dateCandidatePair(): Row {
  const candidates = dateCandidatePacket()['candidates'];
  const empty = (previous_declaration_index: number, current_declaration_index: number) => ({ previous_declaration_index,
    current_declaration_index, state: 'incomparable_literal_candidates', calendar_day_delta: null, utc_microsecond_delta: null });
  return { method_version: 'competitor-date-candidate-pair-v1', organization_id: 7, project_id: 9, source_current: true,
    comparison: datesComparison(), previous_candidates: candidates,
    current_candidates: [...candidates].reverse().map((row: Row, declaration_index: number) => ({ ...row, declaration_index })),
    declaration_pair_candidates: [empty(0, 0), { ...empty(0, 2), state: 'calendar_candidates', calendar_day_delta: 0 },
      empty(1, 1), empty(2, 0), empty(2, 2)],
    interpretation: 'all_same_property_original_declaration_index_pairs_calendar_or_utc_candidate_intervals_not_matched_events_validated_publication_change_age_freshness_cadence_page_identity_whole_site_causality_approval_ai_or_source_authority' };
}
function labComparison(): Row {
  const before = labEvidence()['collection'], after = structuredClone(before);
  after.request_started_at = OBSERVED; after.evidence.received_at = LATER; after.evidence.response_sha256 = 'e'.repeat(64);
  after.evidence.provider_reported_at = after.evidence.lab.observed_at = '2026-01-01T00:00:00+00:00';
  after.evidence.lab.scores.performance = 0.5; after.evidence.lab.audits['largest-contentful-paint'].value = 2000;
  return { method_version: 'competitor-lighthouse-pair-v1', organization_id: 7, project_id: 9, source_current: true,
    collection_method: before.method_version, parser_method: before.evidence.method_version, url: before.url, strategy: before.strategy, selection_sha256: before.selection_sha256,
    previous: { job_id: 21, robots: before.robots, request_started_at: before.request_started_at, evidence: before.evidence },
    current: { job_id: 22, robots: after.robots, request_started_at: after.request_started_at, evidence: after.evidence },
    state: 'arithmetic_original_lab_samples', reason: '', body_changed: true,
    score_deltas: { performance: -0.25, accessibility: 0, 'best-practices': null, seo: null },
    audit_deltas: { 'largest-contentful-paint': { value: -1000, unit: 'ms' }, 'cumulative-layout-shift': { value: 0, unit: 'unitless' },
      'total-blocking-time': { value: null, unit: 'ms' }, 'speed-index': { value: null, unit: 'ms' } },
    interpretation: 'original_same_uri_device_version_lab_sample_arithmetic_not_controlled_conditions_representative_benchmark_statistical_significance_field_p75_current_site_whole_site_rankings_or_causality' };
}
class FixtureApi {
  preference: ApiResult | Error = { status: 200, body: { language: 'en', current_ui_language: 'en', current_email_language: 'en' } };
  async productLanguage(): Promise<ApiResult> { if (this.preference instanceof Error) throw this.preference; return this.preference; }
  headingsStructurePairs: number[][] = []; headingsStructureValue = headingsStructure();
  familyCalls: string[] = [];
  labKeyRevision = DATE;
  formatsPairs: [number, number][] = [];
  formatsStructurePairs: number[][] = []; formatsStructureValue = formatsStructure();
  datesPairs: [number, number][] = [];
  dateCandidatePairs: [number, number][] = []; dateCandidatePairValue = dateCandidatePair();
  labPairs: [number, number][] = [];
  actor = 1; authenticated = true; role = 'owner'; restricted = false; revision = 1; updated = DATE; source = 'skip';
  origins = [ORIGIN]; aliases: string[] = []; rows: ReturnType<typeof job>[] = []; keys: string[] = [];
  commands: Row[] = []; lookups: string[] = []; cancels: number[] = []; previews = 0;
  uncertain = false; drop = false; deny = false; badDigest = false; details: number[] = [];
  detailValue: Row | null = null; previewChange: ((row: Row) => void) | null = null;
  candidateCalls: number[] = []; candidateValue = dateCandidatePacket(); candidateStatus = 200;
  afterCandidates: (() => void) | null = null; candidatePromise: Promise<ApiResult> | null = null;
  detailPromise: Promise<ApiResult> | null = null; previewPromise: Promise<ApiResult> | null = null; postPromise: Promise<ApiResult> | null = null;
  afterPreview: (() => void) | null = null; afterPost: (() => void) | null = null; afterDetail: (() => void) | null = null;
  pairs: number[][] = []; pairValue = comparison(); pairStatus = 200; afterPair: (() => void) | null = null;
  destinationsPairs: number[][] = []; pagePairs: number[][] = []; headingsPairs: number[][] = []; schemaPairs: number[][] = []; linksPairs: number[][] = [];
  pairPromise: Promise<ApiResult> | null = null;
  structurePairs: number[][] = []; structureValue = referenceStructure();
  inventoryPairs: number[][] = []; inventoryValue = destinationInventory();
  modelRows: Row[] = [model()]; accountRows: Row[] = [account()]; catalogCalls = 0;
  synthRows: ReturnType<typeof synthesisJob>[] = []; synthKeys: string[] = []; synthCommands: Row[] = []; synthLookups: string[] = []; synthCancels: number[] = [];
  synthPreviews = 0; synthDetails: number[] = []; synthUnknown = false; synthDrop = false; synthDeny = false;
  synthDetailValue: Row | null = null; synthPreviewChange: ((row: Row) => void) | null = null;
  topicDetails: Record<number, Row> = {}; topicSources: Record<number, Row> = {};
  topicPairs: number[][] = []; topicPairValue: Row | null = null;
  topicPairChange: (() => void) | null = null; topicPairPromise: Promise<ApiResult> | null = null;
  afterSynthesisPreview: (() => void) | null = null; afterSynthesisPost: (() => void) | null = null; afterSynthesisDetail: (() => void) | null = null;
  synthDetailPromise: Promise<ApiResult> | null = null; synthPostPromise: Promise<ApiResult> | null = null;
  async projectAITextCatalog(): Promise<ApiResult> {
    ++this.catalogCalls;
    return { status: 200, body: { models: this.modelRows, accounts: this.accountRows, has_more: false, estimate_units: 1, cost_status: 'unknown' } };
  }
  synthFamilies: string[] = [];
  async competitorSyntheses(org: number, project: number, data?: Row, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.synthFamilies.push('root'); return this.syntheses(org, project, data, id, key, preview);
  }
  async competitorHeadingSyntheses(org: number, project: number, data?: Row, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.synthFamilies.push('headings'); return this.syntheses(org, project, data, id, key, preview);
  }
  async competitorHeadingTopics(org: number, project: number, data?: Row, id?: number, key?: string, preview = false): Promise<ApiResult> {
    this.synthFamilies.push('topics'); return this.syntheses(org, project, data, id, key, preview, true);
  }
  private async syntheses(org: number, project: number, data?: Row, id?: number, key?: string, preview = false, topics = false): Promise<ApiResult> {
    const scope = { organization_id: org, project_id: project }; if (this.synthDeny) return { status: 409, body: {} };
    if (preview) {
      ++this.synthPreviews; const selection = topics ? await topicSelection(data!, this.detailValue || headingsEvidence(), this.actor) : await aiSelection(data!, this.pairValue, this.actor);
      const row = { ...scope, selection, selection_digest: '', estimate_units: 1 }; this.synthPreviewChange?.(row);
      row['selection_digest'] = await sha(row['selection']); this.afterSynthesisPreview?.(); return { status: 200, body: row };
    }
    if (data !== undefined) {
      if (id) { this.synthCancels.push(id); this.synthRows = this.synthRows.map(row => row.id === id ? { ...row, status: 'cancelled', cancel_requested: true } : row); }
      else { this.synthCommands.push(structuredClone(data)); if (!this.synthDrop) { this.synthRows = [synthesisJob()]; this.synthKeys = [data['idempotency_key']]; } }
      this.afterSynthesisPost?.(); if (this.synthPostPromise) return this.synthPostPromise;
      if (this.synthUnknown || this.synthDrop) throw new Error('Acknowledgment lost');
      return { status: 202, body: { ...scope, job: this.synthRows.find(row => !id || row.id === id) } };
    }
    if (id) {
      this.synthDetails.push(id); const row = this.synthRows.find(row => row.id === id)!;
      const value = this.topicDetails[id] || this.synthDetailValue || { ...scope, job: row, selection: await aiSelection(aiInput(), this.pairValue), selection_digest: '', usage: null, evidence: null };
      if (!this.synthDetailValue && !this.topicDetails[id]) value['selection_digest'] = await sha(value['selection']);
      this.afterSynthesisDetail?.(); return this.synthDetailPromise || { status: 200, body: value };
    }
    if (key) this.synthLookups.push(key);
    return { status: 200, body: { ...scope, jobs: key ? this.synthRows.filter((_row, i) => this.synthKeys[i] === key) : this.synthRows, has_more: false, lookup: key || null } };
  }
  session() { return Promise.resolve({ status: this.authenticated ? 200 : 401, body: { data: { user: { id: this.actor } }, meta: { is_authenticated: this.authenticated } } }); }
  projectOnboarding(org: number, project: number) { return Promise.resolve({ status: 200, body: {
    project: { id: project, organization_id: org, canonical_origin: OWN, aliases: this.aliases, role: this.role, access_restricted: this.restricted },
    configuration: { project_id: project, canonical_origin: OWN, competitor_origins: this.origins, revision: this.revision, updated_at: this.updated, source_choice: this.source },
  } }); }
  async competitorRootComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.pairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorLighthouseComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.labPairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.deny ? 403 : this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorPageFormatsComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.formatsPairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorPageHeadingsStructure(org: number, project: number, first: number, second: number): Promise<ApiResult> {
    this.headingsStructurePairs.push([first, second]); this.afterPair?.();
    return this.pairPromise || { status: this.deny ? 403 : this.pairStatus, body: { organization_id: org, project_id: project, structure: this.headingsStructureValue } };
  }
  async competitorPageFormatsStructure(org: number, project: number, first: number, second: number): Promise<ApiResult> {
    this.formatsStructurePairs.push([first, second]); this.afterPair?.();
    return this.pairPromise || { status: this.deny ? 403 : this.pairStatus, body: { organization_id: org, project_id: project, structure: this.formatsStructureValue } };
  }
  async competitorPageDatesComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.datesPairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorPageDateCandidateComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.dateCandidatePairs.push([previous, current]);
    const result = { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: structuredClone(this.dateCandidatePairValue) } };
    this.afterPair?.(); return this.pairPromise || result;
  }
  async competitorPageDestinationsComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.destinationsPairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorPageDestinationInventory(org: number, project: number, first: number, second: number): Promise<ApiResult> {
    this.inventoryPairs.push([first, second]); this.afterPair?.();
    return this.pairPromise || { status: this.deny ? 403 : this.pairStatus, body: { organization_id: org, project_id: project, inventory: this.inventoryValue } };
  }
  async competitorPageReferenceStructure(org: number, project: number, first: number, second: number): Promise<ApiResult> {
    this.structurePairs.push([first, second]); this.afterPair?.();
    return this.pairPromise || { status: this.deny ? 403 : this.pairStatus, body: { organization_id: org, project_id: project, structure: this.structureValue } };
  }
  async competitorHeadingTopicsComparison(org: number, project: number, first: number, second: number): Promise<ApiResult> {
    this.topicPairs.push([first, second]); this.topicPairChange?.();
    return this.topicPairPromise || { status: this.synthDeny ? 403 : this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.topicPairValue } };
  }
  async competitorPageHeadingsComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.headingsPairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorPageComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.pagePairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorSchemaRootComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.schemaPairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorLinksRootComparison(org: number, project: number, previous: number, current: number): Promise<ApiResult> {
    this.linksPairs.push([previous, current]); this.afterPair?.();
    return this.pairPromise || { status: this.pairStatus, body: { organization_id: org, project_id: project, comparison: this.pairValue } };
  }
  async competitorRoots(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('metadata'); return this.rootCommand(org, project, data, id, key, selection, false);
  }
  async competitorSchemaRoots(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('schema'); return this.rootCommand(org, project, data, id, key, selection, true);
  }
  async competitorLinksRoots(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('links'); return this.rootCommand(org, project, data, id, key, selection, false, true);
  }
  async competitorPages(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('page'); return this.rootCommand(org, project, data, id, key, selection, false, false, true);
  }
  async competitorPageHeadings(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('headings'); return this.rootCommand(org, project, data, id, key, selection, false, false, true, true);
  }
  async competitorPageDestinations(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('destinations'); return this.rootCommand(org, project, data, id, key, selection, false, false, true, false, true);
  }
  async competitorPageFormats(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('formats'); return this.rootCommand(org, project, data, id, key, selection, false, false, true, false, false, false, false, true);
  }
  async competitorPageDates(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('dates'); return this.rootCommand(org, project, data, id, key, selection, false, false, true, false, false, true);
  }
  async competitorPageDateCandidates(org: number, project: number, id: number): Promise<ApiResult> {
    this.candidateCalls.push(id);
    if (this.candidatePromise) return this.candidatePromise;
    const result = { status: this.candidateStatus, body: { organization_id: org, project_id: project,
      job: structuredClone(this.rows.find(row => row.id === id)), candidates: structuredClone(this.candidateValue) } };
    this.afterCandidates?.(); return result;
  }
  async competitorLighthouse(org: number, project: number, data?: Row, id?: number, key?: string, selection = false): Promise<ApiResult> {
    this.familyCalls.push('lighthouse'); return this.rootCommand(org, project, data, id, key, selection, false, false, true, false, false, false, true);
  }
  private async rootCommand(org: number, project: number, data?: Row, id?: number, key?: string, selection = false, schema = false, links = false, page = false, headings = false, destinations = false, dates = false, lighthouse = false, formats = false): Promise<ApiResult> {
    const scope = { organization_id: org, project_id: project };
    if (this.deny) return { status: 403, body: {} };
    if (selection) {
      ++this.previews;
      const row: Row = { ...scope, estimate_units: 1, selection: { method: formats ? 'competitor-page-elements-collect-v1' : lighthouse ? 'competitor-lighthouse-collect-v1' : dates ? 'competitor-page-dates-collect-v1' : destinations ? 'competitor-page-destinations-v1' : headings ? 'competitor-page-headings-collect-v1' : page ? 'competitor-static-page-collect-v1' : links ? 'competitor-static-root-links-collect-v1' : schema ? 'competitor-static-schema-root-collect-v1' : 'competitor-static-root-collect-v1', use_permission: true, storage_permission: true, binding: {
        method_version: page ? 'competitor-page-source-v1' : 'competitor-source-v1', ...(page ? { url: data!['url'] } : {}), organization_id: org, project_id: project, actor_id: this.actor, origin: data!['origin'],
        hostname: new URL(data!['origin']).hostname, scope_kind: page ? 'selected_competitor_exact_same_origin_default_port_nonroot_uri_no_query_fragment' : 'selected_competitor_hostname_default_http_https_only', collection_permission: true,
        configuration_revision: this.revision, configuration_updated_at: this.updated, source_sha256: 'c'.repeat(64),
        interpretation: page ? 'customer_selected_exact_uri_not_page_identity_ownership_approval_time_network_commercial_or_observation_authority' : 'customer_selected_public_host_not_ownership_approval_time_network_commercial_or_observation_authority',
      } }, selection_digest: '' };
      if (lighthouse) {
        const source: Row = { method_version: 'competitor-lighthouse-source-v1', provider: 'google_pagespeed_insights', page_source: row['selection'].binding,
          strategy: data!['strategy'], provider_processing_permission: true,
          interpretation: 'current_selected_exact_uri_device_and_declared_google_processing_permission_not_ownership_legal_approval_key_network_commercial_or_observed_lab_authority' };
        source['source_sha256'] = await sha(source);
        const binding: Row = { method_version: 'competitor-lighthouse-selection-v1', source, performance_credential: { source: 'organization', revision: this.labKeyRevision, state: 'active' },
          interpretation: 'current_source_and_credential_configuration_reference_not_key_validity_provider_access_quota_network_commercial_or_observed_lab_authority' };
        binding['selection_sha256'] = await sha(binding); row['selection'].binding = binding;
      }
      this.previewChange?.(row); row['selection_digest'] = this.badDigest ? 'd'.repeat(64) : await sha(row['selection']); this.afterPreview?.();
      return this.previewPromise || { status: 200, body: row };
    }
    if (data !== undefined) {
      if (id) { this.cancels.push(id); this.rows = this.rows.map(row => row.id === id ? { ...row, status: 'cancelled', cancel_requested: true } : row); }
      else { this.commands.push(structuredClone(data)); if (!this.drop) { this.rows = [job()]; this.keys = [data['idempotency_key']]; } }
      this.afterPost?.();
      if (this.postPromise) return this.postPromise;
      if (this.uncertain || this.drop) throw new Error('Lost acknowledgement');
      return { status: 202, body: { ...scope, job: this.rows.find(row => !id || row.id === id) } };
    }
    if (id) {
      this.details.push(id);
      const original = formats ? formatsEvidence(this.origins[0]) : lighthouse ? labEvidence(this.origins[0]) : dates ? datesEvidence(this.origins[0]) : destinations ? destinationsEvidence(this.origins[0]) : headings ? headingsEvidence(this.origins[0]) : page ? pageEvidence(this.origins[0]) : links ? linksEvidence(this.origins[0]) : schema ? schemaEvidence(this.origins[0]) : evidence(this.origins[0]);
      if (dates && this.pairValue['parser_method'] === 'competitor-static-dates-v1') {
        original['job_id'] = id; original['collection'].observed_at = this.pairValue[id === 22 ? 'current' : 'previous'].evidence.observed_at;
        original['collection'].evidence = structuredClone(this.pairValue[id === 22 ? 'current' : 'previous'].evidence);
      }
      if (headings && this.pairValue['parser_method'] === 'competitor-static-headings-v1') {
        original['job_id'] = id; original['collection'].observed_at = this.pairValue[id === 22 ? 'current' : 'previous'].evidence.observed_at;
        original['collection'].evidence = structuredClone(this.pairValue[id === 22 ? 'current' : 'previous'].evidence);
      }
      if (id === 22 && !page) { original['job_id'] = id; original['collection'].observed_at = LATER; original['collection'].evidence = structuredClone(this.pairValue['current'].evidence); }
      const row = { ...scope, job: this.rows.find(row => row.id === id), evidence: this.rows.find(row => row.id === id)?.status === 'succeeded' ? this.topicSources[id] || this.detailValue || original : null };
      this.afterDetail?.(); return this.detailPromise || { status: 200, body: row };
    }
    if (key) this.lookups.push(key);
    return { status: 200, body: { ...scope, jobs: key ? this.rows.filter((_row, i) => this.keys[i] === key) : this.rows, has_more: false, lookup: key || null } };
  }
}
describe.each([
  ['root', '/competitor-roots/7/9'], ['headings', '/competitor-page-headings/7/9'], ['topics', '/competitor-heading-topics/7/9'],
])('Private %s synthesis scalar metadata', (family, path) => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl(path, CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return component;
  }
  async function failedDetail(): Promise<Row> {
    const row = family === 'topics' ? await topicDetail() : await aiDetail(family === 'headings');
    row['job'].status = 'failed'; row['evidence'] = null; row['usage'].status = 'failed';
    return row;
  }
  async function read(component: CompetitorRoots, row: Row) {
    api.synthDetailValue = row; api.synthRows = [row['job']];
    await component.load(); await component.loadSyntheses(); await component.inspectSynthesis(61);
  }
  it('rejects array account sources before retaining synthesis choices and preserves both scalar sources', async () => {
    const component = await screen();
    for (const source of ['platform', 'organization']) {
      api.accountRows = [{ ...account(), source: [source] }];
      await component.load(); await component.loadSyntheses();
      expect(component.synthesisLoaded()).toBe(false); expect(component.accounts()).toEqual([]);
      expect(component.models()).toEqual([]); expect(component.synthesisJobs()).toEqual([]);
      expect(component.aiPermission()).toBe(false); await component.previewSynthesis(); await component.launchSynthesis();
      expect(api.synthPreviews).toBe(0); expect(api.synthCommands).toEqual([]);
      api.accountRows = [{ ...account(), source }]; await component.load(); await component.loadSyntheses();
      expect(component.synthesisLoaded()).toBe(true); expect(component.accounts()[0].source).toBe(source);
    }
  });
  it('rejects array tier and usage states in otherwise digest-bound non-successful synthesis detail', async () => {
    const component = await screen();
    for (const tier of ['standard', 'free']) {
      const malformed = await failedDetail(); malformed['selection'].configuration.model_access_tier = [tier];
      malformed['selection_digest'] = await sha(malformed['selection']);
      await read(component, malformed);
      expect(component.synthesisDetail()).toBeNull(); expect(component.synthesisEvidence()).toBeNull();
      const valid = await failedDetail(); valid['selection'].configuration.model_access_tier = tier;
      valid['selection'].input.allow_free = tier === 'free'; valid['selection_digest'] = await sha(valid['selection']);
      await read(component, valid); expect(component.synthesisDetail()?.['selection']).toEqual(valid['selection']);
    }
    for (const status of ['attempted', 'completed', 'failed', 'unknown']) {
      const valid = await failedDetail(); valid['usage'].status = status;
      valid['usage'].finished_at = status === 'attempted' ? null : FINISHED;
      await read(component, valid); expect(component.synthesisDetail()?.['usage']).toEqual(valid['usage']);
      const malformed = structuredClone(valid); malformed['usage'].status = [status];
      await read(component, malformed); expect(component.synthesisDetail()).toBeNull();
    }
    expect(component.pending()).toBeNull(); expect(api.synthPreviews).toBe(0);
    expect(api.synthCommands).toEqual([]); expect(api.commands).toEqual([]);
  });
});

describe('Private selected competitor root workflow', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-roots/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, origin = api.origins[0]) {
    component.editOrigin(origin); component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  function savedPair() { api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }]; }
  function selectPair(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('preserves literal BOM metadata while rejecting non-normalized Python whitespace and lone surrogates', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    api.detailValue = evidence(); api.detailValue['collection'].evidence.metadata.title = '\ufeffliteral\ufeff';
    await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    for (const title of ['a\u0085b', '\ud800']) {
      await component.load(); api.detailValue = evidence(); api.detailValue['collection'].evidence.metadata.title = title;
      await component.inspect(21); expect(component.evidence()).toBeNull();
    }
  });
  it.each(['en', 'tr'] as const)('uses three initially unchecked native declarations and queues only a frozen digest-bound exact saved root in %s', async (language) => {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    const { harness, component } = await screen(); harness.detectChanges();
    const inputs = [...harness.routeNativeElement!.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(inputs).toHaveLength(3); expect(inputs.every(input => !input.checked && input.required && !!input.closest('label'))).toBe(true);
    expect(harness.routeNativeElement!.querySelector('label[for=competitor-origin]')).not.toBeNull();
    component.editOrigin(ORIGIN); component.editPermission('collection', true); await component.preview(); expect(api.previews).toBe(0);
    component.editPermission('use', true); component.editPermission('storage', true); await component.preview();
    const original = structuredClone(component.selection()); expect(original).not.toBeNull();
    harness.detectChanges(); const origin = harness.routeNativeElement!.querySelector<HTMLSelectElement>('#competitor-origin')!;
    const rights = [...harness.routeNativeElement!.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(harness.routeNativeElement!.querySelector('section')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toBe(component.t('Selected competitor root observations'));
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('#competitor-origin')).toBe(origin); expect(origin.value).toBe(ORIGIN);
    expect(rights.every(input => input.checked)).toBe(true); expect(component.selection()).toEqual(original); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.launch();
    expect(api.commands).toHaveLength(1); expect(api.commands[0]).toEqual({ origin: ORIGIN, collection_permission: true, use_permission: true, storage_permission: true,
      idempotency_key: expect.any(String), selection_digest: original!.selection_digest });
    expect(api.previews).toBe(2); expect(component.pending()).toBeNull(); expect(component.selected()?.id).toBe(21); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('accepts canonical HTTP as well as HTTPS, filters own host aliases and never takes query input as a competitor', async () => {
    api.origins = ['http://competitor.example.invalid', OWN, 'http://alias.example.invalid']; api.aliases = ['https://alias.example.invalid'];
    const { component, harness } = await screen(); expect(component.origins()).toEqual(['http://competitor.example.invalid']);
    component.editOrigin(OWN); expect(component.origin()).toBe('');
    declare(component); await component.preview(); await component.launch(); expect(api.commands[0]['origin']).toBe('http://competitor.example.invalid');
    await harness.navigateByUrl('/competitor-roots/7/10?origin=https://unapproved.example.invalid', CompetitorRoots);
    await harness.fixture.whenStable(); expect(component.origin()).toBe(''); expect(component.pending()).toBeNull();
  });
  it.each(['role', 'actor', 'revision', 'updated', 'restricted', 'origins', 'authenticated', 'source'])('clears all private state after current %s loss between preview and command', async field => {
    const { component } = await screen(); declare(component); await component.preview();
    if (field === 'role') api.role = 'member'; if (field === 'actor') api.actor = 2; if (field === 'revision') ++api.revision;
    if (field === 'updated') api.updated = OBSERVED; if (field === 'restricted') api.restricted = true;
    if (field === 'origins') api.origins = []; if (field === 'authenticated') api.authenticated = false; if (field === 'source') api.source = 'synthetic_demo';
    await component.launch(); expect(api.commands).toHaveLength(0); expect(component.ready()).toBe(false); expect(component.selection()).toBeNull(); expect(component.pending()).toBeNull();
    expect(component.collectionPermission()).toBe(false); expect(component.jobs()).toEqual([]);
  });
  it.each(['en', 'tr'] as const)('freezes lost acknowledgement in memory and reconciles only the original own-key GET, without replay in %s', async (language) => {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    const { component, harness } = await screen(); declare(component); await component.preview(); api.uncertain = true;
    await component.launch(); const frozen = structuredClone(component.pending()); expect(frozen).not.toBeNull();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.pending()).toEqual(frozen); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(component.t('Look up the exact original command (GET only)'));
    await component.launch(); await component.load(); expect(api.commands).toHaveLength(1);
    await component.reconcile(); expect(api.lookups).toEqual([frozen!.key]); expect(api.commands).toHaveLength(1);
    expect(component.pending()).toBeNull(); expect(component.selected()?.id).toBe(21); expect(component.evidence()).toBeNull();
  });
  it('leaves an absent lookup uncertain, then discards only local uncertainty without automatic retry', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.drop = true; await component.launch();
    const key = component.pending()!.key; await component.reconcile(); await component.reconcile();
    expect(component.pending()!.key).toBe(key); expect(api.commands).toHaveLength(1); expect(component.message()).toContain('No saved own-actor');
    component.discard(); expect(component.pending()).toBeNull(); expect(component.selection()).toBeNull();
  });
  it('reconciles uncertain cancellation using exact-job GET only and clears on an edit', async () => {
    api.rows = [job()]; const { component } = await screen(); api.uncertain = true;
    await component.cancel(999); expect(api.cancels).toEqual([]); await component.cancel(21); expect(component.pending()?.jobId).toBe(21);
    await component.reconcile(); expect(api.cancels).toEqual([21]); expect(component.selected()?.cancel_requested).toBe(true); expect(component.pending()).toBeNull();
    api.rows = [job()]; await component.load(); await component.cancel(21); component.editPermission('use', true); expect(component.pending()).toBeNull(); expect(component.selected()).toBeNull();
  });
  it('clears late command acknowledgement or uncertain command when current authority changes', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.afterPost = () => { api.actor = 2; };
    await component.launch(); expect(api.commands).toHaveLength(1); expect(component.pending()).toBeNull(); expect(component.selected()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('clears late preview and rejects shape, binding, rights, source and canonical digest tampering', async () => {
    const { component } = await screen();
    const changes: ((value: any) => void)[] = [v => { v.raw = 'unselected'; }, v => { v.selection.raw = 'unselected'; },
      v => { v.selection.method = 'own-crawl'; }, v => { v.selection.use_permission = 1; }, v => { v.selection.storage_permission = false; },
      v => { v.selection.binding.actor_id = 2; }, v => { v.selection.binding.project_id = 10; }, v => { v.selection.binding.source_sha256 = 'C'.repeat(64); },
      v => { v.selection.binding.configuration_revision = 2; }, v => { v.selection.binding.configuration_updated_at = OBSERVED; },
      v => { v.selection.binding.hostname = 'other.example.invalid'; }, v => { v.selection.binding.collection_permission = 1; },
      v => { v.selection.binding.interpretation = 'ownership'; }, v => { v.estimate_units = 0; }];
    for (const change of changes) { declare(component); api.previewChange = change; await component.preview(); expect(component.selection()).toBeNull(); }
    api.previewChange = null; api.badDigest = true; declare(component); await component.preview(); expect(component.selection()).toBeNull();
    api.badDigest = false; declare(component); api.afterPreview = () => { ++api.revision; }; await component.preview(); expect(component.ready()).toBe(false); expect(api.commands).toHaveLength(0);
  });
  it('displays original literal facts without HTML execution, retains independent reader source SHA and observed-empty versus null meanings', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; api.actor = 2; const { component, harness } = await screen();
    await component.inspect(21); harness.detectChanges(); expect(component.evidence()).not.toBeNull(); expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('<script>literal only</script>'); expect(api.previews).toBe(0);
    api.detailValue = evidence(); api.detailValue['collection'].evidence.metadata = { title: '', description: '', title_truncated: false, description_truncated: false };
    await component.inspect(21); expect(component.evidence()).not.toBeNull();
    api.detailValue['collection'].evidence.state = 'unavailable'; api.detailValue['collection'].evidence.reason = 'ambiguous_markup'; api.detailValue['collection'].evidence.metadata = null;
    api.detailValue['collection'].evidence.counts = Object.fromEntries(Object.keys(api.detailValue['collection'].evidence.counts).map(key => [key, null]));
    await component.inspect(21); expect(component.evidence()).not.toBeNull(); expect((component.evidence() as Row)['collection']['evidence']['counts']['h1']).toBeNull();
  });
  it('rejects private DTO expansion, wrong original dates/root/metadata/bounds/null semantics and late current loss', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    const changes: ((v: any) => void)[] = [v => { v.raw_html = 'not selected'; }, v => { v.job_id = 22; }, v => { v.source_current = 1; },
      v => { v.collection.requested_url = OWN + '/'; }, v => { v.collection.url = ORIGIN + '/other'; },
      v => { v.collection.observed_at = '2026-02-30T00:00:00.000001+00:00'; }, v => { v.collection.observed_at = DATE; v.collection.evidence.observed_at = LATER; },
      v => { v.collection.source_sha256 = 'C'.repeat(64); }, v => { v.collection.robots = 'unknown'; },
      v => { v.collection.robots = ['available']; }, v => { v.collection.observed_at = LATER; v.collection.evidence.observed_at = OBSERVED; },
      v => { v.collection.evidence.body_size_bytes = 131073; }, v => { v.collection.evidence.body_sha256 = 'secret'; },
      v => { v.collection.evidence.metadata.title = 'x'.repeat(501); }, v => { v.collection.evidence.metadata.title_truncated = 1; },
      v => { v.collection.evidence.metadata.title = ' leading'; }, v => { v.collection.evidence.counts.h1 = null; },
      v => { v.collection.evidence.counts.h1 = true; }, v => { v.collection.evidence.counts.h1 = 999; },
      v => { v.collection.evidence.state = 'unavailable'; }, v => { v.collection.evidence.excluded_containers = []; },
      v => { v.collection.evidence.schema = { raw: 'not selected' }; }];
    for (const change of changes) {
      await component.load(); api.detailValue = evidence(); change(api.detailValue); await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.selected()).toBeNull();
    }
    api.detailValue = null; await component.load(); api.afterDetail = () => { api.role = 'viewer'; }; await component.inspect(21); expect(component.ready()).toBe(false);
  });
  it('ignores late private responses after edit, route change and destruction', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component, harness } = await screen();
    let resolve!: (value: ApiResult) => void; api.detailPromise = new Promise(r => { resolve = r; });
    const reading = component.inspect(21); await vi.waitFor(() => expect(component.busy()).toBe(true));
    // Wait until the deferred exact read is actually reached, then invalidate its epoch.
    await vi.waitFor(() => expect(api.details).toEqual([21])); component.editOrigin(ORIGIN);
    resolve({ status: 403, body: {} }); await reading; expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(true);
    api.detailPromise = null; await component.inspect(21); expect(component.evidence()).not.toBeNull();
    await harness.navigateByUrl('/competitor-roots/7/10', CompetitorRoots); await harness.fixture.whenStable(); expect(component.evidence()).toBeNull();
    harness.fixture.destroy(); expect(component.ready()).toBe(false); expect(component.jobs()).toEqual([]);
  });
  it.each(['synthetic_demo', 'malformed_origin', 'future_date', 'unverified_history'])('withholds configuration or authority %s before enabling native work', async state => {
    if (state === 'synthetic_demo') api.source = state; if (state === 'malformed_origin') api.origins = [ORIGIN + '/'];
    if (state === 'future_date') api.updated = '2099-01-01T00:00:00+00:00'; if (state === 'unverified_history') api.deny = true;
    const { component } = await screen(); expect(component.ready()).toBe(false); expect(api.commands).toHaveLength(0); expect(component.origins()).toEqual([]);
  });
  it('withholds expanded, duplicate, foreign-state and malformed private job metadata', async () => {
    const { component } = await screen();
    for (const change of [ { id: 0 }, { status: ['queued'] }, { status: 'waiting_provider' }, { estimate_units: true },
      { cancel_requested: 1 }, { error_category: 'raw provider error' }, { created_at: LATER, updated_at: DATE }, { raw: 'not selected' } ]) {
      api.rows = [{ ...job(), ...change } as any]; await component.load(); expect(component.ready()).toBe(false); expect(component.jobs()).toEqual([]);
    }
    api.rows = [job(), job()]; await component.load(); expect(component.ready()).toBe(false);
  });
  it.each(['en', 'tr'] as const)('deliberately freezes two saved succeeded jobs for GET-only literal original comparisons with safe native controls in %s', async (language) => {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    savedPair(); api.actor = 2; const { component, harness } = await screen(); harness.detectChanges();
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.pairs).toEqual([]);
    expect(harness.routeNativeElement!.querySelector('label[for=competitor-previous]')).not.toBeNull();
    expect(harness.routeNativeElement!.querySelector('label[for=competitor-current]')).not.toBeNull();
    await component.compare(); component.editPair('previous', '999'); component.editPair('current', '022'); await component.compare(); expect(api.pairs).toEqual([]);
    component.editPair('previous', '21'); component.editPair('current', '21'); await component.compare(); expect(api.pairs).toEqual([]);
    selectPair(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(api.pairs).toEqual([[21, 22]]); expect(component.frozenPair()).toEqual({ previous: api.rows[1], current: api.rows[0] });
    expect(component.comparison()).toEqual(comparison()); expect(harness.routeNativeElement!.querySelector('img, script')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('Changed <img src=x onerror=alert(1)>');
    expect(api.commands).toEqual([]); expect(api.previews).toBe(0); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    const retained = component.comparison(), pair = component.frozenPair();
    const earlier = harness.routeNativeElement!.querySelector<HTMLSelectElement>('#competitor-previous')!;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.comparison()).toBe(retained); expect(component.frozenPair()).toBe(pair);
    expect(harness.routeNativeElement!.querySelector('#competitor-previous')).toBe(earlier); expect(earlier.value).toBe('21');
    expect(earlier.querySelector('option[value="21"]')!.getAttribute('lang')).toBe('en'); expect(api.pairs).toHaveLength(1);
    component.productLanguage.set(language); harness.detectChanges();
    component.editPair('current', '21'); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
  });
  it('preserves observed-empty comparability and unavailable/truncated null differences without reconstructing original actor SHA', async () => {
    savedPair(); const { component } = await screen();
    for (const state of ['empty', 'unavailable', 'title_truncated', 'description_truncated']) {
      api.pairValue = comparison(); const value = api.pairValue; const before = value['previous'].evidence; const after = value['current'].evidence;
      if (state === 'empty') {
        for (const item of [before, after]) { item.metadata.title = ''; item.metadata.description = ''; }
        value['metadata_changed'] = { title: false, description: false };
      } else {
        if (state === 'unavailable') {
          before.state = 'unavailable'; before.reason = 'ambiguous_markup'; before.metadata = null;
          before.counts = Object.fromEntries(Object.keys(before.counts).map(key => [key, null]));
        } else after.metadata[state] = true;
        value['comparable'] = false; value['state'] = 'incomparable_unavailable_or_truncated_metadata'; value['metadata_changed'] = null; value['count_deltas'] = null;
      }
      selectPair(component); await component.compare(); expect(component.comparison()).toEqual(value);
    }
  });
  it('withholds expanded/wrong-scope/date/root/source/bounds and fabricated differences in original pair DTOs', async () => {
    savedPair(); const { component } = await screen();
    const changes: ((v: any) => void)[] = [v => { v.raw = 'unselected'; }, v => { v.project_id = 10; }, v => { v.organization_id = 8; },
      v => { v.source_current = 1; }, v => { v.method_version = 'whole-site'; }, v => { v.collection_method = 'own-crawl'; }, v => { v.parser_method = 'other'; },
      v => { v.source_sha256 = 'C'.repeat(64); }, v => { v.url = OWN + '/'; }, v => { v.previous.job_id = 22; }, v => { v.current.job_id = 21; },
      v => { v.previous.extra = 'raw'; }, v => { v.current.robots = 'unknown'; }, v => { v.current.evidence.observed_at = OBSERVED; },
      v => { v.current.evidence.observed_at = DATE; }, v => { v.current.evidence.observed_at = '2026-01-01T00:00:00.000004+00:00'; },
      v => { v.previous.evidence.observed_at = '2026-02-30T00:00:00.000001+00:00'; }, v => { v.current.evidence.url = ORIGIN + '/other'; },
      v => { v.current.evidence.coverage = 'whole_site'; }, v => { v.current.evidence.body_size_bytes = 131073; }, v => { v.current.evidence.counts.h1 = null; },
      v => { v.current.evidence.metadata.title = 'x'.repeat(501); }, v => { v.current.evidence.metadata.title_truncated = 1; },
      v => { v.current.evidence.excluded_containers = []; }, v => { v.body_changed = false; }, v => { v.body_changed = 1; },
      v => { v.metadata_changed.title = false; }, v => { v.metadata_changed.extra = false; }, v => { v.count_deltas.h1 = 1; }, v => { v.count_deltas.h2 = true; },
      v => { v.comparable = false; }, v => { v.state = 'changed_topics'; }, v => { v.interpretation = 'rank_gain'; },
      v => { v.current.evidence.metadata.title_truncated = true; }, v => { v.metadata_changed = null; }, v => { v.count_deltas = null; }];
    for (const change of changes) {
      await component.load(); api.pairValue = comparison(); change(api.pairValue); selectPair(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.previousJobId()).toBe(0);
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'denial'])('clears pair after late %s loss', async field => {
    savedPair(); const { component } = await screen(); selectPair(component);
    api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'denial') api.pairStatus = 403;
    };
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.commands).toEqual([]);
  });
  it('rechecks the frozen original job metadata before delivery and never compares queued or cancelled selections', async () => {
    savedPair(); const { component } = await screen(); selectPair(component); api.rows[1].updated_at = OBSERVED;
    await component.compare(); expect(api.pairs).toEqual([]); expect(component.frozenPair()).toBeNull();
    savedPair(); api.rows[1].status = 'queued'; await component.load(); selectPair(component); await component.compare(); expect(api.pairs).toEqual([]);
    savedPair(); api.rows[1].cancel_requested = true; await component.load(); selectPair(component); await component.compare(); expect(api.pairs).toEqual([]);
  });
  it('clears pair delivery on source declarations, origin, job inspection, refresh, route and destruction; ignores stale denial', async () => {
    savedPair(); const { component, harness } = await screen();
    for (const edit of [() => component.editPermission('use', true), () => component.editOrigin(ORIGIN), () => component.editPair('previous', '22')]) {
      selectPair(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    selectPair(component); await component.compare(); await component.inspect(21); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    selectPair(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull();
    let resolve!: (result: ApiResult) => void; api.pairPromise = new Promise(r => { resolve = r; }); selectPair(component);
    const reading = component.compare(); await vi.waitFor(() => expect(api.pairs).toHaveLength(6)); component.editOrigin(ORIGIN);
    resolve({ status: 403, body: {} }); await reading; expect(component.ready()).toBe(true); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    api.pairPromise = null; selectPair(component); await component.compare();
    await harness.navigateByUrl('/competitor-roots/7/10', CompetitorRoots); await harness.fixture.whenStable(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    harness.fixture.destroy(); expect(component.ready()).toBe(false); expect(component.jobs()).toEqual([]); expect(component.previousJobId()).toBe(0);
  });
  async function prepareAI(component: CompetitorRoots) {
    savedPair(); await component.load(); await component.loadSyntheses(); selectPair(component);
    component.editSynthesis('permission', true); component.editSynthesis('model', '31'); component.editSynthesis('account', '41');
    component.editSynthesis('cost', '1.000001');
  }
  it.each(['en', 'tr'] as const)('deliberately selects an original pair and separate initially unchecked AI permission/model/account/budget with a fully digest-bound frozen command in %s', async (language) => {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    savedPair(); const { component, harness } = await screen(); expect(api.catalogCalls).toBe(0); expect(api.synthPreviews).toBe(0);
    await component.loadSyntheses(); harness.detectChanges();
    const permission = harness.routeNativeElement!.querySelector<HTMLInputElement>('input[name=ai_processing]')!;
    expect(permission.checked).toBe(false); expect(permission.required).toBe(true); expect(permission.closest('label')).not.toBeNull();
    for (const id of ['competitor-model', 'competitor-account', 'competitor-tokens', 'competitor-cost']) expect(harness.routeNativeElement!.querySelector(`label[for=${id}]`)).not.toBeNull();
    await prepareAI(component); await component.previewSynthesis(); const frozen = structuredClone(component.synthesisSelection())!;
    expect(frozen.selection.input).toEqual(aiInput()); expect(frozen.selection_digest).toBe(await sha(frozen.selection)); expect(frozen.comparison).toEqual(comparison());
    harness.detectChanges(); const cost = harness.routeNativeElement!.querySelector<HTMLInputElement>('#competitor-cost')!;
    expect(cost.value).toBe('1.000001'); expect(permission.checked).toBe(true);
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('#competitor-cost')).toBe(cost); expect(cost.value).toBe('1.000001');
    expect(permission.checked).toBe(true); expect(component.synthesisSelection()).toEqual(frozen); expect(api.synthCommands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.launchSynthesis();
    expect(api.synthCommands).toEqual([{ ...aiInput(), selection_digest: frozen.selection_digest, idempotency_key: expect.any(String) }]);
    expect(api.synthPreviews).toBe(3); expect(component.pending()).toBeNull(); expect(component.synthesisSelected()?.id).toBe(61); expect(component.selected()).toBeNull();
    expect(api.commands).toEqual([]); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('rejects missing AI declaration, malformed budget, mismatched account and catalog-only eligibility before generation', async () => {
    const { component } = await screen();
    for (const [kind, value] of [['permission', false], ['tokens', '127'], ['tokens', '2049'], ['tokens', '128.5'], ['cost', '0'], ['cost', '100.000001'], ['cost', '1e1'], ['account', '999']] as const) {
      await prepareAI(component); component.editSynthesis(kind, value); await component.previewSynthesis(); expect(component.synthesisSelection()).toBeNull();
    }
    await prepareAI(component); api.synthDeny = true; await component.previewSynthesis(); expect(component.synthesisSelection()).toBeNull(); expect(api.synthCommands).toEqual([]);
  });
  it('requires explicit free policy consent and matching model limits; model edits reset account and free consent', async () => {
    const { component, harness } = await screen(); api.modelRows[0] = { ...model(), access_tier: 'free', privacy_policy_url: 'https://provider.example.invalid/privacy' };
    await prepareAI(component); harness.detectChanges(); const free = harness.routeNativeElement!.querySelector<HTMLInputElement>('input[name=free_processing]')!;
    expect(free.checked).toBe(false); expect(free.required).toBe(true);
    await component.previewSynthesis(); expect(component.synthesisSelection()).toBeNull(); component.editSynthesis('free', true);
    await component.previewSynthesis(); expect(component.synthesisSelection()?.selection.input['allow_free']).toBe(true);
    component.editSynthesis('model', '31'); expect(component.accountId()).toBe(0); expect(component.allowFree()).toBe(false); expect(component.synthesisSelection()).toBeNull();
    api.modelRows[0]['max_output_tokens'] = 256; await prepareAI(component); component.editSynthesis('free', true); await component.previewSynthesis(); expect(component.synthesisSelection()).toBeNull();
    api.modelRows[0]['privacy_policy_url'] = ''; await prepareAI(component); component.editSynthesis('free', true); await component.previewSynthesis(); expect(component.synthesisSelection()).toBeNull();
  });
  it('rejects expanded or mismatched preview input/config/source digest, free/routing policy and budget despite a recomputed outer SHA', async () => {
    const { component } = await screen();
    const changes: ((v: Row) => void)[] = [v => { v['raw'] = 'extra'; }, v => { v['selection'].input.max_cost_usd = '2'; },
      v => { v['selection'].input.ai_processing_permission = 1; }, v => { v['selection'].configuration.actor_id = 2; },
      v => { v['selection'].configuration.project_id = 10; }, v => { v['selection'].configuration.account_id = 42; },
      v => { v['selection'].configuration.source_selection_digest = 'e'.repeat(64); }, v => { v['selection'].configuration.raw_prompt = 'extra'; },
      v => { v['selection'].configuration.model_access_tier = 'free'; }, v => { v['selection'].configuration.model_identifier = 'other'; },
      v => { v['selection'].configuration.model_revision = '2099-01-01T00:00:00+00:00'; }, v => { v['selection'].configuration.timeout_seconds = 31; },
      v => { v['selection'].configuration.fallback_index = 1; }, v => { v['selection'].configuration.estimated_max_cost_usd = '2.000000'; },
      v => { v['selection'].configuration.provider_base_url = 'https://evil.example.invalid'; }, v => { v['estimate_units'] = true; }];
    for (const change of changes) { await prepareAI(component); api.synthPreviewChange = change; await component.previewSynthesis(); expect(component.synthesisSelection()).toBeNull(); }
    expect(api.synthCommands).toEqual([]);
  });
  it('freezes exact all-input SHA even for two USD ceilings producing the same configuration and rechecks hidden model metadata before POST', async () => {
    const { component } = await screen(); await prepareAI(component); await component.previewSynthesis(); const first = structuredClone(component.synthesisSelection())!;
    component.editSynthesis('cost', '2.000001'); await component.previewSynthesis(); const second = component.synthesisSelection()!;
    expect(second.selection.configuration).toEqual(first.selection.configuration); expect(second.selection_digest).not.toBe(first.selection_digest);
    api.synthPreviewChange = v => { v['selection'].configuration.model_selection_sha256 = 'e'.repeat(64); };
    await component.launchSynthesis(); expect(api.synthCommands).toEqual([]); expect(component.pending()).toBeNull(); expect(component.synthesisSelection()).toBeNull();
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'model', 'account'])('withholds synthesis on late preview %s loss', async field => {
    const { component } = await screen(); await prepareAI(component);
    api.afterSynthesisPreview = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'synthetic_demo'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'model') api.modelRows = []; if (field === 'account') api.accountRows = [];
    };
    await component.previewSynthesis(); expect(component.synthesisSelection()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(api.synthCommands).toEqual([]);
  });
  it('clears an acknowledged command and private memory after late source or hidden model loss', async () => {
    const { component } = await screen(); await prepareAI(component); await component.previewSynthesis();
    api.afterSynthesisPost = () => { api.synthDeny = true; }; await component.launchSynthesis();
    expect(api.synthCommands).toHaveLength(1); expect(component.pending()).toBeNull(); expect(component.ready()).toBe(false); expect(component.selected()).toBeNull();
  });
  it('keeps uncertain commands in memory and reconciles only original-actor same-key GET without provider eligibility or POST replay', async () => {
    const { component } = await screen(); await prepareAI(component); await component.previewSynthesis(); api.synthUnknown = true;
    await component.launchSynthesis(); const frozen = structuredClone(component.pending())!;
    expect(frozen.synthesis).toBe(true); expect(frozen.data).toMatchObject(aiInput()); expect(frozen.pair?.previous.id).toBe(21);
    api.modelRows = []; api.accountRows = []; await component.launchSynthesis(); await component.loadSyntheses(); await component.launch();
    await component.reconcile(); expect(api.synthLookups).toEqual([frozen.key]); expect(api.synthCommands).toHaveLength(1); expect(component.pending()).toBeNull(); expect(component.synthesisEvidence()).toBeNull();
  });
  it('does not treat another/absent own-key lookup as acknowledgment and discards no server work', async () => {
    const { component } = await screen(); await prepareAI(component); await component.previewSynthesis(); api.synthDrop = true;
    await component.launchSynthesis(); const key = component.pending()!.key; await component.reconcile(); await component.reconcile();
    expect(component.pending()!.key).toBe(key); expect(api.synthCommands).toHaveLength(1); expect(component.message()).toContain('No saved own-actor');
    component.discard(); expect(component.pending()).toBeNull(); expect(component.synthesisSelection()).toBeNull();
  });
  it('cancels after source/model loss and reconciles unknown cancellation only by exact-job GET', async () => {
    const { component } = await screen(); api.synthRows = [synthesisJob()]; await component.loadSyntheses(); api.modelRows = []; api.accountRows = [];
    const previews = api.synthPreviews; api.synthUnknown = true; await component.cancelSynthesis(999); await component.cancelSynthesis(61);
    expect(component.pending()?.jobId).toBe(61); expect(component.pending()?.synthesis).toBe(true); await component.reconcile();
    expect(api.synthCancels).toEqual([61]); expect(api.synthDetails).toEqual([61]); expect(api.synthPreviews).toBe(previews); expect(component.pending()).toBeNull();
  });
  it('displays exact original facts separately from unverified cited AI notes and nullable metering safely for an independent reader', async () => {
    const { component, harness } = await screen(); await prepareAI(component); api.actor = 2; await component.load(); api.synthDetailValue = await aiDetail();
    api.synthRows = [api.synthDetailValue['job']]; await component.loadSyntheses(); await component.inspectSynthesis(61); harness.detectChanges();
    expect(component.synthesisDetail()?.['usage']).toEqual(api.synthDetailValue['usage']); expect(component.synthesisEvidence()?.['comparison']).toEqual(comparison());
    expect(api.synthDetails).toEqual([61, 61]); expect(api.synthPreviews).toBe(2); expect(api.synthCommands).toEqual([]);
    expect(harness.routeNativeElement!.querySelector('img,script')).toBeNull(); expect(harness.routeNativeElement!.textContent).toContain('Unverified cited AI');
    expect(harness.routeNativeElement!.textContent).toContain('not proof of actual provider behavior'); expect(component.synthesisEvidence()?.['generated_at']).toBe(GENERATED);
  });
  it('preserves unavailable/truncated null facts and allows only available original references without invented zero quotes', async () => {
    const { component } = await screen(); await prepareAI(component);
    api.pairValue = comparison(); api.pairValue['current'].evidence.metadata.title_truncated = true;
    api.pairValue['comparable'] = false; api.pairValue['state'] = 'incomparable_unavailable_or_truncated_metadata'; api.pairValue['metadata_changed'] = null; api.pairValue['count_deltas'] = null;
    api.synthDetailValue = await aiDetail(); const selection = await aiSelection(aiInput(), api.pairValue);
    api.synthDetailValue['selection'] = selection; api.synthDetailValue['selection_digest'] = await sha(selection);
    const s = api.synthDetailValue['evidence'].synthesis; s.comparison = api.pairValue; s.source_selection_digest = selection['configuration'].source_selection_digest;
    s.interpretations = [{ text: 'Incomparable original metadata requires review.', reference: 'comparison_state', quote: api.pairValue['state'] }];
    api.synthRows = [api.synthDetailValue['job']]; await component.loadSyntheses(); await component.inspectSynthesis(61);
    expect(component.synthesisEvidence()?.['comparison']).toEqual(api.pairValue);
    s.interpretations = [{ text: 'Invented title proof', reference: 'current_title', quote: 'Changed' }]; await component.inspectSynthesis(61); expect(component.synthesisEvidence()).toBeNull();
  });
  it('withholds expanded synthesis/usage, incorrect original source/model/date/status and forged or oversized note citations', async () => {
    const { component } = await screen();
    const changes: ((v: Row) => void)[] = [v => { v['raw'] = 'extra'; }, v => { v['job'].id = 62; }, v => { v['selection_digest'] = 'E'.repeat(64); },
      v => { v['usage'].provider_request_id = 'private'; }, v => { v['usage'].input_tokens = true; }, v => { v['usage'].duration_ms = 120001; },
      v => { v['usage'].reported_cost_usd = '-1.000000'; }, v => { v['usage'].status = 'unknown'; }, v => { v['usage'].finished_at = null; },
      v => { v['evidence'].source_current = 1; }, v => { v['evidence'].synthesis.model_id = 32; }, v => { v['evidence'].synthesis.account_id = 42; },
      v => { v['evidence'].synthesis.raw_answer = 'extra'; }, v => { v['evidence'].synthesis.generated_at = LATER; },
      v => { v['evidence'].synthesis.generated_at = '2026-01-01T00:00:00.000008+00:00'; }, v => { v['evidence'].synthesis.state = 'approved'; },
      v => { v['evidence'].synthesis.comparison.count_deltas.h1 = 0; }, v => { v['evidence'].synthesis.interpretations = []; },
      v => { v['evidence'].synthesis.interpretations[0].reference = 'traffic'; }, v => { v['evidence'].synthesis.interpretations[0].quote = 'not original'; },
      v => { v['evidence'].synthesis.interpretations[1].quote = 'True'; }, v => { v['evidence'].synthesis.interpretations[0].text = 'x'.repeat(501); },
      v => { v['evidence'].synthesis.interpretations[0].text = 'invisible\u200bcontrol'; }, v => { v['evidence'].synthesis.interpretations[0].approved = true; },
      v => { v['evidence'].synthesis.interpretations = Array.from({ length: 10 }, () => ({ text: '😀'.repeat(500), reference: 'body_changed', quote: 'true' })); }];
    for (const change of changes) {
      api.synthDetailValue = await aiDetail(); change(api.synthDetailValue); api.synthRows = [synthesisJob()]; await prepareAI(component); await component.inspectSynthesis(61);
      expect(component.synthesisEvidence()).toBeNull(); expect(component.synthesisDetail()).toBeNull();
    }
  });
  it.each(['source', 'model', 'scope', 'row'])('withholds successful detail after final %s loss or drift', async field => {
    const { component } = await screen(); await prepareAI(component); api.synthDetailValue = await aiDetail(); api.synthRows = [api.synthDetailValue['job']];
    await component.loadSyntheses(); api.afterSynthesisPreview = () => {
      if (api.synthPreviews !== 2) return;
      if (field === 'source') api.rows[1].cancel_requested = true;
      if (field === 'model') api.modelRows = [];
      if (field === 'scope') ++api.actor;
      if (field === 'row') api.synthDetailValue!['usage'].reported_cost_usd = '0.000000';
    };
    await component.inspectSynthesis(61); expect(component.synthesisEvidence()).toBeNull(); expect(component.synthesisDetail()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('preserves genuine zero provider observations separately from unknown nullable values without promoting them to approval', async () => {
    const { component } = await screen(); await prepareAI(component); api.synthDetailValue = await aiDetail();
    Object.assign(api.synthDetailValue['usage'], { input_tokens: 0, output_tokens: 0, duration_ms: 0, estimated_cost_usd: '0.000000', reported_cost_usd: '0.000000' });
    api.synthRows = [api.synthDetailValue['job']]; await component.loadSyntheses(); await component.inspectSynthesis(61);
    expect(component.synthesisDetail()?.['usage']).toEqual(api.synthDetailValue['usage']); expect(component.synthesisEvidence()?.['state']).toBe('unverified_ai_interpretations_require_human_review');
  });
  it('ignores late synthesis detail/command denial on edit, route and destruction and clears all synthesis memory through shared lifecycle operations', async () => {
    const { component, harness } = await screen(); await prepareAI(component); api.synthRows = [synthesisJob()]; await component.loadSyntheses();
    let resolve!: (value: ApiResult) => void; api.synthDetailPromise = new Promise(r => { resolve = r; });
    const reading = component.inspectSynthesis(61); await vi.waitFor(() => expect(api.synthDetails).toEqual([61])); component.editSynthesis('cost', '2');
    resolve({ status: 403, body: {} }); await reading; expect(component.ready()).toBe(true); expect(component.synthesisDetail()).toBeNull();
    api.synthDetailPromise = null;
    for (const edit of [() => component.editPair('current', '21'), () => component.editPermission('storage', false), () => component.editOrigin(ORIGIN), () => component.editSynthesis('tokens', '128')]) {
      await prepareAI(component); await component.previewSynthesis(); expect(component.synthesisSelection()).not.toBeNull(); edit();
      expect(component.synthesisSelection()).toBeNull(); expect(component.synthesisEvidence()).toBeNull(); expect(component.pending()).toBeNull();
    }
    await prepareAI(component); await component.previewSynthesis(); api.synthUnknown = true; await component.launchSynthesis(); expect(component.pending()).not.toBeNull();
    await harness.navigateByUrl('/competitor-roots/7/10', CompetitorRoots); await harness.fixture.whenStable(); expect(component.pending()).toBeNull(); expect(component.models()).toEqual([]);
    harness.fixture.destroy(); expect(component.synthesisJobs()).toEqual([]); expect(component.aiPermission()).toBe(false);
  });
});

it('AccountApi uses fixed scoped competitor endpoints, bodyless GET lookup, CSRF-protected JSON commands and no-store same-origin requests', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorRoots(7, 9); await api.competitorRoots(7, 9, undefined, undefined, 'same.key'); await api.competitorRoots(7, 9, undefined, 21);
  await api.competitorRoots(7, 9, { origin: ORIGIN }, undefined, undefined, true); await api.competitorRoots(7, 9, { idempotency_key: 'same.key' }); await api.competitorRoots(7, 9, {}, 21);
  const calls = fetcher.mock.calls as unknown as [string, RequestInit][]; const commands = calls.filter(([url]) => url.includes('/competitor-roots/'));
  expect(commands.map(([url]) => url.split('/competitor-roots/')[1])).toEqual(['', '?idempotency_key=same.key', '21/', 'selection/', '', '21/']);
  expect(commands.slice(0, 3).every(([, options]) => options.method === 'GET' && options.body === undefined)).toBe(true);
  expect(commands.slice(3).every(([, options]) => options.method === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(commands.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
  expect(commands[5][1].body).toBe('{}');
});

it('AccountApi comparison is the fixed scoped bodyless GET with exact pair IDs and private fetch options', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: '' } }] });
  await TestBed.inject(AccountApi).competitorRootComparison(7, 9, 21, 22);
  const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('/api/organizations/7/projects/9/competitor-roots/comparison/?previous_job_id=21&current_job_id=22');
  expect(options.method).toBe('GET'); expect(options.body).toBeUndefined(); expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store');
});

it('AccountApi synthesis uses fixed scoped private GET/history-own-key/detail and CSRF JSON preview/queue/empty cancellation', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorSyntheses(7, 9); await api.competitorSyntheses(7, 9, undefined, undefined, 'same.key'); await api.competitorSyntheses(7, 9, undefined, 61);
  await api.competitorSyntheses(7, 9, aiInput(), undefined, undefined, true); await api.competitorSyntheses(7, 9, { ...aiInput(), idempotency_key: 'same.key' }); await api.competitorSyntheses(7, 9, {}, 61);
  const calls = fetcher.mock.calls as unknown as [string, RequestInit][]; const commands = calls.filter(([url]) => url.includes('/competitor-syntheses/'));
  expect(commands.map(([url]) => url.split('/competitor-syntheses/')[1])).toEqual(['', '?idempotency_key=same.key', '61/', 'selection/', '', '61/']);
  expect(commands.slice(0, 3).every(([, options]) => options.method === 'GET' && options.body === undefined)).toBe(true);
  expect(commands.slice(3).every(([, options]) => options.method === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(commands.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.cache === 'no-store' && options.credentials === 'same-origin')).toBe(true);
  expect(commands[5][1].body).toBe('{}');
});

describe('Private separate competitor schema-label workflow', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-schema-roots/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots) {
    component.editOrigin(ORIGIN); component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  function savedPair() { api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }]; api.pairValue = schemaComparison(); }
  function selectPair(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('reads only the deliberate frozen schema pair with labelled controls and opaque original SHA, without model, storage or collection calls', async () => {
    savedPair(); api.actor = 2; api.role = 'admin'; const { component, harness } = await screen(); harness.detectChanges();
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.schemaPairs).toEqual([]);
    for (const id of ['competitor-previous', 'competitor-current']) expect(harness.routeNativeElement!.querySelector(`label[for=${id}]`)).not.toBeNull();
    await component.compare(); component.editPair('previous', '999'); component.editPair('current', '022'); await component.compare(); expect(api.schemaPairs).toEqual([]);
    selectPair(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(api.schemaPairs).toEqual([[21, 22]]); expect(api.pairs).toEqual([]); expect(api.pagePairs).toEqual([]); expect(component.comparison()).toEqual(schemaComparison());
    expect(harness.routeNativeElement!.textContent).toContain('not resolved schema validity'); expect(harness.routeNativeElement!.textContent).toContain('VideoObject');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(api.catalogCalls).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.synthDetails).toEqual([]); expect(api.synthCancels).toEqual([]);
    expect(api.commands).toEqual([]); expect(api.previews).toBe(0); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('preserves observed empty schema labels and zero counts separately from unavailable null changes', async () => {
    savedPair(); const { component } = await screen();
    for (const state of ['empty', 'unavailable']) {
      api.pairValue = schemaComparison(); const value = api.pairValue;
      if (state === 'empty') {
        for (const item of [value['previous'].evidence, value['current'].evidence]) item.summary = { json_ld_blocks: 0, typed_nodes: 0, types: [], unrecognized_type_count: 0 };
        value['type_changes'] = { added: [], removed: [] }; value['count_deltas'] = { json_ld_blocks: 0, typed_nodes: 0, unrecognized_type_count: 0 };
      } else {
        value['previous'].evidence.state = 'unavailable'; value['previous'].evidence.reason = 'invalid_json'; value['previous'].evidence.summary = null;
        value['comparable'] = false; value['state'] = 'incomparable_unavailable_schema_labels'; value['type_changes'] = null; value['count_deltas'] = null;
      }
      selectPair(component); await component.compare(); expect(component.comparison()).toEqual(value);
    }
  });
  it('rejects old-family/method/URI/date/body/source or fabricated schema labels, deltas and null shapes', async () => {
    savedPair(); const { component } = await screen();
    const changes: ((value: Row) => void)[] = [v => v['method_version'] = comparison()['method_version'], v => v['collection_method'] = 'competitor-static-root-collect-v1',
      v => v['interpretation'] = comparison()['interpretation'], v => v['parser_method'] = 'competitor-static-metadata-v1', v => v['metadata_changed'] = {},
      v => v['project_id'] = 10, v => v['source_current'] = 1, v => v['url'] = ORIGIN + '/other', v => v['url'] = OWN + '/',
      v => v['current'].evidence.url = ORIGIN + '/other', v => v['current'].evidence.observed_at = OBSERVED, v => v['source_sha256'] = 'bad',
      v => v['current'].evidence.body_sha256 = null, v => v['current'].evidence.body_size_bytes = 131073, v => v['count_deltas'].typed_nodes = 1,
      v => v['type_changes'].added = ['Article'], v => v['type_changes'].removed = [], v => v['type_changes'].added.reverse(),
      v => v['current'].evidence.summary.types = ['<img src=x onerror=alert(1)>'], v => v['current'].evidence.summary.types = ['WebPage', 'WebPage'],
      v => v['body_changed'] = false, v => v['body_changed'] = null, v => v['previous'].job_id = 22, v => v['count_deltas'] = null, v => v['type_changes'] = null];
    for (const change of changes) {
      await component.load(); api.pairValue = schemaComparison(); change(api.pairValue); selectPair(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.previousJobId()).toBe(0);
    }
    expect(api.pairs).toEqual([]); expect(api.pagePairs).toEqual([]); expect(api.synthCommands).toEqual([]);
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'denial'])('clears the private schema pair after late %s loss', async field => {
    savedPair(); const { component } = await screen(); selectPair(component);
    api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'denial') api.pairStatus = 403;
    };
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.commands).toEqual([]); expect(api.pairs).toEqual([]);
  });
  it('rechecks frozen schema job status before GET and clears delivery on origin, rights, pair, refresh, route and destruction', async () => {
    savedPair(); const { component, harness } = await screen(); selectPair(component); api.rows[1].updated_at = OBSERVED;
    await component.compare(); expect(api.schemaPairs).toEqual([]); expect(component.frozenPair()).toBeNull();
    savedPair(); await component.load();
    for (const edit of [() => component.editOrigin(ORIGIN), () => component.editPermission('use', false), () => component.editPair('current', '21')]) {
      selectPair(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    selectPair(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull();
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    selectPair(component); const count = api.schemaPairs.length; const reading = component.compare(); await vi.waitFor(() => expect(api.schemaPairs.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-schema-roots/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 403, body: {} }); await reading; expect(component.comparison()).toBeNull(); expect(component.error()).toBe('');
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.frozenPair()).toBeNull();
  });
  it('has unchecked schema rights, fixed digest/queue, deliberate pair controls and no automatic comparison/model calls', async () => {
    const { harness, component } = await screen(); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toContain('schema type labels');
    const boxes = [...harness.routeNativeElement!.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(boxes).toHaveLength(3); expect(boxes.every(box => !box.checked && box.required && !!box.closest('label'))).toBe(true);
    expect(harness.routeNativeElement!.querySelector('#competitor-model')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('#competitor-previous')).not.toBeNull();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.compare();
    expect(api.catalogCalls).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.pairs).toEqual([]); expect(api.schemaPairs).toEqual([]);
    declare(component); await component.preview();
    const preview = structuredClone(component.selection()!);
    expect(preview.selection['method']).toBe('competitor-static-schema-root-collect-v1');
    expect(preview.selection_digest).toBe(await sha(preview.selection));
    await component.launch(); expect(api.commands).toHaveLength(1);
    expect(api.commands[0]['selection_digest']).toBe(preview.selection_digest);
    expect(api.commands[0]['collection_permission']).toBe(true);
    expect(api.commands[0]['use_permission']).toBe(true); expect(api.commands[0]['storage_permission']).toBe(true);
    expect(api.familyCalls.every(family => family === 'schema')).toBe(true);
  });
  it('accepts original opaque actor provenance, original microseconds, lexical labels, observed empty and unavailable null separately', async () => {
    api.actor = 2; api.role = 'admin'; api.rows = [{ ...job(), status: 'succeeded' }];
    const { harness, component } = await screen();
    await component.inspect(21); expect(component.evidence()).toEqual(schemaEvidence());
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('schema validity');
    expect(harness.routeNativeElement!.textContent).toContain('unrecognized declarations are counted without their text');
    for (const unavailable of [false, true]) {
      api.detailValue = schemaEvidence(); const value = api.detailValue['collection']['evidence'];
      value.summary = unavailable ? null : { json_ld_blocks: 0, typed_nodes: 0, types: [], unrecognized_type_count: 0 };
      value.state = unavailable ? 'unavailable' : 'observed'; value.reason = unavailable ? 'invalid_json' : '';
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
      expect(component.evidence()!['collection']).toHaveProperty('observed_at', OBSERVED);
    }
    expect(api.familyCalls.every(family => family === 'schema')).toBe(true);
  });
  it('rejects metadata-shaped or altered schema evidence, arbitrary/injected identifiers and inconsistent bounded summaries', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    const mutations: ((row: Row) => void)[] = [
      row => row['collection'].method_version = 'competitor-static-root-collect-v1',
      row => row['collection'].evidence = evidence()['collection']['evidence'],
      row => row['collection'].evidence.raw_schema = 'private',
      row => row['collection'].evidence.summary.types = ['<img src=x onerror=alert(1)>'],
      row => row['collection'].evidence.summary.types = ['Article', 'Article'],
      row => row['collection'].evidence.summary.types = ['Organization', 'Article'],
      row => row['collection'].evidence.summary.json_ld_blocks = 21,
      row => row['collection'].evidence.summary.typed_nodes = true,
      row => row['collection'].evidence.summary.typed_nodes = 501,
      row => row['collection'].evidence.summary.unrecognized_type_count = 10001,
      row => row['collection'].evidence.summary.typed_nodes = 0,
      row => row['collection'].evidence.summary.json_ld_blocks = 0,
      row => row['collection'].evidence.summary = null,
      row => { row['collection'].evidence.state = 'unavailable'; row['collection'].evidence.reason = 'invalid_json'; },
      row => row['collection'].evidence.body_sha256 = 'bad',
      row => row['collection'].evidence.body_size_bytes = 131073,
      row => row['collection'].evidence.observed_at = LATER,
      row => row['collection'].evidence.excluded_containers = [],
      row => row['collection'].evidence.interpretation = 'schema_valid',
    ];
    for (const mutate of mutations) {
      await component.load(); api.detailValue = schemaEvidence(); mutate(api.detailValue);
      await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull();
      harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it('rejects the old method, wrong digest, changed source and missing independent declarations before any schema POST', async () => {
    const { component } = await screen();
    component.editOrigin(ORIGIN); component.editPermission('collection', true); component.editPermission('use', true);
    await component.preview(); expect(component.selection()).toBeNull(); expect(api.previews).toBe(0);
    declare(component); api.previewChange = row => row['selection'].method = 'competitor-static-root-collect-v1';
    await component.preview(); expect(component.selection()).toBeNull();
    api.previewChange = null; api.badDigest = true; await component.preview(); expect(component.selection()).toBeNull();
    api.badDigest = false; await component.preview(); expect(component.selection()).not.toBeNull();
    api.afterPreview = () => ++api.revision; await component.launch();
    expect(api.commands).toEqual([]); expect(component.selection()).toBeNull(); expect(component.pending()).toBeNull();
  });
  it('freezes uncertain schema commands and reconciles only their exact own-key GET without POST replay', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.uncertain = true;
    await component.launch(); const frozen = structuredClone(component.pending()!);
    expect(frozen.preview).not.toBeNull(); expect(frozen.data['origin']).toBe(ORIGIN);
    expect(frozen.data['selection_digest']).toBe((frozen.preview as Row)['selection_digest']);
    await component.reconcile(); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([frozen.key]);
    expect(component.pending()).toBeNull(); expect(component.selected()!.id).toBe(21);
    await component.load(); declare(component); await component.preview(); api.drop = true; await component.launch();
    const count = api.commands.length; await component.reconcile(); expect(api.commands).toHaveLength(count);
    expect(component.pending()).not.toBeNull(); component.discard(); expect(component.pending()).toBeNull();
  });
  it('uses fixed schema cancellation and clears uncertain state on current actor/configuration loss', async () => {
    api.rows = [job()]; const { component } = await screen();
    await component.cancel(21); expect(api.cancels).toEqual([21]); expect(component.selected()!.cancel_requested).toBe(true);
    await component.load(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    expect(component.pending()).not.toBeNull(); api.actor = 2;
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.evidence()).toBeNull(); expect(component.origins()).toEqual([]);
  });
  it('withholds late schema detail after scope drift, editing, route change and component destruction', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    api.afterDetail = () => api.role = 'admin'; await component.inspect(21);
    expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    api.afterDetail = null; await component.load(); await component.inspect(21); expect(component.evidence()).not.toBeNull();
    component.editPermission('storage', false); expect(component.evidence()).toBeNull();
    let release!: (result: ApiResult) => void; api.detailPromise = new Promise<ApiResult>(resolve => release = resolve);
    const count = api.details.length; const pending = component.inspect(21); await vi.waitFor(() => expect(api.details.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-schema-roots/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: schemaEvidence() } });
    await pending; expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull();
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.storagePermission()).toBe(false);
  });
});

it('AccountApi schema commands use independent fixed scoped paths and private same-origin CSRF/GET options', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorSchemaRoots(7, 9); await api.competitorSchemaRoots(7, 9, undefined, undefined, 'schema.key');
  await api.competitorSchemaRoots(7, 9, undefined, 21); await api.competitorSchemaRoots(7, 9, { origin: ORIGIN }, undefined, undefined, true);
  await api.competitorSchemaRoots(7, 9, { idempotency_key: 'schema.key' }); await api.competitorSchemaRoots(7, 9, {}, 21); await api.competitorSchemaRootComparison(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-schema-roots/'));
  expect(calls.map(([url]) => url.split('/competitor-schema-roots/')[1])).toEqual(['', '?idempotency_key=schema.key', '21/', 'selection/', '', '21/', 'comparison/?previous_job_id=21&current_job_id=22']);
  expect(calls.slice(0, 3).every(([, options]) => options.method === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3, 6).every(([, options]) => options.method === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls[6][1].method).toBe('GET'); expect(calls[6][1].body).toBeUndefined();
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});


describe('Private separate competitor link-category workflow', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-links-roots/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots) {
    component.editOrigin(ORIGIN); component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  function savedPair() { api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }]; api.pairValue = linksComparison(); }
  function selectPair(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('reads only the deliberate frozen link pair with labelled controls and opaque original SHA, without model, storage or collection calls', async () => {
    savedPair(); api.actor = 2; api.role = 'admin'; const { component, harness } = await screen(); harness.detectChanges();
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.linksPairs).toEqual([]);
    for (const id of ['competitor-previous', 'competitor-current']) expect(harness.routeNativeElement!.querySelector(`label[for=${id}]`)).not.toBeNull();
    await component.compare(); component.editPair('previous', '999'); component.editPair('current', '022'); await component.compare(); expect(api.linksPairs).toEqual([]);
    selectPair(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(api.linksPairs).toEqual([[21, 22]]); expect(api.pairs).toEqual([]); expect(api.pagePairs).toEqual([]); expect(component.comparison()).toEqual(linksComparison());
    expect(harness.routeNativeElement!.textContent).toContain('No destination URLs'); expect(harness.routeNativeElement!.textContent).toContain('reference-category counts');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(api.catalogCalls).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.synthDetails).toEqual([]); expect(api.synthCancels).toEqual([]);
    expect(api.commands).toEqual([]); expect(api.previews).toBe(0); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('preserves observed empty category counts as zero and unavailable changes as null', async () => {
    savedPair(); const { component } = await screen();
    for (const state of ['empty', 'unavailable']) {
      api.pairValue = linksComparison(); const value = api.pairValue;
      if (state === 'empty') {
        for (const item of [value['previous'].evidence, value['current'].evidence]) item.counts = { href_anchors: 0, same_origin_http: 0, other_origin_http: 0, unsupported: 0 };
        value['count_deltas'] = { href_anchors: 0, same_origin_http: 0, other_origin_http: 0, unsupported: 0 };
      } else {
        value['previous'].evidence.state = 'unavailable'; value['previous'].evidence.reason = 'base_dependent_references';
        value['previous'].evidence.counts = { href_anchors: null, same_origin_http: null, other_origin_http: null, unsupported: null };
        value['comparable'] = false; value['state'] = 'incomparable_unavailable_link_categories'; value['count_deltas'] = null;
      }
      selectPair(component); await component.compare(); expect(component.comparison()).toEqual(value);
    }
  });
  it('rejects old-family/method/URI/date/body/source or fabricated category counts, deltas, destinations and null shapes', async () => {
    savedPair(); const { component } = await screen();
    const changes: ((value: Row) => void)[] = [v => v['method_version'] = comparison()['method_version'], v => v['collection_method'] = 'competitor-static-root-collect-v1',
      v => v['interpretation'] = comparison()['interpretation'], v => v['parser_method'] = 'competitor-static-metadata-v1', v => v['metadata_changed'] = {},
      v => v['type_changes'] = {}, v => v['destinations'] = ['/private'], v => v['project_id'] = 10, v => v['source_current'] = 1,
      v => v['url'] = ORIGIN + '/other', v => v['url'] = OWN + '/', v => v['current'].evidence.url = ORIGIN + '/other',
      v => v['current'].evidence.observed_at = OBSERVED, v => v['source_sha256'] = 'bad', v => v['current'].evidence.body_sha256 = null,
      v => v['current'].evidence.body_size_bytes = 131073, v => v['count_deltas'].other_origin_http = 0, v => v['count_deltas'].href_anchors = true,
      v => v['current'].evidence.counts.href_anchors = 999, v => v['current'].evidence.counts.unsupported = true,
      v => v['current'].evidence.counts.other_origin_http = '<img src=x onerror=alert(1)>', v => v['current'].evidence.counts = null,
      v => v['body_changed'] = false, v => v['body_changed'] = null, v => v['previous'].job_id = 22, v => v['count_deltas'] = null];
    for (const change of changes) {
      await component.load(); api.pairValue = linksComparison(); change(api.pairValue); selectPair(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.previousJobId()).toBe(0);
    }
    expect(api.pairs).toEqual([]); expect(api.pagePairs).toEqual([]); expect(api.schemaPairs).toEqual([]); expect(api.synthCommands).toEqual([]);
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'denial'])('clears the private link pair after late %s loss', async field => {
    savedPair(); const { component } = await screen(); selectPair(component);
    api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'denial') api.pairStatus = 403;
    };
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.commands).toEqual([]); expect(api.pairs).toEqual([]);
  });
  it('rechecks frozen link job status before GET and clears delivery on origin, rights, pair, refresh, route and destruction', async () => {
    savedPair(); const { component, harness } = await screen(); selectPair(component); api.rows[1].updated_at = OBSERVED;
    await component.compare(); expect(api.linksPairs).toEqual([]); expect(component.frozenPair()).toBeNull();
    savedPair(); await component.load();
    for (const edit of [() => component.editOrigin(ORIGIN), () => component.editPermission('use', false), () => component.editPair('current', '21')]) {
      selectPair(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    selectPair(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull();
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    selectPair(component); const count = api.linksPairs.length; const reading = component.compare(); await vi.waitFor(() => expect(api.linksPairs.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-links-roots/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 403, body: {} }); await reading; expect(component.comparison()).toBeNull(); expect(component.error()).toBe('');
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.frozenPair()).toBeNull();
  });
  it('has unchecked link rights, fixed digest/queue, deliberate pair controls and no automatic comparison/model calls', async () => {
    const { harness, component } = await screen(); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toContain('root link categories');
    const boxes = [...harness.routeNativeElement!.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(boxes).toHaveLength(3); expect(boxes.every(box => !box.checked && box.required && !!box.closest('label'))).toBe(true);
    expect(harness.routeNativeElement!.querySelector('#competitor-model')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('#competitor-previous')).not.toBeNull();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.compare();
    expect(api.catalogCalls).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.pairs).toEqual([]); expect(api.linksPairs).toEqual([]);
    declare(component); await component.preview();
    const preview = structuredClone(component.selection()!);
    expect(preview.selection['method']).toBe('competitor-static-root-links-collect-v1');
    expect(preview.selection_digest).toBe(await sha(preview.selection));
    await component.launch(); expect(api.commands).toHaveLength(1);
    expect(api.commands[0]['selection_digest']).toBe(preview.selection_digest);
    expect(api.commands[0]['collection_permission']).toBe(true);
    expect(api.commands[0]['use_permission']).toBe(true); expect(api.commands[0]['storage_permission']).toBe(true);
    expect(api.familyCalls.every(family => family === 'links')).toBe(true);
  });
  it('accepts original opaque actor provenance, original microseconds, count categories, observed empty and unavailable null separately', async () => {
    api.actor = 2; api.role = 'admin'; api.rows = [{ ...job(), status: 'succeeded' }];
    const { harness, component } = await screen();
    await component.inspect(21); expect(component.evidence()).toEqual(linksEvidence());
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('link health');
    expect(harness.routeNativeElement!.textContent).toContain('Unsupported references remain in the inspected denominator');
    for (const unavailable of [false, true]) {
      api.detailValue = linksEvidence(); const value = api.detailValue['collection']['evidence'];
      value.counts = { href_anchors: unavailable ? null : 0, same_origin_http: unavailable ? null : 0, other_origin_http: unavailable ? null : 0, unsupported: unavailable ? null : 0 };
      value.state = unavailable ? 'unavailable' : 'observed'; value.reason = unavailable ? 'base_dependent_references' : '';
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
      expect(component.evidence()!['collection']).toHaveProperty('observed_at', OBSERVED);
    }
    expect(api.familyCalls.every(family => family === 'links')).toBe(true);
  });
  it('rejects old-family/altered/injected counts and invalid closed bounds or denominator relationships', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    const mutations: ((row: Row) => void)[] = [
      row => row['collection'].method_version = 'competitor-static-root-collect-v1',
      row => row['collection'].evidence = evidence()['collection']['evidence'],
      row => row['collection'].evidence = schemaEvidence()['collection']['evidence'],
      row => row['collection'].evidence.raw_href = '<img src=x onerror=alert(1)>',
      row => row['collection'].evidence.counts.other_origin_http = '<img src=x onerror=alert(1)>',
      row => row['collection'].evidence.counts.href_anchors = true,
      row => row['collection'].evidence.counts.same_origin_http = -1,
      row => row['collection'].evidence.counts.unsupported = 0.5,
      row => row['collection'].evidence.counts.unsupported = 1001,
      row => row['collection'].evidence.counts.href_anchors = 2,
      row => row['collection'].evidence.counts = null,
      row => row['collection'].evidence.counts.unlisted = 0,
      row => { row['collection'].evidence.state = 'unavailable'; row['collection'].evidence.reason = 'base_dependent_references'; },
      row => row['collection'].evidence.reason = 'private failure',
      row => row['collection'].evidence.body_sha256 = 'bad',
      row => row['collection'].evidence.body_size_bytes = 131073,
      row => row['collection'].evidence.observed_at = LATER,
      row => row['collection'].evidence.excluded_containers = [],
      row => row['collection'].evidence.coverage = 'whole_site',
      row => row['collection'].evidence.interpretation = 'healthy_links',
    ];
    for (const mutate of mutations) {
      await component.load(); api.detailValue = linksEvidence(); mutate(api.detailValue);
      await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull();
      harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it('rejects the old method, wrong digest, changed source and missing independent declarations before any link POST', async () => {
    const { component } = await screen();
    component.editOrigin(ORIGIN); component.editPermission('collection', true); component.editPermission('use', true);
    await component.preview(); expect(component.selection()).toBeNull(); expect(api.previews).toBe(0);
    declare(component); api.previewChange = row => row['selection'].method = 'competitor-static-root-collect-v1';
    await component.preview(); expect(component.selection()).toBeNull();
    api.previewChange = null; api.badDigest = true; await component.preview(); expect(component.selection()).toBeNull();
    api.badDigest = false; await component.preview(); expect(component.selection()).not.toBeNull();
    api.afterPreview = () => ++api.revision; await component.launch();
    expect(api.commands).toEqual([]); expect(component.selection()).toBeNull(); expect(component.pending()).toBeNull();
  });
  it('freezes uncertain link commands and reconciles only their exact own-key GET without POST replay', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.uncertain = true;
    await component.launch(); const frozen = structuredClone(component.pending()!);
    expect(frozen.preview).not.toBeNull(); expect(frozen.data['origin']).toBe(ORIGIN);
    expect(frozen.data['selection_digest']).toBe((frozen.preview as Row)['selection_digest']);
    await component.reconcile(); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([frozen.key]);
    expect(component.pending()).toBeNull(); expect(component.selected()!.id).toBe(21);
    await component.load(); declare(component); await component.preview(); api.drop = true; await component.launch();
    const count = api.commands.length; await component.reconcile(); expect(api.commands).toHaveLength(count);
    expect(component.pending()).not.toBeNull(); component.discard(); expect(component.pending()).toBeNull();
  });
  it('uses fixed link cancellation and clears uncertain state on current actor/configuration loss', async () => {
    api.rows = [job()]; const { component } = await screen();
    await component.cancel(21); expect(api.cancels).toEqual([21]); expect(component.selected()!.cancel_requested).toBe(true);
    await component.load(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    expect(component.pending()).not.toBeNull(); api.actor = 2;
    await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.evidence()).toBeNull(); expect(component.origins()).toEqual([]);
  });
  it('withholds late link detail after scope drift, editing, route change and component destruction', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    api.afterDetail = () => api.role = 'admin'; await component.inspect(21);
    expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    api.afterDetail = null; await component.load(); await component.inspect(21); expect(component.evidence()).not.toBeNull();
    component.editPermission('storage', false); expect(component.evidence()).toBeNull();
    let release!: (result: ApiResult) => void; api.detailPromise = new Promise<ApiResult>(resolve => release = resolve);
    const count = api.details.length; const pending = component.inspect(21); await vi.waitFor(() => expect(api.details.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-links-roots/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: linksEvidence() } });
    await pending; expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull();
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.storagePermission()).toBe(false);
  });
});

it('AccountApi link commands use independent fixed scoped paths and private same-origin CSRF/GET options', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorLinksRoots(7, 9); await api.competitorLinksRoots(7, 9, undefined, undefined, 'links.key');
  await api.competitorLinksRoots(7, 9, undefined, 21); await api.competitorLinksRoots(7, 9, { origin: ORIGIN }, undefined, undefined, true);
  await api.competitorLinksRoots(7, 9, { idempotency_key: 'links.key' }); await api.competitorLinksRoots(7, 9, {}, 21); await api.competitorLinksRootComparison(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-links-roots/'));
  expect(calls.map(([url]) => url.split('/competitor-links-roots/')[1])).toEqual(['', '?idempotency_key=links.key', '21/', 'selection/', '', '21/', 'comparison/?previous_job_id=21&current_job_id=22']);
  expect(calls.slice(0, 3).every(([, options]) => options.method === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3, 6).every(([, options]) => options.method === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls[6][1].method).toBe('GET'); expect(calls[6][1].body).toBeUndefined();
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});

describe('Private exact selected competitor page workflow', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-pages/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, url = ORIGIN + '/selected/article') {
    component.editOrigin(api.origins[0]); component.editUrl(url);
    component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  function savedPair() { api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }]; api.pairValue = pageComparison(); }
  function selectPair(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('deliberately reads only a frozen exact saved page pair with labelled controls, opaque original SHA and escaped metadata', async () => {
    savedPair(); api.actor = 2; api.role = 'admin'; const { component, harness } = await screen(); harness.detectChanges();
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.pagePairs).toEqual([]);
    for (const id of ['competitor-previous', 'competitor-current']) expect(harness.routeNativeElement!.querySelector(`label[for=${id}]`)).not.toBeNull();
    await component.compare(); component.editPair('previous', '999'); component.editPair('current', '022'); await component.compare(); expect(api.pagePairs).toEqual([]);
    selectPair(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(api.pagePairs).toEqual([[21, 22]]); expect(api.pairs).toEqual([]); expect(component.comparison()).toEqual(pageComparison());
    expect(harness.routeNativeElement!.textContent).toContain('does not establish page identity');
    expect(harness.routeNativeElement!.textContent).toContain('Changed <img src=x onerror=alert(1)>');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(api.catalogCalls).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.synthDetails).toEqual([]); expect(api.synthCancels).toEqual([]);
    expect(api.commands).toEqual([]); expect(api.previews).toBe(0); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('preserves empty zero counts separately from unavailable/truncated null page metadata differences', async () => {
    savedPair(); const { component } = await screen();
    for (const state of ['empty', 'unavailable', 'title_truncated', 'description_truncated']) {
      api.pairValue = pageComparison(); const value = api.pairValue; const before = value['previous'].evidence; const after = value['current'].evidence;
      if (state === 'empty') {
        for (const item of [before, after]) { item.metadata.title = ''; item.metadata.description = ''; item.counts = Object.fromEntries(Object.keys(item.counts).map(key => [key, 0])); }
        value['metadata_changed'] = { title: false, description: false }; value['count_deltas'] = Object.fromEntries(Object.keys(value['count_deltas']).map(key => [key, 0]));
      } else {
        if (state === 'unavailable') { before.state = 'unavailable'; before.reason = 'ambiguous_markup'; before.metadata = null; before.counts = Object.fromEntries(Object.keys(before.counts).map(key => [key, null])); }
        else after.metadata[state] = true;
        value['comparable'] = false; value['state'] = 'incomparable_unavailable_or_truncated_metadata'; value['metadata_changed'] = null; value['count_deltas'] = null;
      }
      selectPair(component); await component.compare(); expect(component.comparison()).toEqual(value);
    }
  });
  it('rejects Root/wrong-method-URI-date-body-source/null-shape or fabricated literal page comparison DTOs', async () => {
    savedPair(); const { component } = await screen();
    const changes: ((value: Row) => void)[] = [v => v['method_version'] = 'competitor-static-comparison-v1', v => v['collection_method'] = 'competitor-static-root-collect-v1',
      v => v['interpretation'] = comparison()['interpretation'], v => v['raw_body'] = 'private', v => v['project_id'] = 10, v => v['source_current'] = 1,
      v => v['url'] = ORIGIN + '/', v => v['url'] = OWN + '/selected/article', v => v['current'].evidence.url = ORIGIN + '/other',
      v => v['current'].evidence.observed_at = OBSERVED, v => v['source_sha256'] = 'bad', v => v['current'].evidence.body_sha256 = null,
      v => v['current'].evidence.body_size_bytes = 131073, v => v['count_deltas'].h1 = 1, v => v['metadata_changed'].title = false,
      v => v['body_changed'] = false, v => v['body_changed'] = null, v => v['previous'].job_id = 22, v => v['count_deltas'] = null];
    for (const change of changes) {
      await component.load(); api.pairValue = pageComparison(); change(api.pairValue); selectPair(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.previousJobId()).toBe(0);
    }
    expect(api.pairs).toEqual([]); expect(api.synthCommands).toEqual([]);
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'denial'])('clears the private page pair after late %s loss', async field => {
    savedPair(); const { component } = await screen(); selectPair(component);
    api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'denial') api.pairStatus = 403;
    };
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.commands).toEqual([]); expect(api.pairs).toEqual([]);
  });
  it('rechecks frozen page job status before GET and clears delivery on URI, rights, pair, refresh, route and destruction', async () => {
    savedPair(); const { component, harness } = await screen(); selectPair(component); api.rows[1].updated_at = OBSERVED;
    await component.compare(); expect(api.pagePairs).toEqual([]); expect(component.frozenPair()).toBeNull();
    savedPair(); await component.load();
    for (const edit of [() => component.editUrl(ORIGIN + '/other'), () => component.editOrigin(ORIGIN), () => component.editPermission('use', false), () => component.editPair('current', '21')]) {
      selectPair(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    selectPair(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull();
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    selectPair(component); const count = api.pagePairs.length; const reading = component.compare(); await vi.waitFor(() => expect(api.pagePairs.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-pages/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 403, body: {} }); await reading; expect(component.comparison()).toBeNull(); expect(component.error()).toBe('');
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.frozenPair()).toBeNull();
  });
  it('starts with an empty labelled exact URI and unchecked rights, deliberate saved-page controls and no old pair or model calls', async () => {
    const { harness, component } = await screen(); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toContain('competitor page metadata');
    const input = harness.routeNativeElement!.querySelector<HTMLInputElement>('#competitor-page-url')!;
    expect(input.value).toBe(''); expect(input.required).toBe(true); expect(input.maxLength).toBe(1024);
    expect(harness.routeNativeElement!.querySelector('label[for="competitor-page-url"]')).not.toBeNull();
    expect(component.collectionPermission()).toBe(false); expect(component.usePermission()).toBe(false); expect(component.storagePermission()).toBe(false);
    expect(harness.routeNativeElement!.querySelector('#competitor-model')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('#competitor-previous')).not.toBeNull();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.compare();
    expect(api.catalogCalls).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.pairs).toEqual([]); expect(api.pagePairs).toEqual([]);
    declare(component); await component.preview(); const frozen = structuredClone(component.selection()!);
    expect(frozen['selection']['method']).toBe('competitor-static-page-collect-v1'); expect(frozen['selection'].binding['url']).toBe(ORIGIN + '/selected/article');
    expect(frozen['selection'].binding['method_version']).toBe('competitor-page-source-v1'); expect(frozen.selection_digest).toBe(await sha(frozen['selection']));
    await component.launch(); expect(api.commands).toHaveLength(1);
    expect(api.commands[0]).toEqual({ origin: ORIGIN, url: ORIGIN + '/selected/article', collection_permission: true,
      use_permission: true, storage_permission: true, selection_digest: frozen.selection_digest, idempotency_key: api.commands[0]['idempotency_key'] });
    expect(api.familyCalls.every(family => family === 'page')).toBe(true);
  });
  it('denies missing/root/foreign/cross-scheme/subdomain/custom-port/query-fragment/credential/control or oversized URIs before preview', async () => {
    const { component } = await screen();
    for (const url of ['', ORIGIN, ORIGIN + '/', ORIGIN + '/a?', ORIGIN + '/a#', ORIGIN + '/a?secret=x', ORIGIN + '/%0a', ORIGIN + '/back\\slash',
      'https://competitor.example.invalid:443/a', 'https://competitor.example.invalid:8443/a', 'https://user:secret@competitor.example.invalid/a',
      'http://competitor.example.invalid/a', 'https://sub.competitor.example.invalid/a', OWN + '/a', ORIGIN + '/x' + 'x'.repeat(1024)]) {
      declare(component, url); await component.preview(); expect(component.selection()).toBeNull();
    }
    expect(api.previews).toBe(0); expect(api.commands).toEqual([]);
    declare(component, ORIGIN + '/' + 'x'.repeat(1024 - ORIGIN.length - 1)); await component.preview(); expect(component.selection()).not.toBeNull();
    api.origins = ['http://competitor.example.invalid']; await component.load(); declare(component, api.origins[0] + '/selected/article');
    await component.preview(); expect(component.selection()).not.toBeNull();
  });
  it('clears evidence, frozen selection, local uncertainty and all declarations on exact URL or origin edits', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    await component.inspect(21); expect(component.evidence()).not.toBeNull();
    declare(component); await component.preview(); api.uncertain = true; await component.launch(); expect(component.pending()).not.toBeNull();
    component.editUrl(ORIGIN + '/other'); expect(component.pending()).toBeNull(); expect(component.selection()).toBeNull(); expect(component.evidence()).toBeNull();
    expect(component.collectionPermission()).toBe(false); expect(component.usePermission()).toBe(false); expect(component.storagePermission()).toBe(false);
    component.editOrigin(ORIGIN); expect(component.url()).toBe('');
  });
  it('retains opaque original actor/date/body and escaped static metadata while zero differs from unavailable null', async () => {
    api.actor = 2; api.role = 'admin'; api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    await component.inspect(21); expect(component.evidence()).toEqual(pageEvidence()); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain('<script>literal only</script>'); expect(harness.routeNativeElement!.querySelector('script')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('does not establish page identity');
    for (const unavailable of [false, true]) {
      api.detailValue = pageEvidence(); const value = api.detailValue['collection'].evidence;
      value.counts = Object.fromEntries(Object.keys(value.counts).map(key => [key, unavailable ? null : 0]));
      value.state = unavailable ? 'unavailable' : 'observed'; value.reason = unavailable ? 'ambiguous_markup' : '';
      value.metadata = unavailable ? null : { title: '', description: '', title_truncated: false, description_truncated: false };
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
    expect(api.familyCalls.every(family => family === 'page')).toBe(true);
  });
  it('rejects old-root/schema/link, mismatched URI/date/body, injected extra fields and malformed metadata before display', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    const mutations: ((row: Row) => void)[] = [
      row => row['collection'] = evidence()['collection'], row => row['collection'] = schemaEvidence()['collection'], row => row['collection'] = linksEvidence()['collection'],
      row => row['collection']['url'] = ORIGIN + '/', row => row['collection'].requested_url = ORIGIN + '/other',
      row => { row['collection']['url'] = row['collection'].requested_url = 'https://foreign.example.invalid/a'; },
      row => row['collection'].evidence['url'] = ORIGIN + '/other', row => row['collection'].evidence.raw_body = '<img src=x onerror=alert(1)>',
      row => row['collection'].evidence.counts.h1 = true, row => row['collection'].evidence.counts.h1 = -1,
      row => row['collection'].evidence.counts.h1 = 0.5, row => row['collection'].evidence.counts.h1 = 1001,
      row => row['collection'].evidence.metadata.title = 42, row => row['collection'].evidence.metadata.title_truncated = 'false',
      row => { row['collection'].evidence.state = 'unavailable'; row['collection'].evidence.reason = 'ambiguous_markup'; },
      row => row['collection'].evidence.body_sha256 = 'bad', row => row['collection'].evidence.body_size_bytes = 131073,
      row => row['collection'].evidence.observed_at = LATER, row => row['collection'].evidence.excluded_containers = [],
      row => row['collection'].evidence.coverage = 'whole_site', row => row['collection'].interpretation = 'one_selected_static_root_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks',
    ];
    for (const mutate of mutations) {
      await component.load(); api.detailValue = pageEvidence(); mutate(api.detailValue); await component.inspect(21);
      expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull(); harness.detectChanges();
      expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it('rejects altered page source URL/method/shape/scope/meaning/digest, missing rights and late source drift before any POST', async () => {
    const { component } = await screen(); component.editOrigin(ORIGIN); component.editUrl(ORIGIN + '/selected/article');
    component.editPermission('collection', true); component.editPermission('use', true); await component.preview(); expect(api.previews).toBe(0);
    for (const mutate of [
      (row: Row) => row['selection']['method'] = 'competitor-static-root-collect-v1', (row: Row) => row['selection'].binding['url'] = ORIGIN + '/other',
      (row: Row) => delete row['selection'].binding['url'], (row: Row) => row['selection'].binding['method_version'] = 'competitor-source-v1',
      (row: Row) => row['selection'].binding.scope_kind = 'selected_competitor_hostname_default_http_https_only',
      (row: Row) => row['selection'].binding.interpretation = 'page_identity_verified', (row: Row) => row['selection'].binding.raw_body = 'private',
    ]) { declare(component); api.previewChange = mutate; await component.preview(); expect(component.selection()).toBeNull(); }
    api.previewChange = null; declare(component); api.badDigest = true; await component.preview(); expect(component.selection()).toBeNull();
    api.badDigest = false; await component.preview(); expect(component.selection()).not.toBeNull();
    api.afterPreview = () => ++api.revision; await component.launch(); expect(api.commands).toEqual([]); expect(component.pending()).toBeNull();
  });
  it('freezes the exact URI in uncertain commands and resolves only its original own-key GET without POST replay', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()!); expect(frozen.data['url']).toBe(ORIGIN + '/selected/article');
    expect((frozen.preview as Row)['selection'].binding['url']).toBe(frozen.data['url']);
    await component.reconcile(); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([frozen.key]); expect(component.pending()).toBeNull();
    await component.load(); declare(component); await component.preview(); api.drop = true; await component.launch();
    const count = api.commands.length; await component.reconcile(); expect(api.commands).toHaveLength(count); expect(component.pending()).not.toBeNull();
    component.discard(); expect(component.pending()).toBeNull();
  });
  it('cancels through the fixed page route and clears uncertainty on actor loss', async () => {
    api.rows = [job()]; const { component } = await screen(); await component.cancel(21); expect(api.cancels).toEqual([21]);
    await component.load(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    api.actor = 2; await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.url()).toBe(''); expect(component.origins()).toEqual([]);
  });
  it('withholds late page detail after role drift, URL edits, route changes and destruction', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    api.afterDetail = () => api.role = 'admin'; await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    api.afterDetail = null; await component.load(); await component.inspect(21); expect(component.evidence()).not.toBeNull();
    component.editUrl(ORIGIN + '/other'); expect(component.evidence()).toBeNull();
    let release!: (result: ApiResult) => void; api.detailPromise = new Promise<ApiResult>(resolve => release = resolve);
    const count = api.details.length; const pending = component.inspect(21); await vi.waitFor(() => expect(api.details.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-pages/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: pageEvidence() } });
    await pending; expect(component.evidence()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.url()).toBe('');
  });
});

it('AccountApi page commands use fixed scoped paths and private same-origin CSRF/GET options', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorPages(7, 9); await api.competitorPages(7, 9, undefined, undefined, 'page.key');
  await api.competitorPages(7, 9, undefined, 21); await api.competitorPages(7, 9, { origin: ORIGIN, url: ORIGIN + '/selected/article' }, undefined, undefined, true);
  await api.competitorPages(7, 9, { idempotency_key: 'page.key' }); await api.competitorPages(7, 9, {}, 21);
  await api.competitorPageComparison(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-pages/'));
  expect(calls.map(([url]) => url.split('/competitor-pages/')[1])).toEqual(['', '?idempotency_key=page.key', '21/', 'selection/', '', '21/', 'comparison/?previous_job_id=21&current_job_id=22']);
  expect(calls.slice(0, 3).every(([, options]) => options['method'] === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3, 6).every(([, options]) => options['method'] === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls[6][1].method).toBe('GET'); expect(calls[6][1].body).toBeUndefined();
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});

describe('Private exact selected competitor page heading workflow', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-headings/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, url = ORIGIN + '/selected/article') {
    component.editOrigin(api.origins[0]); component.editUrl(url);
    component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  it('preserves the source whitespace and codepoint contract and all unavailable reasons without fabricating counts', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    for (const text of ['\ufeffliteral\ufeff', '🙂'.repeat(80), '']) {
      api.detailValue = headingsEvidence(); api.detailValue['collection'].evidence.headings[0].text = text;
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
    for (const text of ['a\u0085b', 'a\u00a0b', '\ud800', '🙂'.repeat(81)]) {
      await component.load(); api.detailValue = headingsEvidence(); api.detailValue['collection'].evidence.headings[0].text = text;
      await component.inspect(21); expect(component.evidence()).toBeNull();
    }
    for (const reason of ['ambiguous_markup', 'element_limit', 'heading_limit', 'result_limit']) {
      await component.load(); api.detailValue = headingsEvidence(); const value = api.detailValue['collection'].evidence;
      value.state = 'unavailable'; value.reason = reason; value.headings = null;
      value.counts = Object.fromEntries(Object.keys(value.counts).map(key => [key, null]));
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('withholds a late heading DTO and clears local state after %s scope loss', async field => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    api.afterDetail = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
    };
    await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.selection()).toBeNull(); expect(component.pending()).toBeNull(); expect(component.url()).toBe('');
  });
  it('starts with an empty labelled exact URI and unchecked rights and deliberate pair controls and no automatic pair/model calls', async () => {
    const { harness, component } = await screen(); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toContain('competitor page literal headings');
    const input = harness.routeNativeElement!.querySelector<HTMLInputElement>('#competitor-page-url')!;
    expect(input.value).toBe(''); expect(input.required).toBe(true); expect(input.maxLength).toBe(1024);
    expect(harness.routeNativeElement!.querySelector('label[for="competitor-page-url"]')).not.toBeNull();
    expect(component.collectionPermission()).toBe(false); expect(component.usePermission()).toBe(false); expect(component.storagePermission()).toBe(false);
    expect(harness.routeNativeElement!.querySelector('#competitor-model')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('#competitor-previous')).not.toBeNull();
    component.editPair('previous', '21'); component.editPair('current', '22');
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61); await component.compare();
    expect(api.catalogCalls).toBe(1); expect(api.synthCommands).toEqual([]); expect(api.synthDetails).toEqual([]); expect(api.synthCancels).toEqual([]);
    expect(api.pairs).toEqual([]); expect(api.pagePairs).toEqual([]); expect(api.schemaPairs).toEqual([]); expect(api.linksPairs).toEqual([]);
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0);
    declare(component); await component.preview(); const frozen = structuredClone(component.selection()!);
    expect(frozen['selection']['method']).toBe('competitor-page-headings-collect-v1'); expect(frozen['selection'].binding['url']).toBe(ORIGIN + '/selected/article');
    expect(frozen['selection'].binding['method_version']).toBe('competitor-page-source-v1'); expect(frozen.selection_digest).toBe(await sha(frozen['selection']));
    await component.launch(); expect(api.commands).toHaveLength(1);
    expect(api.commands[0]).toEqual({ origin: ORIGIN, url: ORIGIN + '/selected/article', collection_permission: true,
      use_permission: true, storage_permission: true, selection_digest: frozen.selection_digest, idempotency_key: api.commands[0]['idempotency_key'] });
    expect(api.familyCalls.every(family => family === 'headings')).toBe(true);
  });
  it('denies missing/root/foreign/cross-scheme/subdomain/custom-port/query-fragment/credential/control or oversized URIs before preview', async () => {
    const { component } = await screen();
    for (const url of ['', ORIGIN, ORIGIN + '/', ORIGIN + '/a?', ORIGIN + '/a#', ORIGIN + '/a?secret=x', ORIGIN + '/%0a', ORIGIN + '/back\\slash',
      'https://competitor.example.invalid:443/a', 'https://competitor.example.invalid:8443/a', 'https://user:secret@competitor.example.invalid/a',
      'http://competitor.example.invalid/a', 'https://sub.competitor.example.invalid/a', OWN + '/a', ORIGIN + '/x' + 'x'.repeat(1024)]) {
      declare(component, url); await component.preview(); expect(component.selection()).toBeNull();
    }
    expect(api.previews).toBe(0); expect(api.commands).toEqual([]);
    declare(component, ORIGIN + '/' + 'x'.repeat(1024 - ORIGIN.length - 1)); await component.preview(); expect(component.selection()).not.toBeNull();
    api.origins = ['http://competitor.example.invalid']; await component.load(); declare(component, api.origins[0] + '/selected/article');
    await component.preview(); expect(component.selection()).not.toBeNull();
  });
  it('clears evidence, frozen selection, local uncertainty and all declarations on exact URL or origin edits', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    await component.inspect(21); expect(component.evidence()).not.toBeNull();
    declare(component); await component.preview(); api.uncertain = true; await component.launch(); expect(component.pending()).not.toBeNull();
    component.editUrl(ORIGIN + '/other'); expect(component.pending()).toBeNull(); expect(component.selection()).toBeNull(); expect(component.evidence()).toBeNull();
    expect(component.collectionPermission()).toBe(false); expect(component.usePermission()).toBe(false); expect(component.storagePermission()).toBe(false);
    component.editOrigin(ORIGIN); expect(component.url()).toBe('');
  });
  it('retains opaque original actor/date/body and escaped static metadata while zero differs from unavailable null', async () => {
    api.actor = 2; api.role = 'admin'; api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    await component.inspect(21); expect(component.evidence()).toEqual(headingsEvidence()); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain('<img src=x onerror=alert(1)>'); expect(harness.routeNativeElement!.querySelector('script, img')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('semantic outline');
    for (const unavailable of [false, true]) {
      api.detailValue = headingsEvidence(); const value = api.detailValue['collection'].evidence;
      value.counts = Object.fromEntries(Object.keys(value.counts).map(key => [key, unavailable ? null : 0]));
      value.state = unavailable ? 'unavailable' : 'observed'; value.reason = unavailable ? 'ambiguous_markup' : '';
      value.headings = unavailable ? null : [];
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
    expect(api.familyCalls.every(family => family === 'headings')).toBe(true);
  });
  it('rejects old-root/schema/link, mismatched URI/date/body, injected extra fields and malformed metadata before display', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    const mutations: ((row: Row) => void)[] = [
      row => row['collection'] = pageEvidence()['collection'], row => row['collection'] = evidence()['collection'], row => row['collection'] = schemaEvidence()['collection'], row => row['collection'] = linksEvidence()['collection'],
      row => row['collection']['url'] = ORIGIN + '/', row => row['collection'].requested_url = ORIGIN + '/other',
      row => { row['collection']['url'] = row['collection'].requested_url = 'https://foreign.example.invalid/a'; },
      row => row['collection'].evidence['url'] = ORIGIN + '/other', row => row['collection'].evidence.raw_body = '<img src=x onerror=alert(1)>',
      row => row['collection'].evidence.counts.h1 = true, row => row['collection'].evidence.counts.h1 = -1,
      row => row['collection'].evidence.counts.h1 = 0.5, row => row['collection'].evidence.counts.h1 = 1001,
      row => row['collection'].evidence.headings[0].text = 42, row => row['collection'].evidence.headings[0].truncated = 'false',
      row => row['collection'].evidence.headings[0].level = true, row => row['collection'].evidence.headings[0].level = 0,
      row => row['collection'].evidence.headings[0].level = 7, row => row['collection'].evidence.headings[0].level = 1.5,
      row => row['collection'].evidence.headings[0].text = 'x'.repeat(81), row => row['collection'].evidence.headings[0].text = '  unnormalized  ',
      row => row['collection'].evidence.headings[0].text = 'bad\ncontrol',
      row => { row['collection'].evidence.headings[0].text = ''; row['collection'].evidence.headings[0].truncated = true; },
      row => row['collection'].evidence.headings[0].html = 'private', row => row['collection'].evidence.headings = Array(11).fill({ level: 1, text: 'x', truncated: false }),
      row => row['collection'].evidence.counts.h6 = 0, row => row['collection'].evidence.method_version = 'competitor-static-metadata-v1',
      row => row['collection'].evidence.interpretation = 'semantic_outline_verified',
      row => { row['collection'].evidence.state = 'unavailable'; row['collection'].evidence.reason = 'ambiguous_markup'; },
      row => row['collection'].evidence.body_sha256 = 'bad', row => row['collection'].evidence.body_size_bytes = 131073,
      row => row['collection'].evidence.observed_at = LATER, row => row['collection'].evidence.excluded_containers = [],
      row => row['collection'].evidence.coverage = 'whole_site', row => row['collection'].interpretation = 'one_selected_static_root_not_site_inventory_rendering_freshness_traffic_rankings_or_backlinks',
    ];
    for (const mutate of mutations) {
      await component.load(); api.detailValue = headingsEvidence(); mutate(api.detailValue); await component.inspect(21);
      expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull(); harness.detectChanges();
      expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it('rejects altered page source URL/method/shape/scope/meaning/digest, missing rights and late source drift before any POST', async () => {
    const { component } = await screen(); component.editOrigin(ORIGIN); component.editUrl(ORIGIN + '/selected/article');
    component.editPermission('collection', true); component.editPermission('use', true); await component.preview(); expect(api.previews).toBe(0);
    for (const mutate of [
      (row: Row) => row['selection']['method'] = 'competitor-static-root-collect-v1', (row: Row) => row['selection'].binding['url'] = ORIGIN + '/other',
      (row: Row) => delete row['selection'].binding['url'], (row: Row) => row['selection'].binding['method_version'] = 'competitor-source-v1',
      (row: Row) => row['selection'].binding.scope_kind = 'selected_competitor_hostname_default_http_https_only',
      (row: Row) => row['selection'].binding.interpretation = 'page_identity_verified', (row: Row) => row['selection'].binding.raw_body = 'private',
    ]) { declare(component); api.previewChange = mutate; await component.preview(); expect(component.selection()).toBeNull(); }
    api.previewChange = null; declare(component); api.badDigest = true; await component.preview(); expect(component.selection()).toBeNull();
    api.badDigest = false; await component.preview(); expect(component.selection()).not.toBeNull();
    api.afterPreview = () => ++api.revision; await component.launch(); expect(api.commands).toEqual([]); expect(component.pending()).toBeNull();
  });
  it('freezes the exact URI in uncertain commands and resolves only its original own-key GET without POST replay', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()!); expect(frozen.data['url']).toBe(ORIGIN + '/selected/article');
    expect((frozen.preview as Row)['selection'].binding['url']).toBe(frozen.data['url']);
    await component.reconcile(); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([frozen.key]); expect(component.pending()).toBeNull();
    await component.load(); declare(component); await component.preview(); api.drop = true; await component.launch();
    const count = api.commands.length; await component.reconcile(); expect(api.commands).toHaveLength(count); expect(component.pending()).not.toBeNull();
    component.discard(); expect(component.pending()).toBeNull();
  });
  it('cancels through the fixed page route and clears uncertainty on actor loss', async () => {
    api.rows = [job()]; const { component } = await screen(); await component.cancel(21); expect(api.cancels).toEqual([21]);
    await component.load(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    api.actor = 2; await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.url()).toBe(''); expect(component.origins()).toEqual([]);
  });
  it('withholds late page detail after role drift, URL edits, route changes and destruction', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    api.afterDetail = () => api.role = 'admin'; await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    api.afterDetail = null; await component.load(); await component.inspect(21); expect(component.evidence()).not.toBeNull();
    component.editUrl(ORIGIN + '/other'); expect(component.evidence()).toBeNull();
    let release!: (result: ApiResult) => void; api.detailPromise = new Promise<ApiResult>(resolve => release = resolve);
    const count = api.details.length; const pending = component.inspect(21); await vi.waitFor(() => expect(api.details.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-page-headings/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: headingsEvidence() } });
    await pending; expect(component.evidence()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.url()).toBe('');
  });
});


it('AccountApi heading commands use fixed scoped paths and private same-origin CSRF/GET options', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorPageHeadings(7, 9); await api.competitorPageHeadings(7, 9, undefined, undefined, 'headings.key');
  await api.competitorPageHeadings(7, 9, undefined, 21); await api.competitorPageHeadings(7, 9, { origin: ORIGIN, url: ORIGIN + '/selected/article' }, undefined, undefined, true);
  await api.competitorPageHeadings(7, 9, { idempotency_key: 'headings.key' }); await api.competitorPageHeadings(7, 9, {}, 21);
  await api.competitorPageHeadingsComparison(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-page-headings/'));
  expect(calls.map(([url]) => url.split('/competitor-page-headings/')[1])).toEqual(['', '?idempotency_key=headings.key', '21/', 'selection/', '', '21/', 'comparison/?previous_job_id=21&current_job_id=22']);
  expect(calls.slice(0, 3).every(([, options]) => options['method'] === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3, 6).every(([, options]) => options['method'] === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls[6][1].method).toBe('GET'); expect(calls[6][1].body).toBeUndefined();
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});

describe('Private exact saved competitor heading pairs', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-headings/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, url = ORIGIN + '/selected/article') {
    component.editOrigin(api.origins[0]); component.editUrl(url);
    component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  function savedPair() { api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }]; api.pairValue = headingsComparison(); }
  function selectPair(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('deliberately reads only a frozen exact saved page pair with labelled controls, opaque original SHA and escaped metadata', async () => {
    savedPair(); api.actor = 2; api.role = 'admin'; const { component, harness } = await screen(); harness.detectChanges();
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.headingsPairs).toEqual([]);
    for (const id of ['competitor-previous', 'competitor-current']) expect(harness.routeNativeElement!.querySelector(`label[for=${id}]`)).not.toBeNull();
    await component.compare(); component.editPair('previous', '999'); component.editPair('current', '022'); await component.compare(); expect(api.headingsPairs).toEqual([]);
    selectPair(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(api.headingsPairs).toEqual([[21, 22]]); expect(api.pairs).toEqual([]); expect(component.comparison()).toEqual(headingsComparison());
    expect(harness.routeNativeElement!.textContent).toContain('semantic outline');
    expect(harness.routeNativeElement!.textContent).toContain('Changed <img src=x onerror=alert(1)>');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(api.catalogCalls).toBe(1); expect(api.synthCommands).toEqual([]); expect(api.synthDetails).toEqual([]); expect(api.synthCancels).toEqual([]);
    expect(api.commands).toEqual([]); expect(api.previews).toBe(0); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('preserves empty zero counts separately from unavailable/truncated null page metadata differences', async () => {
    savedPair(); const { component } = await screen();
    for (const state of ['empty', 'unavailable', 'truncated']) {
      api.pairValue = headingsComparison(); const value = api.pairValue; const before = value['previous'].evidence; const after = value['current'].evidence;
      if (state === 'empty') {
        for (const item of [before, after]) { item.headings = []; item.counts = Object.fromEntries(Object.keys(item.counts).map(key => [key, 0])); }
        value['headings_changed'] = false; value['count_deltas'] = Object.fromEntries(Object.keys(value['count_deltas']).map(key => [key, 0]));
      } else {
        if (state === 'unavailable') { before.state = 'unavailable'; before.reason = 'ambiguous_markup'; before.headings = null; before.counts = Object.fromEntries(Object.keys(before.counts).map(key => [key, null])); }
        else after.headings[0].truncated = true;
        value['comparable'] = false; value['state'] = 'incomparable_unavailable_or_truncated_heading_text'; value['headings_changed'] = null; value['count_deltas'] = null;
      }
      selectPair(component); await component.compare(); expect(component.comparison()).toEqual(value);
    }
  });
  it('rejects Root/wrong-method-URI-date-body-source/null-shape or fabricated literal page comparison DTOs', async () => {
    savedPair(); const { component } = await screen();
    const changes: ((value: Row) => void)[] = [v => v['method_version'] = 'competitor-static-comparison-v1', v => v['collection_method'] = 'competitor-static-root-collect-v1',
      v => v['interpretation'] = comparison()['interpretation'], v => v['raw_body'] = 'private', v => v['project_id'] = 10, v => v['source_current'] = 1,
      v => v['url'] = ORIGIN + '/', v => v['url'] = OWN + '/selected/article', v => v['current'].evidence.url = ORIGIN + '/other',
      v => v['current'].evidence.observed_at = OBSERVED, v => v['source_sha256'] = 'bad', v => v['current'].evidence.body_sha256 = null,
      v => v['current'].evidence.body_size_bytes = 131073, v => v['count_deltas'].h1 = 1, v => v['headings_changed'] = false, v => v['headings_changed'] = 1,
      v => v['current'].evidence.headings[0].level = true, v => v['current'].evidence.headings[0].text = 'x'.repeat(81),
      v => v['current'].evidence.headings[0].truncated = true, v => v['current'].evidence.headings[0].html = 'private',
      v => v['metadata_changed'] = { title: false, description: false }, v => v['count_deltas'].href_anchors = 0,
      v => v['body_changed'] = false, v => v['body_changed'] = null, v => v['previous'].job_id = 22, v => v['count_deltas'] = null];
    for (const change of changes) {
      await component.load(); api.pairValue = headingsComparison(); change(api.pairValue); selectPair(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.previousJobId()).toBe(0);
    }
    expect(api.pairs).toEqual([]); expect(api.synthCommands).toEqual([]);
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'denial'])('clears the private page pair after late %s loss', async field => {
    savedPair(); const { component } = await screen(); selectPair(component);
    api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'denial') api.pairStatus = 403;
    };
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.commands).toEqual([]); expect(api.pairs).toEqual([]);
  });
  it('rechecks frozen page job status before GET and clears delivery on URI, rights, pair, refresh, route and destruction', async () => {
    savedPair(); const { component, harness } = await screen(); selectPair(component); api.rows[1].updated_at = OBSERVED;
    await component.compare(); expect(api.headingsPairs).toEqual([]); expect(component.frozenPair()).toBeNull();
    savedPair(); await component.load();
    for (const edit of [() => component.editUrl(ORIGIN + '/other'), () => component.editOrigin(ORIGIN), () => component.editPermission('use', false), () => component.editPair('current', '21')]) {
      selectPair(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    selectPair(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull();
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    selectPair(component); const count = api.headingsPairs.length; const reading = component.compare(); await vi.waitFor(() => expect(api.headingsPairs.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-page-headings/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 403, body: {} }); await reading; expect(component.comparison()).toBeNull(); expect(component.error()).toBe('');
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.frozenPair()).toBeNull();
  });
});

describe('Private exact selected competitor page reference workflow', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-destinations/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, url = ORIGIN + '/selected/article') {
    component.editOrigin(api.origins[0]); component.editUrl(url);
    component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  it('preserves literal root/dot/valid-percent URI syntax and whole-null reasons without browser rewriting or denominator loss', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    for (const path of ['/', '/section/../raw', '/%2e%2e/raw', '/%FF', '/%E2%82%AC', '/%EF%BB%BF', '/%2520', '/a&b']) {
      api.detailValue = destinationsEvidence(); const value = api.detailValue['collection'].evidence;
      value.destinations = [ORIGIN + path]; value.counts.same_origin_http = 1; value.counts.href_anchors = 3;
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
    for (const reason of ['ambiguous_markup', 'element_limit', 'base_dependent_references', 'destination_limit', 'result_limit']) {
      api.detailValue = destinationsEvidence(); const value = api.detailValue['collection'].evidence;
      value.state = 'unavailable'; value.reason = reason; value.destinations = null;
      value.counts = Object.fromEntries(Object.keys(value.counts).map(key => [key, null]));
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
    api.detailValue = destinationsEvidence(); const value = api.detailValue['collection'].evidence;
    value.destinations = []; value.counts.same_origin_http = 0; value.counts.href_anchors = 2;
    await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('withholds a late reference DTO and clears local state after %s scope loss', async field => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    api.afterDetail = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
    };
    await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.selection()).toBeNull(); expect(component.pending()).toBeNull(); expect(component.url()).toBe('');
  });
  it('starts with an empty labelled exact URI and unchecked rights and deliberate pair controls while model promotion stays closed', async () => {
    const { harness, component } = await screen(); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('h1')!.textContent).toContain('competitor page same-origin references');
    const input = harness.routeNativeElement!.querySelector<HTMLInputElement>('#competitor-page-url')!;
    expect(input.value).toBe(''); expect(input.required).toBe(true); expect(input.maxLength).toBe(1024);
    expect(harness.routeNativeElement!.querySelector('label[for="competitor-page-url"]')).not.toBeNull();
    expect(component.collectionPermission()).toBe(false); expect(component.usePermission()).toBe(false); expect(component.storagePermission()).toBe(false);
    expect(harness.routeNativeElement!.querySelector('#competitor-model')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('#competitor-previous')).not.toBeNull();
    component.editPair('previous', '21'); component.editPair('current', '22');
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61); await component.compare();
    expect(api.catalogCalls).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.synthDetails).toEqual([]); expect(api.synthCancels).toEqual([]);
    expect(api.pairs).toEqual([]); expect(api.pagePairs).toEqual([]); expect(api.schemaPairs).toEqual([]); expect(api.linksPairs).toEqual([]); expect(api.headingsPairs).toEqual([]);
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0);
    declare(component); await component.preview(); const frozen = structuredClone(component.selection()!);
    expect(frozen['selection']['method']).toBe('competitor-page-destinations-v1'); expect(frozen['selection'].binding['url']).toBe(ORIGIN + '/selected/article');
    expect(frozen['selection'].binding['method_version']).toBe('competitor-page-source-v1'); expect(frozen.selection_digest).toBe(await sha(frozen['selection']));
    await component.launch(); expect(api.commands).toHaveLength(1);
    expect(api.commands[0]).toEqual({ origin: ORIGIN, url: ORIGIN + '/selected/article', collection_permission: true,
      use_permission: true, storage_permission: true, selection_digest: frozen.selection_digest, idempotency_key: api.commands[0]['idempotency_key'] });
    expect(api.familyCalls.every(family => family === 'destinations')).toBe(true);
  });
  it('denies missing/root/foreign/cross-scheme/subdomain/custom-port/query-fragment/credential/control or oversized URIs before preview', async () => {
    const { component } = await screen();
    for (const url of ['', ORIGIN, ORIGIN + '/', ORIGIN + '/a?', ORIGIN + '/a#', ORIGIN + '/a?secret=x', ORIGIN + '/%0a', ORIGIN + '/back\\slash',
      'https://competitor.example.invalid:443/a', 'https://competitor.example.invalid:8443/a', 'https://user:secret@competitor.example.invalid/a',
      'http://competitor.example.invalid/a', 'https://sub.competitor.example.invalid/a', OWN + '/a', ORIGIN + '/x' + 'x'.repeat(1024)]) {
      declare(component, url); await component.preview(); expect(component.selection()).toBeNull();
    }
    expect(api.previews).toBe(0); expect(api.commands).toEqual([]);
    declare(component, ORIGIN + '/' + 'x'.repeat(1024 - ORIGIN.length - 1)); await component.preview(); expect(component.selection()).not.toBeNull();
    api.origins = ['http://competitor.example.invalid']; await component.load(); declare(component, api.origins[0] + '/selected/article');
    await component.preview(); expect(component.selection()).not.toBeNull();
  });
  it('clears evidence, frozen selection, local uncertainty and all declarations on exact URL or origin edits', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    await component.inspect(21); expect(component.evidence()).not.toBeNull();
    declare(component); await component.preview(); api.uncertain = true; await component.launch(); expect(component.pending()).not.toBeNull();
    component.editUrl(ORIGIN + '/other'); expect(component.pending()).toBeNull(); expect(component.selection()).toBeNull(); expect(component.evidence()).toBeNull();
    expect(component.collectionPermission()).toBe(false); expect(component.usePermission()).toBe(false); expect(component.storagePermission()).toBe(false);
    component.editOrigin(ORIGIN); expect(component.url()).toBe('');
  });
  it('retains opaque original actor/date/body and escaped static metadata while zero differs from unavailable null', async () => {
    api.actor = 2; api.role = 'admin'; api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    await component.inspect(21); expect(component.evidence()).toEqual(destinationsEvidence()); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain(ORIGIN + '/a&b'); expect(harness.routeNativeElement!.querySelector('script, img')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('No referenced destination is requested');
    expect(harness.routeNativeElement!.querySelector('a[href="' + ORIGIN + '/a&b"]')).toBeNull();
    for (const unavailable of [false, true]) {
      api.detailValue = destinationsEvidence(); const value = api.detailValue['collection'].evidence;
      value.counts = Object.fromEntries(Object.keys(value.counts).map(key => [key, unavailable ? null : 0]));
      value.state = unavailable ? 'unavailable' : 'observed'; value.reason = unavailable ? 'ambiguous_markup' : '';
      value.destinations = unavailable ? null : [];
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
    expect(api.familyCalls.every(family => family === 'destinations')).toBe(true);
  });
  it('rejects old-root/schema/link, mismatched URI/date/body, injected extra fields and malformed metadata before display', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    const mutations: ((row: Row) => void)[] = [
      row => row['collection'] = headingsEvidence()['collection'], row => row['collection'] = pageEvidence()['collection'],
      row => row['collection'] = evidence()['collection'], row => row['collection'] = schemaEvidence()['collection'], row => row['collection'] = linksEvidence()['collection'],
      row => row['collection']['url'] = ORIGIN + '/', row => row['collection'].requested_url = ORIGIN + '/other',
      row => row['collection'].evidence['url'] = ORIGIN + '/other', row => row['collection'].evidence.raw_body = '<img src=x onerror=alert(1)>',
      row => row['collection'].evidence.counts.same_origin_http = true, row => row['collection'].evidence.counts.same_origin_http = -1,
      row => row['collection'].evidence.counts.same_origin_http = 0.5, row => row['collection'].evidence.counts.href_anchors = 1001,
      row => row['collection'].evidence.counts.unsupported = 0, row => row['collection'].evidence.destinations = null,
      row => row['collection'].evidence.destinations = Array(11).fill(ORIGIN + '/one'),
      row => row['collection'].evidence.destinations[0] = 42, row => row['collection'].evidence.destinations[0] = '/relative',
      row => row['collection'].evidence.destinations[0] = 'https://foreign.example.invalid/a',
      row => row['collection'].evidence.destinations[0] = 'http://competitor.example.invalid/a',
      row => row['collection'].evidence.destinations[0] = ORIGIN + ':443/a', row => row['collection'].evidence.destinations[0] = ORIGIN,
      row => row['collection'].evidence.destinations[0] = ORIGIN + '/?secret=x', row => row['collection'].evidence.destinations[0] = ORIGIN + '/#',
      row => row['collection'].evidence.destinations[0] = ORIGIN + '/%0a', row => row['collection'].evidence.destinations[0] = ORIGIN + '/%5c',
      row => row['collection'].evidence.destinations[0] = ORIGIN + '/%7f', row => row['collection'].evidence.destinations[0] = ORIGIN + '/%C2%85',
      row => row['collection'].evidence.destinations[0] = ORIGIN + '/%C2%A0', row => row['collection'].evidence.destinations[0] = ORIGIN + '/%E3%80%80',
      row => row['collection'].evidence.destinations[0] = ORIGIN + '/bad%ZZ', row => row['collection'].evidence.destinations[0] = ORIGIN + '/a|b',
      row => row['collection'].evidence.destinations[0] = ORIGIN + '/' + 'x'.repeat(1024),
      row => row['collection'].evidence.method_version = 'competitor-static-link-categories-v1',
      row => row['collection'].evidence.interpretation = 'verified_pages',
      row => { row['collection'].evidence.state = 'unavailable'; row['collection'].evidence.reason = 'destination_limit'; },
      row => row['collection'].evidence.body_sha256 = 'bad', row => row['collection'].evidence.body_size_bytes = 131073,
      row => row['collection'].evidence.observed_at = LATER, row => row['collection'].evidence.excluded_containers = [],
      row => row['collection'].evidence.coverage = 'whole_site',
    ];
    for (const mutate of mutations) {
      await component.load(); api.detailValue = destinationsEvidence(); mutate(api.detailValue); await component.inspect(21);
      expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull(); harness.detectChanges();
      expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it('rejects altered page source URL/method/shape/scope/meaning/digest, missing rights and late source drift before any POST', async () => {
    const { component } = await screen(); component.editOrigin(ORIGIN); component.editUrl(ORIGIN + '/selected/article');
    component.editPermission('collection', true); component.editPermission('use', true); await component.preview(); expect(api.previews).toBe(0);
    for (const mutate of [
      (row: Row) => row['selection']['method'] = 'competitor-static-root-collect-v1', (row: Row) => row['selection'].binding['url'] = ORIGIN + '/other',
      (row: Row) => delete row['selection'].binding['url'], (row: Row) => row['selection'].binding['method_version'] = 'competitor-source-v1',
      (row: Row) => row['selection'].binding.scope_kind = 'selected_competitor_hostname_default_http_https_only',
      (row: Row) => row['selection'].binding.interpretation = 'page_identity_verified', (row: Row) => row['selection'].binding.raw_body = 'private',
    ]) { declare(component); api.previewChange = mutate; await component.preview(); expect(component.selection()).toBeNull(); }
    api.previewChange = null; declare(component); api.badDigest = true; await component.preview(); expect(component.selection()).toBeNull();
    api.badDigest = false; await component.preview(); expect(component.selection()).not.toBeNull();
    api.afterPreview = () => ++api.revision; await component.launch(); expect(api.commands).toEqual([]); expect(component.pending()).toBeNull();
  });
  it('freezes the exact URI in uncertain commands and resolves only its original own-key GET without POST replay', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()!); expect(frozen.data['url']).toBe(ORIGIN + '/selected/article');
    expect((frozen.preview as Row)['selection'].binding['url']).toBe(frozen.data['url']);
    await component.reconcile(); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([frozen.key]); expect(component.pending()).toBeNull();
    await component.load(); declare(component); await component.preview(); api.drop = true; await component.launch();
    const count = api.commands.length; await component.reconcile(); expect(api.commands).toHaveLength(count); expect(component.pending()).not.toBeNull();
    component.discard(); expect(component.pending()).toBeNull();
  });
  it('cancels through the fixed page route and clears uncertainty on actor loss', async () => {
    api.rows = [job()]; const { component } = await screen(); await component.cancel(21); expect(api.cancels).toEqual([21]);
    await component.load(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    api.actor = 2; await component.reconcile(); expect(component.pending()).toBeNull(); expect(component.url()).toBe(''); expect(component.origins()).toEqual([]);
  });
  it('withholds late page detail after role drift, URL edits, route changes and destruction', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    api.afterDetail = () => api.role = 'admin'; await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    api.afterDetail = null; await component.load(); await component.inspect(21); expect(component.evidence()).not.toBeNull();
    component.editUrl(ORIGIN + '/other'); expect(component.evidence()).toBeNull();
    let release!: (result: ApiResult) => void; api.detailPromise = new Promise<ApiResult>(resolve => release = resolve);
    const count = api.details.length; const pending = component.inspect(21); await vi.waitFor(() => expect(api.details.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-page-destinations/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: destinationsEvidence() } });
    await pending; expect(component.evidence()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.url()).toBe('');
  });
});



it('AccountApi reference commands use fixed scoped paths and private same-origin CSRF/GET options', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorPageDestinations(7, 9); await api.competitorPageDestinations(7, 9, undefined, undefined, 'references.key');
  await api.competitorPageDestinations(7, 9, undefined, 21); await api.competitorPageDestinations(7, 9, { origin: ORIGIN, url: ORIGIN + '/selected/article' }, undefined, undefined, true);
  await api.competitorPageDestinations(7, 9, { idempotency_key: 'references.key' }); await api.competitorPageDestinations(7, 9, {}, 21);
  await api.competitorPageDestinationsComparison(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-page-destinations/'));
  expect(calls.map(([url]) => url.split('/competitor-page-destinations/')[1])).toEqual(['', '?idempotency_key=references.key', '21/', 'selection/', '', '21/', 'comparison/?previous_job_id=21&current_job_id=22']);
  expect(calls.slice(0, 3).every(([, options]) => options['method'] === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3, 6).every(([, options]) => options['method'] === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls[6][1].method).toBe('GET'); expect(calls[6][1].body).toBeUndefined();
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});

describe('Private exact saved competitor reference pairs', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-destinations/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, url = ORIGIN + '/selected/article') {
    component.editOrigin(api.origins[0]); component.editUrl(url);
    component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  function savedPair() { api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }]; api.pairValue = destinationsComparison(); }
  function selectPair(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('deliberately reads only a frozen exact saved page pair with labelled controls, opaque original SHA and escaped metadata', async () => {
    savedPair(); api.actor = 2; api.role = 'admin'; const { component, harness } = await screen(); harness.detectChanges();
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.destinationsPairs).toEqual([]);
    for (const id of ['competitor-previous', 'competitor-current']) expect(harness.routeNativeElement!.querySelector(`label[for=${id}]`)).not.toBeNull();
    await component.compare(); component.editPair('previous', '999'); component.editPair('current', '022'); await component.compare(); expect(api.destinationsPairs).toEqual([]);
    selectPair(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(api.destinationsPairs).toEqual([[21, 22]]); expect(api.pairs).toEqual([]); expect(component.comparison()).toEqual(destinationsComparison());
    expect(harness.routeNativeElement!.textContent).toContain('ordered duplicate-preserving');
    expect(harness.routeNativeElement!.textContent).toContain(ORIGIN + '/a&b');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(api.catalogCalls).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.synthDetails).toEqual([]); expect(api.synthCancels).toEqual([]);
    expect(api.commands).toEqual([]); expect(api.previews).toBe(0); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('preserves empty supported references with nonzero denominators, signed decreases and whole unavailable null differences', async () => {
    savedPair(); const { component } = await screen();
    for (const state of ['empty', 'decrease', 'unavailable', 'limit']) {
      api.pairValue = destinationsComparison(); const value = api.pairValue; const before = value['previous'].evidence; const after = value['current'].evidence;
      if (state === 'empty') {
        for (const item of [before, after]) { item.destinations = []; item.counts.same_origin_http = 0; item.counts.href_anchors = 2; }
        value['destinations_changed'] = false;
      } else if (state === 'decrease') {
        after.destinations = []; after.counts.same_origin_http = 0; after.counts.href_anchors = 2;
        value['count_deltas'] = { href_anchors: -3, same_origin_http: -3, other_origin_http: 0, unsupported: 0 };
      } else {
        before.state = 'unavailable'; before.reason = state === 'limit' ? 'result_limit' : 'ambiguous_markup'; before.destinations = null;
        before.counts = Object.fromEntries(Object.keys(before.counts).map(key => [key, null]));
        value['comparable'] = false; value['state'] = 'incomparable_unavailable_supported_same_origin_references'; value['destinations_changed'] = null; value['count_deltas'] = null;
      }
      selectPair(component); await component.compare(); expect(component.comparison()).toEqual(value);
    }
  });
  it('compares literal reference order independently from returned-body bytes and preserves original URI spelling', async () => {
    savedPair(); const { component } = await screen();
    for (const kind of ['same', 'body', 'order', 'literal']) {
      api.pairValue = destinationsComparison(); const value = api.pairValue; const before = value['previous'].evidence; const after = value['current'].evidence;
      if (kind === 'same' || kind === 'body') { after.destinations = structuredClone(before.destinations); value['destinations_changed'] = false; }
      if (kind === 'same') { after.body_sha256 = before.body_sha256; value['body_changed'] = false; }
      if (kind === 'literal') after.destinations[0] = ORIGIN + '/%2e%2e/raw';
      selectPair(component); await component.compare(); expect(component.comparison()).toEqual(value);
    }
  });
  it('rejects Root/wrong-method-URI-date-body-source/null-shape or fabricated literal page comparison DTOs', async () => {
    savedPair(); const { component } = await screen();
    const changes: ((value: Row) => void)[] = [v => v['method_version'] = 'competitor-static-comparison-v1', v => v['collection_method'] = 'competitor-static-root-collect-v1',
      v => v['interpretation'] = comparison()['interpretation'], v => v['raw_body'] = 'private', v => v['project_id'] = 10, v => v['source_current'] = 1,
      v => v['url'] = ORIGIN + '/', v => v['url'] = OWN + '/selected/article', v => v['current'].evidence.url = ORIGIN + '/other',
      v => v['current'].evidence.observed_at = OBSERVED, v => v['source_sha256'] = 'bad', v => v['current'].evidence.body_sha256 = null,
      v => v['current'].evidence.body_size_bytes = 131073, v => v['count_deltas'].same_origin_http = 1,
      v => v['destinations_changed'] = false, v => v['destinations_changed'] = 1,
      v => v['current'].evidence.destinations[0] = 'https://foreign.example.invalid/secret', v => v['current'].evidence.destinations[0] = ORIGIN + '/%20',
      v => v['current'].evidence.counts.same_origin_http = 2, v => v['current'].evidence.counts.href_anchors = 0,
      v => v['current'].evidence.destinations = Array(11).fill(ORIGIN + '/one'), v => v['current'].evidence.anchor_text = 'private',
      v => v['metadata_changed'] = { title: false, description: false }, v => v['headings_changed'] = true, v => v['count_deltas'].h1 = 0,
      v => v['body_changed'] = false, v => v['body_changed'] = null, v => v['previous'].job_id = 22, v => v['count_deltas'] = null,
      v => v['count_deltas'].href_anchors = true, v => v['count_deltas'].href_anchors = '0', v => v['comparable'] = 1,
      v => { v['current'].evidence.state = 'unavailable'; v['current'].evidence.reason = 'result_limit'; }];
    for (const change of changes) {
      await component.load(); api.pairValue = destinationsComparison(); change(api.pairValue); selectPair(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.previousJobId()).toBe(0);
    }
    expect(api.pairs).toEqual([]); expect(api.synthCommands).toEqual([]);
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'denial'])('clears the private page pair after late %s loss', async field => {
    savedPair(); const { component } = await screen(); selectPair(component);
    api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'denial') api.pairStatus = 403;
    };
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0); expect(api.commands).toEqual([]); expect(api.pairs).toEqual([]);
  });
  it('rechecks frozen page job status before GET and clears delivery on URI, rights, pair, refresh, route and destruction', async () => {
    savedPair(); const { component, harness } = await screen(); selectPair(component); api.rows[1].updated_at = OBSERVED;
    await component.compare(); expect(api.destinationsPairs).toEqual([]); expect(component.frozenPair()).toBeNull();
    savedPair(); await component.load();
    for (const edit of [() => component.editUrl(ORIGIN + '/other'), () => component.editOrigin(ORIGIN), () => component.editPermission('use', false), () => component.editPair('current', '21')]) {
      selectPair(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    selectPair(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull();
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    selectPair(component); const count = api.destinationsPairs.length; const reading = component.compare(); await vi.waitFor(() => expect(api.destinationsPairs.length).toBeGreaterThan(count));
    await harness.navigateByUrl('/competitor-page-destinations/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 403, body: {} }); await reading; expect(component.comparison()).toBeNull(); expect(component.error()).toBe('');
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.frozenPair()).toBeNull();
  });
});


describe('Private two saved-page reference structure', () => {
  let api: FixtureApi;
  beforeEach(() => {
    api = new FixtureApi(); api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }];
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-destinations/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { component, harness };
  }
  function select(component: CompetitorRoots, first = '21', second = '22') {
    component.editReferenceStructure(true); component.editPair('previous', first); component.editPair('current', second);
  }
  it('requires an explicit labelled choice and confirms the same exact ordered originals before inert display without commands or storage', async () => {
    api.actor = 2; api.role = 'admin'; const { component, harness } = await screen(); harness.detectChanges();
    const choice = harness.routeNativeElement!.querySelector<HTMLInputElement>('#competitor-reference-structure')!;
    expect(choice.checked).toBe(false); expect(component.referenceStructureMode()).toBe(false);
    expect(harness.routeNativeElement!.querySelector('label[for=competitor-reference-structure]')).not.toBeNull();
    await component.compare(); expect(api.structurePairs).toEqual([]);
    choice.checked = true; choice.dispatchEvent(new Event('change')); harness.detectChanges();
    component.editPair('previous', '021'); component.editPair('current', '999'); await component.compare(); expect(api.structurePairs).toEqual([]);
    component.editPair('previous', '21'); component.editPair('current', '22');
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(component.comparison()).toEqual(referenceStructure()); expect(api.structurePairs).toEqual([[21, 22], [21, 22]]);
    expect(api.destinationsPairs).toEqual([]); expect(api.catalogCalls).toBe(0); expect(api.commands).toEqual([]); expect(api.previews).toBe(0);
    const text = harness.routeNativeElement!.textContent!;
    expect(text).toContain('Reference occurrences between two saved static samples'); expect(text).toContain('unavailable rows stay null');
    expect(text).toContain(ORIGIN + '/selected/%62'); expect(text).toContain('opaque actor-bound source SHAs');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('a[href*="competitor.example.invalid"]')).toBeNull();
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    component.editReferenceStructure(false); expect(component.comparison()).toBeNull(); expect(component.previousJobId()).toBe(0);
    api.pairValue = destinationsComparison(); component.editPair('previous', '21'); component.editPair('current', '22'); await component.compare();
    expect(component.comparison()).toEqual(destinationsComparison()); expect(api.destinationsPairs).toEqual([[21, 22]]);
  });
  it('preserves equal original dates, distinct opaque SHAs, literal duplicates/variants, reversed selection and independent zero versus null rows', async () => {
    const { component } = await screen();
    for (const state of ['reverse', 'empty', 'first_unavailable', 'second_unavailable']) {
      api.structureValue = referenceStructure(); const value = api.structureValue;
      if (state === 'reverse') { value['pages'].reverse(); value['selected_uri_reference_occurrences'] = [[0, 1], [2, 0]]; }
      else {
        const index = state === 'second_unavailable' ? 1 : 0; const evidence = value['pages'][index].collection.evidence;
        if (state === 'empty') { evidence.destinations = []; evidence.counts.same_origin_http = 0; evidence.counts.href_anchors = 2; value['selected_uri_reference_occurrences'][index] = [0, 0]; }
        else { evidence.state = 'unavailable'; evidence.reason = 'result_limit'; evidence.destinations = null;
          evidence.counts = Object.fromEntries(Object.keys(evidence.counts).map(key => [key, null])); value['selected_uri_reference_occurrences'][index] = [null, null]; }
      }
      select(component, state === 'reverse' ? '22' : '21', state === 'reverse' ? '21' : '22');
      await component.compare(); expect(component.comparison()).toEqual(value);
    }
  });
  it('rejects wrong scope, family, order, private originals, URI-origin, date, coverage, cap and fabricated occurrence/null matrix shapes', async () => {
    const { component } = await screen();
    const changes: ((v: Row) => void)[] = [
      v => v['method_version'] = 'competitor-page-references-pair-v1', v => v['organization_id'] = 8, v => v['project_id'] = 10,
      v => v['source_current'] = 1, v => v['interpretation'] = 'whole_site_graph', v => v['raw_body'] = 'private',
      v => v['pages'].reverse(), v => v['pages'].pop(), v => v['pages'].push(v['pages'][0]), v => v['pages'][0].job_id = 22,
      v => v['pages'][0].source_current = false, v => v['pages'][0].collection.source_sha256 = 'bad',
      v => v['pages'][0].collection.method_version = 'competitor-static-page-collect-v1',
      v => v['pages'][0].collection.evidence.method_version = 'competitor-static-headings-v1',
      v => v['pages'][0].collection.evidence.body_size_bytes = 131073,
      v => v['pages'][0].collection.evidence.coverage = 'complete_site',
      v => v['pages'][0].collection.evidence.anchor_text = '<img src=x>',
      v => v['pages'][0].collection.evidence.counts.same_origin_http = 3,
      v => v['pages'][0].collection.observed_at = v['pages'][0].collection.evidence.observed_at = '2026-01-01T00:00:00.000000+00:00',
      v => v['pages'][0].collection.observed_at = v['pages'][0].collection.evidence.observed_at = '2099-01-01T00:00:00.000001+00:00',
      ...[ORIGIN + '/selected/b', ORIGIN + '/', OWN + '/selected/a', 'https://other.example.invalid/selected/a'].map(url => (v: Row) => {
        v['pages'][0].collection.url = v['pages'][0].collection.requested_url = v['pages'][0].collection.evidence.url = url;
      }),
      v => v['pages'][0].collection.requested_url += '/',
      v => v['pages'][0].collection.evidence.destinations = Array(11).fill(ORIGIN + '/selected/b'),
      v => v['selected_uri_reference_occurrences'][0][1] = 4, v => v['selected_uri_reference_occurrences'][0][0] = true,
      v => v['selected_uri_reference_occurrences'][0][0] = '0', v => v['selected_uri_reference_occurrences'][0][0] = null,
      v => v['selected_uri_reference_occurrences'].push([0, 0]), v => v['selected_uri_reference_occurrences'][0].push(0),
      v => v['selected_uri_reference_occurrences'] = null,
      v => { v['pages'][0].collection.evidence.state = 'unavailable'; v['pages'][0].collection.evidence.reason = 'ambiguous_markup'; },
      v => v['pages'][0].collection.source_sha256 = 'a'.repeat(24577),
    ];
    for (const change of changes) {
      await component.load(); api.structureValue = referenceStructure(); change(api.structureValue); select(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.previousJobId()).toBe(0);
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'denial'])('withholds the structure after late %s loss', async field => {
    const { component } = await screen(); select(component);
    api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'denial') api.pairStatus = 403;
    };
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.referenceStructureMode()).toBe(false); expect(api.structurePairs).toHaveLength(1); expect(api.commands).toEqual([]);
  });
  it.each(['mutation', 'denial', 'original_job'])('requires the same confirming GET and final independent history after %s', async change => {
    const { component } = await screen(); select(component);
    api.afterPair = () => {
      if (api.structurePairs.length === 2) {
        if (change === 'mutation') api.structureValue['pages'][0].collection.source_sha256 = 'e'.repeat(64);
        if (change === 'denial') api.pairStatus = 409;
        if (change === 'original_job') api.rows[0].updated_at = OBSERVED;
      }
    };
    await component.compare(); expect(api.structurePairs).toEqual([[21, 22], [21, 22]]); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
  });
  it('freezes both jobs before GET and clears on mode, URI, rights, selection, refresh, route and destruction', async () => {
    const { component, harness } = await screen(); select(component); api.rows[1].updated_at = OBSERVED;
    await component.compare(); expect(api.structurePairs).toEqual([]);
    api.rows[1].updated_at = LATER; await component.load();
    for (const edit of [() => component.editReferenceStructure(false), () => component.editUrl(ORIGIN + '/other'),
      () => component.editOrigin(ORIGIN), () => component.editPermission('use', false), () => component.editPair('current', '21')]) {
      select(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    select(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull(); expect(component.referenceStructureMode()).toBe(false);
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    select(component); const count = api.structurePairs.length; const reading = component.compare(); await vi.waitFor(() => expect(api.structurePairs.length).toBeGreaterThan(count));
    component.editReferenceStructure(false); release({ status: 200, body: { organization_id: 7, project_id: 9, structure: referenceStructure() } });
    await reading; expect(component.comparison()).toBeNull(); expect(api.structurePairs).toHaveLength(count + 1);
    api.pairPromise = new Promise<ApiResult>(resolve => release = resolve); select(component); const next = component.compare();
    await vi.waitFor(() => expect(api.structurePairs.length).toBeGreaterThan(count + 1));
    await harness.navigateByUrl('/competitor-page-destinations/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 403, body: {} }); await next; expect(component.comparison()).toBeNull(); expect(component.error()).toBe('');
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.referenceStructureMode()).toBe(false);
  });
  it('AccountApi uses only the fixed private scoped bodyless GET without CSRF bootstrap or command replay', async () => {
    const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: '' } }] });
    await TestBed.inject(AccountApi).competitorPageReferenceStructure(7, 9, 22, 21);
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][]; expect(calls).toHaveLength(1);
    expect(calls[0][0]).toContain('/organizations/7/projects/9/competitor-page-destinations/structure/?first_job_id=22&second_job_id=21');
    expect(calls[0][1]).toMatchObject({ method: 'GET', credentials: 'same-origin', cache: 'no-store' }); expect(calls[0][1].body).toBeUndefined();
    expect((calls[0][1].headers as Row)['X-CSRFToken']).toBeUndefined();
  });
});

describe('Private original heading-pair synthesis', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }]; api.pairValue = headingsComparison();
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-headings/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  async function prepare(component: CompetitorRoots) {
    await component.load(); await component.loadSyntheses(); component.editPair('previous', '21'); component.editPair('current', '22');
    component.editSynthesis('permission', true); component.editSynthesis('model', '31'); component.editSynthesis('account', '41'); component.editSynthesis('cost', '1.000001');
  }
  it('requires deliberate indexed-heading AI permission and exact source-model preview and a frozen once-only command', async () => {
    const { component, harness } = await screen(); expect(api.catalogCalls).toBe(0); expect(component.aiPermission()).toBe(false);
    await prepare(component); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('label[for=competitor-model]')).not.toBeNull();
    await component.previewSynthesis(); const preview = component.synthesisSelection()!;
    expect(preview.selection.configuration).toMatchObject({ method: 'competitor-heading-synthesis-v1', source_method: 'competitor-heading-ai-source-v1' });
    expect(preview.comparison).toEqual(headingsComparison()); expect(preview.selection_digest).toBe(await sha(preview.selection));
    await component.launchSynthesis(); expect(api.synthCommands).toHaveLength(1); expect(api.synthCommands[0]).toMatchObject(aiInput());
    expect(api.synthCommands[0]['selection_digest']).toBe(preview.selection_digest); expect(api.synthFamilies.every(f => f === 'headings')).toBe(true);
    expect(api.pairs).toEqual([]); expect(api.pagePairs).toEqual([]); expect(api.commands).toEqual([]); expect(component.pending()).toBeNull();
  });
  it('reads original heading facts and exact indexed notes separately with nullable usage, opaque provenance and escaped inert text for an independent caller', async () => {
    const { component, harness } = await screen(); api.actor = 2; await prepare(component); api.synthDetailValue = await aiDetail(true);
    api.synthRows = [api.synthDetailValue['job']]; await component.loadSyntheses(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    await component.inspectSynthesis(61); harness.detectChanges(); expect(component.synthesisEvidence()?.['comparison']).toEqual(headingsComparison());
    expect(component.synthesisDetail()?.['usage']).toEqual(api.synthDetailValue['usage']); expect(api.synthDetails).toEqual([61, 61]);
    expect(harness.routeNativeElement!.querySelector('img,script')).toBeNull(); expect(harness.routeNativeElement!.textContent).toContain('not establish verified page topics');
    expect(harness.routeNativeElement!.textContent).toContain('Unverified cited AI'); expect(api.synthCommands).toEqual([]); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('preserves empty/truncated/unavailable comparisons and permits only actual complete original positions or available state references', async () => {
    const { component } = await screen();
    for (const kind of ['empty', 'truncated', 'unavailable']) {
      api.pairValue = headingsComparison(); const c = api.pairValue, m = c['current'].evidence;
      if (kind === 'empty') { m.headings = []; m.counts = Object.fromEntries(Object.keys(m.counts).map(k => [k, 0])); c['count_deltas'] = { h1: -2, h2: -1, h3: 0, h4: 0, h5: 0, h6: -1 }; }
      if (kind === 'truncated') m.headings[0].truncated = true;
      if (kind === 'unavailable') { m.state = 'unavailable'; m.reason = 'ambiguous_markup'; m.headings = null; m.counts = Object.fromEntries(Object.keys(m.counts).map(k => [k, null])); }
      if (kind !== 'empty') { c['comparable'] = false; c['state'] = 'incomparable_unavailable_or_truncated_heading_text'; c['headings_changed'] = null; c['count_deltas'] = null; }
      await prepare(component); api.synthDetailValue = await aiDetail(true); const selection = await aiSelection(aiInput(), c);
      api.synthDetailValue['selection'] = selection; api.synthDetailValue['selection_digest'] = await sha(selection);
      const result = api.synthDetailValue['evidence'].synthesis; result.comparison = structuredClone(c); result.source_selection_digest = selection['configuration'].source_selection_digest;
      result.interpretations = [{ text: 'Review the retained original state.', reference: 'comparison_state', quote: c['state'] }]; api.synthRows = [api.synthDetailValue['job']];
      await component.loadSyntheses(); await component.inspectSynthesis(61); expect(component.synthesisEvidence()?.['comparison']).toEqual(c);
      result.interpretations = [{ text: 'Missing complete original text.', reference: 'current_heading_0', quote: 'Changed' }];
      await component.inspectSynthesis(61); expect(component.synthesisEvidence()).toBeNull();
    }
  });
  it('denies forged methods, changed original facts, invalid indexed or difference references, Unicode and note-byte expansion', async () => {
    const { component } = await screen(); const changes: ((v: Row) => void)[] = [
      v => { v['selection'].configuration.method = 'competitor-static-synthesis-v1'; },
      v => { v['evidence'].synthesis.method_version = 'competitor-static-synthesis-v1'; },
      v => { v['evidence'].synthesis.interpretation = 'verified_topics'; },
      v => { v['evidence'].synthesis.comparison.headings_changed = false; },
      v => { v['evidence'].synthesis.comparison.current.evidence.headings.reverse(); },
      v => { v['evidence'].synthesis.interpretations[0].reference = 'current_title'; },
      v => { v['evidence'].synthesis.interpretations[0].reference = 'current_heading_9'; },
      v => { v['evidence'].synthesis.interpretations[0].reference = 'current_heading_00'; },
      v => { v['evidence'].synthesis.interpretations[0].quote = 'not original'; },
      v => { v['evidence'].synthesis.interpretations[0].text = 'invisible\u200bcontrol'; },
      v => { v['evidence'].synthesis.interpretations = Array.from({length: 10}, () => ({ text: '😀'.repeat(500), reference: 'body_changed', quote: 'true' })); },
    ];
    for (const change of changes) { await prepare(component); api.synthDetailValue = await aiDetail(true); change(api.synthDetailValue);
      api.synthRows = [api.synthDetailValue['job']]; await component.loadSyntheses(); await component.inspectSynthesis(61);
      expect(component.synthesisEvidence()).toBeNull(); expect(component.synthesisDetail()).toBeNull(); }
  });
  it('reconciles uncertain commands with only own-key GET after model loss and never replays a POST', async () => {
    const { component } = await screen(); await prepare(component); await component.previewSynthesis(); api.synthUnknown = true;
    await component.launchSynthesis(); const key = component.pending()!.key; api.modelRows = []; api.accountRows = [];
    await component.launchSynthesis(); await component.reconcile(); expect(api.synthLookups).toEqual([key]); expect(api.synthCommands).toHaveLength(1); expect(component.pending()).toBeNull();
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated', 'saved_job', 'model', 'account', 'denial'])('clears preview after final %s loss', async field => {
    const { component } = await screen(); await prepare(component); api.afterSynthesisPreview = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'synthetic_demo'; if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[1].cancel_requested = true; if (field === 'model') api.modelRows = []; if (field === 'account') api.accountRows = [];
      if (field === 'denial') api.deny = true;
    }; await component.previewSynthesis(); expect(component.synthesisSelection()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(api.synthCommands).toEqual([]);
  });
  it('clears private state on input refresh route destruction and ignores stale denial', async () => {
    const { component, harness } = await screen(); await prepare(component); api.synthDetailValue = await aiDetail(true); api.synthRows = [api.synthDetailValue['job']]; await component.loadSyntheses();
    let resolve!: (v: ApiResult) => void; api.synthDetailPromise = new Promise(r => { resolve = r; }); const reading = component.inspectSynthesis(61);
    await vi.waitFor(() => expect(api.synthDetails).toEqual([61])); component.editSynthesis('cost', '2'); resolve({status: 403, body: {}}); await reading;
    expect(component.ready()).toBe(true); expect(component.synthesisDetail()).toBeNull(); api.synthDetailPromise = null;
    await prepare(component); await component.previewSynthesis(); expect(component.synthesisSelection()).not.toBeNull(); await component.load(); expect(component.synthesisSelection()).toBeNull();
    await prepare(component); await component.previewSynthesis(); await harness.navigateByUrl('/competitor-roots/7/10', CompetitorRoots); await harness.fixture.whenStable();
    expect(component.models()).toEqual([]); expect(component.pending()).toBeNull(); harness.fixture.destroy(); expect(component.aiPermission()).toBe(false);
  });
});

it('AccountApi uses fixed heading synthesis routes with GET-only own-key and exact-job lookup and same-origin no-store CSRF JSON commands', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); TestBed.configureTestingModule({providers: [{provide: DOCUMENT, useValue: {defaultView: {fetch: fetcher}, cookie: 'csrftoken=fixture'}}]});
  const api = TestBed.inject(AccountApi); await api.competitorHeadingSyntheses(7,9); await api.competitorHeadingSyntheses(7,9,undefined,undefined,'same.key');
  await api.competitorHeadingSyntheses(7,9,undefined,61); await api.competitorHeadingSyntheses(7,9,aiInput(),undefined,undefined,true);
  await api.competitorHeadingSyntheses(7,9,{idempotency_key:'same.key'}); await api.competitorHeadingSyntheses(7,9,{},61);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-heading-syntheses/'));
  expect(calls.map(([url])=>url.split('/competitor-heading-syntheses/')[1])).toEqual(['','?idempotency_key=same.key','61/','selection/','','61/']);
  expect(calls.slice(0,3).every(([,o])=>o.method==='GET' && o.body===undefined)).toBe(true);
  expect(calls.slice(3).every(([,o])=>o.method==='POST' && (o.headers as Row)['X-CSRFToken']==='fixture')).toBe(true);
  expect(calls.every(([url,o])=>url.includes('/organizations/7/projects/9/') && o.credentials==='same-origin' && o.cache==='no-store')).toBe(true);
});

describe('Private selected competitor date declarations', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-dates/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, url = ORIGIN + '/selected/article') {
    component.editOrigin(ORIGIN); component.editUrl(url);
    component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  it('uses labelled empty exact URI and three unchecked rights, fixed frozen date command and separate pair controls with no AI promotion', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen(); harness.detectChanges();
    const native = harness.routeNativeElement!;
    expect(native.querySelector('h1')!.textContent).toContain('article date declarations');
    expect(native.querySelector<HTMLInputElement>('#competitor-page-url')!.value).toBe('');
    expect(native.querySelector('label[for=competitor-page-url]')).not.toBeNull();
    const rights = [...native.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(rights).toHaveLength(3); expect(rights.every(input => !input.checked && input.required && !!input.closest('label'))).toBe(true);
    expect(native.querySelector('#competitor-previous')).not.toBeNull(); expect(native.querySelector('#competitor-model')).toBeNull();
    await component.compare();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(component.previousJobId()).toBe(0); expect(component.frozenPair()).toBeNull(); expect(api.catalogCalls).toBe(0);
    expect([api.datesPairs, api.pairs, api.pagePairs, api.destinationsPairs, api.headingsPairs, api.linksPairs, api.schemaPairs, api.synthCommands, api.synthDetails, api.synthCancels].every(rows => rows.length === 0)).toBe(true);
    declare(component); await component.preview(); const frozen = structuredClone(component.selection()!);
    expect(frozen.selection['method']).toBe('competitor-page-dates-collect-v1'); expect(frozen.selection.binding['url']).toBe(ORIGIN + '/selected/article');
    expect(frozen.selection_digest).toBe(await sha(frozen.selection));
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.launch();
    expect(api.commands).toEqual([{ origin: ORIGIN, url: ORIGIN + '/selected/article', collection_permission: true, use_permission: true, storage_permission: true,
      idempotency_key: expect.any(String), selection_digest: frozen.selection_digest }]);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore(); expect(api.familyCalls.every(family => family === 'dates')).toBe(true);
  });
  it('keeps future, invalid, empty and duplicate date text literal and escaped with original opaque source and timestamps', async () => {
    api.actor = 2; api.role = 'admin'; api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    await component.inspect(21); expect(component.evidence()).toEqual(datesEvidence()); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain('2099-01-01'); expect(harness.routeNativeElement!.textContent).toContain('publishing cadence');
    expect(harness.routeNativeElement!.querySelector('img, script')).toBeNull();
    for (const value of ['not a calendar date', '', '🙂'.repeat(80), '\ufeffliteral\ufeff']) {
      api.detailValue = datesEvidence(); api.detailValue['collection'].evidence.declarations[0].value = value;
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
    api.detailValue = datesEvidence(); api.detailValue['collection'].evidence.declarations = [];
    await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    for (const reason of ['ambiguous_markup', 'element_limit', 'declaration_limit', 'result_limit']) {
      api.detailValue = datesEvidence(); Object.assign(api.detailValue['collection'].evidence, { state: 'unavailable', reason, declarations: null });
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
  });
  it('rejects cross-family and malformed declaration/provenance DTOs before private display', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    const mutations: ((row: Row) => void)[] = [
      ...[evidence, schemaEvidence, linksEvidence, pageEvidence, headingsEvidence, destinationsEvidence].map(factory => (row: Row) => row['collection'] = factory()['collection']),
      row => row['collection'].evidence.declarations[0].property = 'datePublished', row => row['collection'].evidence.declarations[0].property = ['article:published_time'],
      row => row['collection'].evidence.declarations[0].value = 2099, row => row['collection'].evidence.declarations[0].value = 'x'.repeat(81),
      row => row['collection'].evidence.declarations[0].value = 'a\u0085b', row => row['collection'].evidence.declarations[0].value = '\ud800',
      row => row['collection'].evidence.declarations[0].truncated = 1,
      row => Object.assign(row['collection'].evidence.declarations[0], { value: '', truncated: true }),
      row => row['collection'].evidence.declarations[0].parsed_date = '2099-01-01',
      row => row['collection'].evidence.declarations = Array(11).fill({ property: 'article:published_time', value: '', truncated: false }),
      row => row['collection'].evidence.declarations = null, row => row['collection'].evidence.reason = 'valid_date',
      row => Object.assign(row['collection'].evidence, { state: 'unavailable', reason: 'ambiguous_markup' }),
      row => row['collection'].evidence.coverage = 'whole_site', row => row['collection'].evidence.interpretation = 'freshness',
      row => row['collection'].evidence.counts = {}, row => row['collection'].evidence.body_size_bytes = 131073,
      row => row['collection'].evidence.body_sha256 = 'bad', row => row['collection'].evidence.excluded_containers = [],
      row => row['collection'].evidence.url = ORIGIN + '/other', row => row['collection'].evidence.observed_at = LATER,
      row => row['collection'].source_sha256 = 'bad', row => row['source_current'] = false,
    ];
    for (const mutate of mutations) {
      await component.load(); api.detailValue = datesEvidence(); mutate(api.detailValue); await component.inspect(21);
      expect(component.evidence()).toBeNull(); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('withholds late date text and clears state after %s loss', async field => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    api.afterDetail = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
    };
    await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false); expect(component.pending()).toBeNull();
  });
  it('denies invalid exact URIs, missing rights and altered or stale source preview before any POST', async () => {
    const { component } = await screen();
    for (const url of ['', ORIGIN + '/', OWN + '/a', ORIGIN + '/a?', ORIGIN + '/a#', ORIGIN + '/%0a', ORIGIN + '/back\\slash',
      'http://competitor.example.invalid/a', 'https://competitor.example.invalid:443/a', 'https://user:secret@competitor.example.invalid/a']) {
      declare(component, url); await component.preview(); expect(component.selection()).toBeNull();
    }
    expect(api.previews).toBe(0);
    declare(component); component.editPermission('storage', false); await component.preview(); expect(api.previews).toBe(0);
    for (const mutate of [(row: Row) => row['selection'].method = 'competitor-page-headings-collect-v1',
      (row: Row) => row['selection'].binding.url = ORIGIN + '/other', (row: Row) => row['selection'].binding.method_version = 'competitor-source-v1']) {
      declare(component); api.previewChange = mutate; await component.preview(); expect(component.selection()).toBeNull();
    }
    api.previewChange = null; declare(component); await component.preview(); api.afterPreview = () => ++api.revision;
    await component.launch(); expect(api.commands).toEqual([]); expect(component.pending()).toBeNull();
  });
  it('uses only own-key GET for unknown date commands and clears uncertainty on source edits and actor loss', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()!); expect(frozen.data['url']).toBe(ORIGIN + '/selected/article');
    await component.reconcile(); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([frozen.key]); expect(component.pending()).toBeNull();
    await component.load(); declare(component); await component.preview(); api.drop = true; await component.launch();
    const count = api.commands.length; await component.reconcile(); expect(api.commands).toHaveLength(count); expect(component.pending()).not.toBeNull();
    component.editUrl(ORIGIN + '/other'); expect(component.pending()).toBeNull(); expect(component.collectionPermission()).toBe(false);
    api.drop = false; declare(component); await component.preview(); await component.launch(); ++api.actor; await component.reconcile();
    expect(component.pending()).toBeNull(); expect(component.origins()).toEqual([]); expect(component.url()).toBe('');
  });
  it('cancels only through the date family and discards late detail after project switch or destruction', async () => {
    api.rows = [job()]; const { harness, component } = await screen(); await component.cancel(21); expect(api.cancels).toEqual([21]);
    api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    let release!: (result: ApiResult) => void; api.detailPromise = new Promise<ApiResult>(resolve => release = resolve);
    const reading = component.inspect(21); await vi.waitFor(() => expect(api.details).toContain(21));
    await harness.navigateByUrl('/competitor-page-dates/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: datesEvidence() } });
    await reading; expect(component.evidence()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.url()).toBe('');
    expect(api.familyCalls.every(family => family === 'dates')).toBe(true);
  });
});

it('AccountApi date commands use fixed scoped paths and private same-origin CSRF/GET options', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorPageDates(7, 9); await api.competitorPageDates(7, 9, undefined, undefined, 'dates.key'); await api.competitorPageDates(7, 9, undefined, 21);
  await api.competitorPageDates(7, 9, { origin: ORIGIN, url: ORIGIN + '/selected/article' }, undefined, undefined, true);
  await api.competitorPageDates(7, 9, { idempotency_key: 'dates.key' }); await api.competitorPageDates(7, 9, {}, 21);
  await api.competitorPageDatesComparison(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-page-dates/'));
  expect(calls.map(([url]) => url.split('/competitor-page-dates/')[1])).toEqual(['', '?idempotency_key=dates.key', '21/', 'selection/', '', '21/', 'comparison/?previous_job_id=21&current_job_id=22']);
  expect(calls.slice(0, 3).every(([, options]) => options.method === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3, 6).every(([, options]) => options.method === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls[6][1].method).toBe('GET'); expect(calls[6][1].body).toBeUndefined();
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});

describe('Private original article date declaration pairs', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }];
    api.pairValue = datesComparison(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-dates/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function select(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('requires two deliberate saved jobs and retains exact original literal order, timestamps, body and opaque actor SHA without persistence or model authority', async () => {
    api.actor = 2; api.role = 'admin'; const { harness, component } = await screen();
    await component.compare(); expect(api.datesPairs).toEqual([]);
    component.editPair('previous', '021'); component.editPair('current', '999'); await component.compare(); expect(api.datesPairs).toEqual([]);
    select(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(api.datesPairs).toEqual([[21, 22]]); expect(component.comparison()).toEqual(datesComparison()); expect(component.frozenPair()).not.toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('publishing cadence'); expect(harness.routeNativeElement!.textContent).toContain('2099-01-01');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull(); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(api.catalogCalls).toBe(0); expect(api.synthFamilies).toEqual([]); expect(api.commands).toEqual([]);
    expect([api.pairs, api.pagePairs, api.headingsPairs, api.destinationsPairs, api.linksPairs, api.schemaPairs].every(rows => !rows.length)).toBe(true);
  });
  it.each(['empty', 'empty-value', 'unavailable', 'truncated'])('preserves %s declarations as known or whole incomparable without a calendar or count delta', async kind => {
    const { component } = await screen(); const c = api.pairValue, before = c['previous'].evidence, after = c['current'].evidence;
    if (kind === 'empty' || kind === 'empty-value') {
      before.declarations = []; after.declarations = kind === 'empty' ? [] : [{ property: 'article:published_time', value: '', truncated: false }];
      c['declarations_changed'] = kind !== 'empty';
    } else {
      if (kind === 'unavailable') { before.state = 'unavailable'; before.reason = 'ambiguous_markup'; before.declarations = null; }
      else before.declarations[0].truncated = true;
      c['comparable'] = false; c['state'] = 'incomparable_unavailable_or_truncated_article_date_declarations'; c['declarations_changed'] = null;
    }
    select(component); await component.compare(); expect(component.comparison()).toEqual(c); expect(component.comparison()).not.toHaveProperty('count_deltas');
  });
  it('recomputes order/property/value equality independently of body equality, preserving unvalidated date text', async () => {
    const { component } = await screen();
    for (const kind of ['same', 'body', 'order', 'property', 'literal']) {
      api.pairValue = datesComparison(); const c = api.pairValue, before = c['previous'].evidence, after = c['current'].evidence;
      if (kind !== 'order') after.declarations = structuredClone(before.declarations);
      if (kind === 'same') { after.body_sha256 = before.body_sha256; c['body_changed'] = false; }
      if (kind === 'same' || kind === 'body') c['declarations_changed'] = false;
      if (kind === 'property') after.declarations[0].property = 'article:modified_time';
      if (kind === 'literal') after.declarations[0].value = 'not a calendar date';
      select(component); await component.compare(); expect(component.comparison()).toEqual(c);
    }
  });
  it('rejects old family, extra fields, mismatched original scope and forged literal differences before display', async () => {
    const { harness, component } = await screen();
    const changes: ((value: Row) => void)[] = [
      v => v['method_version'] = 'competitor-page-headings-comparison-v1', v => v['parser_method'] = 'competitor-static-metadata-v1',
      v => v['collection_method'] = 'competitor-page-headings-collect-v1', v => v['interpretation'] = 'verified_freshness',
      v => v['organization_id'] = 8, v => v['project_id'] = 10, v => v['source_current'] = false, v => v['source_sha256'] = 'bad',
      v => v['previous'].job_id = 22, v => v['current'].evidence.observed_at = OBSERVED, v => v['url'] = ORIGIN + '/',
      v => v['current'].evidence.url = ORIGIN + '/other', v => v['previous'].robots = 'approved',
      v => v['count_deltas'] = {}, v => v['metadata_changed'] = {}, v => v['declarations_changed'] = false, v => v['declarations_changed'] = 1,
      v => v['body_changed'] = false, v => v['comparable'] = 1, v => v['state'] = 'verified_dates',
      v => v['current'].evidence.declarations[0].value = 'x'.repeat(81), v => v['current'].evidence.declarations[0].property = 'datePublished',
      v => v['current'].evidence.declarations[0].truncated = true, v => v['current'].evidence.declarations[0].parsed_date = '2099-01-01',
      v => v['current'].evidence.declarations = Array(11).fill({ property: 'article:published_time', value: '', truncated: false }),
      v => v['current'].evidence.body_size_bytes = 131073, v => v['current'].evidence.coverage = 'whole_site',
    ];
    for (const change of changes) {
      await component.load(); api.pairValue = datesComparison(); change(api.pairValue); select(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('clears both private originals on post-comparison %s loss without any command replay', async field => {
    const { component } = await screen(); api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
    };
    select(component); await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(component.pending()).toBeNull(); expect(api.commands).toEqual([]); expect(api.synthFamilies).toEqual([]);
  });
  it('withholds final denied pair and clears on source, rights, pair edits or refresh', async () => {
    const { component } = await screen(); select(component); api.pairStatus = 403; await component.compare(); expect(component.comparison()).toBeNull();
    api.pairStatus = 200; await component.load();
    for (const edit of [() => component.editUrl(ORIGIN + '/other'), () => component.editOrigin(ORIGIN), () => component.editPermission('use', false), () => component.editPair('current', '21')]) {
      select(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    select(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull();
  });
  it('discards a late old project comparison and clears state on destruction', async () => {
    const { harness, component } = await screen(); let release!: (result: ApiResult) => void;
    api.pairPromise = new Promise<ApiResult>(resolve => release = resolve); select(component); const reading = component.compare();
    await vi.waitFor(() => expect(api.datesPairs).toEqual([[21, 22]]));
    await harness.navigateByUrl('/competitor-page-dates/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, comparison: datesComparison() } }); await reading;
    expect(component.comparison()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.frozenPair()).toBeNull();
  });
});


describe('Private selected competitor Lighthouse lab workflow', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-lighthouse/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, device = 'mobile') {
    component.editOrigin(ORIGIN); component.editUrl(ORIGIN + '/selected/article'); component.editStrategy(device); component.editProcessing(true);
    component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  it.each(['en', 'tr'] as const)('uses labelled native mobile default, four unchecked rights and exact fixed frozen command with deliberate pair and no AI in %s', async (language) => {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    const { harness, component } = await screen(); harness.detectChanges(); const native = harness.routeNativeElement!;
    expect(native.querySelector('h1')!.textContent).toBe(component.t('Selected competitor Lighthouse lab sample'));
    expect(native.querySelector<HTMLSelectElement>('#competitor-device')!.value).toBe('mobile');
    expect(native.querySelector('label[for=competitor-device]')).not.toBeNull();
    const rights = [...native.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(rights).toHaveLength(4); expect(rights.every(input => !input.checked && input.required && input.closest('label'))).toBe(true);
    expect(native.querySelector('#competitor-previous')).not.toBeNull(); expect(native.querySelector('#competitor-model')).toBeNull();
    await component.compare(); await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis();
    expect(api.catalogCalls).toBe(0); expect(api.pagePairs).toEqual([]); expect(api.synthCommands).toEqual([]);
    declare(component, 'desktop'); await component.preview(); const frozen = structuredClone(component.selection()!);
    expect(frozen.selection_digest).toBe(await sha(frozen.selection));
    expect((frozen.selection.binding['source'] as Row)['page_source']['url']).toBe(ORIGIN + '/selected/article');
    harness.detectChanges(); const device = native.querySelector<HTMLSelectElement>('#competitor-device')!;
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(native.querySelector('#competitor-device')).toBe(device); expect(device.value).toBe('desktop');
    expect(rights.every(input => input.checked)).toBe(true); expect(component.selection()).toEqual(frozen); expect(api.commands).toEqual([]);
    component.productLanguage.set(language); harness.detectChanges();
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.launch();
    expect(api.commands).toEqual([{ origin: ORIGIN, url: ORIGIN + '/selected/article', strategy: 'desktop', provider_processing_permission: true,
      collection_permission: true, use_permission: true, storage_permission: true, idempotency_key: expect.any(String), selection_digest: frozen.selection_digest }]);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore(); expect(api.familyCalls.every(value => value === 'lighthouse')).toBe(true);
  });
  it('retains raw offset provider time, local microsecond receipt, nullable scores/units/zero and whole unavailable without field claims', async () => {
    api.actor = 2; api.role = 'admin'; api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    await component.inspect(21); expect(component.evidence()).toEqual(labEvidence()); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain('Provider time may predate this request');
    expect(harness.routeNativeElement!.querySelector('img, script')).toBeNull();
    for (const strategy of ['mobile', 'desktop']) {
      api.detailValue = labEvidence(ORIGIN, strategy); await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
    api.detailValue = labEvidence(); Object.assign(api.detailValue['collection'].evidence, { state: 'unavailable', reason: 'runtime_failed', lab: null });
    await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
  });
  it('rejects malformed nested lab DTOs and all seven static capture shapes before private display', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    const mutations: ((row: Row) => void)[] = [
      ...[evidence, schemaEvidence, linksEvidence, pageEvidence, headingsEvidence, destinationsEvidence, datesEvidence].map(factory => (row: Row) => row['collection'] = factory()['collection']),
      row => row['collection'].strategy = ['mobile'], row => row['collection'].robots = ['available'], row => row['collection'].selection_sha256 = 'bad',
      row => row['collection'].request_started_at = LATER, row => row['collection'].evidence.received_at = DATE.slice(0,-6) + 'Z',
      row => row['collection'].evidence.response_size_bytes = 2097153, row => row['collection'].evidence.provider_reported_at = '2099-01-01T00:00:00Z',
      row => row['collection'].evidence.provider_reported_at = '2025-12-31T03:00:00', row => row['collection'].evidence.provider_reported_at = '2025-02-30T00:00:00Z',
      row => row['collection'].evidence.lab.observed_at = '2025-12-31T00:00:00+00:00', row => row['collection'].evidence.lab.final_url = ORIGIN + '/other',
      row => row['collection'].evidence.lab.lighthouse_version = '<img src=x onerror=alert(1)>', row => row['collection'].evidence.lab.scores.seo = true,
      row => row['collection'].evidence.lab.scores.performance = 1.1, row => row['collection'].evidence.lab.scores.seo = Infinity,
      row => row['collection'].evidence.lab.audits['cumulative-layout-shift'].unit = 'ms', row => row['collection'].evidence.lab.audits['speed-index'].value = 0,
      row => row['collection'].evidence.lab.audits['largest-contentful-paint'].value = -1, row => row['collection'].evidence.lab.field_data = 'p75',
      row => row['collection'].evidence.raw_body = 'secret', row => Object.assign(row['collection'].evidence, { state: 'unavailable', reason: 'runtime_failed' }),
      row => row['source_current'] = false,
    ];
    for (const mutate of mutations) { await component.load(); api.detailValue = labEvidence(); mutate(api.detailValue); await component.inspect(21); expect(component.evidence()).toBeNull(); }
  });
  it('checks exact nested preparation hashes, current key reference, processing rights and source before POST', async () => {
    const { component } = await screen(); declare(component); component.editProcessing(false); await component.preview(); expect(api.previews).toBe(0);
    for (const mutate of [(row: Row) => row['selection'].binding.source.strategy = 'desktop',
      (row: Row) => row['selection'].binding.source.provider_processing_permission = 1,
      (row: Row) => row['selection'].binding.performance_credential.state = 'revoked', (row: Row) => row['selection'].binding.performance_credential.revision = 'future',
      (row: Row) => row['selection'].binding.source.source_sha256 = 'a'.repeat(64), (row: Row) => row['selection'].binding.selection_sha256 = 'b'.repeat(64),
      (row: Row) => row['selection'].binding.source.page_source.url = ORIGIN + '/other']) {
      declare(component); api.previewChange = mutate; await component.preview(); expect(component.selection()).toBeNull();
    }
    api.previewChange = null; declare(component); api.labKeyRevision = '2026-01-01T00:00:00+00:00'; await component.preview(); expect(component.selection()).not.toBeNull();
    api.labKeyRevision = OBSERVED; await component.launch(); expect(api.commands).toEqual([]); expect(component.pending()).toBeNull();
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('withholds late lab evidence and clears state after %s loss', async field => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    api.afterDetail = () => { if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false; };
    await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false); expect(component.pending()).toBeNull();
  });
  it('reconciles only frozen own-key GET, clears uncertainty on device/processing edits and cancels through fixed family', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()!); await component.reconcile(); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([frozen.key]);
    await component.load(); declare(component); await component.preview(); api.drop = true; await component.launch(); const count = api.commands.length;
    await component.reconcile(); expect(api.commands).toHaveLength(count); expect(component.pending()).not.toBeNull();
    component.editStrategy('desktop'); expect(component.pending()).toBeNull(); expect(component.processingPermission()).toBe(false);
    api.drop = false; api.uncertain = false; api.rows = [job()]; await component.load(); await component.cancel(21); expect(api.cancels).toEqual([21]);
    expect(api.familyCalls.every(value => value === 'lighthouse')).toBe(true);
  });
  it('clears acknowledged commands and delivered private evidence when the current credential fence changes', async () => {
    const { component } = await screen(); declare(component); await component.preview();
    api.afterPost = () => api.labKeyRevision = OBSERVED; await component.launch();
    expect(api.commands).toHaveLength(1); expect(component.pending()).toBeNull(); expect(component.selected()).toBeNull(); expect(component.ready()).toBe(false);
    api.afterPost = null; await component.load(); declare(component); await component.preview();
    api.afterPost = () => api.previewChange = row => row['selection'].binding.performance_credential.state = 'revoked';
    await component.launch(); expect(api.commands).toHaveLength(2); expect(component.pending()).toBeNull(); expect(component.ready()).toBe(false);
    api.afterPost = null; api.previewChange = null; api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    api.afterDetail = () => api.deny = true; await component.inspect(21);
    expect(component.evidence()).toBeNull(); expect(component.pending()).toBeNull(); expect(component.ready()).toBe(false);
    expect(api.details).toEqual([21]); // The second owning API GET denied before producing another detail.
  });
  it('discards late lab reply after a project switch and destruction', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    let release!: (value: ApiResult) => void; api.detailPromise = new Promise(resolve => release = resolve);
    const reading = component.inspect(21); await vi.waitFor(() => expect(api.details).toContain(21));
    await harness.navigateByUrl('/competitor-lighthouse/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: labEvidence() } });
    await reading; expect(component.evidence()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.processingPermission()).toBe(false);
  });
});

it('AccountApi Lighthouse commands keep scoped fixed paths, same-origin CSRF POST and bodyless private GET', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorLighthouse(7,9); await api.competitorLighthouse(7,9,undefined,undefined,'lab.key'); await api.competitorLighthouse(7,9,undefined,21);
  await api.competitorLighthouse(7,9,{ strategy: 'mobile' },undefined,undefined,true); await api.competitorLighthouse(7,9,{ idempotency_key: 'lab.key' }); await api.competitorLighthouse(7,9,{},21);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-lighthouse/'));
  expect(calls.map(([url]) => url.split('/competitor-lighthouse/')[1])).toEqual(['','?idempotency_key=lab.key','21/','selection/','','21/']);
  expect(calls.slice(0,3).every(([,options]) => options.method === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3).every(([,options]) => options.method === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});


describe('Original Lighthouse pair native arithmetic', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); api.pairValue = labComparison(); api.rows = [{ ...job(), status: 'succeeded' }, { ...job(), id: 22, updated_at: LATER, status: 'succeeded' }].reverse();
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-lighthouse/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function choose(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('deliberately reads and confirms exactly both originals by GET with nullable arithmetic and no collection or AI', async () => {
    api.actor = 2; api.role = 'admin'; const { harness, component } = await screen(); choose(component); await component.compare();
    expect(component.comparison()).toEqual(labComparison()); expect(api.labPairs).toEqual([[21,22],[21,22]]); expect(api.commands).toEqual([]);
    expect(api.pagePairs).toEqual([]); expect(api.synthCommands).toEqual([]); expect(api.catalogCalls).toBe(0);
    harness.detectChanges(); expect(harness.routeNativeElement!.textContent).toContain('not a controlled or representative benchmark');
    expect(harness.routeNativeElement!.querySelector('img,script')).toBeNull();
  });
  it('rejects incompatible versions/times and forged nullable deltas before private display', async () => {
    const { component } = await screen();
    for (const mutate of [(row: Row) => row['score_deltas'].performance = 0.25, (row: Row) => row['score_deltas'].seo = 0,
      (row: Row) => row['audit_deltas']['cumulative-layout-shift'].unit = 'ms', (row: Row) => row['current'].evidence.lab.lighthouse_version = '13.0.0',
      (row: Row) => row['current'].evidence.provider_reported_at = row['previous'].evidence.provider_reported_at,
      (row: Row) => row['previous'].request_started_at = LATER, (row: Row) => row['selection_sha256'] = 'bad',
      (row: Row) => row['source_current'] = false, (row: Row) => row['previous'].evidence.lab.lighthouse_version = '<img src=x onerror=alert(1)>']) {
      await component.load(); api.pairValue = labComparison(); mutate(api.pairValue); choose(component); await component.compare(); expect(component.comparison()).toBeNull();
    }
  });
  it('retains honest whole incompatibility reasons and known-zero nullable differences', async () => {
    const { component } = await screen();
    for (const kind of ['runtime', 'version', 'cached', 'unknown']) {
      await component.load(); api.pairValue = labComparison(); const row = api.pairValue, item = row['current'].evidence;
      if (kind === 'runtime') Object.assign(item, { state: 'unavailable', reason: 'runtime_failed', lab: null });
      else if (kind === 'version') item.lab.lighthouse_version = '13.0.0';
      else if (kind === 'unknown') item.lab.lighthouse_version = 'unknown';
      else { item.provider_reported_at = row['previous'].evidence.provider_reported_at; item.lab.observed_at = row['previous'].evidence.lab.observed_at; }
      row['state'] = 'incomparable_lab_samples'; row['reason'] = kind === 'runtime' ? 'lab_unavailable' : kind === 'cached' ? 'provider_report_time_not_increasing' : 'lighthouse_version_unavailable_or_changed';
      Object.keys(row['score_deltas']).forEach(key => row['score_deltas'][key] = null); Object.values(row['audit_deltas']).forEach(item => (item as Row)['value'] = null);
      choose(component); await component.compare(); expect(component.comparison()).toEqual(row);
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('withholds original pair and clears frozen state after %s loss', async field => {
    const { component } = await screen();
    api.afterPair = () => { if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false; };
    choose(component); await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.pending()).toBeNull(); expect(component.ready()).toBe(false);
  });
  it('drops late pair responses after project switch and component destruction', async () => {
    const { harness, component } = await screen(); let release!: (value: ApiResult) => void;
    api.pairPromise = new Promise(resolve => release = resolve); choose(component); const reading = component.compare();
    await vi.waitFor(() => expect(api.labPairs).toEqual([[21,22]]));
    await harness.navigateByUrl('/competitor-lighthouse/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, comparison: labComparison() } }); await reading;
    expect(component.comparison()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.frozenPair()).toBeNull();
  });
  it('clears late key-reference denial and altered confirmation without POST replay', async () => {
    const { component } = await screen(); let calls = 0;
    api.afterPair = () => { if (++calls === 2) api.deny = true; }; choose(component); await component.compare();
    expect(component.comparison()).toBeNull(); expect(component.ready()).toBe(false); expect(api.commands).toEqual([]);
    api.afterPair = null; api.deny = false; await component.load(); calls = 0;
    api.afterPair = () => { if (++calls === 2) api.pairValue['current'].evidence.response_sha256 = 'f'.repeat(64); };
    choose(component); await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
  });
});

it('AccountApi Lighthouse pair uses exact private bodyless GET with scoped saved IDs', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi); await api.competitorLighthouseComparison(7,9,21,22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-lighthouse/comparison/'));
  expect(calls).toHaveLength(1); expect(calls[0][0]).toContain('/organizations/7/projects/9/competitor-lighthouse/comparison/?previous_job_id=21&current_job_id=22');
  expect(calls[0][1].method).toBe('GET'); expect(calls[0][1].body).toBeUndefined(); expect(calls[0][1].credentials).toBe('same-origin'); expect(calls[0][1].cache).toBe('no-store');
});

describe('Private single-heading topic hypotheses', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    api.rows = [{ ...job(), status: 'succeeded' }];
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-heading-topics/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  async function prepare(component: CompetitorRoots) {
    await component.loadSyntheses(); component.editTopicJob('21'); component.editSynthesis('permission', true);
    component.editSynthesis('model', '31'); component.editSynthesis('account', '41'); component.editSynthesis('cost', '1.000001');
  }
  async function retained(component: CompetitorRoots) {
    api.synthDetailValue = await topicDetail(); api.synthRows = [api.synthDetailValue['job']]; await component.loadSyntheses();
  }
  it('previews one original and freezes only the explicit single-source command without a comparison', async () => {
    const { component, harness } = await screen(); expect(component.aiPermission()).toBe(false); await prepare(component); harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('label[for=competitor-topic-source]')).not.toBeNull();
    await component.previewSynthesis(); const preview = component.topicSelection()!;
    expect(preview.selection.input).toEqual(topicInput()); expect(preview.source.observation).toEqual(headingsEvidence());
    expect(preview.selection_digest).toBe(await sha(preview.selection)); expect(component.synthesisSelection()).toBeNull();
    await component.launchSynthesis(); expect(api.synthCommands).toHaveLength(1); expect(api.synthCommands[0]).toMatchObject(topicInput());
    expect(api.synthCommands[0]).not.toHaveProperty('previous_job_id'); expect(api.synthCommands[0]).not.toHaveProperty('current_job_id');
    expect(api.synthFamilies.every(family => family === 'topics')).toBe(true); expect(api.headingsPairs).toEqual([]); expect(api.pairs).toEqual([]);
    expect(api.commands).toEqual([]); expect(component.pending()).toBeNull();
  });
  it('renders original facts and indexed unverified hypotheses separately for an independent reader with inert strings and nullable usage', async () => {
    const { component, harness } = await screen(); api.actor = 2; await component.load(); await retained(component);
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.inspectSynthesis(61); harness.detectChanges();
    expect(component.synthesisEvidence()?.['observation']).toEqual(headingsEvidence()); expect(component.synthesisEvidence()?.['topics']).toEqual(api.synthDetailValue!['evidence'].synthesis['topics']);
    expect((component.synthesisDetail()?.['usage'] as Row)['reported_cost_usd']).toBeNull(); expect(api.synthDetails).toEqual([61, 61]);
    expect(harness.routeNativeElement!.querySelector('img,script')).toBeNull(); expect(harness.routeNativeElement!.textContent).toContain('Unverified indexed topic hypotheses');
    expect(api.synthCommands).toEqual([]); expect(api.headingsPairs).toEqual([]); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it('accepts matching quotes without pretending to verify the label meaning', async () => {
    const { component } = await screen(); await retained(component);
    api.synthDetailValue!['evidence'].synthesis['topics'] = [{ label: 'An unrelated unverified label', reference: 'heading_2', quote: 'Same' }];
    await component.inspectSynthesis(61); expect(component.synthesisEvidence()?.['topics']).toEqual(api.synthDetailValue!['evidence'].synthesis['topics']);
  });
  for (const kind of ['truncated', 'empty', 'unavailable']) it(`denies ${kind} uncitable single inputs before preview`, async () => {
    const { component } = await screen(); await prepare(component); api.detailValue = headingsEvidence(); const facts = api.detailValue['collection'].evidence;
    if (kind === 'truncated') facts.headings.forEach((row: Row) => row['truncated'] = true);
    if (kind === 'empty') { facts.headings = []; facts.counts = { h1: 0, h2: 0, h3: 0, h4: 0, h5: 0, h6: 0 }; }
    if (kind === 'unavailable') { facts['state'] = 'unavailable'; facts.reason = 'ambiguous_markup'; facts.headings = null; facts.counts = { h1: null, h2: null, h3: null, h4: null, h5: null, h6: null }; }
    await component.previewSynthesis(); expect(component.topicSelection()).toBeNull(); expect(api.synthPreviews).toBe(0); expect(api.synthCommands).toEqual([]);
  });
  for (const [kind, mutate] of Object.entries({
    empty: (s: Row): void => { s['topics'] = []; },
    reference: (s: Row): void => { s['topics'][0].reference = 'heading_9'; }, truncated: (s: Row): void => { s['topics'][0].reference = 'heading_3'; },
    quote: (s: Row): void => { s['topics'][0].quote = 'Fabricated'; }, label: (s: Row): void => { s['topics'][0].label = 'x'.repeat(81); },
    unsafe: (s: Row): void => { s['topics'][0].label = 'unsafe\u202e'; }, approval: (s: Row): void => { s['topics'][0].approved = true; },
    extra: (s: Row): void => { s['raw_provider_text'] = 'private'; }, state: (s: Row): void => { s['state'] = 'validated_topics'; },
    source: (s: Row): void => { s['observation'].job_id = 22; }, date: (s: Row): void => { s['generated_at'] = DATE; },
  })) it(`withholds malformed ${kind} topic output`, async () => {
    const { component } = await screen(); await retained(component); mutate(api.synthDetailValue!['evidence'].synthesis);
    await component.inspectSynthesis(61); expect(component.synthesisEvidence()).toBeNull(); expect(component.synthesisDetail()).toBeNull();
    expect(component.topicSelection()).toBeNull(); expect(api.synthCommands).toEqual([]);
  });
  it('reconciles uncertainty only by frozen own-key GET without repreview or replay', async () => {
    const { component } = await screen(); await prepare(component); await component.previewSynthesis(); api.synthUnknown = true;
    await component.launchSynthesis(); const pending = component.pending()!; expect(pending).not.toBeNull(); const previews = api.synthPreviews;
    await component.reconcile(); expect(api.synthLookups).toEqual([pending.key]); expect(api.synthCommands).toHaveLength(1);
    expect(api.synthPreviews).toBe(previews); expect(component.pending()).toBeNull(); expect(component.synthesisSelected()?.id).toBe(61);
  });
  it('clears proofs on edits and clears all private state after acknowledged account loss', async () => {
    const { component } = await screen(); await prepare(component); await component.previewSynthesis(); component.editSynthesis('cost', '2.000001');
    expect(component.topicSelection()).toBeNull(); expect(component.topicJobId()).toBe(21); await component.previewSynthesis();
    api.afterSynthesisPost = () => api.accountRows = []; await component.launchSynthesis();
    expect(api.synthCommands).toHaveLength(1); expect(component.pending()).toBeNull(); expect(component.topicSelection()).toBeNull();
    expect(component.synthesisEvidence()).toBeNull(); expect(component.ready()).toBe(false);
  });
  for (const loss of ['actor', 'role', 'revision', 'origins', 'source-choice', 'authentication']) it(`clears private facts on late ${loss} loss`, async () => {
    const { component } = await screen(); await retained(component);
    api.afterSynthesisPreview = () => {
      if (loss === 'actor') api.actor = 2; if (loss === 'role') api.role = 'viewer'; if (loss === 'revision') api.revision++;
      if (loss === 'origins') api.origins = []; if (loss === 'source-choice') api.source = 'undecided'; if (loss === 'authentication') api.authenticated = false;
    };
    await component.inspectSynthesis(61); expect(component.synthesisEvidence()).toBeNull(); expect(component.synthesisDetail()).toBeNull();
    expect(component.pending()).toBeNull(); expect(api.synthCommands).toEqual([]);
  });
  it('withholds an altered exact confirmation GET after the client scope check', async () => {
    const { component } = await screen(); await retained(component);
    api.afterSynthesisDetail = () => { if (api.synthDetails.length === 2) api.synthDetailValue!['evidence'].synthesis['topics'][0].label = 'Changed late'; };
    await component.inspectSynthesis(61); expect(api.synthDetails).toEqual([61, 61]); expect(component.synthesisEvidence()).toBeNull(); expect(component.synthesisDetail()).toBeNull();
  });
  it('drops late private replies after a project change and clears on destruction', async () => {
    const { component, harness } = await screen(); await retained(component);
    let resolve!: (value: ApiResult) => void; api.synthDetailPromise = new Promise(done => resolve = done);
    const running = component.inspectSynthesis(61); await vi.waitFor(() => expect(api.synthDetails).toEqual([61]));
    await harness.navigateByUrl('/competitor-heading-topics/7/10', CompetitorRoots); resolve({ status: 200, body: api.synthDetailValue! }); await running;
    expect(component.synthesisEvidence()).toBeNull(); expect(component.synthesisDetail()).toBeNull(); harness.fixture.destroy();
    expect(component.ready()).toBe(false); expect(component.pending()).toBeNull();
  });
});

it('AccountApi uses fixed heading topic routes with GET-only own-key and exact-job lookup and same-origin no-store CSRF JSON commands', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) })); TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi); await api.competitorHeadingTopics(7, 9); await api.competitorHeadingTopics(7, 9, undefined, undefined, 'same.key');
  await api.competitorHeadingTopics(7, 9, undefined, 61); await api.competitorHeadingTopics(7, 9, topicInput(), undefined, undefined, true);
  await api.competitorHeadingTopics(7, 9, { idempotency_key: 'same.key' }); await api.competitorHeadingTopics(7, 9, {}, 61);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-heading-topics/'));
  expect(calls.map(([url]) => url.split('/competitor-heading-topics/')[1])).toEqual(['', '?idempotency_key=same.key', '61/', 'selection/', '', '61/']);
  expect(calls.slice(0, 3).every(([, options]) => options.method === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3).every(([, options]) => options.method === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});

describe('Private saved-topic literal label comparison', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  function packet(ids = [61, 62]): Row {
    const samples = ids.map(id => structuredClone(api.topicDetails[id]['evidence']));
    const labels = samples.map(sample => sample['synthesis']['topics'].map((note: Row) => note['label']));
    return { method_version: 'competitor-heading-topic-label-pair-v1', organization_id: 7, project_id: 9, source_current: true, samples,
      exact_label_match_indices: labels[0].flatMap((label: string, i: number) => labels[1].flatMap((other: string, j: number) => label === other ? [[i, j]] : [])),
      unmatched_topic_indices: labels.map((side: string[], index: number) => side.flatMap((label: string, i: number) => labels[1 - index].includes(label) ? [] : [i])),
      interpretation: 'exact_original_unverified_ai_label_matches_and_unmatched_indices_not_semantic_shared_or_missing_page_topics_content_gaps_intent_freshness_rankings_whole_site_or_approval' };
  }
  async function screen() {
    for (const [index, id] of [61, 62].entries()) {
      const source = headingsEvidence(); source['job_id'] = 21 + index;
      const collection = source['collection']; collection.url = collection.requested_url = collection.evidence.url = ORIGIN + `/selected/${index ? 'b' : 'a'}`;
      collection.source_sha256 = String(index + 1).repeat(64);
      api.topicSources[21 + index] = source;
      const row = await topicDetail(); const selection = await topicSelection({ ...topicInput(), job_id: 21 + index }, source);
      row['job'].id = id; row['selection'] = selection; row['selection_digest'] = await sha(selection);
      row['evidence'].job_id = id; row['evidence'].synthesis.observation = source;
      row['evidence'].synthesis.source_selection_digest = selection['configuration'].source_selection_digest;
      const labels = index ? ['Topic', 'I\u0307lk'] : ['Topic', 'Topic', 'topic', 'İlk', '<img src=x onerror=alert(1)>'];
      row['evidence'].synthesis.topics = labels.map(label => ({ label, reference: 'heading_1', quote: 'Same' }));
      api.topicDetails[id] = row;
    }
    api.rows = [22, 21].map(id => ({ ...job(), id, status: 'succeeded' }));
    api.synthRows = [62, 61].map(id => api.topicDetails[id]['job']); api.topicPairValue = packet();
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-heading-topics/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); await component.loadSyntheses();
    component.editTopicPair('previous', '61'); component.editTopicPair('current', '62');
    return { component, harness };
  }
  it('uses saved topic history, retains duplicate/case/Unicode original indices, confirms the same private GET and renders inert facts without AI processing', async () => {
    const { component, harness } = await screen(); const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(component.aiPermission()).toBe(false); await component.compareTopics(); harness.detectChanges();
    expect(component.topicComparison()).toEqual(packet()); expect(component.topicComparison()?.['exact_label_match_indices']).toEqual([[0, 0], [1, 0]]);
    expect(component.topicComparison()?.['unmatched_topic_indices']).toEqual([[2, 3, 4], [1]]);
    expect(api.topicPairs).toEqual([[61, 62], [61, 62]]); expect(api.synthDetails).toEqual([61, 62, 61, 62]);
    expect(api.details).toEqual([21, 22, 21, 22]); expect(api.synthFamilies.every(f => f === 'topics')).toBe(true);
    expect(api.synthPreviews).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.commands).toEqual([]); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    expect(harness.routeNativeElement!.querySelector('img,script')).toBeNull(); expect(harness.routeNativeElement!.textContent).toContain('human review required');
    expect(harness.routeNativeElement!.querySelector('#competitor-topic-first')!.textContent).toContain('61');
    expect(component.comparison()).toBeNull(); expect(component.synthesisEvidence()).toBeNull();
  });
  it('accepts the actual backend standard catalog and saved private model configuration tier', async () => {
    api.modelRows[0]['access_tier'] = 'standard';
    const { component } = await screen();
    expect(component.synthesisLoaded()).toBe(true);
    for (const row of Object.values(api.topicDetails)) {
      row['selection'].configuration.model_access_tier = 'standard';
      row['selection_digest'] = await sha(row['selection']);
    }
    api.topicPairValue = packet(); await component.compareTopics(); expect(component.topicComparison()).toEqual(packet());
    expect(api.synthCommands).toEqual([]); expect(api.synthPreviews).toBe(0);
  });
  it('preserves deliberate reversed result order with unrelated original dates and model provenance', async () => {
    const { component } = await screen(); component.editTopicPair('previous', '62'); component.editTopicPair('current', '61'); api.topicPairValue = packet([62, 61]);
    await component.compareTopics(); expect(component.topicComparison()).toEqual(packet([62, 61])); expect(api.topicPairs).toEqual([[62, 61], [62, 61]]);
  });
  it('does not coerce observation IDs, same job IDs, queued or cancelled results into a saved topic pair', async () => {
    const { component } = await screen();
    for (const value of ['21', '061', '0', '9007199254740992']) { component.editTopicPair('previous', value); expect(component.firstTopicJobId()).toBe(0); }
    component.editTopicPair('previous', '62'); await component.compareTopics(); expect(api.topicPairs).toEqual([]);
    api.synthRows.find(row => row.id === 61)!.status = 'queued'; await component.loadSyntheses(); component.editTopicPair('previous', '61'); expect(component.firstTopicJobId()).toBe(0);
  });
  for (const [kind, mutate] of Object.entries({
    method: (p: Row): void => { p['method_version'] = 'competitor-heading-topics-v1'; }, scope: (p: Row): void => { p['project_id'] = 10; },
    current: (p: Row): void => { p['source_current'] = false; }, meaning: (p: Row): void => { p['interpretation'] = 'shared_and_missing_topics'; },
    extra: (p: Row): void => { p['approved'] = true; }, order: (p: Row): void => { p['samples'].reverse(); },
    quote: (p: Row): void => { p['samples'][0].synthesis.topics[0].quote = 'Made up'; },
    model: (p: Row): void => { p['samples'][1].synthesis.model_id = 99; },
    matches: (p: Row): void => { p['exact_label_match_indices'] = [[0, 0]]; }, unmatched: (p: Row): void => { p['unmatched_topic_indices'] = [[], []]; },
    overflow: (p: Row): void => { p['samples'][0].synthesis.topics[0].label = 'x'.repeat(102401); },
  })) it(`withholds malformed ${kind} packet and clears every private result`, async () => {
    const { component } = await screen(); mutate(api.topicPairValue!); await component.compareTopics();
    expect(component.topicComparison()).toBeNull(); expect(component.ready()).toBe(false); expect(component.synthesisDetail()).toBeNull(); expect(api.synthCommands).toEqual([]);
  });
  it('validates genuine current original quote integrity before comparison and clears on private detail denial', async () => {
    const { component } = await screen(); api.topicDetails[62]['evidence'].synthesis.topics[0].reference = 'heading_3';
    api.topicPairValue = packet(); await component.compareTopics(); expect(component.topicComparison()).toBeNull(); expect(api.topicPairs).toEqual([]);
  });
  for (const loss of ['actor', 'role', 'revision', 'source-choice', 'authentication', 'history', 'original', 'model-denial']) it(`withholds late ${loss} loss after the first comparison`, async () => {
    const { component } = await screen(); api.topicPairChange = () => {
      if (loss === 'actor') api.actor = 2; if (loss === 'role') api.role = 'viewer'; if (loss === 'revision') api.revision++;
      if (loss === 'source-choice') api.source = 'undecided'; if (loss === 'authentication') api.authenticated = false;
      if (loss === 'history') api.synthRows[0] = { ...api.synthRows[0], updated_at: GENERATED };
      if (loss === 'original') api.topicSources[21]['collection'].evidence.headings[1].text = 'Changed';
      if (loss === 'model-denial') api.synthDeny = true;
    };
    await component.compareTopics(); expect(component.topicComparison()).toBeNull(); expect(component.synthesisEvidence()).toBeNull(); expect(component.firstTopicJobId()).toBe(0); expect(api.synthCommands).toEqual([]);
  });
  it('withholds changed final comparison after independent original reads and scope', async () => {
    const { component } = await screen(); api.topicPairChange = () => { if (api.topicPairs.length === 2) api.topicPairValue!['unmatched_topic_indices'] = [[], []]; };
    await component.compareTopics(); expect(api.topicPairs).toHaveLength(2); expect(component.topicComparison()).toBeNull();
  });
  it('drops late replies after result edits, route changes and destruction', async () => {
    const { component, harness } = await screen(); let resolve!: (value: ApiResult) => void;
    api.topicPairPromise = new Promise(done => resolve = done); const running = component.compareTopics(); await vi.waitFor(() => expect(api.topicPairs).toHaveLength(1));
    component.editTopicPair('previous', '62'); resolve({ status: 200, body: { organization_id: 7, project_id: 9, comparison: packet() } }); await running;
    expect(component.topicComparison()).toBeNull(); expect(component.firstTopicJobId()).toBe(62);
    await harness.navigateByUrl('/competitor-heading-topics/7/10', CompetitorRoots); expect(component.topicComparison()).toBeNull(); harness.fixture.destroy(); expect(component.ready()).toBe(false);
  });
  it('clears a displayed comparison on any source or model edit', async () => {
    const { component } = await screen(); await component.compareTopics(); expect(component.topicComparison()).not.toBeNull();
    component.editSynthesis('model', '31'); expect(component.topicComparison()).toBeNull(); expect(component.firstTopicJobId()).toBe(0);
  });
});

it('AccountApi saved-topic comparison uses a fixed bodyless scoped same-origin no-store GET', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: '' } }] });
  await TestBed.inject(AccountApi).competitorHeadingTopicsComparison(7, 9, 62, 61);
  const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toContain('/organizations/7/projects/9/competitor-heading-topics/comparison/?first_job_id=62&second_job_id=61');
  expect(options.method).toBe('GET'); expect(options.body).toBeUndefined(); expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store');
});


describe('Private saved resolved destination inventory', () => {
  let api: FixtureApi;
  beforeEach(() => {
    api = new FixtureApi(); api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }];
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-destinations/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { component, harness };
  }
  function select(component: CompetitorRoots, first = '21', second = '22') {
    component.editReferenceInventory(true); component.editPair('previous', first); component.editPair('current', second);
  }
  function unavailable(page: Row) {
    const evidence = page['collection'].evidence; evidence.state = 'unavailable'; evidence.reason = 'result_limit'; evidence.destinations = null;
    evidence.counts = Object.fromEntries(Object.keys(evidence.counts).map(key => [key, null]));
  }
  it('requires a labelled mutually exclusive choice and two identical frozen GETs before inert resolved-URI display without commands or storage', async () => {
    api.actor = 2; api.role = 'admin'; const { component, harness } = await screen(); harness.detectChanges();
    const choice = harness.routeNativeElement!.querySelector<HTMLInputElement>('#competitor-destination-inventory')!;
    expect(choice.checked).toBe(false); expect(component.referenceInventoryMode()).toBe(false);
    const dated = harness.routeNativeElement!.querySelector<HTMLInputElement>('#competitor-reference-dated')!;
    expect(dated.checked).toBe(true); expect(choice.type).toBe('radio'); expect(choice.name).toBe(dated.name);
    expect(choice.closest('fieldset')!.querySelector('legend')!.textContent).toBe('Saved reference inspection mode');
    expect(harness.routeNativeElement!.querySelectorAll('input[name=competitor-reference-mode]')).toHaveLength(3);
    expect(harness.routeNativeElement!.querySelector('label[for=competitor-destination-inventory]')).not.toBeNull();
    await component.compare(); expect(api.inventoryPairs).toEqual([]);
    component.editReferenceStructure(true); expect(component.referenceStructureMode()).toBe(true);
    choice.checked = true; choice.dispatchEvent(new Event('change')); expect(component.referenceStructureMode()).toBe(false);
    expect(component.referenceInventoryMode()).toBe(true);
    component.editPair('previous', '021'); component.editPair('current', '999'); await component.compare(); expect(api.inventoryPairs).toEqual([]);
    component.editPair('previous', '21'); component.editPair('current', '22');
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(component.comparison()).toEqual(destinationInventory()); expect(api.inventoryPairs).toEqual([[21, 22], [21, 22]]);
    expect(api.structurePairs).toEqual([]); expect(api.destinationsPairs).toEqual([]); expect(api.catalogCalls).toBe(0); expect(api.commands).toEqual([]); expect(api.previews).toBe(0);
    const text = harness.routeNativeElement!.textContent!;
    expect(text).toContain('Stored resolved destinations across two saved static samples'); expect(text).toContain('not raw HTML href spellings');
    expect(text).toContain('unavailable entire row is null'); expect(text).toContain('not complete page, site or destination coverage');
    expect(text).toContain(ORIGIN + '/selected/%62');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model, a[href*="competitor.example.invalid"]')).toBeNull();
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    component.editReferenceStructure(true); expect(component.referenceInventoryMode()).toBe(false); expect(component.comparison()).toBeNull();
    component.editPair('previous', '21'); component.editPair('current', '22'); await component.compare(); expect(component.comparison()).toEqual(referenceStructure());
    dated.checked = true; dated.dispatchEvent(new Event('change'));
    expect(component.referenceStructureMode()).toBe(false); expect(component.referenceInventoryMode()).toBe(false);
    expect(component.comparison()).toBeNull(); expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0);
  });
  it('preserves exact stored URI variants and duplicate counts, reverse order, observed empty and whole-null unknown rows even with empty union', async () => {
    const { component } = await screen();
    for (const state of ['variants', 'reverse', 'empty', 'first_unknown', 'second_unknown', 'empty_unknown', 'both_unknown']) {
      const pages = referenceStructure()['pages'] as Row[];
      if (state === 'variants') { pages[0]['collection'].evidence.destinations.push(ORIGIN + '/selected/B'); pages[0]['collection'].evidence.counts.same_origin_http++; pages[0]['collection'].evidence.counts.href_anchors++; }
      if (state === 'reverse') pages.reverse();
      if (state === 'empty' || state === 'empty_unknown') {
        const evidence = pages[0]['collection'].evidence; evidence.destinations = []; evidence.counts.same_origin_http = 0; evidence.counts.href_anchors = 2;
      }
      if (state === 'first_unknown' || state === 'both_unknown') unavailable(pages[0]);
      if (state === 'second_unknown' || state === 'empty_unknown' || state === 'both_unknown') unavailable(pages[1]);
      api.inventoryValue = destinationInventory(pages); select(component, state === 'reverse' ? '22' : '21', state === 'reverse' ? '21' : '22');
      await component.compare(); expect(component.comparison()).toEqual(api.inventoryValue);
      if (state === 'variants') expect(component.comparison()!['destinations']).toEqual([ORIGIN + '/selected/b', ORIGIN + '/selected/b/', ORIGIN + '/selected/%62', ORIGIN + '/selected/B', ORIGIN + '/selected/a']);
      if (state === 'empty_unknown') expect(component.comparison()!['destination_reference_occurrences']).toEqual([[], null]);
      if (state === 'both_unknown') expect(component.comparison()!['destination_reference_occurrences']).toEqual([null, null]);
    }
  });
  it.each(['extra', 'method', 'meaning', 'scope', 'current', 'size', 'pages', 'ids', 'same_uri', 'other_origin', 'union_order', 'duplicate_uri', 'missing_uri', 'count', 'row_type', 'observed_null', 'row_state'])('rejects malformed exact inventory %s without private state', async field => {
    const { component } = await screen(); const value = api.inventoryValue;
    if (field === 'extra') value['extra'] = true;
    if (field === 'method') value['method_version'] = 'competitor-two-page-references-v1';
    if (field === 'meaning') value['interpretation'] = 'known_literal_supported_references';
    if (field === 'scope') value['project_id'] = 10;
    if (field === 'current') value['source_current'] = false;
    if (field === 'size') value['destinations'] = ['x'.repeat(32769)];
    if (field === 'pages') value['pages'].pop();
    if (field === 'ids') value['pages'][0].job_id = 22;
    if (field === 'same_uri' || field === 'other_origin') {
      const c = value['pages'][1].collection; c.url = c.requested_url = c.evidence.url = field === 'same_uri' ? value['pages'][0].collection.url : 'https://other.example.invalid/selected/b';
    }
    if (field === 'union_order') value['destinations'].reverse();
    if (field === 'duplicate_uri') value['destinations'].push(value['destinations'][0]);
    if (field === 'missing_uri') value['destinations'].pop();
    if (field === 'count') value['destination_reference_occurrences'][0][0] = 1;
    if (field === 'row_type') value['destination_reference_occurrences'][0][0] = '2';
    if (field === 'observed_null') value['destination_reference_occurrences'][0] = null;
    if (field === 'row_state') value['all_rows_observed'] = 1;
    select(component); await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'authenticated', 'saved_job', 'source_cancel', 'denial'])('clears inventory after late %s loss', async field => {
    const { component } = await screen(); api.afterPair = (): void => {
      if (field === 'actor') api.actor = 2;
      if (field === 'role') api.role = 'viewer';
      if (field === 'restricted') api.restricted = true;
      if (field === 'revision') api.revision++;
      if (field === 'updated') api.updated = LATER;
      if (field === 'origins') api.origins = [];
      if (field === 'authenticated') api.authenticated = false;
      if (field === 'saved_job') api.rows[0].updated_at = OBSERVED;
      if (field === 'source_cancel') api.rows[0].cancel_requested = true;
      if (field === 'denial') api.deny = true;
    };
    select(component); await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    expect(component.referenceInventoryMode()).toBe(false); expect(api.inventoryPairs).toHaveLength(1); expect(api.commands).toEqual([]);
  });
  it.each(['mutation', 'scope', 'denial'])('withholds the second private confirmation after %s', async change => {
    const { component } = await screen(); api.afterPair = (): void => {
      if (api.inventoryPairs.length === 2) {
        if (change === 'mutation') api.inventoryValue['pages'][0].collection.source_sha256 = 'e'.repeat(64);
        if (change === 'scope') api.actor = 2;
        if (change === 'denial') api.deny = true;
      }
    };
    select(component); await component.compare(); expect(api.inventoryPairs).toEqual([[21, 22], [21, 22]]);
    expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(api.commands).toEqual([]);
  });
  it('clears mode and private rows on edits, reload, stale pending replies, route switch and destruction', async () => {
    const { component, harness } = await screen();
    for (const edit of [() => component.editReferenceInventory(false), () => component.editReferenceStructure(true), () => component.editUrl(ORIGIN + '/other')]) {
      select(component); await component.compare(); expect(component.comparison()).not.toBeNull(); edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    select(component); await component.compare(); await component.load(); expect(component.comparison()).toBeNull(); expect(component.referenceInventoryMode()).toBe(false);
    let release!: (value: ApiResult) => void; api.pairPromise = new Promise(resolve => { release = resolve; });
    select(component); const count = api.inventoryPairs.length; const pending = component.compare(); await vi.waitFor(() => expect(api.inventoryPairs.length).toBeGreaterThan(count));
    component.editReferenceInventory(false); release({ status: 200, body: { organization_id: 7, project_id: 9, inventory: destinationInventory() } });
    await pending; expect(component.comparison()).toBeNull(); expect(api.inventoryPairs).toHaveLength(count + 1); api.pairPromise = null;
    select(component); await component.compare(); await harness.navigateByUrl('/competitor-page-destinations/7/10', CompetitorRoots);
    expect(component.comparison()).toBeNull(); expect(component.referenceInventoryMode()).toBe(false);
    harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.referenceInventoryMode()).toBe(false);
  });
  it('AccountApi sends only the fixed scoped bodyless inventory GET', async () => {
    TestBed.resetTestingModule(); TestBed.configureTestingModule({});
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }));
    await TestBed.inject(AccountApi).competitorPageDestinationInventory(7, 9, 22, 21);
    const calls = fetch.mock.calls; expect(calls).toHaveLength(1);
    expect(calls[0][0]).toContain('/organizations/7/projects/9/competitor-page-destinations/inventory/?first_job_id=22&second_job_id=21');
    expect(calls[0][1]?.method).toBe('GET'); expect(calls[0][1]?.body).toBeUndefined(); fetch.mockRestore();
  });
});


describe('Private selected competitor content elements', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-formats/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function declare(component: CompetitorRoots, url = ORIGIN + '/selected/article') {
    component.editOrigin(ORIGIN); component.editUrl(url);
    component.editPermission('collection', true); component.editPermission('use', true); component.editPermission('storage', true);
  }
  it('uses labelled empty exact URI and three unchecked rights, fixed frozen element command with separate pair controls and no AI promotion', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen(); harness.detectChanges();
    const native = harness.routeNativeElement!;
    expect(native.querySelector('h1')!.textContent).toContain('static content-element counts');
    expect(native.querySelector<HTMLInputElement>('#competitor-page-url')!.value).toBe('');
    expect(native.querySelector('label[for=competitor-page-url]')).not.toBeNull();
    const rights = [...native.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
    expect(rights).toHaveLength(3); expect(rights.every(input => !input.checked && input.required && !!input.closest('label'))).toBe(true);
    expect(native.querySelector('#competitor-previous')).not.toBeNull(); expect(native.querySelector('#competitor-model')).toBeNull();
    await component.compare();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(component.previousJobId()).toBe(0); expect(component.frozenPair()).toBeNull(); expect(api.catalogCalls).toBe(0);
    expect([api.datesPairs, api.pairs, api.pagePairs, api.destinationsPairs, api.headingsPairs, api.linksPairs, api.schemaPairs, api.synthCommands, api.synthDetails, api.synthCancels].every(rows => rows.length === 0)).toBe(true);
    declare(component); await component.preview(); const frozen = structuredClone(component.selection()!);
    expect(frozen.selection['method']).toBe('competitor-page-elements-collect-v1'); expect(frozen.selection.binding['url']).toBe(ORIGIN + '/selected/article');
    expect(frozen.selection_digest).toBe(await sha(frozen.selection));
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.launch();
    expect(api.commands).toEqual([{ origin: ORIGIN, url: ORIGIN + '/selected/article', collection_permission: true, use_permission: true, storage_permission: true,
      idempotency_key: expect.any(String), selection_digest: frozen.selection_digest }]);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore(); expect(api.familyCalls.every(family => family === 'formats')).toBe(true);
  });
  it('preserves original private counts, observed zero and whole-null unknown with inert sample limits', async () => {
    api.actor = 2; api.role = 'admin'; api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    await component.inspect(21); expect(component.evidence()).toEqual(formatsEvidence()); harness.detectChanges();
    expect(harness.routeNativeElement!.textContent).toContain('CSS-hidden syntax may count');
    expect(harness.routeNativeElement!.textContent).toContain('whole-null unavailable');
    expect(harness.routeNativeElement!.textContent).toContain('search result features');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull();
    expect(harness.routeNativeElement!.querySelector('#competitor-previous')).not.toBeNull();
    api.detailValue = formatsEvidence(); api.detailValue['collection'].evidence.counts = Object.fromEntries(Object.keys(api.detailValue['collection'].evidence.counts).map(key => [key, 0]));
    await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    for (const reason of ['ambiguous_markup', 'element_limit']) {
      api.detailValue = formatsEvidence(); Object.assign(api.detailValue['collection'].evidence, { state: 'unavailable', reason,
        counts: Object.fromEntries(Object.keys(api.detailValue['collection'].evidence.counts).map(key => [key, null])) });
      await component.inspect(21); expect(component.evidence()).toEqual(api.detailValue);
    }
  });
  it('rejects cross-family and malformed count/provenance DTOs before private display', async () => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { harness, component } = await screen();
    const mutations: ((row: Row) => void)[] = [
      ...[evidence, schemaEvidence, linksEvidence, pageEvidence, headingsEvidence, destinationsEvidence, datesEvidence, labEvidence].map(factory => (row: Row) => row['collection'] = factory()['collection']),
      row => row['collection'].evidence.counts.p = true, row => row['collection'].evidence.counts.p = -1,
      row => row['collection'].evidence.counts.p = 1001, row => row['collection'].evidence.counts.p = null,
      row => row['collection'].evidence.counts.p = 1.5, row => row['collection'].evidence.counts = {},
      row => row['collection'].evidence.counts = { ...row['collection'].evidence.counts, iframe: 1 },
      row => Object.assign(row['collection'].evidence.counts, { p: 1000, ul: 1 }),
      row => row['collection'].evidence.raw_body = '<img src=x onerror=alert(1)>',
      row => row['collection'].evidence.reason = 'rendered_format',
      row => Object.assign(row['collection'].evidence, { state: 'unavailable', reason: 'ambiguous_markup' }),
      row => row['collection'].evidence.coverage = 'whole_site', row => row['collection'].evidence.interpretation = 'loaded_media',
      row => row['collection'].evidence.body_size_bytes = 131073, row => row['collection'].evidence.body_size_bytes = true,
      row => row['collection'].evidence.body_sha256 = 'bad', row => row['collection'].evidence.excluded_containers = [],
      row => row['collection'].evidence.url = ORIGIN + '/other', row => row['collection'].evidence.observed_at = LATER,
      row => row['collection'].source_sha256 = 'bad', row => row['source_current'] = false,
    ];
    for (const mutate of mutations) {
      await component.load(); api.detailValue = formatsEvidence(); mutate(api.detailValue); await component.inspect(21);
      expect(component.evidence()).toBeNull(); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('withholds late element counts and clears state after %s loss', async field => {
    api.rows = [{ ...job(), status: 'succeeded' }]; const { component } = await screen();
    api.afterDetail = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
    };
    await component.inspect(21); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false); expect(component.pending()).toBeNull();
  });
  it('denies invalid exact URIs, missing rights and altered or stale source preview before any POST', async () => {
    const { component } = await screen();
    for (const url of ['', ORIGIN + '/', OWN + '/a', ORIGIN + '/a?', ORIGIN + '/a#', ORIGIN + '/%0a', ORIGIN + '/back\\slash',
      'http://competitor.example.invalid/a', 'https://competitor.example.invalid:443/a', 'https://user:secret@competitor.example.invalid/a']) {
      declare(component, url); await component.preview(); expect(component.selection()).toBeNull();
    }
    expect(api.previews).toBe(0);
    declare(component); component.editPermission('storage', false); await component.preview(); expect(api.previews).toBe(0);
    for (const mutate of [(row: Row) => row['selection'].method = 'competitor-page-headings-collect-v1',
      (row: Row) => row['selection'].binding.url = ORIGIN + '/other', (row: Row) => row['selection'].binding.method_version = 'competitor-source-v1']) {
      declare(component); api.previewChange = mutate; await component.preview(); expect(component.selection()).toBeNull();
    }
    api.previewChange = null; declare(component); await component.preview(); api.afterPreview = () => ++api.revision;
    await component.launch(); expect(api.commands).toEqual([]); expect(component.pending()).toBeNull();
  });
  it('uses only own-key GET for unknown element commands and clears uncertainty on source edits and actor loss', async () => {
    const { component } = await screen(); declare(component); await component.preview(); api.uncertain = true; await component.launch();
    const frozen = structuredClone(component.pending()!); expect(frozen.data['url']).toBe(ORIGIN + '/selected/article');
    await component.reconcile(); expect(api.commands).toHaveLength(1); expect(api.lookups).toEqual([frozen.key]); expect(component.pending()).toBeNull();
    await component.load(); declare(component); await component.preview(); api.drop = true; await component.launch();
    const count = api.commands.length; await component.reconcile(); expect(api.commands).toHaveLength(count); expect(component.pending()).not.toBeNull();
    component.editUrl(ORIGIN + '/other'); expect(component.pending()).toBeNull(); expect(component.collectionPermission()).toBe(false);
    api.drop = false; declare(component); await component.preview(); await component.launch(); ++api.actor; await component.reconcile();
    expect(component.pending()).toBeNull(); expect(component.origins()).toEqual([]); expect(component.url()).toBe('');
  });
  it('cancels only through the format family and discards late detail after project switch or destruction', async () => {
    api.rows = [job()]; const { harness, component } = await screen(); await component.cancel(21); expect(api.cancels).toEqual([21]);
    api.rows = [{ ...job(), status: 'succeeded' }]; await component.load();
    let release!: (result: ApiResult) => void; api.detailPromise = new Promise<ApiResult>(resolve => release = resolve);
    const reading = component.inspect(21); await vi.waitFor(() => expect(api.details).toContain(21));
    await harness.navigateByUrl('/competitor-page-formats/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, evidence: formatsEvidence() } });
    await reading; expect(component.evidence()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.url()).toBe('');
    expect(api.familyCalls.every(family => family === 'formats')).toBe(true);
  });
});


it('AccountApi content-element commands use fixed scoped private CSRF/GET paths', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  const api = TestBed.inject(AccountApi);
  await api.competitorPageFormats(7, 9); await api.competitorPageFormats(7, 9, undefined, undefined, 'elements.key'); await api.competitorPageFormats(7, 9, undefined, 21);
  await api.competitorPageFormats(7, 9, { origin: ORIGIN, url: ORIGIN + '/selected/article' }, undefined, undefined, true);
  await api.competitorPageFormats(7, 9, { idempotency_key: 'elements.key' }); await api.competitorPageFormats(7, 9, {}, 21);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-page-formats/'));
  expect(calls.map(([url]) => url.split('/competitor-page-formats/')[1])).toEqual(['', '?idempotency_key=elements.key', '21/', 'selection/', '', '21/']);
  expect(calls.slice(0, 3).every(([, options]) => options.method === 'GET' && options.body === undefined)).toBe(true);
  expect(calls.slice(3).every(([, options]) => options.method === 'POST' && (options.headers as Row)['X-CSRFToken'] === 'fixture')).toBe(true);
  expect(calls.every(([url, options]) => url.includes('/organizations/7/projects/9/') && options.credentials === 'same-origin' && options.cache === 'no-store')).toBe(true);
});

describe('Private original static content-element pairs', () => {
  let api: FixtureApi;
  beforeEach(() => { api = new FixtureApi(); api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }];
    api.pairValue = formatsComparison(); TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] }); });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-formats/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function select(component: CompetitorRoots) { component.editPair('previous', '21'); component.editPair('current', '22'); }
  it('requires two deliberate saved jobs and preserves signed lexical counts, dates and opaque source without storage, collection or AI', async () => {
    api.actor = 2; api.role = 'admin'; const { harness, component } = await screen();
    await component.compare(); expect(api.formatsPairs).toEqual([]);
    component.editPair('previous', '021'); component.editPair('current', '999'); await component.compare(); expect(api.formatsPairs).toEqual([]);
    select(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(api.formatsPairs).toEqual([[21, 22], [21, 22]]); expect(component.comparison()).toEqual(formatsComparison()); expect(component.frozenPair()).not.toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain('later minus earlier'); expect(harness.routeNativeElement!.textContent).toContain('whole-null');
    expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull(); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.cancelSynthesis(61); await component.inspectSynthesis(61);
    expect(api.catalogCalls).toBe(0); expect(api.synthFamilies).toEqual([]); expect(api.commands).toEqual([]);
    expect([api.pairs, api.pagePairs, api.headingsPairs, api.destinationsPairs, api.datesPairs, api.linksPairs, api.schemaPairs].every(rows => !rows.length)).toBe(true);
  });
  it.each(['empty', 'unavailable-before', 'unavailable-after'])('retains %s as observed zero or whole-null differences with original provenance', async kind => {
    const { component } = await screen(); const row = api.pairValue;
    if (kind === 'empty') {
      for (const key of ['previous', 'current']) row[key].evidence.counts = Object.fromEntries(Object.keys(row[key].evidence.counts).map(key => [key, 0]));
      row['count_deltas'] = Object.fromEntries(Object.keys(row['count_deltas']).map(key => [key, 0]));
    } else {
      const item = row[kind === 'unavailable-before' ? 'previous' : 'current'].evidence;
      Object.assign(item, { state: 'unavailable', reason: 'ambiguous_markup', counts: Object.fromEntries(Object.keys(item.counts).map(key => [key, null])) });
      row['comparable'] = false; row['state'] = 'incomparable_unavailable_content_element_counts'; row['count_deltas'] = null;
    }
    select(component); await component.compare(); expect(component.comparison()).toEqual(row);
  });
  it('rejects forged deltas, extra fields, original scope, types and evidence before private display', async () => {
    const { harness, component } = await screen();
    const changes: ((value: Row) => void)[] = [
      v => v['method_version'] = 'competitor-page-dates-pair-v1', v => v['parser_method'] = 'competitor-static-metadata-v1',
      v => v['collection_method'] = 'competitor-page-headings-collect-v1', v => v['interpretation'] = 'rendered_formats',
      v => v['organization_id'] = 8, v => v['project_id'] = 10, v => v['source_current'] = false, v => v['source_sha256'] = 'bad',
      v => v['previous'].job_id = 22, v => v['current'].evidence.observed_at = OBSERVED, v => v['url'] = ORIGIN + '/',
      v => v['current'].evidence.url = ORIGIN + '/other', v => v['previous'].robots = 'approved',
      v => v['metadata_changed'] = {}, v => v['count_deltas'].p = 1, v => v['count_deltas'].img = '-2',
      v => v['count_deltas'].p = true, v => delete v['count_deltas'].audio, v => v['count_deltas'].h1 = 0,
      v => v['body_changed'] = false, v => v['comparable'] = 1, v => v['state'] = 'rendered_formats',
      v => v['current'].evidence.counts.p = true, v => v['current'].evidence.counts.p = 1001,
      v => v['current'].evidence.counts.p = null, v => v['current'].evidence.body_size_bytes = 131073,
      v => v['current'].evidence.coverage = 'whole_site', v => v['current'].evidence.text = '<img onerror=alert(1)>',
      v => v['current'].evidence.state = 'unavailable',
    ];
    for (const change of changes) {
      await component.load(); api.pairValue = formatsComparison(); change(api.pairValue); select(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('img')).toBeNull();
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('clears both private originals on post-comparison %s loss without commands', async field => {
    const { component } = await screen(); api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
    };
    select(component); await component.compare(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); expect(component.ready()).toBe(false);
    expect(api.commands).toEqual([]); expect(api.synthFamilies).toEqual([]);
  });
  it.each(['changed', 'denied', 'job-changed'])('withholds %s final identical-pair confirmation', async loss => {
    const { component } = await screen(); let calls = 0;
    api.afterPair = () => { if (++calls === 2) {
      if (loss === 'changed') api.pairValue['current'].evidence.body_sha256 = 'f'.repeat(64);
      if (loss === 'denied') api.pairStatus = 403;
      if (loss === 'job-changed') api.rows[0].updated_at = OBSERVED;
    } };
    select(component); await component.compare(); expect(calls).toBe(2); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
  });
  it('discards late old-project results and clears originals on edits, refresh and destruction', async () => {
    const { harness, component } = await screen();
    for (const edit of [() => component.editUrl(ORIGIN + '/other'), () => component.editPermission('use', false), () => component.editPair('current', '21'), () => component.load()]) {
      select(component); await component.compare(); expect(component.comparison()).not.toBeNull(); await edit(); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    api.formatsPairs = []; select(component); const reading = component.compare(); await vi.waitFor(() => expect(api.formatsPairs).toEqual([[21, 22]]));
    await harness.navigateByUrl('/competitor-page-formats/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, comparison: formatsComparison() } }); await reading;
    expect(component.comparison()).toBeNull(); harness.fixture.destroy(); expect(component.jobs()).toEqual([]); expect(component.frozenPair()).toBeNull();
  });
});

it('AccountApi content-element comparison uses only the exact private scoped bodyless GET', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  await TestBed.inject(AccountApi).competitorPageFormatsComparison(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-page-formats/'));
  expect(calls).toHaveLength(1); const [url, options] = calls[0];
  expect(url).toContain('/organizations/7/projects/9/competitor-page-formats/comparison/?previous_job_id=21&current_job_id=22');
  expect(options.method).toBe('GET'); expect(options.body).toBeUndefined(); expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store');
});


describe('Private two saved-page static element structure', () => {
  let api: FixtureApi;
  beforeEach(() => {
    api = new FixtureApi(); api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }];
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-formats/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function select(component: CompetitorRoots, first = '21', second = '22') {
    component.editReferenceStructure(true); component.editPair('previous', first); component.editPair('current', second);
  }
  it.each(['en', 'tr'] as const)('requires labelled deliberate mode and confirms the exact original rows before an inert accessible count table without storage or AI in %s', async (language) => {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    api.actor = 2; api.role = 'admin'; const { harness, component } = await screen(); harness.detectChanges();
    const native = harness.routeNativeElement!; const choice = native.querySelector<HTMLInputElement>('#competitor-reference-structure')!;
    expect(choice.checked).toBe(false); expect(native.querySelector('label[for=competitor-reference-structure]')).not.toBeNull();
    expect(native.querySelector('#competitor-destination-inventory')).toBeNull();
    await component.compare(); expect(api.formatsStructurePairs).toEqual([]);
    choice.checked = true; choice.dispatchEvent(new Event('change')); harness.detectChanges();
    expect(component.referenceStructureMode()).toBe(true); expect(component.referenceInventoryMode()).toBe(false);
    component.editPair('previous', '021'); component.editPair('current', '999'); await component.compare(); expect(api.formatsStructurePairs).toEqual([]);
    component.editPair('previous', '21'); component.editPair('current', '22');
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(component.comparison()).toEqual(formatsStructure()); expect(api.formatsStructurePairs).toEqual([[21, 22], [21, 22]]);
    expect(api.formatsPairs).toEqual([]); expect(api.structurePairs).toEqual([]); expect(api.inventoryPairs).toEqual([]);
    expect(native.querySelector('table caption')!.textContent).toContain(component.t('Literal start-tag counts'));
    expect(native.querySelector(`[role=region][aria-label="${component.t('Two saved-page literal element counts')}"][tabindex="0"]`)).not.toBeNull();
    expect(native.querySelectorAll('thead th[scope=col]')).toHaveLength(9); expect(native.querySelectorAll('tbody th[scope=row]')).toHaveLength(2);
    const retained = component.comparison();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(native.querySelector('#competitor-reference-structure')).toBe(choice); expect(choice.checked).toBe(true);
    expect(component.comparison()).toBe(retained); expect(component.previousJobId()).toBe(21); expect(component.currentJobId()).toBe(22);
    component.productLanguage.set(language); harness.detectChanges();
    expect(native.querySelectorAll('tbody td')).toHaveLength(16); expect(native.textContent).toContain(language === 'tr' ? 'yalnızca bu iki statik örneği' : 'only these two static samples');
    expect(native.querySelector('img, script, #competitor-model')).toBeNull(); expect(native.querySelector('a[href*="competitor.example.invalid"]')).toBeNull();
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    await component.loadSyntheses(); await component.previewSynthesis(); expect(api.catalogCalls).toBe(0); expect(api.commands).toEqual([]);
    component.editReferenceStructure(false); expect(component.comparison()).toBeNull(); expect(component.previousJobId()).toBe(0);
    api.pairValue = formatsComparison(); component.editPair('previous', '21'); component.editPair('current', '22'); await component.compare();
    expect(component.comparison()).toEqual(formatsComparison()); expect(api.formatsPairs).toEqual([[21, 22], [21, 22]]);
  });
  it('retains row order and equal dates with independent observed zero versus whole unknown counts', async () => {
    const { harness, component } = await screen();
    for (const state of ['reverse', 'empty', 'first-unavailable', 'second-unavailable']) {
      const pages = formatsStructure()['pages'] as Row[];
      if (state === 'reverse') pages.reverse();
      else {
        const evidence = (pages[state === 'second-unavailable' ? 1 : 0]['collection'] as Row)['evidence'] as Row;
        evidence['counts'] = Object.fromEntries(Object.keys(evidence['counts'] as Row).map(name => [name, state === 'empty' ? 0 : null]));
        if (state !== 'empty') Object.assign(evidence, { state: 'unavailable', reason: 'ambiguous_markup' });
      }
      api.formatsStructureValue = formatsStructure(pages); select(component, state === 'reverse' ? '22' : '21', state === 'reverse' ? '21' : '22');
      await component.compare(); expect(component.comparison()).toEqual(api.formatsStructureValue); harness.detectChanges();
      if (state.includes('unavailable')) expect(harness.routeNativeElement!.querySelector('tbody')!.textContent).toContain('Unavailable');
    }
  });
  it('rejects forged count matrices, coverage, originals, scope, URI and private fields before display', async () => {
    const { harness, component } = await screen();
    const changes: ((v: Row) => void)[] = [
      v => v['method_version'] = 'competitor-two-page-references-v1', v => v['organization_id'] = 8, v => v['project_id'] = 10,
      v => v['source_current'] = 1, v => v['interpretation'] = 'whole_site', v => v['raw_body'] = 'private',
      v => v['element_names'].reverse(), v => v['element_names'].pop(), v => v['all_rows_observed'] = 1, v => v['all_rows_observed'] = false,
      v => v['pages'].reverse(), v => v['pages'].pop(), v => v['pages'][0].job_id = 22,
      v => v['pages'][0].collection.method_version = 'competitor-page-headings-collect-v1', v => v['pages'][0].collection.source_sha256 = 'bad',
      v => v['pages'][0].collection.evidence.counts.p = true, v => v['pages'][0].collection.evidence.counts.p = 1001,
      v => v['pages'][0].collection.evidence.counts.p = null, v => v['pages'][0].collection.evidence.state = 'unavailable',
      v => v['pages'][0].collection.evidence.coverage = 'whole_site', v => v['pages'][0].collection.evidence.media = '<img src=x>',
      v => v['pages'][0].collection.observed_at = v['pages'][0].collection.evidence.observed_at = '2099-01-01T00:00:00.000001+00:00',
      ...[ORIGIN + '/selected/b', ORIGIN + '/', OWN + '/selected/a', 'https://other.example.invalid/selected/a'].map(url => (v: Row) => {
        v['pages'][0].collection.url = v['pages'][0].collection.requested_url = v['pages'][0].collection.evidence.url = url;
      }),
      v => v['selected_element_occurrences'][0][0] = true, v => v['selected_element_occurrences'][0][0] = '2',
      v => v['selected_element_occurrences'][0][0] = 3, v => v['selected_element_occurrences'][0][0] = null,
      v => v['selected_element_occurrences'][0].pop(), v => v['selected_element_occurrences'].push([0]),
      v => v['pages'][0].collection.source_sha256 = 'a'.repeat(24577),
    ];
    for (const change of changes) {
      await component.load(); api.formatsStructureValue = formatsStructure(); change(api.formatsStructureValue); select(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('table')).toBeNull();
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('withholds original count rows after late %s loss', async field => {
    const { component } = await screen(); api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
    };
    select(component); await component.compare(); expect(component.comparison()).toBeNull(); expect(component.ready()).toBe(false); expect(api.commands).toEqual([]);
  });
  it.each(['changed', 'denied', 'job-changed'])('withholds %s final original table confirmation', async loss => {
    const { component } = await screen(); let calls = 0;
    api.afterPair = () => { if (++calls === 2) {
      if (loss === 'changed') api.formatsStructureValue['pages'][0].collection.evidence.body_sha256 = 'f'.repeat(64);
      if (loss === 'denied') api.pairStatus = 403; if (loss === 'job-changed') api.rows[0].updated_at = OBSERVED;
    } };
    select(component); await component.compare(); expect(calls).toBe(2); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
  });
  it('clears tables on edits or mode changes and discards late old-project rows', async () => {
    const { harness, component } = await screen();
    for (const edit of [() => component.editUrl(ORIGIN + '/other'), () => component.editPair('current', '21'), () => component.load(), () => component.editReferenceStructure(false)]) {
      select(component); await component.compare(); expect(component.comparison()).not.toBeNull(); await edit(); expect(component.comparison()).toBeNull();
    }
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    api.formatsStructurePairs = []; select(component); const reading = component.compare(); await vi.waitFor(() => expect(api.formatsStructurePairs).toEqual([[21, 22]]));
    await harness.navigateByUrl('/competitor-page-formats/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, structure: formatsStructure() } }); await reading;
    expect(component.comparison()).toBeNull(); harness.fixture.destroy(); expect(component.frozenPair()).toBeNull();
  });
});

it('AccountApi two-page element structure uses exact scoped bodyless private GET only', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  await TestBed.inject(AccountApi).competitorPageFormatsStructure(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-page-formats/'));
  expect(calls).toHaveLength(1); const [url, options] = calls[0];
  expect(url).toContain('/organizations/7/projects/9/competitor-page-formats/structure/?first_job_id=21&second_job_id=22');
  expect(options.method).toBe('GET'); expect(options.body).toBeUndefined(); expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store');
});

describe('Private saved date syntax candidates', () => {
  let api: FixtureApi;
  beforeEach(() => {
    api = new FixtureApi(); api.rows = [{ ...job(), status: 'succeeded' }];
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen(path = '/competitor-page-dates/7/9') {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl(path, CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  it.each(['en', 'tr'] as const)('reads twice only deliberately and preserves original literals, duplicates, privacy and a named inert accessible table in %s', async (language) => {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    api.actor = 2; api.role = 'admin'; const { harness, component } = await screen(); harness.detectChanges();
    expect(component.dateCandidates()).toBeNull(); expect(api.candidateCalls).toEqual([]);
    const button = [...harness.routeNativeElement!.querySelectorAll('button')].find(row => row.textContent?.includes(component.t('Inspect saved date syntax candidates')));
    expect(button?.getAttribute('type')).toBe('button');
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.inspectDateCandidates(21); storage.mockRestore();
    expect(storage).not.toHaveBeenCalled(); expect(api.candidateCalls).toEqual([21, 21]); expect(component.dateCandidates()).toEqual(api.candidateValue);
    expect(component.evidence()).toEqual(datesEvidence()); expect(api.commands).toEqual([]); expect(api.synthCommands).toEqual([]);
    harness.detectChanges(); const region = harness.routeNativeElement!.querySelector(`[aria-label="${component.t('Stored date syntax candidate table')}"]`)!;
    expect(region.getAttribute('role')).toBe('region'); expect(region.getAttribute('tabindex')).toBe('0');
    expect(region.querySelector('caption')!.textContent).toContain(language === 'tr' ? 'Yinelenenler dahil' : 'including duplicates'); expect(region.querySelectorAll('th[scope=col]')).toHaveLength(5);
    expect(region.querySelectorAll('th[scope=row]')).toHaveLength(3); expect(region.textContent).toContain(component.t('Unavailable'));
    expect(region.querySelector('tbody tr td:nth-child(3)')!.getAttribute('lang')).toBe('en');
    expect(region.querySelector('tbody tr td:nth-child(4)')!.getAttribute('lang')).toBe(language);
    expect(harness.routeNativeElement!.querySelector('img, script')).toBeNull();
    expect(harness.routeNativeElement!.textContent).toContain(language === 'tr' ? 'doğrulanmamış beyanlar' : 'unverified declarations');
    const retained = component.dateCandidates(), original = component.evidence();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(component.dateCandidates()).toBe(retained); expect(component.evidence()).toBe(original); expect(api.candidateCalls).toEqual([21, 21]);
    component.productLanguage.set(language); harness.detectChanges();
    component.editUrl(ORIGIN + '/other'); expect(component.dateCandidates()).toBeNull(); expect(component.evidence()).toBeNull();
  });
  it('checks lossless known offsets, pre-epoch instants, and exact microsecond literal ordering without future rejection', async () => {
    const { component } = await screen();
    for (const [literal, instant, after] of [
      ['2026-01-01T03:00:00.000003+03:00', '2026-01-01T00:00:00.000003+00:00', true],
      ['2026-01-01T00:00:00.000002Z', OBSERVED, false],
      ['1969-12-31T23:59:59.999999Z', '1969-12-31T23:59:59.999999+00:00', false],
      ['2099-01-01T01:00:00+01:00', '2099-01-01T00:00:00.000000+00:00', true],
      ['0001-01-01T00:00:00Z', '0001-01-01T00:00:00.000000+00:00', false],
    ] as const) {
      api.candidateValue = dateCandidatePacket(); api.candidateValue['collection'].evidence.declarations = [{ property: 'article:modified_time', value: literal, truncated: false }];
      api.candidateValue['candidates'] = [{ declaration_index: 0, state: 'offset_literal', calendar_date: null, utc_instant: instant, after_observation: after }];
      await component.inspectDateCandidates(21); expect(component.dateCandidates()).toEqual(api.candidateValue);
    }
  });
  it('preserves unsupported, truncated and calendar-only syntax and empty versus whole unknown', async () => {
    const { component } = await screen();
    for (const literal of ['2026-02-30', '2026-01-01T00:00:00-00:00', '2026-01-01T00:00:00', '2026-01-01t00:00:00z',
      '2026-01-01T00:00:60Z', '2026-01-01T00:00:00.0000001Z', '0001-01-01T00:00:00+00:01', '9999-12-31T23:59:59-00:01']) {
      api.candidateValue = dateCandidatePacket(); api.candidateValue['collection'].evidence.declarations = [{ property: 'article:published_time', value: literal, truncated: false }];
      api.candidateValue['candidates'] = [{ declaration_index: 0, state: 'unsupported_literal', calendar_date: null, utc_instant: null, after_observation: null }];
      await component.inspectDateCandidates(21); expect(component.dateCandidates()).toEqual(api.candidateValue);
    }
    api.candidateValue = dateCandidatePacket(); api.candidateValue['collection'].evidence.declarations[0].truncated = true;
    Object.assign(api.candidateValue['candidates'][0], { state: 'truncated_literal', calendar_date: null });
    await component.inspectDateCandidates(21); expect(component.dateCandidates()).toEqual(api.candidateValue);
    api.candidateValue = dateCandidatePacket(); api.candidateValue['collection'].evidence.declarations = []; api.candidateValue['candidates'] = [];
    await component.inspectDateCandidates(21); expect(component.dateCandidates()!['candidates']).toEqual([]);
    Object.assign(api.candidateValue['collection'].evidence, { state: 'unavailable', reason: 'ambiguous_markup', declarations: null }); api.candidateValue['candidates'] = null;
    await component.inspectDateCandidates(21); expect(component.dateCandidates()!['candidates']).toBeNull();
  });
  it('rejects malformed, forged, cross-family or non-original candidate DTOs before display', async () => {
    const { component } = await screen();
    const mutations = [
      (row: Row) => row['method_version'] = 'other', (row: Row) => row['private_raw'] = 'secret',
      (row: Row) => row['source_current'] = false, (row: Row) => row['job_id'] = 22,
      (row: Row) => row['collection'] = formatsEvidence()['collection'], (row: Row) => row['candidates'].reverse(),
      (row: Row) => row['candidates'].pop(), (row: Row) => row['candidates'][0].after_observation = true,
      (row: Row) => row['candidates'][0].utc_instant = '2099-01-01T00:00:00.000000+00:00',
      (row: Row) => row['candidates'][0].calendar_date = '2026-01-01',
      (row: Row) => row['candidates'][1].state = 'calendar_literal', (row: Row) => row['candidates'][0].private = 'secret',
    ];
    for (const mutate of mutations) {
      api.candidateValue = dateCandidatePacket(); mutate(api.candidateValue); await component.load();
      const count = api.candidateCalls.length; await component.inspectDateCandidates(21);
      expect(api.candidateCalls.length).toBe(count + 1); expect(component.dateCandidates()).toBeNull(); expect(component.evidence()).toBeNull();
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'origins', 'authenticated', 'history'])('clears candidates on late %s scope or history loss', async field => {
    const { component } = await screen(); api.afterCandidates = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'origins') api.origins = []; if (field === 'authenticated') api.authenticated = false;
      if (field === 'history') api.rows = [];
    };
    await component.inspectDateCandidates(21); expect(component.dateCandidates()).toBeNull(); expect(component.evidence()).toBeNull(); expect(component.ready()).toBe(false);
    expect(api.candidateCalls).toEqual([21]); expect(component.pending()).toBeNull();
  });
  it('requires identical final private confirmation and clears late final authority or source changes', async () => {
    const { component } = await screen(); api.afterCandidates = () => {
      if (api.candidateCalls.length === 1) api.candidateValue['collection'].evidence.body_sha256 = 'f'.repeat(64);
    };
    await component.inspectDateCandidates(21); expect(api.candidateCalls).toEqual([21, 21]); expect(component.dateCandidates()).toBeNull();
    api.afterCandidates = null; api.candidateValue = dateCandidatePacket(); await component.load();
    api.afterCandidates = () => { if (api.candidateCalls.length === 4) api.role = 'viewer'; };
    await component.inspectDateCandidates(21); expect(component.dateCandidates()).toBeNull(); expect(component.evidence()).toBeNull();
  });
  it('denies cross-family actions and discards late private results after project switch or destruction', async () => {
    const { harness, component } = await screen();
    let release!: (result: ApiResult) => void; api.candidatePromise = new Promise<ApiResult>(resolve => release = resolve);
    const reading = component.inspectDateCandidates(21); await vi.waitFor(() => expect(api.candidateCalls).toEqual([21]));
    await harness.navigateByUrl('/competitor-page-dates/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, job: { ...job(), status: 'succeeded' }, candidates: dateCandidatePacket() } });
    await reading; expect(component.dateCandidates()).toBeNull();
    api.candidatePromise = null; const other = await harness.navigateByUrl('/competitor-page-formats/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(other.busy()).toBe(false));
    const count = api.candidateCalls.length; await other.inspectDateCandidates(21); expect(api.candidateCalls.length).toBe(count);
    harness.fixture.destroy(); expect(other.jobs()).toEqual([]); expect(other.dateCandidates()).toBeNull();
  });
});

it('AccountApi saved date syntax candidates use one exact bodyless scoped private GET', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  await TestBed.inject(AccountApi).competitorPageDateCandidates(7, 9, 21);
  const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('/api/organizations/7/projects/9/competitor-page-dates/21/candidates/');
  expect(options.method).toBe('GET'); expect(options.body).toBeUndefined(); expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store');
});

describe('Private Date candidate interval pairs', () => {
  let api: FixtureApi;
  beforeEach(() => {
    api = new FixtureApi(); api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }]; api.pairValue = datesComparison();
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-dates/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function select(component: CompetitorRoots) {
    component.editDateCandidatePair(true); component.editPair('previous', '21'); component.editPair('current', '22');
  }
  it('deliberately selects mutually exclusive saved modes and retains ordered index crossproducts with no new command', async () => {
    const { harness, component } = await screen(); harness.detectChanges();
    const modes = [...harness.routeNativeElement!.querySelectorAll<HTMLInputElement>('input[name=date-comparison-mode]')];
    expect(modes).toHaveLength(2); expect(modes.map(row => row.checked)).toEqual([true, false]); expect(modes.every(row => !!row.closest('label'))).toBe(true);
    component.editPair('previous', '21'); component.editPair('current', '22'); await component.compare(); expect(api.datesPairs).toEqual([[21, 22]]);
    select(component); const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); storage.mockRestore();
    expect(storage).not.toHaveBeenCalled(); expect(api.dateCandidatePairs).toEqual([[21, 22], [21, 22]]); expect(component.comparison()).toEqual(api.dateCandidatePairValue);
    expect(api.commands).toEqual([]); expect(api.synthCommands).toEqual([]); expect(api.candidateCalls).toEqual([]);
    harness.detectChanges(); const region = harness.routeNativeElement!.querySelector('[aria-label="Stored Date candidate interval table"]')!;
    expect(region.getAttribute('role')).toBe('region'); expect(region.getAttribute('tabindex')).toBe('0');
    expect(region.querySelector('caption')!.textContent).toContain('current minus previous'); expect(region.querySelectorAll('th[scope=col]')).toHaveLength(5);
    expect(region.querySelectorAll('th[scope=row]')).toHaveLength(5); expect(region.textContent).toContain(component.t('Unavailable'));
    expect(harness.routeNativeElement!.textContent).toContain('not matched actual publishing events'); expect(harness.routeNativeElement!.querySelector('img, script, #competitor-model')).toBeNull();
    component.editDateCandidatePair(false); expect(component.comparison()).toBeNull(); expect(component.previousJobId()).toBe(0);
  });
  it('validates exact signed microseconds outside safe Number precision and calendar-day leap gaps', async () => {
    const { component } = await screen();
    for (const [first, second, delta, firstFuture, secondFuture] of [
      ['9999-12-31T23:59:59.999999+00:00', '0001-01-01T00:00:00.000000+00:00', '-315537897599999999', true, false],
      ['2026-01-01T00:00:00.000001+00:00', '2026-01-01T00:00:00.000002+00:00', '1', false, false],
    ] as const) {
      api.dateCandidatePairValue = dateCandidatePair(); const row = api.dateCandidatePairValue; const original = row['comparison'];
      original.previous.evidence.declarations = [{ property: 'article:published_time', value: first, truncated: false }];
      original.current.evidence.declarations = [{ property: 'article:published_time', value: second, truncated: false }];
      row['previous_candidates'] = [{ declaration_index: 0, state: 'offset_literal', calendar_date: null, utc_instant: first, after_observation: firstFuture }];
      row['current_candidates'] = [{ declaration_index: 0, state: 'offset_literal', calendar_date: null, utc_instant: second, after_observation: secondFuture }];
      row['declaration_pair_candidates'] = [{ previous_declaration_index: 0, current_declaration_index: 0, state: 'offset_candidates', calendar_day_delta: null, utc_microsecond_delta: delta }];
      select(component); await component.compare(); expect(component.comparison()).toEqual(row);
    }
    const row = dateCandidatePair(); row['comparison'].previous.evidence.declarations = [{ property: 'article:published_time', value: '2024-02-28', truncated: false }];
    row['comparison'].current.evidence.declarations = [{ property: 'article:published_time', value: '2024-03-01', truncated: false }];
    for (const [key, value] of [['previous', '2024-02-28'], ['current', '2024-03-01']]) row[key + '_candidates'] = [{ declaration_index: 0, state: 'calendar_literal', calendar_date: value, utc_instant: null, after_observation: null }];
    row['declaration_pair_candidates'] = [{ previous_declaration_index: 0, current_declaration_index: 0, state: 'calendar_candidates', calendar_day_delta: 2, utc_microsecond_delta: null }];
    api.dateCandidatePairValue = row; select(component); await component.compare(); expect(component.comparison()).toEqual(row);
  });
  it('preserves whole unknown versus observed empty pairs without fabricating intervals', async () => {
    const { component } = await screen();
    for (const unavailable of [false, true]) {
      const row = dateCandidatePair(); row['comparison'].previous.evidence.declarations = [];
      row['previous_candidates'] = []; row['current_candidates'] = []; row['declaration_pair_candidates'] = [];
      row['comparison'].current.evidence.declarations = []; row['comparison'].declarations_changed = false;
      if (unavailable) {
        Object.assign(row['comparison'].current.evidence, { state: 'unavailable', reason: 'ambiguous_markup', declarations: null });
        Object.assign(row['comparison'], { comparable: false, declarations_changed: null, state: 'incomparable_unavailable_or_truncated_article_date_declarations' });
        row['current_candidates'] = null; row['declaration_pair_candidates'] = null;
      }
      api.dateCandidatePairValue = row; select(component); await component.compare(); expect(component.comparison()).toEqual(row);
    }
  });
  it('rejects malformed, rounded, partial, wrong-order or forged original-derived interval packets before display', async () => {
    const { component } = await screen();
    for (const mutate of [
      (row: Row) => row['method_version'] = 'other', (row: Row) => row['private'] = 'secret', (row: Row) => row['source_current'] = false,
      (row: Row) => row['comparison'] = formatsComparison(), (row: Row) => row['previous_candidates'][0].calendar_date = '2026-01-01',
      (row: Row) => row['current_candidates'].pop(), (row: Row) => row['declaration_pair_candidates'].reverse(),
      (row: Row) => row['declaration_pair_candidates'].pop(), (row: Row) => row['declaration_pair_candidates'][1].calendar_day_delta = 1,
      (row: Row) => row['declaration_pair_candidates'][1].utc_microsecond_delta = 0,
      (row: Row) => row['declaration_pair_candidates'][0].state = 'offset_candidates',
    ]) {
      api.dateCandidatePairValue = dateCandidatePair(); mutate(api.dateCandidatePairValue); await component.load(); select(component);
      const count = api.dateCandidatePairs.length; await component.compare(); expect(api.dateCandidatePairs.length).toBe(count + 1);
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'origins', 'authenticated', 'history'])('clears interval pairs on late %s authority or history loss', async field => {
    const { component } = await screen(); select(component); api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'origins') api.origins = []; if (field === 'authenticated') api.authenticated = false;
      if (field === 'history') api.rows = [];
    };
    await component.compare(); expect(component.comparison()).toBeNull(); expect(component.ready()).toBe(false); expect(component.dateCandidatePairMode()).toBe(false);
    expect(api.dateCandidatePairs).toEqual([[21, 22]]); expect(component.pending()).toBeNull();
  });
  it('requires an identical final private interval packet and clears mode edits before new reads', async () => {
    const { component } = await screen(); select(component); api.afterPair = () => {
      if (api.dateCandidatePairs.length === 1) api.dateCandidatePairValue['comparison'].current.evidence.body_sha256 = 'f'.repeat(64);
    };
    await component.compare(); expect(api.dateCandidatePairs).toEqual([[21, 22], [21, 22]]); expect(component.comparison()).toBeNull();
    api.afterPair = null; api.dateCandidatePairValue = dateCandidatePair(); await component.load(); select(component);
    await component.compare(); expect(component.comparison()).not.toBeNull(); component.editDateCandidatePair(false); expect(component.comparison()).toBeNull();
    expect(component.previousJobId()).toBe(0); expect(component.currentJobId()).toBe(0);
  });
  it('discards late interval GETs after a project switch and leaves non-Date comparison modes closed', async () => {
    const { harness, component } = await screen(); select(component);
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    const reading = component.compare(); await vi.waitFor(() => expect(api.dateCandidatePairs).toEqual([[21, 22]]));
    await harness.navigateByUrl('/competitor-page-dates/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, comparison: dateCandidatePair() } });
    await reading; expect(component.comparison()).toBeNull();
    api.pairPromise = null; const other = await harness.navigateByUrl('/competitor-page-formats/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(other.busy()).toBe(false)); other.editDateCandidatePair(true);
    expect(other.dateCandidatePairMode()).toBe(false); harness.fixture.destroy(); expect(other.comparison()).toBeNull();
  });
});

it('AccountApi Date candidate intervals use an exact scoped bodyless private comparison GET', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  await TestBed.inject(AccountApi).competitorPageDateCandidateComparison(7, 9, 21, 22);
  const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('/api/organizations/7/projects/9/competitor-page-dates/candidates/comparison/?previous_job_id=21&current_job_id=22');
  expect(options.method).toBe('GET'); expect(options.body).toBeUndefined(); expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store');
});

describe('Private two saved-page literal heading structure', () => {
  let api: FixtureApi;
  beforeEach(() => {
    api = new FixtureApi(); api.rows = [{ ...job(), id: 22, status: 'succeeded' }, { ...job(), status: 'succeeded' }];
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
  });
  async function screen() {
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl('/competitor-page-headings/7/9', CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); return { harness, component };
  }
  function select(component: CompetitorRoots, first = '21', second = '22') {
    component.editReferenceStructure(true); component.editPair('previous', first); component.editPair('current', second);
  }
  it.each(['en', 'tr'] as const)('requires labelled deliberate mode and confirms the exact original rows before an inert accessible count table without storage or AI in %s', async (language) => {
    api.preference = { status: 200, body: { language, current_ui_language: 'en', current_email_language: 'en' } };
    api.actor = 2; api.role = 'admin'; const { harness, component } = await screen(); harness.detectChanges();
    const native = harness.routeNativeElement!; const choice = native.querySelector<HTMLInputElement>('#competitor-reference-structure')!;
    expect(choice.checked).toBe(false); expect(native.querySelector('label[for=competitor-reference-structure]')).not.toBeNull();
    expect(native.querySelector('#competitor-destination-inventory')).toBeNull();
    await component.compare(); expect(api.headingsStructurePairs).toEqual([]);
    choice.checked = true; choice.dispatchEvent(new Event('change')); harness.detectChanges();
    expect(component.referenceStructureMode()).toBe(true); expect(component.referenceInventoryMode()).toBe(false);
    component.editPair('previous', '021'); component.editPair('current', '999'); await component.compare(); expect(api.headingsStructurePairs).toEqual([]);
    component.editPair('previous', '21'); component.editPair('current', '22');
    const storage = vi.spyOn(Storage.prototype, 'setItem'); await component.compare(); harness.detectChanges();
    expect(component.comparison()).toEqual(headingsStructure()); expect(api.headingsStructurePairs).toEqual([[21, 22], [21, 22]]);
    expect(api.formatsPairs).toEqual([]); expect(api.structurePairs).toEqual([]); expect(api.inventoryPairs).toEqual([]);
    expect(native.querySelector('table caption')!.textContent).toContain(component.t('Literal heading-level counts'));
    expect(native.querySelector(`[role=region][aria-label="${component.t('Two saved-page literal heading counts')}"][tabindex="0"]`)).not.toBeNull();
    expect(native.querySelectorAll('thead th[scope=col]')).toHaveLength(7); expect(native.querySelectorAll('tbody th[scope=row]')).toHaveLength(2);
    const retained = component.comparison();
    component.productLanguage.set(language === 'tr' ? 'en' : 'tr'); harness.detectChanges();
    expect(native.querySelector('#competitor-reference-structure')).toBe(choice); expect(choice.checked).toBe(true);
    expect(component.comparison()).toBe(retained); expect(component.previousJobId()).toBe(21); expect(component.currentJobId()).toBe(22);
    component.productLanguage.set(language); harness.detectChanges();
    expect(native.querySelectorAll('tbody td')).toHaveLength(12); expect(native.textContent).toContain(language === 'tr' ? 'yalnızca bu iki statik örnek durumunu' : 'only these two static sample states');
    expect(native.querySelector('img, script, #competitor-model')).toBeNull(); expect(native.querySelector('a[href*="competitor.example.invalid"]')).toBeNull();
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    await component.loadSyntheses(); await component.previewSynthesis(); await component.launchSynthesis(); await component.inspectSynthesis(61); await component.cancelSynthesis(61); expect(api.catalogCalls).toBe(0); expect(api.commands).toEqual([]); expect(api.synthCommands).toEqual([]); expect(api.synthDetails).toEqual([]);
    component.editReferenceStructure(false); expect(component.comparison()).toBeNull(); expect(component.previousJobId()).toBe(0);
    api.pairValue = headingsComparison(); component.editPair('previous', '21'); component.editPair('current', '22'); await component.compare();
    expect(component.comparison()).toEqual(headingsComparison()); expect(api.headingsPairs).toEqual([[21, 22]]);
  });
  it('retains row order and equal dates with independent observed zero versus whole unknown counts', async () => {
    const { harness, component } = await screen();
    for (const state of ['reverse', 'empty', 'first-unavailable', 'second-unavailable']) {
      const pages = headingsStructure()['pages'] as Row[];
      if (state === 'reverse') pages.reverse();
      else {
        const evidence = (pages[state === 'second-unavailable' ? 1 : 0]['collection'] as Row)['evidence'] as Row;
        evidence['counts'] = Object.fromEntries(Object.keys(evidence['counts'] as Row).map(name => [name, state === 'empty' ? 0 : null]));
        evidence['headings'] = state === 'empty' ? [] : null;
        if (state !== 'empty') Object.assign(evidence, { state: 'unavailable', reason: 'ambiguous_markup' });
      }
      api.headingsStructureValue = headingsStructure(pages); select(component, state === 'reverse' ? '22' : '21', state === 'reverse' ? '21' : '22');
      await component.compare(); expect(component.comparison()).toEqual(api.headingsStructureValue); harness.detectChanges();
      if (state.includes('unavailable')) expect(harness.routeNativeElement!.querySelector('tbody')!.textContent).toContain('Unavailable');
    }
  });
  it('rejects forged count matrices, coverage, originals, scope, URI and private fields before display', async () => {
    const { harness, component } = await screen();
    const changes: ((v: Row) => void)[] = [
      v => v['method_version'] = 'competitor-two-page-references-v1', v => v['organization_id'] = 8, v => v['project_id'] = 10,
      v => v['source_current'] = 1, v => v['interpretation'] = 'whole_site', v => v['raw_body'] = 'private',
      v => v['heading_levels'].reverse(), v => v['heading_levels'].pop(), v => v['all_rows_observed'] = 1, v => v['all_rows_observed'] = false,
      v => v['pages'].reverse(), v => v['pages'].pop(), v => v['pages'][0].job_id = 22,
      v => v['pages'][0].collection.method_version = 'competitor-page-elements-collect-v1', v => v['pages'][0].collection.source_sha256 = 'bad',
      v => v['pages'][0].collection.evidence.counts.h1 = true, v => v['pages'][0].collection.evidence.counts.h1 = 1001,
      v => v['pages'][0].collection.evidence.counts.h1 = null, v => v['pages'][0].collection.evidence.state = 'unavailable',
      v => v['pages'][0].collection.evidence.coverage = 'whole_site', v => v['pages'][0].collection.evidence.media = '<img src=x>',
      v => v['pages'][0].collection.observed_at = v['pages'][0].collection.evidence.observed_at = '2099-01-01T00:00:00.000001+00:00',
      ...[ORIGIN + '/selected/b', ORIGIN + '/', OWN + '/selected/a', 'https://other.example.invalid/selected/a'].map(url => (v: Row) => {
        v['pages'][0].collection.url = v['pages'][0].collection.requested_url = v['pages'][0].collection.evidence.url = url;
      }),
      v => v['selected_heading_occurrences'][0][0] = true, v => v['selected_heading_occurrences'][0][0] = '2',
      v => v['selected_heading_occurrences'][0][0] = 3, v => v['selected_heading_occurrences'][0][0] = null,
      v => v['selected_heading_occurrences'][0].pop(), v => v['selected_heading_occurrences'].push([0]),
      v => v['pages'][0].collection.source_sha256 = 'a'.repeat(24577),
    ];
    for (const change of changes) {
      await component.load(); api.headingsStructureValue = headingsStructure(); change(api.headingsStructureValue); select(component); await component.compare();
      expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull(); harness.detectChanges(); expect(harness.routeNativeElement!.querySelector('table')).toBeNull();
    }
  });
  it.each(['actor', 'role', 'restricted', 'revision', 'updated', 'origins', 'source', 'authenticated'])('withholds original count rows after late %s loss', async field => {
    const { component } = await screen(); api.afterPair = () => {
      if (field === 'actor') ++api.actor; if (field === 'role') api.role = 'member'; if (field === 'restricted') api.restricted = true;
      if (field === 'revision') ++api.revision; if (field === 'updated') api.updated = OBSERVED; if (field === 'origins') api.origins = [];
      if (field === 'source') api.source = 'undecided'; if (field === 'authenticated') api.authenticated = false;
    };
    select(component); await component.compare(); expect(component.comparison()).toBeNull(); expect(component.ready()).toBe(false); expect(api.commands).toEqual([]);
  });
  it.each(['changed', 'denied', 'job-changed'])('withholds %s final original table confirmation', async loss => {
    const { component } = await screen(); let calls = 0;
    api.afterPair = () => { if (++calls === 2) {
      if (loss === 'changed') api.headingsStructureValue['pages'][0].collection.evidence.body_sha256 = 'f'.repeat(64);
      if (loss === 'denied') api.pairStatus = 403; if (loss === 'job-changed') api.rows[0].updated_at = OBSERVED;
    } };
    select(component); await component.compare(); expect(calls).toBe(2); expect(component.comparison()).toBeNull(); expect(component.frozenPair()).toBeNull();
  });
  it('clears tables on edits or mode changes and discards late old-project rows', async () => {
    const { harness, component } = await screen();
    for (const edit of [() => component.editUrl(ORIGIN + '/other'), () => component.editPair('current', '21'), () => component.load(), () => component.editReferenceStructure(false)]) {
      select(component); await component.compare(); expect(component.comparison()).not.toBeNull(); await edit(); expect(component.comparison()).toBeNull();
    }
    let release!: (result: ApiResult) => void; api.pairPromise = new Promise<ApiResult>(resolve => release = resolve);
    api.headingsStructurePairs = []; select(component); const reading = component.compare(); await vi.waitFor(() => expect(api.headingsStructurePairs).toEqual([[21, 22]]));
    await harness.navigateByUrl('/competitor-page-headings/7/10', CompetitorRoots); await harness.fixture.whenStable();
    release({ status: 200, body: { organization_id: 7, project_id: 9, structure: headingsStructure() } }); await reading;
    expect(component.comparison()).toBeNull(); harness.fixture.destroy(); expect(component.frozenPair()).toBeNull();
  });
});

it('AccountApi original two-page heading structure uses exact scoped bodyless private GET only', async () => {
  const fetcher = vi.fn(async () => ({ status: 200, json: async () => ({}) }));
  TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { defaultView: { fetch: fetcher }, cookie: 'csrftoken=fixture' } }] });
  await TestBed.inject(AccountApi).competitorPageHeadingsStructure(7, 9, 21, 22);
  const calls = (fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.includes('/competitor-page-headings/'));
  expect(calls).toHaveLength(1); const [url, options] = calls[0];
  expect(url).toContain('/organizations/7/projects/9/competitor-page-headings/structure/?first_job_id=21&second_job_id=22');
  expect(options.method).toBe('GET'); expect(options.body).toBeUndefined(); expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store');
});


describe('Private competitor interface language draft', () => {
  afterEach(() => vi.restoreAllMocks());
  async function screen(api: FixtureApi, path = '/competitor-roots/7/9') {
    TestBed.configureTestingModule({ providers: [provideRouter(workspaceRoutes), { provide: AccountApi, useValue: api }] });
    const harness = await RouterTestingHarness.create(); const component = await harness.navigateByUrl(path, CompetitorRoots);
    await harness.fixture.whenStable(); await vi.waitFor(() => expect(component.busy()).toBe(false)); harness.detectChanges();
    return { harness, component };
  }
  it('renders all ten fixed competitor profiles as private Turkish drafts without choosing consent or translating protocols', async () => {
    const profiles = [
      ['roots', 'Seçilen rakip kökün gözlemleri'], ['schema-roots', 'Seçilen rakibin şema türü etiketleri'],
      ['links-roots', 'Seçilen rakip kökün bağlantı kategorileri'], ['pages', 'Seçilen rakip sayfanın meta verileri'],
      ['page-headings', 'Seçilen rakip sayfanın sözcüğü sözcüğüne başlıkları'], ['heading-topics', 'Kaydedilmiş tek başlık gözleminden konu hipotezleri'],
      ['page-destinations', 'Seçilen rakip sayfanın aynı kökenli referansları'], ['page-dates', 'Seçilen rakip sayfanın makale tarihi beyanları'],
      ['page-formats', 'Seçilen rakibin statik içerik öğesi sayıları'], ['lighthouse', 'Seçilen rakibin Lighthouse laboratuvar örneği'],
    ];
    const metadata: Record<string, [string, string]> = {
  "roots": [
    "Private selected competitor root observations — OrganicSEOOps",
    "Özel seçilen rakip kök gözlemleri — OrganicSEOOps"
  ],
  "schema-roots": [
    "Private selected competitor schema labels — OrganicSEOOps",
    "Özel seçilen rakip şema etiketleri — OrganicSEOOps"
  ],
  "links-roots": [
    "Private selected competitor root link categories — OrganicSEOOps",
    "Özel seçilen rakip kök bağlantı kategorileri — OrganicSEOOps"
  ],
  "pages": [
    "Private selected competitor page metadata — OrganicSEOOps",
    "Özel seçilen rakip sayfa meta verileri — OrganicSEOOps"
  ],
  "page-headings": [
    "Private selected competitor page literal headings — OrganicSEOOps",
    "Özel seçilen rakip sayfanın sözcüğü sözcüğüne başlıkları — OrganicSEOOps"
  ],
  "heading-topics": [
    "Private single-heading topic hypotheses — OrganicSEOOps",
    "Özel tek başlık konu hipotezleri — OrganicSEOOps"
  ],
  "page-destinations": [
    "Private selected competitor page same-origin references — OrganicSEOOps",
    "Özel seçilen rakip sayfanın aynı kökenli referansları — OrganicSEOOps"
  ],
  "page-dates": [
    "Private selected competitor page article date declarations — OrganicSEOOps",
    "Özel seçilen rakip sayfanın makale tarihi beyanları — OrganicSEOOps"
  ],
  "page-formats": [
    "Private selected competitor static content-element counts — OrganicSEOOps",
    "Özel seçilen rakibin statik içerik öğesi sayıları — OrganicSEOOps"
  ],
  "lighthouse": [
    "Private selected competitor Lighthouse lab sample — OrganicSEOOps",
    "Özel seçilen rakibin Lighthouse laboratuvar örneği — OrganicSEOOps"
  ]
};
    for (const [profile, title] of profiles) {
      TestBed.resetTestingModule(); const api = new FixtureApi();
      api.preference = { status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'tr' } };
      const { harness, component } = await screen(api, `/competitor-${profile}/7/9`); const native = harness.routeNativeElement!;
      expect(TestBed.inject(Title).getTitle()).toBe(metadata[profile][1]);
      const controls = [...native.querySelectorAll('input, select')], values = controls.map(row => (row as HTMLInputElement).value);
      component.productLanguage.set('en'); harness.detectChanges();
      expect(TestBed.inject(Title).getTitle()).toBe(metadata[profile][0]);
      expect([...native.querySelectorAll('input, select')]).toEqual(controls); expect(controls.map(row => (row as HTMLInputElement).value)).toEqual(values);
      component.productLanguage.set('tr'); harness.detectChanges();
      expect(native.querySelector('section')!.getAttribute('lang')).toBe('tr'); expect(native.querySelector('h1')!.textContent).toBe(title);
      expect(native.textContent).toContain('iki dilli onay bekleniyor'); expect(native.textContent).toContain('90 günlük');
      expect(native.querySelector('label[for=competitor-origin]')!.textContent).toBe('Kaydedilmiş yapılandırılmış köken');
      expect(native.querySelector('option[value=""]')!.textContent).toBe('Kaydedilmiş tek rakip seçin');
      expect(native.querySelector('option[value="' + ORIGIN + '"]')!.getAttribute('lang')).toBe('');
      const rights = [...native.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
      expect(rights).toHaveLength(profile === 'lighthouse' ? 4 : 3); expect(rights.every(row => row.required && !row.checked)).toBe(true);
      if (profile === 'lighthouse') {
        expect(native.querySelector<HTMLSelectElement>('#competitor-device')!.value).toBe('mobile');
        expect(native.querySelector('option[value=mobile]')!.textContent).toBe('Mobil');
      }
      component.error.set('Exact current source, three declarations or collection allowance unavailable. No collection command sent.'); harness.detectChanges();
      expect(native.querySelector('[role=alert]')!.textContent).toBe('Tam güncel kaynak, üç beyan veya toplama hakkı kullanılamıyor. Toplama komutu gönderilmedi.');
      expect(native.querySelector('[role=alert]')!.getAttribute('lang')).toBe('tr');
      component.message.set('Original protocol caption'); harness.detectChanges();
      expect(native.querySelector('[role=status][lang=en]')!.textContent).toBe('Original protocol caption');
      expect(api.commands).toEqual([]); expect(api.previews).toBe(0); expect(api.synthCommands).toEqual([]); expect(api.catalogCalls).toBe(0);
      harness.fixture.destroy(); TestBed.inject(Title).setTitle('Next route — OrganicSEOOps');
      component.productLanguage.set('en'); TestBed.tick(); expect(TestBed.inject(Title).getTitle()).toBe('Next route — OrganicSEOOps');
    }
  });
  it('keeps malformed denied unavailable incompatible and production preferences English and drops destroyed preference replies', async () => {
    const buildEnvironment = environment as { production: boolean }, production = buildEnvironment.production;
    try {
      for (const mode of ['invalid', 'incompatible', 'signed-out', 'unavailable', 'production'] as const) {
        TestBed.resetTestingModule(); const api = new FixtureApi(); buildEnvironment.production = mode === 'production';
        api.preference = mode === 'unavailable' ? new Error('private preference error') : mode === 'signed-out' ? { status: 401, body: {} }
          : { status: 200, body: { language: mode === 'invalid' ? ['tr'] : 'tr', current_ui_language: mode === 'incompatible' ? 'tr' : 'en', current_email_language: 'en' } };
        const { harness, component } = await screen(api); const native = harness.routeNativeElement!;
        expect(TestBed.inject(Title).getTitle()).toBe('Private selected competitor root observations — OrganicSEOOps');
        expect(component.uiLanguage()).toBe('en'); expect(native.querySelector('section')!.getAttribute('lang')).toBe('en');
        expect(native.querySelector('h1')!.textContent).toBe('Selected competitor root observations');
        expect(native.textContent).not.toContain('private preference error'); expect(native.textContent).not.toContain('incelenmemiş Türkçe');
        expect(component.collectionPermission()).toBe(false); expect(api.commands).toEqual([]); harness.fixture.destroy();
      }
      TestBed.resetTestingModule(); buildEnvironment.production = false; const api = new FixtureApi(); let resolve!: (reply: ApiResult) => void;
      vi.spyOn(api, 'productLanguage').mockReturnValue(new Promise(done => resolve = done));
      const { harness, component } = await screen(api); harness.fixture.destroy();
      resolve({ status: 200, body: { language: 'tr', current_ui_language: 'en', current_email_language: 'en' } }); await Promise.resolve();
      expect(component.productLanguage()).toBe('en'); expect(api.commands).toEqual([]);
    } finally { buildEnvironment.production = production; }
  });
});
