/*
For now, the functionality here only applies to the edit source form,
not the new source form. That may change later though.
 */
class SourceFormHelper {

    constructor() {
        this.extractorSettingField =
            document.getElementById('id_feature_extractor_setting');
        if (!this.extractorSettingField) {
            // Currently, everything in this class is only relevant when
            // the feature extractor setting field is there.
            return;
        }

        this.warningElement =
            document.getElementById('feature-extractor-change-warning');
        this.form =
            document.getElementById('source-form');

        // Move the warning element into the appropriate part of the form.
        let extractorSettingFieldGrid =
            this.extractorSettingField.closest('.form-fields-grid');
        extractorSettingFieldGrid.parentNode.insertBefore(
            this.warningElement, extractorSettingFieldGrid);

        // When field changes, update visibility of the warning.
        this.extractorSettingField.addEventListener(
            'change',
            this.updateVisibilityOfExtractorChangeWarning.bind(this));
        // Initialize visibility.
        this.updateVisibilityOfExtractorChangeWarning();

        // Custom form-submit handler to show a confirmation dialog.
        this.form.addEventListener(
            'submit',
            this.submitForm.bind(this));
    }

    /*
    See if the value of the extractor field is different from what the
    value initially was.
    */
    extractorHasChanged() {
        let originalValue = this.extractorSettingField.dataset.originalValue;
        return originalValue !== this.extractorSettingField.value;
    }

    /*
    If the extractor has changed, show the associated warning message.
    */
    updateVisibilityOfExtractorChangeWarning() {
        this.warningElement.hidden = !this.extractorHasChanged();
    }

    submitForm(event) {
        if (this.extractorHasChanged()) {
            if (!window.confirm(
                "Since the feature extractor has been changed,"
                + " this source's entire classifier history will be deleted,"
                + " and a new classifier will be generated."
                + " Is this OK?")) {
                event.preventDefault();
            }
        }
    }
}

export default SourceFormHelper;
