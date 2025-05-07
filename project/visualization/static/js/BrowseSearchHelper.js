class BrowseSearchHelper {

    static setupSearchSubmitLogic(form) {
        let boundMethod = BrowseSearchHelper.onSearchSubmit.bind(
            BrowseSearchHelper, form);
        form.addEventListener('submit', boundMethod);
    }

    static onSearchSubmit(form) {
        // Disable any blank fields so that they don't get submitted and
        // don't clutter up the URL params.
        form.querySelectorAll('input, select').forEach((field) => {
            if (field.value === '') {
                field.disabled = true;
            }
        });

        // Then after returning from here, the default submit behavior
        // should run, which is submitting the form to the server.
    }
}

export default BrowseSearchHelper;
