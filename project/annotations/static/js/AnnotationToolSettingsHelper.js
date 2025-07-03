var ATS = {

    $saveButton: undefined,
    $settingsForm: undefined,

    annotationToolSettingsSaveUrl: undefined,

    settings: {
        pointMarker: undefined,
        pointMarkerSize: undefined,
        pointMarkerIsScaled: undefined,
        pointNumberSize: undefined,
        pointNumberIsScaled: undefined,
        unannotatedColor: undefined,
        robotAnnotatedColor: undefined,
        humanAnnotatedColor: undefined,
        selectedColor: undefined,
        showMachineAnnotations: undefined
    },
    $fields: {
        pointMarker: undefined,
        pointMarkerSize: undefined,
        pointMarkerIsScaled: undefined,
        pointNumberSize: undefined,
        pointNumberIsScaled: undefined,
        unannotatedColor: undefined,
        robotAnnotatedColor: undefined,
        humanAnnotatedColor: undefined,
        selectedColor: undefined
    },
    validators: {
        pointMarkerSize: undefined,
        pointNumberSize: undefined
    },


    init: function(params) {
        ATS.$saveButton = $('#saveSettingsButton');
        ATS.$settingsForm = $('#annotationToolSettingsForm');

        ATS.annotationToolSettingsSaveUrl =
            params.annotationToolSettingsSaveUrl;

        ATS.$fields.pointMarker = $('#id_point_marker');
        ATS.$fields.pointMarkerSize = $('#id_point_marker_size');
        ATS.$fields.pointMarkerIsScaled = $('#id_point_marker_is_scaled');
        ATS.$fields.pointNumberSize = $('#id_point_number_size');
        ATS.$fields.pointNumberIsScaled = $('#id_point_number_is_scaled');
        ATS.$fields.unannotatedColor = $('#id_unannotated_point_color');
        ATS.$fields.robotAnnotatedColor = $('#id_robot_annotated_point_color');
        ATS.$fields.humanAnnotatedColor = $('#id_human_annotated_point_color');
        ATS.$fields.selectedColor = $('#id_selected_point_color');
        ATS.$fields.showMachineAnnotations = $('#id_show_machine_annotations');

        ATS.validators.pointMarkerSize = ATS.pointMarkerSizeIsValid;
        ATS.validators.pointNumberSize = ATS.pointNumberSizeIsValid;

        // Initialize settings
        ATS.updateSettingsObj();

        // When a settings field is changed:
        // - enable the save button.
        // - update the settings object, which the annotation tool code
        //   refers to during point drawing, etc.
        // - redraw all points
        for (var fieldName in ATS.$fields) {
            if (!ATS.$fields.hasOwnProperty(fieldName)){ continue; }

            ATS.$fields[fieldName].change( function() {
                ATS.enableSaveButton();
                ATS.updateSettingsObj();
                AnnotationToolHelper.redrawAllPoints();
            });
        }

        // When the save button is clicked, save.
        ATS.$saveButton.click(ATS.saveSettings);
    },

    /* Update: $fields -> settings.
     * Revert settings -> $fields for any erroneous field values.
     */
    updateSettingsObj: function() {
        for (var fieldName in ATS.$fields) {
            if (!ATS.$fields.hasOwnProperty(fieldName)){ continue; }

            var $field = ATS.$fields[fieldName];

            if (ATS.validators.hasOwnProperty(fieldName)) {
                var fieldIsValid = ATS.validators[fieldName]();
                if (fieldIsValid === false) {
                    ATS.revertField(fieldName);
                    continue;
                }
            }

            // Update the setting
            if ($field.attr('type') === 'checkbox')
                ATS.settings[fieldName] = $field.prop('checked');
            else if ($field.hasClass('jscolor'))
                ATS.settings[fieldName] = '#' + $field.val();
            else if ($field.attr('type') === 'number')
                // Only integer fields right now, no floats
                ATS.settings[fieldName] = parseInt($field.val(), 10);
            else
                ATS.settings[fieldName] = $field.val();
        }
    },

    pointMarkerSizeIsValid: function() {
        var fieldValue = ATS.$fields.pointMarkerSize.val();

        return (util.representsInt(fieldValue)
                && parseInt(fieldValue, 10) >= 1
                && parseInt(fieldValue, 10) <= 30);
    },
    pointNumberSizeIsValid: function() {
        var fieldValue = ATS.$fields.pointNumberSize.val();

        return (util.representsInt(fieldValue)
            && parseInt(fieldValue, 10) >= 1
            && parseInt(fieldValue, 10) <= 40);
    },
    revertField: function(fieldName) {
        ATS.$fields[fieldName].val(ATS.settings[fieldName]);
    },

    enableSaveButton: function() {
        ATS.$saveButton.removeAttr('disabled');
        ATS.$saveButton.text("Save settings");
    },
    saveSettings: function() {
        ATS.$saveButton.attr('disabled', 'disabled');
        ATS.$saveButton.text("Now saving...");

        $.ajax({
            // Data to send in the request
            data: ATS.$settingsForm.serialize(),

            // Callback on successful response
            success: ATS.saveSettingsAjaxCallback,

            type: 'POST',

            // URL to make request to
            url: ATS.annotationToolSettingsSaveUrl
        });
    },
    saveSettingsAjaxCallback: function(returnDict) {
        if (returnDict.error) {
            ATS.$saveButton.text("Error");
            alert(returnDict.error);
            return;
        }

        ATS.$saveButton.text("Settings saved");
    }
};