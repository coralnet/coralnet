# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.shortcuts import render
from django.contrib.auth.decorators import permission_required

from .models import NewsItem, NewsSubItem


@permission_required('is_superuser')
def global_feed(request):
    print('in main')
    return render(request, 'newsfeed/global.html', {
        'news_items':
            [item.render_view() for item in
             NewsItem.objects.filter().order_by('-pk')]
    })


def one_event(request, news_item_id):
    print('in one')
    return render(request, 'newsfeed/details.html', {
        'main': NewsItem.objects.get(id=news_item_id).render_view(),
        'subs': [item.render_view() for item in
                 NewsSubItem.objects.filter(news_item__id=news_item_id)]
    })
