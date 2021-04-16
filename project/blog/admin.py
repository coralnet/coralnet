from django import forms
from django.contrib import admin
from markdownx.widgets import AdminMarkdownxWidget
from reversion.admin import VersionAdmin

from .models import BlogPost


class BlogPostForm(forms.ModelForm):

    class Media:
        css = {
            'all': ("css/markdownx_editor.css",)
        }

    class Meta:
        # Use the markdownx widget for the content field.
        widgets = dict(
            content=AdminMarkdownxWidget(),
        )


# With VersionAdmin, saving blog posts via site views (admin or otherwise)
# should trigger saving of django-reversion Versions.
@admin.register(BlogPost)
class BlogPostAdmin(VersionAdmin):
    form = BlogPostForm
