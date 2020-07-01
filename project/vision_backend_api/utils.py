from __future__ import unicode_literals
from vision_backend.models import Classifier


def deploy_request_json_as_strings(job):
    """
    Get a string list representing a deploy job's request JSON.
    """
    request_json = job.request_json
    classifier_id = request_json['classifier_id']
    try:
        classifier = Classifier.objects.get(pk=classifier_id)
        classifier_display = "Classifier ID {} (Source ID {})".format(
            classifier_id, classifier.source.pk)
    except Classifier.DoesNotExist:
        classifier_display = "Classifier ID {} (deleted)".format(classifier_id)

    return [
        classifier_display,
        "URL: {}".format(request_json['url']),
        "Point count: {}".format(len(request_json['points'])),
    ]
