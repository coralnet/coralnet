from django.contrib import admin

from .models import BatchJob


@admin.register(BatchJob)
class BatchJobAdmin(admin.ModelAdmin):
    list_display = (
        'create_date', 'status', 'batch_token', 'internal_job', 'spec_level')
