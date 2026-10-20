import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, OnInit, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AccountApi } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { environment } from '../../environments/environment';

type ModelCount = { model: string; count: number; latest_id: number | null };
type StorageCount = { project_id: number; visible_count: number };
type SnapshotPart = { position: number; size_bytes: number; sha256: string; download_path: string;
  source?: { kind: string; model?: string; project_id?: number; artifact_index?: number; offset?: number } };
type SnapshotSummary = { id: number; state: 'ready' | 'preparing' | 'failed' | 'expired'; created_at: string; expires_at?: string | null; manifest_path: string | null };

const organizationExportTurkish: Record<string, string> = {
  "Organization customer-data export inventory": "Kuruluş müşteri verisi dışa aktarma envanteri",
  "Organization": "Kuruluş",
  "customer-data export inventory": "müşteri verisi dışa aktarma envanteri",
  "Return to organization selection": "Kuruluş seçimine dön",
  "This owner-only inventory lists current record counts and visible private storage objects, not a complete or immutable organization export. Downloaded record pages omit credentials and bearer fields; source artifacts are separate private downloads. Billing/security audit records remain restricted. Do not close an organization on the assumption that this inventory proves every copy was exported or deleted.": "Yalnızca sahiplerin erişebildiği bu envanter, güncel kayıt sayılarını ve görünür özel depolama nesnelerini listeler; tam veya değişmez bir kuruluş dışa aktarımı değildir. İndirilen kayıt sayfaları kimlik bilgilerini ve bearer alanlarını içermez; kaynak dosyaları ayrı özel indirmelerdir. Faturalama/güvenlik denetim kayıtları kısıtlı kalır. Bu envanterin her kopyanın dışa aktarıldığını veya silindiğini kanıtladığını varsayarak kuruluşu kapatmayın.",
  "Checking current organization export permission.": "Güncel kuruluş dışa aktarma izni kontrol ediliyor.",
  "Download one current customer-content archive": "Güncel müşteri içeriğini tek arşiv olarak indir",
  "The bounded ZIP contains the currently stored customer-owned model rows and visible project artifacts, with a per-file digest manifest. It excludes platform/OAuth secrets, restricted billing/audit records, hidden S3 versions and backups. If this organization's data exceeds the 5,000-row, 1,000-object-per-project or 32 MiB ceiling, no archive is issued; use the individual record and artifact parts below. This is not a complete account, financial or backup export.": "Sınırlı ZIP, şu anda saklanan müşteriye ait model satırlarını ve görünür proje dosyalarını, dosya başına özet içeren bir manifest ile içerir. Platform/OAuth sırları, kısıtlı faturalama/denetim kayıtları, gizli S3 sürümleri ve yedekler hariçtir. Bu kuruluşun verileri 5.000 satır, proje başına 1.000 nesne veya 32 MiB sınırını aşarsa arşiv oluşturulmaz; aşağıdaki ayrı kayıt ve dosya parçalarını kullanın. Bu, tam bir hesap, mali kayıt veya yedek dışa aktarımı değildir.",
  "Download bounded private ZIP": "Sınırlı özel ZIP’i indir",
  "Capture a reusable private copy of this bounded ZIP": "Bu sınırlı ZIP’in yeniden kullanılabilir özel kopyasını oluştur",
  "Capture runs in the background. Refresh this page to check its status; a preparing or failed copy is not downloadable. A ready copy stays private and may expire before customer-data deletion. It has the same 5,000-row, 1,000-object-per-project and 32 MiB ceilings. Download every ready part in order, concatenate them to reconstruct the ZIP, and check the whole-file SHA-256. Three captures per organization are available; this is not an all-size legal export.": "Kopya arka planda oluşturulur. Durumunu kontrol etmek için bu sayfayı yenileyin; hazırlanan veya başarısız bir kopya indirilemez. Hazır kopya özel kalır ve müşteri verileri silinmeden önce süresi dolabilir. Aynı 5.000 satır, proje başına 1.000 nesne ve 32 MiB sınırlarına tabidir. Hazır parçaların tümünü sırayla indirin, ZIP’i yeniden oluşturmak için birleştirin ve tüm dosyanın SHA-256 özetini kontrol edin. Kuruluş başına üç kopya oluşturulabilir; bu, her boyutu kapsayan yasal bir dışa aktarım değildir.",
  "Capture bounded ZIP parts": "Sınırlı ZIP parçalarını oluştur",
  "Capture sequential source parts for larger organizations": "Daha büyük kuruluşlar için sıralı kaynak parçalarını oluştur",
  "This separate format has no whole-ZIP row, object-count or 32 MiB limit. It records up to 50 rows per page and splits each permitted source artifact into private ZIP parts. It uses initial record high-water windows and sequential visible-object observations, not a point-in-time organization snapshot: concurrent changes may be excluded or make capture fail. Restricted billing/audit, credentials, hidden storage versions and backups are excluded. Preparing or failed parts cannot be downloaded.": "Bu ayrı biçimde ZIP’in tamamı için satır, nesne sayısı veya 32 MiB sınırı yoktur. Sayfa başına en fazla 50 satır kaydeder ve izin verilen her kaynak dosyasını özel ZIP parçalarına böler. Kuruluşun tek bir andaki görüntüsü yerine başlangıçtaki kayıt üst sınırlarını ve görünür nesnelerin sıralı gözlemlerini kullanır: eşzamanlı değişiklikler dışarıda kalabilir veya kopya oluşturmayı başarısız kılabilir. Kısıtlı faturalama/denetim kayıtları, kimlik bilgileri, gizli depolama sürümleri ve yedekler hariçtir. Hazırlanan veya başarısız parçalar indirilemez.",
  "For a ready source capture, download every manifest page and each independent ZIP. Each ZIP contains data and source.json. Keep row pages by model; for an artifact, concatenate its data chunks by offset and verify the object checksum in its completion part. The capture digest commits to ordered part descriptors, not a concatenated ZIP. All captured formats share the three-capture limit.": "Hazır bir kaynak kopyası için tüm manifest sayfalarını ve her bağımsız ZIP’i indirin. Her ZIP, data ve source.json içerir. Satır sayfalarını modele göre saklayın; bir dosya için veri parçalarını ofsete göre birleştirin ve tamamlama parçasındaki nesne sağlama toplamını doğrulayın. Kopya özeti, birleştirilmiş bir ZIP yerine sıralı parça tanımlayıcılarını doğrular. Tüm kopya biçimleri aynı üç kopya sınırını paylaşır.",
  "Capture sequential source parts": "Sıralı kaynak parçalarını oluştur",
  "Capture coherent customer-content parts": "Tutarlı müşteri içeriği parçalarını oluştur",
  "This format keeps one consistent view of customer-owned records and visible private files. It has no whole-export row, object-count or 32 MiB ceiling, but must finish within nine minutes; a lost or expired capture cannot resume. It excludes restricted billing/audit records, credentials, hidden storage versions and backups, and does not establish legal export or deletion readiness. Download every manifest page and each independent ZIP using the source-part reconstruction instructions above.": "Bu biçim, müşteriye ait kayıtların ve görünür özel dosyaların tek bir tutarlı görünümünü korur. Dışa aktarımın tamamı için satır, nesne sayısı veya 32 MiB sınırı yoktur; ancak dokuz dakika içinde tamamlanmalıdır. Kaybolan veya süresi dolan kopya oluşturma işlemi sürdürülemez. Kısıtlı faturalama/denetim kayıtları, kimlik bilgileri, gizli depolama sürümleri ve yedekler hariçtir; yasal dışa aktarım veya silme hazırlığının tamamlandığını kanıtlamaz. Yukarıdaki kaynak parçası yeniden oluşturma talimatlarıyla tüm manifest sayfalarını ve her bağımsız ZIP’i indirin.",
  "Copy download expires": "Kopya indirme süresi bitişi",
  "No separate copy expiry was assigned; source retention and current permissions still apply.": "Ayrı bir kopya son kullanma tarihi atanmamış; kaynak saklama süresi ve güncel izinler geçerlidir.",
  "Expired copy: downloads are disabled; storage cleanup may still be pending.": "Kopyanın süresi dolmuş: indirmeler kapalıdır; depolama temizliği henüz tamamlanmamış olabilir.",
  "Refresh capture status": "Kopya durumunu yenile",
  "Recent private captures (including uncertain earlier requests):": "Son özel kopyalar (sonucu belirsiz önceki istekler dahil):",
  "Snapshot": "Kopya",
  "Show its parts": "Parçalarını göster",
  "Discard failed capture copy": "Başarısız kopyayı kaldır",
  "Captured snapshot": "Oluşturulan kopya",
  "bytes": "bayt",
  "Part-descriptor chain SHA-256": "Parça tanımlayıcı zinciri SHA-256",
  "ZIP SHA-256": "ZIP SHA-256",
  "Showing manifest positions": "Gösterilen manifest konumları",
  " through ": " ile ",
  " of ": " / ",
  " parts.": " parça.",
  "Download this manifest page": "Bu manifest sayfasını indir",
  "Previous manifest page": "Önceki manifest sayfası",
  "Next manifest page": "Sonraki manifest sayfası",
  "Part": "Parça",
  "Download part": "Parçayı indir",
  "Current customer-owned record groups": "Güncel müşteriye ait kayıt grupları",
  "Each response is one model page (up to 50 current rows), not an atomic snapshot of all models. New work or membership changes may invalidate an earlier inventory; refresh before relying on counts.": "Her yanıt tek bir model sayfasıdır (en fazla 50 güncel satır); tüm modellerin atomik görüntüsü değildir. Yeni işler veya üyelik değişiklikleri önceki envanteri geçersiz kılabilir; sayılara güvenmeden önce yenileyin.",
  "Source record group": "Kaynak kayıt grubu",
  "Select a model": "Bir model seçin",
  " · downloaded through ID ": " · indirilen son kimlik ",
  " of inventory high-water ID ": " / envanter üst sınır kimliği ",
  "No more recorded rows in this selected window.": "Seçilen aralıkta başka kayıtlı satır yok.",
  "Download next bounded JSON page": "Sonraki sınırlı JSON sayfasını indir",
  "Private source and report artifacts": "Özel kaynak ve rapor dosyaları",
  "Storage objects are counted only when currently visible; historical S3 versions, in-flight changes and backups require independent deletion checks. Each download requires current owner authorization and never exposes the storage key. Larger files stream as individual downloads up to the configured artifact limit. Each individual download carries a SHA-256 header; separate downloads are not a consistent organization snapshot.": "Depolama nesneleri yalnızca şu anda görünür olduklarında sayılır; eski S3 sürümleri, devam eden değişiklikler ve yedekler bağımsız silme kontrolleri gerektirir. Her indirme güncel sahip yetkisi gerektirir ve depolama anahtarını açığa çıkarmaz. Daha büyük dosyalar, yapılandırılmış dosya sınırına kadar ayrı indirmeler olarak aktarılır. Her ayrı indirme SHA-256 başlığı taşır; ayrı indirmeler kuruluşun tutarlı görüntüsü değildir.",
  "No project artifact scope is available.": "Proje dosyası kapsamı kullanılamıyor.",
  "Project": "Proje",
  "currently visible object(s).": "şu anda görünür nesne.",
  "Artifact index, starting at zero": "Sıfırdan başlayan dosya dizini",
  "Download selected private artifact": "Seçilen özel dosyayı indir",
  "Select a current organization.": "Güncel bir kuruluş seçin.",
  "Organization export inventory is unavailable or permission was revoked.": "Kuruluş dışa aktarma envanteri kullanılamıyor veya izin kaldırılmış.",
  "Private customer-content ZIP downloaded (SHA-256 ": "Özel müşteri içeriği ZIP’i indirildi (SHA-256 ",
  "). Restricted billing/account data and backups are separate.": "). Kısıtlı faturalama/hesap verileri ve yedekler ayrıdır.",
  "Complete bounded archive unavailable. Review current inventory and export permitted parts separately.": "Tam sınırlı arşiv kullanılamıyor. Güncel envanteri inceleyin ve izin verilen parçaları ayrı ayrı dışa aktarın.",
  "Private copy is ready. Download every manifest page and listed part before closing access.": "Özel kopya hazır. Erişimi kapatmadan önce tüm manifest sayfalarını ve listelenen parçaları indirin.",
  "Private capture is preparing. Refresh to check status; do not create another request while its outcome is unknown.": "Özel kopya hazırlanıyor. Durumu kontrol etmek için yenileyin; sonuç bilinmezken başka bir istek oluşturmayın.",
  "Private snapshot unavailable; check recent captures before trying again.": "Özel kopya kullanılamıyor; yeniden denemeden önce son kopyaları kontrol edin.",
  "Previous private captures are unavailable.": "Önceki özel kopyalar kullanılamıyor.",
  "Private coherent customer-content parts are ready. Download each manifest page and independent ZIP; restricted records and backups are excluded.": "Özel tutarlı müşteri içeriği parçaları hazır. Her manifest sayfasını ve bağımsız ZIP’i indirin; kısıtlı kayıtlar ve yedekler hariçtir.",
  "Private captured parts are ready. Source observations are sequential, not a transactional snapshot.": "Özel kopya parçaları hazır. Kaynak gözlemleri sıralıdır; işlemsel bir görüntü değildir.",
  "Private snapshot parts are unavailable or permission was revoked.": "Özel kopya parçaları kullanılamıyor veya izin kaldırılmış.",
  "Failed private capture removed; its slot is available again.": "Başarısız özel kopya kaldırıldı; yeri yeniden kullanılabilir.",
  "Private cleanup is still in progress. Retry this same failed capture until it is removed.": "Özel temizleme hâlâ devam ediyor. Kaldırılana kadar aynı başarısız kopyayı yeniden deneyin.",
  "Failed capture cleanup is unavailable; inspect the current status before retrying.": "Başarısız kopya temizliği kullanılamıyor; yeniden denemeden önce güncel durumu inceleyin.",
  "Page downloaded. Continue until this model window is exhausted.": "Sayfa indirildi. Bu model aralığı bitene kadar devam edin.",
  "This selected model window ended. Other models and private artifacts must be exported separately.": "Seçilen model aralığı sona erdi. Diğer modeller ve özel dosyalar ayrı ayrı dışa aktarılmalıdır.",
  "Record download unavailable; refresh the inventory and verify current permission.": "Kayıt indirme kullanılamıyor; envanteri yenileyin ve güncel izni doğrulayın.",
  "Unreviewed Turkish organization-export interface draft in local development. Stored model/state/source values and other screens remain English; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe kuruluş dışa aktarma arayüzü taslağı. Saklanan model/durum/kaynak değerleri ve diğer ekranlar İngilizce kalır; iki dilde onay bekleniyor."
};

