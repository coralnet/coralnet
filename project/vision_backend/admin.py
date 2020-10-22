from django.contrib import admin
from .models import Classifier, BatchJob

admin.site.register(Classifier)
admin.site.register(BatchJob)
