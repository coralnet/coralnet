from lib.tests.utils_qunit import QUnitView
from ...forms import SourceForm
from ...models import Source


class SourceEditQUnitView(QUnitView):

    test_template_name = 'sources/source_edit_qunit.html'
    # base.html should already include jQuery, util, and AsyncMedia.
    javascript_functionality_modules = []
    javascript_test_modules = ['js/tests/SourceEditQUnit.js']

    @property
    def test_template_contexts(self):
        source = Source(
            id=0,
            enable_robot_classifier=True,
            confidence_threshold=80,
            feature_extractor_setting='efficientnet_b0_ver1',
        )
        return {
            'main': {
                'source': source,
                'edit_source_form': SourceForm(instance=source),
                'map_minimum_images': 5,
            },
        }
