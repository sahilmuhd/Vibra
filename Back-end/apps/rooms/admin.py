from django.contrib import admin

from .models import (
    Gift, GiftEvent, HandRaise, Message, Report, Room, RoomBan, RoomModerator, RoomParticipant, Seat,
)

admin.site.register(Room)
admin.site.register(Seat)
admin.site.register(HandRaise)
admin.site.register(RoomParticipant)
admin.site.register(Message)
admin.site.register(Gift)
admin.site.register(GiftEvent)
admin.site.register(RoomBan)
admin.site.register(RoomModerator)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "reason", "reporter", "reported_user", "room", "is_resolved", "created_at")
    list_filter = ("is_resolved", "reason")
    actions = ["mark_resolved"]

    @admin.action(description="Mark selected reports as resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(is_resolved=True)
