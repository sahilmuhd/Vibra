from django.contrib import admin

from .models import Gift, GiftEvent, HandRaise, Message, Room, Seat

admin.site.register(Room)
admin.site.register(Seat)
admin.site.register(HandRaise)
admin.site.register(Message)
admin.site.register(Gift)
admin.site.register(GiftEvent)
