import { Component, Input, OnChanges, OnDestroy, signal } from '@angular/core';
import { draftProductLanguage } from '../product-language';
import { AccountApi } from '../account/account-api';
import { calendar, microseconds } from './utc-date';

type Job = { id: number; strategy: string; grain: string };
type Observation = { id: number; source: string; collected_at: string; result: Record<string, unknown> };
type Period = { start: string; end: string; eligible_days: 'unknown'; calendar_days: number };
type Value = { period: Period; p75: number | string | null; grade: string; state: string };
type Comparison = { metric: string; state: keyof typeof states; unit: string; observations: Value[];
  overlap_calendar_days: number | null; period_contract: string; sample_count: string; interpretation: string };
type History = { assessed_at: string; collected_at: string; state: string; comparisons: Comparison[];
  form_factor?: string; requested_grain?: string; observed_grain?: string; origin_fallback?: boolean;
  url_normalization?: string; source_period_count?: number };
type PolicyRow = { metric: string; unit: string; state: keyof typeof policyStates;
  minimum_absolute_increase: string; minimum_relative_increase_fraction: string;
  absolute_increase: string | null; absolute_floor_met: boolean | null; relative_floor_met: boolean | null;
  sample_sufficiency: 'unknown'; statistical_significance: 'unknown' };
type Policy = { rows: PolicyRow[]; source_fingerprint: string };
const states = {
  threshold_worsening_candidate: 'Field threshold worsening candidate',
  no_threshold_worsening_observed: 'No threshold worsening observed in these two periods',
  unknown_insufficient_eligible_periods: 'Unknown: insufficient eligible periods',
  incomparable_source_periods: 'Original source periods are not comparable under the weekly 28-day contract',
};
const interpretation = 'field_threshold_candidate_not_confirmed_seo_regression_or_causal_change';
const policyStates = { ...states,
  material_threshold_worsening_candidate: 'Material field threshold worsening candidate under product heuristics',
  below_material_change_floor: 'Grade worsened, but below one or both product material-change floors',
  unknown_relative_zero_baseline: 'Unknown: relative increase cannot be assessed from a zero baseline',
  unknown_exact_numeric_precision: 'Unknown: original values exceed supported exact arithmetic precision',
};
const day = 86400000;
const id = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
function keys(value: unknown, fields: string): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === fields.split(',').sort().join(',');
}

