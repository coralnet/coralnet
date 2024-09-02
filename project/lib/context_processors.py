from django.conf import settings


def coralnet_settings(request):
    return dict(
        account_questions_link=settings.ACCOUNT_QUESTIONS_LINK,
        forum_link=settings.FORUM_LINK,
        dark_colors_available=settings.DARK_COLORS_AVAILABLE,
    )
