from django.db import IntegrityError

from lib.tests.utils import CnStandardTest
from ..models import CalcifyRateTable


class RateTableUniqueTest(CnStandardTest):
    """Test calcification rate table uniqueness constraints."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.source_2 = cls.create_source(cls.user)

    def test_different_table_names_in_same_source(self):
        """Try to make 2 tables in the same source with different names."""
        CalcifyRateTable(
            name="Name 1", description="Desc", rates_json={},
            source=self.source).save()
        # Should have no error
        CalcifyRateTable(
            name="Name 2", description="Desc", rates_json={},
            source=self.source).save()

    def test_dupe_table_name_in_same_source(self):
        """Try to make 2 tables in the same source with the same name."""
        CalcifyRateTable(
            name="Name", description="Desc", rates_json={},
            source=self.source).save()

        table = CalcifyRateTable(
            name="Name", description="Desc", rates_json={},
            source=self.source)
        self.assertRaises(IntegrityError, table.save)

    def test_dupe_global_table_name(self):
        """Try to make 2 global tables with the same name."""
        CalcifyRateTable(
            name="Name", description="Desc", rates_json={},
            source=None).save()
        # Should have no error (unfortunately, but that's how it works)
        CalcifyRateTable(
            name="Name", description="Desc", rates_json={},
            source=None).save()

    def test_same_table_name_between_source_and_global(self):
        """Try to make a global table and a source table with the same name."""
        CalcifyRateTable(
            name="Name", description="Desc", rates_json={},
            source=self.source).save()
        # Should have no error
        CalcifyRateTable(
            name="Name", description="Desc", rates_json={},
            source=None).save()

    def test_same_table_name_between_sources(self):
        """Try to make 2 tables in different sources with the same name."""
        CalcifyRateTable(
            name="Name", description="Desc", rates_json={},
            source=self.source).save()
        # Should have no error
        CalcifyRateTable(
            name="Name", description="Desc", rates_json={},
            source=self.source_2).save()
