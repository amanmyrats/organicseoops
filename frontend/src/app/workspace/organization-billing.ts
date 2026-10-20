import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { CheckoutLinkReceipt } from '../account/checkout-link-receipt';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Attempt = { id: number; state: 'reserved' | 'sending' | 'unknown' | 'ready' | 'rejected' | 'settled';
  created_at: string; checkout_url: string | null; payment_confirmed: false; payment_captured: boolean };

type FirstPaidObservation = { method: 'first-active-observation-v1'; organization_id: number;
  state: 'recorded' | 'not_observed' | 'unknown'; observation: null | {
    attempt_id: number; source_digest: string; observed_at: string; provider_occurred_at: string;
    environment: 'sandbox' | 'live'; offer_version: 'agency-launch-v1'; currency_code: string;
    interpretation: 'historical_first_active_server_observation_not_current_access_or_provider_activation_time';
  } };

type PaidTiming = { method: string; state: string; precision: string; interpretation: string;
  tracking_started_at: string | null; observed_at: string | null;
  source_digest: string | null; elapsed_milliseconds: number | null };

type TrialActivation = { method: string; state: 'recorded' | 'not_activated' | 'unknown'; activation: null | {
  activation_method: 'automatic' | 'staff_approved'; offer_version: string;
  started_at: string; audited_at: string; source_digest: string;
} };
type TrialPaidTiming = { method: string; state: string; precision: string; interpretation: string;
  trial_started_at: string | null; observed_at: string | null; activation_method: string | null;
  trial_source_digest: string | null; paid_source_digest: string | null;
  source_digest: string | null; elapsed_milliseconds: number | null };

type TrialPaidWindow = { method: string; state: string; window_days: number; interpretation: string; assessed_at: string;
  trial_started_at: string | null; window_ends_at: string | null; paid_observed_at: string | null;
  trial_source_digest: string | null; paid_source_digest: string | null; source_digest: string | null; outcome: string | null };

function originalMicroseconds(value: unknown, allowFuture = false): bigint | null {
  if (typeof value !== 'string') return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}:\d{2}(?:\.(\d{1,6}))?(?:Z|[+-]\d{2}:\d{2})$/.exec(value);
  const date = Date.parse(value);
  if (!match || !Number.isFinite(date) || !allowFuture && date > Date.now()
    || Number(match[3]) < 1 || Number(match[3]) > new Date(Date.UTC(Number(match[1]), Number(match[2]), 0)).getUTCDate()
    || !/T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d/.test(value)) return null;
  // Preserve Python's original microseconds before rounding the duration, not each date.
  return BigInt(date) * 1000n + BigInt(Number((match[4] || '').padEnd(6, '0')) % 1000);
}

function readFirstPaidObservation(value: unknown, organizationId: number): FirstPaidObservation | null {
  if (!value || typeof value !== 'object') return null;
  const body = value as Record<string, unknown>;
  if (Object.keys(body).length !== 4 || body['method'] !== 'first-active-observation-v1' || body['organization_id'] !== organizationId
      || typeof body['state'] !== 'string' || !['recorded', 'not_observed', 'unknown'].includes(body['state'])) return null;
  if (body['state'] !== 'recorded') return body['observation'] === null ? body as FirstPaidObservation : null;
  const row = body['observation'];
  if (!row || typeof row !== 'object') return null;
  const observation = row as Record<string, unknown>;
  const observed = originalMicroseconds(observation['observed_at']), occurred = originalMicroseconds(observation['provider_occurred_at']);
  return Object.keys(observation).length === 8 && Number.isSafeInteger(observation['attempt_id']) && Number(observation['attempt_id']) > 0
    && typeof observation['source_digest'] === 'string' && /^[a-f0-9]{64}$/.test(observation['source_digest'])
    && observed !== null && occurred !== null && occurred <= observed
    && typeof observation['environment'] === 'string' && ['sandbox', 'live'].includes(observation['environment'])
    && observation['offer_version'] === 'agency-launch-v1' && typeof observation['currency_code'] === 'string'
    && /^[A-Z]{3}$/.test(observation['currency_code'])
    && observation['interpretation'] === 'historical_first_active_server_observation_not_current_access_or_provider_activation_time'
    ? body as FirstPaidObservation : null;
}

function readPaidTiming(body: Record<string, unknown>, history: FirstPaidObservation): PaidTiming | null {
  if (Object.keys(body).length !== 2 || body['organization_id'] !== history.organization_id
    || !body['timing'] || typeof body['timing'] !== 'object') return null;
  const timing = body['timing'] as Record<string, unknown>;
  const fields = ['tracking_started_at', 'observed_at', 'source_digest', 'elapsed_milliseconds'];
  if (Object.keys(timing).length !== 8 || fields.some(key => !Object.hasOwn(timing, key))
    || timing['method'] !== 'first-active-observation-timing-v1' || timing['state'] !== history.state
    || timing['precision'] !== 'whole_milliseconds_rounded_down'
    || timing['interpretation'] !== 'organization_age_at_first_paid_server_observation_not_provider_activation_trial_or_cohort') return null;
  if (!history.observation) return fields.every(key => timing[key] === null) ? timing as PaidTiming : null;
  const born = originalMicroseconds(timing['tracking_started_at']), observed = originalMicroseconds(timing['observed_at']);
  return timing['observed_at'] === history.observation.observed_at && timing['source_digest'] === history.observation.source_digest
    && born !== null && observed !== null && observed >= born
    && Number.isSafeInteger(timing['elapsed_milliseconds']) && Number(timing['elapsed_milliseconds']) >= 0
    && (observed - born) / 1000n === BigInt(Number(timing['elapsed_milliseconds'])) ? timing as PaidTiming : null;
}

