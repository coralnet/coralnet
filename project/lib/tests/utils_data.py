from io import BytesIO
import json
import math
import posixpath
import random

from PIL import Image as PILImage
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.base import ContentFile
from django.test.client import Client
from django.urls import reverse
from spacer.messages import ClassifyReturnMsg

from annotations.model_utils import AnnotationArea
from images.model_utils import PointGen
from images.models import Image, Point
from labels.models import LabelGroup, Label
from sources.models import Source
from vision_backend.common import Extractors
from vision_backend.models import Classifier
import vision_backend.task_helpers as backend_task_helpers

User = get_user_model()


class DataTestMixin:
    """
    Convenience methods a ClientTest can use to set up model instances
    and related data.
    """

    client: Client

    user_count = 0

    @classmethod
    def create_user(
            cls, username=None, password='SamplePassword', email=None,
            activate=True):
        """
        Create a user.
        :param username: New user's username. 'user<number>' if not given.
        :param password: New user's password.
        :param email: New user's email. '<username>@example.com' if not given.
        :param activate: Whether to activate the user or not.
        :return: The new user.
        """
        cls.user_count += 1
        if not username:
            # Generate a username. If some tests check for string matching
            # of usernames, then having both 'user1' and 'user10' could be
            # problematic; so we add leading zeroes to the number suffix, like
            # 'user0001'.
            username = 'user{n:04d}'.format(n=cls.user_count)
        if not email:
            email = '{username}@example.com'.format(username=username)

        cls.client.post(reverse('django_registration_register'), dict(
            username=username, email=email,
            password1=password, password2=password,
            first_name="-", last_name="-",
            affiliation="-",
            reason_for_registering="-",
            project_description="-",
            how_did_you_hear_about_us="-",
            agree_to_data_policy=True,
        ))

        if activate:
            activation_email = mail.outbox[-1]
            activation_link = None
            for word in activation_email.body.split():
                if '://' in word:
                    activation_link = word
                    break
            cls.client.get(activation_link)

        return User.objects.get(username=username)

    @classmethod
    def create_superuser(cls):
        # There is a createsuperuser management command included in Django,
        # but it doesn't create a password or user profile for the new
        # superuser. Those are handy to have for some tests, so we'll instead
        # create the superuser like any regular user.
        user = cls.create_user(username='superuser')

        user.is_superuser = True
        # We don't particularly care about separating superusers/staff.
        # We'll just give this superuser everything, including staff perms.
        user.is_staff = True
        user.save()

        return user

    source_count = 0
    source_defaults = dict(
        name=None,
        visibility=Source.VisibilityTypes.PUBLIC,
        description="Description",
        affiliation="Affiliation",
        key1="Aux1",
        key2="Aux2",
        key3="Aux3",
        key4="Aux4",
        key5="Aux5",
        # X 0-100%, Y 0-100%
        image_annotation_area_0=0,
        image_annotation_area_1=100,
        image_annotation_area_2=0,
        image_annotation_area_3=100,
        # Simple random, 5 points
        default_point_generation_method_0=PointGen.Types.SIMPLE.value,
        default_point_generation_method_1=5,
        trains_own_classifiers=True,
        confidence_threshold=100,
        feature_extractor_setting=Extractors.EFFICIENTNET.value,
        latitude='0.0',
        longitude='0.0',
    )

    @classmethod
    def create_source(
        cls, user, name=None,
        image_annotation_area: dict = None,
        default_point_generation_method: dict = None,
        **options
    ):
        """
        Create a source.
        :param user: User who is creating this source.
        :param name: Source name. "Source <number>" if not given.
        :param image_annotation_area: Shortcut for specifying this
          source option as one concise dict (min_x, max_x, min_y, max_y)
          instead of 4 verbose kwargs.
        :param default_point_generation_method: Shortcut for specifying
          this source option as one concise dict instead of 2-4 verbose
          kwargs.
        :param options: Other params to POST into the new source form.
        :return: The new source.
        """
        cls.source_count += 1
        if not name:
            name = f'Source {cls.source_count:04d}'

        post_dict = dict()
        post_dict.update(cls.source_defaults)
        post_dict.update(options)
        post_dict['name'] = name

        if image_annotation_area:
            area = AnnotationArea(
                type=AnnotationArea.TYPE_PERCENTAGES, **image_annotation_area)
            post_dict |= area.source_form_kwargs
        if default_point_generation_method:
            post_dict |= PointGen(
                **default_point_generation_method).source_form_kwargs

        cls.client.force_login(user)
        # Create source.
        cls.client.post(reverse('source_new'), post_dict)
        source = Source.objects.get(name=name)
        # Edit source; confidence_threshold is only reachable from source_edit.
        cls.client.post(reverse('source_edit', args=[source.pk]), post_dict)
        source.refresh_from_db()
        cls.client.logout()

        return source

    @classmethod
    def add_source_member(cls, admin, source, member, perm):
        """
        Add member to source, with permission level perm.
        Use admin to send the invite.
        """
        # Send invite as source admin
        cls.client.force_login(admin)
        cls.client.post(
            reverse('source_admin', kwargs={'source_id': source.pk}),
            dict(
                sendInvite='sendInvite',
                recipient=member.username,
                source_perm=perm,
            )
        )
        # Accept invite as prospective source member
        cls.client.force_login(member)
        cls.client.post(
            reverse('invites_manage'),
            dict(
                accept='accept',
                sender=admin.pk,
                source=source.pk,
            )
        )

        cls.client.logout()

    @classmethod
    def create_labels(cls, user, label_names, group_name, default_codes=None):
        """
        Create labels.
        :param user: User who is creating these labels.
        :param label_names: Names for the new labels.
        :param group_name: Name for the label group to put the labels in;
          this label group is assumed to not exist yet.
        :param default_codes: Default short codes for the labels, as a list of
          the same length as label_names. If not specified, the first 10
          letters of the label names are used.
        :return: The new labels, as a queryset.
        """
        group = LabelGroup(name=group_name, code=group_name[:10])
        group.save()

        if default_codes is None:
            default_codes = [name[:10] for name in label_names]

        cls.client.force_login(user)
        for name, code in zip(label_names, default_codes):
            cls.client.post(
                reverse('label_new_ajax'),
                dict(
                    name=name,
                    default_code=code,
                    group=group.id,
                    description="Description",
                    # A new filename will be generated, and the uploaded
                    # filename will be discarded, so it doesn't matter.
                    thumbnail=sample_image_as_file('_.png'),
                )
            )
        cls.client.logout()

        return Label.objects.filter(name__in=label_names)

    @classmethod
    def create_labelset(cls, user, source, labels):
        """
        Create a labelset (or redefine entries in an existing one).
        :param user: User to create the labelset as.
        :param source: The source which this labelset will belong to
        :param labels: The labels this labelset will have, as a queryset
        :return: The new labelset
        """
        cls.client.force_login(user)
        cls.client.post(
            reverse('labelset_add', kwargs=dict(source_id=source.id)),
            dict(
                label_ids=','.join(
                    str(pk) for pk in labels.values_list('pk', flat=True)),
            ),
        )
        cls.client.logout()
        source.refresh_from_db()
        return source.labelset

    image_count = 0

    @classmethod
    def upload_image(cls, user, source, image_options=None, image_file=None):
        """
        Upload a data image.
        :param user: User to upload as.
        :param source: Source to upload to.
        :param image_options: Dict of options for the image file.
            Accepted keys: filetype, and whatever create_sample_image() takes.
        :param image_file: If present, this is an open file to use as the
            image file. Takes precedence over image_options.
        :return: The new image.
        """
        cls.image_count += 1

        post_dict = dict()

        # Get an image file
        if image_file:
            post_dict['file'] = image_file
            post_dict['name'] = image_file.name
        else:
            image_options = image_options or dict()
            filetype = image_options.pop('filetype', 'PNG')
            default_filename = "file_{count:04d}.{filetype}".format(
                count=cls.image_count, filetype=filetype.lower())
            filename = image_options.pop('filename', default_filename)
            post_dict['file'] = sample_image_as_file(
                filename, filetype, image_options)
            post_dict['name'] = filename

        # Send the upload form.
        # Ensure the on_commit() callback runs, which should schedule a
        # source check.
        cls.client.force_login(user)
        with cls.captureOnCommitCallbacks(execute=True):
            response = cls.client.post(
                reverse('upload_images_ajax', kwargs={'source_id': source.id}),
                post_dict,
            )
        cls.client.logout()

        response_json = response.json()
        image_id = response_json['image_id']
        image = Image.objects.get(pk=image_id)
        return image

    @staticmethod
    def sample_image_as_file(filename, filetype=None, image_options=None):
        """
        Create a sample image and get it as a File-like object.
        """
        return sample_image_as_file(
            filename, filetype=filetype, image_options=image_options)

    @classmethod
    def add_annotations(cls, user, image, annotations=None):
        """
        Add human annotations to an image.
        :param user: Which user to annotate as.
        :param image: Image to add annotations for.
        :param annotations: Annotations to add, as a dict of point
            numbers to label codes, e.g.: {1: 'labelA', 2: 'labelB'}
            If not specified, adds random annotations for all points.
        :return: None.
        """
        if not annotations:
            annotations = random_annotations(image)

        num_points = Point.objects.filter(image=image).count()

        post_dict = dict()
        for point_num in range(1, num_points+1):
            post_dict['label_'+str(point_num)] = annotations.get(point_num, '')
            post_dict['robot_'+str(point_num)] = json.dumps(False)

        cls.client.force_login(user)
        cls.client.post(
            reverse('save_annotations_ajax', kwargs=dict(image_id=image.id)),
            post_dict,
        )
        cls.client.logout()

    @staticmethod
    def create_robot(source, set_as_deployed=True):
        """
        Add a robot to a source.
        """
        return create_robot(source, set_as_deployed=set_as_deployed)

    @staticmethod
    def add_robot_annotations(robot, image, annotations=None):
        """
        Add robot annotations to an image.
        """
        add_robot_annotations(robot, image, annotations=annotations)


