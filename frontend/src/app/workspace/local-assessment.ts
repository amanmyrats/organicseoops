import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';

type Assessment = { id: number; location_digest: string; revision: number; configuration_revision: number;
  source_current: boolean; location_label: string; business_name: string; address_display: string;
  phone: string; hours: string; services: string[]; service_areas: string[]; profile_url: string;
  eligibility: string; review_theme: string; evidence_note: string; suggested_action: string;
  actor_id: number; reviewed_at: string; verification_state: string };

function isAssessment(value: unknown): value is Assessment {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && typeof row['location_digest'] === 'string' && /^[0-9a-f]{64}$/.test(row['location_digest'])
    && Number.isSafeInteger(row['revision']) && Number.isSafeInteger(row['configuration_revision'])
    && typeof row['source_current'] === 'boolean' && typeof row['business_name'] === 'string'
    && typeof row['location_label'] === 'string' && typeof row['evidence_note'] === 'string'
    && typeof row['eligibility'] === 'string' && Array.isArray(row['services'])
    && Array.isArray(row['service_areas']) && row['verification_state'] === 'manual_user_supplied_not_listing_or_provider_verified';
}

@Component({
  selector: 'app-local-assessment',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="local-title">
      <h1 id="local-title">{{ t('Manual local business assessment') }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t('Unreviewed Turkish manual local-assessment interface draft in local development. Stored eligibility states and other screens remain English; bilingual approval is pending.') }}</p> }
      <p><a routerLink="/app">{{ t('Return to workspace') }}</a></p>
      <p><a [routerLink]="['/app/business-profile', organizationId, projectId]">{{ t('Separate authorized Google profile/review reader') }}</a> {{ t('(response-only; live access unverified)') }}</p>
      <p><a [routerLink]="['/app/local-feedback', organizationId, projectId]">{{ t('Independent customer-owned website feedback and human reply review') }}</a></p>
      <p><a [routerLink]="['/app/local-visibility', organizationId, projectId]">{{ t('Manual location/context-specific organic-link observations') }}</a></p>
      <p>{{ t('Only details explicitly entered for this project are reviewed. No Google Business Profile account, listing, review, local ranking or location eligibility has been verified. Missing information is') }} <strong>{{ t('unknown') }}</strong>{{ t(', not an inconsistency.') }}</p>
      @if (loading()) { <p role="status">{{ t('Loading current project business facts.') }}</p> }
      @if (error()) { <p role="alert">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <button type="button" (click)="load()" [disabled]="busy()">{{ t('Refresh manual assessments') }}</button>
        @if (truncated()) { <p>{{ t('Only the first 50 reviewed locations are shown.') }}</p> }
        @if (!assessments().length) { <p>{{ t('No local business facts have been assessed for this project.') }}</p> }
        <ul [attr.aria-label]="t('Project manual local business reviews')">
          @for (row of assessments(); track row.location_digest) {
            <li>
              <h2><span lang="">{{ row.location_label }}</span>{{ row.location_label ? '' : t('General service-area review') }} · {{ t('revision') }} {{ row.revision }}</h2>
              <p><span lang="">{{ row.business_name }}</span> · <span lang="">{{ row.address_display }}</span>{{ row.address_display ? '' : t('No address supplied') }} · <span lang="">{{ row.phone }}</span>{{ row.phone ? '' : t('No phone supplied') }}.</p>
              <p>{{ t('Hours:') }} <span lang="">{{ row.hours }}</span>{{ row.hours ? '' : t('Unknown') }}. {{ t('Actual user-entered services:') }} <span lang="">{{ row.services.join(', ') }}</span>. {{ t('Service areas:') }} <span lang="">{{ row.service_areas.join(', ') }}</span>{{ row.service_areas.length ? '' : t('none entered') }}.</p>
              <p>{{ t('Profile link:') }} <span lang="">{{ row.profile_url }}</span>{{ row.profile_url ? '' : t('unavailable') }}. {{ t('Eligibility:') }} <span lang="en">{{ row.eligibility }}</span> {{ t('— user claim only, not provider approved.') }} {{ t('Review theme:') }} <span lang="">{{ row.review_theme }}</span>{{ row.review_theme ? '' : t('none entered') }}.</p>
              <p>{{ t('Owner evidence/limits:') }} <span lang="">{{ row.evidence_note }}</span>. {{ t('Human page/action idea:') }} <span lang="">{{ row.suggested_action }}</span>{{ row.suggested_action ? '' : t('none') }}.</p>
              <p>{{ t(row.source_current ? 'Based on current project configuration.' : 'Historical facts; configuration changed, review again.') }} {{ t('No discrepancy is automatically detected.') }}</p>
              <button type="button" (click)="history(row.location_digest)">{{ t('Inspect correction history') }}</button>
              @if (canManage() && row.source_current) { <button type="button" (click)="edit(row)">{{ t('Correct this review') }}</button> }
            </li>
          }
        </ul>
        @if (historyRows().length) {
          <section aria-labelledby="local-history-title">
            <h2 id="local-history-title">{{ t('Immutable manual review revisions') }}</h2>
            <ol>@for (row of historyRows(); track row.id) {
              <li>{{ t('Revision') }} {{ row.revision }} · {{ row.reviewed_at }} · <span lang="">{{ row.evidence_note }}</span> · {{ t('eligibility') }} <span lang="en">{{ row.eligibility }}</span> {{ t('(unverified)') }}</li>
            }</ol>
          </section>
        }
        @if (canManage()) {
          <section aria-labelledby="local-form-title"><h2 id="local-form-title">{{ t(editing() ? 'Correct manual evidence' : 'Review selected business facts') }}</h2>
            @if (!locations().length && !serviceAreas().length) {
              <p>{{ t('Add an actual business location or service area in project onboarding first. A domain/city alone does not establish profile eligibility.') }}</p>
            } @else {
              <form (submit)="save($event)">
                <label for="local-location">{{ t('Configured location (or general service-area review)') }}</label>
                <select lang="" id="local-location" name="location_label">
                  @for (location of locations(); track location) {
                    <option lang="" [value]="location" [selected]="location === editing()?.location_label">{{ location }}</option>
                  }
                  @if (serviceAreas().length) { <option [attr.lang]="uiLanguage()" value="" [selected]="editing()?.location_label === ''">{{ t('General service-area review') }}</option> }
                </select>
                <label for="local-name">{{ t('Business name confirmed by the owner') }}</label>
                <input lang="" id="local-name" name="business_name" maxlength="160" required [value]="editing()?.business_name || ''" />
                <label for="local-address">{{ t('Address/display difference note (blank for undisclosed service area)') }}</label>
                <input lang="" id="local-address" name="address_display" maxlength="512" [value]="editing()?.address_display || ''" />
                <label for="local-phone">{{ t('Owner-confirmed phone') }}</label>
                <input lang="" id="local-phone" name="phone" maxlength="64" [value]="editing()?.phone || ''" />
                <label for="local-hours">{{ t('Hours recorded in current project configuration') }}</label>
                <input lang="" id="local-hours" name="hours" maxlength="500" [value]="editing()?.hours || configuredHours()" />
                <label for="local-services">{{ t('Real services (one per line, maximum 20)') }}</label>
                <textarea lang="" id="local-services" name="services" required>{{ editing()?.services.join('\n') || '' }}</textarea>
                <fieldset><legend>{{ t('Current configured service areas') }}</legend>
                  @for (area of serviceAreas(); track area) {
                    <label><input type="checkbox" [checked]="selectedAreas().includes(area)" (change)="toggleArea(area)" /><span lang="">{{ area }}</span></label>
                  }
                </fieldset>
                <label for="local-profile">{{ t('Configured public profile URL (not checked by us)') }}</label>
                <select lang="" id="local-profile" name="profile_url"><option [attr.lang]="uiLanguage()" value="">{{ t('No reviewed profile') }}</option>
                  @for (url of profiles(); track url) { <option lang="" [value]="url" [selected]="url === editing()?.profile_url">{{ url }}</option> }
                </select>
                <label for="local-eligibility">{{ t('Profile eligibility evidence state') }}</label>
                <select lang="en" id="local-eligibility" name="eligibility">
                  @for (state of eligibilityStates; track state) { <option [value]="state" [selected]="state === editing()?.eligibility">{{ state }}</option> }
                </select>
                <p>{{ t('(not provider verified)') }}</p>
                <label for="local-theme">{{ t('Optional manually reported review theme (never scraped)') }}</label>
                <input lang="" id="local-theme" name="review_theme" maxlength="240" [value]="editing()?.review_theme || ''" />
                <label for="local-note">{{ t('Owner evidence, eligibility limits and source date/context') }}</label>
                <textarea lang="" id="local-note" name="evidence_note" required maxlength="500">{{ editing()?.evidence_note || '' }}</textarea>
                <label for="local-action">{{ t('Optional human idea to improve a genuinely useful existing/service page') }}</label>
                <textarea lang="" id="local-action" name="suggested_action" maxlength="500">{{ editing()?.suggested_action || '' }}</textarea>
                <button type="submit" [disabled]="busy()">{{ t('Save manual review revision') }}</button>
                @if (editing()) { <button type="button" (click)="cancelEdit()">{{ t('Cancel correction') }}</button> }
              </form>
            }
          </section>
        }
        @if (message()) { <p role="status">{{ t(message()) }}</p> }
      }
    </section>
  `,
  styles: `
    form { display: grid; gap: 0.6rem; max-width: 48rem; }
    fieldset { display: grid; gap: 0.4rem; }
    li { margin-block: 1.5rem; }
  `,
})
export class LocalAssessment implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? localAssessmentTurkish[text] ?? text : text; }
  readonly eligibilityStates = ['unknown', 'review_needed', 'user_attested'];
  readonly loading = signal(true);
  readonly error = signal('');
  readonly message = signal('');
  readonly busy = signal(false);
  readonly canManage = signal(false);
  readonly truncated = signal(false);
  readonly assessments = signal<Assessment[]>([]);
  readonly historyRows = signal<Assessment[]>([]);
  readonly editing = signal<Assessment | null>(null);
  readonly locations = signal<string[]>([]);
  readonly serviceAreas = signal<string[]>([]);
  readonly profiles = signal<string[]>([]);
  readonly configuredHours = signal('');
  readonly selectedAreas = signal<string[]>([]);
  protected organizationId = 0;
  protected projectId = 0;
  private configRevision = 0;
  private generation = 0;
  private requestKey = '';

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Manual local business review')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.projectId = Number(params.get('projectId'));
      this.generation++;
      this.assessments.set([]); this.historyRows.set([]); this.editing.set(null); this.selectedAreas.set([]);
      this.locations.set([]); this.serviceAreas.set([]); this.profiles.set([]);
      this.canManage.set(false); this.busy.set(false); this.message.set(''); this.error.set(''); this.requestKey = '';
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0
          && Number.isSafeInteger(this.projectId) && this.projectId > 0) void this.load();
      else { this.loading.set(false); this.error.set('Select an authorized project.'); }
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

  async load() {
    const generation = ++this.generation;
    this.loading.set(true); this.error.set(''); this.assessments.set([]);
    this.canManage.set(false); this.historyRows.set([]);
    try {
      const [onboarding, response] = await Promise.all([
        this.api.projectOnboarding(this.organizationId, this.projectId),
        this.api.localAssessments(this.organizationId, this.projectId),
      ]);
      if (generation !== this.generation) return;
      if (onboarding.status !== 200 || response.status !== 200
          || response.body['project_id'] !== this.projectId || !Array.isArray(response.body['assessments'])
          || !(response.body['assessments'] as unknown[]).every(isAssessment)
          || !onboarding.body['project'] || !onboarding.body['configuration']) throw new Error();
      const project = onboarding.body['project'] as Record<string, unknown>;
      const config = onboarding.body['configuration'] as Record<string, unknown>;
      if (project['id'] !== this.projectId || project['organization_id'] !== this.organizationId
          || typeof project['role'] !== 'string' || !['owner', 'admin', 'member', 'viewer'].includes(project['role'])
          || config['project_id'] !== this.projectId || !Number.isSafeInteger(config['revision'])
          || typeof config['business_hours'] !== 'string'
          || !['business_locations', 'service_areas', 'profile_urls'].every((key) =>
            Array.isArray(config[key]) && config[key].every((value: unknown) => typeof value === 'string'))) throw new Error();
      this.configRevision = Number(config['revision']);
      this.locations.set(config['business_locations'] as string[]);
      this.serviceAreas.set(config['service_areas'] as string[]);
      this.profiles.set(config['profile_urls'] as string[]);
      this.configuredHours.set(config['business_hours']);
      this.canManage.set(['owner', 'admin'].includes(project['role']));
      this.assessments.set(response.body['assessments'] as Assessment[]);
      this.truncated.set(response.body['has_more'] === true);
    } catch {
      if (generation === this.generation) this.error.set('Manual local evidence is unavailable for this project or session.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  toggleArea(area: string) {
    const values = this.selectedAreas();
    this.selectedAreas.set(values.includes(area) ? values.filter((value) => value !== area) : [...values, area]);
  }

  edit(row: Assessment) {
    this.editing.set(row);
    this.selectedAreas.set(row.service_areas.filter((area) => this.serviceAreas().includes(area)));
    this.requestKey = '';
  }

  cancelEdit() { this.editing.set(null); this.selectedAreas.set([]); this.requestKey = ''; this.message.set(''); }

  async history(digest: string) {
    const generation = this.generation;
    this.historyRows.set([]);
    try {
      const response = await this.api.localAssessmentHistory(this.organizationId, this.projectId, digest);
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.body['project_id'] !== this.projectId
          || !Array.isArray(response.body['history']) || !(response.body['history'] as unknown[]).every(isAssessment)) throw new Error();
      this.historyRows.set(response.body['history'] as Assessment[]);
    } catch {
      if (generation === this.generation) this.message.set('Review history is unavailable; refresh this project.');
    }
  }

  async save(event: Event) {
    event.preventDefault();
    if (this.busy() || !this.canManage()) return;
    const form = event.target as HTMLFormElement;
    if (!form.reportValidity()) return;
    const fields = new FormData(form);
    const current = this.editing();
    const generation = this.generation;
    this.requestKey ||= crypto.randomUUID();
    const data: Record<string, unknown> = {
      request_key: this.requestKey, expected_config_revision: this.configRevision,
      location_label: String(fields.get('location_label') || ''),
      business_name: String(fields.get('business_name') || ''),
      address_display: String(fields.get('address_display') || ''), phone: String(fields.get('phone') || ''),
      hours: String(fields.get('hours') || ''),
      services: String(fields.get('services') || '').split('\n').map((item) => item.trim()).filter(Boolean),
      service_areas: this.selectedAreas(), profile_url: String(fields.get('profile_url') || ''),
      eligibility: String(fields.get('eligibility') || ''), review_theme: String(fields.get('review_theme') || ''),
      evidence_note: String(fields.get('evidence_note') || ''),
      suggested_action: String(fields.get('suggested_action') || ''),
    };
    if (current) data['expected_revision'] = current.revision;
    this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.saveLocalAssessment(this.organizationId, this.projectId, data,
        current?.location_digest);
      if (generation !== this.generation) return;
      const row = response.body['assessment'];
      if (![200, 201].includes(response.status) || response.body['project_id'] !== this.projectId
          || !isAssessment(row) || row.revision !== (current ? current.revision + 1 : 1)) throw new Error();
      this.requestKey = ''; this.editing.set(null); this.selectedAreas.set([]); this.busy.set(false);
      form.reset();
      await this.load();
      if (generation + 1 === this.generation) this.message.set('Manual review saved; profile, reviews and eligibility remain unverified.');
    } catch {
      if (generation === this.generation) this.message.set('Review outcome unknown or configuration changed; refresh before retrying.');
    } finally {
      if (generation === this.generation) this.busy.set(false);
    }
  }
}

const localAssessmentTurkish: Record<string, string> = {
  "Manual local business review": "Elle yerel işletme incelemesi",
  "Manual local business assessment": "İşletme için elle yerel değerlendirme",
  "Unreviewed Turkish manual local-assessment interface draft in local development. Stored eligibility states and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe elle yerel değerlendirme arayüzü taslağı. Kaydedilen uygunluk durumları ve diğer ekranlar İngilizce kalır; iki dilli onay bekleniyor.",
  "Return to workspace": "Çalışma alanına dön",
  "Separate authorized Google profile/review reader": "Ayrı, yetkilendirilmiş Google profil/yorum okuyucusu",
  "(response-only; live access unverified)": "(yalnızca yanıt; canlı erişim doğrulanmadı)",
  "Independent customer-owned website feedback and human reply review": "Müşterinin kendi sitesinden bağımsız geri bildirim ve insan yanıt incelemesi",
  "Manual location/context-specific organic-link observations": "Konuma/bağlama özel elle organik bağlantı gözlemleri",
  "Only details explicitly entered for this project are reviewed. No Google Business Profile account, listing, review, local ranking or location eligibility has been verified. Missing information is": "Yalnızca bu proje için açıkça girilen bilgiler incelenir. Hiçbir Google İşletme Profili hesabı, kaydı, yorumu, yerel sıralaması veya konum uygunluğu doğrulanmadı. Eksik bilgi",
  "unknown": "bilinmiyor",
  ", not an inconsistency.": "; tutarsızlık değildir.",
  "Loading current project business facts.": "Güncel proje işletme bilgileri yükleniyor.",
  "Refresh manual assessments": "Elle değerlendirmeleri yenile",
  "Only the first 50 reviewed locations are shown.": "Yalnızca incelenmiş ilk 50 konum gösterilir.",
  "No local business facts have been assessed for this project.": "Bu proje için henüz yerel işletme bilgileri değerlendirilmedi.",
  "Project manual local business reviews": "Projenin elle yerel işletme incelemeleri",
  "General service-area review": "Genel hizmet bölgesi incelemesi",
  "revision": "sürüm",
  "No address supplied": "Adres girilmedi",
  "No phone supplied": "Telefon girilmedi",
  "Hours:": "Çalışma saatleri:",
  "Unknown": "Bilinmiyor",
  "Actual user-entered services:": "Kullanıcının girdiği gerçek hizmetler:",
  "Service areas:": "Hizmet bölgeleri:",
  "none entered": "girilmedi",
  "Profile link:": "Profil bağlantısı:",
  "unavailable": "kullanılamıyor",
  "Eligibility:": "Uygunluk:",
  "— user claim only, not provider approved.": "— yalnızca kullanıcı beyanı; sağlayıcı onayı değildir.",
  "Review theme:": "Yorum teması:",
  "Owner evidence/limits:": "İşletme sahibinin kanıtı/sınırları:",
  "Human page/action idea:": "İnsanın sayfa/eylem fikri:",
  "none": "yok",
  "Based on current project configuration.": "Güncel proje yapılandırmasına dayanır.",
  "Historical facts; configuration changed, review again.": "Geçmiş bilgiler; yapılandırma değişti, tekrar inceleyin.",
  "No discrepancy is automatically detected.": "Hiçbir uyuşmazlık otomatik olarak tespit edilmez.",
  "Inspect correction history": "Düzeltme geçmişini incele",
  "Correct this review": "Bu incelemeyi düzelt",
  "Immutable manual review revisions": "Değiştirilemez elle inceleme sürümleri",
  "Revision": "Sürüm",
  "eligibility": "uygunluk",
  "(unverified)": "(doğrulanmadı)",
  "Correct manual evidence": "Elle girilen kanıtı düzelt",
  "Review selected business facts": "Seçilen işletme bilgilerini incele",
  "Add an actual business location or service area in project onboarding first. A domain/city alone does not establish profile eligibility.": "Önce proje kurulumunda gerçek bir işletme konumu veya hizmet bölgesi ekleyin. Yalnızca alan adı/şehir, profil uygunluğunu kanıtlamaz.",
  "Configured location (or general service-area review)": "Yapılandırılmış konum (veya genel hizmet bölgesi incelemesi)",
  "Business name confirmed by the owner": "İşletme sahibinin doğruladığı işletme adı",
  "Address/display difference note (blank for undisclosed service area)": "Adres/gösterim farkı notu (açıklanmayan hizmet bölgesi için boş bırakın)",
  "Owner-confirmed phone": "İşletme sahibinin doğruladığı telefon",
  "Hours recorded in current project configuration": "Güncel proje yapılandırmasında kayıtlı çalışma saatleri",
  "Real services (one per line, maximum 20)": "Gerçek hizmetler (satır başına bir, en fazla 20)",
  "Current configured service areas": "Güncel yapılandırılmış hizmet bölgeleri",
  "Configured public profile URL (not checked by us)": "Yapılandırılmış herkese açık profil URL’si (tarafımızca kontrol edilmedi)",
  "No reviewed profile": "İncelenmiş profil yok",
  "Profile eligibility evidence state": "Profil uygunluğu kanıt durumu",
  "(not provider verified)": "(sağlayıcı tarafından doğrulanmadı)",
  "Optional manually reported review theme (never scraped)": "İsteğe bağlı, elle bildirilen yorum teması (asla kazınmaz)",
  "Owner evidence, eligibility limits and source date/context": "İşletme sahibinin kanıtı, uygunluk sınırları ve kaynak tarihi/bağlamı",
  "Optional human idea to improve a genuinely useful existing/service page": "Gerçekten yararlı mevcut/hizmet sayfasını iyileştirmek için isteğe bağlı insan fikri",
  "Save manual review revision": "Elle inceleme sürümünü kaydet",
  "Cancel correction": "Düzeltmeyi iptal et",
  "Select an authorized project.": "Yetkili bir proje seçin.",
  "Manual local evidence is unavailable for this project or session.": "Bu proje veya oturum için elle yerel kanıt kullanılamıyor.",
  "Review history is unavailable; refresh this project.": "İnceleme geçmişi kullanılamıyor; bu projeyi yenileyin.",
  "Manual review saved; profile, reviews and eligibility remain unverified.": "Elle inceleme kaydedildi; profil, yorumlar ve uygunluk hâlâ doğrulanmadı.",
  "Review outcome unknown or configuration changed; refresh before retrying.": "İnceleme sonucu bilinmiyor veya yapılandırma değişti; yeniden denemeden önce yenileyin."
};