function readTrialActivation(body: Record<string, unknown>, org: number): TrialActivation | null {
  if (Object.keys(body).length !== 2 || body['organization_id'] !== org
    || !body['trial_activation'] || typeof body['trial_activation'] !== 'object') return null;
  const trial = body['trial_activation'] as Record<string, unknown>;
  if (Object.keys(trial).length !== 3 || trial['method'] !== 'audited-trial-activation-v1'
    || typeof trial['state'] !== 'string' || !['recorded', 'not_activated', 'unknown'].includes(trial['state'])) return null;
  if (trial['state'] !== 'recorded') return trial['activation'] === null ? trial as TrialActivation : null;
  if (!trial['activation'] || typeof trial['activation'] !== 'object') return null;
  const row = trial['activation'] as Record<string, unknown>;
  const started = originalMicroseconds(row['started_at']), audited = originalMicroseconds(row['audited_at']);
  return Object.keys(row).length === 5 && typeof row['activation_method'] === 'string'
    && ['automatic', 'staff_approved'].includes(row['activation_method'])
    && row['offer_version'] === 'agency-launch-v1' && typeof row['source_digest'] === 'string'
    && /^[a-f0-9]{64}$/.test(row['source_digest']) && started !== null && audited !== null && audited >= started
    ? trial as TrialActivation : null;
}

async function readTrialPaidTiming(body: Record<string, unknown>, trial: TrialActivation, paid: FirstPaidObservation): Promise<TrialPaidTiming | null> {
  if (Object.keys(body).length !== 2 || body['organization_id'] !== paid.organization_id
    || !body['timing'] || typeof body['timing'] !== 'object') return null;
  const timing = body['timing'] as Record<string, unknown>;
  const fields = ['trial_started_at', 'observed_at', 'activation_method', 'trial_source_digest',
    'paid_source_digest', 'source_digest', 'elapsed_milliseconds'];
  const state = trial.state === 'recorded' ? paid.state : 'unknown';
  if (Object.keys(timing).length !== 11 || fields.some(key => !Object.hasOwn(timing, key))
    || timing['method'] !== 'trial-to-first-paid-server-timing-v1' || timing['state'] !== state
    || timing['precision'] !== 'whole_milliseconds_rounded_down'
    || timing['interpretation'] !== 'audited_trial_start_to_first_paid_server_observation_not_provider_activation_or_cohort') return null;
  if (state !== 'recorded') return fields.every(key => timing[key] === null) ? timing as TrialPaidTiming : null;
  const activation = trial.activation!, observation = paid.observation!;
  const started = originalMicroseconds(timing['trial_started_at']), observed = originalMicroseconds(timing['observed_at']);
  if (timing['trial_started_at'] !== activation.started_at || timing['observed_at'] !== observation.observed_at
    || timing['activation_method'] !== activation.activation_method || timing['trial_source_digest'] !== activation.source_digest
    || timing['paid_source_digest'] !== observation.source_digest || typeof timing['source_digest'] !== 'string'
    || !/^[a-f0-9]{64}$/.test(timing['source_digest']) || started === null || observed === null || observed < started
    || !Number.isSafeInteger(timing['elapsed_milliseconds']) || Number(timing['elapsed_milliseconds']) < 0
    || (observed - started) / 1000n !== BigInt(Number(timing['elapsed_milliseconds']))) return null;
  const source = { activation_method: activation.activation_method, method: timing['method'],
    observed_at: observation.observed_at, organization_id: paid.organization_id,
    paid_source_digest: observation.source_digest, trial_source_digest: activation.source_digest, trial_started_at: activation.started_at };
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(source)));
  const digest = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
  return digest === timing['source_digest'] ? timing as TrialPaidTiming : null;
}

async function readTrialPaidWindow(body: Record<string, unknown>, trial: TrialActivation, paid: FirstPaidObservation): Promise<TrialPaidWindow | null> {
  if (Object.keys(body).length !== 2 || body['organization_id'] !== paid.organization_id
    || !body['window'] || typeof body['window'] !== 'object') return null;
  const window = body['window'] as Record<string, unknown>;
  const fields = ['trial_started_at', 'window_ends_at', 'paid_observed_at', 'trial_source_digest', 'paid_source_digest', 'source_digest', 'outcome'];
  const assessed = originalMicroseconds(window['assessed_at']);
  if (Object.keys(window).length !== 12 || fields.some(key => !Object.hasOwn(window, key))
    || window['method'] !== 'original-trial-paid-observation-window-v1' || window['window_days'] !== 37 || assessed === null
    || window['interpretation'] !== 'fixed_half_open_original_trial_paid_server_window_not_provider_activation_or_conversion_rate') return null;
  if (trial.state !== 'recorded' || paid.state === 'unknown') {
    return window['state'] === 'unknown' && fields.every(key => window[key] === null) ? window as TrialPaidWindow : null;
  }
  const activation = trial.activation!, observation = paid.observation;
  // The fixed end may be future for an immature window; original observations/assessment may not.
  const started = originalMicroseconds(window['trial_started_at']), endMicros = originalMicroseconds(window['window_ends_at'], true);
  const observed = observation ? originalMicroseconds(window['paid_observed_at']) : null;
  if (window['trial_started_at'] !== activation.started_at || window['trial_source_digest'] !== activation.source_digest
    || window['paid_observed_at'] !== (observation?.observed_at ?? null) || window['paid_source_digest'] !== (observation?.source_digest ?? null)
    || typeof window['source_digest'] !== 'string' || !/^[a-f0-9]{64}$/.test(window['source_digest'])
    || started === null || endMicros === null || started > assessed || endMicros - started !== 37n * 86400n * 1000000n
    || observation && (observed === null || observed < started || observed > assessed)) return null;
  const state = assessed >= endMicros ? 'mature' : 'immature';
  const outcome = state === 'mature' ? observed !== null && observed < endMicros ? 'observed_within_window' : 'not_observed_within_window' : null;
  if (window['state'] !== state || window['outcome'] !== outcome) return null;
  const source = { method: window['method'], organization_id: paid.organization_id, window_days: 37,
    assessed_at: window['assessed_at'], trial_started_at: window['trial_started_at'], window_ends_at: window['window_ends_at'],
    paid_observed_at: window['paid_observed_at'], trial_source_digest: window['trial_source_digest'],
    paid_source_digest: window['paid_source_digest'], paid_state: paid.state, state, outcome };
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(Object.fromEntries(Object.entries(source).sort()))));
  const digest = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
  return digest === window['source_digest'] ? window as TrialPaidWindow : null;
}