def create_sample_image(width=200, height=200, cols=10, rows=10, mode='RGB'):
    """
    Create a test image. The image content is a color grid.
    Optionally specify pixel width/height, and the color grid cols/rows.
    You can also specify the "mode" (see PIL documentation).
    Colors are interpolated along the grid with randomly picked color ranges.

    Return as an in-memory PIL image.
    """
    # Randomly choose one RGB color component to vary along x, one to vary
    # along y, and one to stay constant.
    x_varying_component = random.choice([0, 1, 2])
    y_varying_component = random.choice(list(
        {0, 1, 2} - {x_varying_component}))
    const_component = list(
        {0, 1, 2} - {x_varying_component, y_varying_component})[0]
    # Randomly choose the ranges of colors.
    x_min_color = random.choice([0.0, 0.1, 0.2, 0.3])
    x_max_color = random.choice([0.7, 0.8, 0.9, 1.0])
    y_min_color = random.choice([0.0, 0.1, 0.2, 0.3])
    y_max_color = random.choice([0.7, 0.8, 0.9, 1.0])
    const_color = random.choice([0.3, 0.4, 0.5, 0.6, 0.7])

    col_width = width / cols
    row_height = height / rows
    min_rgb = 0
    max_rgb = 255

    im = PILImage.new(mode, (width, height))

    const_color_value = int(round(
        const_color*(max_rgb - min_rgb) + min_rgb
    ))

    for x in range(cols):

        left_x = int(round(x*col_width))
        right_x = int(round((x+1)*col_width))

        x_varying_color_value = int(round(
            (x/cols)*(x_max_color - x_min_color)*(max_rgb - min_rgb)
            + (x_min_color*min_rgb)
        ))

        for y in range(rows):

            upper_y = int(round(y*row_height))
            lower_y = int(round((y+1)*row_height))

            y_varying_color_value = int(round(
                (y/rows)*(y_max_color - y_min_color)*(max_rgb - min_rgb)
                + (y_min_color*min_rgb)
            ))

            color_dict = {
                x_varying_component: x_varying_color_value,
                y_varying_component: y_varying_color_value,
                const_component: const_color_value,
            }

            # The dict's keys should be the literals 0, 1, and 2.
            # We interpret these as R, G, and B respectively.
            if mode in ['L', '1', 'P']:
                # Gray scale, just grab one of the channels.
                im.paste(color_dict[0], (left_x, upper_y, right_x, lower_y))
            else:
                rgb_color = (color_dict[0], color_dict[1], color_dict[2])
                im.paste(rgb_color, (left_x, upper_y, right_x, lower_y))

    return im


