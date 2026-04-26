var AnnotationToolHelper = (function() {

    // Compatibility
    var isMac = util.osIsMac();

    // URLs
    var saveAnnotationsUrl = null;
    var isAnnotationAllDoneUrl = null;

    // Helper instances
    var imageHelper = null;

    // HTML elements
    var annotationArea = null;
    var annotationList = null;
    var pointFieldRows = [];
    var pointFields = [];
    var pointRobotFields = [];
    var $pointFields = null;

    var $annotationField = null;
    var $annotationFieldFixedContainer = null;
    var $annotationFieldImageContainer = null;

    var $rectangleSelectListener = null;
    var $rectangleSelectArea = null;

    var imageArea = null;
    var pointsCanvas = null;
    var listenerElmt = null;
    var saveButton = null;

    // Annotation related
    var labelCodes = [];
    var labelCodesToNames = {};

    // Canvas related
    var context = null;
    var canvasPoints = [], imagePoints = null;
    var numOfPoints = null;
    var NUMBER_FONT_FORMAT_STRING = "bold {0}px sans-serif";

    // Border where the canvas is drawn, but the image is not.
    // This is used to fully show the points that are located near the edge of the image.
    var IMAGE_GUTTER = 25;
    var IMAGE_GUTTER_COLOR = "#BBBBBB";

    // Related to possible states of each annotation point
    var pointContentStates = [];
    var pointGraphicStates = [];
    // Graphic state values
    var STATE_UNANNOTATED = 0;
    var STATE_ROBOT = 1;
    var STATE_ANNOTATED = 2;
    var STATE_SELECTED = 3;
    var STATE_NOTSHOWN = 4;

    // Point number outline color
    var OUTLINE_COLOR = "#000000";

    // Point viewing mode
    var pointViewMode = null;
    var POINTMODE_ALL = 0;
    var POINTMODE_SELECTED = 1;
    var POINTMODE_NONE = 2;

    // The original image's dimensions
    var IMAGE_FULL_WIDTH = null;
    var IMAGE_FULL_HEIGHT = null;
    // The area that the image is permitted to fill
    var IMAGE_AREA_WIDTH = null;
    var IMAGE_AREA_HEIGHT = null;
    // The canvas area, where drawing is allowed
    var ANNOTATION_AREA_WIDTH = null;
    var ANNOTATION_AREA_HEIGHT = null;
    // Label button grid
    var BUTTONS_PER_ROW = 10;
    var LABEL_BUTTON_WIDTH = null;

    // Display parameters of the image.
    // > 1 zoomFactor means larger than original image
    // zoom levels start at 0 (fully zoomed out) and go up like 1,2,3,etc.
    var imageDisplayWidth = null;
    var imageDisplayHeight = null;
    var zoomFactor = null;
    var zoomLevel = null;
    var ZOOM_FACTORS = {};
    var ZOOM_INCREMENT = 1.5;
    var HIGHEST_ZOOM_LEVEL = 8;
    // Current display position of the image.
    // centerOfZoom is in terms of raw-image coordinates.
    // < 0 offset means top left corner is not visible.
    var centerOfZoomX = null;
    var centerOfZoomY = null;
    var imageLeftOffset = null;
    var imageTopOffset = null;

    var rectangleStartX = null;
    var rectangleStartY = null;

    // Size of sub-windows.
    var SUB_WINDOW_MIN_WIDTH = 500;
    var SUB_WINDOW_MIN_HEIGHT = 500;
    var SUB_WINDOW_PCT_WIDTH = 30;
    var SUB_WINDOW_PCT_HEIGHT = 90;
    var subWindowWidth = null;
    var subWindowHeight = null;

    // Z-indices.
    var ZINDEX_IMAGE_CANVAS = 0;
    var ZINDEX_POINTS_CANVAS = 1;
    var ZINDEX_IMAGE_LISTENER = 2;
    var ZINDEX_ANNOTATION_FIELD = 3;
    var ZINDEX_RECTANGLE_SELECT_AREA = 4;
    var ZINDEX_RECTANGLE_SELECT_LISTENER = 5;
    var ZINDEX_SUBWINDOW = 6;



    //
    // CANVAS methods
    //

    function getImageCanvas() {
        return imageHelper.imageCanvas;
    }

    /*
     * Based on the current zoom level and focus of the zoom, position and
     * set up the image and on-image listener elements.
     */
    function setupImageArea() {
        imageDisplayWidth = IMAGE_FULL_WIDTH * zoomFactor;
        imageDisplayHeight = IMAGE_FULL_HEIGHT * zoomFactor;

        // Round off imprecision, so that if the display width is supposed to be
        // equal to the image area width, then they will actually be equal.
        imageDisplayWidth = parseFloat(imageDisplayWidth.toFixed(3));
        imageDisplayHeight = parseFloat(imageDisplayHeight.toFixed(3));

        // Position the image within the image area.
        // Negative offsets means the top-left corner is offscreen.
        // Positive offsets means there's extra space around the image.
        //
        // Allow a certain maximum amount of extra space around the image
        // so the user can get a sense that they are near the edge of
        // the image.
        //
        // Allow more extra space only if the image display is smaller than
        // the image area.

        if (imageDisplayWidth <= IMAGE_AREA_WIDTH)
            imageLeftOffset = (IMAGE_AREA_WIDTH - imageDisplayWidth) / 2;
        else {
            var centerOfZoomInDisplayX = centerOfZoomX * zoomFactor;
            var leftEdgeInDisplayX = centerOfZoomInDisplayX - (IMAGE_AREA_WIDTH / 2);
            var rightEdgeInDisplayX = centerOfZoomInDisplayX + (IMAGE_AREA_WIDTH / 2);

            // Enforce max gutter space on left, and max gutter space on right,
            if (leftEdgeInDisplayX < -IMAGE_GUTTER)
                imageLeftOffset = IMAGE_GUTTER;
            else if (rightEdgeInDisplayX > imageDisplayWidth+IMAGE_GUTTER)
                imageLeftOffset = -(imageDisplayWidth+IMAGE_GUTTER - IMAGE_AREA_WIDTH);
            else
                imageLeftOffset = -leftEdgeInDisplayX;
        }

        if (imageDisplayHeight <= IMAGE_AREA_HEIGHT)
            imageTopOffset = (IMAGE_AREA_HEIGHT - imageDisplayHeight) / 2;
        else {
            var centerOfZoomInDisplayY = centerOfZoomY * zoomFactor;
            var topEdgeInDisplayY = centerOfZoomInDisplayY - (IMAGE_AREA_HEIGHT / 2);
            var bottomEdgeInDisplayY = centerOfZoomInDisplayY + (IMAGE_AREA_HEIGHT / 2);

            // Enforce max gutter space on top, and max gutter space on bottom.
            if (topEdgeInDisplayY < -IMAGE_GUTTER)
                imageTopOffset = IMAGE_GUTTER;
            else if (bottomEdgeInDisplayY > imageDisplayHeight+IMAGE_GUTTER)
                imageTopOffset = -(imageDisplayHeight+IMAGE_GUTTER - IMAGE_AREA_HEIGHT);
            else
                imageTopOffset = -topEdgeInDisplayY;
        }

        // Round off imprecision, so that we don't have any extremely small offsets
        // that get expressed in scientific notation (that confuses jQuery's number parsing).
        imageLeftOffset = parseFloat(imageLeftOffset.toFixed(3));
        imageTopOffset = parseFloat(imageTopOffset.toFixed(3));

        // Set styling properties for the image canvas.
        //
        // We need to set both the width and height. If we set only one
        // dimension, the browser MAY auto-scale the other dimension, but it's
        // not guaranteed (e.g. with very large sizes in Chromium-based
        // browsers).
        $(getImageCanvas()).css({
            "width": imageDisplayWidth,
            "height": imageDisplayHeight,
            "left": imageLeftOffset,
            "top": imageTopOffset,
            "z-index": ZINDEX_IMAGE_CANVAS
        });

        // Set styling properties for the listener element:
        // An invisible element that sits on top of the image
        // and listens for mouse events.
        // Since it has to be on top to listen for mouse events,
        // the z-index should be set accordingly.
        $(listenerElmt).css({
            "width": imageDisplayWidth,
            "height": imageDisplayHeight,
            "left": imageLeftOffset,
            "top": imageTopOffset,
            "z-index": ZINDEX_IMAGE_LISTENER
        });

        // Set styling properties for the rectangle select listener, too.
        $rectangleSelectListener.css({
            "width": imageDisplayWidth,
            "height": imageDisplayHeight,
            "left": imageLeftOffset,
            "top": imageTopOffset
        });
    }

    /*
     * Clear the points canvas and reset the context.
     */
    function resetCanvas() {
        // Get the original (untranslated) context back.
        context.restore();
        // And save the context again for the next time we have to translate.
        context.save();

        // Clear the entire canvas.
        context.clearRect(0, 0, pointsCanvas.width, pointsCanvas.height);

        // If you designed the canvas and image area such that they don't
        // line up exactly, then translate the context.
        // That'll allow you to pretend that canvas coordinates = image area coordinates.
        context.translate(0,0);
    }

    function zoomIn(e) {
        zoom('in', e);
    }
    function zoomOut(e) {
        zoom('out', e);
    }
    function zoomFit(e) {
        zoom('fit', e);
    }
    function zoom(zoomType, e) {
        var zoomLevelChange;

        if (zoomType === 'in') {
            if (zoomLevel === HIGHEST_ZOOM_LEVEL)
                return;

            zoomLevelChange = 1;
        }
        else if (zoomType === 'out') {
            // 0 is the lowest zoom level.
            if (zoomLevel === 0)
                return;

            zoomLevelChange = -1;
        }
        else if (zoomType === 'fit') {
            // Zoom all the way out, i.e. get the zoom level to 0.
            if (zoomLevel === 0)
                return;

            zoomLevelChange = -zoomLevel;
        }

        if (e !== undefined && e.type.indexOf('mouse') !== -1) {
            // Zoom on click: zoom into the part that was clicked. (Make sure
            // to use the old zoom factor for calculating the click position)
            var imagePos = getImagePosition(e);
            centerOfZoomX = imagePos[0];
            centerOfZoomY = imagePos[1];
        }
        // Else, zoom with hotkey: don't change the center of zoom, just the
        // zoom level.

        zoomLevel += zoomLevelChange;
        zoomFactor = ZOOM_FACTORS[zoomLevel];

        // Adjust the image and point coordinates.
        setupImageArea();
        getCanvasPoints();

        // Redraw all points.
        redrawAllPoints();

        // Move the annotation field to get alongside the current point again.
        moveAnnotationFieldImageContainer();
    }

    /* Get the mouse position in the canvas element:
     (mouse's position in the HTML document) minus
     (canvas element's position in the HTML document). */
    function getImageElmtPosition(e) {
        var x;
        var y;

        /* The method for getting the mouse position in the HTML document
         varies depending on the browser: can be based on pageX/Y or clientX/Y. */
        if (e.pageX !== undefined && e.pageY !== undefined) {
            x = e.pageX;
            y = e.pageY;
        }
        else {
            x = e.clientX + document.body.scrollLeft +
                document.documentElement.scrollLeft;
            y = e.clientY + document.body.scrollTop +
                document.documentElement.scrollTop;
        }

        // Get the x,y relative to the upper-left corner of the image
        var elmt = getImageCanvas();
        while (elmt !== null) {
            x -= elmt.offsetLeft;
            y -= elmt.offsetTop;
            elmt = elmt.offsetParent;
        }

        return [x,y];
    }

    function getImagePosition(e) {
        var imageElmtPosition = getImageElmtPosition(e);
        var imageElmtX = imageElmtPosition[0];
        var imageElmtY = imageElmtPosition[1];

        var x = imageElmtX / zoomFactor;
        var y = imageElmtY / zoomFactor;

        return [x,y];
    }

    function getNearestPoint(e) {
        // Mouse's position in the canvas element
        var imagePosition = getImagePosition(e);
        var x = imagePosition[0];
        var y = imagePosition[1];

        var minDistance = Infinity;
        var closestPoint = null;

        for (var i = 0; i < imagePoints.length; i++) {
            var currPoint = imagePoints[i];

            // Don't count points that are offscreen.
            if (pointIsOffscreen(currPoint.point_number))
                continue;

            var xDiff = x - currPoint.column;
            var yDiff = y - currPoint.row;
            var distance = Math.sqrt((xDiff*xDiff) + (yDiff*yDiff));

            if (distance < minDistance) {
                minDistance = distance;
                closestPoint = currPoint.point_number;
            }
        }

        return closestPoint;
    }

    function centerOnPoint(pointNum) {
        // Shift the center of zoom to this point.
        centerOfZoomX = imagePoints[pointNum-1].column;
        centerOfZoomY = imagePoints[pointNum-1].row;

        // If we're zoomed in at all, complete the center-of-zoom-shift process.
        if (zoomLevel > 0) {

            // Adjust the image and point coordinates.
            setupImageArea();
            getCanvasPoints();

            // Redraw all points.
            redrawAllPoints();
        }
    }

    function onCanvasClick(e) {

        var mouseButton = util.identifyMouseButton(e);
        var clickType;
        var nearestPoint;

        // Get the click type (in Windows terms)...

        if ((!isMac && e.ctrlKey && mouseButton === "LEFT")
            || isMac && e.metaKey && mouseButton === "LEFT") {
            // Ctrl-click non-Mac OR Cmd-click Mac
            clickType = "ctrlClick";
        }
        else if (mouseButton === "RIGHT"
            || (isMac && e.ctrlKey && mouseButton === "LEFT")) {
            // Right-click OR Ctrl-click Mac
            clickType = "rightClick";
        }
        else if (e.shiftKey && mouseButton === "LEFT") {
            // Shift-click
            clickType = "shiftClick";
        }
        else if (mouseButton === "LEFT") {
            // Other left click
            clickType = "leftClick";
        }
        else {
            // Middle or other click
            clickType = "unknown";
        }

        // Carry out the click action.

        // Toggle the nearest point.
        if (clickType === "ctrlClick") {

            // This only works if we're displaying all points.
            if (pointViewMode !== POINTMODE_ALL)
                return;

            nearestPoint = getNearestPoint(e);
            toggle(nearestPoint);
            $annotationField.focus();
        }
        // Select the nearest point and unselect all others.
        else if (clickType === "shiftClick") {
            nearestPoint = getNearestPoint(e);
            selectOnly([nearestPoint]);
            $annotationField.focus();
        }
        // Increase zoom on the image display.
        else if (clickType === "leftClick") {
            zoomIn(e);
        }
        // Decrease zoom on the image display.
        else if (clickType === "rightClick") {
            zoomOut(e);
        }
    }

    /*
     Raw image coordinates -> Canvas coordinates:
     (1) Scale the raw image coordinates by the image zoom factor.
     (2) Account for image position offset.
     (3) Don't account for gutter offset (translating the canvas context already takes care of this).
     */
    function getCanvasPoints() {
        for (var i = 0; i < imagePoints.length; i++) {

            // imagePoints[num].row: which image pixel it is, from 0 to height.
            // canvasPoints[num].row: offset on the canvas, starting from 0
            // if the point is visible.
            // Add 0.5 so the canvasPoint is in the middle of the point's pixel
            // instead of the top-left edge.
            canvasPoints[imagePoints[i].point_number] = {
                num: imagePoints[i].point_number,
                row: ((imagePoints[i].row + 0.5) * zoomFactor) + imageTopOffset,
                col: ((imagePoints[i].column + 0.5) * zoomFactor) + imageLeftOffset
            };
        }
    }

    /*
     * Return true if the given point's coordinates
     * are not within the image area
     */
    function pointIsOffscreen(pointNum) {
        return (canvasPoints[pointNum].row < 0
            || canvasPoints[pointNum].row >= IMAGE_AREA_HEIGHT
            || canvasPoints[pointNum].col < 0
            || canvasPoints[pointNum].col >= IMAGE_AREA_WIDTH
            )
    }

    function changePointMode(pointMode) {
        // Outline this point mode button in red (and de-outline the other buttons).
        $('.pointModeButton').removeClass('selected');

        if (pointMode == POINTMODE_ALL)
            $('#pointModeButtonAll').addClass('selected');
        else if (pointMode == POINTMODE_SELECTED)
            $('#pointModeButtonSelected').addClass('selected');
        else if (pointMode == POINTMODE_NONE)
            $('#pointModeButtonNone').addClass('selected');

        // Set the new point display mode.
        pointViewMode = pointMode;

        // Redraw all points.
        redrawAllPoints();
    }



    //
    // POINT methods
    //

    // These functions aren't meant to be called directly by handlers. Use
    // toggle() and selectOnly() to ensure that various elements get updated.
    function select(pointNum) {
        $(pointFieldRows[pointNum]).addClass('selected');
        updatePointGraphic(pointNum);
    }
    function unselect(pointNum) {
        $(pointFieldRows[pointNum]).removeClass('selected');
        updatePointGraphic(pointNum);
    }

    // Handlers can call either of the following functions to
    // update point selections.
    function toggle(pointNum) {
        // Toggle the selection status of a single point.
        if (isPointSelected(pointNum))
            unselect(pointNum);
        else
            select(pointNum);
        updateElementsAfterSelections();
    }
    function selectOnly(pointNumList) {
        // Once this function is done, only the points
        // in the given list will be selected.
        //
        // This function is optimized to try and limit the
        // number of select and unselect calls.
        var i, n;
        var isToBeSelected = {};
        for (n = 1; n <= numOfPoints; n++) {
            isToBeSelected[n] = false;
        }
        for (i = 0; i < pointNumList.length; i++) {
            n = pointNumList[i];
            isToBeSelected[n] = true;
        }

        for (n = 1; n <= numOfPoints; n++) {
            if (isPointSelected(n) && !isToBeSelected[n]) {
                unselect(n);
            }
            else if (!isPointSelected(n) && isToBeSelected[n]) {
                select(n);
            }
        }

        updateElementsAfterSelections();
    }

    function isPointSelected(pointNum) {
        var row = pointFieldRows[pointNum];
        return $(row).hasClass('selected');
    }

    function isRobot(pointNum) {
        var robotField = pointRobotFields[pointNum];
        return robotField.value === 'true';
    }

    function unrobot(pointNum) {
        var robotField = pointRobotFields[pointNum];
        robotField.value = 'false';

        var row = pointFieldRows[pointNum];
        $(row).removeClass('robot');
    }

    function isPointHumanAnnotated(pointNum) {
        var row = pointFieldRows[pointNum];
        return $(row).hasClass('annotated');
    }

    function getPointNumOfAnnoField(annoField) {
        // Assuming the annotation field's name attribute is "label_<pointnumber>".
        // "label_" is 6 characters.
        return parseInt(annoField.name.substring(6));
    }

    function getSelectedNumbers() {
        var selectedNumbers = [];
        var n;
        for (n = 1; n <= numOfPoints; n++) {
            if (isPointSelected(n)) {
                selectedNumbers.push(n);
            }
        }
        return selectedNumbers;
    }



    //
    // LABEL methods
    //

    function labelPointWithValue(pointNum, v) {
        var ptField = pointFields[pointNum];
        ptField.value = v;
    }

    function getMatchingLabelCode(labelCode) {
        // Get a valid label code that matches the given one
        // case-insensitively. (Label codes are
        // case-insensitive unique).
        var i;
        for (i = 0; i < labelCodes.length; i++) {
            if (labelCode.equalsIgnoreCase(labelCodes[i])) {
                return labelCodes[i];
            }
        }
        // No matches; return null.
        return null;
    }

    function isLabelCodeValid(labelCode) {
        return (getMatchingLabelCode(labelCode) !== null);
    }

    // Label the selected points with the given label code,
    // and select the next point if we only have one selected
    function labelSelected(labelCode) {
        var allSelectedNumbers = getSelectedNumbers();

        var i;
        for (i = 0; i < allSelectedNumbers.length; i++) {
            var n = allSelectedNumbers[i];
            labelPointWithValue(n, labelCode);
            onPointUpdate(n);
        }
    }



    //
    // FIELD methods
    //

    function selectPrevPoint() {
        var allSelectedNumbers = getSelectedNumbers();

        if (allSelectedNumbers.length !== 1) {
            // We've selected 0 or 2+ points, so abort
            return;
        }

        var selectedNumber = allSelectedNumbers[0];

        if (selectedNumber === 1) {
            // If first point, just un-select
            selectOnly([]);
        }
        else {
            selectOnly([selectedNumber-1]);
            prepareFieldForUse();
        }
    }

    function selectNextPoint() {
        var allSelectedNumbers = getSelectedNumbers();

        if (allSelectedNumbers.length !== 1) {
            // We've selected 0 or 2+ points, so abort
            return;
        }

        var selectedNumber = allSelectedNumbers[0];

        if (selectedNumber === numOfPoints) {
            // If last point, just un-select
            selectOnly([]);
        }
        else {
            selectOnly([selectedNumber+1]);
            prepareFieldForUse();
        }
    }

    // Select the next unannotated point; or if everything is
    // annotated, select the next point.
    function selectNextUnannotatedPoint() {
        var allSelectedNumbers = getSelectedNumbers();

        if (allSelectedNumbers.length !== 1) {
            // We've selected 0 or 2+ points, so abort
            return;
        }

        var selectedNumber = allSelectedNumbers[0];
        var n;

        // Search from here to the last point
        // for something unannotated
        for (n = selectedNumber+1; n <= numOfPoints; n++) {
            if (!isPointHumanAnnotated(n)) {
                selectOnly([n]);
                prepareFieldForUse();
                return;
            }
        }
        // Search from the first point to here
        // for something unannotated
        for (n = 1; n < selectedNumber; n++) {
            if (!isPointHumanAnnotated(n)) {
                selectOnly([n]);
                prepareFieldForUse();
                return;
            }
        }

        // Nothing unannotated; just select the next point
        selectNextPoint();
    }

    function selectFirstUnannotatedPoint() {
        var pointNum = null;

        for (var n = 1; n <= numOfPoints; n++) {
            if (!isPointHumanAnnotated(n)) {
                pointNum = n;
                break;
            }
        }

        if (pointNum !== null) {
            selectOnly([pointNum]);
        }

        $annotationField.focus();
    }

    function unfocusField() {
        $annotationField.blur();
    }

    function labelSelectedAndVerify() {
        var annoField = $annotationField[0];

        // Check if the label is valid
        if (!isLabelCodeValid(annoField.value)) {
            // TODO: Notify the user that it's invalid
            annoField.value = '';
            return;
        }

        labelSelected(annoField.value);
        selectNextUnannotatedPoint();
    }

    function onFieldFocus() {
        prepareFieldForUse();
    }

    function onFieldBlur() {
        updateElementsAfterSelections();
    }

    function updateElementsAfterSelections() {

        var selectedNumbers = getSelectedNumbers();

        if (selectedNumbers.length === 0) {
            $annotationField.prop('disabled', true);

            $annotationField.attr('value', '');
        }
        else if (selectedNumbers.length === 1) {
            $annotationField.prop('disabled', false);

            var pointNum = selectedNumbers[0];
            var $ptField = $(pointFields[pointNum]);
            $annotationField.attr('value', $ptField.attr('value'));

            // Shift the center of zoom to this point.
            centerOnPoint(pointNum);

            // If we have a machine annotated point, clear the field
            // so it will display the list of machine suggestions.
            if (isRobot(pointNum)) {
                $annotationField.attr('value', '');
            }

            // Scroll the points list to the current point.
            var pointAtTopScrollPosition = pointFieldRows[pointNum].offsetTop;
            var pointsListHalfMaxHeight =
                parseFloat($(annotationList).css('max-height')) / 2;
            var pointAtMiddleScrollPosition =
                Math.max(pointAtTopScrollPosition - pointsListHalfMaxHeight, 0);
            $(annotationList).scrollTop(pointAtMiddleScrollPosition);
        }
        else {  // 2+ selected
            $annotationField.prop('disabled', false);

            $annotationField.attr('value', '');
        }

        // Move the annotation field if it's on the image.
        moveAnnotationFieldImageContainer();
    }

    function prepareFieldForUse() {
        // Select (highlight) all the text in the label field,
        // so the user can start typing over it.
        //
        // Must set a timeout so that the selection sticks when you
        // focus with a mouseclick. Otherwise, in some browsers, you
        // will select and then immediately place your cursor to
        // unselect.
        // http://stackoverflow.com/a/19498477
        // Also, a timeout of 50 ms seems enough for Chrome, but not
        // for Firefox. 100 is enough for Firefox...
        //
        // TODO: Apparently may not work in mobile Safari?
        // http://stackoverflow.com/a/4067488
        var selectTextFunction = function(elmt) {elmt.select();};
        setTimeout(selectTextFunction.curry($annotationField[0]), 100);

        // Show the autocomplete dropdown
        $annotationField.autocomplete("search", $annotationField[0].value);
    }

    function getAnnotationFieldContainer() {
        if ($annotationField.parent().is($annotationFieldFixedContainer)) {
            return 'fixed';
        }
        return 'image';
    }

    function moveAnnotationFieldImageContainer() {
        if (getAnnotationFieldContainer() !== 'image') {
            return;
        }

        var selectedNumbers = getSelectedNumbers();
        if (selectedNumbers.length === 0) {
            $annotationField.hide();
        }
        else {
            $annotationField.show();

            // Set position

            var x,y;

            if (selectedNumbers.length === 1) {
                // Single point selected.
                // Position the field a little right and below the point.
                var canvasCoords = canvasPoints[selectedNumbers[0]];
                x = canvasCoords.col + 100;
                y = canvasCoords.row + 100;
            }
            else {
                // Multiple points selected.
                // Just put the field at a fixed location.
                x = ANNOTATION_AREA_WIDTH*(2/3);
                y = ANNOTATION_AREA_HEIGHT*(2/3);
            }

            var xMin = 0;
            var yMin = 0;

            // Don't allow the field to stick out past the image edge.
            var xMax = ANNOTATION_AREA_WIDTH - $annotationField.width();
            // Don't allow the field to stick out past the image edge, and
            // don't allow the autocomplete to stick out too much.
            var yMax = ANNOTATION_AREA_HEIGHT - $annotationField.height() - 100;

            if (x < xMin) {x = xMin;}
            if (y < yMin) {y = yMin;}
            if (x > xMax) {x = xMax;}
            if (y > yMax) {y = yMax;}

            $annotationFieldImageContainer.css({
                top: y+'px',
                left: x+'px'
            });
        }
    }

    function toggleAnnotationFieldContainer() {
        if (getAnnotationFieldContainer() === 'image') {
            // Move the field to the fixed container
            $annotationField.detach().prependTo($annotationFieldFixedContainer);

            $annotationField.removeClass('semi-transparent');
            $('.ui-autocomplete.ui-menu').removeClass('semi-transparent');

            // The field should always be shown when in this location, so make
            // sure of that
            $annotationField.show();
        }
        else {
            // Move the field to the on-image container
            $annotationField.detach().prependTo($annotationFieldImageContainer);

            $annotationField.addClass('semi-transparent');
            $('.ui-autocomplete.ui-menu').addClass('semi-transparent');

            // The field needs to move to the right spot and show/hide
            // depending on the current selected points
            moveAnnotationFieldImageContainer();
        }
    }

    function enableRectangleSelect() {
        $rectangleSelectListener.appendTo($(imageArea));
    }
    function disableRectangleSelect() {
        $rectangleSelectListener.detach();
    }

    function startRectangleSelect(e) {
        // TODO: There has got to be a simpler way to calculate this.
        var imageElmtPos = getImageElmtPosition(e);
        var imageElmtX = imageElmtPos[0];
        var imageElmtY = imageElmtPos[1];
        var imageLeftOffset = parseFloat($(getImageCanvas()).css('left'));
        var imageTopOffset = parseFloat($(getImageCanvas()).css('top'));
        rectangleStartX = imageElmtX + imageLeftOffset;
        rectangleStartY = imageElmtY + imageTopOffset;

        $rectangleSelectArea.css({
            'left': rectangleStartX.toString() + 'px',
            'top': rectangleStartY.toString() + 'px',
            'width': '0px',
            'height': '0px'
        });
        $rectangleSelectArea.appendTo($(imageArea));

        $(document).bind('mouseup', finishRectangleSelect);
        $(document).bind('mousemove', moveRectangleSelect);
    }
    function moveRectangleSelect(e) {
        var imageElmtPos = getImageElmtPosition(e);
        var imageElmtX = imageElmtPos[0];
        var imageElmtY = imageElmtPos[1];
        var imageLeftOffset = parseFloat($(getImageCanvas()).css('left'));
        var imageTopOffset = parseFloat($(getImageCanvas()).css('top'));
        var currentX = imageElmtX + imageLeftOffset;
        var currentY = imageElmtY + imageTopOffset;

        $rectangleSelectArea.css({
            'left': Math.min(currentX, rectangleStartX).toString() + 'px',
            'top': Math.min(currentY, rectangleStartY).toString() + 'px',
            'width': Math.abs(currentX - rectangleStartX).toString() + 'px',
            'height': Math.abs(currentY - rectangleStartY).toString() + 'px'
        });
    }
    function finishRectangleSelect(e) {
        $rectangleSelectArea.detach();

        // Select points based on the rectangle area.

        // Mouse's position in the canvas element
        var imageElmtPos = getImageElmtPosition(e);
        var imageLeftOffset = parseFloat($(getImageCanvas()).css('left'));
        var imageTopOffset = parseFloat($(getImageCanvas()).css('top'));
        var displayX1 = imageElmtPos[0] + imageLeftOffset;
        var displayY1 = imageElmtPos[1] + imageTopOffset;
        var displayX2 = rectangleStartX;
        var displayY2 = rectangleStartY;

        var imageXMin = (Math.min(displayX1,displayX2) - imageLeftOffset)/zoomFactor;
        var imageYMin = (Math.min(displayY1,displayY2) - imageTopOffset)/zoomFactor;
        var imageXMax = (Math.max(displayX1,displayX2) - imageLeftOffset)/zoomFactor;
        var imageYMax = (Math.max(displayY1,displayY2) - imageTopOffset)/zoomFactor;

        var numbersToSelect = getSelectedNumbers();

        for (var i = 0; i < imagePoints.length; i++) {
            var currPoint = imagePoints[i];

            var inXRange = imageXMin <= currPoint.column
                           && currPoint.column <= imageXMax;
            var inYRange = imageYMin <= currPoint.row
                           && currPoint.row <= imageYMax;

            if (inXRange && inYRange) {
                // This point is in the rectangle.
                if (!isPointSelected(currPoint.point_number)) {
                    // This point was not previously selected. Select it.
                    numbersToSelect.push(currPoint.point_number)
                }
            }
        }

        selectOnly(numbersToSelect);

        // Clean up.
        rectangleStartX = null;
        rectangleStartY = null;
        $(document).unbind('mouseup', finishRectangleSelect);
        $(document).unbind('mousemove', moveRectangleSelect);
        disableRectangleSelect();
    }



    //
    // NAV methods
    //

    /* Navigate to another image. */
    function navNext() {
        // Need to click the button, not just submit the form with submit().
        // The name associated with the button is part of the form
        // data we want to submit.
        $('#nav-next-submit').click();
    }
    function navPrev() {
        $('#nav-prev-submit').click();
    }



    //
    // SAVE methods
    //

    function saveAnnotations() {
        $(saveButton).attr('disabled', 'disabled');
        $(saveButton).text("Now saving...");
        $.ajax({
            // Data to send in the request
            data: $("#annotationForm").serialize(),

            // Callback on successful response
            success: ajaxSaveButtonCallback,

            type: 'POST',

            // URL to make request to
            url: saveAnnotationsUrl
        });
    }

    // AJAX callback.
    function ajaxSaveButtonCallback(returnDict) {
        if (returnDict.error) {
            setSaveButtonText("Error");
            alert("Annotation save error: {0}".format(returnDict.error));
            return;
        }

        setSaveButtonText("Saved");

        // Add or remove ALL DONE indicator
        setAllDoneIndicator(returnDict.all_done);

        util.pageLeaveWarningDisable();
    }

    function setSaveButtonText(buttonText) {
        $(saveButton).text(buttonText);
    }

    function clickSaveButton() {
        if ($(saveButton).prop('disabled') === false) {
            $(saveButton).click();
        }
    }

    function updateSaveButton() {
        // No errors in annotation form
        if ($(annotationList).find('tr.error').length === 0) {
            // Enable save button
            $(saveButton).removeAttr('disabled');
            setSaveButtonText("Save progress");
        }
        // Errors
        else {
            // Disable save button
            $(saveButton).attr('disabled', 'disabled');
            setSaveButtonText("Error");
        }

        util.pageLeaveWarningEnable("You have unsaved changes.");
    }

    // AJAX callback.
    function ajaxIsAllDoneCallback(returnDict) {
        if (returnDict.error) {
            console.log(
                "All-done status check error: {0}".format(returnDict.error));
            return;
        }

        // Add or remove ALL DONE indicator
        setAllDoneIndicator(returnDict.all_done);
    }

    function setAllDoneIndicator(allDone) {
        var $allDone = $('#allDone');
        $allDone.empty();
        if (allDone) {
            $allDone.append('<span>').text("ALL DONE");
        }
    }



    //
    // DRAW methods
    //

    function drawPointHelper(pointNum, color, outlineColor) {
        var canvasPoint = canvasPoints[pointNum];

        drawPointMarker(canvasPoint.col, canvasPoint.row,
            color);
        drawPointNumber(canvasPoint.num.toString(), canvasPoint.col, canvasPoint.row,
            color, outlineColor);
    }

    function drawPointUnannotated(pointNum) {
        drawPointHelper(pointNum, ATS.settings.unannotatedColor, OUTLINE_COLOR);
    }
    function drawPointRobotAnnotated(pointNum) {
        drawPointHelper(pointNum, ATS.settings.robotAnnotatedColor, OUTLINE_COLOR);
    }
    function drawPointHumanAnnotated(pointNum) {
        drawPointHelper(pointNum, ATS.settings.humanAnnotatedColor, OUTLINE_COLOR);
    }
    function drawPointSelected(pointNum) {
        drawPointHelper(pointNum, ATS.settings.selectedColor, OUTLINE_COLOR);
    }

    /*
     Draw an annotation point marker (crosshair, circle, or whatever)
     which is centered at x,y.
     */
    function drawPointMarker(x, y, color) {
        var markerType = ATS.settings.pointMarker;
        var radius;

        if (ATS.settings.pointMarkerIsScaled === true)
            // Zoomed all the way out: radius = pointMarkerSize.
            // Zoomed in 1.5x: radius = pointMarkerSize * 1.5. etc.
            // radius must be an integer.
            radius = Math.round(ATS.settings.pointMarkerSize * Math.pow(ZOOM_INCREMENT, zoomLevel));
        else
            radius = ATS.settings.pointMarkerSize;

        context.strokeStyle = color;
        context.lineWidth = 3;

        context.beginPath();

        if (markerType === 'crosshair' || markerType === 'crosshair and circle') {
            context.moveTo(x, y + radius);
            context.lineTo(x, y - radius);

            context.moveTo(x - radius, y);
            context.lineTo(x + radius, y);
        }
        if (markerType === 'circle' || markerType === 'crosshair and circle') {
            context.arc(x, y, radius, 0, 2.0*Math.PI);
        }
        if (markerType === 'box') {
            context.moveTo(x + radius, y + radius);
            context.lineTo(x - radius, y + radius);
            context.lineTo(x - radius, y - radius);
            context.lineTo(x + radius, y - radius);
            context.lineTo(x + radius, y + radius);
        }

        context.stroke();
    }

    /*
     Draw the number of an annotation point
     which is centered at x,y.
     */
    function drawPointNumber(num, x, y, color, outlineColor) {
        context.textBaseline = "bottom";
        context.textAlign = "left";
        context.fillStyle = color;
        context.strokeStyle = outlineColor;
        context.lineWidth = 1;

        var numberSize = ATS.settings.pointNumberSize;
        if (ATS.settings.pointNumberIsScaled)
            numberSize = Math.round(numberSize * Math.pow(ZOOM_INCREMENT, zoomLevel));

        context.font = NUMBER_FONT_FORMAT_STRING.format(numberSize.toString());

        // Offset the number's position a bit so it doesn't overlap with the annotation point.
        // TODO: Consider doing offset calculations once each time the settings/zoom level change, not once for each point
        var offset = ATS.settings.pointMarkerSize;

        if (ATS.settings.pointMarker !== 'box')
            // When the pointMarker is a box, line up the number with the corner of the box.
            // When the pointMarker is not a box, line up the number with the corner of a circle instead.
            offset = offset * 0.7;
        if (ATS.settings.pointMarkerIsScaled === true)
            offset = offset * Math.pow(ZOOM_INCREMENT, zoomLevel);
        // Compensate for the fact that the number ends up being drawn
        // a few pixels away from the specified baseline point.
        offset = offset - 2;
        offset = Math.round(offset);

        x = x + offset;
        y = y - offset;

        context.fillText(num, x, y);    // Color in the number
        context.strokeText(num, x, y);    // Outline the number (make it easier to see)
    }



    //
    // UPDATE methods
    //

    /* Update a point's graphics on the canvas in the correct color.
     * Don't redraw a point unless necessary.
     */
    function updatePointGraphic(pointNum) {
        // If the point is offscreen, then don't draw
        if (pointIsOffscreen(pointNum))
            return;

        // Get the current (graphical) state of this point
        var newState;

        if (isPointSelected(pointNum))
            newState = STATE_SELECTED;
        else if (isPointHumanAnnotated(pointNum))
            newState = STATE_ANNOTATED;
        else if (isRobot(pointNum))
            newState = STATE_ROBOT;
        else
            newState = STATE_UNANNOTATED;

        // Account for point view modes
        if (pointViewMode === POINTMODE_SELECTED && newState !== STATE_SELECTED)
            newState = STATE_NOTSHOWN;
        if (pointViewMode === POINTMODE_NONE)
            newState = STATE_NOTSHOWN;

        // Redraw if the (graphical) state has changed
        var oldState = pointGraphicStates[pointNum];

        if (oldState !== newState) {
            pointGraphicStates[pointNum] = newState;

            if (newState === STATE_SELECTED)
                drawPointSelected(pointNum);
            else if (newState === STATE_ANNOTATED)
                drawPointHumanAnnotated(pointNum);
            else if (newState === STATE_ROBOT)
                drawPointRobotAnnotated(pointNum);
            else if (newState === STATE_UNANNOTATED)
                drawPointUnannotated(pointNum);
            else if (newState === STATE_NOTSHOWN) {
                // "Erase" this point.
                // To do this, redraw the canvas with this point marked as not shown.
                // For performance reasons, you'll want to avoid reaching this code whenever
                // possible/reasonable.  One tip: remember to mark all points as NOTSHOWN
                // whenever you clear the canvas of all points.
                redrawAllPoints();
            }
        }
    }

    /* Look at a label field, and based on the label, mark the point
     * as (human) annotated, robot annotated, unannotated, or errored.
     *
     * Return true if something changed (label code or robot status).
     * Return false otherwise.
     */
    function updatePointState(pointNum, robotStatusAction) {
        var field = pointFields[pointNum];
        var row = pointFieldRows[pointNum];
        var robotField = pointRobotFields[pointNum];
        var labelCode = field.value;

        // Has the label text changed?
        var oldState = pointContentStates[pointNum];
        var labelChanged = (oldState['label'] !== labelCode);

        /*
         * Update style elements and robot statuses accordingly
         */

        if (labelCode === '') {
            // Empty string; if the label field was non-empty before, fill the field back in.
            // (Or if it was empty before, then leave it empty.)
            if (oldState.label !== undefined && oldState.label !== '')
                field.value = oldState.label;
            return false;
        }
        else if (!isLabelCodeValid(labelCode)) {
            // Error: label is not in the labelset
            $(field).attr('title', 'Label not in labelset');
            $(row).addClass('error');
            $(row).removeClass('annotated');
            unrobot(pointNum);
        }
        else {
            // No error

            // Fix the casing
            labelCode = getMatchingLabelCode(labelCode);
            field.value = labelCode;

            if (robotField.value === 'true') {
                if (robotStatusAction === 'initialize') {
                    // Initializing the page, need to add robot styles as appropriate.
                    $(row).addClass('robot');
                }
                else if (robotStatusAction === 'unrobotOnlyIfChanged') {
                    // We're told to only unrobot the annotation if the label changed.
                    if (labelChanged)
                        unrobot(pointNum);
                }
                else {
                    // Any other update results in this annotation being un-roboted.
                    unrobot(pointNum);
                }
            }

            // Set as (human) annotated or not
            if (isRobot(pointNum)) {
                // Robot annotated
                $(row).removeClass('annotated');
            }
            else {
                $(row).addClass('annotated');
            }

            // Remove error styling, if any
            $(row).removeClass('error');

            // Field's mouseover text = label name
            $(field).attr('title', labelCodesToNames[labelCode]);
        }

        var robotStatusChanged = (oldState['robot'] !== robotField.value);
        var contentChanged = ((labelChanged || robotStatusChanged) && (robotStatusAction !== 'initialize'));

        // Done assessing change of state, so set the new state.
        pointContentStates[pointNum] = {'label': labelCode, 'robot': robotField.value};
        return contentChanged;
    }

    function onPointUpdate(pointNum, robotStatusAction) {
        var contentChanged = updatePointState(pointNum, robotStatusAction);

        updatePointGraphic(pointNum);

        if (contentChanged) {
            updateSaveButton();
        }
    }

    function redrawAllPoints() {
        // Reset the canvas and re-translate the context
        // to compensate for the gutters.
        resetCanvas();

        // Clear the pointGraphicStates.
        var n;
        for (n = 1; n <= numOfPoints; n++) {
            pointGraphicStates[n] = STATE_NOTSHOWN;
        }

        // Draw all points.
        for (n = 1; n <= numOfPoints; n++) {
            updatePointGraphic(n);
        }
    }



    //
    // MISC methods
    //

    function openSubwindow($elmt, title) {
        $elmt.dialog({
            width: subWindowWidth,
            height: subWindowHeight,
            modal: false,
            title: title
        });
        $('.ui-dialog').css('z-index', ZINDEX_SUBWINDOW);
    }



    //
    // PUBLIC methods
    //

    /* These are the only methods that need to be referred to as
     * AnnotationToolHelper.methodname. */
    return {

        /* Params:
         * fullHeight, fullWidth, IMAGE_AREA_WIDTH, IMAGE_AREA_HEIGHT,
         * imagePoints, labels, machineSuggestions,
         * saveAnnotationsUrl, isAnnotationAllDoneUrl, imageHelper */
        init: function(params) {
            var i, j, n;    // Loop variables...

            /* Ajax URLs */

            saveAnnotationsUrl = params.saveAnnotationsUrl;
            isAnnotationAllDoneUrl = params.isAnnotationAllDoneUrl;

            /* Helpers */

            imageHelper = params.imageHelper;

            /*
             * Initialize styling, sizing, and positioning for various elements
             */

            IMAGE_FULL_WIDTH = params.fullWidth;
            IMAGE_FULL_HEIGHT = params.fullHeight;
            IMAGE_AREA_WIDTH = params.IMAGE_AREA_WIDTH;
            IMAGE_AREA_HEIGHT = params.IMAGE_AREA_HEIGHT;

            // TODO: Now that the annotation area is the same size as the image area,
            // maybe some of the element hierarchy can be collapsed a bit.
            ANNOTATION_AREA_WIDTH = IMAGE_AREA_WIDTH;
            ANNOTATION_AREA_HEIGHT = IMAGE_AREA_HEIGHT;

            var horizontalSpacePerButton = ANNOTATION_AREA_WIDTH / BUTTONS_PER_ROW;

            // LABEL_BUTTON_WIDTH will represent a value that can be passed into jQuery's
            // width() and css('width'), and these jQuery functions deal with
            // inner width + padding + border only.
            // So don't count the button's margins... and subtract another pixel or two
            // to be safe, so that slightly imprecise rendering won't cause an overflow.
            // (Chrome seems a bit more prone to this kind of imprecise rendering, compared
            // to Firefox...)
            LABEL_BUTTON_WIDTH = horizontalSpacePerButton - (
                parseFloat($('#labelButtons button').css('margin-left'))
                    + parseFloat($('#labelButtons button').css('margin-right'))
                    + 2
                );

            var $labelButton;
            for (i = 0; i < params.labels.length; i++) {
                $labelButton = $("#labelButtons button:exactlycontains('{0}')".format(params.labels[i].code));

                /* Set the button's width.  But first, check to see if the
                 button text is going to overflow; if so, then shrink the text
                 until it doesn't overflow.

                 ... never mind that text shrinking thing for now.  Setting the
                 height of the button afterward is just not reliable at all, and
                 can destroy the layout of buttons below.
                 TODO: Need a robust way to support text shrinking in label buttons.
                 */

                //            var numOfSizeDecreases = 0;
                //            var initialButtonHeight = $labelButton.outerHeight();
                //            while (parseFloat($labelButton.outerWidth()) > LABEL_BUTTON_WIDTH) {
                //                // Scale the font to 90% size of what it was before.
                //                $labelButton.changeFontSize(0.9);
                //
                //                numOfSizeDecreases++;
                //                // Don't shrink the text so much that it'll become totally unreadable.
                //                // Just accept the text overflow if we've already shrunk the text a lot.
                //                if (numOfSizeDecreases > 8)
                //                    break;
                //            }
                //            // Need to reset the button's height to what it was before,
                //            // if we shrunk the button's text.
                //            if (numOfSizeDecreases > 0)
                //                $labelButton.css('height', initialButtonHeight);

                // Now set the button's width.
                $labelButton.css('width', LABEL_BUTTON_WIDTH.toString() + "px");
            }

            annotationArea = $("#annotationArea")[0];
            annotationList = $("#annotationList")[0];
            pointsCanvas = $("#pointsCanvas")[0];
            listenerElmt = $("#listenerElmt")[0];
            saveButton = $("#saveButton")[0];

            imageArea = $("#imageArea")[0];

            $(annotationArea).css({
                "width": ANNOTATION_AREA_WIDTH + "px",
                "height": ANNOTATION_AREA_HEIGHT + "px",
                "background-color": IMAGE_GUTTER_COLOR
            });

            $(imageArea).css({
                "width": IMAGE_AREA_WIDTH + "px",
                "height": IMAGE_AREA_HEIGHT + "px"
            });

            // Computations for a multi-column layout. Based on
            // http://alistapart.com/article/holygrail
            //
            // Note: something that's weird (and not readily apparent) is that
            // the whole annotation tool is left-aligned on the page. It just so
            // happens that there is not much room for the position to change
            // from alignment. But if that room expands, then the left
            // align may look weird.
            var $mainColumn = $('#mainColumn');
            var $rightSidebar = $('#rightSidebar');

            // Maybe there is a way to compute the right sidebar width dynamically
            // and guarantee that the layout is correct, but I don't know what
            // that way is.
            var rightSidebarWidth = 150;

            $mainColumn.css({
                "width": $(annotationArea).width().toString() + "px"
            });
            $rightSidebar.css({
                "width": rightSidebarWidth.toString() + "px",
                "margin-right": (-1 * rightSidebarWidth).toString() + "px"
            });
            $('#columnContainer').css({
                "width": $mainColumn.width().toString() + "px",
                "padding-right": $rightSidebar.width().toString() + "px"
            });

            // Hackish computation to make the right sidebar's
            // horizontal rule line up (roughly) with the bottom of
            // the annotation area.
            var annotationListMaxHeight =
                ANNOTATION_AREA_HEIGHT
                    - $("#toolButtonArea").outerHeight(true)
                    - $("#image-tools-wrapper").outerHeight(true)
                    - $(saveButton).outerHeight(true)
                    - $("#allDone").outerHeight(true)
                    - 2*$("hr.narrow").outerHeight(true);

            $(annotationList).css({
                "max-height": annotationListMaxHeight + "px"
            });

            // Auto-adjust the vertical scroll position to fit the
            // annotation tool better.
            var contentContainerY = $('#content-container').offset().top;
            $(window).scrollTop(contentContainerY);

            $rectangleSelectListener = $('<div>');
            $rectangleSelectListener.attr('id', 'rectangle-select-listener');
            $rectangleSelectListener.css({
                "z-index": ZINDEX_RECTANGLE_SELECT_LISTENER
            });

            $rectangleSelectArea = $('<div>');
            $rectangleSelectArea.attr('id', 'rectangle-select-area');
            $rectangleSelectArea.css({
                "z-index": ZINDEX_RECTANGLE_SELECT_AREA
            });


            /* Initialization - Labels and label buttons */

            var groupsWithStyles = [];
            var groupStyles = {};
            var nextStyleNumber = 1;

            for (i = 0; i < params.labels.length; i++) {
                var label = params.labels[i];

                // If this label's functional group doesn't have a style yet,
                // then assign this group a style.
                if (groupsWithStyles.indexOf(label.group) === -1) {
                    groupStyles[label.group] = 'group'+nextStyleNumber;
                    groupsWithStyles.push(label.group);
                    nextStyleNumber++;
                }

                // Get the label's button and apply the label's functional group style to it.
                $labelButton = $("#labelButtons button:exactlycontains('{0}')".format(label.code));
                $labelButton.addClass(groupStyles[label.group]);

                // Assign a grid position to the label button.
                // For example, i=0 gets position [0,0], i=13 gets [1,3]
                $labelButton.attr('gridy', Math.floor(i / BUTTONS_PER_ROW));
                $labelButton.attr('gridx', i % BUTTONS_PER_ROW);

                // When you mouseover the button, show the label name in a tooltip.
                $labelButton.attr('title', label.name);

                // Add to an array of available label codes, which will
                // be used for input checking purposes (in label fields).
                labelCodes.push(label.code);

                // Add to a mapping of label codes to names, which will
                // be used to show a label name when you mouse over a
                // label field with a valid code.
                labelCodesToNames[label.code] = label.name;
            }


            /*
             * Set initial image scaling so the whole image is shown.
             * Also set the allowable zoom factors.
             */

            var windowWidth = $(window).width();
            var windowHeight = $(window).height();

            var widthScaleRatio = IMAGE_FULL_WIDTH / IMAGE_AREA_WIDTH;
            var heightScaleRatio = IMAGE_FULL_HEIGHT / IMAGE_AREA_HEIGHT;
            var scaleDownFactor = Math.max(widthScaleRatio, heightScaleRatio);

            // If the scaleDownFactor is < 1, then it's scaled up (meaning the image is really small).
            zoomFactor = 1.0 / scaleDownFactor;

            // Allowable zoom factors/levels:
            // Start with the most zoomed out level, 0.  Level 1 is ZOOM_INCREMENT * level 0.
            // Level 2 is ZOOM_INCREMENT * level 1, etc.  Goes up to level HIGHEST_ZOOM_LEVEL.
            zoomLevel = 0;
            for (i = 0; i <= HIGHEST_ZOOM_LEVEL; i++) {
                ZOOM_FACTORS[i] = zoomFactor * Math.pow(ZOOM_INCREMENT, i);
            }

            // Based on the zoom level, set up the image area.
            // (No need to define centerOfZoom since we're not zooming in to start with.)
            setupImageArea();

            // Set the canvas's width and height properties so the canvas contents don't stretch.
            // Note that this is different from CSS width and height properties.
            pointsCanvas.width = ANNOTATION_AREA_WIDTH;
            pointsCanvas.height = ANNOTATION_AREA_HEIGHT;
            $(pointsCanvas).css({
                "left": 0,
                "top": 0,
                "z-index": ZINDEX_POINTS_CANVAS
            });

            // Set the sub-window size.
            subWindowWidth = Math.max(
                SUB_WINDOW_MIN_WIDTH,
                windowWidth*SUB_WINDOW_PCT_WIDTH/100
            );
            subWindowHeight = Math.max(
                SUB_WINDOW_MIN_HEIGHT,
                windowHeight*SUB_WINDOW_PCT_HEIGHT/100
            );


            /*
             * Initialize and draw annotation points,
             * and initialize some other variables and elements
             */

            // Create a canvas context
            context = pointsCanvas.getContext("2d");

            // Save this fresh context so we can restore it later as needed.
            context.save();

            // Translate the canvas context to compensate for the gutter and the image offset.
            resetCanvas();

            // Initialize point coordinates
            imagePoints = params.imagePoints;
            numOfPoints = imagePoints.length;
            getCanvasPoints();

            $pointFields = $(annotationList).find('input');
            var $pointFieldRows = $(annotationList).find('tr');

            $annotationField = $('#annotation-field');
            $annotationFieldFixedContainer = $('#annotation-field-fixed-container');
            $annotationFieldImageContainer = $('#annotation-field-image-container');

            $annotationFieldImageContainer.css({
                'z-index': ZINDEX_ANNOTATION_FIELD
            });

            // Create arrays that map point numbers to HTML elements.
            // For example, for point 1:
            // annotationFields = form field with point 1's label code
            // annotationFieldRows = table row containing form field 1
            // annotationRobotFields = hidden form element of value true/false saying whether point 1 is robot annotated
            $pointFieldRows.each( function() {
                var field = $(this).find('input')[0];
                var pointNum = getPointNumOfAnnoField(field);
                var robotField = $('#id_robot_' + pointNum)[0];

                pointFields[pointNum] = field;
                pointFieldRows[pointNum] = this;
                pointRobotFields[pointNum] = robotField;
            });

            // Set point annotation statuses,
            // and draw the points
            for (n = 1; n <= numOfPoints; n++) {
                pointContentStates[n] = {'label': undefined, 'robot': undefined};
                pointGraphicStates[n] = STATE_NOTSHOWN;
                onPointUpdate(n, 'initialize');
            }

            // Initialize stuff based on point selections.
            updateElementsAfterSelections();

            // Set the initial point view mode.  This'll trigger a redraw of the points, but that's okay;
            // initialization slowness is a relatively minor worry.
            changePointMode(POINTMODE_ALL);

            // Initialize save button
            $(saveButton).attr('disabled', 'disabled');
            $(saveButton).text('Saved');

            // Initialize all_done state
            $.ajax({
                // Callback on successful response
                success: ajaxIsAllDoneCallback,

                type: 'GET',

                // URL to make request to
                url: isAnnotationAllDoneUrl
            });


            /*
             * Set event handlers
             */

            // Mouse button is pressed and un-pressed on the canvas
            $(listenerElmt).mousedown( function(e) {
                onCanvasClick(e);
            });

            // Disable the context menu on the listener element.
            // The menu just gets in the way while trying to zoom out, etc.
            $(listenerElmt).bind('contextmenu', function(e){
                e.preventDefault();
            });
            // Same goes for the canvas element, which is sometimes what we end up
            // right clicking on if the image is no longer over that part of the canvas.
            $(pointsCanvas).bind('contextmenu', function(e){
                e.preventDefault();
            });
            // Also note that the listener element uses CSS to disable
            // double-click-to-select (it makes the image turn blue, which is annoying).

            $rectangleSelectListener.mousedown(function(e){
                startRectangleSelect(e);
            });

            // Save button is clicked
            $(saveButton).click(function() {
                saveAnnotations();
            });

            // A label button is clicked
            $('#labelButtons').find('button').each( function() {
                $(this).click( function() {
                    // Label the selected points with this button's label code
                    labelSelected($(this).text());
                    // Select the next unannotated point
                    // (if we only have one selected)
                    selectNextUnannotatedPoint();
                });
            });

            // Annotation field gains focus
            $annotationField.focus(function() {
                onFieldFocus();
            });

            // Annotation field is unfocused
            $annotationField.blur(function() {
                onFieldBlur();
            });

            // Point fields (which are read-only) are clicked
            $pointFields.click(function() {
                var pointNum = getPointNumOfAnnoField(this);
                selectOnly([pointNum]);
                $annotationField.focus();
            });

            // Number next to a point field is clicked
            $(".annotationFormLabel").click(function() {
                var pointNum = parseInt($(this).text());
                toggle(pointNum);
            });

            // A zoom button is clicked.

            $("#zoomInButton").click(function() {
                zoomIn();
            });
            $("#zoomOutButton").click(function() {
                zoomOut();
            });
            $("#zoomFitButton").click(function() {
                zoomFit();
            });

            // A point mode button is clicked.

            $("#pointModeButtonAll").click(function() {
                changePointMode(POINTMODE_ALL);
            });
            $("#pointModeButtonSelected").click(function() {
                changePointMode(POINTMODE_SELECTED);
            });
            $("#pointModeButtonNone").click(function() {
                changePointMode(POINTMODE_NONE);
            });

            // A quick-select button is clicked.

            $("#quickSelectButtonNone").click(function() {
                // Un-select all points.

                selectOnly([]);
            });
            $("#quickSelectButtonUnannotated").click(function() {
                // Select only unannotated points.

                var unannotatedPoints = [];

                for (var n = 1; n <= numOfPoints; n++) {
                    if (!isPointHumanAnnotated(n)) {
                        unannotatedPoints.push(n);
                    }
                }

                selectOnly(unannotatedPoints);
            });
            $("#quickSelectButtonInvert").click(function() {
                // Invert selections. (selected -> unselected, unselected -> selected)

                var unselectedPoints = [];

                for (var n = 1; n <= numOfPoints; n++) {
                    if (!isPointSelected(n)) {
                        unselectedPoints.push(n);
                    }
                }

                selectOnly(unselectedPoints);
            });

            // Other tool buttons.
            $("#rectangleSelectButton").click(function() {
                enableRectangleSelect();
            });

            // Buttons that bring up dialogs.
            $("#settings-button").click(function() {
                openSubwindow($("#settings"), "Settings");
            });
            $("#help-button").click(function() {
                openSubwindow($("#help"), "Help");
            });
            var $controlsButton = $("#controls-button");
            $controlsButton.click(function() {
                openSubwindow($("#controls"), "Controls");
            });


            // Keymap.
            //
            // Mousetrap (keyboard shortcut plugin) notes:
            // "mod" means Ctrl in Windows/Linux, Cmd in Mac.
            //
            // Shortcut rules:
            // 1. 'field' is when focused in the annotation field. 'top' is when focused
            // on anything else. 'all' applies when either field or top is true.
            // 2. For 'field' or 'all', don't use anything that could clash with typing
            // a label code.
            // 3. You can't have more than one handler for a given shortcut, even if
            // they are for different contexts (like top and field). This is due to
            // how Mousetrap works.
            var keymap = [
                ['shift+up', zoomIn, 'all'],
                ['shift+down', zoomOut, 'all'],
                ['shift+right', toggleAnnotationFieldContainer, 'all'],

                ['mod+s', clickSaveButton, 'all'],

                ['.', selectFirstUnannotatedPoint, 'top'],
                ['?', function() {$controlsButton.click();}, 'top'],

                ['g p', navPrev, 'top'],
                ['g n', navNext, 'top'],

                ['return', labelSelectedAndVerify, 'field'],
                ['shift+tab', selectPrevPoint, 'field'],
                ['tab', selectNextPoint, 'field'],
                ['esc', unfocusField, 'field']
            ];

            // By default, mousetrap doesn't activate when focused in an
            // input field. But we want some shortcut keys for our
            // annotation input field, so add the class 'mousetrap' to
            // indicate that.
            $annotationField.addClass('mousetrap');

            // Define a few possible handler modifiers.

            // Handler modifier: only trigger
            // when the annotation field is focused.
            var applyOnlyInAnnoField = function(f, event) {
                var aElmt = document.activeElement;
                var aElmtIsAnnotationField = $annotationField.is(aElmt);

                // We're in the annotation field.
                if (aElmtIsAnnotationField) {
                    f(event);
                    // Prevent browser's default behavior.
                    event.preventDefault();
                }
                // We're not in the annotation field.
                // Don't prevent default behavior.
            };

            // Handler modifier: only trigger
            // when the annotation field is NOT focused.
            var applyOnlyAtTop = function(f, event) {
                var aElmt = document.activeElement;
                var aElmtIsAnnotationField = $annotationField.is(aElmt);

                // We're not in the annotation field.
                if (!aElmtIsAnnotationField) {
                    f(event);
                    // Prevent browser's default behavior.
                    event.preventDefault();
                }
                // We're in the annotation field.
                // Don't prevent default behavior.
            };

            // Handler modifier: just prevent the event's
            // default behavior in all cases.
            var modifyToPreventDefault = function(f, event) {
                f(event);
                event.preventDefault();
            };

            // Bind event handlers according to the keymap.
            for (i = 0; i < keymap.length; i++) {
                var keymapping = keymap[i];

                var key = keymapping[0];
                var func = keymapping[1];
                var scope = keymapping[2];

                // May optionally specify the kind of key event
                var keyEvent = null;
                if (keymapping.length >= 4)
                    keyEvent = keymapping[3];

                // Modify the handler
                if (scope === 'field') {
                    func = applyOnlyInAnnoField.curry(func);
                }
                else if (scope === 'top') {
                    func = applyOnlyAtTop.curry(func);
                }
                else {  // 'all'
                    func = modifyToPreventDefault.curry(func);
                }

                // Bind the key combo to the handler.
                if (keyEvent) {
                    Mousetrap.bind(key, func, keyEvent);
                }
                else {
                    Mousetrap.bind(key, func);
                }
            }


            // Initialize AnnotationToolAutocomplete object.
            // Autocomplete will work in the annotation field.
            AnnotationToolAutocomplete.init({
                $annotationField: $annotationField,
                labelCodes: labelCodes,
                machineSuggestions: params.machineSuggestions
            });
            $('.ui-autocomplete.ui-menu').css({
                'z-index': ZINDEX_ANNOTATION_FIELD
            });
            // The annotation field starts is on the image by default, so
            // make it and autocomplete semi-transparent by default.
            $annotationField.addClass('semi-transparent');
            $('.ui-autocomplete.ui-menu').addClass('semi-transparent');


            // Show/hide certain key instructions depending on whether Mac is the OS.
            if (isMac) {
                $('span.key_mac').show();
                $('span.key_non_mac').hide();
            }
            else {
                $('span.key_non_mac').show();
                $('span.key_mac').hide();
            }
        },

        // Public version of these functions...
        getSelectedNumbers: function() {
            return getSelectedNumbers();
        },
        labelSelected: function(v) {
            labelSelected(v);
        },
        redrawAllPoints: function() {
            redrawAllPoints();
        },
        selectNextUnannotatedPoint: function() {
            selectNextUnannotatedPoint();
        }
    }
})();
