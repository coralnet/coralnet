from django.template.defaultfilters import truncatechars

from .models import ErrorLog


def replace_null(s):
    """
    It's apparently possible to get null chars in at least one of
    the error log char/text fields, which makes PostgreSQL get
    "A string literal cannot contain NUL (0x00) characters" upon
    saving the error log. So, this replaces null chars with
    a Replacement Character (question mark diamond).
    """
    return s.replace('\x00', '\uFFFD')


def instantiate_error_log(kind, html, path, info, data):
    """
    Take inputs for saving an ErrorLog, and preprocess the inputs so they
    can be saved successfully. We want to guarantee that this won't fail, so
    we truncate and replace chars as needed.
    """
    path_max_length = ErrorLog._meta.get_field('path').max_length

    return ErrorLog(
        kind=kind,
        html=replace_null(html),
        path=replace_null(truncatechars(path, path_max_length)),
        info=replace_null(info),
        data=replace_null(data),
    )
