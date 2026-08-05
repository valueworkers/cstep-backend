from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Q

from .models import User


class TestOrOfficialEmailFilter(admin.SimpleListFilter):
    title = "email category"
    parameter_name = "email_category"

    OFFICIAL_Q = (
        Q(email__iendswith="@admin.com")
        | Q(email__iendswith="@cstep.in")
        | Q(email__iexact="event.admin@test.com")
    )

    def lookups(self, request, model_admin):
        return (
            ("official", "Official (@admin.com / @cstep.in / event.admin@test.com)"),
            ("non_official", "Non-official (safe to clean up)"),
        )

    def queryset(self, request, queryset):
        if self.value() == "official":
            return queryset.filter(self.OFFICIAL_Q)
        if self.value() == "non_official":
            return queryset.exclude(self.OFFICIAL_Q)
        return queryset


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-created_at",)

    list_display = (
        "id",
        "email",
        "phone_number",
        "first_name",
        "last_name",
        "role",
        "gender",
        "city",
        "org_type",
        "org_name",
        "phone_verified",
        "email_verified",
        "is_active",
        "is_staff",
        "created_at",
    )

    list_filter = (
        "role",
        "gender",
        "org_type",
        "country",
        "phone_verified",
        "email_verified",
        "is_active",
        "is_staff",
        "is_superuser",
        TestOrOfficialEmailFilter,
    )

    actions = ["delete_non_official_users"]

    @admin.action(description="Delete non-official / test users")
    def delete_non_official_users(self, request, queryset):
        non_official = queryset.exclude(TestOrOfficialEmailFilter.OFFICIAL_Q).exclude(
            is_superuser=True
        )
        count = non_official.count()
        non_official.delete()
        self.message_user(request, f"Deleted {count} non-official user(s).")

    search_fields = (
        "email",
        "phone_number",
        "first_name",
        "middle_name",
        "last_name",
        "org_name",
        "city",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "last_login",
    )

    fieldsets = (
        (
            "Personal Information",
            {
                "fields": (
                    "salutation",
                    "first_name",
                    "middle_name",
                    "last_name",
                    "gender",
                )
            },
        ),
        (
            "Contact Information",
            {
                "fields": (
                    "email",
                    "country_code",
                    "phone_number",
                    "city",
                    "state",
                    "country",
                )
            },
        ),
        (
            "Organisation",
            {
                "fields": (
                    "designation",
                    "org_type",
                    "org_name",
                    "motivation",
                )
            },
        ),
        (
            "Role & Permissions",
            {
                "fields": (
                    "role",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Verification",
            {
                "fields": (
                    "phone_verified",
                    "email_verified",
                )
            },
        ),
        (
            "Authentication",
            {
                "fields": (
                    "password",
                    "last_login",
                )
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "salutation",
                    "first_name",
                    "middle_name",
                    "last_name",
                    "email",
                    "country_code",
                    "phone_number",
                    "city",
                    "state",
                    "country",
                    "designation",
                    "org_type",
                    "org_name",
                    "gender",
                    "role",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )