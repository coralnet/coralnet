from django.urls import reverse

from images.models import Image, Metadata
from lib.tests.utils import BasePermissionTest, ClientTest
from vision_backend.models import Features
from ..models import Source, SourceInvite


class PermissionTest(BasePermissionTest):

    def test_invites_manage(self):
        url = reverse('invites_manage')
        template = 'sources/invites_manage.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_source_admin(self):
        url = reverse('source_admin', args=[self.source.pk])
        template = 'sources/source_invite.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)


class SourceInviteTest(BasePermissionTest):
    """
    Test invites to sources.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.source_to_private()

    def send_invite(self, sender, receiver, permission_level):
        self.client.force_login(sender)
        response = self.client.post(
            reverse('source_admin', args=[self.source.pk]),
            dict(
                sendInvite='sendInvite',
                recipient=receiver.username,
                source_perm=permission_level,
            ),
            follow=True)
        self.assertContains(response, "Your invite has been sent!")

        # Invite should exist
        SourceInvite.objects.get(sender=sender, source=self.source.pk)

    def accept_invite(self, sender, receiver):
        self.client.force_login(receiver)
        self.client.post(
            reverse('invites_manage'),
            dict(
                accept='',
                sender=sender.pk,
                source=self.source.pk,
            ),
        )

        # Invite should be used up
        with self.assertRaises(SourceInvite.DoesNotExist):
            SourceInvite.objects.get(sender=sender, source=self.source)

    def test_send_and_accept_view_level_invite(self):
        new_member = self.create_user()
        self.send_invite(self.user, new_member, Source.PermTypes.VIEW.code)
        self.accept_invite(self.user, new_member)

        # Test that the given permission level works
        self.assertPermissionGranted(
            reverse('source_main', args=[self.source.pk]), new_member,
            template='sources/source_main.html')
        self.assertPermissionDenied(
            reverse('upload_images', args=[self.source.pk]), new_member)
        self.assertPermissionDenied(
            reverse('source_admin', args=[self.source.pk]), new_member)

    def test_send_and_accept_edit_level_invite(self):
        new_member = self.create_user()
        self.send_invite(self.user, new_member, Source.PermTypes.EDIT.code)
        self.accept_invite(self.user, new_member)

        # Test that the given permission level works
        self.assertPermissionGranted(
            reverse('source_main', args=[self.source.pk]), new_member,
            template='sources/source_main.html')
        self.assertPermissionGranted(
            reverse('upload_images', args=[self.source.pk]), new_member,
            template='upload/upload_images.html')
        self.assertPermissionDenied(
            reverse('source_admin', args=[self.source.pk]), new_member)

    def test_send_and_accept_admin_level_invite(self):
        new_member = self.create_user()
        self.send_invite(self.user, new_member, Source.PermTypes.ADMIN.code)
        self.accept_invite(self.user, new_member)

        # Test that the given permission level works
        self.assertPermissionGranted(
            reverse('source_main', args=[self.source.pk]), new_member,
            template='sources/source_main.html')
        self.assertPermissionGranted(
            reverse('upload_images', args=[self.source.pk]), new_member,
            template='upload/upload_images.html')
        self.assertPermissionGranted(
            reverse('source_admin', args=[self.source.pk]), new_member,
            template='sources/source_invite.html')

    def test_send_and_decline_invite(self):
        receiver = self.create_user()
        self.send_invite(self.user, receiver, Source.PermTypes.EDIT.code)

        self.client.force_login(receiver)
        self.client.post(
            reverse('invites_manage'),
            dict(
                decline='',
                sender=self.user.pk,
                source=self.source.pk,
            ),
        )

        # Invite should no longer exist
        with self.assertRaises(SourceInvite.DoesNotExist):
            SourceInvite.objects.get(sender=self.user, source=self.source)

        # Test for lack of permission
        self.assertPermissionDenied(
            reverse('source_main', args=[self.source.pk]), receiver)
        self.assertPermissionDenied(
            reverse('upload_images', args=[self.source.pk]), receiver)
        self.assertPermissionDenied(
            reverse('source_admin', args=[self.source.pk]), receiver)

    def test_send_and_withdraw_invite(self):
        receiver = self.create_user()
        self.send_invite(self.user, receiver, Source.PermTypes.EDIT.code)

        self.client.force_login(self.user)
        self.client.post(
            reverse('invites_manage'),
            dict(
                delete='',
                recipient=receiver.pk,
                source=self.source.pk,
            ),
        )

        # Invite should no longer exist
        with self.assertRaises(SourceInvite.DoesNotExist):
            SourceInvite.objects.get(sender=self.user, source=self.source)

        # Test for lack of permission
        self.assertPermissionDenied(
            reverse('source_main', args=[self.source.pk]), receiver)
        self.assertPermissionDenied(
            reverse('upload_images', args=[self.source.pk]), receiver)
        self.assertPermissionDenied(
            reverse('source_admin', args=[self.source.pk]), receiver)

    def test_cant_accept_nonexistent_invite(self):
        """
        Sending 'accept' POST params pointing to a particular source and sender
        should only work if such an invite actually exists.
        """
        non_invitee = self.create_user()
        self.client.force_login(non_invitee)
        response = self.client.post(
            reverse('invites_manage'),
            dict(
                accept='',
                sender=self.user.pk,
                source=self.source.pk,
            ),
        )

        self.assertInHTML(
            "Sorry, there was an error with this invite."
            "<br>Maybe the user who sent it withdrew the invite,"
            " or you already accepted or declined earlier.",
            response.content.decode())

        # Test for lack of permission
        self.assertPermissionDenied(
            reverse('source_main', args=[self.source.pk]), non_invitee)
        self.assertPermissionDenied(
            reverse('upload_images', args=[self.source.pk]), non_invitee)
        self.assertPermissionDenied(
            reverse('source_admin', args=[self.source.pk]), non_invitee)


class ChangeMemberPermissionLevelTest(BasePermissionTest):
    """
    Test changing a source member's permission level.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.source_to_private()

    def test_change_level(self):
        # Test initial permission level
        self.assertPermissionGranted(
            reverse('source_main', args=[self.source.pk]), self.user_admin,
            template='sources/source_main.html')
        self.assertPermissionGranted(
            reverse('upload_images', args=[self.source.pk]), self.user_admin,
            template='upload/upload_images.html')
        self.assertPermissionGranted(
            reverse('source_admin', args=[self.source.pk]), self.user_admin,
            template='sources/source_invite.html')

        # Change user_admin's level from admin to view
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('source_admin', args=[self.source.pk]),
            dict(
                changePermission='changePermission',
                user=self.user_admin.pk,
                perm_change=Source.PermTypes.VIEW.code,
            ),
            follow=True)
        self.assertContains(response, "Permission for user has changed.")

        # Test that the new permission level works
        self.assertPermissionGranted(
            reverse('source_main', args=[self.source.pk]), self.user_admin,
            template='sources/source_main.html')
        self.assertPermissionDenied(
            reverse('upload_images', args=[self.source.pk]), self.user_admin)
        self.assertPermissionDenied(
            reverse('source_admin', args=[self.source.pk]), self.user_admin)


