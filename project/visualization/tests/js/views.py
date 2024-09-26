from lib.forms import DummyForm
from lib.tests.utils_qunit import QUnitView
from lib.utils import paginate


class BrowseImagesActionsQUnitView(QUnitView):

    test_template_name = 'visualization/browse_images_actions.html'
    javascript_functionality_modules = [
        'js/jquery.min.js', 'js/util.js', 'js/BrowseActionHelper.js']
    javascript_test_modules = ['js/tests/BrowseImagesActionsTest.js']

    @property
    def default_test_template_context(self):
        return {
            'source': dict(pk=1, confidence_threshold=80),
            'page_results': paginate(
                results=[1, 2, 3, 4], items_per_page=3, request_args=dict())[0],
            'links': dict(
                annotation_tool_first_result='/annotate_all/',
                annotation_tool_page_results=['/annotate_selected/']),
            'empty_message': "",

            'hidden_image_form': None,

            'can_annotate': True,
            'can_export_cpc_annotations': True,
            'can_manage_source_data': True,

            'export_annotations_form': DummyForm(),
            'export_image_covers_form': DummyForm(),

            'export_calcify_rates_form': DummyForm(),
            'calcify_table_form': DummyForm(),
            'source_calcification_tables': [dict(
                name="Table name", pk=2, description="Table description")],
            'global_calcification_tables': [dict(
                name="Default table", pk=1, description="Table description")],
            'cpc_export_form': DummyForm(),
        }

    @property
    def test_template_contexts(self):
        return {
            'all_images': self.create_test_template_context(),
            'with_search_filters': self.create_test_template_context(**{
                'hidden_image_form': DummyForm(
                    aux1='Site A',
                    photo_date_0='date_range',
                    photo_date_1='',
                    photo_date_2='',
                    photo_date_3='2021-01-01',
                    photo_date_4='2021-06-30',
                ),
            }),
        }
