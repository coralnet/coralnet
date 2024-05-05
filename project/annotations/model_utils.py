# Utility methods used by models.py.
#
# These methods should not import anything from models.py.  Otherwise,
# there will be circular import dependencies.  Utility functions
# that use models.py should go in the general utility functions
# file, utils.py.
from decimal import Decimal
import math

from django.db import models


class AnnotationArea:
    """
    Utility class for specifying annotation-area specs.

    Percentages are decimals.
    Pixels are integers.
    Database (db) format:
        percentages - '5.7;94.5;10;90'
        pixels - '125,1880,80,1600'
        imported - 'imported'
    """

    IMPORTED_DB_VALUE = 'imported'
    TYPE_PERCENTAGES = 'percentages'
    TYPE_PIXELS = 'pixels'
    TYPE_IMPORTED = 'imported'

    number_field_order = [
        'min_x', 'max_x', 'min_y', 'max_y',
    ]

    def __init__(self, type, min_x=None, max_x=None, min_y=None, max_y=None):
        self.type = type

        match self.type:
            case self.TYPE_PERCENTAGES:
                conversion = Decimal
            case self.TYPE_PIXELS:
                conversion = int
            case self.TYPE_IMPORTED:
                # Identity function; imported doesn't care about other args.
                def conversion(x):
                    return x
            case _:
                raise ValueError(f"Unsupported type: {self.type}")

        self.min_x = conversion(min_x)
        self.max_x = conversion(max_x)
        self.min_y = conversion(min_y)
        self.max_y = conversion(max_y)

    @property
    def db_value(self):
        match self.type:
            case self.TYPE_PERCENTAGES:
                return ';'.join([
                    str(getattr(self, field_name))
                    for field_name in self.number_field_order
                ])
            case self.TYPE_PIXELS:
                return ','.join([
                    str(getattr(self, field_name))
                    for field_name in self.number_field_order
                ])
            case self.TYPE_IMPORTED:
                return self.IMPORTED_DB_VALUE
            case _:
                raise ValueError(f"Unsupported type: {self.type}")

    @property
    def source_form_kwargs(self):
        """
        Kwargs that can be submitted to the new source or edit source form.
        """
        if self.type != self.TYPE_PERCENTAGES:
            raise ValueError(
                "Sources can only have percentage annotation areas.")

        return {
            f'image_annotation_area_{index}': getattr(self, field_name)
            for index, field_name in enumerate(self.number_field_order)
        }

    def __str__(self):
        match self.type:
            case self.TYPE_PERCENTAGES:
                return (
                    f"X: {self.min_x} - {self.max_x}%"
                    f" / Y: {self.min_y} - {self.max_y}%"
                )
            case self.TYPE_PIXELS:
                return (
                    f"X: {self.min_x} - {self.max_x} pixels"
                    f" / Y: {self.min_y} - {self.max_y} pixels"
                )
            case self.TYPE_IMPORTED:
                return "(Imported points; not specified)"
            case _:
                raise ValueError(f"Unsupported type: {self.type}")

    @classmethod
    def from_db_value(cls, db_value):
        if db_value == cls.IMPORTED_DB_VALUE:
            return cls(type=cls.TYPE_IMPORTED)
        elif ';' in db_value:
            # percentages
            number_values = [
                Decimal(dec_str) for dec_str in db_value.split(';')]
            d = dict(zip(cls.number_field_order, number_values))
            return cls(type=cls.TYPE_PERCENTAGES, **d)
        elif ',' in db_value:
            # pixels
            number_values = [
                int(int_str) for int_str in db_value.split(',')]
            d = dict(zip(cls.number_field_order, number_values))
            return cls(type=cls.TYPE_PIXELS, **d)
        else:
            raise ValueError("Annotation area isn't in a valid DB format.")

    @classmethod
    def to_pixels(cls, instance, width, height):
        match instance.type:
            case cls.TYPE_PERCENTAGES:
                # Convert to Decimal pixel values ranging from 0 to the
                # width/height.
                #
                # Type progression of the computation:
                # (Decimal / int) * int
                # Decimal * int
                # Decimal
                d = {
                    'min_x': (instance.min_x / 100) * width,
                    'max_x': (instance.max_x / 100) * width,
                    'min_y': (instance.min_y / 100) * height,
                    'max_y': (instance.max_y / 100) * height,
                }

                for key in d.keys():
                    # Convert the Decimal pixel values to integers.

                    # At this point our values range from 0.0 to width/height.
                    # Round up, then subtract 1.
                    d[key] = int(math.ceil(d[key]) - 1)

                    # Clamp the -1 edge-value to 0.
                    # We thus map 0.000-1.000 to 0, 1.001-2.000 to 1,
                    # 2.001-3.000 to 2, etc.
                    d[key] = max(d[key], 0)

                return cls(type=cls.TYPE_PIXELS, **d)
            case cls.TYPE_PIXELS:
                return instance
            case cls.TYPE_IMPORTED:
                raise ValueError(
                    "Points were imported; area pixels not specified.")
            case _:
                raise ValueError(f"Unsupported type: {instance.type}")