function readAttempt(value: unknown): Attempt | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && typeof row['state'] === 'string' && ['reserved', 'sending', 'unknown', 'ready', 'rejected', 'settled'].includes(row['state'])
    && typeof row['created_at'] === 'string' && row['payment_confirmed'] === false
    && typeof row['payment_captured'] === 'boolean'
    && (row['checkout_url'] === null || typeof row['checkout_url'] === 'string')
    ? row as Attempt : null;
}

function localCheckoutPath(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.origin);
    const transactionId = url.searchParams.get('_ptxn');
    return url.origin === window.location.origin && url.pathname === '/account/billing/checkout'
      && [...url.searchParams.keys()].length === 1 && transactionId && /^txn_[a-z0-9]{26}$/.test(transactionId)
      && !url.hash ? `/account/billing/checkout?_ptxn=${transactionId}` : null;
  } catch { return null; }
}

function safePortalUrl(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 2048) return null;
  try {
    const url = new URL(value);
    const host = url.hostname;
    const token = url.searchParams.get('token');
    return url.protocol === 'https:' && url.port === '' && !url.username && !url.password && !url.hash
      && ['customer-portal.paddle.com', 'sandbox-customer-portal.paddle.com'].includes(host)
      && /^\/cpl_[a-z0-9]{26}$/.test(url.pathname) && url.searchParams.get('action') === 'overview'
      && [...url.searchParams.keys()].length === 2 && !!token && /^[A-Za-z0-9._-]{1,1024}$/.test(token)
      ? value : null;
  } catch { return null; }
}