@Component({
  selector: 'app-project-crux-history',
  template: `
    <section [attr.lang]="uiLanguage()" [attr.aria-label]="t('Original CrUX history inspection')">
      <h5>{{ t("Original CrUX field history and actual collection periods") }}</h5>
      <p>{{ t("Explicit inspection checks this selected stored source. It does not collect new data, send alerts or save alert consent.") }}</p>
      <button type="button" [disabled]="busy()" (click)="inspect()">{{ t("Inspect / refresh original CrUX history") }}</button>
      <button type="button" [disabled]="busy()" (click)="inspect(true)">{{ t("Inspect / refresh CrUX material policy") }}</button>
      @if (busy()) { <p role="status">{{ t("Checking selected original field evidence for this observation.") }}</p> }
      @if (error()) { <p role="alert">{{ t("Selected CrUX evidence is unavailable for this selection. Refresh the audit before inspecting again.") }}</p> }
      @if (history(); as result) {
        <p>{{ t("Collected") }} {{ result.collected_at }} {{ t("(UTC); server assessment") }} {{ result.assessed_at }} (UTC).</p>
        @if (result.state === 'unknown_original_raw_integrity') {
          <p role="status">{{ t("Original raw integrity unknown for this legacy observation. No comparison was reconstructed; missing evidence is not passing.") }}</p>
        } @else {
          <p>{{ t("Original stored-response integrity checked;") }} <span lang="en">{{ result.form_factor }}</span> · {{ t("requested") }} <span lang="en">{{ result.requested_grain }}</span>, {{ t("observed") }} <span lang="en">{{ result.observed_grain }}</span> · {{ t(result.origin_fallback ? 'origin fallback (not page data)' : 'no origin fallback') }} · {{ t("normalization") }} <span lang="en">{{ result.url_normalization }}</span>.</p>
          <p>{{ result.source_period_count }} {{ t("original source periods; only the last one or two are shown. Collection dates are PST (fixed UTC−8), not the project timezone.") }}</p>
          <p>{{ t("Eligible days and sample counts are unknown. Field p75 grades are not lab scores. Overlapping windows do not prove a causal change, statistical significance or a confirmed SEO regression.") }}</p>
          <ul>@for (row of result.comparisons; track row.metric) {
            <li><strong><span lang="en">{{ row.metric }}</span></strong>: {{ stateLabel(row.state) }}.
              @for (value of row.observations; track $index) {
                <p>{{ value.period.start }} {{ t("to") }} {{ value.period.end }} (PST), {{ value.period.calendar_days }} {{ t("inclusive calendar days: p75") }} {{ value.p75 ?? t('unavailable') }} <span lang="en">{{ row.unit }}</span> · <span lang="en">{{ value.grade }}</span> · <span lang="en">{{ value.state }}</span>. {{ t("Eligible days unknown.") }}</p>
              }
              <p>{{ t("Actual overlap:") }} {{ row.overlap_calendar_days === null ? t('unknown: only one period') : row.overlap_calendar_days + ' ' + t('calendar days') }}. {{ t(row.period_contract === 'weekly_28_day_windows' ? 'Two 28-day windows, seven-day cadence.' : 'Weekly 28-day comparison unavailable.') }} {{ t("Sample count unknown.") }}</p>
            </li>
          }</ul>
        }
      }
      @if (policy(); as result) {
        <h5>{{ t("Product material-change policy v1") }}</h5>
        <p>{{ t("Requires grade worsening and both inclusive floors: 20% relative increase and 500 ms LCP, 50 ms INP or 0.05 unitless CLS. These are product heuristics, not provider noise estimates. Large within-grade changes are ineligible.") }}</p>
        <p>{{ t("Sample sufficiency and statistical significance are unknown. This inspection establishes neither confirmed SEO regression, causality, alert consent nor delivery.") }}</p>
        <p>{{ t("Server source-policy reference") }} {{ result.source_fingerprint }}{{ t(". Its shape is checked; the browser cannot independently authenticate the server's full original metadata.") }}</p>
        @if (!result.rows.length) { <p>{{ t("Legacy original integrity unknown; no material comparison reconstructed.") }}</p> }
        <ul>@for (row of result.rows; track row.metric) {
          <li><strong><span lang="en">{{ row.metric }}</span></strong>: {{ policyLabel(row.state) }}.
            <p>{{ t("Absolute floor") }} {{ row.minimum_absolute_increase }} <span lang="en">{{ row.unit }}</span>{{ t("; relative floor 20%.") }}
              {{ t("Exact absolute increase") }} {{ row.absolute_increase ?? t('unknown / not evaluated') }} <span lang="en">{{ row.unit }}</span>.
              {{ t("Absolute floor") }} {{ floorLabel(row.absolute_floor_met) }}{{ t("; relative floor") }} {{ floorLabel(row.relative_floor_met) }}.</p>
          </li>
        }</ul>
      }
    </section>`,
  styles: `section { margin-block: 1rem; } li { margin-block: .6rem; overflow-wrap: anywhere; }`,
})
export class ProjectCruxHistory implements OnChanges, OnDestroy {
  @Input() organizationId = 0;
  @Input() projectId = 0;
  @Input() job: Job | null = null;
  @Input() observation: Observation | null = null;
  @Input() revision = 0;
  @Input() language: 'en' | 'tr' = 'en';
  uiLanguage() { return draftProductLanguage(this.language); }
  t(text: string) { return this.uiLanguage() === 'tr' ? cruxTurkish[text] ?? text : text; }
  readonly history = signal<History | null>(null);
  readonly policy = signal<Policy | null>(null);
  readonly busy = signal(false);
  readonly error = signal(false);
  private generation = 0;
  constructor(private readonly api: AccountApi) {}
  ngOnChanges() { this.clear(); }
  ngOnDestroy() { this.clear(); }
  private clear() { this.generation++; this.history.set(null); this.policy.set(null); this.busy.set(false); this.error.set(false); }
  stateLabel(state: Comparison['state']) { return this.t(states[state]); }
  policyLabel(state: PolicyRow['state']) { return this.t(policyStates[state]); }
  floorLabel(value: boolean | null) { return this.t(value === null ? 'unknown / not evaluated' : value ? 'met' : 'not met'); }
  private selection() {
    const job = this.job, observation = this.observation;
    if (![this.organizationId, this.projectId, job?.id, observation?.id].every(id)
        || !job || !observation || observation.source !== 'crux_history'
        || microseconds(observation.collected_at) === null
        || !['mobile', 'desktop', 'tablet'].includes(job.strategy) || !['page', 'origin'].includes(job.grain)) return null;
    const result = observation.result;
    if (!result || typeof result !== 'object' || Array.isArray(result)
        || result['requested_grain'] !== job.grain || !['page', 'origin'].includes(result['observed_grain'] as string)
        || typeof result['origin_fallback'] !== 'boolean'
        || !['none', 'provider_normalized'].includes(result['url_normalization'] as string)) return null;
    return { organization: this.organizationId, project: this.projectId, job: job.id, observation: observation.id,
      collected: observation.collected_at, device: { mobile: 'PHONE', desktop: 'DESKTOP', tablet: 'TABLET' }[job.strategy],
      requested: job.grain, observed: result['observed_grain'], fallback: result['origin_fallback'],
      normalization: result['url_normalization'], revision: this.revision };
  }
  async inspect(material = false) {
    this.clear();
    const selected = this.selection();
    if (!selected) { this.error.set(true); return; }
    const generation = this.generation, original = JSON.stringify(selected);
    const current = () => generation === this.generation && JSON.stringify(this.selection()) === original;
    this.busy.set(true);
    try {
      const response = await (material ? this.api.projectCruxMaterialPolicy(selected.organization, selected.project, selected.observation)
        : this.api.projectCruxHistory(selected.organization, selected.project, selected.observation));
      if (!current()) return;
      const policy = material && response.status === 200 ? readPolicy(response.body, selected) : null;
      const history = material ? policy?.history : response.status === 200 ? readHistory(response.body, selected) : null;
      if (!history) throw new Error();
      this.history.set(structuredClone(history));
      if (policy) this.policy.set(structuredClone(policy.policy));
    } catch { if (current()) this.error.set(true); }
    finally { if (generation === this.generation) this.busy.set(false); }
  }
}

