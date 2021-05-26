import csv

from labels.models import Label
from .models import CalcifyRateTable


def get_default_calcify_tables():
    # Get the latest global table from each region.
    tables = CalcifyRateTable.objects.filter(source__isnull=True).order_by(
        'region', '-date').distinct('region')
    return {
        table.region: table
        for table in tables
    }


def get_default_calcify_rates():
    tables = get_default_calcify_tables()
    return {
        region: table.rates_json
        for region, table in tables.items()
    }


def rate_table_json_to_csv(csv_stream, rate_table):
    fieldnames = [
        "Label",
        "Mean rate",
        "Lower bound",
        "Upper bound",
    ]
    writer = csv.DictWriter(csv_stream, fieldnames)
    writer.writeheader()

    rates = rate_table.rates_json
    label_ids = [label_id for label_id in rates.keys()]
    # Get the label names we need with O(1) queries.
    label_names = {
        str(label['pk']): label['name']
        for label
        in Label.objects.filter(pk__in=label_ids).values('pk', 'name')
    }

    for label_id, label_rates in rates.items():
        writer.writerow({
            "Label": label_names[label_id],
            "Mean rate": label_rates['mean'],
            "Lower bound": label_rates['lower_bound'],
            "Upper bound": label_rates['upper_bound'],
        })
