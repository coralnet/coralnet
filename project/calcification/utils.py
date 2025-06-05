import csv

from django.conf import settings
from django.core.cache import cache

from labels.models import Label
from lib.exceptions import FileProcessError
from upload.utils import csv_to_dicts
from .models import CalcifyRateTable


def get_global_calcify_tables():
    return CalcifyRateTable.objects.filter(source__isnull=True).order_by('-pk')


def get_default_calcify_tables():
    """
    Get the latest global table from each region.
    """
    if not settings.USE_DISTINCT_ON:
        return CalcifyRateTable.objects.filter(source__isnull=True)

    return CalcifyRateTable.objects.filter(source__isnull=True).order_by(
        'region', '-pk').distinct('region')


def get_default_calcify_rates():
    cache_key = 'default_calcify_rates'

    # Check for cached value
    cached_value = cache.get(cache_key)
    if cached_value is not None:
        return cached_value

    # No cached value available
    tables = get_default_calcify_tables()
    rates = {
        table.region: table.rates_json
        for table in tables
    }
    # Cache for 10 minutes
    cache.set(cache_key, rates, 60*10)
    return rates


def label_has_calcify_rates(label):
    rates_by_region = get_default_calcify_rates()
    return any([
        str(label.pk) in region_rates
        for _, region_rates in rates_by_region.items()
    ])


def rate_table_csv_to_json(csv_stream):
    csv_data = csv_to_dicts(
        csv_stream=csv_stream,
        required_columns=dict(
            label_name="Name",
            mean="Mean",
            lower_bound="Lower bound",
            upper_bound="Upper bound",
        ),
        optional_columns=dict(),
        unique_keys=['label_name'],
    )

    rates_json = dict()

    for row_d in csv_data:

        try:
            # Case insensitive name search
            label_id = Label.objects.get(name__iexact=row_d['label_name']).pk
        except Label.DoesNotExist:
            raise FileProcessError(
                f"Label name not found: {row_d['label_name']}")

        # Ensure rates are numbers
        for key in ['mean', 'lower_bound', 'upper_bound']:
            try:
                float(row_d[key])
            except ValueError:
                raise FileProcessError(
                    f"{key} value '{row_d[key]}'"
                    " couldn't be converted to a number.")

        rates_json[label_id] = dict(
            mean=row_d['mean'],
            lower_bound=row_d['lower_bound'],
            upper_bound=row_d['upper_bound'],
        )

    return rates_json


def rate_table_json_to_csv(csv_stream, rate_table, source=None):
    fieldnames = [
        "Name",
        "Mean",
        "Lower bound",
        "Upper bound",
    ]
    writer = csv.DictWriter(csv_stream, fieldnames)
    writer.writeheader()

    rates = rate_table.rates_json

    if source:

        # Include all entries in the given source's labelset.

        label_ids_and_names = {
            str(label['pk']): label['name']
            for label
            in source.labelset.get_globals().values('pk', 'name')
        }

        for label_id, label_name in label_ids_and_names.items():
            if label_id in rates:
                label_rates = rates[label_id]
            else:
                # Default to 0s
                label_rates = dict(
                    mean='0.0', lower_bound='0.0', upper_bound='0.0')

            writer.writerow({
                "Name": label_name,
                "Mean": label_rates['mean'],
                "Lower bound": label_rates['lower_bound'],
                "Upper bound": label_rates['upper_bound'],
            })

    else:

        # Include all entries in the rate table.

        label_ids = [label_id for label_id in rates.keys()]
        # Get the label names we need with O(1) queries.
        label_names = {
            str(label['pk']): label['name']
            for label
            in Label.objects.filter(pk__in=label_ids).values('pk', 'name')
        }

        for label_id, label_rates in rates.items():
            writer.writerow({
                "Name": label_names[label_id],
                "Mean": label_rates['mean'],
                "Lower bound": label_rates['lower_bound'],
                "Upper bound": label_rates['upper_bound'],
            })