function readPolicy(body: Record<string, unknown>, selected: NonNullable<ReturnType<ProjectCruxHistory['selection']>>) {
  if (!keys(body, 'method_version,source,state,rows,interpretation,source_fingerprint,assessed_at')
      || body['method_version'] !== 'material-crux-threshold-candidate-v1'
      || body['interpretation'] !== 'product_material_change_heuristic_not_statistical_seo_regression_causality_consent_or_delivery'
      || typeof body['source_fingerprint'] !== 'string' || !/^[a-f0-9]{64}$/.test(body['source_fingerprint'])
      || !body['source'] || typeof body['source'] !== 'object' || Array.isArray(body['source'])
      || Object.hasOwn(body['source'], 'assessed_at') || !Array.isArray(body['rows'])) return null;
  const history = readHistory({ ...body['source'], assessed_at: body['assessed_at'] }, selected);
  if (!history || body['state'] !== (history.state === 'unknown_original_raw_integrity' ? history.state
      : 'assessed_original_field_threshold_candidates') || body['rows'].length !== history.comparisons.length) return null;
  for (const [index, row] of body['rows'].entries()) {
    const comparison = history.comparisons[index], floor = ['500', '50', '0.05'][index];
    if (!keys(row, 'metric,unit,state,minimum_absolute_increase,minimum_relative_increase_fraction,absolute_increase,absolute_floor_met,relative_floor_met,sample_sufficiency,statistical_significance')
        || row['metric'] !== comparison.metric || row['unit'] !== comparison.unit
        || row['minimum_absolute_increase'] !== floor || row['minimum_relative_increase_fraction'] !== '0.20'
        || row['sample_sufficiency'] !== 'unknown' || row['statistical_significance'] !== 'unknown') return null;
    let state: string = comparison.state, absolute: boolean | null = null, relative: boolean | null = null;
    if (comparison.state === 'threshold_worsening_candidate') {
      const previous = decimal(String(comparison.observations[0].p75))!, current = decimal(String(comparison.observations[1].p75))!;
      const minimum = decimal(floor)!;
      if (previous.coefficient === 0n) state = 'unknown_relative_zero_baseline';
      else {
        const exponent = [previous.exponent, current.exponent, minimum.exponent].reduce((a, b) => a < b ? a : b);
        const precision = [0n, previous.adjusted, current.adjusted, minimum.adjusted].reduce((a, b) => a > b ? a : b) - exponent + 4n;
        if (precision > 64n) state = 'unknown_exact_numeric_precision';
        else {
          const before = scaled(previous, exponent), increase = scaled(current, exponent) - before;
          const declared = typeof row['absolute_increase'] === 'string' ? decimal(row['absolute_increase'], 90) : null;
          if (!declared || declared.exponent < -64n || declared.exponent > 64n) return null;
          const common = exponent < declared.exponent ? exponent : declared.exponent;
          if (increase * 10n ** (exponent - common) !== scaled(declared, common)) return null;
          absolute = increase >= scaled(minimum, exponent); relative = increase * 5n >= before;
          state = absolute && relative ? 'material_threshold_worsening_candidate' : 'below_material_change_floor';
        }
      }
    }
    if (row['state'] !== state || row['absolute_floor_met'] !== absolute || row['relative_floor_met'] !== relative
        || absolute === null && row['absolute_increase'] !== null) return null;
  }
  return { history, policy: { rows: body['rows'] as PolicyRow[], source_fingerprint: body['source_fingerprint'] } };
}

