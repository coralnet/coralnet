from django.contrib import admin
from .models import Classifier


@admin.register(Classifier)
class ClassifierAdmin(admin.ModelAdmin):
    list_display = ('status', 'source', 'accuracy', 'create_date')
