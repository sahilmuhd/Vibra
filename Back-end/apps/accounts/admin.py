from django.contrib import admin

from .models import Block, Follow, Profile

admin.site.register(Profile)
admin.site.register(Follow)
admin.site.register(Block)
