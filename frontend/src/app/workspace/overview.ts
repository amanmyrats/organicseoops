import { Title } from '@angular/platform-browser';
import { Component, DestroyRef, effect, ElementRef, OnInit, computed, signal, ViewChild } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { AccountApi, ApiResult, InvitationInfo, OrganizationInfo, OwnershipTransferInfo, ProjectInfo, TeamMemberInfo, TrialInfo } from '../account/account-api';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { environment } from '../../environments/environment';

const overviewTurkish: Record<string, string> = {
  "Authenticated workspace": "Kimliği doğrulanmış çalışma alanı",
  "Organization and project context": "Kuruluş ve proje bağlamı",
  "Active context": "Etkin bağlam",
  "Organization:": "Kuruluş:",
  "Project:": "Proje:",
  "Loading organizations.": "Kuruluşlar yükleniyor.",
  "Organization context could not be loaded. Your access has not been changed.": "Kuruluş bağlamı yüklenemedi. Erişiminiz değiştirilmedi.",
  "Retry organizations": "Kuruluşları yeniden yükleyin",
  "Create your organization": "Kuruluşunuzu oluşturun",
  "Name the workspace you own. An eligible first organization records a 30-day no-card trial; later organizations require staff review.": "Sahip olduğunuz çalışma alanını adlandırın. Uygun ilk kuruluş, kart gerektirmeyen 30 günlük deneme kaydı oluşturur; sonraki kuruluşlar personel incelemesi gerektirir.",
  "Organization name": "Kuruluş adı",
  "Create organization": "Kuruluş oluşturun",
  "Organization": "Kuruluş",
  "Project": "Proje",
  "No accessible projects": "Erişilebilir proje yok",
  "Review organization billing and hosted checkout": "Kuruluş faturalandırmasını ve barındırılan ödeme akışını inceleyin",
  "Inspect owner-only customer-data export parts and retention status": "Yalnızca sahibin erişebildiği müşteri verisi dışa aktarım parçalarını ve saklama durumunu inceleyin",
  "Inspect closure and retention progress": "Kapanma ve saklama ilerlemesini inceleyin",
  "Trial status": "Deneme durumu",
  "Active.": "Etkin.",
  "The trial ends": "Deneme bitişi:",
  "in your local time.": "yerel saatinize göre.",
  "Eligibility review required.": "Uygunluk incelemesi gerekli.",
  "The trial clock has not started.": "Deneme süresi başlamadı.",
  "Expired.": "Süresi doldu.",
  "New billable work is paused. Stored project results and private report exports remain readable under current project permissions while retained; complete organization export and hosted timed deletion are not yet verified.": "Yeni ücretlendirilebilir işler duraklatıldı. Saklanan proje sonuçları ve özel rapor dışa aktarımları, saklandıkları sürece güncel proje izinleri kapsamında okunabilir; kuruluşun eksiksiz dışa aktarımı ve barındırılan zamanlı silme henüz doğrulanmadı.",
  "Expired and suspended.": "Süresi doldu ve askıya alındı.",
  "The trial ended and organization access is also suspended.": "Deneme sona erdi ve kuruluş erişimi de askıya alındı.",
  "Suspended.": "Askıya alındı.",
  "Trial access is unavailable while the organization is suspended.": "Kuruluş askıya alınmışken deneme erişimi kullanılamaz.",
  "Recorded policy values:": "Kaydedilen politika değerleri:",
  "project,": "proje,",
  "members and": "üye ve",
  "internal units across this trial.": "bu deneme boyunca dahili birim.",
  "Recorded usage:": "Kaydedilen kullanım:",
  "settled internal units and": "kesinleşmiş dahili birim ve",
  "currently reserved.": "şu anda ayrılmış birim.",
  "Recorded usage is not a live remaining-unit balance. New work rechecks effective trial or paid capacity on the server.": "Kaydedilen kullanım, canlı kalan birim bakiyesi değildir. Yeni işler, geçerli deneme veya ücretli kapasiteyi sunucuda yeniden kontrol eder.",
  "Unavailable.": "Kullanılamıyor.",
  "Trial status could not be loaded for this organization.": "Bu kuruluş için deneme durumu yüklenemedi.",
  "Local implementation only: project reports and owner-only export parts are fixture-checked; complete organization export, hosted deletion and real provider acceptance remain unavailable.": "Yalnızca yerel uygulama: proje raporları ve yalnızca sahibin erişebildiği dışa aktarım parçaları test verileriyle kontrol edildi; kuruluşun eksiksiz dışa aktarımı, barındırılan silme ve gerçek sağlayıcı kabulü henüz mevcut değil.",
  "This organization is suspended. Project and team operations are unavailable. Contact support to resolve the hold.": "Bu kuruluş askıya alındı. Proje ve ekip işlemleri kullanılamıyor. Kısıtlamayı çözmek için destekle iletişime geçin.",
  "Ownership transfer pending": "Sahiplik devri bekleniyor",
  "proposed transferring ownership to": "sahipliği şu kişiye devretmeyi önerdi:",
  "Re-enter your password to accept ownership": "Sahipliği kabul etmek için parolanızı yeniden girin",
  "Accept ownership": "Sahipliği kabul edin",
  "Re-enter your password to": "Parolanızı yeniden girin; işlem:",
  "the transfer": "sahiplik devri",
  "Transfer ownership": "Sahipliği devredin",
  "The selected member must explicitly accept. You will become an admin after acceptance.": "Seçilen üye açıkça kabul etmelidir. Kabulden sonra yönetici olacaksınız.",
  "Existing member": "Mevcut üye",
  "Select a verified member": "Doğrulanmış bir üye seçin",
  "Re-enter your password": "Parolanızı yeniden girin",
  "Propose transfer": "Devir önerin",
  "Leave organization": "Kuruluştan ayrılın",
  "Leaving removes only your access to this organization. A last active owner must transfer ownership or close the organization first.": "Ayrılmak yalnızca bu kuruluşa erişiminizi kaldırır. Son etkin sahip önce sahipliği devretmeli veya kuruluşu kapatmalıdır.",
  "Loading projects. Previous project context has been cleared.": "Projeler yükleniyor. Önceki proje bağlamı temizlendi.",
  "Retry projects": "Projeleri yeniden yükleyin",
  "No accessible projects are available in this organization.": "Bu kuruluşta erişilebilir proje yok.",
  "Canonical origin:": "Kanonik köken:",
  "Access:": "Erişim:",
  "Review source evidence and next human actions": "Kaynak kanıtlarını ve sonraki insan eylemlerini inceleyin",
  "Project onboarding and configuration": "Proje başlangıç kurulumu ve yapılandırması",
  "Select model and run a bounded AI text job": "Model seçin ve sınırlı bir yapay zekâ metin işi çalıştırın",
  "Diagnostic job progress (local development)": "Tanılama işi ilerlemesi (yerel geliştirme)",
  "Team and project access": "Ekip ve proje erişimi",
  "Organization AI provider credentials": "Kuruluş yapay zekâ sağlayıcı kimlik bilgileri",
  "Loading team access.": "Ekip erişimi yükleniyor.",
  "Retry team access": "Ekip erişimini yeniden yükleyin",
  "Role": "Rol",
  "Restricted project access": "Kısıtlı proje erişimi",
  "No accessible projects to assign.": "Atanabilecek erişilebilir proje yok.",
  "Save access": "Erişimi kaydedin",
  "Pending invitations": "Bekleyen davetler",
  "No pending invitations.": "Bekleyen davet yok.",
  "· expires": "· sona erme",
  "Invite a team member": "Ekip üyesi davet edin",
  "Verified email address": "Doğrulanmış e-posta adresi",
  "Send invitation": "Davet gönderin",
  "Organization settings": "Kuruluş ayarları",
  "Save organization": "Kuruluşu kaydedin",
  "Add project": "Proje ekleyin",
  "Enter one canonical HTTP or HTTPS origin. Aliases stay explicit and do not widen crawl scope.": "Tek bir kanonik HTTP veya HTTPS kökeni girin. Takma adlar açıkça belirtilir ve tarama kapsamını genişletmez.",
  "Project name": "Proje adı",
  "Canonical origin": "Kanonik köken",
  "Aliases": "Takma adlar",
  "One origin per line": "Her satıra bir köken",
  "Restrict access to assigned members": "Erişimi atanmış üyelerle sınırlandırın",
  "Create project": "Proje oluşturun",
  "Project settings": "Proje ayarları",
  "Save project": "Projeyi kaydedin",
  "Security and sessions": "Güvenlik ve oturumlar",
  "Preview home": "Önizleme ana sayfası",
  "none selected": "seçilmedi",
  "cancel": "iptal etme",
  "decline": "reddetme",
  "Cancel transfer": "Devri iptal edin",
  "Decline transfer": "Devri reddedin",
  "Confirm leave organization": "Kuruluştan ayrılmayı onaylayın",
  "Restricted to assigned members": "Atanmış üyelerle sınırlı",
  "All organization members": "Tüm kuruluş üyeleri",
  "Confirm remove member": "Üyeyi kaldırmayı onaylayın",
  "Remove member": "Üyeyi kaldırın",
  "Confirm reissue (old link stops working)": "Yeniden göndermeyi onaylayın (eski bağlantı çalışmaz)",
  "Reissue invitation": "Daveti yeniden gönderin",
  "Confirm revoke invitation": "Daveti iptal etmeyi onaylayın",
  "Revoke invitation": "Daveti iptal edin",
  "Working…": "İşleniyor…",
  "Sign out": "Oturumu kapatın",
  "Personal and preview links": "Kişisel ve önizleme bağlantıları",
  "Organizations are temporarily unavailable. Try again.": "Kuruluşlar geçici olarak kullanılamıyor. Tekrar deneyin.",
  "after eligibility approval": "uygunluk onayından sonra",
  "Organization created with a 30-day trial record.": "Kuruluş, 30 günlük deneme kaydıyla oluşturuldu.",
  "Organization created. Trial eligibility requires staff review.": "Kuruluş oluşturuldu. Deneme uygunluğu personel incelemesi gerektirir.",
  "Organization creation failed. Check the name and verified account status.": "Kuruluş oluşturulamadı. Adı ve doğrulanmış hesap durumunu kontrol edin.",
  "Organization creation is temporarily unavailable. Try again.": "Kuruluş oluşturma geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Organization settings saved.": "Kuruluş ayarları kaydedildi.",
  "Only an organization owner can change these settings.": "Bu ayarları yalnızca kuruluş sahibi değiştirebilir.",
  "Organization settings could not be saved.": "Kuruluş ayarları kaydedilemedi.",
  "Organization settings are temporarily unavailable. Try again.": "Kuruluş ayarları geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Project created. Aliases remain explicit configuration only.": "Proje oluşturuldu. Takma adlar yalnızca açık yapılandırma olarak kalır.",
  "Project creation failed. Check the origin and aliases.": "Proje oluşturulamadı. Kökeni ve takma adları kontrol edin.",
  "Project creation is temporarily unavailable. Try again.": "Proje oluşturma geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Project settings saved.": "Proje ayarları kaydedildi.",
  "Project settings could not be saved.": "Proje ayarları kaydedilemedi.",
  "Project settings are temporarily unavailable. Try again.": "Proje ayarları geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Invitation saved, but delivery failed. Reissue it from pending invitations to try again.": "Davet kaydedildi, ancak teslimat başarısız oldu. Tekrar denemek için bekleyen davetlerden yeniden gönderin.",
  "Invitation sent. It expires in seven days and does not create a trial.": "Davet gönderildi. Yedi gün sonra sona erer ve deneme oluşturmaz.",
  "Invitation could not be created. Check the email, role, and existing invitations.": "Davet oluşturulamadı. E-postayı, rolü ve mevcut davetleri kontrol edin.",
  "Invitations are temporarily unavailable. Try again.": "Davetler geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Team access saved.": "Ekip erişimi kaydedildi.",
  "Team access could not be saved.": "Ekip erişimi kaydedilemedi.",
  "Team access is temporarily unavailable. Try again.": "Ekip erişimi geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Member access removed. Their account and other organizations were not changed.": "Üyenin erişimi kaldırıldı. Hesabı ve diğer kuruluşları değiştirilmedi.",
  "Member access could not be removed.": "Üyenin erişimi kaldırılamadı.",
  "Member access is temporarily unavailable. Try again.": "Üye erişimi geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Invitation revoked.": "Davet iptal edildi.",
  "Invitation could not be revoked.": "Davet iptal edilemedi.",
  "New invitation saved but delivery failed. You can reissue it again.": "Yeni davet kaydedildi, ancak teslimat başarısız oldu. Yeniden gönderebilirsiniz.",
  "New invitation sent. The old link no longer works.": "Yeni davet gönderildi. Eski bağlantı artık çalışmaz.",
  "Invitation could not be reissued. Check its status and team access.": "Davet yeniden gönderilemedi. Durumunu ve ekip erişimini kontrol edin.",
  "Reauthentication failed. Check your password and try again.": "Yeniden kimlik doğrulama başarısız oldu. Parolanızı kontrol edip tekrar deneyin.",
  "Transfer proposed. The member must sign in and accept it.": "Devir önerildi. Üye oturum açıp kabul etmelidir.",
  "Transfer could not be proposed. Select an active verified member or resolve a pending transfer.": "Devir önerilemedi. Etkin ve doğrulanmış bir üye seçin veya bekleyen devri çözün.",
  "Transfer is temporarily unavailable. Try again.": "Devir geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Ownership accepted. Your role is now owner.": "Sahiplik kabul edildi. Rolünüz artık sahip.",
  "Ownership could not be accepted. Ask the owner to review the transfer.": "Sahiplik kabul edilemedi. Sahibinden devri incelemesini isteyin.",
  "Ownership transfer cancelled. No roles changed.": "Sahiplik devri iptal edildi. Hiçbir rol değiştirilmedi.",
  "Ownership transfer could not be cancelled. Refresh and try again.": "Sahiplik devri iptal edilemedi. Yenileyip tekrar deneyin.",
  "Ownership transfer is temporarily unavailable. Try again.": "Sahiplik devri geçici olarak kullanılamıyor. Tekrar deneyin.",
  "You left the organization. Your account and other organizations remain available.": "Kuruluştan ayrıldınız. Hesabınız ve diğer kuruluşlarınız erişilebilir durumda.",
  "Transfer ownership or close the organization before leaving.": "Ayrılmadan önce sahipliği devredin veya kuruluşu kapatın.",
  "You could not leave the organization. Try again.": "Kuruluştan ayrılamadınız. Tekrar deneyin.",
  "Leaving is temporarily unavailable. Try again.": "Ayrılma geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Sign out failed. Your session may still be active. Try again.": "Oturum kapatılamadı. Oturumunuz hâlâ etkin olabilir. Tekrar deneyin.",
  "Projects are temporarily unavailable. Try again.": "Projeler geçici olarak kullanılamıyor. Tekrar deneyin.",
  "Ownership status could not be loaded. Retry the organization context before changing ownership.": "Sahiplik durumu yüklenemedi. Sahipliği değiştirmeden önce kuruluş bağlamını yeniden yükleyin.",
  "Your organization access changed. The active context was refreshed.": "Kuruluş erişiminiz değişti. Etkin bağlam yenilendi.",
  "Unreviewed Turkish workspace interface draft in local development. Organization and project names retain their original language; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe çalışma alanı arayüzü taslağı. Kuruluş ve proje adları özgün dillerini korur; iki dilli onay bekleniyor."
};