const organizationBillingTurkish: Record<string, string> = {
  "Back to organization context": "Kuruluş bağlamına dön",
  "Organization billing": "Kuruluş faturalandırması",
  "Agency: USD 149 per month before Paddle-calculated tax. Paddle shows your actual currency, tax and total before you confirm payment. Your trial requires no card. If you pay early, the trial ends and your paid monthly period starts immediately; unused trial time and units do not carry over. Renewal is monthly until canceled. Cancellation takes effect at the end of the paid period.": "Agency: Paddle tarafından hesaplanan vergi öncesinde ayda 149 USD. Paddle, ödemeyi onaylamadan önce gerçek para birimini, vergiyi ve toplamı gösterir. Denemeniz için kart gerekmez. Erken ödeme yaparsanız deneme sona erer ve ücretli aylık döneminiz hemen başlar; kullanılmayan deneme süresi ve birimleri devredilmez. İptal edilene kadar her ay yenilenir. İptal, ücretli dönemin sonunda geçerli olur.",
  "Only the organization owner can begin checkout. A checkout link or return to this app does not prove payment; paid access waits for verified billing reconciliation.": "Ödeme işlemini yalnızca kuruluş sahibi başlatabilir. Ödeme bağlantısı veya uygulamaya dönüş, ödemenin kanıtı değildir; ücretli erişim, doğrulanmış faturalandırma mutabakatını bekler.",
  "Loading billing status.": "Faturalandırma durumu yükleniyor.",
  "Billing status is unavailable for this organization or role.": "Bu kuruluş veya rol için faturalandırma durumu kullanılamıyor.",
  "Refresh billing status": "Faturalandırma durumunu yenile",
  "Prospective first active paid observation": "İleriye dönük izlenen ilk etkin ücretli erişim gözlemi",
  "This is historical server reconciliation evidence, not current paid access or the provider's activation time. Renewal, recovery and recheckout do not reset it. Older or incomplete tracking remains unknown.": "Bu, geçmiş sunucu mutabakatı kanıtıdır; mevcut ücretli erişimi veya sağlayıcının etkinleştirme zamanını göstermez. Yenileme, kurtarma ve yeniden ödeme işlemi bu kaydı sıfırlamaz. Eski veya eksik izleme bilinmiyor olarak kalır.",
  "First tracked active server observation:": "İzlenen ilk etkin sunucu gözlemi:",
  "The separate signed provider event occurred at": "Ayrı imzalı sağlayıcı olayının zamanı:",
  "Original checkout attempt": "İlk ödeme girişimi",
  "No active paid observation has been captured for this prospectively tracked organization.": "İleriye dönük izlenen bu kuruluş için etkin ücretli erişim gözlemi kaydedilmedi.",
  "Historical first active paid observation is unknown. Current billing status cannot reconstruct it.": "Geçmişteki ilk etkin ücretli erişim gözlemi bilinmiyor. Mevcut faturalandırma durumu bunu yeniden oluşturamaz.",
  "Retained paid server observation timing": "Saklanan ücretli erişim sunucu gözlemi zamanlaması",
  "Inspect original organization age at its first tracked active paid server observation. This is not time from registration or trial, provider activation time, checkout runtime, current paid access, business value or a conversion cohort.": "Kuruluşun izlenen ilk etkin ücretli erişim sunucu gözlemindeki özgün yaşını inceleyin. Bu, kayıt veya denemeden itibaren geçen süreyi, sağlayıcı etkinleştirme zamanını, ödeme işlemi süresini, mevcut ücretli erişimi, iş değerini veya dönüşüm kohortunu göstermez.",
  "Inspect saved paid server timing": "Kaydedilen ücretli erişim sunucu zamanlamasını incele",
  "Checking original timing and current owner history access.": "Özgün zamanlama ve mevcut sahibin geçmişe erişimi kontrol ediliyor.",
  "Original organization tracking began": "Kuruluşun özgün izleme başlangıcı:",
  "first active paid server observation": "ilk etkin ücretli erişim sunucu gözlemi:",
  "Elapsed organization age:": "Geçen kuruluş yaşı:",
  "whole milliseconds, rounded down.": "aşağı yuvarlanmış tam milisaniye.",
  "Original source SHA-256:": "Özgün kaynak SHA-256:",
  "Renewal and recovery do not reset this history.": "Yenileme ve kurtarma bu geçmişi sıfırlamaz.",
  "Unknown or unobserved history supplies no duration. No zero-value timing is inferred.": "Bilinmeyen veya gözlemlenmemiş geçmiş bir süre sağlamaz. Sıfır süre çıkarımı yapılmaz.",
  "Original trial-to-paid server timing": "Özgün denemeden ücretli erişime sunucu zamanlaması",
  "Inspect the original audited trial start and first tracked paid server observation. Extension, renewal and recovery do not reset them. This is historical timing, not provider activation time, current access or a conversion cohort.": "Denetim kaydı bulunan özgün deneme başlangıcını ve izlenen ilk ücretli erişim sunucu gözlemini inceleyin. Uzatma, yenileme ve kurtarma bunları sıfırlamaz. Bu geçmiş zamanlamasıdır; sağlayıcı etkinleştirme zamanını, mevcut erişimi veya dönüşüm kohortunu göstermez.",
  "Inspect saved trial-to-paid server timing": "Kaydedilen denemeden ücretli erişime sunucu zamanlamasını incele",
  "Inspect saved trial paid-observation window": "Kaydedilen deneme ücretli erişim gözlem aralığını incele",
  "Checking both original sources and current owner history access.": "Her iki özgün kaynak ve mevcut sahibin geçmişe erişimi kontrol ediliyor.",
  "Original": "Özgün",
  "trial started": "deneme başlangıcı:",
  "separate original audit": "ayrı özgün denetim kaydı:",
  "Offer": "Teklif",
  "trial source SHA-256": "deneme kaynağı SHA-256",
  "First paid server observation": "İlk ücretli erişim sunucu gözlemi",
  "Elapsed original trial-to-paid server time:": "Özgün denemeden ücretli erişime geçen sunucu süresi:",
  "Original paid source SHA-256": "Özgün ücretli erişim kaynağı SHA-256",
  "combined source SHA-256": "birleşik kaynak SHA-256",
  "Missing, pending, unknown or unobserved originals supply no duration. No zero-value trial-to-paid timing is inferred.": "Eksik, bekleyen, bilinmeyen veya gözlemlenmemiş özgün kayıtlar bir süre sağlamaz. Denemeden ücretli erişime sıfır süre çıkarımı yapılmaz.",
  "Fixed original trial paid-observation window": "Sabit özgün deneme ücretli erişim gözlem aralığı",
  "Assessment at": "Değerlendirme zamanı:",
  "This fixed 37-day analytical window includes the maximum possible extension; it does not extend trial access or report a conversion rate.": "Bu sabit 37 günlük analiz aralığı mümkün olan en uzun uzatmayı içerir; deneme erişimini uzatmaz veya dönüşüm oranı bildirmez.",
  "Missing, pending or unknown original coverage supplies no window outcome.": "Eksik, bekleyen veya bilinmeyen özgün kapsam bir aralık sonucu sağlamaz.",
  "Original half-open UTC window:": "Özgün yarı açık UTC aralığı:",
  "to": "ile",
  "the exact end is excluded.": "bitiş anı aralığa dahil değildir.",
  "Original paid server observation": "Özgün ücretli erişim sunucu gözlemi",
  "Full follow-up has not elapsed. Even an early paid observation supplies no mature outcome.": "Takip süresinin tamamı geçmedi. Erken bir ücretli erişim gözlemi bile tamamlanmış aralık sonucu sağlamaz.",
  "The first tracked paid server observation was within this completed window.": "İzlenen ilk ücretli erişim sunucu gözlemi tamamlanan bu aralığın içindeydi.",
  "No first tracked paid server observation was within this completed window. This does not establish provider activation time or lifetime absence.": "İzlenen ilk ücretli erişim sunucu gözlemi tamamlanan bu aralığın içinde değildi. Bu, sağlayıcı etkinleştirme zamanını veya hiçbir zaman gözlem olmadığını kanıtlamaz.",
  "No paid observation": "Ücretli erişim gözlemi yok",
  "frozen assessment source SHA-256": "sabitlenen değerlendirme kaynağı SHA-256",
  "A Paddle subscription reference is linked. Its status and paid access are not verified by this screen.": "Bir Paddle abonelik referansı bağlı. Bu ekran aboneliğin durumunu ve ücretli erişimi doğrulamaz.",
  "Reconciled billing state:": "Mutabakat sonrası faturalandırma durumu:",
  "Paid quota enforcement and customer export/recovery follow server verification; a linked provider ID alone grants no paid access.": "Ücretli kota uygulaması ve müşteri dışa aktarma/kurtarma işlemleri sunucu doğrulamasına bağlıdır; bağlı bir sağlayıcı kimliği tek başına ücretli erişim vermez.",
  "Get a fresh Paddle billing portal link": "Yeni bir Paddle faturalandırma portalı bağlantısı al",
  "Billing portal recovery is not currently configured.": "Faturalandırma portalıyla kurtarma şu anda yapılandırılmamış.",
  "Open temporary Paddle portal": "Geçici Paddle portalını aç",
  "(invoices, payment methods and cancellation)": "(faturalar, ödeme yöntemleri ve iptal)",
  "Hosted checkout is not configured for this organization.": "Bu kuruluş için sağlayıcıda ödeme işlemi yapılandırılmamış.",
  "Checkout attempts": "Ödeme girişimleri",
  "Attempt": "Girişim",
  "Review Paddle checkout": "Paddle ödeme işlemini incele",
  "Select attempt": "Girişimi seç:",
  "for browser receipt inspection": "tarayıcı bağlantı alındısı incelemesi için",
  "No checkout attempt has been recorded.": "Ödeme girişimi kaydedilmedi.",
  "I understand the monthly renewal, immediate early-trial charge, provider-calculated tax and period-end cancellation.": "Aylık yenilemeyi, deneme sırasında erken ödemenin hemen tahsil edilmesini, sağlayıcı tarafından hesaplanan vergiyi ve dönem sonunda iptali anlıyorum.",
  "Continue to Paddle for review": "İncelemek için Paddle’a devam et",
  "Original trial-to-paid server evidence unavailable or needs billing review. Refresh billing status; unknown originals supply no duration or window outcome.": "Özgün denemeden ücretli erişime sunucu kanıtı kullanılamıyor veya faturalandırma incelemesi gerekiyor. Faturalandırma durumunu yenileyin; bilinmeyen özgün kayıtlar süre veya aralık sonucu sağlamaz.",
  "Original paid server timing unavailable or needs billing review. Refresh billing status; unknown history supplies no duration.": "Özgün ücretli erişim sunucu zamanlaması kullanılamıyor veya faturalandırma incelemesi gerekiyor. Faturalandırma durumunu yenileyin; bilinmeyen geçmiş bir süre sağlamaz.",
  "A checkout is prepared. Review the provider amount and tax before confirming payment.": "Ödeme işlemi hazırlandı. Ödemeyi onaylamadan önce sağlayıcının tutarını ve vergiyi inceleyin.",
  "Checkout is not ready. Refresh status; an uncertain provider outcome must be reviewed before another attempt.": "Ödeme işlemi hazır değil. Durumu yenileyin; başka bir girişimden önce belirsiz sağlayıcı sonucu incelenmelidir.",
  "Checkout could not be confirmed. Refresh status before trying the same request again.": "Ödeme işlemi doğrulanamadı. Aynı isteği yeniden denemeden önce durumu yenileyin.",
  "The payment page link is not on the approved account host. Refresh billing status.": "Ödeme sayfası bağlantısı onaylı hesap sunucusunda değil. Faturalandırma durumunu yenileyin.",
  "This temporary Paddle portal link is available for this session only.": "Bu geçici Paddle portalı bağlantısı yalnızca bu oturum için kullanılabilir.",
  "The billing portal is unavailable. Refresh and try again later.": "Faturalandırma portalı kullanılamıyor. Yenileyin ve daha sonra tekrar deneyin.",
  "Unreviewed Turkish organization-billing interface draft in local development. Stored status/currency/source values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe kuruluş faturalandırma arayüzü taslağı. Saklanan durum/para birimi/kaynak değerleri ve diğer ekranlar İngilizce kalır; iki dilde onay bekleniyor.",
  "Source SHA-256:": "Kaynak SHA-256:",
  "The provider outcome needs billing review. Do not submit another payment request.": "Sağlayıcı sonucunun faturalandırma incelemesi gerekiyor. Başka bir ödeme isteği göndermeyin.",
  "The provider reports payment captured. Paid access awaits current subscription reconciliation.": "Sağlayıcı ödemenin tahsil edildiğini bildiriyor. Ücretli erişim mevcut aboneliğin mutabakatını bekler.",
  "The payment is not yet confirmed.": "Ödeme henüz doğrulanmadı."
};

