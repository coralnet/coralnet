from lib.tests.utils_qunit import QUnitView
from ...forms import ImageUploadFrontendForm


class UploadImagesQUnitView(QUnitView):

    test_template_name = 'upload/upload_images_main_elements.html'
    javascript_functionality_modules = [
        'js/jquery.min.js', 'js/util.js', 'js/UploadImagesHelper.js']
    javascript_test_modules = ['js/tests/UploadImagesQUnit.js']

    @property
    def test_template_contexts(self):
        return {
            'main': {
                'images_form': ImageUploadFrontendForm(),
                'source': dict(id=1),
            },
        }
