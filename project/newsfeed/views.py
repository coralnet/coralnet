# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.shortcuts import render
from django.contrib.auth.decorators import permission_required

from .models import NewsItem


@permission_required('is_superuser')
def newsfeed_global(request):
    return render(request, 'newsfeed/global.html', {
            'newslist': NewsItem.objects.filter()
        })