def sample_image_as_file(
        filename, filetype=None, image_options=None) -> ContentFile:
    """
    Create a sample image and get it as a File-like object.
    """
    if not filetype:
        if posixpath.splitext(filename)[-1].upper() in ['.JPG', '.JPEG']:
            filetype = 'JPEG'
        elif posixpath.splitext(filename)[-1].upper() == '.PNG':
            filetype = 'PNG'
        else:
            raise ValueError(
                f"Couldn't get filetype from filename: {filename}")

    image_options = image_options or dict()
    im = create_sample_image(**image_options)
    with BytesIO() as stream:
        # Save the PIL image to an IO stream
        im.save(stream, filetype)
        # Convert to a file-like object, and use that in the upload form
        # http://stackoverflow.com/a/28209277/
        image_file = ContentFile(stream.getvalue(), name=filename)
    return image_file


def create_robot(source, set_as_deployed=True):
    """
    Add a robot (Classifier) to a source.
    NOTE: This does not use any standard task or utility function
    for adding a robot, so standard assumptions might not hold.
    :param source: Source to add a robot for.
    :return: The new robot.
    """
    classifier = Classifier(
        source=source,
        nbr_train_images=50,
        runtime_train=100,
        accuracy=0.50,
        status=Classifier.ACCEPTED,
    )
    classifier.save()

    if set_as_deployed:
        source.deployed_classifier = classifier
        source.save()

    return classifier


