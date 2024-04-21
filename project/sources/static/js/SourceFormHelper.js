var SourceFormHelper = {

    /*
    See if the value of the extractor field is different from what the
    value initially was.
    */
    extractorHasChanged: function() {
        var extractorSettingElement = document.getElementById(
            'id_feature_extractor_setting');

        if (!extractorSettingElement.hasAttribute('data-original-value')) {
            // If no original value, then this is the new source form, and
            // we just report as not changed.
            return false;
        }

        var originalValue = extractorSettingElement.getAttribute(
            'data-original-value');
        var currentValue = extractorSettingElement.value;

        return originalValue !== currentValue;
    },

    /*
    If the extractor has changed, show the associated warning message.
    */
    updateVisibilityOfExtractorChangeWarning: function() {
        var warningElement = document.getElementById(
            'feature-extractor-change-warning');
        if (!warningElement) {
            // New source form. No action needed here.
            return;
        }

        if (SourceFormHelper.extractorHasChanged()) {
            warningElement.style.display = 'block';
        }
        else {
            warningElement.style.display = 'none';
        }
    },

    submitEditForm: function() {
        if (SourceFormHelper.extractorHasChanged()) {
            return window.confirm(
                "Since the feature extractor has been changed,"
                + " this source's entire classifier history will be deleted,"
                + " and a new classifier will be generated."
                + " Is this OK?");
        }

        return true;
    }
};

util.addLoadEvent(SourceFormHelper.updateVisibilityOfExtractorChangeWarning);
