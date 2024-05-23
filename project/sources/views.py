import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from annotations.model_utils import ImageAnnoStatuses
from annotations.utils import cacheable_annotation_count
from images.models import Image
from images.utils import delete_image
from jobs.utils import schedule_job
from lib.decorators import (
    source_permission_required,
    source_visibility_required,
)
from lib.utils import date_display, datetime_display
from map.utils import cacheable_map_sources
from newsfeed.models import NewsItem
from vision_backend.models import Classifier, Features
from vision_backend.utils import schedule_source_check_on_commit
from .forms import (
    SourceChangePermissionForm,
    SourceForm,
    SourceInviteForm,
    SourceRemoveUserForm,
)
from .models import Source, SourceInvite


def source_list(request):
    """
    Page with a list of the user's Sources.
    """
    your_sources = Source.get_sources_of_user(request.user)

    # Redirect to the About page if the user doesn't have any Sources.
    # This includes the not-logged-in case.
    if not your_sources:
        return HttpResponseRedirect(reverse('source_about'))

    your_sources_dicts = [dict(id=s.id,
                               name=s.name,
                               your_role=s.get_member_role(request.user),)
                          for s in your_sources]
    other_public_sources = Source.get_other_public_sources(request.user)

    # Gather some stats
    total_sources = Source.objects.all().count()
    total_images = Image.objects.all().count()
    total_annotations = cacheable_annotation_count.get()

    return render(request, 'sources/source_list.html', {
        'your_sources': your_sources_dicts,
        'map_sources': cacheable_map_sources.get(),
        'other_public_sources': other_public_sources,
        'total_sources': total_sources,
        'total_images': total_images,
        'total_annotations': total_annotations,
    })


def source_about(request):
    """
    Page that explains what Sources are and how to use them.
    """

    if request.user.is_authenticated:
        if Source.get_sources_of_user(request.user):
            user_status = 'has_sources'
        else:
            user_status = 'no_sources'
    else:
        user_status = 'anonymous'

    return render(request, 'sources/source_about.html', {
        'user_status': user_status,
        'public_sources': Source.get_public_sources(),
    })


@login_required
def source_new(request):
    """
    Page with the form to create a new Source.
    """

    # We can get here one of two ways: either we just got to the form
    # page, or we just submitted the form.  If POST, we submitted; if
    # GET, we just got here.
    if request.method == 'POST':
        # Bind the form to the submitted POST data.
        source_form = SourceForm(request.POST, request=request)

        # <form>.is_valid() calls <form>.clean() and checks field validity.
        if source_form.is_valid():

            # Save a new Source model instance and retrieve it.
            new_source = source_form.save()

            # Make the current user an admin of the new source
            new_source.assign_role(request.user, Source.PermTypes.ADMIN.code)

            # Add a success message
            messages.success(request, "Source successfully created.")

            # Redirect to the source's main page
            return HttpResponseRedirect(
                reverse('source_main', args=[new_source.id]))
        else:
            # Show the form again, with error message
            messages.error(request, "Please correct the errors below.")
    else:
        # Unbound (empty) form
        source_form = SourceForm()

    return render(request, 'sources/source_new.html', {
        'source_form': source_form,
        'map_minimum_images': settings.MAP_IMAGE_COUNT_TIERS[0],
    })


