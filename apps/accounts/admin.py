from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    AccessPermission,
    APIKey,
    Invitation,
    LoginAttempt,
    Membership,
    PersonalPreference,
    Role,
    SecurityAuditEvent,
    User,
    UserSession,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["email"]
    list_display = ["email", "is_staff", "is_active", "created_at"]
    search_fields = ["email"]
    readonly_fields = ["created_at", "updated_at", "last_login"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )


admin.site.register(AccessPermission)
admin.site.register(Role)
admin.site.register(Membership)
admin.site.register(Invitation)
admin.site.register(UserSession)
admin.site.register(LoginAttempt)
admin.site.register(PersonalPreference)
admin.site.register(APIKey)
admin.site.register(SecurityAuditEvent)