@Component({
  selector: 'app-organization-export',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-panel" aria-labelledby="export-title">
      <h1 id="export-title">{{ t("Organization") }} {{ organizationId }} {{ t("customer-data export inventory") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish organization-export interface draft in local development. Stored model/state/source values and other screens remain English; bilingual approval is pending.") }}</p> }
      <p><a routerLink="/app">{{ t("Return to organization selection") }}</a></p>
      <p>{{ t("This owner-only inventory lists current record counts and visible private storage objects, not a complete or immutable organization export. Downloaded record pages omit credentials and bearer fields; source artifacts are separate private downloads. Billing/security audit records remain restricted. Do not close an organization on the assumption that this inventory proves every copy was exported or deleted.") }}</p>
      @if (loading()) { <p role="status">{{ t("Checking current organization export permission.") }}</p> }
      @if (error()) { <p role="alert" [attr.lang]="textLanguage(error())">{{ t(error()) }}</p> }
      @if (!loading() && !error()) {
        <section aria-labelledby="archive-title">
          <h2 id="archive-title">{{ t("Download one current customer-content archive") }}</h2>
          <p>{{ t("The bounded ZIP contains the currently stored customer-owned model rows and visible project artifacts, with a per-file digest manifest. It excludes platform/OAuth secrets, restricted billing/audit records, hidden S3 versions and backups. If this organization's data exceeds the 5,000-row, 1,000-object-per-project or 32 MiB ceiling, no archive is issued; use the individual record and artifact parts below. This is not a complete account, financial or backup export.") }}</p>
          <button type="button" [disabled]="busy()" (click)="downloadArchive()">{{ t("Download bounded private ZIP") }}</button>
          <h3>{{ t("Capture a reusable private copy of this bounded ZIP") }}</h3>
           <p>{{ t("Capture runs in the background. Refresh this page to check its status; a preparing or failed copy is not downloadable. A ready copy stays private and may expire before customer-data deletion. It has the same 5,000-row, 1,000-object-per-project and 32 MiB ceilings. Download every ready part in order, concatenate them to reconstruct the ZIP, and check the whole-file SHA-256. Three captures per organization are available; this is not an all-size legal export.") }}</p>
          <button type="button" [disabled]="busy()" (click)="captureSnapshot()">{{ t("Capture bounded ZIP parts") }}</button>
          <h3>{{ t("Capture sequential source parts for larger organizations") }}</h3>
          <p>{{ t("This separate format has no whole-ZIP row, object-count or 32 MiB limit. It records up to 50 rows per page and splits each permitted source artifact into private ZIP parts. It uses initial record high-water windows and sequential visible-object observations, not a point-in-time organization snapshot: concurrent changes may be excluded or make capture fail. Restricted billing/audit, credentials, hidden storage versions and backups are excluded. Preparing or failed parts cannot be downloaded.") }}</p>
          <p>{{ t("For a ready source capture, download every manifest page and each independent ZIP. Each ZIP contains data and source.json. Keep row pages by model; for an artifact, concatenate its data chunks by offset and verify the object checksum in its completion part. The capture digest commits to ordered part descriptors, not a concatenated ZIP. All captured formats share the three-capture limit.") }}</p>
          <button type="button" [disabled]="busy()" (click)="captureSnapshot('source-parts-v2')">{{ t("Capture sequential source parts") }}</button>
          <h3>{{ t("Capture coherent customer-content parts") }}</h3>
          <p>{{ t("This format keeps one consistent view of customer-owned records and visible private files. It has no whole-export row, object-count or 32 MiB ceiling, but must finish within nine minutes; a lost or expired capture cannot resume. It excludes restricted billing/audit records, credentials, hidden storage versions and backups, and does not establish legal export or deletion readiness. Download every manifest page and each independent ZIP using the source-part reconstruction instructions above.") }}</p>
          <button type="button" [disabled]="busy()" (click)="captureSnapshot('coherent-parts-v3')">{{ t("Capture coherent customer-content parts") }}</button>
          <button type="button" [disabled]="busy()" (click)="loadSnapshotHistory()">{{ t("Refresh capture status") }}</button>
          @if (snapshotHistoryError()) { <p role="status" [attr.lang]="textLanguage(snapshotHistoryError())">{{ t(snapshotHistoryError()) }}</p> }
          @if (snapshotHistory().length) {
            <p>{{ t("Recent private captures (including uncertain earlier requests):") }}</p>
            <ul>
              @for (item of snapshotHistory(); track item.id) {
                <li>{{ t("Snapshot") }} {{ item.id }} · <span lang="en">{{ item.state }} · {{ item.created_at }}</span>
                  @if (item.expires_at) {
                    <p>{{ t("Copy download expires") }}: <time [attr.datetime]="item.expires_at">{{ item.expires_at }}</time></p>
                  } @else if (item.state === 'ready') {
                    <p>{{ t("No separate copy expiry was assigned; source retention and current permissions still apply.") }}</p>
                  }
                  @if (item.state === 'expired') {
                    <p>{{ t("Expired copy: downloads are disabled; storage cleanup may still be pending.") }}</p>
                  }
                  @if (item.state === 'ready') {
                    <button type="button" [disabled]="busy()" (click)="loadSnapshot(item.id)">{{ t("Show its parts") }}</button>
                  }
                  @if (item.state === 'failed') {
                    <button type="button" [disabled]="busy()" (click)="discardFailedSnapshot(item.id)">{{ t("Discard failed capture copy") }}</button>
                  }
                </li>
              }
            </ul>
          }
          @if (snapshotParts().length) {
            <p>{{ t("Captured snapshot") }} {{ snapshotId() }} · {{ snapshotBytes() }} {{ t("bytes") }} ·
              {{ t(snapshotFormat() !== 'bounded-zip-v1' ? 'Part-descriptor chain SHA-256' : 'ZIP SHA-256') }} <span lang="en">{{ snapshotDigest() }}</span></p>
            @if (snapshotFormat() !== 'bounded-zip-v1') {
              <p>{{ t("Showing manifest positions") }} {{ snapshotPosition() }}{{ t(" through ") }}{{ snapshotPosition() + snapshotParts().length - 1 }}{{ t(" of ") }}{{ snapshotPartCount() }}{{ t(" parts.") }}</p>
              <a [href]="manifestUrl()" download>{{ t("Download this manifest page") }}</a>
              @if (snapshotPosition() > 0) {
                <button type="button" (click)="loadSnapshot(snapshotId(), undefined, snapshotPosition() - 50)">{{ t("Previous manifest page") }}</button>
              }
              @if (snapshotNextPosition() !== null) {
                <button type="button" (click)="loadSnapshot(snapshotId(), undefined, snapshotNextPosition()!)">{{ t("Next manifest page") }}</button>
              }
            }
            <ol>
              @for (part of snapshotParts(); track part.position) {
                <li>{{ t("Part") }} {{ part.position }} · {{ part.size_bytes }} {{ t("bytes") }} · <span lang="en">SHA-256 {{ part.sha256 }}</span>
                  @if (part.source) { <span lang="en"> · {{ part.source.kind }} {{ part.source.model || '' }}</span> }
                  <a [href]="part.download_path" download>{{ t("Download part") }} {{ part.position }}</a></li>
              }
            </ol>
          }
        </section>
        <section aria-labelledby="records-title">
          <h2 id="records-title">{{ t("Current customer-owned record groups") }}</h2>
          <p>{{ t("Each response is one model page (up to 50 current rows), not an atomic snapshot of all models. New work or membership changes may invalidate an earlier inventory; refresh before relying on counts.") }}</p>
          <label for="export-model">{{ t("Source record group") }}</label>
          <select id="export-model" (change)="chooseModel($event)">
            <option [attr.lang]="uiLanguage()" value="">{{ t("Select a model") }}</option>
            @for (item of models(); track item.model) {
              <option lang="en" [value]="item.model">{{ item.model }} · {{ item.count }} record(s)</option>
            }
          </select>
          @if (selectedModel()) {
            <p><span lang="en">{{ selectedModel() }}</span>{{ t(" · downloaded through ID ") }}{{ afterId() }}{{ t(" of inventory high-water ID ") }}{{ throughId() }}.
              @if (afterId() >= throughId()) { <span>{{ t("No more recorded rows in this selected window.") }}</span> }
            </p>
            <button type="button" [disabled]="busy() || !throughId() || afterId() >= throughId()" (click)="downloadRows()">
              {{ t("Download next bounded JSON page") }}
            </button>
          }
        </section>
        <section aria-labelledby="artifacts-title">
          <h2 id="artifacts-title">{{ t("Private source and report artifacts") }}</h2>
           <p>{{ t("Storage objects are counted only when currently visible; historical S3 versions, in-flight changes and backups require independent deletion checks. Each download requires current owner authorization and never exposes the storage key. Larger files stream as individual downloads up to the configured artifact limit. Each individual download carries a SHA-256 header; separate downloads are not a consistent organization snapshot.") }}</p>
          @if (!projects().length) { <p>{{ t("No project artifact scope is available.") }}</p> }
          @for (project of projects(); track project.project_id) {
            <div><p>{{ t("Project") }} {{ project.project_id }} · {{ project.visible_count }} {{ t("currently visible object(s).") }}</p>
              @if (project.visible_count) {
                <label [for]="'artifact-index-' + project.project_id">{{ t("Artifact index, starting at zero") }}</label>
                <input [id]="'artifact-index-' + project.project_id" type="number" min="0"
                  [max]="project.visible_count - 1" [value]="artifactIndices()[project.project_id] || 0"
                  (change)="selectArtifact(project, $event)" />
                <a [href]="artifactUrl(project)" download>{{ t("Download selected private artifact") }}</a>
              }
            </div>
          }
        </section>
        @if (message()) { <p role="status" [attr.lang]="textLanguage(message())">{{ t(message()) }}</p> }
      }
    </section>
  `,
  styles: `
    section { margin-block: 1.2rem; border-top: 1px solid #b9cfd5; overflow-wrap: anywhere; }
    label, button, select { display: block; margin-block: 0.5rem; }
    input { width: 7rem; }
  `,
})
export class OrganizationExport implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly messageDraft = signal<{ message: string; translation: string } | null>(null);
  textLanguage(text: string) {
    return Object.hasOwn(organizationExportTurkish, text) || this.messageDraft()?.message === text ? this.uiLanguage() : 'en';
  }
  t(text: string) {
    if (this.textLanguage(text) !== 'tr') return text;
    const draft = this.messageDraft();
    return draft?.message === text ? draft.translation : organizationExportTurkish[text];
  }
  private setDraftMessage(message: string, translation: string) {
    this.messageDraft.set({ message, translation });
    this.message.set(message);
  }
  readonly loading = signal(true);
  readonly error = signal('');
  readonly message = signal('');
  readonly busy = signal(false);
  readonly models = signal<ModelCount[]>([]);
  readonly projects = signal<StorageCount[]>([]);
  readonly selectedModel = signal('');
  readonly afterId = signal(0);
  readonly throughId = signal(0);
  readonly artifactIndices = signal<Record<number, number>>({});
  readonly snapshotId = signal(0);
  readonly snapshotBytes = signal(0);
  readonly snapshotDigest = signal('');
  readonly snapshotFormat = signal('bounded-zip-v1');
  readonly snapshotPosition = signal(0);
  readonly snapshotNextPosition = signal<number | null>(null);
  readonly snapshotPartCount = signal(0);
  readonly snapshotParts = signal<SnapshotPart[]>([]);
  readonly snapshotHistory = signal<SnapshotSummary[]>([]);
  readonly snapshotHistoryError = signal('');
  organizationId = 0;
  private generation = 0;
  private manifestGeneration = 0;
  private historyGeneration = 0;

  constructor(private readonly route: ActivatedRoute, private readonly api: AccountApi,
              private readonly destroyRef: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Organization customer-data export inventory')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.organizationId = Number(params.get('organizationId'));
      this.generation++;
      this.models.set([]); this.projects.set([]); this.artifactIndices.set({});
      this.snapshotId.set(0); this.snapshotBytes.set(0); this.snapshotDigest.set(''); this.snapshotParts.set([]);
      this.snapshotFormat.set('bounded-zip-v1'); this.snapshotPosition.set(0);
      this.snapshotNextPosition.set(null); this.snapshotPartCount.set(0);
      this.snapshotHistory.set([]); this.snapshotHistoryError.set('');
      this.selectedModel.set(''); this.afterId.set(0); this.throughId.set(0);
      this.error.set(''); this.message.set(''); this.messageDraft.set(null); this.busy.set(false);
      if (Number.isSafeInteger(this.organizationId) && this.organizationId > 0) void this.load();
      else { this.loading.set(false); this.error.set("Select a current organization."); }
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
    this.loading.set(true); this.error.set(''); this.models.set([]); this.projects.set([]);
    try {
      const response = await this.api.organizationExportInventory(this.organizationId);
      if (generation !== this.generation) return;
      const customer = response.body['customer'];
      const artifacts = response.body['artifact_counts'] as Record<string, unknown> | undefined;
      if (response.status !== 200 || response.body['organization_id'] !== this.organizationId
          || response.body['scope'] !== 'record_counts_only_not_a_complete_export_or_deletion_receipt'
          || !Array.isArray(customer) || !customer.every(isModelCount)
          || !Array.isArray(artifacts?.['projects']) || !artifacts['projects'].every(isStorageCount)) throw new Error();
      this.models.set(customer as ModelCount[]);
      this.projects.set(artifacts['projects'] as StorageCount[]);
      void this.loadSnapshotHistory(generation);
    } catch {
      if (generation === this.generation) this.error.set("Organization export inventory is unavailable or permission was revoked.");
    } finally { if (generation === this.generation) this.loading.set(false); }
  }

  chooseModel(event: Event) {
    const selected = (event.target as HTMLSelectElement).value;
    const entry = this.models().find((item) => item.model === selected);
    this.selectedModel.set(entry?.model || '');
    this.throughId.set(entry?.latest_id ?? 0);
    this.afterId.set(0); this.message.set('');
  }

  selectArtifact(project: StorageCount, event: Event) {
    const index = Number((event.target as HTMLInputElement).value);
    this.artifactIndices.update((existing) => ({ ...existing,
      [project.project_id]: Number.isSafeInteger(index) && index >= 0 && index < project.visible_count ? index : 0 }));
  }

  artifactUrl(project: StorageCount) {
    return `${environment.apiBase}/organizations/${this.organizationId}/export/projects/${project.project_id}/artifacts/${this.artifactIndices()[project.project_id] || 0}/`;
  }

  async downloadArchive() {
    if (this.busy()) return;
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.boundedOrganizationArchive(this.organizationId);
      if (generation !== this.generation) return;
      if (response.status !== 200 || response.type !== 'application/zip'
          || !response.blob || !response.blob.size || response.blob.size > 32 * 1024 * 1024
          || !response.digest || !/^[0-9a-f]{64}$/.test(response.digest)) throw new Error();
      const url = URL.createObjectURL(response.blob);
      const link = document.createElement('a');
      link.href = url; link.download = `organization-${this.organizationId}-customer-content.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      this.setDraftMessage(`Private customer-content ZIP downloaded (SHA-256 ${response.digest}). Restricted billing/account data and backups are separate.`,
        `Özel müşteri içeriği ZIP’i indirildi (SHA-256 ${response.digest}). Kısıtlı faturalama/hesap verileri ve yedekler ayrıdır.`);
    } catch {
      if (generation === this.generation) this.message.set("Complete bounded archive unavailable. Review current inventory and export permitted parts separately.");
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async captureSnapshot(format = 'bounded-zip-v1') {
    if (this.busy() || !['bounded-zip-v1', 'source-parts-v2', 'coherent-parts-v3'].includes(format)) return;
    const generation = this.generation;
    this.busy.set(true); this.message.set(''); this.manifestGeneration++; this.snapshotParts.set([]);
    try {
      const created = await this.api.captureOrganizationSnapshot(this.organizationId, format);
      if (generation !== this.generation) return;
      const id = created.body['snapshot_id'];
      if ((created.status !== 202 && created.status !== 200) || !Number.isSafeInteger(id) || Number(id) <= 0
          || created.body['organization_id'] !== this.organizationId
          || created.body['format'] !== format
          || typeof created.body['state'] !== 'string' || !['ready', 'preparing'].includes(created.body['state'])
          || created.body['scope'] !== (format === 'source-parts-v2'
            ? 'sequential_source_parts_not_transactional' : format === 'coherent-parts-v3'
            ? 'coherent_customer_content_only' : 'bounded_customer_content_only')) throw new Error();
      await this.loadSnapshotHistory(generation);
      if (created.body['state'] === 'ready') await this.loadSnapshot(Number(id), generation);
      if (generation === this.generation) this.message.set(created.body['state'] === 'ready'
        ? "Private copy is ready. Download every manifest page and listed part before closing access."
        : "Private capture is preparing. Refresh to check status; do not create another request while its outcome is unknown.");
    } catch {
      if (generation === this.generation) this.message.set("Private snapshot unavailable; check recent captures before trying again.");
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async loadSnapshotHistory(generation = this.generation) {
    if (generation !== this.generation) return;
    const historyGeneration = ++this.historyGeneration;
    this.manifestGeneration++; this.snapshotParts.set([]);
    this.snapshotHistory.set([]); this.snapshotHistoryError.set('');
    try {
      const result = await this.api.organizationSnapshots(this.organizationId);
      if (generation !== this.generation || historyGeneration !== this.historyGeneration) return;
      const rows = result.body['snapshots'];
      if (result.status !== 200 || result.body['organization_id'] !== this.organizationId
          || result.body['scope'] !== 'bounded_capture_history_not_complete_export'
          || !Array.isArray(rows) || rows.length > 3 || !rows.every((row: unknown) => isSnapshotSummary(row, this.organizationId)))
        throw new Error();
      this.snapshotHistory.set(rows as SnapshotSummary[]); this.snapshotHistoryError.set('');
    } catch {
      if (generation === this.generation && historyGeneration === this.historyGeneration)
        this.snapshotHistoryError.set("Previous private captures are unavailable.");
    }
  }

  manifestUrl() {
    return `${environment.apiBase}/organizations/${this.organizationId}/export/snapshots/${this.snapshotId()}/?position=${this.snapshotPosition()}`;
  }

  async loadSnapshot(id: number, generation = this.generation, position = 0) {
    if (generation !== this.generation || !Number.isSafeInteger(id) || id <= 0
        || !Number.isSafeInteger(position) || position < 0) return;
    const manifestGeneration = ++this.manifestGeneration;
    this.snapshotParts.set([]); this.message.set('');
    try {
      const result = await this.api.organizationSnapshotManifest(this.organizationId, id, position);
      if (generation !== this.generation || manifestGeneration !== this.manifestGeneration) return;
      const body = result.body;
      const parts = body['parts'];
      const sourceParts = body['version'] === 'source-parts-v2';
      const coherentParts = body['version'] === 'coherent-parts-v3';
      const paged = sourceParts || coherentParts;
      const window = body['capture_window'] as Record<string, unknown> | undefined;
      if (result.status !== 200 || body['organization_id'] !== this.organizationId || body['snapshot_id'] !== id
          || (!paged && body['version'] !== 'bounded-organization-snapshot-v1')
          || body['scope'] !== (sourceParts ? 'sequential_source_parts_not_transactional'
            : coherentParts ? 'coherent_customer_content_only' : 'captured_bounded_customer_content_not_legal_or_backup_export')
          || (coherentParts && (body['consistency'] !== 'one_live_database_snapshot_and_admitted_visible_objects_not_legal_or_backup_export'
            || !window || typeof window['started_at'] !== 'string' || typeof window['completed_at'] !== 'string'
            || !Number.isFinite(Date.parse(window['started_at'])) || !Number.isFinite(Date.parse(window['completed_at']))
            || Date.parse(window['started_at']) > Date.parse(window['completed_at'])))
          || !Number.isSafeInteger(body['size_bytes']) || Number(body['size_bytes']) < 1
          || (!paged && Number(body['size_bytes']) > 32 * 1024 * 1024)
          || typeof body['sha256'] !== 'string' || !/^[0-9a-f]{64}$/.test(body['sha256'])
          || !Array.isArray(parts) || !parts.length || !parts.every((part: unknown, index: number) =>
            isSnapshotPart(part, this.organizationId, Number(id), (paged ? position : 0) + index))
          || (!paged && parts.reduce((total: number, part: SnapshotPart) => total + part.size_bytes, 0) !== body['size_bytes'])
          || (paged && (parts.length > 50 || !Number.isSafeInteger(body['part_count'])
            || Number(body['part_count']) < position + parts.length
            || body['integrity'] !== 'sha256_chain_of_canonical_part_descriptors_from_32_zero_bytes'
            || body['next_position'] !== (Number(body['part_count']) > position + parts.length ? position + parts.length : null))))
        throw new Error();
      this.snapshotId.set(Number(id)); this.snapshotBytes.set(Number(body['size_bytes']));
      this.snapshotDigest.set(body['sha256'] as string); this.snapshotParts.set(parts as SnapshotPart[]);
      this.snapshotFormat.set(coherentParts ? 'coherent-parts-v3' : sourceParts ? 'source-parts-v2' : 'bounded-zip-v1');
      this.snapshotPosition.set(paged ? position : 0); this.snapshotPartCount.set(Number(body['part_count'] ?? parts.length));
      this.snapshotNextPosition.set(paged ? body['next_position'] as number | null : null);
      this.message.set(coherentParts
        ? "Private coherent customer-content parts are ready. Download each manifest page and independent ZIP; restricted records and backups are excluded."
        : "Private captured parts are ready. Source observations are sequential, not a transactional snapshot.");
    } catch {
      if (generation === this.generation && manifestGeneration === this.manifestGeneration)
        this.message.set("Private snapshot parts are unavailable or permission was revoked.");
    }
  }

  async discardFailedSnapshot(id: number) {
    if (this.busy() || !this.snapshotHistory().some((item) => item.id === id && item.state === 'failed')) return;
    const generation = this.generation;
    this.busy.set(true); this.message.set('');
    try {
      const result = await this.api.discardFailedOrganizationSnapshot(this.organizationId, id);
      if (generation !== this.generation) return;
      if ((result.status !== 200 && result.status !== 202) || result.body['organization_id'] !== this.organizationId
          || result.body['snapshot_id'] !== id || (result.body['state'] !== 'discarded'
          && result.body['state'] !== 'cleanup_pending')) throw new Error();
      await this.loadSnapshotHistory(generation);
      if (generation === this.generation) this.message.set(result.body['state'] === 'discarded'
        ? "Failed private capture removed; its slot is available again."
        : "Private cleanup is still in progress. Retry this same failed capture until it is removed.");
    } catch {
      if (generation === this.generation) this.message.set("Failed capture cleanup is unavailable; inspect the current status before retrying.");
    } finally { if (generation === this.generation) this.busy.set(false); }
  }

  async downloadRows() {
    const entry = this.models().find((item) => item.model === this.selectedModel());
    if (this.busy() || !entry?.latest_id || this.afterId() >= this.throughId()) return;
    const generation = this.generation;
    const after = this.afterId();
    this.busy.set(true); this.message.set('');
    try {
      const response = await this.api.organizationCustomerRows(this.organizationId, entry.model, after, this.throughId());
      if (generation !== this.generation || entry.model !== this.selectedModel()) return;
      const body = response.body;
      const next = body['next_after_id'];
      if (response.status !== 200 || body['organization_id'] !== this.organizationId
          || body['model'] !== entry.model || body['through_id'] !== this.throughId()
          || body['scope'] !== 'one_model_page_not_a_complete_organization_export'
          || !Array.isArray(body['rows']) || !body['rows'].length || body['rows'].length > 50
          || !Number.isSafeInteger(next) || Number(next) <= after || Number(next) > this.throughId()
          || typeof body['has_more'] !== 'boolean') throw new Error();
      const file = new Blob([JSON.stringify(body)], { type: 'application/json' });
      const url = URL.createObjectURL(file);
      const link = document.createElement('a');
      link.href = url;
      link.download = `organization-${this.organizationId}-${entry.model.replaceAll('.', '-')}-${after + 1}-${next}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      this.afterId.set(Number(next));
      this.message.set(body['has_more'] ? "Page downloaded. Continue until this model window is exhausted."
        : "This selected model window ended. Other models and private artifacts must be exported separately.");
    } catch {
      if (generation === this.generation) this.message.set("Record download unavailable; refresh the inventory and verify current permission.");
    } finally { if (generation === this.generation) this.busy.set(false); }
  }
}

function isModelCount(value: unknown): value is ModelCount {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return typeof row['model'] === 'string' && /^[a-zA-Z]+\.[a-zA-Z]+$/.test(row['model'])
    && Number.isSafeInteger(row['count']) && Number(row['count']) >= 0
    && (row['latest_id'] === null || Number.isSafeInteger(row['latest_id']) && Number(row['latest_id']) > 0);
}

function isStorageCount(value: unknown): value is StorageCount {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['project_id']) && Number(row['project_id']) > 0
    && Number.isSafeInteger(row['visible_count']) && Number(row['visible_count']) >= 0;
}

function isSnapshotPart(value: unknown, organizationId: number, snapshotId: number, position: number): value is SnapshotPart {
  if (!value || typeof value !== 'object') return false;
  const part = value as Record<string, unknown>;
  return part['position'] === position && Number.isSafeInteger(part['size_bytes'])
    && Number(part['size_bytes']) > 0 && Number(part['size_bytes']) <= 8 * 1024 * 1024
    && typeof part['sha256'] === 'string' && /^[0-9a-f]{64}$/.test(part['sha256'])
    && part['download_path'] === `/api/organizations/${organizationId}/export/snapshots/${snapshotId}/parts/${position}/`;
}

function isSnapshotSummary(value: unknown, organizationId: number): value is SnapshotSummary {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && typeof row['state'] === 'string' && ['ready', 'preparing', 'failed', 'expired'].includes(row['state'])
    && (row['expires_at'] === undefined || row['expires_at'] === null
      || typeof row['expires_at'] === 'string' && Number.isFinite(Date.parse(row['expires_at'])))
    && (row['state'] !== 'expired' || typeof row['expires_at'] === 'string')
    && typeof row['created_at'] === 'string' && !Number.isNaN(Date.parse(row['created_at']))
    && (row['state'] === 'ready'
      ? row['manifest_path'] === `/api/organizations/${organizationId}/export/snapshots/${row['id']}/`
      : row['manifest_path'] === null);
}
