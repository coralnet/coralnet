from django.contrib import admin
from .models import Classifier, BatchJob


@admin.register(BatchJob)
class BatchJobAdmin(admin.ModelAdmin):
    list_display = ('create_date', 'status', 'batch_token', 'job_token')


@admin.register(Classifier)
class ClassifierAdmin(admin.ModelAdmin):
    list_display = ('valid', 'source', 'accuracy', 'create_date')
