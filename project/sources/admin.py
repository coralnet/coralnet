from django.contrib import admin
from guardian.admin import GuardedModelAdmin

from .models import Source


@admin.register(Source)
class SourceAdmin(GuardedModelAdmin):
    list_display = ('name', 'visibility', 'create_date')
