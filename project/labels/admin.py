from django.contrib import admin
from .models import LabelGroup, LocalLabel, Label, LabelSet


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ('name', 'default_code', 'group', 'create_date')


@admin.register(LocalLabel)
class LocalLabelAdmin(admin.ModelAdmin):
    list_display = ('labelset', 'name', 'code')


@admin.register(LabelGroup)
class LabelGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')


@admin.register(LabelSet)
class LabelSetAdmin(admin.ModelAdmin):
    pass
