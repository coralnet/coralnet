from django import forms
from django.core.exceptions import ValidationError

from lib.forms import FieldsetsFormComponent, GridFormRenderer
from .common import ClassifierStatuses
from .models import SourceClassifierOptions


class BackendMainForm(forms.Form):
    confidence_threshold = forms.IntegerField(
        min_value=0, max_value=100)
    label_mode = forms.ChoiceField(
        choices=(('full', 'Labels'), ('func', 'Functional Groups')),
        initial='full')


class CmTestForm(forms.Form):
    nlabels = forms.IntegerField(min_value=0, max_value=200)    
    namelength = forms.IntegerField(min_value=10, max_value=100)


# This probably would go better in a '?' button's help text,
# which is generally defined in an HTML template.
confidence_threshold_help_text = \
"""The CoralNet alleviate feature offers a trade-off between fully automated and fully manual annotation. This is done by auto-accepting machine annotations when they are sufficiently confident.

This auto-acceptance happens when you enter the annotation tool for an image. Effectively, the classifier's most confident points are "alleviated" from your annotation workload (for that image). Alleviated annotation decisions are treated as 'Confirmed', and are included when you export your annotations.

Here you can control this functionality by specifying the classifier confidence threshold. For example, with a 90% confidence threshold, all point annotations for which the classifier is more than 90% confident will be auto-confirmed when you enter the annotation tool.

Once you've trained or chosen a source classifier, you can visit the source's Backend page to see the trade-off between confidence threshold, the fraction of points above each threshold, and the annotation accuracy. We recommend that you leave the confidence threshold at 100% (meaning, nothing gets auto-confirmed) until you have seen this trade-off curve.

The best confidence threshold to use depends on your research goals, but we'll note that <a href="https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0130312">this study</a> suggests a 5% drop in annotation accuracy has marginal (if any) impact on derived cover estimates. Therefore, you might consider using a confidence threshold corresponding to a 5% drop in accuracy.
"""


class SourceClassifierOptionsForm(FieldsetsFormComponent, forms.ModelForm):

    class Meta:
        model = SourceClassifierOptions
        fields = [
            'trains_own_classifiers', 'deployed_classifier',
            'feature_extractor_setting',
            'confidence_threshold',
        ]
        widgets = {
            'trains_own_classifiers': forms.Select(
                choices=[(True, "Train"), (False, "Use existing")]),
            'deployed_classifier': forms.TextInput(attrs={
                'size': 6,
                'data-visibility-control-field': 'trains_own_classifiers',
                'data-visibility-activating-values': 'False',
            }),
            'confidence_threshold': forms.NumberInput(
                attrs={'min': 0, 'max': 100, 'size': 3}),
        }
        labels = {
            'trains_own_classifiers': "Classifier mode",
            'deployed_classifier': "Classifier global ID number",
        }
        error_messages = {
            'deployed_classifier': {
                'invalid_choice': "This isn't a valid classifier ID.",
            },
        }

    default_renderer = GridFormRenderer

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)

        if self.is_bound and not request:
            raise ValueError(
                "request kwarg is required if this form is bound.")
        self.request = request

        self.is_edit_form = self.instance.pk is not None

        if self.is_edit_form:
            # Edit source form should have a way to detect and indicate (via
            # Javascript) that the feature extractor setting has changed.
            self.fields['feature_extractor_setting'].widget.attrs.update({
                'data-original-value': self.instance.feature_extractor_setting,
            })

            if self.instance.deployed_classifier:
                self.fields['deployed_classifier'].help_text = (
                    f"Currently selected:"
                    f" {self.instance.get_deployed_classifier_html()}"
                )
        else:
            # Remove this field from the new source form. It's generally
            # a step to take later after seeing how the classifier performs.
            del self.fields['confidence_threshold']

        # This fieldsets definition uses stuff that can't be evaluated
        # at import time, such as reverse(), so we define it
        # in __init__() here.
        self.fieldsets = [

            dict(
                header="Automatic classification",
                subfieldsets=[
                    dict(
                        header="Classifiers",
                        help_text="""Your source can either use its own image and annotation data to train new classifiers (the default behavior), or you can specify an existing CoralNet classifier to use.
                        
                            If using an existing classifier from another source, this source's labelset must match the classifier's source's labelset. We'll automatically create a matching labelset as needed.""",
                        fields=[
                            'trains_own_classifiers',
                            'deployed_classifier',
                        ],
                    ),

                    dict(
                        header="Feature extractor ('Train' classifier mode only)",
                        help_text="""Before machine classifiers can process images, CoralNet must extract numeric features from the images first. In the 'Train' classifier mode, this setting determines the format used. In the 'Use existing' classifier mode, the extractor setting of that classifier's source determines the format used.
                        
                        We recommend the EfficientNet extractor for all use-cases. It is faster and 2-3% more accurate on average. It is a more modern neural network architecture and trained on more data. The legacy VGG16 extractor is provided only for sources that want to retain their old classifiers, for example, if they are already deployed in a survey.""",
                        fields=['feature_extractor_setting'],
                    ),

                    dict(
                        header="Level of alleviation",
                        help_text=confidence_threshold_help_text,
                        fields=['confidence_threshold'],
                    ),
                ],
            ),
        ]

    def clean_deployed_classifier(self):
        deployed_classifier = self.cleaned_data['deployed_classifier']

        if deployed_classifier is not None:

            if deployed_classifier.status != ClassifierStatuses.ACCEPTED.value:
                raise ValidationError(
                    "This isn't a valid classifier ID.",
                    code='classifier_not_accepted',
                )

            source_accessible = deployed_classifier.source.visible_to_user(
                self.request.user)
            if not source_accessible:
                raise ValidationError(
                    "You don't have access to this classifier's source.",
                    code='source_access_denied',
                )

            if self.is_edit_form and self.instance.source.labelset is not None:
                if not self.instance.source.labelset.has_same_labels(
                    deployed_classifier.source.labelset
                ):
                    raise ValidationError(
                        "This source's labelset must match the"
                        " classifier's source's labelset.",
                        code='labelset_mismatch',
                    )

        return deployed_classifier

    def save_new(self, source, **kwargs):
        self.instance.source = source
        return self.save(**kwargs)

    def save(self, **kwargs):
        if self.instance.trains_own_classifiers:
            if self.is_edit_form:
                self.instance.deployed_classifier = \
                    self.instance.source.last_accepted_classifier
            else:
                self.instance.deployed_classifier = None

        if self.instance.deployed_classifier:
            self.instance.deployed_source_id = \
                self.instance.deployed_classifier.source_id
        else:
            self.instance.deployed_source_id = None

        # Per the above, if deployed_classifier is being nulled through this
        # form, we also null deployed_source_id.
        #
        # Besides this form, the other ways that deployed_classifier can be
        # nulled are:
        # 1. That classifier getting deleted.
        # 2. That classifier's source changing its labelset.
        # In these cases it's good to keep deployed_source_id unchanged
        # instead.
        # This distinguishes the source's state from a source that had
        # never chosen a classifier, and lets us display a reminder like
        # "you previously chose a classifier from this source".

        if self.instance.deployed_classifier and not self.instance.source.labelset:
            # No labelset yet; copy the labelset the deployed
            # classifier uses. This applies to both new source and edit source.
            copied_labelset = (
                self.instance.deployed_classifier.source
                .labelset.save_copy())
            self.instance.source.labelset = copied_labelset
            self.instance.source.save()

        return super().save(**kwargs)