@source_visibility_required('source_id')
def source_main(request, source_id):
    """
    Main page for a particular source.
    """

    source = get_object_or_404(Source, id=source_id)

    # Users who are members of the source
    members = source.get_members_ordered_by_role()
    memberDicts = [dict(pk=member.pk,
                        username=member.username,
                        role=source.get_member_role(member))
                   for member in members]

    all_images = source.image_set.all()
    latest_images = all_images.order_by('-upload_date')[:3]

    # Images' annotation status
    browse_url_base = reverse('browse_images', args=[source.id])

    def browse_link_filtered_by_status(annotation_status):
        return browse_url_base + '?' + urlencode(dict(
            image_form_type='search', annotation_status=annotation_status,
            sort_direction='asc', sort_method='name'))

    image_stats = dict(
        total = all_images.count(),
        total_link = browse_url_base,
        confirmed = all_images.confirmed().count(),
        confirmed_link = browse_link_filtered_by_status(
            ImageAnnoStatuses.CONFIRMED.value),
        unconfirmed = all_images.unconfirmed().count(),
        unconfirmed_link = browse_link_filtered_by_status(
            ImageAnnoStatuses.UNCONFIRMED.value),
        unclassified = all_images.unclassified().count(),
        unclassified_link = browse_link_filtered_by_status(
            ImageAnnoStatuses.UNCLASSIFIED.value),
    )

    # Setup the classifier overview info, and plot if applicable
    classifier_plot_data = []
    last_accepted_classifier = source.last_accepted_classifier

    if source.trains_own_classifiers and last_accepted_classifier:

        trained_classifiers = source.classifier_set.filter(
            status__in=[Classifier.ACCEPTED, Classifier.REJECTED_ACCURACY])
        classifier_details = [
            ("Last classifier saved",
             datetime_display(last_accepted_classifier.train_completion_date)),
            ("Last classifier trained",
             datetime_display(
                 trained_classifiers.latest('pk').train_completion_date)),
            ("Feature extractor",
             source.get_feature_extractor_setting_display()),
            ("Confidence threshold",
             f'{source.confidence_threshold}%'),
        ]

        clfs = source.get_accepted_robots()
        for clf_index, clf in enumerate(clfs):
            classifier_plot_data.append({
                'x': clf_index + 1,
                'y': round(100 * clf.accuracy),
                'nimages': clf.nbr_train_images,
                'traintime': str(datetime.timedelta(seconds=clf.runtime_train)),
                'date': date_display(clf.train_completion_date),
                'pk': str(clf.pk),
            })

    elif source.trains_own_classifiers:

        classifier_details = [
            ("Classifier status",
             f"No classifier yet. Need a minimum of"
             f" {settings.TRAINING_MIN_IMAGES} Confirmed images"
             f" to train a classifier."),
            ("Feature extractor",
             source.get_feature_extractor_setting_display()),
        ]

    elif source.deployed_classifier:

        classifier_details = [
            ("Active classifier",
             source.get_deployed_classifier_html()),
            ("Confidence threshold",
             f'{source.confidence_threshold}%'),
        ]

    else:

        classifier_details = [
            ("Active classifier",
             source.get_deployed_classifier_html()),
        ]

    return render(request, 'sources/source_main.html', {
        'source': source,
        'members': memberDicts,
        'latest_images': latest_images,
        'image_stats': image_stats,

        'classifier_details': classifier_details,
        'classifier_plot_data': classifier_plot_data,

        'news_items': [item.render_view() for item in
                       NewsItem.objects.filter(source_id=source.id).order_by('-pk')]
    })


@source_permission_required('source_id', perm=Source.PermTypes.ADMIN.code)
def source_edit(request, source_id):
    """
    Edit a source: name, visibility, aux. metadata, etc.
    """
    source = get_object_or_404(Source, id=source_id)

    if request.method == 'POST':

        source_form = SourceForm(
            request.POST, request=request, instance=source)

        if source_form.is_valid():

            # Save the edits to the Source.
            source_form.save()

            resetting_something = False

            # Schedule classifier reset if needed.
            if 'feature_extractor_setting' in source_form.changed_data:
                # Changed the feature extractor setting for train-classifiers
                # mode. Wipe this source's trained classifiers.
                schedule_job(
                    'reset_classifiers_for_source', source_id,
                    source_id=source_id)
                messages.success(
                    request,
                    "Source successfully edited."
                    " Classifier history will be cleared.")
                resetting_something = True
            else:
                messages.success(request, "Source successfully edited.")

            # Schedule feature reset if needed.
            source_features = Features.objects.filter(
                image__source=source_form.instance, extracted=True)
            if (
                source_form.instance.feature_extractor is not None
                and source_features.exclude(
                    extractor=source_form.instance.feature_extractor).exists()
            ):
                # There exist features in the source that don't match
                # the new active extractor.
                # Going by the assumption that all extracted features in the
                # source must use the same extractor, we reset all extracted
                # features in the source.
                schedule_job(
                    'reset_features_for_source', source_id,
                    source_id=source_id)
                resetting_something = True

            classifier_settings_changed = (
                ('trains_own_classifiers' in source_form.changed_data)
                or ('deployed_classifier' in source_form.changed_data)
            )
            if classifier_settings_changed and not resetting_something:
                # A source check may be warranted, and may not be scheduled
                # soon unless we do so now.
                schedule_source_check_on_commit(source_id)

            return HttpResponseRedirect(
                reverse('source_main', args=[source_id]))

        else:

            messages.error(request, 'Please correct the errors below.')
    else:
        # Just reached this form page
        source_form = SourceForm(instance=source)

    return render(request, 'sources/source_edit.html', {
        'source': source,
        'edit_source_form': source_form,
        'map_minimum_images': settings.MAP_IMAGE_COUNT_TIERS[0],
    })


@source_permission_required('source_id', perm=Source.PermTypes.ADMIN.code)
def source_edit_cancel(request, source_id):
    messages.success(request, "Edit cancelled.")
    return redirect('source_main', source_id)


