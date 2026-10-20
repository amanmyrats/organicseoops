from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from allauth.mfa.models import Authenticator
from django.urls import path

from .forms import UserCreationForm, UserEditForm
from .models import User
from . import staff_mail_admin

admin.site.unregister(Authenticator)


@admin.register(Authenticator)
class AuthenticatorAdmin(admin.ModelAdmin):
    fields = ("user", "type", "created_at", "last_used_at")
    readonly_fields = fields
    list_display = ("user", "type", "created_at", "last_used_at")
    list_filter = ("type", "created_at", "last_used_at")
    search_fields = ("user__email",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserEditForm
    add_form = UserCreationForm
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active", "closed_at")
    search_fields = ("email", "first_name", "last_name")
    readonly_fields = ("last_login", "date_joined")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "usable_password", "password1", "password2")}),
    )

    def get_urls(self):
        from .identity_admin import identity_cleanup_view
        return [path("identity-cleanup/", self.admin_site.admin_view(
            lambda request: identity_cleanup_view(self.admin_site, request)),
            name="accounts_user_identity_cleanup")] + super().get_urls()

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return super().get_fieldsets(request, obj)
        return tuple((name, {**options, "fields": tuple(field for field in options["fields"] if field != "password")})
                     for name, options in self.fieldsets)

    def has_change_permission(self, request, obj=None):
        # Account status must use the audited suspension service; direct staff edits
        # can remove the last active owner or escalate platform permissions.
        return bool(obj is None and request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)