class RemoveMemberTest(BasePermissionTest):
    """
    Test removing a source member from a source.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.source_to_private()

    def test_remove_member(self):
        # Test initial permission level
        self.assertPermissionGranted(
            reverse('source_main', args=[self.source.pk]), self.user_admin,
            template='sources/source_main.html')
        self.assertPermissionGranted(
            reverse('upload_images', args=[self.source.pk]), self.user_admin,
            template='upload/upload_images.html')
        self.assertPermissionGranted(
            reverse('source_admin', args=[self.source.pk]), self.user_admin,
            template='sources/source_invite.html')

        # Remove user_admin's membership
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('source_admin', args=[self.source.pk]),
            dict(
                removeUser='removeUser',
                user=self.user_admin.pk,
            ),
            follow=True)
        self.assertContains(response, "User has been removed from the source.")

        # Test for lack of permission
        self.assertPermissionDenied(
            reverse('source_main', args=[self.source.pk]), self.user_admin)
        self.assertPermissionDenied(
            reverse('upload_images', args=[self.source.pk]), self.user_admin)
        self.assertPermissionDenied(
            reverse('source_admin', args=[self.source.pk]), self.user_admin)


class DeleteSourceTest(ClientTest):
    """
    Test source deletion.
    """
    def test_delete_source(self):
        user = self.create_user()
        source = self.create_source(user)
        img = self.upload_image(user, source)

        source_id = source.pk
        image_id = img.pk
        metadata_id = img.metadata.pk
        features_id = img.features.pk

        # Source should exist
        Source.objects.get(pk=source_id)

        self.client.force_login(user)
        response = self.client.post(
            reverse('source_admin', args=[source.pk]),
            dict(
                Delete='Delete',
            ),
            follow=True)
        self.assertContains(response, "Source has been deleted.")

        # Objects should no longer exist
        with self.assertRaises(Source.DoesNotExist):
            Source.objects.get(pk=source_id)
        with self.assertRaises(Image.DoesNotExist):
            Image.objects.get(pk=image_id)
        with self.assertRaises(Metadata.DoesNotExist):
            Metadata.objects.get(pk=metadata_id)
        with self.assertRaises(Features.DoesNotExist):
            Features.objects.get(pk=features_id)
