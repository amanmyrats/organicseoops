import { Title } from '@angular/platform-browser';
import { Component, computed, DestroyRef, effect, inject, OnInit, signal, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';
import { draftProductLanguage, isProductLanguageResult } from '../product-language';
import { AccountApi, AIRoutingPolicyInfo, readAIRoutingPolicy } from './account-api';
import { YouTubeSettings } from './youtube-settings';
import { StaffNoticeInspector } from './staff-notice-inspector';
import { StaffMailInspector } from './staff-mail-inspector';
import { StaffFeedbackInspector } from './staff-feedback-inspector';
import { StaffReceiptInspector } from './staff-receipt-inspector';

type Provider = { id: number; key: string; name: string; kind: 'openai' | 'openai_compatible'; enabled: boolean };
type Account = { id: number; provider_id: number; label: string; state: 'active' | 'revoked'; stored: boolean };
type Model = { id: number; provider_id: number; identifier: string; name: string; capabilities: string[];
  enabled: boolean; max_output_tokens: number | null; capability_source: string;
  input_price_usd_per_million: string | null; output_price_usd_per_million: string | null;
  pricing_source: string; access_tier: 'unknown' | 'standard' | 'free'; privacy_policy_url: string };

const providerSettingsTurkish: Record<string, string> = {
  "Provider credentials": "Sağlayıcı kimlik bilgileri",
  "Search Console application saved. Existing customer grants remain separate.": "Search Console uygulaması kaydedildi. Mevcut müşteri yetkileri ayrı kalır.",
  "Search Console application revoked. No new project consent can begin.": "Search Console uygulaması iptal edildi. Yeni proje onayı başlatılamaz.",
  "Analytics application saved. Existing customer grants remain separate.": "Analytics uygulaması kaydedildi. Mevcut müşteri yetkileri ayrı kalır.",
  "Analytics application revoked. No new project consent can begin.": "Analytics uygulaması iptal edildi. Yeni proje onayı başlatılamaz.",
  "Business Profile application saved. Existing customer grants remain separate.": "Business Profile uygulaması kaydedildi. Mevcut müşteri yetkileri ayrı kalır.",
  "Business Profile application revoked. No new project consent can begin.": "Business Profile uygulaması iptal edildi. Yeni proje onayı başlatılamaz.",

  "Platform settings": "Platform ayarları",
  "AI provider credentials": "Yapay zekâ sağlayıcı kimlik bilgileri",
  "Return to security settings": "Güvenlik ayarlarına dönün",
  "Only authorized platform staff can manage these credentials. Saved keys cannot be viewed again. Customer project selection and organization-owned keys are separate settings.": "Bu kimlik bilgilerini yalnızca yetkili platform personeli yönetebilir. Kayıtlı anahtarlar tekrar görüntülenemez. Müşteri proje seçimi ve kuruluşa ait anahtarlar ayrı ayarlardır.",
  "Loading platform providers.": "Platform sağlayıcıları yükleniyor.",
  "Platform provider access is unavailable for this account or session.": "Bu hesap veya oturum için platform sağlayıcı erişimi kullanılamıyor.",
  "Refresh provider list": "Sağlayıcı listesini yenileyin",
  "Only the first 100 providers or accounts are shown.": "Yalnızca ilk 100 sağlayıcı veya hesap gösterilir.",
  "Add provider": "Sağlayıcı ekleyin",
  "Provider key": "Sağlayıcı kodu",
  "Display name": "Görünen ad",
  "API type": "API türü",
  "Compatible API base URL (HTTPS; leave blank for OpenAI)": "Uyumlu API temel URL adresi (HTTPS; OpenAI için boş bırakın)",
  "Add a platform credential": "Platform kimlik bilgisi ekleyin",
  "Provider": "Sağlayıcı",
  "Account label": "Hesap etiketi",
  "Provider API key": "Sağlayıcı API anahtarı",
  "Save credential": "Kimlik bilgisini kaydedin",
  "Rotate a credential": "Kimlik bilgisini yenileyin",
  "Account": "Hesap",
  "Replacement API key": "Yeni API anahtarı",
  "Replace credential": "Kimlik bilgisini değiştirin",
  "Revoking this account stops future model requests. Continue?": "Bu hesabın iptali gelecekteki model isteklerini durdurur. Devam edilsin mi?",
  "Confirm revoke": "İptali onaylayın",
  "Cancel": "İptal",
  "Revoke": "İptal edin",
  "Search Console OAuth application": "Search Console OAuth uygulaması",
  "Configure the platform's Google web application client here. Customers authorize their own projects through Google sign-in; they never paste refresh tokens into this page.": "Platformun Google web uygulaması istemcisini burada yapılandırın. Müşteriler kendi projelerini Google oturum açma işlemiyle yetkilendirir; bu sayfaya asla yenileme belirteci yapıştırmazlar.",
  "Loading Google application status.": "Google uygulama durumu yükleniyor.",
  "Google application settings are unavailable for this staff session.": "Bu personel oturumu için Google uygulama ayarları kullanılamıyor.",
  "Application:": "Uygulama:",
  "· Callback:": "· Geri çağrı:",
  "Google web client ID": "Google web istemcisi kimliği",
  "Google client secret": "Google istemci sırrı",
  "Exact callback URL": "Tam geri çağrı URL adresi",
  "A running OAuth consent or grant must be disconnected before changing this client.": "Bu istemciyi değiştirmeden önce devam eden OAuth izni veya yetkisi kaldırılmalıdır.",
  "Save Google application": "Google uygulamasını kaydedin",
  "Remove this client secret and stop new Google connections?": "Bu istemci sırrı kaldırılsın ve yeni Google bağlantıları durdurulsun mu?",
  "Revoke Google application": "Google uygulamasını iptal edin",
  "Google Analytics OAuth application": "Google Analytics OAuth uygulaması",
  "Configure a separate Analytics read-only web application. Search Console consent cannot authorize Analytics; customer properties and source grants are selected per project after separate browser consent.": "Ayrı bir salt okunur Analytics web uygulaması yapılandırın. Search Console izni Analytics yetkisi vermez; müşteri mülkleri ve kaynak yetkileri ayrı tarayıcı izninden sonra proje bazında seçilir.",
  "Loading Analytics application status.": "Analytics uygulama durumu yükleniyor.",
  "Analytics application settings are unavailable for this staff session.": "Bu personel oturumu için Analytics uygulama ayarları kullanılamıyor.",
  "Analytics application:": "Analytics uygulaması:",
  "Analytics web client ID": "Analytics web istemcisi kimliği",
  "Analytics client secret": "Analytics istemci sırrı",
  "Exact Analytics callback URL": "Tam Analytics geri çağrı URL adresi",
  "Existing Analytics grants and pending consent must be revoked before rotating this client.": "Bu istemciyi yenilemeden önce mevcut Analytics yetkileri ve bekleyen izinler iptal edilmelidir.",
  "Save Analytics application": "Analytics uygulamasını kaydedin",
  "Remove the Analytics client secret and stop new Analytics consent?": "Analytics istemci sırrı kaldırılsın ve yeni Analytics izinleri durdurulsun mu?",
  "Confirm Analytics revoke": "Analytics iptalini onaylayın",
  "Revoke Analytics application": "Analytics uygulamasını iptal edin",
  "Google Business Profile OAuth application": "Google Business Profile OAuth uygulaması",
  "Dedicated business.manage consent; Search Console and Analytics grants cannot authorize business profiles. App approval, quota, eligible business access and terms remain unverified release checks. The reader is still under implementation.": "Özel business.manage izni gerekir; Search Console ve Analytics yetkileri işletme profillerini yetkilendiremez. Uygulama onayı, kota, uygun işletme erişimi ve koşullar doğrulanmamış yayın kontrolleridir. Okuyucunun geliştirilmesi devam ediyor.",
  "Loading Business Profile application status.": "Business Profile uygulama durumu yükleniyor.",
  "Business Profile settings are unavailable for this staff session.": "Bu personel oturumu için Business Profile ayarları kullanılamıyor.",
  "Business Profile application:": "Business Profile uygulaması:",
  "Business Profile web client ID": "Business Profile web istemcisi kimliği",
  "Business Profile client secret": "Business Profile istemci sırrı",
  "Exact Business Profile callback URL": "Tam Business Profile geri çağrı URL adresi",
  "Finish revoking existing grants and pending consent before rotation. Emergency app revocation immediately disables grants; remote token revocation remains pending until confirmed.": "Yenilemeden önce mevcut yetkilerin ve bekleyen izinlerin iptalini tamamlayın. Acil uygulama iptali yetkileri hemen devre dışı bırakır; uzak belirteç iptali doğrulanana kadar beklemede kalır.",
  "Save Business Profile application": "Business Profile uygulamasını kaydedin",
  "Remove the Business Profile app secret and immediately disable its source grants?": "Business Profile uygulama sırrı kaldırılsın ve kaynak yetkileri hemen devre dışı bırakılsın mı?",
  "Confirm Business Profile revoke": "Business Profile iptalini onaylayın",
  "Revoke Business Profile application": "Business Profile uygulamasını iptal edin",
  "Paddle seller and Agency catalog": "Paddle satıcısı ve Agency kataloğu",
  "Staff-only sandbox and live credentials are independent and write-only. Catalog terms entered here are unverified until Paddle confirms the product and recurring USD 149 monthly price. Checkout is unavailable.": "Yalnızca personele açık test ve canlı ortam kimlik bilgileri bağımsızdır ve yalnızca yazılır. Paddle ürünü ve tekrarlayan aylık 149 USD fiyatını doğrulayana kadar buradaki katalog koşulları doğrulanmamıştır. Ödeme başlatılamaz.",
  "Loading seller status.": "Satıcı durumu yükleniyor.",
  "Seller settings are unavailable for this session.": "Bu oturum için satıcı ayarları kullanılamıyor.",
  "· catalog not provider-verified": "· katalog sağlayıcı tarafından doğrulanmamış",
  "Product:": "Ürün:",
  "· price:": "· fiyat:",
  "seller secrets? Linked subscriptions prevent unsafe removal.": "satıcı sırları iptal edilsin mi? Bağlı abonelikler güvenli olmayan kaldırmayı engeller.",
  "seller": "satıcısı",
  "Paddle environment": "Paddle ortamı",
  "Sandbox": "Test ortamı",
  "Live": "Canlı ortam",
  "Seller API key": "Satıcı API anahtarı",
  "Webhook verification secret": "Webhook doğrulama sırrı",
  "Paddle.js client-side token for this environment": "Bu ortam için Paddle.js istemci tarafı belirteci",
  "Paddle product ID": "Paddle ürün kimliği",
  "Paddle recurring price ID": "Paddle tekrarlayan fiyat kimliği",
  "By saving, you attest this price is USD 149.00 per month, quantity one, with no Paddle trial. This form does not verify Paddle's catalog or activate customer payments.": "Kaydederek bu fiyatın aylık 149.00 USD, miktarın bir olduğunu ve Paddle denemesi içermediğini beyan edersiniz. Bu form Paddle kataloğunu doğrulamaz veya müşteri ödemelerini etkinleştirmez.",
  "Save seller settings": "Satıcı ayarlarını kaydedin",
  "Rotate only a seller API key": "Yalnızca satıcı API anahtarını yenileyin",
  "Linked subscriptions keep their existing webhook verification secret and catalog. A full replacement is unavailable while subscriptions or checkout attempts need reconciliation.": "Bağlı abonelikler mevcut webhook doğrulama sırrını ve kataloğunu korur. Abonelikler veya ödeme girişimleri mutabakat gerektirirken tam değiştirme yapılamaz.",
  "Environment": "Ortam",
  "Replacement seller API key": "Yeni satıcı API anahtarı",
  "Rotate seller API key": "Satıcı API anahtarını yenileyin",
  "Retry a reviewed failed signed billing receipt": "İncelenmiş başarısız imzalı faturalama alındısını yeniden deneyin",
  "Use a receipt ID from staff billing inspection only after reviewing provider recovery. Retrying reads current provider state; it never submits another checkout payment.": "Personel faturalama incelemesinden alınan bir alındı kimliğini yalnızca sağlayıcının toparlanmasını inceledikten sonra kullanın. Yeniden deneme güncel sağlayıcı durumunu okur; asla başka bir ödeme göndermez.",
  "Billing receipt ID": "Faturalama alındısı kimliği",
  "Reason for this audited retry": "Bu denetim kaydı tutulan yeniden denemenin nedeni",
  "Retry signed receipt reconciliation": "İmzalı alındı mutabakatını yeniden deneyin",
  "Trial notice delivery review": "Deneme bildirimi gönderim incelemesi",
  "A failed or interrupted SMTP call may have delivered a notice. Review before reissuing; it can send a duplicate, and no retry is automatic.": "Başarısız veya kesintiye uğrayan bir SMTP çağrısı bildirim göndermiş olabilir. Yeniden göndermeden önce inceleyin; yinelenen bildirim gönderilebilir ve hiçbir yeniden deneme otomatik değildir.",
  "Uncertain notice ID": "Sonucu belirsiz bildirim kimliği",
  "Review reason": "İnceleme nedeni",
  "I reviewed the outcome and accept that reissuing may send a duplicate.": "Sonucu inceledim ve yeniden gönderimin yinelenen bildirim gönderebileceğini kabul ediyorum.",
  "Reissue once after review": "İncelemeden sonra bir kez yeniden gönderin",
  "Email bounce and complaint review": "E-posta geri dönme ve şikâyet incelemesi",
  "Permanent bounces and single-recipient complaints stop mail to the affected verified address. Clear a suppression only after confirming the address can receive mail; account recovery may use another verified address.": "Kalıcı geri dönüşler ve tek alıcı şikâyetleri etkilenen doğrulanmış adrese gönderimi durdurur. Engellemeyi yalnızca adresin e-posta alabileceğini doğruladıktan sonra kaldırın; hesap kurtarma başka bir doğrulanmış adresi kullanabilir.",
  "Suppression ID": "Engelleme kimliği",
  "I confirmed the address is ready to receive mail again.": "Adresin yeniden e-posta almaya hazır olduğunu doğruladım.",
  "Clear after review": "İncelemeden sonra kaldırın",
  "PageSpeed and CrUX API key": "PageSpeed ve CrUX API anahtarı",
  "The audit worker uses this platform key for bounded performance reports. It is never shown after saving.": "Denetim işçisi bu platform anahtarını sınırlı performans raporları için kullanır. Kaydettikten sonra asla gösterilmez.",
  "Loading performance key status.": "Performans anahtarı durumu yükleniyor.",
  "Performance key settings are unavailable for this staff session.": "Bu personel oturumu için performans anahtarı ayarları kullanılamıyor.",
  "Performance key:": "Performans anahtarı:",
  "Save performance key": "Performans anahtarını kaydedin",
  "Remove the saved key and stop future performance requests?": "Kayıtlı anahtar kaldırılsın ve gelecekteki performans istekleri durdurulsun mu?",
  "Revoke performance key": "Performans anahtarını iptal edin",
  "AI model catalog": "Yapay zekâ model kataloğu",
  "Staff confirm the model's documented capabilities before enabling it. Saving the same provider and identifier updates its record.": "Personel modeli etkinleştirmeden önce belgelenmiş yeteneklerini doğrular. Aynı sağlayıcı ve kimlikle kaydetmek mevcut kaydı günceller.",
  "Loading model catalog.": "Model kataloğu yükleniyor.",
  "Model configuration is unavailable for this staff session.": "Bu personel oturumu için model yapılandırması kullanılamıyor.",
  "Refresh model catalog": "Model kataloğunu yenileyin",
  "Only the first 100 models are shown.": "Yalnızca ilk 100 model gösterilir.",
  "; max output": "; azami çıktı",
  "access;": "erişim;",
  "input /": "girdi /",
  "output per million tokens": "milyon belirteç başına çıktı",
  "price unknown": "fiyat bilinmiyor",
  "Provider model identifier": "Sağlayıcı model kimliği",
  "Documented capabilities (select all that apply)": "Belgelenmiş yetenekler (uygun olanların tümünü seçin)",
  "Maximum output tokens (optional)": "Azami çıktı belirteci (isteğe bağlı)",
  "Public HTTPS capability evidence URL": "Herkese açık HTTPS yetenek kanıtı URL adresi",
  "Verified access tier": "Doğrulanmış erişim düzeyi",
  "Unknown (no automatic routing)": "Bilinmiyor (otomatik yönlendirme yok)",
  "Standard paid access": "Standart ücretli erişim",
  "Free/contributor tier (explicit opt-in required)": "Ücretsiz/katkıda bulunan düzeyi (açık tercih gerekir)",
  "Input USD per million tokens (optional, with output price and dated evidence)": "Milyon girdi belirteci başına USD (isteğe bağlı; çıktı fiyatı ve tarihli kanıtla)",
  "Output USD per million tokens (optional)": "Milyon çıktı belirteci başına USD (isteğe bağlı)",
  "Public HTTPS pricing evidence URL": "Herkese açık HTTPS fiyat kanıtı URL adresi",
  "Public HTTPS data-use policy URL (required for free access)": "Herkese açık HTTPS veri kullanım politikası URL adresi (ücretsiz erişim için zorunlu)",
  "Enable after reviewing evidence today": "Kanıtı bugün inceledikten sonra etkinleştirin",
  "Save model": "Modeli kaydedin",
  "System AI text default": "Sistem yapay zekâ metin varsayılanı",
  "Applies only when a project has no override and a job has no explicit model choice. Fallbacks are considered before the first provider request, never after a failed or uncertain attempt. Free/unverified models are not automatic.": "Yalnızca projede geçersiz kılma ve işte açık model seçimi yoksa uygulanır. Yedekler ilk sağlayıcı isteğinden önce değerlendirilir; başarısız veya belirsiz girişimden sonra asla değerlendirilmez. Ücretsiz/doğrulanmamış modeller otomatik değildir.",
  "Loading system routing.": "Sistem yönlendirmesi yükleniyor.",
  "System routing is unavailable for this staff session.": "Bu personel oturumu için sistem yönlendirmesi kullanılamıyor.",
  "Current:": "Güncel:",
  "; revision": "; sürüm",
  "; up to": "; en fazla",
  "tokens, USD": "belirteç, USD",
  "estimated and": "tahmini ve",
  "seconds.": "saniye.",
  "preflight fallback(s).": "istek öncesi yedek model.",
  "Remove the system default? Projects without an override will need explicit model selection.": "Sistem varsayılanı kaldırılsın mı? Geçersiz kılma olmayan projeler açık model seçimi gerektirecek.",
  "Confirm removal": "Kaldırmayı onaylayın",
  "Remove system default": "Sistem varsayılanını kaldırın",
  "No system AI model is chosen.": "Sistem yapay zekâ modeli seçilmemiş.",
  "Standard priced text model": "Fiyatı bilinen standart metin modeli",
  "Choose a model": "Model seçin",
  "Platform account for this model": "Bu model için platform hesabı",
  "Choose an account": "Hesap seçin",
  "Same-provider fallback models (select up to two)": "Aynı sağlayıcıdan yedek modeller (en fazla iki seçin)",
  "Maximum output tokens (1–256)": "Azami çıktı belirteci (1–256)",
  "Maximum estimated USD cost per request (up to 100)": "İstek başına azami tahmini USD maliyeti (en fazla 100)",
  "Request timeout in seconds (1–30)": "Saniye cinsinden istek zaman aşımı (1–30)",
  "Save system default": "Sistem varsayılanını kaydedin",
  "enabled": "etkin",
  "disabled": "devre dışı",
  "stored key": "kayıtlı anahtar",
  "legacy reference": "eski referans",
  "unspecified": "belirtilmemiş",
  "Unavailable model": "Model kullanılamıyor",
  "Unknown provider": "Bilinmeyen sağlayıcı",
  "Unreviewed Turkish platform-settings interface draft in local development. Provider values and identifiers retain their source form; bilingual approval is pending.": "Yerel geliştirmede incelenmemiş Türkçe platform ayarları arayüzü taslağı. Sağlayıcı değerleri ve kimlikler kaynak biçimlerini korur; iki dilli onay bekleniyor.",
  "Notice reissue was not confirmed. Check staff MFA, recipient and trial state.": "Bildirim yeniden gönderimi doğrulanamadı. Personel MFA doğrulamasını, alıcıyı ve deneme durumunu kontrol edin.",
  "Email suppression could not be cleared. Check staff MFA and current status.": "E-posta engellemesi kaldırılamadı. Personel MFA doğrulamasını ve güncel durumu kontrol edin.",
  "Seller settings were not saved. Check MFA, catalog IDs, encryption and linked subscriptions.": "Satıcı ayarları kaydedilmedi. MFA doğrulamasını, katalog kimliklerini, şifrelemeyi ve bağlı abonelikleri kontrol edin.",
  "Seller revocation could not be confirmed. Refresh and check linked subscriptions.": "Satıcı iptali doğrulanamadı. Yenileyin ve bağlı abonelikleri kontrol edin.",
  "Seller API key rotation was not confirmed. Check staff MFA, environment and key format.": "Satıcı API anahtarı yenilemesi doğrulanamadı. Personel MFA doğrulamasını, ortamı ve anahtar biçimini kontrol edin.",
  "Receipt retry could not be confirmed. Check current MFA, receipt status and age.": "Alındı yeniden denemesi doğrulanamadı. Güncel MFA doğrulamasını, alındı durumunu ve yaşını kontrol edin.",
  "Choose one matching platform account and at most two same-provider fallbacks.": "Eşleşen bir platform hesabı ve aynı sağlayıcıdan en fazla iki yedek seçin.",
  "System AI text default saved; jobs still recheck current credentials and budgets.": "Sistem yapay zekâ metin varsayılanı kaydedildi; işler güncel kimlik bilgilerini ve bütçeleri yeniden kontrol eder.",
  "System route was not saved. Refresh and check staff access, model, fallback and cost.": "Sistem yönlendirmesi kaydedilmedi. Yenileyin ve personel erişimini, modeli, yedekleri ve maliyeti kontrol edin.",
  "System AI text default removed. Explicit project settings remain separate.": "Sistem yapay zekâ metin varsayılanı kaldırıldı. Açık proje ayarları ayrı kalır.",
  "Removal could not be confirmed. Refresh routing before retrying.": "Kaldırma doğrulanamadı. Yeniden denemeden önce yönlendirmeyi yenileyin.",
  "Both model prices need dated public evidence; free access requires a data-use policy URL.": "Her iki model fiyatı için tarihli herkese açık kanıt gerekir; ücretsiz erişim veri kullanım politikası URL adresi gerektirir.",
  "Model configuration saved. Capability evidence was dated today.": "Model yapılandırması kaydedildi. Yetenek kanıtı bugün tarihlendirildi.",
  "Model was not saved. Check staff access, capabilities, evidence URL and output limit.": "Model kaydedilmedi. Personel erişimini, yetenekleri, kanıt URL adresini ve çıktı sınırını kontrol edin.",
  "Performance key saved.": "Performans anahtarı kaydedildi.",
  "Performance key was not saved. Check staff access and encryption configuration.": "Performans anahtarı kaydedilmedi. Personel erişimini ve şifreleme yapılandırmasını kontrol edin.",
  "Performance key revoked. Future performance requests cannot use it.": "Performans anahtarı iptal edildi. Gelecekteki performans istekleri bunu kullanamaz.",
  "Performance key revocation could not be confirmed. Refresh before retrying.": "Performans anahtarı iptali doğrulanamadı. Yeniden denemeden önce yenileyin.",
  "Google application was not saved. Check the exact callback, staff access and pending grants.": "Google uygulaması kaydedilmedi. Tam geri çağrı adresini, personel erişimini ve bekleyen yetkileri kontrol edin.",
  "Google revocation could not be confirmed. Disconnect pending grants and refresh.": "Google iptali doğrulanamadı. Bekleyen yetkileri kaldırın ve yenileyin.",
  "Provider settings are unavailable. Retry the load.": "Sağlayıcı ayarları kullanılamıyor. Yüklemeyi yeniden deneyin.",
  "Provider added.": "Sağlayıcı eklendi.",
  "Credential saved.": "Kimlik bilgisi kaydedildi.",
  "Credential replaced.": "Kimlik bilgisi değiştirildi.",
  "Choose an available account.": "Kullanılabilir bir hesap seçin.",
  "Provider account revoked. Existing provider keys are no longer usable here.": "Sağlayıcı hesabı iptal edildi. Mevcut sağlayıcı anahtarları artık burada kullanılamaz.",
  "Revocation could not be confirmed. Refresh before trying again.": "İptal doğrulanamadı. Yeniden denemeden önce yenileyin.",
  "Provider settings were not saved. Check the fields, staff access and encryption configuration.": "Sağlayıcı ayarları kaydedilmedi. Alanları, personel erişimini ve şifreleme yapılandırmasını kontrol edin."
};

@Component({
  selector: 'app-provider-settings',
  imports: [RouterLink, YouTubeSettings, StaffNoticeInspector, StaffMailInspector, StaffFeedbackInspector, StaffReceiptInspector],
  template: `
    <section [attr.lang]="uiLanguage()" class="account-card" aria-labelledby="provider-title">
      <p class="eyebrow">{{ t("Platform settings") }}</p>
      <h1 id="provider-title">{{ t("AI provider credentials") }}</h1>
      @if (uiLanguage() === 'tr') { <p role="status">{{ t("Unreviewed Turkish platform-settings interface draft in local development. Provider values and identifiers retain their source form; bilingual approval is pending.") }}</p> }
      <p><a routerLink="/account/security">{{ t("Return to security settings") }}</a></p>
      <p>{{ t("Only authorized platform staff can manage these credentials. Saved keys cannot be viewed again. Customer project selection and organization-owned keys are separate settings.") }}</p>
      @if (message()) { <p role="status" [attr.lang]="textLanguage(message())">{{ t(message()) }}</p> }
      @if (error()) { <p role="alert" class="form-status error">{{ t(error()) }}</p> }
      @if (loading()) { <p role="status">{{ t("Loading platform providers.") }}</p> }
      @if (!loading() && denied()) { <p>{{ t("Platform provider access is unavailable for this account or session.") }}</p> }
      @if (!loading() && !denied()) {
        <button type="button" (click)="load()" [disabled]="busy()">{{ t("Refresh provider list") }}</button>
        @if (hasMore()) { <p>{{ t("Only the first 100 providers or accounts are shown.") }}</p> }
        <ul>
          @for (provider of providers(); track provider.id) {
            <li><span lang="">{{ provider.name }}</span> (<span lang="en">{{ provider.kind }}</span>) — {{ t(provider.enabled ? 'enabled' : 'disabled') }}</li>
          }
        </ul>
        <section aria-labelledby="create-provider-title">
          <h2 id="create-provider-title">{{ t("Add provider") }}</h2>
          <form (submit)="createProvider($event)">
            <label for="provider-key">{{ t("Provider key") }}</label>
            <input id="provider-key" name="key" required maxlength="32" autocomplete="off" />
            <label for="provider-name">{{ t("Display name") }}</label>
            <input id="provider-name" name="name" required maxlength="80" />
            <label for="provider-kind">{{ t("API type") }}</label>
            <select id="provider-kind" name="kind" required>
              <option value="openai">OpenAI</option>
              <option value="openai_compatible">OpenAI-compatible</option>
            </select>
            <label for="provider-url">{{ t("Compatible API base URL (HTTPS; leave blank for OpenAI)") }}</label>
            <input id="provider-url" name="base_url" type="url" maxlength="1024" />
            <button type="submit" [disabled]="busy()">{{ t("Add provider") }}</button>
          </form>
        </section>
        @if (providers().length) {
          <section aria-labelledby="create-account-title">
            <h2 id="create-account-title">{{ t("Add a platform credential") }}</h2>
            <form (submit)="createAccount($event)">
              <label for="credential-provider">{{ t("Provider") }}</label>
              <select id="credential-provider" name="provider_id" required>
                @for (provider of providers(); track provider.id) {
                  <option [value]="provider.id" lang="">{{ provider.name }}</option>
                }
              </select>
              <label for="credential-label">{{ t("Account label") }}</label>
              <input id="credential-label" name="label" required maxlength="80" />
              <label for="new-platform-key">{{ t("Provider API key") }}</label>
              <input id="new-platform-key" name="secret" type="password" required autocomplete="new-password" />
              <button type="submit" [disabled]="busy()">{{ t("Save credential") }}</button>
            </form>
          </section>
        }
        @if (activeAccounts().length) {
          <section aria-labelledby="rotate-title">
            <h2 id="rotate-title">{{ t("Rotate a credential") }}</h2>
            <form (submit)="rotate($event)">
              <label for="rotate-account">{{ t("Account") }}</label>
              <select id="rotate-account" name="account_id" required>
                @for (account of activeAccounts(); track account.id) {
                  <option [value]="account.id" lang="">{{ account.label }} — {{ providerName(account.provider_id) }}
                    ({{ t(account.stored ? 'stored key' : 'legacy reference') }})</option>
                }
              </select>
              <label for="rotate-key">{{ t("Replacement API key") }}</label>
              <input id="rotate-key" name="secret" type="password" required autocomplete="new-password" />
              <button type="submit" [disabled]="busy()">{{ t("Replace credential") }}</button>
            </form>
            @for (account of activeAccounts(); track account.id) {
              <div>
                <span><span lang="">{{ account.label }}</span> — <span lang="">{{ providerName(account.provider_id) }}</span></span>
                @if (confirmRevoke() === account.id) {
                  <p role="alert">{{ t("Revoking this account stops future model requests. Continue?") }}</p>
                  <button type="button" (click)="revoke(account)" [disabled]="busy()">{{ t("Confirm revoke") }}</button>
                  <button type="button" (click)="confirmRevoke.set(null)" [disabled]="busy()">{{ t("Cancel") }}</button>
                } @else {
                  <button type="button" (click)="confirmRevoke.set(account.id)" [disabled]="busy()">{{ t("Revoke") }} <span lang="">{{ account.label }}</span></button>
                }
              </div>
            }
          </section>
        }
      }
      <section aria-labelledby="google-app-title">
        <h2 id="google-app-title">{{ t("Search Console OAuth application") }}</h2>
        <p>{{ t("Configure the platform's Google web application client here. Customers authorize their own projects through Google sign-in; they never paste refresh tokens into this page.") }}</p>
        @if (googleState() === 'loading') { <p role="status">{{ t("Loading Google application status.") }}</p> }
        @else if (googleState() === 'denied') { <p>{{ t("Google application settings are unavailable for this staff session.") }}</p> }
        @else {
          <p role="status">{{ t("Application:") }} <span lang="en">{{ googleState() }}</span>
            @if (googleRedirect()) { {{ t("· Callback:") }} <span lang="en">{{ googleRedirect() }}</span> }
          </p>
          <form (submit)="saveGoogle($event)">
            <label for="google-client-id">{{ t("Google web client ID") }}</label>
            <input id="google-client-id" name="client_id" required maxlength="512" autocomplete="off" />
            <label for="google-client-secret">{{ t("Google client secret") }}</label>
            <input id="google-client-secret" name="client_secret" type="password" required autocomplete="new-password" maxlength="512" />
            <label for="google-redirect-uri">{{ t("Exact callback URL") }}</label>
            <input id="google-redirect-uri" name="redirect_uri" type="url" required maxlength="512" [value]="googleRedirect()" />
            <p>{{ t("A running OAuth consent or grant must be disconnected before changing this client.") }}</p>
            <button type="submit" [disabled]="busy()">{{ t("Save Google application") }}</button>
          </form>
          @if (googleState() === 'active') {
            @if (confirmGoogleRevoke()) {
              <p role="alert">{{ t("Remove this client secret and stop new Google connections?") }}</p>
              <button type="button" (click)="revokeGoogle()" [disabled]="busy()">{{ t("Confirm revoke") }}</button>
              <button type="button" (click)="confirmGoogleRevoke.set(false)" [disabled]="busy()">{{ t("Cancel") }}</button>
            } @else {
              <button type="button" (click)="confirmGoogleRevoke.set(true)" [disabled]="busy()">{{ t("Revoke Google application") }}</button>
            }
          }
        }
      </section>
      <section aria-labelledby="analytics-app-title">
        <h2 id="analytics-app-title">{{ t("Google Analytics OAuth application") }}</h2>
        <p>{{ t("Configure a separate Analytics read-only web application. Search Console consent cannot authorize Analytics; customer properties and source grants are selected per project after separate browser consent.") }}</p>
        @if (analyticsState() === 'loading') { <p role="status">{{ t("Loading Analytics application status.") }}</p> }
        @else if (analyticsState() === 'denied') { <p>{{ t("Analytics application settings are unavailable for this staff session.") }}</p> }
        @else {
          <p role="status">{{ t("Analytics application:") }} <span lang="en">{{ analyticsState() }}</span>
            @if (analyticsRedirect()) { {{ t("· Callback:") }} <span lang="en">{{ analyticsRedirect() }}</span> }
          </p>
          <form (submit)="saveGoogle($event, 'analytics')">
            <label for="analytics-client-id">{{ t("Analytics web client ID") }}</label>
            <input id="analytics-client-id" name="client_id" required maxlength="512" autocomplete="off" />
            <label for="analytics-client-secret">{{ t("Analytics client secret") }}</label>
            <input id="analytics-client-secret" name="client_secret" type="password" required autocomplete="new-password" maxlength="512" />
            <label for="analytics-redirect-uri">{{ t("Exact Analytics callback URL") }}</label>
            <input id="analytics-redirect-uri" name="redirect_uri" type="url" required maxlength="512" [value]="analyticsRedirect()" />
            <p>{{ t("Existing Analytics grants and pending consent must be revoked before rotating this client.") }}</p>
            <button type="submit" [disabled]="busy()">{{ t("Save Analytics application") }}</button>
          </form>
          @if (analyticsState() === 'active') {
            @if (confirmAnalyticsRevoke()) {
              <p role="alert">{{ t("Remove the Analytics client secret and stop new Analytics consent?") }}</p>
              <button type="button" (click)="revokeGoogle('analytics')" [disabled]="busy()">{{ t("Confirm Analytics revoke") }}</button>
              <button type="button" (click)="confirmAnalyticsRevoke.set(false)" [disabled]="busy()">{{ t("Cancel") }}</button>
            } @else {
              <button type="button" (click)="confirmAnalyticsRevoke.set(true)" [disabled]="busy()">{{ t("Revoke Analytics application") }}</button>
            }
          }
        }
      </section>
      <section aria-labelledby="business-app-title">
        <h2 id="business-app-title">{{ t("Google Business Profile OAuth application") }}</h2>
        <p>{{ t("Dedicated business.manage consent; Search Console and Analytics grants cannot authorize business profiles. App approval, quota, eligible business access and terms remain unverified release checks. The reader is still under implementation.") }}</p>
        @if (businessState() === 'loading') { <p role="status">{{ t("Loading Business Profile application status.") }}</p> }
        @else if (businessState() === 'denied') { <p>{{ t("Business Profile settings are unavailable for this staff session.") }}</p> }
        @else {
          <p role="status">{{ t("Business Profile application:") }} <span lang="en">{{ businessState() }}</span></p>
          <form (submit)="saveGoogle($event, 'business')">
            <label for="business-client-id">{{ t("Business Profile web client ID") }}</label>
            <input id="business-client-id" name="client_id" required maxlength="512" autocomplete="off" />
            <label for="business-client-secret">{{ t("Business Profile client secret") }}</label>
            <input id="business-client-secret" name="client_secret" type="password" required autocomplete="new-password" maxlength="512" />
            <label for="business-redirect-uri">{{ t("Exact Business Profile callback URL") }}</label>
            <input id="business-redirect-uri" name="redirect_uri" type="url" required maxlength="512" [value]="businessRedirect()" />
            <p>{{ t("Finish revoking existing grants and pending consent before rotation. Emergency app revocation immediately disables grants; remote token revocation remains pending until confirmed.") }}</p>
            <button type="submit" [disabled]="busy()">{{ t("Save Business Profile application") }}</button>
          </form>
          @if (businessState() === 'active') {
            @if (confirmBusinessRevoke()) {
              <p role="alert">{{ t("Remove the Business Profile app secret and immediately disable its source grants?") }}</p>
              <button type="button" (click)="revokeGoogle('business')" [disabled]="busy()">{{ t("Confirm Business Profile revoke") }}</button>
              <button type="button" (click)="confirmBusinessRevoke.set(false)" [disabled]="busy()">{{ t("Cancel") }}</button>
            } @else {
              <button type="button" (click)="confirmBusinessRevoke.set(true)" [disabled]="busy()">{{ t("Revoke Business Profile application") }}</button>
            }
          }
        }
      </section>
      <section aria-labelledby="paddle-seller-title">
        <h2 id="paddle-seller-title">{{ t("Paddle seller and Agency catalog") }}</h2>
        <p>{{ t("Staff-only sandbox and live credentials are independent and write-only. Catalog terms entered here are unverified until Paddle confirms the product and recurring USD 149 monthly price. Checkout is unavailable.") }}</p>
        @for (environment of paddleEnvironments; track environment) {
          <div>
            <h3>{{ t(environment === 'sandbox' ? 'Sandbox' : 'Live') }}</h3>
            @if (paddleStates()[environment] === 'loading') { <p role="status">{{ t("Loading seller status.") }}</p> }
            @else if (paddleStates()[environment] === 'denied') { <p>{{ t("Seller settings are unavailable for this session.") }}</p> }
            @else {
              <p role="status"><span lang="en">{{ paddleStates()[environment] }}</span> {{ t("· catalog not provider-verified") }}</p>
              @if (paddleStates()[environment] === 'active') {
                <p>{{ t("Product:") }} <span lang="en">{{ paddleProducts()[environment] }}</span> {{ t("· price:") }} <span lang="en">{{ paddlePrices()[environment] }}</span></p>
                @if (confirmPaddleRevoke() === environment) {
                  <p role="alert">{{ t("Revoke") }} <span lang="en">{{ environment }}</span> {{ t("seller secrets? Linked subscriptions prevent unsafe removal.") }}</p>
                  <button type="button" (click)="revokePaddle(environment)" [disabled]="busy()">{{ t("Confirm revoke") }}</button>
                  <button type="button" (click)="confirmPaddleRevoke.set(null)" [disabled]="busy()">{{ t("Cancel") }}</button>
                } @else {
                  <button type="button" (click)="confirmPaddleRevoke.set(environment)" [disabled]="busy()">{{ t("Revoke") }} <span lang="en">{{ environment }}</span> {{ t("seller") }}</button>
                }
              }
            }
          </div>
        }
        <form (submit)="savePaddle($event)">
          <label for="paddle-environment">{{ t("Paddle environment") }}</label>
          <select id="paddle-environment" name="environment" required>
            <option value="sandbox">{{ t("Sandbox") }}</option><option value="live">{{ t("Live") }}</option>
          </select>
          <label for="paddle-api-key">{{ t("Seller API key") }}</label>
          <input id="paddle-api-key" name="api_key" type="password" required minlength="16" maxlength="512" autocomplete="new-password" />
          <label for="paddle-webhook-secret">{{ t("Webhook verification secret") }}</label>
          <input id="paddle-webhook-secret" name="webhook_secret" type="password" required minlength="16" maxlength="512" autocomplete="new-password" />
          <label for="paddle-client-token">{{ t("Paddle.js client-side token for this environment") }}</label>
          <input id="paddle-client-token" name="client_token" type="password" required minlength="32" maxlength="32" autocomplete="new-password" />
          <label for="paddle-product">{{ t("Paddle product ID") }}</label>
          <input id="paddle-product" name="product_id" required pattern="pro_[a-z0-9]{26}" maxlength="30" autocomplete="off" />
          <label for="paddle-price">{{ t("Paddle recurring price ID") }}</label>
          <input id="paddle-price" name="price_id" required pattern="pri_[a-z0-9]{26}" maxlength="30" autocomplete="off" />
          <p>{{ t("By saving, you attest this price is USD 149.00 per month, quantity one, with no Paddle trial. This form does not verify Paddle's catalog or activate customer payments.") }}</p>
          <button type="submit" [disabled]="busy()">{{ t("Save seller settings") }}</button>
        </form>
        @if (paddleStates().sandbox === 'active' || paddleStates().live === 'active') {
          <form (submit)="rotatePaddleApiKey($event)">
            <h3>{{ t("Rotate only a seller API key") }}</h3>
            <p>{{ t("Linked subscriptions keep their existing webhook verification secret and catalog. A full replacement is unavailable while subscriptions or checkout attempts need reconciliation.") }}</p>
            <label for="paddle-rotate-environment">{{ t("Environment") }}</label>
            <select id="paddle-rotate-environment" name="environment" required>
              @if (paddleStates().sandbox === 'active') { <option value="sandbox">{{ t("Sandbox") }}</option> }
              @if (paddleStates().live === 'active') { <option value="live">{{ t("Live") }}</option> }
            </select>
            <label for="paddle-rotate-api-key">{{ t("Replacement seller API key") }}</label>
            <input id="paddle-rotate-api-key" name="api_key" type="password" required minlength="69" maxlength="69" autocomplete="new-password" />
            <button type="submit" [disabled]="busy()">{{ t("Rotate seller API key") }}</button>
          </form>
        }
        <app-staff-receipt-inspector />
        <form (submit)="retryPaddleReceipt($event)">
          <h3>{{ t("Retry a reviewed failed signed billing receipt") }}</h3>
          <p>{{ t("Use a receipt ID from staff billing inspection only after reviewing provider recovery. Retrying reads current provider state; it never submits another checkout payment.") }}</p>
          <label for="paddle-receipt-id">{{ t("Billing receipt ID") }}</label>
          <input id="paddle-receipt-id" name="receipt_id" type="number" required min="1" step="1" />
          <label for="paddle-retry-reason">{{ t("Reason for this audited retry") }}</label>
          <input id="paddle-retry-reason" name="reason" required maxlength="250" />
          <button type="submit" [disabled]="busy()">{{ t("Retry signed receipt reconciliation") }}</button>
        </form>
        <section aria-labelledby="notice-review-title">
          <h3 id="notice-review-title">{{ t("Trial notice delivery review") }}</h3>
          <p>{{ t("A failed or interrupted SMTP call may have delivered a notice. Review before reissuing; it can send a duplicate, and no retry is automatic.") }}</p>
          <app-staff-notice-inspector />
          <form (submit)="retryUnknownNotice($event)">
            <label for="unknown-notice-id">{{ t("Uncertain notice ID") }}</label>
            <input id="unknown-notice-id" name="notice_id" type="number" required min="1" step="1" />
            <label for="unknown-notice-reason">{{ t("Review reason") }}</label>
            <input id="unknown-notice-reason" name="reason" required maxlength="250" />
            <label><input type="checkbox" name="acknowledged" required /> {{ t("I reviewed the outcome and accept that reissuing may send a duplicate.") }}</label>
            <button type="submit" [disabled]="busy()">{{ t("Reissue once after review") }}</button>
          </form>
        </section>
        <section aria-labelledby="email-suppression-title">
          <h3 id="email-suppression-title">{{ t("Email bounce and complaint review") }}</h3>
          <p>{{ t("Permanent bounces and single-recipient complaints stop mail to the affected verified address. Clear a suppression only after confirming the address can receive mail; account recovery may use another verified address.") }}</p>
          <app-staff-feedback-inspector />
          <form (submit)="clearEmailSuppression($event)">
            <label for="email-suppression-id">{{ t("Suppression ID") }}</label>
            <input id="email-suppression-id" name="suppression_id" type="number" required min="1" step="1" />
            <label for="email-suppression-reason">{{ t("Review reason") }}</label>
            <input id="email-suppression-reason" name="reason" required maxlength="250" />
            <label><input type="checkbox" name="confirmed" required /> {{ t("I confirmed the address is ready to receive mail again.") }}</label>
            <button type="submit" [disabled]="busy()">{{ t("Clear after review") }}</button>
          </form>
        </section>
        <app-staff-mail-inspector />
      </section>
      <section aria-labelledby="performance-key-title">
        <h2 id="performance-key-title">{{ t("PageSpeed and CrUX API key") }}</h2>
        <p>{{ t("The audit worker uses this platform key for bounded performance reports. It is never shown after saving.") }}</p>
        @if (performanceState() === 'loading') { <p role="status">{{ t("Loading performance key status.") }}</p> }
        @else if (performanceState() === 'denied') { <p>{{ t("Performance key settings are unavailable for this staff session.") }}</p> }
        @else {
          <p role="status">{{ t("Performance key:") }} <span lang="en">{{ performanceState() }}</span></p>
          <form (submit)="savePerformance($event)">
            <label for="performance-api-key">{{ t("Replacement API key") }}</label>
            <input id="performance-api-key" name="api_key" type="password" required autocomplete="new-password" maxlength="200" />
            <button type="submit" [disabled]="busy()">{{ t("Save performance key") }}</button>
          </form>
          @if (performanceState() === 'active') {
            @if (confirmPerformanceRevoke()) {
              <p role="alert">{{ t("Remove the saved key and stop future performance requests?") }}</p>
              <button type="button" (click)="revokePerformance()" [disabled]="busy()">{{ t("Confirm revoke") }}</button>
              <button type="button" (click)="confirmPerformanceRevoke.set(false)" [disabled]="busy()">{{ t("Cancel") }}</button>
            } @else {
              <button type="button" (click)="confirmPerformanceRevoke.set(true)" [disabled]="busy()">{{ t("Revoke performance key") }}</button>
            }
          }
        }
      </section>
      <app-youtube-settings />
      <section aria-labelledby="models-title">
        <h2 id="models-title">{{ t("AI model catalog") }}</h2>
        <p>{{ t("Staff confirm the model's documented capabilities before enabling it. Saving the same provider and identifier updates its record.") }}</p>
        @if (modelLoading()) { <p role="status">{{ t("Loading model catalog.") }}</p> }
        @else if (modelDenied()) { <p>{{ t("Model configuration is unavailable for this staff session.") }}</p> }
        @else {
          <button type="button" (click)="loadModels()" [disabled]="busy()">{{ t("Refresh model catalog") }}</button>
          @if (modelHasMore()) { <p>{{ t("Only the first 100 models are shown.") }}</p> }
          <ul>
            @for (model of models(); track model.id) {
              <li><span lang="">{{ model.name }}</span> (<span lang="en">{{ model.identifier }}</span>) — {{ t(model.enabled ? 'enabled' : 'disabled') }};
                <span lang="en">{{ model.capabilities.join(', ') }}</span>{{ t("; max output") }} {{ model.max_output_tokens ?? t('unspecified') }};
                <span lang="en">{{ model.access_tier }}</span> {{ t("access;") }}
                @if (model.input_price_usd_per_million !== null && model.output_price_usd_per_million !== null) {
                  USD {{ model.input_price_usd_per_million }} {{ t("input /") }} {{ model.output_price_usd_per_million }} {{ t("output per million tokens") }}
                } @else { {{ t("price unknown") }} }
              </li>
            }
          </ul>
          @if (providers().length) {
            <form (submit)="saveModel($event)">
              <label for="model-provider">{{ t("Provider") }}</label>
              <select id="model-provider" name="provider_id" required>
                @for (provider of providers(); track provider.id) { <option [value]="provider.id" lang="">{{ provider.name }}</option> }
              </select>
              <label for="model-identifier">{{ t("Provider model identifier") }}</label>
              <input id="model-identifier" name="identifier" required maxlength="128" autocomplete="off" />
              <label for="model-name">{{ t("Display name") }}</label>
              <input id="model-name" name="name" required maxlength="120" />
              <label for="model-capabilities">{{ t("Documented capabilities (select all that apply)") }}</label>
              <select id="model-capabilities" name="capabilities" multiple required size="7">
                @for (capability of capabilityChoices(); track capability) {
                  <option [value]="capability" lang="en">{{ capability }}</option>
                }
              </select>
              <label for="model-max-output">{{ t("Maximum output tokens (optional)") }}</label>
              <input id="model-max-output" name="max_output_tokens" type="number" min="1" max="1000000" />
              <label for="model-evidence">{{ t("Public HTTPS capability evidence URL") }}</label>
              <input id="model-evidence" name="capability_source" type="url" maxlength="1024" />
              <label for="model-access-tier">{{ t("Verified access tier") }}</label>
              <select id="model-access-tier" name="access_tier">
                <option value="unknown">{{ t("Unknown (no automatic routing)") }}</option>
                <option value="standard">{{ t("Standard paid access") }}</option>
                <option value="free">{{ t("Free/contributor tier (explicit opt-in required)") }}</option>
              </select>
              <label for="model-input-price">{{ t("Input USD per million tokens (optional, with output price and dated evidence)") }}</label>
              <input id="model-input-price" name="input_price_usd_per_million" inputmode="decimal" pattern="[0-9]{1,5}(\\.[0-9]{1,4})?" maxlength="12" />
              <label for="model-output-price">{{ t("Output USD per million tokens (optional)") }}</label>
              <input id="model-output-price" name="output_price_usd_per_million" inputmode="decimal" pattern="[0-9]{1,5}(\\.[0-9]{1,4})?" maxlength="12" />
              <label for="model-pricing-source">{{ t("Public HTTPS pricing evidence URL") }}</label>
              <input id="model-pricing-source" name="pricing_source" type="url" maxlength="1024" />
              <label for="model-privacy-policy">{{ t("Public HTTPS data-use policy URL (required for free access)") }}</label>
              <input id="model-privacy-policy" name="privacy_policy_url" type="url" maxlength="1024" />
              <label for="model-enabled"><input id="model-enabled" name="enabled" type="checkbox" /> {{ t("Enable after reviewing evidence today") }}</label>
              <button type="submit" [disabled]="busy()">{{ t("Save model") }}</button>
            </form>
          }
        }
      </section>
      <section aria-labelledby="default-route-title">
        <h2 id="default-route-title">{{ t("System AI text default") }}</h2>
        <p>{{ t("Applies only when a project has no override and a job has no explicit model choice. Fallbacks are considered before the first provider request, never after a failed or uncertain attempt. Free/unverified models are not automatic.") }}</p>
        @if (routeState() === 'loading') { <p role="status">{{ t("Loading system routing.") }}</p> }
        @else if (routeState() === 'denied') { <p>{{ t("System routing is unavailable for this staff session.") }}</p> }
        @else {
          @if (systemRoute(); as policy) {
            <p role="status">{{ t("Current:") }} <span lang="">{{ modelName(policy.model_id) }}</span>{{ t("; revision") }} {{ policy.revision }}{{ t("; up to") }} {{ policy.max_output_tokens }} {{ t("tokens, USD") }} {{ policy.max_cost_usd }} {{ t("estimated and") }}
              {{ policy.timeout_seconds }} {{ t("seconds.") }} {{ policy.fallback_model_ids.length }} {{ t("preflight fallback(s).") }}</p>
            @if (confirmRemoveRoute()) {
              <p role="alert">{{ t("Remove the system default? Projects without an override will need explicit model selection.") }}</p>
              <button type="button" (click)="removeSystemRoute()" [disabled]="busy()">{{ t("Confirm removal") }}</button>
              <button type="button" (click)="confirmRemoveRoute.set(false)" [disabled]="busy()">{{ t("Cancel") }}</button>
            } @else {
              <button type="button" (click)="confirmRemoveRoute.set(true)" [disabled]="busy()">{{ t("Remove system default") }}</button>
            }
          } @else { <p>{{ t("No system AI model is chosen.") }}</p> }
          @if (standardModels().length) {
            <form (submit)="saveSystemRoute($event)">
              <label for="system-route-model">{{ t("Standard priced text model") }}</label>
              <select id="system-route-model" name="model_id" required (change)="selectRouteModel($event)">
                <option value="">{{ t("Choose a model") }}</option>
                @for (model of standardModels(); track model.id) {
                  <option [value]="model.id" lang="">{{ model.name }} — {{ model.identifier }}</option>
                }
              </select>
              <label for="system-route-account">{{ t("Platform account for this model") }}</label>
              <select id="system-route-account" name="account_id" required>
                <option value="">{{ t("Choose an account") }}</option>
                @for (account of routeAccounts(); track account.id) {
                  <option [value]="account.id" lang="">{{ account.label }}</option>
                }
              </select>
              <label for="system-route-fallbacks">{{ t("Same-provider fallback models (select up to two)") }}</label>
              <select id="system-route-fallbacks" name="fallback_model_ids" multiple size="3">
                @for (model of routeFallbacks(); track model.id) {
                  <option [value]="model.id" lang="">{{ model.name }} — {{ model.identifier }}</option>
                }
              </select>
              <label for="system-route-tokens">{{ t("Maximum output tokens (1–256)") }}</label>
              <input id="system-route-tokens" name="max_output_tokens" type="number" min="1" max="256" value="100" required />
              <label for="system-route-cost">{{ t("Maximum estimated USD cost per request (up to 100)") }}</label>
              <input id="system-route-cost" name="max_cost_usd" inputmode="decimal" pattern="[0-9]{1,3}(\\.[0-9]{1,6})?" maxlength="10" required />
              <label for="system-route-timeout">{{ t("Request timeout in seconds (1–30)") }}</label>
              <input id="system-route-timeout" name="timeout_seconds" type="number" min="1" max="30" value="30" required />
              <button type="submit" [disabled]="busy()">{{ t("Save system default") }}</button>
            </form>
          }
        }
      </section>
    </section>
  `,
})
export class ProviderSettings implements OnInit {
  readonly productLanguage = signal<'en' | 'tr'>('en');
  readonly uiLanguage = computed(() => draftProductLanguage(this.productLanguage()));
  private readonly destroyRef = inject(DestroyRef);
  textLanguage(text: string) {
    return Object.hasOwn(providerSettingsTurkish, text) || this.messageDraft()?.message === text ? this.uiLanguage() : 'en';
  }
  t(text: string) {
    if (this.textLanguage(text) !== 'tr') return text;
    const draft = this.messageDraft();
    return draft?.message === text ? draft.translation : providerSettingsTurkish[text];
  }
  private setDraftMessage(message: string, translation: string) {
    this.messageDraft.set({ message, translation });
    this.message.set(message);
  }
  readonly providers = signal<Provider[]>([]);
  readonly accounts = signal<Account[]>([]);
  readonly loading = signal(true);
  readonly denied = signal(false);
  readonly busy = signal(false);
  readonly hasMore = signal(false);
  readonly message = signal('');
  private readonly messageDraft = signal<{ message: string; translation: string } | null>(null);
  readonly error = signal('');
  readonly confirmRevoke = signal<number | null>(null);
  readonly googleState = signal<'loading' | 'denied' | 'unconfigured' | 'active' | 'revoked' | 'environment_reference'>('loading');
  readonly googleRedirect = signal('');
  readonly confirmGoogleRevoke = signal(false);
  readonly analyticsState = signal<'loading' | 'denied' | 'unconfigured' | 'active' | 'revoked' | 'environment_reference'>('loading');
  readonly analyticsRedirect = signal('');
  readonly confirmAnalyticsRevoke = signal(false);
  readonly businessState = signal<'loading' | 'denied' | 'unconfigured' | 'active' | 'revoked' | 'environment_reference'>('loading');
  readonly businessRedirect = signal('');
  readonly confirmBusinessRevoke = signal(false);
  readonly paddleEnvironments = ['sandbox', 'live'] as const;
  readonly paddleStates = signal<Record<'sandbox' | 'live', 'loading' | 'denied' | 'unconfigured' | 'active' | 'revoked'>>({ sandbox: 'loading', live: 'loading' });
  readonly noticeInspector = viewChild(StaffNoticeInspector);
  readonly receiptInspector = viewChild(StaffReceiptInspector);
   readonly feedbackInspector = viewChild(StaffFeedbackInspector);
  readonly paddleProducts = signal<Record<'sandbox' | 'live', string>>({ sandbox: '', live: '' });
  readonly paddlePrices = signal<Record<'sandbox' | 'live', string>>({ sandbox: '', live: '' });
  readonly confirmPaddleRevoke = signal<'sandbox' | 'live' | null>(null);
  readonly performanceState = signal<'loading' | 'denied' | 'unconfigured' | 'active' | 'revoked' | 'environment_reference'>('loading');
  readonly confirmPerformanceRevoke = signal(false);
  readonly models = signal<Model[]>([]);
  readonly capabilityChoices = signal<string[]>([]);
  readonly modelLoading = signal(true);
  readonly modelDenied = signal(false);
  readonly modelHasMore = signal(false);
  readonly routeState = signal<'loading' | 'denied' | 'ready'>('loading');
  readonly systemRoute = signal<AIRoutingPolicyInfo | null>(null);
  readonly routeModelId = signal<number | null>(null);
  readonly confirmRemoveRoute = signal(false);

  constructor(private readonly api: AccountApi, title: Title) {
    effect(() => title.setTitle(`${this.t('Provider credentials')} — OrganicSEOOps`));
  }

  ngOnInit() { void this.loadProductLanguage(); void this.load(); void this.loadGoogle(); void this.loadGoogle('analytics'); void this.loadGoogle('business');
    void this.loadPaddle('sandbox'); void this.loadPaddle('live');
    void this.loadPerformance(); void this.loadModels(); void this.loadRouting(); }

  private async loadProductLanguage() {
    try {
      const result = await this.api.productLanguage();
      if (!this.destroyRef.destroyed && result.status === 200 && isProductLanguageResult(result.body)) {
        this.productLanguage.set(result.body['language']);
      }
    } catch { /* Keep English when the private preference is unavailable. */ }
  }

  async retryUnknownNotice(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form);
    const id = Number(fields.get('notice_id'));
    if (!Number.isSafeInteger(id) || id <= 0 || fields.get('acknowledged') !== 'on') return;
    this.noticeInspector()?.clear();
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.retryPlatformNotice(id, String(fields.get('reason')).trim());
      if (response.status !== 202 || response.body['queued'] !== true) throw new Error();
      this.setDraftMessage(`Notice ${id} queued for one reviewed reissue. A duplicate remains possible.`,
        `Bildirim ${id}, incelenmiş tek bir yeniden gönderim için kuyruğa alındı. Yinelenen gönderim hâlâ mümkündür.`);
      form.reset();
    } catch { this.error.set('Notice reissue was not confirmed. Check staff MFA, recipient and trial state.'); }
    finally { this.busy.set(false); }
  }

  async clearEmailSuppression(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form);
    const id = Number(fields.get('suppression_id'));
    if (!Number.isSafeInteger(id) || id <= 0 || fields.get('confirmed') !== 'on') return;
    this.feedbackInspector()?.clear();
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.clearPlatformEmailSuppression(id, String(fields.get('reason')).trim());
      if (response.status !== 200 || response.body['cleared'] !== true) throw new Error();
      this.setDraftMessage(`Suppression ${id} cleared after review. A new provider failure may suppress it again.`,
        `Engelleme ${id}, incelemeden sonra kaldırıldı. Yeni bir sağlayıcı hatası yeniden engellemeye neden olabilir.`);
      form.reset();
    } catch { this.error.set('Email suppression could not be cleared. Check staff MFA and current status.'); }
    finally { this.feedbackInspector()?.clear(); this.busy.set(false); }
  }

  async loadPaddle(environment: 'sandbox' | 'live') {
    try {
      const result = await this.api.platformPaddleSeller(environment);
      const row = result.body;
      if (result.status !== 200 || row['environment'] !== environment
        || typeof row['state'] !== 'string' || !['active', 'revoked', 'unconfigured'].includes(row['state'])
        || typeof row['product_id'] !== 'string' || typeof row['price_id'] !== 'string'
        || row['catalog_verified'] !== false) throw new Error();
      this.paddleStates.update((states) => ({ ...states, [environment]: row['state'] as 'active' | 'revoked' | 'unconfigured' }));
      this.paddleProducts.update((values) => ({ ...values, [environment]: row['product_id'] as string }));
      this.paddlePrices.update((values) => ({ ...values, [environment]: row['price_id'] as string }));
    } catch {
      this.paddleStates.update((states) => ({ ...states, [environment]: 'denied' }));
      this.paddleProducts.update((values) => ({ ...values, [environment]: '' }));
      this.paddlePrices.update((values) => ({ ...values, [environment]: '' }));
    }
  }

  async savePaddle(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form);
    const environment = fields.get('environment');
    if (environment !== 'sandbox' && environment !== 'live') return;
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.setPlatformPaddleSeller(environment, {
        api_key: String(fields.get('api_key')), webhook_secret: String(fields.get('webhook_secret')),
        client_token: String(fields.get('client_token')),
        product_id: String(fields.get('product_id')), price_id: String(fields.get('price_id')),
        currency: 'USD', amount: '14900', interval: 'month', frequency: 1,
      });
      if (response.status !== 200 || response.body['configured'] !== true) throw new Error();
      this.setDraftMessage(`${environment} seller settings stored. Catalog remains unverified; checkout is unavailable.`,
        `${environment} satıcı ayarları kaydedildi. Katalog hâlâ doğrulanmamıştır; ödeme kullanılamaz.`);
      await this.loadPaddle(environment);
    } catch { this.error.set('Seller settings were not saved. Check MFA, catalog IDs, encryption and linked subscriptions.'); }
    finally { form.reset(); this.busy.set(false); }
  }

  async revokePaddle(environment: 'sandbox' | 'live') {
    if (this.confirmPaddleRevoke() !== environment || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.revokePlatformPaddleSeller(environment);
      if (response.status !== 200 || response.body['revoked'] !== true) throw new Error();
      this.confirmPaddleRevoke.set(null);
      this.setDraftMessage(`${environment} seller secrets removed.`,
        `${environment} satıcı sırları kaldırıldı.`);
      await this.loadPaddle(environment);
    } catch { this.error.set('Seller revocation could not be confirmed. Refresh and check linked subscriptions.'); }
    finally { this.busy.set(false); }
  }

  async rotatePaddleApiKey(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form);
    const environment = fields.get('environment');
    if (environment !== 'sandbox' && environment !== 'live') return;
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.rotatePlatformPaddleApiKey(environment, String(fields.get('api_key')));
      if (response.status !== 200 || response.body['rotated'] !== true) throw new Error();
      this.setDraftMessage(`${environment} seller API key rotated; webhook secret and catalog remain unchanged.`,
        `${environment} satıcı API anahtarı yenilendi; webhook sırrı ve katalog değişmedi.`);
      await this.loadPaddle(environment);
    } catch { this.error.set('Seller API key rotation was not confirmed. Check staff MFA, environment and key format.'); }
    finally { form.reset(); this.busy.set(false); }
  }

  async retryPaddleReceipt(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form);
    const id = Number(fields.get('receipt_id'));
    if (!Number.isSafeInteger(id) || id <= 0) return;
    this.receiptInspector()?.clear();
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.retryPlatformPaddleReceipt(id, String(fields.get('reason')).trim());
      if (response.status !== 202 || response.body['queued'] !== true) throw new Error();
      this.setDraftMessage(`Billing receipt ${id} queued for current-provider reconciliation; status is not yet changed.`,
        `Faturalama alındısı ${id}, mevcut sağlayıcıyla mutabakat için kuyruğa alındı; durum henüz değişmedi.`);
      form.reset();
    } catch { this.error.set('Receipt retry could not be confirmed. Check current MFA, receipt status and age.'); }
    finally { this.receiptInspector()?.clear(); this.busy.set(false); }
  }

  modelName(id: number) { return this.models().find((row) => row.id === id)?.name || this.t('Unavailable model'); }
  standardModels() { return this.models().filter((row) => row.enabled && row.access_tier === 'standard'
    && row.input_price_usd_per_million !== null && row.output_price_usd_per_million !== null
    && row.capabilities.includes('text_generation')); }
  routeAccounts() {
    const model = this.models().find((row) => row.id === this.routeModelId());
    return model ? this.accounts().filter((row) => row.provider_id === model.provider_id && row.state === 'active') : [];
  }
  routeFallbacks() {
    const model = this.models().find((row) => row.id === this.routeModelId());
    return model ? this.standardModels().filter((row) => row.provider_id === model.provider_id && row.id !== model.id) : [];
  }
  selectRouteModel(event: Event) { this.routeModelId.set(Number((event.target as HTMLSelectElement).value) || null); }

  async loadRouting() {
    try {
      const response = await this.api.platformAIRouting();
      if (response.status !== 200 || (response.body['policy'] !== null && !readAIRoutingPolicy(response.body['policy']))) {
        this.routeState.set('denied'); this.systemRoute.set(null); return;
      }
      this.systemRoute.set(readAIRoutingPolicy(response.body['policy']));
      this.routeState.set('ready');
    } catch { this.routeState.set('denied'); this.systemRoute.set(null); }
  }

  async saveSystemRoute(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form);
    const fallbackIds = fields.getAll('fallback_model_ids').map(Number);
    if (fallbackIds.length > 2 || !this.routeAccounts().some((row) => row.id === Number(fields.get('account_id')))) {
      this.error.set('Choose one matching platform account and at most two same-provider fallbacks.'); return;
    }
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.savePlatformAIRouting({
        model_id: Number(fields.get('model_id')), account_id: Number(fields.get('account_id')),
        fallback_model_ids: fallbackIds, max_output_tokens: Number(fields.get('max_output_tokens')),
        max_cost_usd: String(fields.get('max_cost_usd')), timeout_seconds: Number(fields.get('timeout_seconds')),
        revision: this.systemRoute()?.revision ?? 0, policy_id: this.systemRoute()?.id ?? null,
      });
      if (response.status !== 200 || !readAIRoutingPolicy(response.body['policy'])) throw new Error();
      form.reset(); this.routeModelId.set(null);
      this.message.set('System AI text default saved; jobs still recheck current credentials and budgets.');
      await this.loadRouting();
    } catch { this.error.set('System route was not saved. Refresh and check staff access, model, fallback and cost.'); }
    finally { this.busy.set(false); }
  }

  async removeSystemRoute() {
    const policy = this.systemRoute();
    if (!policy || !this.confirmRemoveRoute() || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {
      const response = await this.api.removePlatformAIRouting(policy.revision, policy.id);
      if (response.status !== 200 || response.body['removed'] !== true) throw new Error();
      this.systemRoute.set(null); this.confirmRemoveRoute.set(false);
      this.message.set('System AI text default removed. Explicit project settings remain separate.');
    } catch { this.error.set('Removal could not be confirmed. Refresh routing before retrying.'); }
    finally { this.busy.set(false); }
  }

  async loadModels() {
    this.modelLoading.set(true);
    try {
      const response = await this.api.platformModels();
      if (response.status === 200 && Array.isArray(response.body['models'])
        && response.body['models'].every(isModel) && Array.isArray(response.body['capability_choices'])
        && response.body['capability_choices'].every((choice: unknown) => typeof choice === 'string')
        && typeof response.body['has_more'] === 'boolean') {
        this.models.set(response.body['models'] as Model[]);
        this.capabilityChoices.set(response.body['capability_choices'] as string[]);
        this.modelHasMore.set(response.body['has_more']);
        this.modelDenied.set(false);
      } else {
        this.models.set([]);
        this.modelDenied.set(true);
      }
    } catch { this.models.set([]); this.modelDenied.set(true); }
    finally { this.modelLoading.set(false); }
  }

  async saveModel(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form);
    const limit = String(fields.get('max_output_tokens'));
    const inputPrice = String(fields.get('input_price_usd_per_million')).trim();
    const outputPrice = String(fields.get('output_price_usd_per_million')).trim();
    if (Boolean(inputPrice) !== Boolean(outputPrice) || (inputPrice && !fields.get('pricing_source'))
      || (fields.get('access_tier') === 'free' && !fields.get('privacy_policy_url'))) {
      this.error.set('Both model prices need dated public evidence; free access requires a data-use policy URL.'); return;
    }
    this.busy.set(true);
    this.error.set('');
    try {
      const response = await this.api.savePlatformModel({
        provider_id: Number(fields.get('provider_id')), identifier: String(fields.get('identifier')),
        name: String(fields.get('name')), capabilities: fields.getAll('capabilities').map(String),
        max_output_tokens: limit ? Number(limit) : null, capability_source: String(fields.get('capability_source')),
        enabled: fields.has('enabled'), input_price_usd_per_million: inputPrice || null,
        output_price_usd_per_million: outputPrice || null,
        pricing_source: String(fields.get('pricing_source')), access_tier: String(fields.get('access_tier')),
        privacy_policy_url: String(fields.get('privacy_policy_url')),
      });
      if (response.status !== 200) throw new Error();
      form.reset();
      this.message.set('Model configuration saved. Capability evidence was dated today.');
      await this.loadModels();
    } catch { this.error.set('Model was not saved. Check staff access, capabilities, evidence URL and output limit.'); }
    finally { this.busy.set(false); }
  }

  async loadPerformance() {
    try {
      const response = await this.api.platformPerformanceKey();
      const state = response.body['state'];
      if (response.status === 401 || response.status === 403) this.performanceState.set('denied');
      else if (response.status === 200 && typeof state === 'string' && ['unconfigured', 'active', 'revoked', 'environment_reference'].includes(state)) {
        this.performanceState.set(state as 'unconfigured' | 'active' | 'revoked' | 'environment_reference');
      } else this.performanceState.set('denied');
    } catch { this.performanceState.set('denied'); }
  }

  async savePerformance(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const key = String(new FormData(form).get('api_key'));
    this.busy.set(true);
    this.error.set('');
    try {
      const response = await this.api.setPlatformPerformanceKey(key);
      if (response.status !== 200) throw new Error();
      this.message.set('Performance key saved.');
      form.reset();
      await this.loadPerformance();
    } catch { this.error.set('Performance key was not saved. Check staff access and encryption configuration.'); }
    finally {
      const secret = form.elements.namedItem('api_key') as HTMLInputElement | null;
      if (secret) secret.value = '';
      this.busy.set(false);
    }
  }

  async revokePerformance() {
    if (!this.confirmPerformanceRevoke() || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    try {
      const response = await this.api.revokePlatformPerformanceKey();
      if (response.status !== 200) throw new Error();
      this.confirmPerformanceRevoke.set(false);
      this.message.set('Performance key revoked. Future performance requests cannot use it.');
      await this.loadPerformance();
    } catch { this.error.set('Performance key revocation could not be confirmed. Refresh before retrying.'); }
    finally { this.busy.set(false); }
  }

  async loadGoogle(kind: 'search' | 'analytics' | 'business' = 'search') {
    try {
      const result = kind === 'business' ? await this.api.platformGoogleBusinessApp()
        : kind === 'analytics' ? await this.api.platformGoogleAnalyticsApp() : await this.api.platformGoogleOAuthApp();
      const state = result.body['state'];
      const redirect = result.body['redirect_uri'];
      const status = kind === 'business' ? this.businessState : kind === 'analytics' ? this.analyticsState : this.googleState;
      const callback = kind === 'business' ? this.businessRedirect : kind === 'analytics' ? this.analyticsRedirect : this.googleRedirect;
      if (result.status === 401 || result.status === 403) status.set('denied');
      else if (result.status === 200 && typeof state === 'string' && ['active', 'revoked', 'unconfigured', 'environment_reference'].includes(state)
        && typeof redirect === 'string' && redirect.length <= 512) {
        status.set(state as 'active' | 'revoked' | 'unconfigured' | 'environment_reference');
        callback.set(redirect);
      } else status.set('denied');
    } catch { (kind === 'business' ? this.businessState : kind === 'analytics' ? this.analyticsState : this.googleState).set('denied'); }
  }

  async saveGoogle(event: SubmitEvent, kind: 'search' | 'analytics' | 'business' = 'search') {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const fields = new FormData(form);
    this.busy.set(true);
    this.error.set('');
    try {
      const result = kind === 'business'
        ? await this.api.platformGoogleBusinessApp('POST', { client_id: String(fields.get('client_id')),
          client_secret: String(fields.get('client_secret')), redirect_uri: String(fields.get('redirect_uri')) })
        : kind === 'analytics'
        ? await this.api.setPlatformGoogleAnalyticsApp(String(fields.get('client_id')),
          String(fields.get('client_secret')), String(fields.get('redirect_uri')))
        : await this.api.setPlatformGoogleOAuthApp(String(fields.get('client_id')),
          String(fields.get('client_secret')), String(fields.get('redirect_uri')));
      if (result.status !== 200) throw new Error();
      this.message.set(`${kind === 'business' ? 'Business Profile' : kind === 'analytics' ? 'Analytics' : 'Search Console'} application saved. Existing customer grants remain separate.`);
      form.reset();
      await this.loadGoogle(kind);
    } catch { this.error.set('Google application was not saved. Check the exact callback, staff access and pending grants.'); }
    finally {
      const secret = form.elements.namedItem('client_secret') as HTMLInputElement | null;
      if (secret) secret.value = '';
      this.busy.set(false);
    }
  }

  async revokeGoogle(kind: 'search' | 'analytics' | 'business' = 'search') {
    const confirmation = kind === 'business' ? this.confirmBusinessRevoke : kind === 'analytics' ? this.confirmAnalyticsRevoke : this.confirmGoogleRevoke;
    if (!confirmation() || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    try {
      const result = kind === 'business' ? await this.api.platformGoogleBusinessApp('DELETE') : kind === 'analytics'
        ? await this.api.revokePlatformGoogleAnalyticsApp() : await this.api.revokePlatformGoogleOAuthApp();
      if (result.status !== 200) throw new Error();
      confirmation.set(false);
      this.message.set(`${kind === 'business' ? 'Business Profile' : kind === 'analytics' ? 'Analytics' : 'Search Console'} application revoked. No new project consent can begin.`);
      await this.loadGoogle(kind);
    } catch { this.error.set('Google revocation could not be confirmed. Disconnect pending grants and refresh.'); }
    finally { this.busy.set(false); }
  }

  activeAccounts() { return this.accounts().filter((account) => account.state === 'active'); }

  providerName(id: number) { return this.providers().find((provider) => provider.id === id)?.name || this.t('Unknown provider'); }

  async load() {
    this.loading.set(true);
    this.denied.set(true);
    this.providers.set([]);
    this.accounts.set([]);
    try {
      const response = await this.api.platformProviders();
      if (response.status === 401 || response.status === 403) {
        this.denied.set(true);
        this.providers.set([]);
        this.accounts.set([]);
      } else if (response.status === 200 && Array.isArray(response.body['providers'])
        && response.body['providers'].every(isProvider) && Array.isArray(response.body['accounts'])
        && response.body['accounts'].every(isAccount) && typeof response.body['has_more'] === 'boolean') {
        this.denied.set(false);
        this.providers.set(response.body['providers'] as Provider[]);
        this.accounts.set(response.body['accounts'] as Account[]);
        this.hasMore.set(response.body['has_more']);
        this.error.set('');
      } else this.error.set('Provider settings are unavailable. Retry the load.');
    } catch {
      this.error.set('Provider settings are unavailable. Retry the load.');
    } finally {
      this.loading.set(false);
    }
  }

  async createProvider(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const data = new FormData(form);
    await this.submit(() => this.api.addPlatformProvider(String(data.get('key')), String(data.get('name')),
      String(data.get('kind')), String(data.get('base_url'))), form, 'Provider added.');
  }

  async createAccount(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const data = new FormData(form);
    const secret = String(data.get('secret'));
    await this.submit(() => this.api.addPlatformAccount(Number(data.get('provider_id')),
      String(data.get('label')), secret), form, 'Credential saved.');
  }

  async rotate(event: SubmitEvent) {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    if (!form.reportValidity() || this.busy()) return;
    const data = new FormData(form);
    const account = this.activeAccounts().find((row) => row.id === Number(data.get('account_id')));
    if (!account) { this.error.set('Choose an available account.'); return; }
    const secret = String(data.get('secret'));
    await this.submit(() => this.api.setPlatformCredential(account.provider_id, account.id, secret),
      form, 'Credential replaced.');
  }

  async revoke(account: Account) {
    if (this.busy() || this.confirmRevoke() !== account.id) return;
    this.busy.set(true);
    this.error.set('');
    try {
      const response = await this.api.revokePlatformCredential(account.provider_id, account.id);
      if (response.status !== 200) throw new Error();
      this.confirmRevoke.set(null);
      this.message.set('Provider account revoked. Existing provider keys are no longer usable here.');
      await this.load();
    } catch { this.error.set('Revocation could not be confirmed. Refresh before trying again.'); }
    finally { this.busy.set(false); }
  }

  private async submit(request: () => ReturnType<AccountApi['platformProviders']>, form: HTMLFormElement, success: string) {
    this.busy.set(true);
    this.error.set('');
    try {
      const response = await request();
      if (response.status !== 200 && response.status !== 201) throw new Error();
      form.reset();
      this.message.set(success);
      await this.load();
    } catch { this.error.set('Provider settings were not saved. Check the fields, staff access and encryption configuration.'); }
    finally {
      const field = form.elements.namedItem('secret') as HTMLInputElement | null;
      if (field) field.value = '';
      this.busy.set(false);
    }
  }
}

function isProvider(value: unknown): value is Provider {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0 && typeof row['key'] === 'string'
    && typeof row['name'] === 'string' && typeof row['kind'] === 'string' && ['openai', 'openai_compatible'].includes(row['kind'])
    && typeof row['enabled'] === 'boolean';
}

function isAccount(value: unknown): value is Account {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && Number.isSafeInteger(row['provider_id']) && Number(row['provider_id']) > 0
    && typeof row['label'] === 'string' && typeof row['state'] === 'string' && ['active', 'revoked'].includes(row['state'])
    && typeof row['stored'] === 'boolean';
}

function isModel(value: unknown): value is Model {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row['id']) && Number(row['id']) > 0
    && Number.isSafeInteger(row['provider_id']) && Number(row['provider_id']) > 0
    && typeof row['identifier'] === 'string' && typeof row['name'] === 'string'
    && Array.isArray(row['capabilities']) && row['capabilities'].every((item: unknown) => typeof item === 'string')
    && typeof row['enabled'] === 'boolean' && typeof row['capability_source'] === 'string'
    && (row['max_output_tokens'] === null || Number.isSafeInteger(row['max_output_tokens']))
    && (row['input_price_usd_per_million'] === null || typeof row['input_price_usd_per_million'] === 'string')
    && (row['output_price_usd_per_million'] === null || typeof row['output_price_usd_per_million'] === 'string')
    && typeof row['pricing_source'] === 'string' && typeof row['privacy_policy_url'] === 'string'
    && typeof row['access_tier'] === 'string' && ['unknown', 'standard', 'free'].includes(row['access_tier']);
}
