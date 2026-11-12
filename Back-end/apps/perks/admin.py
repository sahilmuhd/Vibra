from django.contrib import admin

from .models import DailyCheckin, StoreItem, TaskClaim, UserItem


@admin.register(StoreItem)
class StoreItemAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "key", "price", "days", "is_active")
    list_filter = ("kind", "is_active")
    list_editable = ("price", "days", "is_active")


admin.site.register(UserItem)
admin.site.register(DailyCheckin)
admin.site.register(TaskClaim)
