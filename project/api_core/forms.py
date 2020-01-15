# Django's forms system seems to have limited use for our API, since:
# - Django doesn't seem to have JSON field validators.
# - There's no clean way to specify the error 'source' as a JSON pointer.
#   The cleanest way would have been to raise ValidationErrors like
#   "This field is required. | /images/2", then parse the message and
#   JSON pointer out of that string by splitting at the |.
# So we more or less roll our own validation. We still put it in 'forms.py'
# since that filename is generally associated with validating user input.

from __future__ import unicode_literals
import json
import six
from six.moves import collections_abc

from .exceptions import ApiRequestDataError


def validate_required_param(data, param_name):
    try:
        return data[param_name]
    except KeyError:
        raise ApiRequestDataError(
            "This parameter is required.", parameter=param_name)


def validate_json(s, param_name):
    try:
        return json.loads(s)
    except ValueError:
        raise ApiRequestDataError(
            "Could not parse as JSON.", parameter=param_name)


def validate_array(element, json_path, check_non_empty=False, max_length=None):
    # We use MutableSequence instead of Sequence to avoid matching strings.
    if not isinstance(element, collections_abc.MutableSequence):
        raise ApiRequestDataError(
            "Ensure this element is an array.", json_path)
    if check_non_empty:
        if len(element) == 0:
            raise ApiRequestDataError(
                "Ensure this array is non-empty.", json_path)
    if max_length:
        if len(element) > max_length:
            message = "This array exceeds the max length of {max}.".format(
                max=max_length)
            raise ApiRequestDataError(message, json_path)


def validate_hash(element, json_path, expected_keys=None):
    if not isinstance(element, collections_abc.Mapping):
        raise ApiRequestDataError("Ensure this element is a hash.", json_path)
    if expected_keys:
        for key in expected_keys:
            if key not in element:
                raise ApiRequestDataError(
                    "Ensure this hash has a '{key}' key.".format(key=key),
                    json_path)


def validate_integer(element, json_path, min_value=None, max_value=None):
    if isinstance(element, int):
        integer = element
    else:
        try:
            integer = int(element)
        except ValueError:
            raise ApiRequestDataError(
                "Ensure this element is an integer.", json_path)

    if min_value is not None:
        if integer < min_value:
            raise ApiRequestDataError(
                "This element's value is below the minimum"
                " of {min}.".format(min=min_value),
                json_path)
    if max_value is not None:
        if integer > max_value:
            raise ApiRequestDataError(
                "This element's value is above the maximum"
                " of {max}.".format(max=max_value),
                json_path)

    # This function accepts an integer or string, and returns an integer,
    # to simplify further processing steps.
    return integer


def validate_string(element, json_path):
    if not isinstance(element, six.text_type):
        raise ApiRequestDataError(
            "Ensure this element is a string.", json_path)
