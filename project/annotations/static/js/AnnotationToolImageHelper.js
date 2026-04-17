class AnnotationToolImageHelper {

    get brightnessField() {
        return document.getElementById('id_brightness');
    }
    get contrastField() {
        return document.getElementById('id_contrast');
    }
    get brightnessSlider() {
        return document.getElementById('id_brightness_slider');
    }
    get contrastSlider() {
        return document.getElementById('id_contrast_slider');
    }

    get MIN_BRIGHTNESS() {
        return Number(this.brightnessField.min);
    }
    get MAX_BRIGHTNESS() {
        return Number(this.brightnessField.max);
    }
    get MIN_CONTRAST() {
        return Number(this.contrastField.min);
    }
    get MAX_CONTRAST() {
        return Number(this.contrastField.max);
    }

    get imageCanvas() {
        return document.getElementById('imageCanvas');
    }
    get resetButton() {
        return document.getElementById('resetImageOptionsButton');
    }
    get applyingText() {
        return document.getElementById('applyingText');
    }

    currentSourceImage = null;
    nowApplyingProcessing = false;
    redrawSignal = false;

    constructor(sourceImagesArg) {

        // Initialize value.
        this.brightnessSlider.value = this.brightnessField.value;
        // While the slider is moved by the user, update the text field too.
        this.brightnessSlider.addEventListener(
            'input', this.updateBrightnessTextField.bind(this));
        // When the slider is moved by the user and then released, redraw.
        this.brightnessSlider.addEventListener(
            'change', this.redrawImage.bind(this));

        this.contrastSlider.value = this.contrastField.value;
        this.contrastSlider.addEventListener(
            'input', this.updateContrastTextField.bind(this));
        this.contrastSlider.addEventListener(
            'change', this.redrawImage.bind(this));

        /*
        When the text fields are updated by the user: check validity of
        input, update the sliders too, and redraw.
        */
        this.brightnessField.addEventListener(
            'change', this.onBrightnessText.bind(this));
        this.contrastField.addEventListener(
            'change', this.onContrastText.bind(this));

        this.resetButton.addEventListener(
            'click', this.resetBriCon.bind(this));

        this.sourceImages = sourceImagesArg;
    }

    updateBrightnessTextField(event) {
        this.brightnessField.value = event.target.value;
    }
    updateContrastTextField(event) {
        this.contrastField.value = event.target.value;
    }

    onBrightnessText(event) {
        let field = event.target;
        // If the browser supports the "number" input type, with
        // validity checking and all, then return if invalid.
        if (field.validity && !field.validity.valid) { return; }
        // If value box is empty, return.
        if (field.value === '') { return; }

        this.brightnessSlider.value = Number(field.value);

        this.redrawImage();
    }
    onContrastText(event) {
        let field = event.target;
        if (field.validity && !field.validity.valid) { return; }
        if (field.value === '') { return; }

        this.contrastSlider.value = Number(field.value);

        this.redrawImage();
    }

    async loadSourceImages() {
        if (this.sourceImages.hasOwnProperty('scaled')) {
            await this.loadSourceImage('scaled');
        }
        await this.loadSourceImage('full');
    }

    resetImageExifOrientation(imageAsString) {
        let exifObj;

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
                            `Error when setting up the image: "${e.message}"`
                            + " \nIf the problem persists,"
                            + " please notify the admins.");
                        throw e;
                    }
                }
            }
            else {
                alert(
                    `Error when loading the image: "${e.message}"`
                    + " \nIf the problem persists, please notify the admins.");
                throw e;
            }
        }

        // If we're here, we successfully read the exif.
        // Set the orientation tag to the default value.
        exifObj['0th'][piexif.ImageIFD.Orientation] = 1;
        let editedExifStr = piexif.dump(exifObj);
        return piexif.insert(editedExifStr, imageAsString);
    }

    /*
    Load a source image, and swap it in as the image used in the
    annotation tool.

    Parameters:
    code - Which version of the image it is: 'scaled' or 'full'.

    Basic code pattern from: http://stackoverflow.com/a/1662153/
    */
    async loadSourceImage(code) {
        // Create an Image object.
        this.sourceImages[code].imgBuffer = new Image();
        let imgBuffer = this.sourceImages[code].imgBuffer;

        // Allow the image to be from a different domain such as S3.
        // https://developer.mozilla.org/en-US/docs/Web/HTML/CORS_enabled_image
        imgBuffer.crossOrigin = "Anonymous";

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
        let response = await fetch(this.sourceImages[code].url);

        let imageAsBinaryString;
        try {
            let blob = await response.blob();
            imageAsBinaryString = await this.readBlob(blob);
        }
        catch (e) {
            alert(
                `Error when retrieving the ${code} image: "${e.message}"`
                + " \nIf the problem persists, please notify the admins.");
            return;
        }

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
        let exifEditedDataString =
            this.resetImageExifOrientation(imageAsBinaryString);

        // Convert the data string to a base64 URL.
        let contentType = response.headers.get('content-type');
        let exifEditedDataURL = (
            "data:" + contentType
            + ";base64," + btoa(exifEditedDataString));

        // For debugging, it sometimes helps to load a full image that
        // (1) has different image content, so you can tell when it's swapped
        //     in, and/or
        // (2) is loaded after a delay, so you can zoom in first and then
        //     notice the resolution change when it happens.
        // Here's (2) in action: uncomment the below lines to try it.
        // NOTE: only use this for debugging, not for production.
        // if (code === 'full') {
        //     const SECONDS = 5;
        //     await new Promise(r => setTimeout(r, SECONDS * 1000));
        // }

        // Load the EXIF-edited image into the image canvas.
        imgBuffer.src = exifEditedDataURL;

        // Wait for image to load.
        await imgBuffer.decode();

        // Swap images.
        this.imageCanvas.width = this.sourceImages[code].width;
        this.imageCanvas.height = this.sourceImages[code].height;

        this.currentSourceImage = this.sourceImages[code];
        this.redrawImage();
    }

    readBlob(blob) {
      return new Promise((resolve, reject) => {
        let reader = new FileReader();

        reader.onload = () => {
          resolve(reader.result);
        };

        reader.onerror = reject;

        // TODO: This method is deprecated. The challenge is that the format it
        //  produces (binary string) is also pretty much deprecated in JS, and
        //  piexif is an outdated library which pretty much depends on that
        //  format. So it seems we need to replace piexif.
        reader.readAsBinaryString(blob);
      });
    }

    /* Redraw the source image, and apply brightness and contrast operations. */
    redrawImage() {
        // If we haven't loaded any image yet, don't do anything.
        if (this.currentSourceImage === null)
            return;

        // If processing is currently going on, emit the redraw signal to
        // tell it to stop processing and re-call this function.
        if (this.nowApplyingProcessing === true) {
            this.redrawSignal = true;
            return;
        }

        // Redraw the source image.
        // https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/drawImage
        this.imageCanvas.getContext("2d").drawImage(
            this.currentSourceImage.imgBuffer,
            // Canvas coordinates at which to place the top-left corner of
            // the source image.
            0, 0,
            // The dimensions to draw the image in the canvas. In some cases,
            // browsers have problems interpreting the scaling info from
            // image metadata, so specifying dimensions explicitly here helps.
            // See https://github.com/coralnet/coralnet/issues/658
            this.currentSourceImage.width, this.currentSourceImage.height);

        // If processing parameters are neutral values, then we just need
        // the original image, so we're done.
        if (
            this.brightnessField.value === 0
            && this.contrastField.value === 0
        ) {
            return;
        }

        /* Divide the canvas into rectangles.  We'll operate on one
           rectangle at a time, and do a timeout between rectangles.
           That way we don't lock up the browser for a really long
           time when processing a large image. */

        const X_MAX = this.imageCanvas.width - 1;
        const Y_MAX = this.imageCanvas.height - 1;

        const RECT_SIZE = 1400;

        let x1 = 0, y1 = 0, xRanges = [], yRanges = [];
        while (x1 <= X_MAX) {
            let x2 = Math.min(x1 + RECT_SIZE - 1, X_MAX);
            xRanges.push([x1, x2]);
            x1 = x2 + 1;
        }
        while (y1 <= Y_MAX) {
            let y2 = Math.min(y1 + RECT_SIZE - 1, Y_MAX);
            yRanges.push([y1, y2]);
            y1 = y2 + 1;
        }

        let rects = [];
        for (let i = 0; i < xRanges.length; i++) {
            for (let j = 0; j < yRanges.length; j++) {
                rects.push({
                    'left': xRanges[i][0],
                    'top': yRanges[j][0],
                    'width': xRanges[i][1] - xRanges[i][0] + 1,
                    'height': yRanges[j][1] - yRanges[j][0] + 1
                });
            }
        }

        this.nowApplyingProcessing = true;
        this.applyingText.style.visibility = 'visible';

        // The user-defined brightness and contrast are applied as
        // 'bias' and 'gain' according to this formula:
        // http://docs.opencv.org/2.4/doc/tutorials/core/basic_linear_transform/basic_linear_transform.html

        // We'll say the bias can increase/decrease the pixel value by
        // as much as 150.
        let brightness = Number(this.brightnessField.value);
        let brightnessFraction =
            (brightness - this.MIN_BRIGHTNESS)
            / (this.MAX_BRIGHTNESS - this.MIN_BRIGHTNESS);
        let bias = (150*2)*brightnessFraction - 150;

        // We'll say the gain can multiply the pixel values by
        // a range of MIN_BIAS to MAX_BIAS.
        // The middle contrast value must map to 1.
        const MIN_BIAS = 0.25;
        const MAX_BIAS = 3.0;
        let contrast = Number(this.contrastField.value);
        let contrastFraction =
            (contrast - this.MIN_CONTRAST)
            / (this.MAX_CONTRAST - this.MIN_CONTRAST);
        let gain;
        let gainFraction;
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

        this.applyBriConToRemainingRects(gain, bias, rects);
    }

    /*
    Reset image processing parameters to default values,
    and redraw the image.
    */
    resetBriCon() {
        this.brightnessField.value = 0;
        this.contrastField.value = 0;
        this.brightnessSlider.value = 0;
        this.contrastSlider.value = 0;
        this.redrawImage();
    }

    applyBriConToRect(gain, bias, data, numPixels) {
        // Performance note: We tried having a curried function which was
        // called once for each pixel. However, this ended up taking 8-9
        // seconds for a 1400x1400 pixel rect, even if the function simply
        // returns immediately. (Firefox 50.0, 2016.11.28)
        // So the lesson is: function calls are usually cheap,
        // but don't underestimate using them by the million.
        for (let px = 0; px < numPixels; px++) {
            // 4 components per pixel, in RGBA order. We'll ignore alpha.
            data[4*px] = gain*data[4*px] + bias;
            data[4*px + 1] = gain*data[4*px + 1] + bias;
            data[4*px + 2] = gain*data[4*px + 2] + bias;
        }
    }

    applyBriConToRemainingRects(gain, bias, rects) {
        if (this.redrawSignal === true) {
            this.nowApplyingProcessing = false;
            this.redrawSignal = false;
            this.applyingText.style.visibility = 'hidden';

            this.redrawImage();
            return;
        }

        // "Pop" the first element from rects.
        let rect = rects.shift();

        // Grab the rect from the image canvas.
        let rectCanvasImageData = this.imageCanvas.getContext("2d")
            .getImageData(rect.left, rect.top, rect.width, rect.height);

        // Apply bri/con to the rect.
        this.applyBriConToRect(
            gain, bias, rectCanvasImageData.data,
            rect['width']*rect['height']);

        // Put the post-bri/con data on the image canvas.
        this.imageCanvas.getContext("2d").putImageData(
            rectCanvasImageData, rect.left, rect.top);

        if (rects.length > 0) {
            // Slightly delay the processing of the next rect, so we
            // don't lock up the browser for an extended period of time.
            setTimeout(
                this.applyBriConToRemainingRects.bind(this, gain, bias, rects),
                50,
            );
        }
        else {
            this.nowApplyingProcessing = false;
            this.applyingText.style.visibility = 'hidden';
        }
    }
}


export default AnnotationToolImageHelper;