def random_annotations(image) -> dict[int, str]:
    """
    Example: {1: 'labelA', 2: 'labelB'}
    """
    point_count = image.point_set.count()
    point_numbers = range(1, point_count + 1)
    local_labels = list(image.source.labelset.locallabel_set.all())
    label_codes = [
        random.choice(local_labels).code
        for _ in range(point_count)]
    return dict(zip(point_numbers, label_codes))


def add_robot_annotations(robot, image, annotations=None):
    """
    Add robot annotations and scores to an image, without touching any
    computer vision algorithms.

    NOTE: This only uses helper functions for adding robot annotations,
    not an entire view or task. So the regular assumptions might not hold,
    like setting statuses, etc. Use with slight caution.

    :param robot: Classifier model object to use for annotation.
    :param image: Image to add annotations for.
    :param annotations: Annotations to add,
      as a dict of point numbers to label codes like: {1: 'AB', 2: 'CD'}
      OR dict of point numbers to label code / confidence value tuples:
      {1: ('AB', 85), 2: ('CD', 47)}
      You must specify annotations for ALL points in the image, because
      that's the expectation of the helper function called from here.
      Alternatively, you can skip specifying this parameter and let this
      function assign random labels.
    :return: None.
    """
    # This is the same way _add_annotations() orders points.
    # This is the order that the scores list should follow.
    points = Point.objects.filter(image=image).order_by('id')

    # Labels can be in any order, as long as the order stays consistent
    # throughout annotation adding.
    local_labels = list(image.source.labelset.get_labels())
    label_count = len(local_labels)

    if annotations is None:
        annotations = random_annotations(image)

    # Make label scores. The specified label should come out on top,
    # and that label's confidence value (if specified) should be respected.
    # The rest is arbitrary.
    scores = []
    for point in points:
        try:
            annotation = annotations[point.point_number]
        except KeyError:
            raise ValueError((
                "No annotation specified for point {num}. You must specify"
                " annotations for all points in this image.").format(
                    num=point.point_number))

        if isinstance(annotation, str):
            # Only top label specified
            label_code = annotation
            # Pick a top score, which is possible to be an UNTIED top score
            # given the label count (if tied, then the top label is ambiguous).
            # min with 100 to cover the 1-label-count case.
            lowest_possible_confidence = min(
                100, math.ceil(100 / label_count) + 1)
            top_score = random.randint(lowest_possible_confidence, 100)
        else:
            # Top label and top confidence specified
            label_code, top_score = annotation

        remaining_total = 100 - top_score
        quotient = remaining_total // (label_count - 1)
        remainder = remaining_total % (label_count - 1)
        other_scores = [quotient + 1] * remainder
        other_scores += [quotient] * (label_count - 1 - remainder)

        # We just tried to make the max of other_scores as small as
        # possible (given a total of 100), so if that didn't work,
        # then we'll conclude the confidence value is unreasonably low
        # given the label count. (Example: 33% confidence, 2 labels)
        if max(other_scores) >= top_score:
            raise ValueError((
                "Could not create {label_count} label scores with a"
                " top confidence value of {top_score}. Try lowering"
                " the confidence or adding more labels.").format(
                    label_count=label_count, top_score=top_score))

        scores_for_point = []
        # List of scores for a point and list of labels should be in
        # the same order. In particular, if the nth label is the top one,
        # then the nth score should be the top one too.
        for local_label in local_labels:
            if local_label.code == label_code:
                scores_for_point.append(top_score)
            else:
                scores_for_point.append(other_scores.pop())

        # Up to now we've represented 65% as the integer 65, for easier math.
        # But the utility functions we'll call actually expect the float 0.65.
        # So divide by 100.
        scores.append((
            point.row, point.column, [s / 100 for s in scores_for_point]))

    global_labels = [ll.global_label for ll in local_labels]

    # Package scores into a ClassifyReturnMsg. Note that this function expects
    # scores for all labels, but will only save the top
    # NBR_SCORES_PER_ANNOTATION per point.
    clf_return_msg = ClassifyReturnMsg(
        runtime=1.0,
        scores=scores,
        classes=[label.pk for label in global_labels],
        valid_rowcol=True
    )

    backend_task_helpers.add_scores(image.pk, clf_return_msg, global_labels)
    backend_task_helpers.add_annotations(
        image.pk, clf_return_msg, global_labels, robot)