@Component({
  selector: 'app-organization-billing',
  imports: [RouterLink, CheckoutLinkReceipt],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="billing-title">
      <p><a routerLink="/app">{{ t("Back to organization context") }}</a></p>
      <h1 id="billing-title">{{ t("Organization billing") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish organization-billing interface draft in local development. Stored status/currency/source values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p>{{ t("Agency: USD 149 per month before Paddle-calculated tax. Paddle shows your actual currency, tax and total before you confirm payment. Your trial requires no card. If you pay early, the trial ends and your paid monthly period starts immediately; unused trial time and units do not carry over. Renewal is monthly until canceled. Cancellation takes effect at the end of the paid period.") }}</p>
      <p>{{ t("Only the organization owner can begin checkout. A checkout link or return to this app does not prove payment; paid access waits for verified billing reconciliation.") }}</p>
      @if (message()) { <p role="status" [attr.lang]="textLanguage(message())">{{ t(message()) }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="textLanguage(error())">{{ t(error()) }}</p> }
      @if (loading()) { <p role="status">{{ t("Loading billing status.") }}</p> }
      @else if (denied()) { <p>{{ t("Billing status is unavailable for this organization or role.") }}</p> }
      @else {
        <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh billing status") }}</button>
        @if (firstPaidObservation(); as history) {
          <h2>{{ t("Prospective first active paid observation") }}</h2>
          <p>{{ t("This is historical server reconciliation evidence, not current paid access or the provider's activation time. Renewal, recovery and recheckout do not reset it. Older or incomplete tracking remains unknown.") }}</p>
          @if (history.observation; as observed) {
            <p>{{ t("First tracked active server observation:") }} <time lang="en" [attr.datetime]="observed.observed_at">{{ observed.observed_at }}</time>.
              {{ t("The separate signed provider event occurred at") }} <time lang="en" [attr.datetime]="observed.provider_occurred_at">{{ observed.provider_occurred_at }}</time>.</p>
            <p>{{ t("Original checkout attempt") }} {{ observed.attempt_id }}; <span lang="en">{{ observed.environment }}</span>; <span lang="en">{{ observed.currency_code }}</span>.
              {{ t("Source SHA-256:") }} <code lang="en">{{ observed.source_digest }}</code>.</p>
          } @else if (history.state === 'not_observed') { <p>{{ t("No active paid observation has been captured for this prospectively tracked organization.") }}</p> }
          @else { <p>{{ t("Historical first active paid observation is unknown. Current billing status cannot reconstruct it.") }}</p> }
          <section aria-labelledby="paid-timing-title">
            <h2 id="paid-timing-title">{{ t("Retained paid server observation timing") }}</h2>
            <p>{{ t("Inspect original organization age at its first tracked active paid server observation. This is not time from registration or trial, provider activation time, checkout runtime, current paid access, business value or a conversion cohort.") }}</p>
            <button type="button" (click)="inspectPaidTiming()" [disabled]="busy()">{{ t("Inspect saved paid server timing") }}</button>
            @if (timingLoading()) { <p role="status">{{ t("Checking original timing and current owner history access.") }}</p> }
            @if (paidTiming(); as timing) {
              @if (timing.state === 'recorded') {
                <p>{{ t("Original organization tracking began") }} <time lang="en" [attr.datetime]="timing.tracking_started_at">{{ timing.tracking_started_at }}</time>;
                  {{ t("first active paid server observation") }} <time lang="en" [attr.datetime]="timing.observed_at">{{ timing.observed_at }}</time>.</p>
                <p>{{ t("Elapsed organization age:") }} {{ timing.elapsed_milliseconds }} {{ t("whole milliseconds, rounded down.") }}
                  {{ t("Original source SHA-256:") }} <code lang="en">{{ timing.source_digest }}</code>. {{ t("Renewal and recovery do not reset this history.") }}</p>
              } @else { <p>{{ t("Unknown or unobserved history supplies no duration. No zero-value timing is inferred.") }}</p> }
            }
          </section>
          <section aria-labelledby="trial-paid-timing-title">
            <h2 id="trial-paid-timing-title">{{ t("Original trial-to-paid server timing") }}</h2>
            <p>{{ t("Inspect the original audited trial start and first tracked paid server observation. Extension, renewal and recovery do not reset them. This is historical timing, not provider activation time, current access or a conversion cohort.") }}</p>
            <button type="button" (click)="inspectTrialPaidTiming()" [disabled]="busy()">{{ t("Inspect saved trial-to-paid server timing") }}</button>
            <button type="button" (click)="inspectTrialPaidTiming('window')" [disabled]="busy()">{{ t("Inspect saved trial paid-observation window") }}</button>
            @if (trialTimingLoading()) { <p role="status">{{ t("Checking both original sources and current owner history access.") }}</p> }
            @if (trialActivation()?.activation; as activation) {
              <p>{{ t("Original") }} <span lang="en">{{ activation.activation_method }}</span> {{ t("trial started") }} <time lang="en" [attr.datetime]="activation.started_at">{{ activation.started_at }}</time>;
                {{ t("separate original audit") }} <time lang="en" [attr.datetime]="activation.audited_at">{{ activation.audited_at }}</time>.
                {{ t("Offer") }} <span lang="en">{{ activation.offer_version }}</span>; {{ t("trial source SHA-256") }} <code lang="en">{{ activation.source_digest }}</code>.</p>
            }
            @if (trialPaidTiming(); as timing) {
              @if (timing.state === 'recorded') {
                <p>{{ t("First paid server observation") }} <time lang="en" [attr.datetime]="timing.observed_at">{{ timing.observed_at }}</time>.
                  {{ t("Elapsed original trial-to-paid server time:") }} {{ timing.elapsed_milliseconds }} {{ t("whole milliseconds, rounded down.") }}</p>
                <p>{{ t("Original paid source SHA-256") }} <code lang="en">{{ timing.paid_source_digest }}</code>;
                  {{ t("combined source SHA-256") }} <code lang="en">{{ timing.source_digest }}</code>.</p>
              } @else { <p>{{ t("Missing, pending, unknown or unobserved originals supply no duration. No zero-value trial-to-paid timing is inferred.") }}</p> }
            }
            @if (trialPaidWindow(); as window) {
              <h3>{{ t("Fixed original trial paid-observation window") }}</h3>
              <p>{{ t("Assessment at") }} <time lang="en" [attr.datetime]="window.assessed_at">{{ window.assessed_at }}</time>.
                {{ t("This fixed 37-day analytical window includes the maximum possible extension; it does not extend trial access or report a conversion rate.") }}</p>
              @if (window.state === 'unknown') { <p>{{ t("Missing, pending or unknown original coverage supplies no window outcome.") }}</p> }
              @else {
                <p>{{ t("Original half-open UTC window:") }} <time lang="en" [attr.datetime]="window.trial_started_at">{{ window.trial_started_at }}</time>
                  {{ t("to") }} <time lang="en" [attr.datetime]="window.window_ends_at">{{ window.window_ends_at }}</time>; {{ t("the exact end is excluded.") }}</p>
                @if (window.paid_observed_at) { <p>{{ t("Original paid server observation") }} <time lang="en" [attr.datetime]="window.paid_observed_at">{{ window.paid_observed_at }}</time>.</p> }
                @if (window.state === 'immature') { <p>{{ t("Full follow-up has not elapsed. Even an early paid observation supplies no mature outcome.") }}</p> }
                @else if (window.outcome === 'observed_within_window') { <p>{{ t("The first tracked paid server observation was within this completed window.") }}</p> }
                @else { <p>{{ t("No first tracked paid server observation was within this completed window. This does not establish provider activation time or lifetime absence.") }}</p> }
                <p>{{ t("Original paid source SHA-256") }} @if (window.paid_source_digest) { <code lang="en">{{ window.paid_source_digest }}</code> } @else { {{ t("No paid observation") }} };
                  {{ t("frozen assessment source SHA-256") }} <code lang="en">{{ window.source_digest }}</code>.</p>
              }
            }
          </section>
        }
        @if (timingError()) { <p role="alert" [attr.lang]="textLanguage(timingError())">{{ t(timingError()) }}</p> }
        @if (trialTimingError()) { <p role="alert" [attr.lang]="textLanguage(trialTimingError())">{{ t(trialTimingError()) }}</p> }
        @if (subscriptionLinked()) {
          <p role="status">{{ t("A Paddle subscription reference is linked. Its status and paid access are not verified by this screen.") }}</p>
          <p>{{ t("Reconciled billing state:") }} <span lang="en">{{ billingAccessState() }}</span>. {{ t("Paid quota enforcement and customer export/recovery follow server verification; a linked provider ID alone grants no paid access.") }}</p>
          @if (portalAvailable()) {
            <button type="button" (click)="requestPortal()" [disabled]="busy()">{{ t("Get a fresh Paddle billing portal link") }}</button>
          } @else { <p>{{ t("Billing portal recovery is not currently configured.") }}</p> }
          @if (portalUrl()) { <p><a [href]="portalUrl()" target="_blank" rel="noopener noreferrer">{{ t("Open temporary Paddle portal") }}</a>
            {{ t("(invoices, payment methods and cancellation)") }}</p> }
        }
        @if (!sellerConfigured()) { <p role="status">{{ t("Hosted checkout is not configured for this organization.") }}</p> }
        @if (attempts().length) {
          <h2>{{ t("Checkout attempts") }}</h2>
          <ul>@for (attempt of attempts(); track attempt.id) {
            <li>{{ t("Attempt") }} {{ attempt.id }}: <span lang="en">{{ attempt.state }}</span>.
              @if (attempt.state === 'unknown' || attempt.state === 'sending') {
                {{ t("The provider outcome needs billing review. Do not submit another payment request.") }}
              }
              @if (attempt.payment_captured) {
                {{ t("The provider reports payment captured. Paid access awaits current subscription reconciliation.") }}
              }
              @if (attempt.state === 'ready' && attempt.checkout_url) {
                {{ t("The payment is not yet confirmed.") }}
                <button type="button" (click)="openCheckout(attempt.checkout_url)" [disabled]="busy()">{{ t("Review Paddle checkout") }}</button>
              }
              <button type="button" (click)="receiptAttempt.set(attempt)" [disabled]="busy()">{{ t("Select attempt") }} {{ attempt.id }} {{ t("for browser receipt inspection") }}</button>
            </li>
          }</ul>
        } @else { <p>{{ t("No checkout attempt has been recorded.") }}</p> }
        @if (receiptAttempt(); as selected) {
          <app-checkout-link-receipt [language]="uiLanguage()" [organizationId]="organizationId()" [attemptId]="selected.id" [checkoutUrl]="selected.checkout_url" />
        }
        @if (sellerConfigured() && canStartNewCheckout()) {
          <label for="billing-consent"><input id="billing-consent" type="checkbox" (change)="setConsent($event)" [checked]="consented()" />
            {{ t("I understand the monthly renewal, immediate early-trial charge, provider-calculated tax and period-end cancellation.") }}
          </label>
          <button type="button" (click)="beginCheckout()" [disabled]="busy() || !consented()">{{ t("Continue to Paddle for review") }}</button>
        }
      }
    </section>
  `,
})
export class OrganizationBilling implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  textLanguage(text: string) { return Object.hasOwn(organizationBillingTurkish, text) ? this.uiLanguage() : 'en'; }
  t(text: string) { return this.textLanguage(text) === 'tr' ? organizationBillingTurkish[text] : text; }
  readonly organizationId = signal(0);
  readonly loading = signal(true);
  readonly denied = signal(false);
  readonly busy = signal(false);
  readonly consented = signal(false);
  readonly sellerConfigured = signal(false);
  readonly canStartNewCheckout = signal(false);
  readonly attempts = signal<Attempt[]>([]);
  readonly receiptAttempt = signal<Attempt | null>(null);
  readonly subscriptionLinked = signal(false);
  readonly portalAvailable = signal(false);
  readonly portalUrl = signal<string | null>(null);
  readonly billingAccessState = signal('unverified');
  readonly firstPaidObservation = signal<FirstPaidObservation | null>(null);
  readonly paidTiming = signal<PaidTiming | null>(null);
  readonly timingLoading = signal(false);
  readonly timingError = signal('');
  readonly trialActivation = signal<TrialActivation | null>(null);
  readonly trialPaidTiming = signal<TrialPaidTiming | null>(null);
  readonly trialPaidWindow = signal<TrialPaidWindow | null>(null);
  readonly trialTimingLoading = signal(false);
  readonly trialTimingError = signal('');
  readonly error = signal('');
  readonly message = signal('');
  private requestId = 0;
  private requestKey = '';

  constructor(private readonly api: AccountApi, private readonly route: ActivatedRoute,
              private readonly router: Router, private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Organization billing')} — OrganicSEOOps`));
    destroyRef.onDestroy(() => { this.requestId++; this.firstPaidObservation.set(null); this.clearPaidTiming(); this.clearTrialPaidTiming(); });
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(params => {
      const id = Number(params.get('organizationId'));
      this.organizationId.set(Number.isSafeInteger(id) && id > 0 ? id : 0);
      this.consented.set(false);
      this.requestKey = '';
      this.attempts.set([]);
      this.portalUrl.set(null); this.portalAvailable.set(false); this.subscriptionLinked.set(false);
      this.canStartNewCheckout.set(false);
      this.billingAccessState.set('unverified');
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

  setConsent(event: Event) { this.consented.set((event.target as HTMLInputElement).checked); }

  private clearPaidTiming() {
    this.paidTiming.set(null); this.timingError.set('');
    if (this.timingLoading()) this.busy.set(false);
    this.timingLoading.set(false);
  }

  private clearTrialPaidTiming() {
    this.trialActivation.set(null); this.trialPaidTiming.set(null); this.trialPaidWindow.set(null); this.trialTimingError.set('');
    if (this.trialTimingLoading()) this.busy.set(false);
    this.trialTimingLoading.set(false);
  }

  async inspectTrialPaidTiming(kind: 'timing' | 'window' = 'timing') {
    const org = this.organizationId(), loaded = this.firstPaidObservation();
    if (!org || !loaded || this.loading() || this.denied() || this.busy()) return;
    const paid = structuredClone(loaded), request = ++this.requestId;
    const current = () => request === this.requestId && org === this.organizationId()
      && JSON.stringify(this.firstPaidObservation()) === JSON.stringify(paid);
    const checkPaid = async () => {
      const result = await this.api.organizationCheckout(org);
      if (!current()) return false;
      const fresh = readFirstPaidObservation(result.body['first_paid_observation'], org);
      if (result.status !== 200 || !fresh || JSON.stringify(fresh) !== JSON.stringify(paid)) throw new Error();
      return true;
    };
    this.clearPaidTiming(); this.clearTrialPaidTiming(); this.trialTimingLoading.set(true); this.busy.set(true);
    try {
      if (!await checkPaid()) return;
      const original = await this.api.organizationTrialActivation(org);
      if (!current()) return;
      const parsed = readTrialActivation(original.body, org);
      if (original.status !== 200 || !parsed) throw new Error();
      const trial = structuredClone(parsed);
      const result = await (kind === 'window' ? this.api.organizationTrialPaidWindow(org) : this.api.organizationTrialPaidTiming(org));
      if (!current()) return;
      const timing = kind === 'window' ? await readTrialPaidWindow(result.body, trial, paid) : await readTrialPaidTiming(result.body, trial, paid);
      if (!current()) return;
      if (result.status !== 200 || !timing) throw new Error();
      const final = await this.api.organizationTrialActivation(org);
      if (!current()) return;
      const fresh = readTrialActivation(final.body, org);
      if (final.status !== 200 || !fresh || JSON.stringify(fresh) !== JSON.stringify(trial)) throw new Error();
      if (!await checkPaid()) return;
      this.trialActivation.set(trial);
      if (kind === 'window') this.trialPaidWindow.set(structuredClone(timing as TrialPaidWindow));
      else this.trialPaidTiming.set(structuredClone(timing as TrialPaidTiming));
    } catch { if (current()) {
      this.clearTrialPaidTiming(); this.firstPaidObservation.set(null);
      this.trialTimingError.set("Original trial-to-paid server evidence unavailable or needs billing review. Refresh billing status; unknown originals supply no duration or window outcome.");
    } } finally { if (request === this.requestId) { this.trialTimingLoading.set(false); this.busy.set(false); } }
  }

  async inspectPaidTiming() {
    const org = this.organizationId(), loaded = this.firstPaidObservation();
    if (!org || !loaded || this.loading() || this.denied() || this.busy()) return;
    const history = structuredClone(loaded), request = ++this.requestId;
    const current = () => request === this.requestId && org === this.organizationId()
      && JSON.stringify(this.firstPaidObservation()) === JSON.stringify(history);
    const checkHistory = async () => {
      const result = await this.api.organizationCheckout(org);
      if (!current()) return false;
      const fresh = readFirstPaidObservation(result.body['first_paid_observation'], org);
      if (result.status !== 200 || !fresh || fresh.state !== history.state
        || (history.observation ? !fresh.observation || Object.keys(history.observation).some(key =>
          fresh.observation![key as keyof typeof fresh.observation] !== history.observation![key as keyof typeof history.observation])
          : fresh.observation !== null)) throw new Error();
      return true;
    };
    this.clearTrialPaidTiming(); this.clearPaidTiming(); this.timingLoading.set(true); this.busy.set(true);
    try {
      if (!await checkHistory()) return;
      const result = await this.api.organizationPaidObservationTiming(org);
      if (!current()) return;
      const timing = readPaidTiming(result.body, history);
      if (result.status !== 200 || !timing) throw new Error();
      if (!await checkHistory()) return;
      this.paidTiming.set(structuredClone(timing));
    } catch { if (current()) {
      this.paidTiming.set(null); this.firstPaidObservation.set(null);
      this.timingError.set("Original paid server timing unavailable or needs billing review. Refresh billing status; unknown history supplies no duration.");
    } } finally { if (request === this.requestId) { this.timingLoading.set(false); this.busy.set(false); } }
  }

  async load() {
    const org = this.organizationId();
    const request = ++this.requestId;
    this.clearPaidTiming();
    this.clearTrialPaidTiming();
    this.receiptAttempt.set(null);
    this.firstPaidObservation.set(null);
    this.loading.set(true); this.error.set('');
    if (!org) { this.denied.set(true); this.loading.set(false); return; }
    try {
      const response = await this.api.organizationCheckout(org);
      if (request !== this.requestId || org !== this.organizationId()) return;
      const rows = response.body['attempts'];
      const observation = readFirstPaidObservation(response.body['first_paid_observation'], org);
      if (response.status !== 200 || response.body['offer_version'] !== 'agency-launch-v1'
        || typeof response.body['seller_configured'] !== 'boolean'
        || typeof response.body['can_start_new_checkout'] !== 'boolean'
        || typeof response.body['subscription_linked'] !== 'boolean'
        || typeof response.body['portal_available'] !== 'boolean'
        || typeof response.body['billing_access_state'] !== 'string'
        || !['unverified', 'unavailable', 'paid_active', 'cancellation_scheduled', 'payment_grace',
            'read_only', 'retained_read_only', 'retention_elapsed', 'billing_review_hold'].includes(response.body['billing_access_state'])
         || !observation || !Array.isArray(rows) || rows.length > 20 || !rows.every(readAttempt)) throw new Error();
      this.attempts.set(rows as Attempt[]);
      this.sellerConfigured.set(response.body['seller_configured']);
      this.canStartNewCheckout.set(response.body['can_start_new_checkout']);
      this.subscriptionLinked.set(response.body['subscription_linked']);
      this.portalAvailable.set(response.body['portal_available']);
      this.billingAccessState.set(response.body['billing_access_state'] as string);
       this.firstPaidObservation.set(structuredClone(observation));
      this.portalUrl.set(null);
      this.denied.set(false);
    } catch {
      if (request === this.requestId) { this.denied.set(true); this.attempts.set([]); }
    } finally { if (request === this.requestId) this.loading.set(false); }
  }

  async beginCheckout() {
    const org = this.organizationId();
    if (!org || this.busy() || !this.consented() || !this.sellerConfigured() || !this.canStartNewCheckout()) return;
    this.requestKey ||= crypto.randomUUID();
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.startOrganizationCheckout(org, this.requestKey);
      if (org !== this.organizationId()) return;
      if (![200, 202].includes(response.status) || typeof response.body['state'] !== 'string'
        || !['ready', 'reserved', 'sending', 'unknown'].includes(response.body['state'])) throw new Error();
      this.message.set(response.body['state'] === 'ready'
        ? "A checkout is prepared. Review the provider amount and tax before confirming payment."
        : "Checkout is not ready. Refresh status; an uncertain provider outcome must be reviewed before another attempt.");
      await this.load();
    } catch { if (org === this.organizationId()) this.error.set("Checkout could not be confirmed. Refresh status before trying the same request again."); }
    finally { this.busy.set(false); }
  }

  openCheckout(value: string | null) {
    const path = localCheckoutPath(value);
    if (path) void this.router.navigateByUrl(path);
    else this.error.set("The payment page link is not on the approved account host. Refresh billing status.");
  }

  async requestPortal() {
    const org = this.organizationId();
    if (!org || this.busy() || !this.portalAvailable() || !this.subscriptionLinked()) return;
    this.busy.set(true); this.error.set(''); this.portalUrl.set(null);
    try {
      const response = await this.api.createOrganizationPortal(org);
      if (org !== this.organizationId()) return;
      const link = response.status === 200 ? safePortalUrl(response.body['portal_url']) : null;
      if (!link) throw new Error();
      this.portalUrl.set(link);
      this.message.set("This temporary Paddle portal link is available for this session only.");
    } catch { if (org === this.organizationId()) this.error.set("The billing portal is unavailable. Refresh and try again later."); }
    finally { this.busy.set(false); }
  }
}
