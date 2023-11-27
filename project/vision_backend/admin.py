from django.contrib import admin
from .models import Classifier, BatchJob


@admin.register(BatchJob)
class BatchJobAdmin(admin.ModelAdmin):
    list_display = (
        'create_date', 'status', 'batch_token', 'internal_job', 'spec_level')


@admin.register(Classifier)
class ClassifierAdmin(admin.ModelAdmin):
    list_display = ('status', 'source', 'accuracy', 'create_date')
