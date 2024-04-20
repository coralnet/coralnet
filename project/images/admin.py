from django.contrib import admin

from .models import Image, Metadata


@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = ('original_file', 'source', 'metadata')


@admin.register(Metadata)
class MetadataAdmin(admin.ModelAdmin):
    list_display = ('name', 'aux1', 'aux2', 'aux3', 'aux4', 'aux5')
