from lib.tests.utils_qunit import QUnitView
from ...forms import AnnotationImageOptionsForm


class AnnotationToolImageQUnitView(QUnitView):

    test_template_name = 'annotations/annotation_tool_image_qunit.html'
    javascript_functionality_modules = [
        'js/piexif.js',
    ]
    javascript_test_modules = ['js/tests/AnnotationToolImageQUnit.js']

    @property
    def test_template_contexts(self):

        return {
            'main': {
                'image_options_form': AnnotationImageOptionsForm(),
            }
        }
