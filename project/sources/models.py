from django.contrib.auth.models import User
from django.db import models

from images.models import Source


class SourceInvite(models.Model):
    """
    An invite for a user to join a source.
    Invites will be deleted once they're accepted/declined.
    """
    # Will change this to a BigAutoField later.
    id = models.AutoField(primary_key=True)

    sender = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='invites_sent', editable=False)
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='invites_received')
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE,
        editable=False)
    source_perm = models.CharField(
        max_length=50, choices=Source._meta.permissions)

    class Meta:
        # A user can only be invited once to a source.
        unique_together = ['recipient', 'source']

    def source_perm_verbose(self):
        for permType in [Source.PermTypes.ADMIN,
                         Source.PermTypes.EDIT,
                         Source.PermTypes.VIEW]:
            if self.source_perm == permType.code:
                return permType.verbose
