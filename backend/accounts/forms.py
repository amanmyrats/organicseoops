from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from .models import User


class UserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email",)


class UserEditForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"
        exclude = ("product_language",)