class ImageAnnoStatuses(models.TextChoices):
    UNCLASSIFIED = 'unclassified', "Unclassified"
    UNCONFIRMED = 'unconfirmed', "Unconfirmed"
    CONFIRMED = 'confirmed', "Confirmed"


class VerboseImageAnnoStatuses(models.TextChoices):
    NOT_STARTED = 'not_started', "Not started"
    UNCONFIRMED = 'unconfirmed', "Unconfirmed"
    PARTIALLY_CONFIRMED = 'partially_confirmed', "Partially confirmed"
    CONFIRMED = 'confirmed', "Confirmed (completed)"


def image_annotation_status(image):
    """
    Unclassified pts | Unconfirmed pts | Confirmed pts | Status
    ------------------------------------------------------------------
    Y | Y | Y | UNCLASSIFIED
    Y | Y | N | UNCLASSIFIED
    Y | N | Y | UNCLASSIFIED
    Y | N | N | UNCLASSIFIED
    N | Y | Y | UNCONFIRMED
    N | Y | N | UNCONFIRMED
    N | N | Y | CONFIRMED
    N | N | N | UNCLASSIFIED
    """
    annotations = image.annotation_set.all()
    annotation_count = annotations.count()

    if annotation_count == 0:
        return ImageAnnoStatuses.UNCLASSIFIED.value

    point_count = image.point_set.count()
    if annotation_count < point_count:
        return ImageAnnoStatuses.UNCLASSIFIED.value

    if annotations.unconfirmed().exists():
        return ImageAnnoStatuses.UNCONFIRMED.value

    return ImageAnnoStatuses.CONFIRMED.value


def image_annotation_verbose_status(image):
    """
    Unclassified pts | Unconfirmed pts | Confirmed pts | Status
    ------------------------------------------------------------------
    Y | Y | Y | PARTIALLY_CONFIRMED
    Y | Y | N | NOT_STARTED
    Y | N | Y | PARTIALLY_CONFIRMED
    Y | N | N | NOT_STARTED
    N | Y | Y | PARTIALLY_CONFIRMED
    N | Y | N | UNCONFIRMED
    N | N | Y | CONFIRMED
    N | N | N | NOT_STARTED
    """
    annotations = image.annotation_set.all()
    annotation_count = annotations.count()

    if annotation_count == 0:
        return VerboseImageAnnoStatuses.NOT_STARTED.value

    point_count = image.point_set.count()
    confirmed_count = annotations.confirmed().count()

    if confirmed_count == point_count:
        return VerboseImageAnnoStatuses.CONFIRMED.value

    if confirmed_count > 0:
        return VerboseImageAnnoStatuses.PARTIALLY_CONFIRMED.value

    if annotation_count == point_count:
        return VerboseImageAnnoStatuses.UNCONFIRMED.value

    return VerboseImageAnnoStatuses.NOT_STARTED.value


def image_annotation_verbose_status_label(image):
    return VerboseImageAnnoStatuses(
        image_annotation_verbose_status(image)).label
