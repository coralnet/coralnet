from functools import lru_cache

from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


@lru_cache
def get_imported_user():
    return User.objects.get(username=settings.IMPORTED_USERNAME)
@lru_cache
def get_robot_user():
    return User.objects.get(username=settings.ROBOT_USERNAME)
@lru_cache
def get_alleviate_user():
    return User.objects.get(username=settings.ALLEVIATE_USERNAME)

def is_imported_user(user):
    return user.username == settings.IMPORTED_USERNAME
def is_robot_user(user):
    return user.username == settings.ROBOT_USERNAME
def is_alleviate_user(user):
    return user.username == settings.ALLEVIATE_USERNAME


def can_view_profile(request, profile):
    if request.user.is_superuser:
        return True
    if profile.user == request.user:
        # Can view your own profile.
        return True
    if not profile.user.is_active:
        # Most people can't view inactive users' profiles.
        return False

    if profile.privacy == 'open':
        # Anyone can view a public profile.
        return True
    if profile.privacy == 'registered':
        return request.user.is_authenticated
    # profile.privacy == 'closed'
    return False
