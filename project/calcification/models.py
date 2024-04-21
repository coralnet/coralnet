from django.db import models

from sources.models import Source


class CalcifyRateTable(models.Model):
    name = models.CharField(max_length=80)
    description = models.TextField(max_length=500, blank=True)
    date = models.DateTimeField(auto_now=True, editable=False)

    # The calcification rate data. It's more convenient to store it as JSON
    # than as a "table" format.
    # Structure:
    # {
    #   <label ID>: {
    #     mean: <float>, lower_bound: <float>, upper_bound: <float>
    #   },
    #   <another label ID>: {
    #     mean: <float>, lower_bound: <float>, upper_bound: <float>
    #   },
    #   ...
    # }
    rates_json = models.JSONField()

    # Source that the rate table belongs to.
    # Null for site-wide default rate tables.
    source = models.ForeignKey(Source, on_delete=models.CASCADE, null=True)

    # Name of the geographic region that the rate table is for
    # (e.g. Indo-Pacific).
    # Should be required for site-wide default rate tables; optional for
    # tables belonging to a source.
    region = models.CharField(max_length=30, blank=True)

    class Meta:
        constraints = [
            # Each table name must be unique within a particular source.
            #
            # Note: This does NOT prevent duplicate names among default
            # (global) tables - the case where source is NULL.
            # https://stackoverflow.com/questions/4081783/unique-key-with-nulls
            # So be careful when creating default tables, since creating
            # duplicate names can lead to confusion.
            models.UniqueConstraint(
                name="unique_name_within_source", fields=['source', 'name']),
        ]
        verbose_name = "Calcification rate table"

    def __str__(self):
        """
        To-string method.
        """
        if self.source:
            return self.source.name + " - " + self.name
        else:
            return "DEFAULT TABLE - " + self.name
