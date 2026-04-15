var AnnotationToolImageHelper = (function() {

    var $resetButton = null;
    var $applyingText = null;

    var brightnessField = null;
    var contrastField = null;
    var MIN_BRIGHTNESS = null;
    var MAX_BRIGHTNESS = null;
    var MIN_CONTRAST = null;
    var MAX_CONTRAST = null;

    var sourceImages = {};
    var currentSourceImage = null;
    var imageCanvas = null;

    var nowApplyingProcessing = false;
    var redrawSignal = false;


    function resetImageExifOrientation(imageAsString) {
        var exifObj;

        try {
            exifObj = piexif.load(imageAsString);
        }
        catch (e) {
            if (e.message.includes("invalid file data")
                    || e.message.includes("'unpack' error")
                    || e.message.includes("incorrect value type to decode")) {
                // piexifjs couldn't properly load the exif.
                try {
                    // Since we can't edit the exif, Plan B: remove the
                    // entire exif block, just in case the browser is more
                    // clever than piexifjs and still tries to salvage the
                    // orientation field.
                    return piexif.remove(imageAsString);
                }
                catch (e) {
                    if (e.message.includes("not jpeg")) {
                        // piexifjs couldn't remove the exif either.
                        // We just leave the image unmodified. Likely there is
                        // no exif at all. Though there is the off chance that
                        // we have a PNG with EXIF or something (if so,
                        // hopefully the browser doesn't recognize it; no
                        // browsers seem to recognize PNG EXIF as of 2020/06).
                        return imageAsString;
                    }
                    else {
                        alert(
                            "Error when loading the image: \"" + e.message
                            + "\" If the problem persists,"
                            + " please contact the admins.");
                        throw e;
                    }
                }
            }
            else {
                alert(
                    "Error when loading the image: \"" + e.message
                    + "\" If the problem persists,"
                    + " please contact the admins.");
                throw e;
            }
        }

        // If we're here, we successfully read the exif.
        // Set the orientation tag to the default value.
        exifObj['0th'][piexif.ImageIFD.Orientation] = 1;
        var editedExifStr = piexif.dump(exifObj);
        return piexif.insert(editedExifStr, imageAsString);
    }

    /* Preload a source image; once it's loaded, swap it in as the image
     * used in the annotation tool.
     *
     * Parameters:
     * code - Which version of the image it is: 'scaled' or 'full'.
     *
     * Basic code pattern from: http://stackoverflow.com/a/1662153/
     */
    function preloadAndUseSourceImage(code) {
        // Create an Image object.
        sourceImages[code].imgBuffer = new Image();

        // Allow the image to be from a different domain such as S3.
        // https://developer.mozilla.org/en-US/docs/Web/HTML/CORS_enabled_image
        sourceImages[code].imgBuffer.crossOrigin = "Anonymous";

        // When image preloading is done, swap images.
        sourceImages[code].imgBuffer.onload = function() {
            imageCanvas.width = sourceImages[code].width;
            imageCanvas.height = sourceImages[code].height;

            currentSourceImage = sourceImages[code];
            redrawImage();

            // If we just finished loading the scaled image, then start loading
            // the full image.
            if (code === 'scaled') {
                preloadAndUseSourceImage('full');
            }
        };

        // Download image from URL. Normally setting a DOM Image's src
        // attribute to the URL is a 'shortcut' for doing this, but:
        //
        // 1. Since we are concerned about EXIF orientation screwing up
        // dimensions assumptions, we want to edit the EXIF before loading the
        // data into any DOM Image.
        //
        // 2. The Image src route could require an intermediate usage of
        // Canvas.toDataURL(), which would re-encode the image (thus applying
        // another round of JPEG compression, for example).
        var imageRequest = new XMLHttpRequest();
        imageRequest.open('GET', sourceImages[code].url, true);
        imageRequest.responseType = 'arraybuffer';

        imageRequest.onload = function() {
            var arrayBuffer = imageRequest.response;
            if (!arrayBuffer) {
                alert(
                    "Error when loading the image: couldn't get arrayBuffer."
                    + " If the problem persists, please contact the admins.");
                return;
            }

            var blob = new Blob([arrayBuffer]);
            var reader = new FileReader();

            reader.onload = function(event) {

                // Reset the image's EXIF orientation tag to the default value,
                // so that the browser can't pick up the EXIF orientation and
                // rotate the displayed image accordingly.
                //
                // Perhaps later, we'll give an option to respect the EXIF
                // orientation here. But it must be done properly, rotating
                // the point positions as well as the image itself.
                //
                // This overall approach of EXIF-editing may not be necessary
                // in the future, if canvas elements respect the CSS
                // image-orientation attribute or similar:
                // https://image-orientation-test.now.sh/
                var exifEditedDataString = resetImageExifOrientation(
                    event.target.result);

                // Convert the data string to a base64 URL.
                var contentType = imageRequest.getResponseHeader(
                    'content-type');
                var exifEditedDataURL = (
                    "data:" + contentType
                    + ";base64," + btoa(exifEditedDataString));

                // Load the EXIF-edited image into the image canvas.
                sourceImages[code].imgBuffer.src = exifEditedDataURL;
            };
            reader.readAsBinaryString(blob);
        };

        imageRequest.send(null);

        // For debugging, it sometimes helps to load an image that
        // (1) has different image content, so you can tell when it's swapped in, and/or
        // (2) is loaded after a delay, so you can zoom in first and then
        //     notice the resolution change when it happens.
        // Here's (2) in action: uncomment the below code and comment out the
        // preload line above to try it.  The second parameter to setTimeout()
        // is milliseconds until the first-parameter function is called.
        // NOTE: only use this for debugging, not for production.
        //setTimeout(function() {
        //    sourceImages[code].imgBuffer.src = sourceImages[code].url;
        //}, 10000);
    }

    /* Redraw the source image, and apply brightness and contrast operations. */
    function redrawImage() {
        // If we haven't loaded any image yet, don't do anything.
        if (currentSourceImage === null)
            return;

        // If processing is currently going on, emit the redraw signal to
        // tell it to stop processing and re-call this function.
        if (nowApplyingProcessing === true) {
            redrawSignal = true;
            return;
        }

        // Redraw the source image.
        // https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/drawImage
        imageCanvas.getContext("2d").drawImage(
            currentSourceImage.imgBuffer,
            // Canvas coordinates at which to place the top-left corner of
            // the source image.
            0, 0,
            // The dimensions to draw the image in the canvas. In some cases,
            // browsers have problems interpreting the scaling info from
            // image metadata, so specifying dimensions explicitly here helps.
            // See https://github.com/coralnet/coralnet/issues/658
            currentSourceImage.width, currentSourceImage.height);

        // If processing parameters are neutral values, then we just need
        // the original image, so we're done.
        if (brightnessField.value === 0 && contrastField.value === 0) {
            return;
        }

        /* Divide the canvas into rectangles.  We'll operate on one
           rectangle at a time, and do a timeout between rectangles.
           That way we don't lock up the browser for a really long
           time when processing a large image. */

        var X_MAX = imageCanvas.width - 1;
        var Y_MAX = imageCanvas.height - 1;

        var RECT_SIZE = 1400;

        var x1 = 0, y1 = 0, xRanges = [], yRanges = [];
        while (x1 <= X_MAX) {
            var x2 = Math.min(x1 + RECT_SIZE - 1, X_MAX);
            xRanges.push([x1, x2]);
            x1 = x2 + 1;
        }
        while (y1 <= Y_MAX) {
            var y2 = Math.min(y1 + RECT_SIZE - 1, Y_MAX);
            yRanges.push([y1, y2]);
            y1 = y2 + 1;
        }

        var rects = [];
        for (var i = 0; i < xRanges.length; i++) {
            for (var j = 0; j < yRanges.length; j++) {
                rects.push({
                    'left': xRanges[i][0],
                    'top': yRanges[j][0],
                    'width': xRanges[i][1] - xRanges[i][0] + 1,
                    'height': yRanges[j][1] - yRanges[j][0] + 1
                });
            }
        }

        nowApplyingProcessing = true;
        $applyingText.css({'visibility': 'visible'});

        // The user-defined brightness and contrast are applied as
        // 'bias' and 'gain' according to this formula:
        // http://docs.opencv.org/2.4/doc/tutorials/core/basic_linear_transform/basic_linear_transform.html

        // We'll say the bias can increase/decrease the pixel value by
        // as much as 150.
        var brightness = Number(brightnessField.value);
        var brightnessFraction =
            (brightness - MIN_BRIGHTNESS) / (MAX_BRIGHTNESS - MIN_BRIGHTNESS);
        var bias = (150*2)*brightnessFraction - 150;

        // We'll say the gain can multiply the pixel values by
        // a range of MIN_BIAS to MAX_BIAS.
        // The middle contrast value must map to 1.
        var MIN_BIAS = 0.25;
        var MAX_BIAS = 3.0;
        var contrast = Number(contrastField.value);
        var contrastFraction =
            (contrast - MIN_CONTRAST) / (MAX_CONTRAST - MIN_CONTRAST);
        var gain = null;
        var gainFraction = null;
        if (contrastFraction > 0.5) {
            // Map 0.5~1.0 to 1.0~3.0
            gainFraction = (contrastFraction - 0.5) / (1.0 - 0.5);
            gain = (MAX_BIAS-1.0)*gainFraction + 1.0;
        }
        else {
            // Map 0.0~0.5 to 0.25~1.0
            gainFraction = contrastFraction / 0.5;
            gain = (1.0-MIN_BIAS)*gainFraction + MIN_BIAS;
        }

        applyBriConToRemainingRects(gain, bias, rects);
    }

    function applyBriConToRect(gain, bias, data, numPixels) {
        // Performance note: We tried having a curried function which was
        // called once for each pixel. However, this ended up taking 8-9
        // seconds for a 1400x1400 pixel rect, even if the function simply
        // returns immediately. (Firefox 50.0, 2016.11.28)
        // So the lesson is: function calls are usually cheap,
        // but don't underestimate using them by the million.
        var px;
        for (px = 0; px < numPixels; px++) {
            // 4 components per pixel, in RGBA order. We'll ignore alpha.
            data[4*px] = gain*data[4*px] + bias;
            data[4*px + 1] = gain*data[4*px + 1] + bias;
            data[4*px + 2] = gain*data[4*px + 2] + bias;
        }
    }

    function applyBriConToRemainingRects(gain, bias, rects) {
        if (redrawSignal === true) {
            nowApplyingProcessing = false;
            redrawSignal = false;
            $applyingText.css({'visibility': 'hidden'});

            redrawImage();
            return;
        }

        // "Pop" the first element from rects.
        var rect = rects.shift();

        // Grab the rect from the image canvas.
        var rectCanvasImageData = imageCanvas.getContext("2d")
            .getImageData(rect.left, rect.top, rect.width, rect.height);

        // Apply bri/con to the rect.
        applyBriConToRect(
            gain, bias, rectCanvasImageData.data,
            rect['width']*rect['height']);

        // Put the post-bri/con data on the image canvas.
        imageCanvas.getContext("2d").putImageData(
            rectCanvasImageData, rect.left, rect.top);

        if (rects.length > 0) {
            // Slightly delay the processing of the next rect, so we
            // don't lock up the browser for an extended period of time.
            // Note the use of curry() to produce a function.
            setTimeout(
                applyBriConToRemainingRects.curry(gain, bias, rects), 50
            );
        }
        else {
            nowApplyingProcessing = false;
            $applyingText.css({'visibility': 'hidden'});
        }
    }


    /* Public methods.
     * These are the only methods that need to be referred to as
     * <SingletonClassName>.<methodName>. */
    return {
        init: function (sourceImagesArg) {
            $resetButton = $('#resetImageOptionsButton');
            $applyingText = $('#applyingText');

            brightnessField = $('#id_brightness')[0];
            contrastField = $('#id_contrast')[0];
            MIN_BRIGHTNESS = Number(brightnessField.min);
            MAX_BRIGHTNESS = Number(brightnessField.max);
            MIN_CONTRAST = Number(contrastField.min);
            MAX_CONTRAST = Number(contrastField.max);

            // http://api.jqueryui.com/slider/
            var $brightnessSlider = $('#brightness_slider').slider({
                value: Number(brightnessField.value),
                min: MIN_BRIGHTNESS,
                max: MAX_BRIGHTNESS,
                step: 1,
                // When the slider is moved (by the user),
                // update the text field too.
                slide: function(event, ui) {
                    brightnessField.value = ui.value;
                },
                // When the slider value is changed, either by the user
                // directly or a programmatic change, re-draw the source image
                // and re-apply bri/con operations.
                change: redrawImage
            });
            var $contrastSlider = $('#contrast_slider').slider({
                value: Number(contrastField.value),
                min: MIN_CONTRAST,
                max: MAX_CONTRAST,
                step: 1,
                slide: function(event, ui) {
                    contrastField.value = ui.value;
                },
                change: redrawImage
            });

            // When the text fields are updated (by the user),
            // update the sliders too.
            brightnessField.addEventListener('change', function() {
                // If the browser supports the "number" input type, with
                // validity checking and all, then return if invalid.
                if (this.validity && !this.validity.valid) { return; }
                // If value box is empty, return.
                if (this.value === '') { return; }
                $brightnessSlider.slider('value', Number(this.value));
            });
            contrastField.addEventListener('change', function() {
                if (this.validity && !this.validity.valid) { return; }
                if (this.value === '') { return; }
                $contrastSlider.slider('value', Number(this.value));
            });

            sourceImages = sourceImagesArg;

            imageCanvas = $('#imageCanvas')[0];

            if (sourceImages.hasOwnProperty('scaled')) {
                preloadAndUseSourceImage('scaled');
            }
            else {
                preloadAndUseSourceImage('full');
            }

            // When the Reset button is clicked, reset image processing
            // parameters to default values, and redraw the image.
            $resetButton.click(function () {
                brightnessField.value = 0;
                contrastField.value = 0;
                $brightnessSlider.slider('value', 0);
                $contrastSlider.slider('value', 0);
                redrawImage();
            });
        },

        getImageCanvas: function () {
            return imageCanvas;
        }
    }
})();
