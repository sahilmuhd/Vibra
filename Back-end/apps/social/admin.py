from django.contrib import admin

from .models import Bond, BondRequest, Family, FamilyMember, ScheduledRoom


class MemberInline(admin.TabularInline):
    model = FamilyMember
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ["name", "tag", "owner", "created_at"]
    search_fields = ["name", "tag"]
    raw_id_fields = ["owner"]
    inlines = [MemberInline]


@admin.register(Bond)
class BondAdmin(admin.ModelAdmin):
    list_display = ["user_a", "user_b", "kind", "created_at"]
    raw_id_fields = ["user_a", "user_b"]


@admin.register(BondRequest)
class BondRequestAdmin(admin.ModelAdmin):
    list_display = ["from_user", "to_user", "kind", "cost", "status", "created_at"]
    list_filter = ["status", "kind"]
    raw_id_fields = ["from_user", "to_user"]


@admin.register(ScheduledRoom)
class ScheduledRoomAdmin(admin.ModelAdmin):
    list_display = ["title", "host", "starts_at", "cancelled", "room"]
    raw_id_fields = ["host", "room"]
