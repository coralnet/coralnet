class MultiValueFieldHelper {

    static onControlFieldChange(
            controlField, conditionallyVisibleField, activatingValues) {
        // The field is shown if the control field matches any of
        // the activating values.
        conditionallyVisibleField.hidden = (
            !activatingValues.includes(controlField.value)
        );
    }

    static setUpFieldBasedVisibility(form) {

        let conditionallyVisibleElements = form.querySelectorAll(
            '[data-visibility-control-field]')

        conditionallyVisibleElements.forEach(function(element) {
            let controlFieldName = element.dataset.visibilityControlField;
            let controlField = form.querySelector(
                `[name="${controlFieldName}"]`);

            // This is expected to be a space-separated string, like the way
            // you'd specify multiple CSS classes on an element.
            let activatingValues =
                element.dataset.visibilityActivatingValues.split(' ');

            // When the control field changes, update visibility of the
            // conditionally visible field.
            let boundMethod = MultiValueFieldHelper.onControlFieldChange.bind(
                MultiValueFieldHelper,
                controlField, element, activatingValues
            );
            controlField.addEventListener('change', boundMethod);

            // Initialize field visibility.
            boundMethod();
        });
    }
}

export default MultiValueFieldHelper;
