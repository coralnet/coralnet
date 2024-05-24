from django.db import models


class SourceExtractorChoices(models.TextChoices):
    EFFICIENTNET = 'efficientnet_b0_ver1', "EfficientNet (default)"
    VGG16 = 'vgg16_coralnet_ver1', "VGG16 (legacy)"


class Extractors(models.TextChoices):
    EFFICIENTNET = (
        SourceExtractorChoices.EFFICIENTNET.value,
        SourceExtractorChoices.EFFICIENTNET.label)
    VGG16 = (
        SourceExtractorChoices.VGG16.value,
        SourceExtractorChoices.VGG16.label)
    DUMMY = 'dummy', "Dummy"


# Hard-coded shallow learners for each deep model.
# MLP is the better newer shallow learner, but we stayed with
# LR for the old extractor for backwards compatibility.
CLASSIFIER_MAPPINGS = {
    Extractors.VGG16.value: 'LR',
    Extractors.EFFICIENTNET.value: 'MLP',
    Extractors.DUMMY.value: 'LR',
}