@Component({
  selector: 'app-overview',
  imports: [RouterLink],
  template: `
    <section [attr.lang]="uiLanguage()" class="workspace-shell" aria-labelledby="workspace-title">
      <p class="eyebrow">{{ t("Authenticated workspace") }}</p>
      <h1 id="workspace-title">{{ t("Organization and project context") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish workspace interface draft in local development. Organization and project names retain their original language; bilingual approval is pending.") }}</p> }

      <div class="scope-summary" aria-live="polite">
        <strong>{{ t("Active context") }}</strong>
        <span>{{ t("Organization:") }} <span [attr.lang]="activeOrganization()?.name ? '' : uiLanguage()">{{ activeOrganization()?.name || t("none selected") }}</span></span>
        <span>{{ t("Project:") }} <span [attr.lang]="activeProject()?.name ? '' : uiLanguage()">{{ activeProject()?.name || t("none selected") }}</span></span>
      </div>

      @if (message()) { <p class="form-status" role="status">{{ t(message()) }}</p> }
      @if (error()) { <p #errorSummary class="form-status error" role="alert" tabindex="-1">{{ t(error()) }}</p> }

      @if (loadingOrganizations()) {
        <p role="status">{{ t("Loading organizations.") }}</p>
      } @else if (organizationLoadFailed()) {
        <p role="status">{{ t("Organization context could not be loaded. Your access has not been changed.") }}</p>
        <button type="button" class="retry-organizations" (click)="retryOrganizations()">{{ t("Retry organizations") }}</button>
      } @else if (!organizations().length) {
        <section class="workspace-panel" aria-labelledby="first-organization-title">
          <h2 id="first-organization-title">{{ t("Create your organization") }}</h2>
          <p>{{ t("Name the workspace you own. An eligible first organization records a 30-day no-card trial; later organizations require staff review.") }}</p>
          <form (submit)="createOrganization($event)">
            <label for="new-organization-name">{{ t("Organization name") }}</label>
            <input lang="" id="new-organization-name" name="name" required maxlength="160" />
            <button type="submit" [disabled]="submitting()">{{ t("Create organization") }}</button>
          </form>
        </section>
      } @else {
        <div class="scope-selectors">
          <div>
            <label for="organization-selector">{{ t("Organization") }}</label>
            <select id="organization-selector" (change)="selectOrganization($event)" [disabled]="submitting()">
              @for (organization of organizations(); track organization.id) {
                <option lang="" [value]="organization.id" [selected]="organization.id === activeOrganization()?.id">
                  {{ organization.name }} ({{ organization.role }})
                </option>
              }
            </select>
          </div>
          <div>
            <label for="project-selector">{{ t("Project") }}</label>
            <select id="project-selector" (change)="selectProject($event)"
              [disabled]="loadingProjects() || !projects().length || submitting()">
              @if (!projects().length) { <option value="">{{ t("No accessible projects") }}</option> }
              @for (project of projects(); track project.id) {
                <option lang="" [value]="project.id" [selected]="project.id === activeProject()?.id">{{ project.name }}</option>
              }
            </select>
          </div>
        </div>

        @if (activeOrganization()?.role === 'owner') {
          <p><a [routerLink]="['/app/billing', activeOrganization()!.id]">{{ t("Review organization billing and hosted checkout") }}</a></p>
          <p><a [routerLink]="['/app/export', activeOrganization()!.id]">{{ t("Inspect owner-only customer-data export parts and retention status") }}</a></p>
          <p><a [routerLink]="['/app/closure-status', activeOrganization()!.id]">{{ t("Inspect closure and retention progress") }}</a></p>
          <section class="workspace-panel" aria-labelledby="trial-status-title">
            <h2 id="trial-status-title">{{ t("Trial status") }}</h2>
            @if (activeOrganization()?.trial; as trial) {
              @if (trial.access_state === 'active') {
                <p><strong>{{ t("Active.") }}</strong> {{ t("The trial ends") }}
                  <time [attr.datetime]="trial.ends_at"><span [attr.lang]="trial.ends_at ? 'en' : uiLanguage()">{{ t(trialEndLabel(trial)) }}</span></time> {{ t("in your local time.") }}</p>
              } @else if (trial.access_state === 'pending_review') {
                <p><strong>{{ t("Eligibility review required.") }}</strong> {{ t("The trial clock has not started.") }}</p>
              } @else if (trial.access_state === 'read_only') {
                <p><strong>{{ t("Expired.") }}</strong> {{ t("New billable work is paused. Stored project results and private report exports remain readable under current project permissions while retained; complete organization export and hosted timed deletion are not yet verified.") }}</p>
              } @else if (trial.state === 'expired') {
                <p><strong>{{ t("Expired and suspended.") }}</strong> {{ t("The trial ended and organization access is also suspended.") }}</p>
              } @else {
                <p><strong>{{ t("Suspended.") }}</strong> {{ t("Trial access is unavailable while the organization is suspended.") }}</p>
              }
              <p>{{ t("Recorded policy values:") }} <span lang="en">{{ trial.project_limit }}</span> {{ t("project,") }} <span lang="en">{{ trial.member_limit }}</span> {{ t("members and") }}
                <span lang="en">{{ trial.unit_limit }}</span> {{ t("internal units across this trial.") }}</p>
              <p>{{ t("Recorded usage:") }} <span lang="en">{{ trial.settled_units }}</span> {{ t("settled internal units and") }}
                <span lang="en">{{ trial.reserved_units }}</span> {{ t("currently reserved.") }}</p>
              <p>{{ t("Recorded usage is not a live remaining-unit balance. New work rechecks effective trial or paid capacity on the server.") }}</p>
            } @else {
              <p><strong>{{ t("Unavailable.") }}</strong> {{ t("Trial status could not be loaded for this organization.") }}</p>
            }
            @if (!environment.production) {
              <p>{{ t("Local implementation only: project reports and owner-only export parts are fixture-checked; complete organization export, hosted deletion and real provider acceptance remain unavailable.") }}</p>
            }
          </section>
        }

        @if (activeOrganization()?.is_suspended) {
          <p class="form-status" role="status">{{ t("This organization is suspended. Project and team operations are unavailable. Contact support to resolve the hold.") }}</p>
        } @else {
          @if (pendingTransfer(); as transfer) {
            <section class="workspace-panel" aria-labelledby="ownership-title">
              <h2 id="ownership-title">{{ t("Ownership transfer pending") }}</h2>
              <p><span lang="">{{ transfer.from_email }}</span> {{ t("proposed transferring ownership to") }} <span lang="">{{ transfer.to_email }}</span>.</p>
              @if (activeOrganization()?.role !== 'owner') {
                <form (submit)="acceptTransfer($event, transfer)">
                  <label for="accept-transfer-password">{{ t("Re-enter your password to accept ownership") }}</label>
                  <input id="accept-transfer-password" name="password" type="password" autocomplete="current-password" required />
                  <button type="submit" [disabled]="submitting()">{{ t("Accept ownership") }}</button>
                </form>
              }
              <form (submit)="cancelTransfer($event, transfer)">
                <label for="cancel-transfer-password">{{ t("Re-enter your password to") }} {{ activeOrganization()?.role === 'owner' ? t("cancel") : t("decline") }} {{ t("the transfer") }}</label>
                <input id="cancel-transfer-password" name="password" type="password" autocomplete="current-password" required />
                <button type="submit" class="danger-button" [disabled]="submitting()">
                  {{ activeOrganization()?.role === 'owner' ? t("Cancel transfer") : t("Decline transfer") }}
                </button>
              </form>
            </section>
          }
          @if (activeOrganization()?.role === 'owner' && !pendingTransfer()) {
            <section class="workspace-panel" aria-labelledby="transfer-title">
              <h2 id="transfer-title">{{ t("Transfer ownership") }}</h2>
              <p>{{ t("The selected member must explicitly accept. You will become an admin after acceptance.") }}</p>
              <form (submit)="proposeTransfer($event)">
                <label for="transfer-member">{{ t("Existing member") }}</label>
                <select id="transfer-member" name="member" required>
                  <option value="">{{ t("Select a verified member") }}</option>
                  @for (member of members(); track member.id) {
                    @if (member.role !== 'owner') { <option lang="" [value]="member.id">{{ member.email }}</option> }
                  }
                </select>
                <label for="transfer-password">{{ t("Re-enter your password") }}</label>
                <input id="transfer-password" name="password" type="password" autocomplete="current-password" required />
                <button type="submit" [disabled]="submitting() || loadingTeam() || teamLoadFailed()">{{ t("Propose transfer") }}</button>
              </form>
            </section>
          }
          <section class="workspace-panel" aria-labelledby="leave-title">
            <h2 id="leave-title">{{ t("Leave organization") }}</h2>
            <p>{{ t("Leaving removes only your access to this organization. A last active owner must transfer ownership or close the organization first.") }}</p>
            <form (submit)="leave($event)">
              <label for="leave-password">{{ t("Re-enter your password") }}</label>
              <input id="leave-password" name="password" type="password" autocomplete="current-password" required />
              <button type="submit" class="danger-button" [disabled]="submitting()">
                {{ pendingLeave() ? t("Confirm leave organization") : t("Leave organization") }}
              </button>
            </form>
          </section>
        }

        @if (loadingProjects()) {
          <p role="status">{{ t("Loading projects. Previous project context has been cleared.") }}</p>
        } @else if (projectLoadFailed()) {
          <button type="button" class="retry-projects" (click)="retryProjects()">{{ t("Retry projects") }}</button>
        } @else if (!projects().length) {
          <p class="form-status">{{ t("No accessible projects are available in this organization.") }}</p>
        } @else if (activeProject()) {
          <div class="project-context">
            <p><strong>{{ t("Canonical origin:") }}</strong> <span lang="en">{{ activeProject()!.canonical_origin }}</span></p>
            <p><strong>{{ t("Access:") }}</strong> {{ activeProject()!.access_restricted ? t("Restricted to assigned members") : t("All organization members") }}</p>
            <a [routerLink]="['/app/dashboard', activeOrganization()!.id, activeProject()!.id]">{{ t("Review source evidence and next human actions") }}</a>
            <a [routerLink]="['/app/onboarding', activeOrganization()!.id, activeProject()!.id]">{{ t("Project onboarding and configuration") }}</a>
            <a [routerLink]="['/app/ai-text', activeOrganization()!.id, activeProject()!.id]">{{ t("Select model and run a bounded AI text job") }}</a>
            @if (!environment.production) {
              <a [routerLink]="['/app/jobs', activeOrganization()!.id, activeProject()!.id]">{{ t("Diagnostic job progress (local development)") }}</a>
            }
          </div>
        }

        @if (canManageTeam()) {
          <section class="workspace-panel" aria-labelledby="team-title">
            <h2 id="team-title">{{ t("Team and project access") }}</h2>
            <p><a [routerLink]="['/app/provider-accounts', activeOrganization()!.id]">{{ t("Organization AI provider credentials") }}</a></p>
            @if (loadingTeam()) {
              <p role="status">{{ t("Loading team access.") }}</p>
            } @else if (teamLoadFailed()) {
              <button type="button" class="retry-team" (click)="retryTeam()">{{ t("Retry team access") }}</button>
            } @else {
              <ul class="team-list">
                @for (member of members(); track member.id) {
                  <li>
                    <strong><span lang="">{{ member.email }}</span></strong>
                    <span><span lang="en">{{ member.role }}</span></span>
                    @if (canEditRole(member.role)) {
                      <form (submit)="saveMember($event, member)">
                        <label [for]="'member-role-' + member.id">{{ t("Role") }}</label>
                        <select [id]="'member-role-' + member.id" name="role">
                          @for (role of manageableRoles(); track role) {
                            <option lang="en" [value]="role" [selected]="role === member.role">{{ role }}</option>
                          }
                        </select>
                        <fieldset>
                          <legend>{{ t("Restricted project access") }}</legend>
                          @if (!projects().length) { <p>{{ t("No accessible projects to assign.") }}</p> }
                          @for (project of projects(); track project.id) {
                            <label class="check-row" [for]="'member-' + member.id + '-project-' + project.id">
                              <input [id]="'member-' + member.id + '-project-' + project.id" type="checkbox"
                                [name]="'project-' + project.id" [checked]="member.project_ids.includes(project.id)" />
                              <span lang="">{{ project.name }}</span>
                            </label>
                          }
                        </fieldset>
                        <button type="submit" [disabled]="submitting()">{{ t("Save access") }}</button>
                      </form>
                      <button type="button" class="danger-button" (click)="removeMember(member)" [disabled]="submitting()">
                        {{ pendingRemoval() === member.id ? t("Confirm remove member") : t("Remove member") }}
                      </button>
                    }
                  </li>
                }
              </ul>

              <h3>{{ t("Pending invitations") }}</h3>
              @if (!invitations().length) { <p>{{ t("No pending invitations.") }}</p> }
              <ul class="team-list invitation-list">
                @for (invitation of invitations(); track invitation.id) {
                  <li>
                    <strong><span lang="">{{ invitation.email }}</span></strong>
                    <span><span lang="en">{{ invitation.role }}</span> {{ t("· expires") }} <span lang="en">{{ invitation.expires_at }}</span></span>
                    @if (canEditRole(invitation.role)) {
                      <button type="button" (click)="reissueInvitation(invitation)" [disabled]="submitting()">
                        {{ pendingInvitationReissue() === invitation.id ? t("Confirm reissue (old link stops working)") : t("Reissue invitation") }}
                      </button>
                      <button type="button" class="danger-button" (click)="revokeInvitation(invitation)" [disabled]="submitting()">
                        {{ pendingInvitationRevocation() === invitation.id ? t("Confirm revoke invitation") : t("Revoke invitation") }}
                      </button>
                    }
                  </li>
                }
              </ul>

              <h3>{{ t("Invite a team member") }}</h3>
              <form (submit)="inviteMember($event)">
                <label for="invitation-email">{{ t("Verified email address") }}</label>
                <input lang="" id="invitation-email" name="email" type="email" autocomplete="email" required />
                <label for="invitation-role">{{ t("Role") }}</label>
                <select id="invitation-role" name="role">
                  @for (role of manageableRoles(); track role) { <option lang="en" [value]="role">{{ role }}</option> }
                </select>
                <fieldset>
                  <legend>{{ t("Restricted project access") }}</legend>
                  @for (project of projects(); track project.id) {
                    <label class="check-row" [for]="'invitation-project-' + project.id">
                      <input [id]="'invitation-project-' + project.id" type="checkbox" [name]="'project-' + project.id" />
                      <span lang="">{{ project.name }}</span>
                    </label>
                  }
                </fieldset>
                <button type="submit" [disabled]="submitting()">{{ t("Send invitation") }}</button>
              </form>
            }
          </section>
        }

        @if (activeOrganization()?.role === 'owner' && !activeOrganization()?.is_suspended) {
          <section class="workspace-panel" aria-labelledby="organization-settings-title">
            <h2 id="organization-settings-title">{{ t("Organization settings") }}</h2>
            <form (submit)="saveOrganization($event)">
              <label for="organization-name">{{ t("Organization name") }}</label>
              <input lang="" id="organization-name" name="name" required maxlength="160" [value]="activeOrganization()!.name" />
              <button type="submit" [disabled]="submitting()">{{ t("Save organization") }}</button>
            </form>
          </section>

        }

        @if (canManageProjects()) {
          <section class="workspace-panel" aria-labelledby="new-project-title">
            <h2 id="new-project-title">{{ t("Add project") }}</h2>
            <p>{{ t("Enter one canonical HTTP or HTTPS origin. Aliases stay explicit and do not widen crawl scope.") }}</p>
            <form (submit)="createProject($event)">
              <label for="new-project-name">{{ t("Project name") }}</label>
              <input lang="" id="new-project-name" name="name" required maxlength="160" />
              <label for="new-project-origin">{{ t("Canonical origin") }}</label>
              <input lang="" id="new-project-origin" name="canonical-origin" type="url" required placeholder="https://example.com" />
              <label for="new-project-aliases">{{ t("Aliases") }} <span class="field-help">{{ t("One origin per line") }}</span></label>
              <textarea lang="" id="new-project-aliases" name="aliases" rows="3"></textarea>
              <label class="check-row" for="new-project-restricted">
                <input id="new-project-restricted" name="restricted" type="checkbox" /> {{ t("Restrict access to assigned members") }}
              </label>
              <button type="submit" [disabled]="submitting()">{{ t("Create project") }}</button>
            </form>
          </section>

          @if (activeProject()) {
            <section class="workspace-panel" aria-labelledby="project-settings-title">
              <h2 id="project-settings-title">{{ t("Project settings") }}</h2>
              <form (submit)="saveProject($event)">
                <label for="project-name">{{ t("Project name") }}</label>
                <input lang="" id="project-name" name="name" required maxlength="160" [value]="activeProject()!.name" />
                <label for="project-origin">{{ t("Canonical origin") }}</label>
                <input lang="" id="project-origin" name="canonical-origin" type="url" required [value]="activeProject()!.canonical_origin" />
                <label for="project-aliases">{{ t("Aliases") }} <span class="field-help">{{ t("One origin per line") }}</span></label>
                <textarea lang="" id="project-aliases" name="aliases" rows="3" [value]="activeProject()!.aliases.join('\n')"></textarea>
                <label class="check-row" for="project-restricted">
                  <input id="project-restricted" name="restricted" type="checkbox" [checked]="activeProject()!.access_restricted" /> {{ t("Restrict access to assigned members") }}
                </label>
                <button type="submit" [disabled]="submitting()">{{ t("Save project") }}</button>
              </form>
            </section>
          }
        }
      }

      <nav class="workspace-links" [attr.aria-label]="t('Personal and preview links')">
        <a routerLink="/account/security">{{ t("Security and sessions") }}</a>
        <a routerLink="/">{{ t("Preview home") }}</a>
      </nav>
      <button type="button" class="sign-out secondary-button" (click)="logout()" [disabled]="submitting()">
        {{ submitting() ? t("Working…") : t("Sign out") }}
      </button>
    </section>
  `,
})
export class Overview implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  t(text: string) { return this.uiLanguage() === 'tr' ? overviewTurkish[text] ?? text : text; }
  readonly environment = environment;
  @ViewChild('errorSummary') private errorSummary?: ElementRef<HTMLElement>;
  readonly organizations = signal<OrganizationInfo[]>([]);
  readonly projects = signal<ProjectInfo[]>([]);
  readonly activeOrganization = signal<OrganizationInfo | null>(null);
  readonly activeProject = signal<ProjectInfo | null>(null);
  readonly members = signal<TeamMemberInfo[]>([]);
  readonly invitations = signal<InvitationInfo[]>([]);
  readonly loadingOrganizations = signal(true);
  readonly loadingProjects = signal(false);
  readonly loadingTeam = signal(false);
  readonly organizationLoadFailed = signal(false);
  readonly projectLoadFailed = signal(false);
  readonly teamLoadFailed = signal(false);
  readonly submitting = signal(false);
  readonly error = signal('');
  readonly message = signal('');
  readonly pendingRemoval = signal<number | null>(null);
  readonly pendingInvitationRevocation = signal<number | null>(null);
  readonly pendingInvitationReissue = signal<number | null>(null);
  readonly pendingTransfer = signal<OwnershipTransferInfo | null>(null);
  readonly pendingLeave = signal(false);
  private organizationRequest = 0;
  private projectRequest = 0;
  private teamRequest = 0;
  private transferRequest = 0;

  constructor(private readonly api: AccountApi, private readonly router: Router, private readonly destroy: DestroyRef, title: Title) {
    effect(() => title.setTitle(`${this.t('Organization and project context')} — OrganicSEOOps`));
  }

  ngOnInit() {
    void this.loadProductLanguage();
    void this.loadOrganizations();
  }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroy.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  async loadOrganizations(preferredId?: number) {
    const request = ++this.organizationRequest;
    this.loadingOrganizations.set(true);
    this.organizationLoadFailed.set(false);
    this.clearStatus();
    this.organizations.set([]);
    this.activeOrganization.set(null);
    this.clearProjects();
    this.clearTeam();
    this.clearTransfer();
    try {
      const result = await this.api.organizations();
      if (request !== this.organizationRequest) return;
      if (result.status === 401) return void this.router.navigateByUrl('/account/login');
      if (result.status !== 200) {
        this.organizationLoadFailed.set(true);
        return this.showError('Organizations are temporarily unavailable. Try again.');
      }
      const organizations = readOrganizations(result);
      if (organizations === null) {
        this.organizationLoadFailed.set(true);
        return this.showError('Organizations are temporarily unavailable. Try again.');
      }
      this.organizations.set(organizations);
      const active = organizations.find((item) => item.id === preferredId) || organizations[0] || null;
      this.activeOrganization.set(active);
      if (active && !active.is_suspended) {
        void this.loadProjects(active.id);
        if (this.canManageTeam()) void this.loadTeam(active.id);
        else this.clearTeam();
        void this.loadTransfer(active.id);
      } else {
        this.clearProjects();
        this.clearTeam();
      }
    } catch {
      if (request === this.organizationRequest) {
        this.organizationLoadFailed.set(true);
        this.showError('Organizations are temporarily unavailable. Try again.');
      }
    } finally {
      if (request === this.organizationRequest) this.loadingOrganizations.set(false);
    }
  }

  selectOrganization(event: Event) {
    const id = Number((event.target as HTMLSelectElement).value);
    const organization = this.organizations().find((item) => item.id === id) || null;
    this.activeOrganization.set(organization);
    this.clearStatus();
    this.clearProjects();
    this.clearTeam();
    this.clearTransfer();
    if (organization && !organization.is_suspended) {
      void this.loadProjects(organization.id);
      if (this.canManageTeam()) void this.loadTeam(organization.id);
      void this.loadTransfer(organization.id);
    }
  }

  selectProject(event: Event) {
    const id = Number((event.target as HTMLSelectElement).value);
    this.activeProject.set(this.projects().find((item) => item.id === id) || null);
    this.clearStatus();
  }

  retryOrganizations() {
    void this.loadOrganizations(this.activeOrganization()?.id);
  }

  retryProjects() {
    const organization = this.activeOrganization();
    if (organization) void this.loadProjects(organization.id);
  }

  retryTeam() {
    const organization = this.activeOrganization();
    if (organization && this.canManageTeam()) void this.loadTeam(organization.id);
  }

  canManageTeam() {
    return !this.activeOrganization()?.is_suspended && (this.activeOrganization()?.role === 'owner' || this.activeOrganization()?.role === 'admin');
  }

  canManageProjects() {
    return this.canManageTeam();
  }

  trialEndLabel(trial: TrialInfo) {
    return trial.ends_at ? new Date(trial.ends_at).toLocaleString() : 'after eligibility approval';
  }

  manageableRoles(): OrganizationInfo['role'][] {
    return this.activeOrganization()?.role === 'owner'
      ? ['member', 'viewer', 'admin']
      : ['member', 'viewer'];
  }

  canEditRole(role: OrganizationInfo['role']) {
    if (role === 'owner') return false;
    return this.activeOrganization()?.role === 'owner' || (this.activeOrganization()?.role === 'admin' && (role === 'member' || role === 'viewer'));
  }

  async createOrganization(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.submitting()) return;
    this.startRequest();
    try {
      const result = await this.api.createOrganization(String(new FormData(form).get('name')));
      const organization = readOrganization(result.body['organization']);
      if (result.status === 201 && organization) {
        form.reset();
        await this.loadOrganizations(organization.id);
        this.message.set(organization.trial?.access_state === 'active'
          ? 'Organization created with a 30-day trial record.'
          : 'Organization created. Trial eligibility requires staff review.');
      } else this.showError('Organization creation failed. Check the name and verified account status.');
    } catch {
      this.showError('Organization creation is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async saveOrganization(event: SubmitEvent) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !form.reportValidity() || this.submitting()) return;
    this.startRequest();
    try {
      const result = await this.api.updateOrganization(organization.id, String(new FormData(form).get('name')));
      const updated = readOrganization(result.body['organization']);
      if (result.status === 200 && updated) {
        this.organizations.update((items) => items.map((item) => item.id === updated.id ? updated : item));
        this.activeOrganization.set(updated);
        this.message.set('Organization settings saved.');
      } else this.showError(result.status === 403 ? 'Only an organization owner can change these settings.' : 'Organization settings could not be saved.');
    } catch {
      this.showError('Organization settings are temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async createProject(event: SubmitEvent) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !form.reportValidity() || this.submitting()) return;
    const fields = new FormData(form);
    this.startRequest();
    try {
      const result = await this.api.createProject(
        organization.id,
        String(fields.get('name')),
        String(fields.get('canonical-origin')),
        aliases(fields.get('aliases')),
        fields.get('restricted') === 'on',
      );
      const project = readProject(result.body['project']);
      if (result.status === 201 && project) {
        form.reset();
        await this.loadProjects(organization.id, project.id);
        this.message.set('Project created. Aliases remain explicit configuration only.');
      } else this.showError('Project creation failed. Check the origin and aliases.');
    } catch {
      this.showError('Project creation is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async saveProject(event: SubmitEvent) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const project = this.activeProject();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !project || !form.reportValidity() || this.submitting()) return;
    const fields = new FormData(form);
    this.startRequest();
    try {
      const result = await this.api.updateProject(organization.id, project.id, {
        name: String(fields.get('name')),
        canonical_origin: String(fields.get('canonical-origin')),
        aliases: aliases(fields.get('aliases')),
        access_restricted: fields.get('restricted') === 'on',
      });
      const updated = readProject(result.body['project']);
      if (result.status === 200 && updated) {
        this.projects.update((items) => items.map((item) => item.id === updated.id ? updated : item));
        this.activeProject.set(updated);
        this.message.set('Project settings saved.');
      } else this.showError(result.status === 403 ? 'Only an organization owner can change these settings.' : 'Project settings could not be saved.');
    } catch {
      this.showError('Project settings are temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async inviteMember(event: SubmitEvent) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !form.reportValidity() || this.submitting()) return;
    const fields = new FormData(form);
    const role = String(fields.get('role')) as OrganizationInfo['role'];
    this.startRequest();
    try {
      const result = await this.api.inviteMember(
        organization.id,
        String(fields.get('email')),
        role,
        selectedProjectIds(form, this.projects()),
      );
      if (result.status === 201) {
        form.reset();
        await this.loadTeam(organization.id);
        this.message.set(result.body['delivery'] === 'failed'
          ? 'Invitation saved, but delivery failed. Reissue it from pending invitations to try again.'
          : 'Invitation sent. It expires in seven days and does not create a trial.');
      } else if (result.status === 403 || result.status === 404) {
        await this.refreshAfterAccessLoss();
      } else this.showError('Invitation could not be created. Check the email, role, and existing invitations.');
    } catch {
      this.showError('Invitations are temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async saveMember(event: SubmitEvent, member: TeamMemberInfo) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !form.reportValidity() || this.submitting()) return;
    this.startRequest();
    try {
      const result = await this.api.updateMember(
        organization.id,
        member.id,
        String(new FormData(form).get('role')) as OrganizationInfo['role'],
        selectedProjectIds(form, this.projects()),
      );
      if (result.status === 200) {
        await this.loadTeam(organization.id);
        this.message.set('Team access saved.');
      } else if (result.status === 403 || result.status === 404) {
        await this.refreshAfterAccessLoss();
      } else this.showError('Team access could not be saved.');
    } catch {
      this.showError('Team access is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async removeMember(member: TeamMemberInfo) {
    const organization = this.activeOrganization();
    if (!organization || this.submitting()) return;
    if (this.pendingRemoval() !== member.id) {
      this.pendingRemoval.set(member.id);
      this.pendingInvitationRevocation.set(null);
      this.pendingInvitationReissue.set(null);
      return;
    }
    this.startRequest();
    try {
      const result = await this.api.removeMember(organization.id, member.id);
      if (result.status === 204) {
        await this.loadTeam(organization.id);
        this.message.set('Member access removed. Their account and other organizations were not changed.');
      } else if (result.status === 403 || result.status === 404) {
        await this.refreshAfterAccessLoss();
      } else this.showError('Member access could not be removed.');
    } catch {
      this.showError('Member access is temporarily unavailable. Try again.');
    } finally {
      this.pendingRemoval.set(null);
      this.submitting.set(false);
    }
  }

  async revokeInvitation(invitation: InvitationInfo) {
    const organization = this.activeOrganization();
    if (!organization || this.submitting()) return;
    if (this.pendingInvitationRevocation() !== invitation.id) {
      this.pendingInvitationRevocation.set(invitation.id);
      this.pendingRemoval.set(null);
      this.pendingInvitationReissue.set(null);
      return;
    }
    this.startRequest();
    try {
      const result = await this.api.revokeInvitation(organization.id, invitation.id);
      if (result.status === 204) {
        await this.loadTeam(organization.id);
        this.message.set('Invitation revoked.');
      } else if (result.status === 403 || result.status === 404) {
        await this.refreshAfterAccessLoss();
      } else this.showError('Invitation could not be revoked.');
    } catch {
      this.showError('Invitations are temporarily unavailable. Try again.');
    } finally {
      this.pendingInvitationRevocation.set(null);
      this.submitting.set(false);
    }
  }

  async reissueInvitation(invitation: InvitationInfo) {
    const organization = this.activeOrganization();
    if (!organization || this.submitting()) return;
    if (this.pendingInvitationReissue() !== invitation.id) {
      this.pendingInvitationReissue.set(invitation.id);
      this.pendingInvitationRevocation.set(null);
      this.pendingRemoval.set(null);
      return;
    }
    this.startRequest();
    try {
      const result = await this.api.reissueInvitation(organization.id, invitation.id);
      if (result.status === 201) {
        await this.loadTeam(organization.id);
        this.message.set(result.body['delivery'] === 'failed'
          ? 'New invitation saved but delivery failed. You can reissue it again.'
          : 'New invitation sent. The old link no longer works.');
      } else if (result.status === 403 || result.status === 404) {
        await this.refreshAfterAccessLoss();
      } else this.showError('Invitation could not be reissued. Check its status and team access.');
    } catch {
      this.showError('Invitations are temporarily unavailable. Try again.');
    } finally {
      this.pendingInvitationReissue.set(null);
      this.submitting.set(false);
    }
  }

  async proposeTransfer(event: SubmitEvent) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !form.reportValidity() || this.submitting()) return;
    const fields = new FormData(form);
    this.startRequest();
    try {
      const auth = await this.api.reauthenticate(String(fields.get('password')));
      if (auth.status !== 200) return this.showError('Reauthentication failed. Check your password and try again.');
      const result = await this.api.proposeOwnershipTransfer(organization.id, Number(fields.get('member')));
      if (result.status === 201) {
        form.reset();
        await this.loadTransfer(organization.id);
        this.message.set('Transfer proposed. The member must sign in and accept it.');
      } else if (result.status === 403 || result.status === 404) await this.refreshAfterAccessLoss();
      else this.showError('Transfer could not be proposed. Select an active verified member or resolve a pending transfer.');
    } catch {
      this.showError('Transfer is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async acceptTransfer(event: SubmitEvent, transfer: OwnershipTransferInfo) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !form.reportValidity() || this.submitting()) return;
    this.startRequest();
    try {
      const auth = await this.api.reauthenticate(String(new FormData(form).get('password')));
      if (auth.status !== 200) return this.showError('Reauthentication failed. Check your password and try again.');
      const result = await this.api.acceptOwnershipTransfer(organization.id, transfer.id);
      if (result.status === 200) {
        await this.loadOrganizations(organization.id);
        this.message.set('Ownership accepted. Your role is now owner.');
      } else if (result.status === 403 || result.status === 404) await this.refreshAfterAccessLoss();
      else this.showError('Ownership could not be accepted. Ask the owner to review the transfer.');
    } catch {
      this.showError('Transfer is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async cancelTransfer(event: SubmitEvent, transfer: OwnershipTransferInfo) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !form.reportValidity() || this.submitting()) return;
    this.startRequest();
    try {
      const auth = await this.api.reauthenticate(String(new FormData(form).get('password')));
      if (auth.status !== 200) return this.showError('Reauthentication failed. Check your password and try again.');
      const result = await this.api.cancelOwnershipTransfer(organization.id, transfer.id);
      if (result.status === 204) {
        await this.loadTransfer(organization.id);
        this.message.set('Ownership transfer cancelled. No roles changed.');
      } else if (result.status === 403 || result.status === 404) await this.refreshAfterAccessLoss();
      else this.showError('Ownership transfer could not be cancelled. Refresh and try again.');
    } catch {
      this.showError('Ownership transfer is temporarily unavailable. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  async leave(event: SubmitEvent) {
    event.preventDefault();
    const organization = this.activeOrganization();
    const form = event.currentTarget as HTMLFormElement;
    if (!organization || !form.reportValidity() || this.submitting()) return;
    if (!this.pendingLeave()) {
      this.pendingLeave.set(true);
      return;
    }
    this.startRequest();
    try {
      const auth = await this.api.reauthenticate(String(new FormData(form).get('password')));
      if (auth.status !== 200) return this.showError('Reauthentication failed. Check your password and try again.');
      const result = await this.api.leaveOrganization(organization.id);
      if (result.status === 204) {
        await this.loadOrganizations();
        this.message.set('You left the organization. Your account and other organizations remain available.');
      } else if (result.status === 403 || result.status === 404) await this.refreshAfterAccessLoss();
      else if (result.status === 409) this.showError('Transfer ownership or close the organization before leaving.');
      else this.showError('You could not leave the organization. Try again.');
    } catch {
      this.showError('Leaving is temporarily unavailable. Try again.');
    } finally {
      this.pendingLeave.set(false);
      this.submitting.set(false);
    }
  }

  async logout() {
    if (this.submitting()) return;
    this.clearStatus();
    this.submitting.set(true);
    try {
      const result = await this.api.logout();
      if (result.status === 401 || (result.status >= 200 && result.status < 300)) {
        await this.router.navigateByUrl('/account/login');
      } else {
        this.showError('Sign out failed. Your session may still be active. Try again.');
      }
    } catch {
      this.showError('Sign out failed. Your session may still be active. Try again.');
    } finally {
      this.submitting.set(false);
    }
  }

  private async loadProjects(organizationId: number, preferredId?: number) {
    const request = ++this.projectRequest;
    this.clearProjects(false);
    this.loadingProjects.set(true);
    this.projectLoadFailed.set(false);
    try {
      const result = await this.api.projects(organizationId);
      if (request !== this.projectRequest || this.activeOrganization()?.id !== organizationId) return;
      if (result.status === 401) return void this.router.navigateByUrl('/account/login');
      if (result.status !== 200) {
        this.projectLoadFailed.set(true);
        return this.showError('Projects are temporarily unavailable. Try again.');
      }
      const projects = readProjects(result);
      this.projects.set(projects);
      this.activeProject.set(projects.find((item) => item.id === preferredId) || projects[0] || null);
    } catch {
      if (request === this.projectRequest) {
        this.projectLoadFailed.set(true);
        this.showError('Projects are temporarily unavailable. Try again.');
      }
    } finally {
      if (request === this.projectRequest) this.loadingProjects.set(false);
    }
  }

  private async loadTeam(organizationId: number) {
    const request = ++this.teamRequest;
    this.members.set([]);
    this.invitations.set([]);
    this.loadingTeam.set(true);
    this.teamLoadFailed.set(false);
    try {
      const result = await this.api.team(organizationId);
      if (request !== this.teamRequest || this.activeOrganization()?.id !== organizationId) return;
      if (result.status === 401) return void this.router.navigateByUrl('/account/login');
      if (result.status === 403 || result.status === 404) return void await this.refreshAfterAccessLoss();
      if (result.status !== 200) {
        this.teamLoadFailed.set(true);
        return this.showError('Team access is temporarily unavailable. Try again.');
      }
      this.members.set(readMembers(result));
      this.invitations.set(readInvitations(result));
    } catch {
      if (request === this.teamRequest) {
        this.teamLoadFailed.set(true);
        this.showError('Team access is temporarily unavailable. Try again.');
      }
    } finally {
      if (request === this.teamRequest) this.loadingTeam.set(false);
    }
  }

  private clearProjects(invalidate = true) {
    if (invalidate) this.projectRequest++;
    this.projects.set([]);
    this.activeProject.set(null);
    this.loadingProjects.set(false);
    this.projectLoadFailed.set(false);
  }

  private clearTeam(invalidate = true) {
    if (invalidate) this.teamRequest++;
    this.members.set([]);
    this.invitations.set([]);
    this.loadingTeam.set(false);
    this.teamLoadFailed.set(false);
    this.pendingRemoval.set(null);
    this.pendingInvitationRevocation.set(null);
    this.pendingInvitationReissue.set(null);
  }

  private async loadTransfer(organizationId: number) {
    const request = ++this.transferRequest;
    this.pendingTransfer.set(null);
    try {
      const result = await this.api.ownershipTransfer(organizationId);
      if (request !== this.transferRequest || this.activeOrganization()?.id !== organizationId) return;
      if (result.status === 200) this.pendingTransfer.set(readTransfer(result.body['transfer']));
      else this.showError('Ownership status could not be loaded. Retry the organization context before changing ownership.');
    } catch {
      if (request === this.transferRequest) this.showError('Ownership status could not be loaded. Retry the organization context before changing ownership.');
    }
  }

  private clearTransfer() {
    this.transferRequest++;
    this.pendingTransfer.set(null);
    this.pendingLeave.set(false);
  }

  private async refreshAfterAccessLoss() {
    this.clearProjects();
    this.clearTeam();
    this.clearTransfer();
    await this.loadOrganizations();
    this.showError('Your organization access changed. The active context was refreshed.');
  }

  private startRequest() {
    this.clearStatus();
    this.submitting.set(true);
  }

  private clearStatus() {
    this.error.set('');
    this.message.set('');
  }

  private showError(message: string) {
    this.error.set(message);
    setTimeout(() => {
      if (!this.destroy.destroyed && this.error() === message) this.errorSummary?.nativeElement.focus();
    });
  }
}

function readOrganizations(result: ApiResult) {
  const values = result.body['organizations'];
  if (!Array.isArray(values)) return null;
  const organizations = values.map(readOrganization);
  return organizations.every((value): value is OrganizationInfo => value !== null) ? organizations : null;
}

function readProjects(result: ApiResult) {
  const values = result.body['projects'];
  return Array.isArray(values) ? values.map(readProject).filter((value): value is ProjectInfo => value !== null) : [];
}

function readMembers(result: ApiResult) {
  const values = result.body['members'];
  return Array.isArray(values) ? values.map(readMember).filter((value): value is TeamMemberInfo => value !== null) : [];
}

function readInvitations(result: ApiResult) {
  const values = result.body['invitations'];
  return Array.isArray(values) ? values.map(readInvitation).filter((value): value is InvitationInfo => value !== null) : [];
}

function readOrganization(value: unknown): OrganizationInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const trial = readTrial(item['trial']);
  const accessState = item['trial'] != null && trial === null
    ? 'unavailable'
    : isAccessState(item['access_state']) ? item['access_state'] : 'unavailable';
  return typeof item['id'] === 'number' && typeof item['name'] === 'string' && isRole(item['role'])
    ? {
      id: item['id'],
      name: item['name'],
      role: item['role'],
      is_suspended: item['is_suspended'] === true,
      access_state: accessState,
      trial,
    }
    : null;
}

function readTrial(value: unknown): TrialInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const timestampsValid = item['state'] === 'pending_review'
    ? item['started_at'] === null && item['ends_at'] === null
    : isTimestamp(item['started_at']) && isTimestamp(item['ends_at']);
  const statesAgree = (
    item['state'] === 'pending_review' && (item['access_state'] === 'pending_review' || item['access_state'] === 'suspended')
  ) || (
    item['state'] === 'active' && (item['access_state'] === 'active' || item['access_state'] === 'suspended')
  ) || (
    item['state'] === 'expired' && (item['access_state'] === 'read_only' || item['access_state'] === 'suspended')
  ) || (
    item['state'] === 'suspended' && item['access_state'] === 'suspended'
  );
  return isTrialState(item['state'])
    && item['access_state'] !== 'unavailable' && isAccessState(item['access_state'])
    && typeof item['offer_version'] === 'string'
    && timestampsValid
    && statesAgree
    && positiveInteger(item['project_limit'])
    && positiveInteger(item['member_limit'])
    && positiveInteger(item['unit_limit'])
    && nonnegativeInteger(item['settled_units'])
    && nonnegativeInteger(item['reserved_units'])
    ? item as unknown as TrialInfo : null;
}

function isAccessState(value: unknown): value is NonNullable<OrganizationInfo['access_state']> {
  return value === 'unavailable' || value === 'pending_review' || value === 'active'
    || value === 'read_only' || value === 'suspended';
}

function isTrialState(value: unknown): value is TrialInfo['state'] {
  return value === 'pending_review' || value === 'active' || value === 'expired' || value === 'suspended';
}

function positiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

function nonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isTimestamp(value: unknown): value is string {
  return typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && Number.isFinite(Date.parse(value));
}

function readTransfer(value: unknown): OwnershipTransferInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  return typeof item['id'] === 'number' && typeof item['from_email'] === 'string' && typeof item['to_email'] === 'string'
    ? { id: item['id'], from_email: item['from_email'], to_email: item['to_email'] } : null;
}

function readProject(value: unknown): ProjectInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const values = item['aliases'];
  return typeof item['id'] === 'number'
    && typeof item['organization_id'] === 'number'
    && typeof item['name'] === 'string'
    && typeof item['canonical_origin'] === 'string'
    && Array.isArray(values)
    && values.every((alias) => typeof alias === 'string')
    && typeof item['access_restricted'] === 'boolean'
    && isRole(item['role'])
    ? {
      id: item['id'],
      organization_id: item['organization_id'],
      name: item['name'],
      canonical_origin: item['canonical_origin'],
      aliases: values,
      access_restricted: item['access_restricted'],
      role: item['role'],
    }
    : null;
}

function readMember(value: unknown): TeamMemberInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  return typeof item['id'] === 'number'
    && typeof item['email'] === 'string'
    && isRole(item['role'])
    && isIds(item['project_ids'])
    ? { id: item['id'], email: item['email'], role: item['role'], project_ids: item['project_ids'] }
    : null;
}

function readInvitation(value: unknown): InvitationInfo | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  return typeof item['id'] === 'number'
    && typeof item['email'] === 'string'
    && isRole(item['role'])
    && (item['state'] === 'pending' || item['state'] === 'accepted' || item['state'] === 'revoked')
    && typeof item['expires_at'] === 'string'
    && isIds(item['project_ids'])
    ? {
      id: item['id'],
      email: item['email'],
      role: item['role'],
      state: item['state'],
      expires_at: item['expires_at'],
      project_ids: item['project_ids'],
    }
    : null;
}

function isRole(value: unknown): value is OrganizationInfo['role'] {
  return value === 'owner' || value === 'admin' || value === 'member' || value === 'viewer';
}

function isIds(value: unknown): value is number[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'number');
}

function aliases(value: FormDataEntryValue | null) {
  return String(value || '').split(/\r?\n/).map((alias) => alias.trim()).filter(Boolean);
}

function selectedProjectIds(form: HTMLFormElement, projects: ProjectInfo[]) {
  const fields = new FormData(form);
  return projects.filter((project) => fields.get(`project-${project.id}`) === 'on').map((project) => project.id);
}
