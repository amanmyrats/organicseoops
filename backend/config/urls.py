from django.contrib import admin
from django.urls import include, path
from allauth.account.decorators import secure_admin_login

from accounts.api import (change_password, logout_all, platform_email_deliveries, product_language,
                          personal_account_export, personal_account_close, personal_account_closure_status,
                          resend_verification, verification_status)

from .views import health
from accounts.mail_api import platform_inspect_account_mail
from tenancy.staff_receipt_api import platform_inspect_billing_receipt

admin.site.login = secure_admin_login(admin.site.login)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("_allauth/", include("allauth.headless.urls")),
    path("api/account/verification-status/", verification_status, name="verification-status"),
    path("api/account/resend-verification/", resend_verification, name="resend-verification"),
    path("api/account/change-password/", change_password, name="change-password"),
    path("api/account/logout-all/", logout_all, name="logout-all"),
    path("api/account/export/", personal_account_export, name="personal-account-export"),
    path("api/account/closure-status/", personal_account_closure_status, name="personal-account-closure-status"),
    path("api/account/close/", personal_account_close, name="personal-account-close"),
    path("api/account/product-language/", product_language, name="product-language"),
    path("api/platform/email/deliveries/", platform_email_deliveries, name="platform-email-deliveries"),
    path("api/platform/email/deliveries/inspect/", platform_inspect_account_mail, name="platform-inspect-account-mail"),
    path("api/platform/billing/paddle/receipts/inspect/", platform_inspect_billing_receipt, name="platform-inspect-billing-receipt"),
    path("api/", include("tenancy.urls")),
    path("api/", include("providers.urls")),
    path("api/", include("integrations.urls")),
    path("api/", include("jobs.urls")),
    path("api/health/", health, name="health"),
]