// Preserve the source exponent/trailing zeros to match the server's precision ceiling before allocation.
function decimal(value: string, limit = 20) {
  if (value.length > limit) return null;
  const match = /^([+-]?)(\d+)(?:\.(\d*))?(?:[Ee]([+-]?\d+))?$/.exec(value);
  if (!match) return null;
  const digits = (match[2] + (match[3] || '')).replace(/^0+/, '') || '0';
  const exponent = BigInt(match[4] || 0) - BigInt(match[3]?.length || 0);
  return { coefficient: BigInt((match[1] === '-' ? '-' : '') + digits), exponent,
    adjusted: exponent + BigInt(digits.length - 1) };
}
function scaled(value: NonNullable<ReturnType<typeof decimal>>, exponent: bigint) {
  return value.coefficient * 10n ** (value.exponent - exponent);
}

function readHistory(body: Record<string, unknown>, selected: NonNullable<ReturnType<ProjectCruxHistory['selection']>>): History | null {
  const base = 'method_version,project_id,observation_id,job_id,assessed_at,collected_at,raw_sha256,state,comparisons';
  const legacy = body['state'] === 'unknown_original_raw_integrity';
  if (!keys(body, base + (legacy ? '' : ',source_method,form_factor,requested_grain,observed_grain,origin_fallback,url_normalization,collection_timezone,source_period_count'))
      || body['method_version'] !== 'current-crux-history-threshold-source-v1'
      || body['project_id'] !== selected.project || body['observation_id'] !== selected.observation || body['job_id'] !== selected.job
      || microseconds(body['collected_at']) !== microseconds(selected.collected)
      || microseconds(body['assessed_at']) === null || microseconds(body['collected_at']) === null
      || microseconds(body['assessed_at'])! < microseconds(body['collected_at'])!
      || !Array.isArray(body['comparisons'])) return null;
  if (legacy) return body['raw_sha256'] === null && body['comparisons'].length === 0 ? body as History : null;
  if (body['state'] !== 'available_original_field_history' || typeof body['raw_sha256'] !== 'string'
      || !/^[a-f0-9]{64}$/.test(body['raw_sha256']) || body['source_method'] !== 'crux-p75-v1'
      || body['form_factor'] !== selected.device || body['requested_grain'] !== selected.requested
      || body['observed_grain'] !== selected.observed || body['origin_fallback'] !== selected.fallback
      || body['url_normalization'] !== selected.normalization
      || body['origin_fallback'] !== (selected.requested === 'page' && selected.observed === 'origin')
      || selected.requested === 'origin' && selected.observed !== 'origin'
      || selected.observed === 'origin' && selected.normalization !== 'none'
      || body['collection_timezone'] !== 'PST_fixed_UTC_minus_8'
      || !id(body['source_period_count']) || (body['source_period_count'] as number) > 40
      || body['comparisons'].length !== 3) return null;
  const count = Math.min(2, body['source_period_count'] as number);
  let periods = '';
  const collectedDay = Math.floor(Number(microseconds(body['collected_at'])! / 1000n) / day - 8 / 24) * day;
  for (const [index, row] of body['comparisons'].entries()) {
    if (!keys(row, 'metric,state,unit,observations,overlap_calendar_days,period_contract,sample_count,interpretation')
        || row['metric'] !== ['LCP', 'INP', 'CLS'][index] || row['unit'] !== (index === 2 ? 'unitless' : 'ms')
        || row['sample_count'] !== 'unknown' || row['interpretation'] !== interpretation
        || !Array.isArray(row['observations']) || row['observations'].length !== count) return null;
    const dates: { start: number; end: number; span: number }[] = [];
    for (const value of row['observations']) {
      if (!keys(value, 'period,p75,grade,state') || !keys(value['period'], 'start,end,eligible_days,calendar_days')) return null;
      const period = value['period'], start = calendar(period['start']), end = calendar(period['end']);
      if (start === null || end === null || start > end || end > collectedDay || period['eligible_days'] !== 'unknown'
          || period['calendar_days'] !== (end - start) / day + 1 || dates.length && end <= dates[0].end) return null;
      dates.push({ start, end, span: (end - start) / day + 1 });
      if (value['state'] === 'unavailable') {
        if (value['p75'] !== null || value['grade'] !== 'unknown') return null;
      } else {
        const p75 = value['p75'];
        const grade = index === 2 ? clsGrade(p75) : typeof p75 === 'number' && Number.isSafeInteger(p75)
          && p75 >= 0 && p75 <= 10000000 ? p75 <= (index === 0 ? 2500 : 200) ? 'good'
            : p75 > (index === 0 ? 4000 : 500) ? 'poor' : 'needs_improvement' : null;
        if (value['state'] !== 'observed' || grade === null || value['grade'] !== grade) return null;
      }
    }
    const signature = JSON.stringify(row['observations'].map(value => value.period));
    if (index && signature !== periods) return null;
    periods = signature;
    const overlap = count === 1 ? null : Math.max(0, (Math.min(dates[0].end, dates[1].end) - Math.max(dates[0].start, dates[1].start)) / day + 1);
    const comparable = count === 2 && dates.every(date => date.span === 28)
      && dates[1].start - dates[0].start === 7 * day && dates[1].end - dates[0].end === 7 * day;
    const rank = ['good', 'needs_improvement', 'poor'];
    const expected = count < 2 || row['observations'].some(value => value.state !== 'observed') ? 'unknown_insufficient_eligible_periods'
      : !comparable ? 'incomparable_source_periods'
      : rank.indexOf(row['observations'][1].grade) > rank.indexOf(row['observations'][0].grade) ? 'threshold_worsening_candidate' : 'no_threshold_worsening_observed';
    if (row['state'] !== expected || row['overlap_calendar_days'] !== overlap
        || row['period_contract'] !== (comparable ? 'weekly_28_day_windows' : 'not_comparable')) return null;
  }
  return body as History;
}

