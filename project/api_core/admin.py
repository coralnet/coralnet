from django.contrib import admin

from .models import UserApiLimits


@admin.register(UserApiLimits)
class UserApiLimitsAdmin(admin.ModelAdmin):
    pass