def source_detail_box(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    example_image_count = 5
    example_images = \
        source.image_set.all().order_by('-upload_date')[:example_image_count]

    detail_box_html = render_to_string('sources/source_detail_box.html', {
        'source': source,
        'example_images': example_images,
    })

    return JsonResponse(dict(
        detailBoxHtml=detail_box_html,
    ))


@source_permission_required('source_id', perm=Source.PermTypes.ADMIN.code)
def source_admin(request, source_id):
    """
    Either invites a user to the source or changes their permission in the source.
    """

    source = get_object_or_404(Source, id=source_id)

    if request.method == 'POST':

        inviteForm = SourceInviteForm(request.POST, source_id=source_id)
        changePermissionForm = SourceChangePermissionForm(request.POST, source_id=source_id, user=request.user)
        removeUserForm = SourceRemoveUserForm(request.POST, source_id=source_id, user=request.user)
        sendInvite = request.POST.get('sendInvite', None)
        changePermission = request.POST.get('changePermission', None)
        removeUser = request.POST.get('removeUser', None)
        deleteSource = request.POST.get('Delete', None)

        if inviteForm.is_valid() and sendInvite:

            invite = SourceInvite(
                sender=request.user,
                recipient=User.objects.get(username=inviteForm.cleaned_data['recipient']),
                source=source,
                source_perm=inviteForm.cleaned_data['source_perm'],
            )
            invite.save()

            messages.success(request, 'Your invite has been sent!')
            return HttpResponseRedirect(reverse('source_main', args=[source_id]))
        elif changePermissionForm.is_valid() and changePermission:

            source.reassign_role(
                user=User.objects.get(id=changePermissionForm.cleaned_data['user']),
                role=changePermissionForm.cleaned_data['perm_change']
            )

            messages.success(request, 'Permission for user has changed.')
            return HttpResponseRedirect(reverse('source_main', args=[source_id]))
        elif removeUserForm.is_valid() and removeUser:
            source.remove_role(User.objects.get(id=removeUserForm.cleaned_data['user']))

            messages.success(request, 'User has been removed from the source.')
            return HttpResponseRedirect(reverse('source_main', args=[source_id]))
        elif deleteSource:
            # Delete all images with our utility function to ensure no
            # problems like leftover related objects.
            images = source.get_all_images()
            for img in images:
                delete_image(img)

            # This is a ForeignKey field of the Source, and thus deleting
            # the Source can't trigger a cascade delete on this labelset.
            # So we have to get the labelset and delete it separately.
            # Also, we delete it after deleting the source to not trigger
            # PROTECT-related errors on this ForeignKey.
            labelset = source.labelset

            source.delete()
            if labelset:
                labelset.delete()

            messages.success(request, 'Source has been deleted.')

            return HttpResponseRedirect(reverse('index'))

        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Just reached this form page
        inviteForm = SourceInviteForm(source_id=source_id)
        changePermissionForm = SourceChangePermissionForm(source_id=source_id, user=request.user)
        removeUserForm = SourceRemoveUserForm(source_id=source_id, user=request.user)

    return render(request, 'sources/source_invite.html', {
        'source': source,
        'inviteForm': inviteForm,
        'changePermissionForm': changePermissionForm,
        'removeUserForm': removeUserForm,
    })


@login_required
def invites_manage(request):
    """
    Manage sent and received invites.
    """

    if request.method == 'POST':

        if ('accept' in request.POST) or ('decline' in request.POST):
            sender_id = request.POST['sender']
            source_id = request.POST['source']

            try:
                invite = SourceInvite.objects.get(sender__id=sender_id, recipient=request.user, source__id=source_id)
            except SourceInvite.DoesNotExist:
                messages.error(request, "Sorry, there was an error with this invite.\n"
                                        "Maybe the user who sent it withdrew the invite, or you already accepted or declined earlier.")
            else:
                if 'accept' in request.POST:
                    source = Source.objects.get(id=source_id)
                    source.assign_role(invite.recipient, invite.source_perm)

                    invite.delete()
                    messages.success(request, 'Invite accepted!')
                    return HttpResponseRedirect(reverse('source_main', args=[source.id]))
                elif 'decline' in request.POST:
                    invite.delete()
                    messages.success(request, 'Invite declined.')

        elif 'delete' in request.POST:
            recipient_id = request.POST['recipient']
            source_id = request.POST['source']

            try:
                invite = SourceInvite.objects.get(recipient__id=recipient_id, sender=request.user, source__id=source_id)
            except SourceInvite.DoesNotExist:
                messages.error(request, "Sorry, there was an error with this invite.\n"
                                        "Maybe you already deleted it earlier, or the user who received it already accepted or declined.")
            else:
                invite.delete()
                messages.success(request, 'Invite deleted.')

    return render(request, 'sources/invites_manage.html', {
        'invitesSent': request.user.invites_sent.all(),
        'invitesReceived': request.user.invites_received.all(),
    })
