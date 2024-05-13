/* The following "singleton" design pattern is from
 * http://stackoverflow.com/a/1479341/
 */
var LabelsetAdd = (function() {

    var initialLabelIdsLookup = null;
    var initialLabelIdsCount = null;
    var labelIdsInConfirmedAnnotationsLookup = null;
    var hasClassifier = null;

    var $labelsetLabelIdsField = null;
    var $saveLabelsetButton = null;
    var $unusedLabelElementsContainer = null;
    var $searchStatus = null;
    var $searchField = null;
    var searchFieldTypingTimer = null;


    function get$addBox(labelId) {
        return $('.label-add-box[data-label-id="{0}"]'.format(labelId));
    }
    function get$removeBox(labelId) {
        return $('.label-remove-box[data-label-id="{0}"]'.format(labelId));
    }
    function get$detailBox(labelId) {
        return $('.label-detail-box[data-label-id="{0}"]'.format(labelId));
    }

    function isSelected(labelId) {
        return $('#selected-label-container').find(
            'div[data-label-id="{0}"]'.format(labelId)).length > 0;
    }
    function isInSearch(labelId) {
        return $('#label-search-result-container').find(
            'div[data-label-id="{0}"]'.format(labelId)).length > 0;
    }
    function isInUse(labelId) {
        return isSelected(labelId) || isInSearch(labelId);
    }
    function isInInitialLabels(labelId) {
        return labelId in initialLabelIdsLookup;
    }
    function isInAnnotations(labelId) {
        return labelId in labelIdsInConfirmedAnnotationsLookup;
    }

    function getSelectedIds() {
        var $container = $('#selected-label-container');
        var ids = [];

        $container.children().each(function() {
            ids.push(Number($(this).attr('data-label-id')));
        });
        return ids
    }
    function getNumSelected() {
        var $container = $('#selected-label-container');
        return $container.children().length;
    }
    function afterSelectionChange() {
        // Disable/enable save button based on whether the label ids
        // have changed from the initial ones.
        var ids = getSelectedIds();
        var i;
        var changedFromInitial = false;
        for (i = 0; i < ids.length; i++) {
            if (!isInInitialLabels(ids[i])) {
                changedFromInitial = true;
                break;
            }
        }
        if (ids.length !== initialLabelIdsCount) {
            changedFromInitial = true;
        }

        if (changedFromInitial) {
            $saveLabelsetButton.enable();
        }
        else {
            $saveLabelsetButton.disable();
        }
    }

    function enableAddButton(labelId) {
        var $addButton = get$addBox(labelId).find('.add-remove-button');
        $addButton.removeClass('disabled');
        $addButton.attr('title', "Add to labelset");
        $addButton.click(addLabelToSelected.curry(labelId));
    }
    function disableAddButton(labelId) {
        var $addButton = get$addBox(labelId).find('.add-remove-button');
        $addButton.addClass('disabled');
        $addButton.attr('title', "Label already in labelset");
        $addButton.unbind('click');
    }
    function enableRemoveButton(labelId) {
        var $addButton = get$removeBox(labelId).find('.add-remove-button');
        $addButton.removeClass('disabled');
        $addButton.attr('title', "Remove from labelset");
        $addButton.click(removeLabelFromSelected.curry(labelId));
    }
    function disableRemoveButton(labelId) {
        var $addButton = get$removeBox(labelId).find('.add-remove-button');
        $addButton.addClass('disabled');
        $addButton.attr(
            'title', "Can't remove; label is used in confirmed annotations");
        $addButton.unbind('click');
    }


    function submitSearch(searchValue) {
        removeAllLabelsFromSearch();

        if (searchValue.length < 3) {
            $searchStatus.text("Enter 3 or more characters.");
            return;
        }

        $.get(
            $searchField.attr('data-url'),
            {'search': searchValue},
            handleSearchResponse
        ).fail(util.handleServerError);
        $searchStatus.text("Searching...");
    }


    function handleSearchResponse(htmlResponse) {
        // The response here doesn't have a root node.
        // Fix that for easier jQuery parsing.
        var $htmlResponse = $('<div>' + htmlResponse + '</div>');
        var children = $htmlResponse.children();

        if (children.length > 0) {
            $searchStatus.text("{0} results found:".format(children.length));
            children.each(function () {
                var labelId = addResponseLabelToPage($(this));
                addLabelToSearch(labelId);
            });
        }
        else {
            $searchStatus.text("No results.");
        }
    }


    function addResponseLabelToPage($labelContainer) {
        var $labelAddBox = $labelContainer.find('.label-add-box');
        var $labelRemoveBox = $labelContainer.find('.label-remove-box');
        var $labelDetailBox = $labelContainer.find('.label-detail-box');

        var labelId = Number($labelAddBox.attr('data-label-id'));

        if (isInUse(labelId)) {
            // The label is already on the page. This container just provides
            // duplicate elements.
            $labelContainer.remove();
            return labelId;
        }

        $unusedLabelElementsContainer.append($labelAddBox);
        $unusedLabelElementsContainer.append($labelRemoveBox);
        $unusedLabelElementsContainer.append($labelDetailBox);

        // Detail-button click handlers
        $labelAddBox.find('.detail-button').click(
            showLabelDetail.curry(labelId)
        );
        $labelRemoveBox.find('.detail-button').click(
            showLabelDetail.curry(labelId)
        );

        // Add/remove handlers
        enableAddButton(labelId);
        enableRemoveButton(labelId);

        // We've moved or used all the container elements, so no use for the
        // container anymore
        $labelContainer.remove();

        return labelId;
    }


    function removeLabelFromPage(labelId) {
        get$addBox(labelId).remove();
        get$removeBox(labelId).remove();
        get$detailBox(labelId).remove();
    }


    function addLabelToSearch(labelId) {
        if (isInSearch(labelId)) { return; }

        // Add label-add box to selected.
        // We'll just assume this function is called such that the labels
        // stay in the desired order.
        $('#label-search-result-container').append(get$addBox(labelId));
    }


    function removeAllLabelsFromSearch() {
        $('#label-search-result-container').children().each(function() {
            var labelId = Number($(this).attr('data-label-id'));

            if (isSelected(labelId)) {
                // Only remove add box from search area
                $('#unused-label-elements-container').append(
                    get$addBox(labelId));
            }
            else {
                // Remove all boxes from page
                removeLabelFromPage(labelId);
            }
        });
    }


    function addLabelToSelected(labelId) {
        if (isSelected(labelId)) { return; }

        // Add label-remove box to selected;
        // maintain ordering based on label names
        var $removeBox = get$removeBox(labelId);
        var labelName = $removeBox.attr('data-label-name');
        var $selectedContainer = $('#selected-label-container');

        if ($selectedContainer.children().length === 0) {
            // Only box so far
            $removeBox.appendTo($selectedContainer);
        }
        else if (
            $selectedContainer.children().last().attr('data-label-name')
            <= labelName) {
            // Comes after the last box
            $removeBox.insertAfter($selectedContainer.children().last());
        }
        else {
            $selectedContainer.children().each(function() {
                var $thisRemoveBox = $(this);
                if (labelName < $thisRemoveBox.attr('data-label-name')) {
                    // Comes before this box
                    $removeBox.insertBefore($thisRemoveBox);
                    // Break from the each 'loop'
                    return false;
                }
            });
        }

        // Hide label-add box
        $('#unused-label-elements-container').append(get$addBox(labelId));

        // Update number of labels display
        $('#selected-label-count').text(getNumSelected());

        // Update the labelset form's field
        $labelsetLabelIdsField.val(getSelectedIds().join(','));

        // Disable the add button for this label
        disableAddButton(labelId);

        if (isInAnnotations(labelId)) {
            disableRemoveButton(labelId);
        }

        afterSelectionChange();
    }


    function removeLabelFromSelected(labelId) {
        if (!isSelected(labelId)) { return; }

        // Hide label-remove box
        $('#unused-label-elements-container').append(get$removeBox(labelId));

        // Update number of labels display
        $('#selected-label-count').text(getNumSelected());

        // Update the labelset form's field
        $labelsetLabelIdsField.val(getSelectedIds().join(','));

        // Re-enable the add button for this label
        enableAddButton(labelId);

        if (!isInUse(labelId)) {
            removeLabelFromPage(labelId);
        }

        afterSelectionChange();
    }


    function loadLabelDetailImages($detailBox) {
        var $lazyLoadingImages = $detailBox.find('img.lazy-load');
        $lazyLoadingImages.each(function() {
            var $this = $(this);
            // src = data-src
            $this.attr('src', $this.attr('data-src'));
        });
    }


    function showLabelDetail(labelId, event) {
        var $detailBox = get$detailBox(labelId);
        $detailBox.dialog({
            position: {my: 'left top', of: event, collision: 'fit'},
            width: 400,
            height: 300,
            modal: false
        });

        // Most of the label-detail content is loaded along with the label
        // button, except for the image(s) in the label detail box.
        // We load those only when the label detail box is actually shown
        // (i.e. now).
        loadLabelDetailImages($detailBox);
    }


    /* Public methods.
     * These are the only methods that need to be referred to as
     * <SingletonClassName>.<methodName>. */
    return {
        init: function(params) {
            labelIdsInConfirmedAnnotationsLookup = {};
            var idsList = params['labelIdsInConfirmedAnnotations'];
            var i;
            for (i = 0; i < idsList.length; i++) {
                labelIdsInConfirmedAnnotationsLookup[idsList[i]] = true;
            }

            $labelsetLabelIdsField = $('#id_label_ids');
            $unusedLabelElementsContainer =
                $('#unused-label-elements-container');
            var $labelsetForm = $('#labelset-form');
            $saveLabelsetButton = $labelsetForm.find('.save-button');

            initialLabelIdsLookup = {};
            initialLabelIdsCount = 0;
            $('#initial-label-container').children().each(function() {
                var labelId = addResponseLabelToPage($(this));
                initialLabelIdsLookup[labelId] = true;
                initialLabelIdsCount++;
                addLabelToSelected(labelId);
            });
            afterSelectionChange();

            $('#new-label-form-show-button').click(function() {
                $('#new-label-form-popup').dialog({
                    width: 600,
                    height: 600,
                    modal: false,
                    // This option adds an extra CSS class to the dialog.
                    // But this way of doing it is deprecated in jQuery 1.12+:
                    // http://api.jqueryui.com/dialog/#option-dialogClass
                    dialogClass: 'ui-dialog-form'
                });
            });

            $searchStatus = $('#label-search-status');
            $searchField = $('#label-search-field');

            hasClassifier = params['hasClassifier'];
            $labelsetForm.submit(function() {
                if ($saveLabelsetButton.is(':disabled')) {
                    // Even with the button disabled, the user might submit
                    // the form another way, so catch that case.
                    window.alert("No labelset changes detected.");
                    return false;
                }

                if (hasClassifier) {
                    return window.confirm(
                        "This will delete the source's classifiers." +
                        " Is this OK?");
                }

                return true;
            });

            // Update search results 0.75s after typing in the field
            $searchField.keyup(function() {
                window.clearTimeout(searchFieldTypingTimer);
                searchFieldTypingTimer = window.setTimeout(
                    submitSearch.curry($searchField.val()), 750);
            });
        },

        afterLabelCreated: function(htmlResponse) {
            // The response here should only have one top-level node,
            // corresponding to the one label that was created.
            var labelId = addResponseLabelToPage($(htmlResponse));
            addLabelToSelected(labelId);
        }
    }
})();
