from django.db import IntegrityError

from lib.tests.utils import BaseTest
from ..models import Label, LabelGroup, LabelSet, LocalLabel


class LocalLabelTest(BaseTest):

    def test_unique(self):
        """
        Creating dupe entries (same global label, same labelset)
        should be disallowed at the database level.

        This shouldn't be possible to attempt through CoralNet forms
        except in a race condition of some kind, which is why
        we're doing manual instance creation for easier testing.
        """
        group = LabelGroup(name="Group 1", code='1')
        group.save()
        label_a = Label(name="A", default_code='A', group=group)
        label_a.save()
        label_b = Label(name="B", default_code='B', group=group)
        label_b.save()
        labelset = LabelSet()
        labelset.save()

        entry_a = LocalLabel(
            labelset=labelset, global_label=label_a, code='A')
        entry_a.save()
        entry_b = LocalLabel(
            labelset=labelset, global_label=label_b, code='B')
        entry_b.save()

        entry_a2 = LocalLabel(
            labelset=labelset, global_label=label_a, code='A2')
        with self.assertRaises(IntegrityError) as cm:
            entry_a2.save()
        self.assertIn(
            "duplicate key value violates unique constraint",
            str(cm.exception))