// Compare Decimal source strings exactly: Number would round values just above a grade boundary.
function clsGrade(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 20) return null;
  const match = /^([+-]?)(\d+)(?:\.(\d*))?(?:[Ee]([+-]?\d+))?$/.exec(value);
  if (!match) return null;
  const digits = (match[2] + (match[3] || '')).replace(/^0+/, '');
  if (!digits) return 'good';
  if (match[1] === '-') return null;
  const order = BigInt(digits.length - (match[3]?.length || 0)) + BigInt(match[4] || 0);
  const exceeds = (boundary: string, boundaryOrder: bigint) => order !== boundaryOrder ? order > boundaryOrder
    : digits.padEnd(Math.max(digits.length, boundary.length), '0') > boundary.padEnd(Math.max(digits.length, boundary.length), '0');
  if (exceeds('1', 3n)) return null; // Maximum supported CLS is 100.
  return !exceeds('1', 0n) ? 'good' : exceeds('25', 0n) ? 'poor' : 'needs_improvement';
}

const cruxTurkish: Readonly<Record<string, string>> = {
  "Original CrUX history inspection": "Özgün CrUX geçmişi incelemesi",
  "Original CrUX field history and actual collection periods": "Özgün CrUX saha geçmişi ve gerçek toplama dönemleri",
  "Explicit inspection checks this selected stored source. It does not collect new data, send alerts or save alert consent.": "Açıkça başlatılan inceleme, seçilen kayıtlı kaynağı kontrol eder. Yeni veri toplamaz, uyarı göndermez veya uyarı onayını kaydetmez.",
  "Inspect / refresh original CrUX history": "Özgün CrUX geçmişini incele / yenile",
  "Inspect / refresh CrUX material policy": "CrUX önemli değişiklik politikasını incele / yenile",
  "Checking selected original field evidence for this observation.": "Bu gözlem için seçilen özgün saha kanıtları kontrol ediliyor.",
  "Selected CrUX evidence is unavailable for this selection. Refresh the audit before inspecting again.": "Bu seçim için seçilen CrUX kanıtları kullanılamıyor. Tekrar incelemeden önce denetimi yenileyin.",
  "Collected": "Toplanma zamanı",
  "(UTC); server assessment": "(UTC); sunucu değerlendirmesi",
  "Original raw integrity unknown for this legacy observation. No comparison was reconstructed; missing evidence is not passing.": "Bu eski gözlem için özgün ham veri bütünlüğü bilinmiyor. Karşılaştırma yeniden oluşturulmadı; eksik kanıt, başarılı sonuç değildir.",
  "Original stored-response integrity checked;": "Özgün kayıtlı yanıtın bütünlüğü kontrol edildi;",
  "requested": "istenen",
  "observed": "gözlenen",
  "origin fallback (not page data)": "kaynak adresine dönüş (sayfa verisi değil)",
  "no origin fallback": "kaynak adresine dönüş yok",
  "normalization": "normalleştirme",
  "original source periods; only the last one or two are shown. Collection dates are PST (fixed UTC−8), not the project timezone.": "özgün kaynak dönemi; yalnızca son bir veya iki dönem gösteriliyor. Toplama tarihleri proje saat diliminde değil, PST (sabit UTC−8) saat dilimindedir.",
  "Eligible days and sample counts are unknown. Field p75 grades are not lab scores. Overlapping windows do not prove a causal change, statistical significance or a confirmed SEO regression.": "Uygun günler ve örnek sayıları bilinmiyor. Saha p75 notları laboratuvar puanları değildir. Örtüşen pencereler nedensel değişikliği, istatistiksel anlamlılığı veya doğrulanmış SEO gerilemesini kanıtlamaz.",
  "Field threshold worsening candidate": "Saha eşiğinde kötüleşme adayı",
  "No threshold worsening observed in these two periods": "Bu iki dönemde eşik kötüleşmesi gözlenmedi",
  "Unknown: insufficient eligible periods": "Bilinmiyor: yetersiz uygun dönem",
  "Original source periods are not comparable under the weekly 28-day contract": "Özgün kaynak dönemleri, haftalık 28 günlük sözleşmeye göre karşılaştırılamaz",
  "Material field threshold worsening candidate under product heuristics": "Ürün sezgisel kurallarına göre önemli saha eşiği kötüleşmesi adayı",
  "Grade worsened, but below one or both product material-change floors": "Not kötüleşti, ancak bir veya iki ürün önemli değişiklik alt sınırının altında",
  "Unknown: relative increase cannot be assessed from a zero baseline": "Bilinmiyor: sıfır başlangıç değerinden göreli artış değerlendirilemez",
  "Unknown: original values exceed supported exact arithmetic precision": "Bilinmiyor: özgün değerler desteklenen tam aritmetik hassasiyetini aşıyor",
  "to": "ile",
  "inclusive calendar days: p75": "dahil takvim günü: p75",
  "unavailable": "kullanılamıyor",
  "Eligible days unknown.": "Uygun günler bilinmiyor.",
  "Actual overlap:": "Gerçek örtüşme:",
  "unknown: only one period": "bilinmiyor: yalnızca bir dönem",
  "calendar days": "takvim günü",
  "Two 28-day windows, seven-day cadence.": "İki 28 günlük pencere, yedi günlük aralık.",
  "Weekly 28-day comparison unavailable.": "Haftalık 28 günlük karşılaştırma kullanılamıyor.",
  "Sample count unknown.": "Örnek sayısı bilinmiyor.",
  "Product material-change policy v1": "Ürün önemli değişiklik politikası v1",
  "Requires grade worsening and both inclusive floors: 20% relative increase and 500 ms LCP, 50 ms INP or 0.05 unitless CLS. These are product heuristics, not provider noise estimates. Large within-grade changes are ineligible.": "Not kötüleşmesi ve her iki dahil alt sınır gerekir: %20 göreli artış ile 500 ms LCP, 50 ms INP veya 0.05 birimsiz CLS. Bunlar ürün sezgisel kurallarıdır; sağlayıcı gürültü tahminleri değildir. Aynı not içindeki büyük değişiklikler uygun değildir.",
  "Sample sufficiency and statistical significance are unknown. This inspection establishes neither confirmed SEO regression, causality, alert consent nor delivery.": "Örnek yeterliliği ve istatistiksel anlamlılık bilinmiyor. Bu inceleme doğrulanmış SEO gerilemesini, nedenselliği, uyarı onayını veya teslimatı kanıtlamaz.",
  "Server source-policy reference": "Sunucu kaynak-politika referansı",
  ". Its shape is checked; the browser cannot independently authenticate the server's full original metadata.": ". Biçimi kontrol edilir; tarayıcı sunucunun tüm özgün meta verilerinin doğruluğunu bağımsız olarak doğrulayamaz.",
  "Legacy original integrity unknown; no material comparison reconstructed.": "Eski özgün veri bütünlüğü bilinmiyor; önemli değişiklik karşılaştırması yeniden oluşturulmadı.",
  "Absolute floor": "Mutlak alt sınır",
  "; relative floor 20%.": "; göreli alt sınır %20.",
  "Exact absolute increase": "Tam mutlak artış",
  "unknown / not evaluated": "bilinmiyor / değerlendirilmedi",
  "met": "karşılandı",
  "not met": "karşılanmadı",
  "; relative floor": "; göreli alt sınır",
};
