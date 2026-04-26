const { test } = QUnit;
import fetchMock from '/static/js/fetch-mock.js';

import AnnotationToolImageHelper from '/static/js/AnnotationToolImageHelper.js';
import { useFixture } from '/static/js/test-utils.js';

let imageHelper;
// These numbers are from a specific example in this issue regarding
// EXIF resolution detection:
// https://github.com/coralnet/coralnet/issues/658
// See "EXIF scaling" QUnit module below.
let SCALED_WIDTH = 770;
let SCALED_HEIGHT = 775;
let FULL_WIDTH = 2568;
let FULL_HEIGHT = 2583;

let originalWindowAlert = window.alert;
let originalPiexifLoad = piexif.load;
let originalPiexifRemove = piexif.remove;


function instantiate(
        {
            scaled_name = 'scaled.jpg', full_name = 'full.jpg',
            full_width = FULL_WIDTH, full_height = FULL_HEIGHT,
        } = {}) {

    imageHelper = new AnnotationToolImageHelper(
        {
            'scaled': {
                'url': scaled_name,
                'width': SCALED_WIDTH,
                'height': SCALED_HEIGHT,
            },
            'full': {
                'url': full_name,
                'width': full_width,
                'height': full_height,
            },
        },
        null,
        {},
    );
}


function instantiateFullOnly() {
    imageHelper = new AnnotationToolImageHelper(
        {
            'full': {
                'url': 'full.jpg',
                'width': FULL_WIDTH,
                'height': FULL_HEIGHT,
            },
        },
        null,
        {},
    );
}


/*
If you want to download a test's crafted image to check its contents manually,
you can temporarily add a call to this function in the test code.
It should pop up a standard download dialog.
Credit: https://gist.github.com/philipstanislaus/c7de1f43b52531001412

Once downloaded, you can check the EXIF data with a web tool like this:
https://framebird.io/exif-metadata-viewer/jfif
Or with Python, like this function that checks scaling data (uses Pillow):
from PIL import Image
from PIL.ExifTags import IFD
def info(filepath):
    with Image.open(filepath) as im:
        exif = im.getexif()
    ifd = exif.get_ifd(IFD.Exif)
    print(f"Pixel data dimensions: {im.width} x {im.height}")
    print(f"EXIF IFD PixelX/YDimension: {ifd.get(40962)} x {ifd.get(40963)}")
    print(f"EXIF X/YResolution: {exif.get(282)} x {exif.get(283)}")
    print(f"EXIF ResolutionUnit: {exif.get(296)}")
*/
function downloadBlob(blob, filename) {
    let anchor = document.createElement('a');
    document.body.appendChild(anchor);
    anchor.style = 'display: none';

    let url = window.URL.createObjectURL(blob);
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.URL.revokeObjectURL(url);
}


function makeCanvas(width, height, pattern, color) {
    let canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    let context = canvas.getContext('2d');

    if (pattern === 'solid') {
        // Fill entire image with this color.
        context.fillStyle = color;
        context.fillRect(0, 0, canvas.width, canvas.height);
    }
    if (pattern === 'first_pixel') {
        // Fill just the upper left pixel with this color.
        // This can help to check that an image wasn't rotated
        // unexpectedly.
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
    }
    if (pattern === 'border') {
        // Draw a thin outer border with this color.
        // This can help to check that an image wasn't scaled down or up
        // unexpectedly.
        context.fillStyle = color;
        context.fillRect(0, 0, canvas.width, 1);
        context.fillRect(0, 0, 1, canvas.height);
        context.fillRect(0, canvas.height-1, canvas.width, 1);
        context.fillRect(canvas.width-1, 0, 1, canvas.height);
    }
    if (pattern === 'checker') {
        // Draw four quadrants of the image, each in a different color.
        // Having multiple explicit colors allows contrast testing;
        // two at an absolute minimum, but more makes the contrast changes
        // truer to 'real' scenarios.
        let [color1, color2, color3, color4] = color;
        context.fillStyle = color1;
        context.fillRect(0, 0, canvas.width/2, canvas.height/2);
        context.fillStyle = color2;
        context.fillRect(canvas.width/2, 0, canvas.width/2, canvas.height/2);
        context.fillStyle = color3;
        context.fillRect(
            canvas.width/2, canvas.height/2, canvas.width/2, canvas.height/2);
        context.fillStyle = color4;
        context.fillRect(0, canvas.height/2, canvas.width/2, canvas.height/2);
    }

    return canvas;
}


async function setImage(
    filename, width, height, pattern, color,
    {toAwaitBeforeLoad = null, exifObj = null,
     imageContentType = 'image/jpeg'} = {})
{
    let canvas = makeCanvas(width, height, pattern, color);

    let blob = await new Promise(
        resolve => canvas.toBlob(resolve, imageContentType));

    if (exifObj) {
        // Convert to string for piexif
        let imageAsBinaryString =
            await AnnotationToolImageHelper.readBlob(blob);

        let exifStr = piexif.dump(exifObj);
        imageAsBinaryString = piexif.insert(exifStr, imageAsBinaryString);

        // Back to a blob
        let uint8Array = Uint8Array.from(
            imageAsBinaryString, c => c.charCodeAt(0));
        blob = new Blob([uint8Array], {type: imageContentType});
    }

    if (toAwaitBeforeLoad) {
        // A Promise has been given which allows the fetch-caller and
        // the fetch-callback to wait for each other.
        // 1. Caller waits for the callback's about-to-load resolution. Then
        //    the caller can run some code, such as asserting expected state
        //    at this point.
        // 2. Callback waits for the caller's to-await-before-load resolution.
        //    Then the callback here can proceed with loading the image.
        let {promise: aboutToLoadPromise, resolve: atlResolve, reject}
            = Promise.withResolvers();
        let fetchCallback = async (url, options, request) => {
            atlResolve();
            await toAwaitBeforeLoad;
            return new Response(blob);
        };
        fetchMock.get(filename, fetchCallback);
        // We want to return the aboutToLoadPromise to the caller. To do so,
        // we wrap the aboutToLoadPromise in a hash; because if we didn't
        // wrap this Promise in anything, this Promise would become the
        // Promise that's 'used up' by the `await setImage(...)` call.
        return {'promise': aboutToLoadPromise};
    }
    else {
        fetchMock.get(filename, new Response(blob));
    }
}


QUnit.module("Load basic images", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');
    });
    hooks.afterEach(() => {
        fetchMock.reset();
    });

    test("full image only", async function(assert) {
        await setImage('full.jpg', FULL_WIDTH, FULL_HEIGHT, 'solid', 'red');
        instantiateFullOnly();
        await imageHelper.loadSourceImages();

        // Get any pixel (the first pixel, here).
        let pixelData = imageHelper.imageCanvas
            .getContext('2d').getImageData(0, 0, 1, 1).data;
        let [red, green, blue, _alpha] = pixelData;

        // This is jpg, so we don't expect a perfectly faithful
        // (255,0,0) red.
        // Instead just ensure this pixel is 'red enough'.
        assert.true(
            red - green - blue > 200,
            "Should have loaded the image, so an arbitrary pixel should be" +
            " close to red");
    });

    test("scaled image then full image", async function(assert) {
        let {promise: checkedScaledImagePromise, resolve: csipResolve, reject}
            = Promise.withResolvers();

        await setImage(
            'scaled.jpg', SCALED_WIDTH, SCALED_HEIGHT, 'solid', 'blue');
        let {promise: fullImageAboutToLoadPromise} = await setImage(
            'full.jpg', FULL_WIDTH, FULL_HEIGHT, 'solid', 'red',
            {toAwaitBeforeLoad: checkedScaledImagePromise},
        );
        instantiate();
        let fullImageLoadedPromise = imageHelper.loadSourceImages();

        // Wait for loading to proceed far enough so that the scaled image
        // is loaded, but the full image isn't yet.
        await fullImageAboutToLoadPromise;
        let pixelData = imageHelper.imageCanvas
            .getContext('2d').getImageData(0, 0, 1, 1).data;
        let [red, green, blue, _alpha] = pixelData;
        assert.true(
            blue - red - green > 200,
            "Should have loaded the scaled image, so an arbitrary pixel" +
            " should be close to blue");

        // Allow loading of the full image to proceed.
        csipResolve();
        await fullImageLoadedPromise;
        pixelData = imageHelper.imageCanvas
            .getContext('2d').getImageData(0, 0, 1, 1).data;
        [red, green, blue, _alpha] = pixelData;
        assert.true(
            red - green - blue > 200,
            "Should have loaded the full image, so an arbitrary pixel" +
            " should be close to red");
    });
});


function setupBriConTest({perRectAction = null} = {}) {

    let {promise: doneProcessingPromise, resolve: dppResolve, reject}
        = Promise.withResolvers();
    let originalApplyToRects =
        imageHelper.applyBriConToRemainingRects.bind(imageHelper);
    let newApply = (gain, bias, rects) => {
        originalApplyToRects(gain, bias, rects);
        if (perRectAction) {
            // Some kind of bookkeeping, etc. for the test's purposes.
            perRectAction();
        }
        // Resolve the Promise when the image is fully processed.
        if (rects.length === 0) {
            dppResolve();
        }
    };
    imageHelper.applyBriConToRemainingRects = newApply.bind(imageHelper);
    return doneProcessingPromise;
}


/* https://css-tricks.com/converting-color-spaces-in-javascript/ */
function rgbToHsl(r, g, b) {
    // Make r, g, and b fractions of 1
    r /= 255;
    g /= 255;
    b /= 255;

    // Find greatest and smallest channel values
    let cmin = Math.min(r,g,b),
        cmax = Math.max(r,g,b),
        delta = cmax - cmin,
        h,
        s,
        l;

    // Calculate hue
    // No difference
    if (delta === 0)
        h = 0;
    // Red is max
    else if (cmax === r)
        h = ((g - b) / delta) % 6;
    // Green is max
    else if (cmax === g)
        h = (b - r) / delta + 2;
    // Blue is max
    else
        h = (r - g) / delta + 4;

    h = Math.round(h * 60);

    // Make negative hues positive behind 360°
    if (h < 0)
        h += 360;

    // Calculate lightness
    l = (cmax + cmin) / 2;

    // Calculate saturation
    s = delta === 0 ? 0 : delta / (1 - Math.abs(2 * l - 1));

    // Multiply l and s by 100
    s = +(s * 100).toFixed(1);
    l = +(l * 100).toFixed(1);

    return [h, s, l];
}


function assertCanvasColors(assert, expectedColors) {

    // Pixels close to each of the four corners.
    let context = imageHelper.imageCanvas.getContext('2d');
    let pixelDatas = [
        context.getImageData(10, 10, 1, 1).data,
        context.getImageData(imageHelper.imageCanvas.width-10, 10, 1, 1).data,
        context.getImageData(
            imageHelper.imageCanvas.width-10,
            imageHelper.imageCanvas.height-10, 1, 1).data,
        context.getImageData(10, imageHelper.imageCanvas.height-10, 1, 1).data,
    ];
    let pixelNames = [
        "Upper left", "Upper right", "Lower right", "Lower left"];
    let index = 0;

    for (let pixelData of pixelDatas) {
        let [red, green, blue, _alpha] = pixelData;
        let [hue, sat, light] = rgbToHsl(red, green, blue);
        let [xhue, xsat, xlight] = expectedColors[index];

        assert.true(
            // We won't be exacting, due to the rgb -> hsl conversion
            // and jpeg compression.
            Math.abs(hue - xhue) < 4,
            `${pixelNames[index]} pixel's hue should be close to expected`
            + `(${hue} vs. ${xhue}`);
        assert.true(
            Math.abs(sat - xsat) < 4,
            `${pixelNames[index]} pixel's saturation should be close to expected`
            + `(${sat} vs. ${xsat}`);
        assert.true(
            Math.abs(light - xlight) < 4,
            `${pixelNames[index]} pixel's lightness should be close to expected`
            + `(${light} vs. ${xlight}`);

        index++;
    }
}


QUnit.module("Brightness and contrast", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');

        await setImage(
            'scaled.jpg', SCALED_WIDTH, SCALED_HEIGHT, 'solid', 'blue');
        // Multicolor pattern, with nontrivial saturation and lightness, so
        // that contrast and brightness adjustment do different nontrivial
        // things.
        await setImage(
            'full.jpg', 2400, 1500, 'checker',
            ['hsl(90 30% 70%)', 'hsl(140 70% 30%)',
             'hsl(190 30% 30%)', 'hsl(240 70% 70%)'],
        );
        instantiate({full_width: 2400, full_height: 1500});

        // Individual tests can overwrite this to increase/decrease the number
        // of rectangles to process.
        imageHelper.RECT_SIZE = 500;

        imageHelper.brightnessSlider.value = 0;
        imageHelper.brightnessField.value = 0;
        imageHelper.contrastSlider.value = 0;
        imageHelper.contrastField.value = 0;

        await imageHelper.loadSourceImages();
    });
    hooks.afterEach(() => {
        fetchMock.reset();
    });

    test.each(
            "rect count",
            [
                [500, 5*3],
                [480, 5*4],
                [460, 6*4],
            ],
            async (assert, [rectSize, expectedRects]) => {

        imageHelper.RECT_SIZE = rectSize;
        let rectsProcessed = 0;
        let perRectAction = () => {rectsProcessed++;}
        let doneProcessingPromise =
            setupBriConTest({perRectAction: perRectAction});

        imageHelper.brightnessSlider.value = 20;
        // Although redrawing happens on our change listener, we need to fire
        // an input event first so that the updated slider value is recognized.
        imageHelper.brightnessSlider.dispatchEvent(new Event('input'));
        imageHelper.brightnessSlider.dispatchEvent(new Event('change'));
        // Wait for the brightness application to finish on the whole image
        await doneProcessingPromise;
        assert.equal(
            rectsProcessed, expectedRects,
            "Number of rectangles processed for bri/con should be as" +
            " expected, given the image width/height and rectangle size");
    });

    test("brightness slider", async function(assert) {
        let doneProcessingPromise = setupBriConTest();

        imageHelper.brightnessSlider.value = 20;
        assert.equal(
            imageHelper.brightnessField.value, 0,
            "Field value should not have changed yet");
        // Should not have redrawn with new brightness
        assertCanvasColors(
            assert, [[90,30,70], [140,70,30], [190,30,30], [240,70,70]]);

        imageHelper.brightnessSlider.dispatchEvent(new Event('input'));
        assert.equal(
            imageHelper.brightnessField.value, 20,
            "Field value should have changed");
        // Should not have redrawn with new brightness
        assertCanvasColors(
            assert, [[90,30,70], [140,70,30], [190,30,30], [240,70,70]]);

        imageHelper.brightnessSlider.dispatchEvent(new Event('change'));
        // Wait for the brightness application to finish on the whole image
        await doneProcessingPromise;
        // Should have redrawn with new brightness
        assertCanvasColors(
            assert, [[90,49,82], [140,50,42], [190,22,42], [240,100,80]]);
    });

    test("contrast slider", async function(assert) {
        let doneProcessingPromise = setupBriConTest();

        imageHelper.contrastSlider.value = 20;
        assert.equal(
            imageHelper.contrastField.value, 0,
            "Field value should not have changed yet");
        // Should not have redrawn with new contrast
        assertCanvasColors(
            assert, [[90,30,70], [140,70,30], [190,30,30], [240,70,70]]);

        imageHelper.contrastSlider.dispatchEvent(new Event('input'));
        assert.equal(
            imageHelper.contrastField.value, 20,
            "Field value should have changed");
        // Should not have redrawn with new contrast
        assertCanvasColors(
            assert, [[90,30,70], [140,70,30], [190,30,30], [240,70,70]]);

        imageHelper.contrastSlider.dispatchEvent(new Event('change'));
        // Wait for the contrast application to finish on the whole image
        await doneProcessingPromise;
        // Should have redrawn with new contrast
        assertCanvasColors(
            assert, [[66,100,93], [140,70,42], [190,30,42], [240,100,84]]);
    });

    test("negative brightness", async function(assert) {
        let doneProcessingPromise = setupBriConTest();

        imageHelper.brightnessSlider.value = -30;
        imageHelper.brightnessSlider.dispatchEvent(new Event('input'));
        imageHelper.brightnessSlider.dispatchEvent(new Event('change'));

        assert.equal(
            imageHelper.brightnessField.value, -30,
            "Field value should have changed");

        await doneProcessingPromise;
        assertCanvasColors(
            assert, [[89,19,52], [131,100,17], [190,74,12], [240,44,52]]);
    });

    test("negative contrast", async function(assert) {
        let doneProcessingPromise = setupBriConTest();

        imageHelper.contrastSlider.value = -30;
        imageHelper.contrastSlider.dispatchEvent(new Event('input'));
        imageHelper.contrastSlider.dispatchEvent(new Event('change'));

        assert.equal(
            imageHelper.contrastField.value, -30,
            "Field value should have changed");

        await doneProcessingPromise;
        assertCanvasColors(
            assert, [[88,15,54], [140,70,23], [190,30,23], [240,35,54]]);
    });

    test("brightness text field", async function(assert) {
        let doneProcessingPromise = setupBriConTest();

        imageHelper.brightnessField.value = 120;
        imageHelper.brightnessField.dispatchEvent(new Event('change'));
        assert.equal(
            imageHelper.brightnessSlider.value, 0,
            "Slider value should not have updated, due to out-of-range input");
        // Should not have redrawn with new brightness
        assertCanvasColors(
            assert, [[90,30,70], [140,70,30], [190,30,30], [240,70,70]]);

        imageHelper.brightnessField.value = 100;
        imageHelper.brightnessField.dispatchEvent(new Event('change'));
        assert.equal(
            imageHelper.brightnessSlider.value, 100,
            "Slider value should have updated");
        // Wait for the brightness application to finish on the whole image
        await doneProcessingPromise;
        // Should have redrawn with new brightness
        assertCanvasColors(
            assert, [[0,0,100], [147,100,84], [190,79,89], [0,0,100]]);
    });

    test("contrast text field", async function(assert) {
        let doneProcessingPromise = setupBriConTest();

        imageHelper.contrastField.value = -120;
        imageHelper.contrastField.dispatchEvent(new Event('change'));
        assert.equal(
            imageHelper.contrastSlider.value, 0,
            "Slider value should not have updated, due to out-of-range input");
        // Should not have redrawn with new contrast
        assertCanvasColors(
            assert, [[90,30,70], [140,70,30], [190,30,30], [240,70,70]]);

        imageHelper.contrastField.value = -100;
        imageHelper.contrastField.dispatchEvent(new Event('change'));
        assert.equal(
            imageHelper.contrastSlider.value, -100,
            "Slider value should have updated");
        // Wait for the contrast application to finish on the whole image
        await doneProcessingPromise;
        // Should have redrawn with new contrast
        assertCanvasColors(
            assert, [[87,12,18], [140,70,8], [190,30,8], [240,30,18]]);
    });

    test("reset button", async function(assert) {
        let doneProcessingPromise = setupBriConTest();

        imageHelper.brightnessSlider.value = 20;
        imageHelper.brightnessSlider.dispatchEvent(new Event('input'));
        imageHelper.brightnessSlider.dispatchEvent(new Event('change'));
        await doneProcessingPromise;
        // Should have redrawn with new brightness
        assertCanvasColors(
            assert, [[90,49,82], [140,50,42], [190,22,42], [240,100,80]]);

        imageHelper.resetButton.dispatchEvent(new Event('click'));
        // Should have reset; this should happen synchronously
        assertCanvasColors(
            assert, [[90,30,70], [140,70,30], [190,30,30], [240,70,70]]);
    });

    test("overlapping actions", async function(assert) {
        // We expect 5*3 = 15 rectangles.
        imageHelper.RECT_SIZE = 500;

        let updatedContrast = false;
        let {promise: updatedContrastPromise, resolve: ucpResolve, reject1}
            = Promise.withResolvers();

        let {promise: halfDoneBrightnessPromise, resolve: hdbpResolve, reject2}
            = Promise.withResolvers();
        let {promise: doneBriAndConPromise, resolve: dbacpResolve, reject3}
            = Promise.withResolvers();
        let originalApplyToRects =
            imageHelper.applyBriConToRemainingRects.bind(imageHelper);
        let applyCalls = 0;
        let newApply = (gain, bias, rects) => {
            if (!updatedContrast && rects.length === 7) {
                // 7 rectangles left (8 processed) in the brightness-only phase.
                hdbpResolve();
                // Do not proceed until we update the contrast slider.
                updatedContrastPromise.then(
                    originalApplyToRects.bind(imageHelper, gain, bias, rects));
            }
            else {
                originalApplyToRects(gain, bias, rects);

                if (updatedContrast && rects.length === 0) {
                    // 0 rectangles left (15 processed) in the
                    // brightness-and-contrast phase.
                    dbacpResolve();
                }
            }
            applyCalls++;
        };
        imageHelper.applyBriConToRemainingRects = newApply.bind(imageHelper);

        // Set brightness to 20 and trigger the events to start processing it.
        imageHelper.brightnessSlider.value = 20;
        imageHelper.brightnessSlider.dispatchEvent(new Event('input'));
        imageHelper.brightnessSlider.dispatchEvent(new Event('change'));
        // Wait for half the rectangles to be processed.
        await halfDoneBrightnessPromise;

        // At this point processing should be paused halfway (we forced it to
        // wait for a Promise).
        // Set contrast to 20 and trigger the events to start processing it.
        imageHelper.contrastSlider.value = 20;
        imageHelper.contrastSlider.dispatchEvent(new Event('input'));
        imageHelper.contrastSlider.dispatchEvent(new Event('change'));
        updatedContrast = true;
        // Unpause processing. This should interrupt the previous half-done
        // processing, and start a new round of processing.
        ucpResolve();
        // Wait for all the rectangles to be processed.
        await doneBriAndConPromise;

        assert.equal(
            applyCalls, 8+1+15,
            "24 apply calls should have been processed: 8 for processing" +
            " rects in the brightness-only phase, 1 to exit that phase," +
            " and 15 in the bri+con phase (of note, phase 1 should have run" +
            " only partially, so it shouldn't be 15 or 30 calls)");
    });
});


async function doExifRotationTest(assert, exifObj) {
    await setImage(
        'scaled.jpg', SCALED_WIDTH, SCALED_HEIGHT, 'first_pixel', 'blue');
    await setImage(
        'full.jpg', FULL_WIDTH, FULL_HEIGHT, 'first_pixel', 'red',
        {exifObj: exifObj},
    );

    instantiate();
    await imageHelper.loadSourceImages();

    let pixelData = imageHelper.imageCanvas
        .getContext('2d')
        .getImageData(0, 0, 1, 1).data;
    let [red, green, blue, _alpha] = pixelData;
    assert.true(
        red - green - blue > 200,
        "Image should be loaded unrotated,"
        + " so the upper left corner pixel should be close to red");
}


QUnit.module("EXIF rotation", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');
    });
    hooks.afterEach(() => {
        fetchMock.reset();
    });

    test("No EXIF rotation", async function(assert) {
        await doExifRotationTest(assert, {});
    });

    test("90 degree EXIF rotation in full image", async function(assert) {
        let zeroth = {};
        zeroth[piexif.ImageIFD.Orientation] = 6;
        let exifObj = {'0th': zeroth};
        await doExifRotationTest(assert, exifObj);
    });
});


async function doExifScalingTest(assert, exifObj) {
    await setImage(
        'scaled.jpg', SCALED_WIDTH, SCALED_HEIGHT, 'border', 'blue');
    await setImage(
        'full.jpg', FULL_WIDTH, FULL_HEIGHT, 'border', 'red',
        {exifObj: exifObj},
    );

    instantiate();
    await imageHelper.loadSourceImages();

    let pixelData = imageHelper.imageCanvas
        .getContext('2d')
        .getImageData(FULL_WIDTH-1, FULL_HEIGHT-1, 1, 1).data;
    let [red, green, blue, _alpha] = pixelData;
    assert.true(
        red - green - blue > 200,
        "Image should be loaded with full dimensions, faithful to the"
        + " pixel data, so the far corner pixel should be close to red");
}


/*
These test cases are based on Virtlink's comment here:
https://github.com/coralnet/coralnet/issues/658#issuecomment-4268345016
*/
QUnit.module("EXIF scaling", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');
    });
    hooks.afterEach(() => {
        fetchMock.reset();
    });

    test("No EXIF scaling fields present", async function(assert) {
        await doExifScalingTest(assert, {});
    });

    /*
    Lightroom Classic can produce images like this.
    Not known to be a special case in any image viewers, but just making sure
    our EXIF-related code doesn't do anything weird with it.
    */
    test("EXIF resolution fields present, but not dimension fields", async function(assert) {
        let zeroth = {};
        // Rational: array of numerator and denominator
        zeroth[piexif.ImageIFD.XResolution] = [240, 1];
        zeroth[piexif.ImageIFD.YResolution] = [240, 1];
        zeroth[piexif.ImageIFD.ResolutionUnit] = 2;
        let exifObj = {'0th': zeroth};

        await doExifScalingTest(assert, exifObj);
    });

    /*
    This test is for the following case in the HTML spec:
    https://html.spec.whatwg.org/multipage/images.html#preparing-an-image-for-presentation
    - dimX is a positive integer;
    - dimY is a positive integer;
    - resX is a positive floating-point number;
    - resY is a positive floating-point number;
    - physicalWidth × 72 / resX is dimX; [72 CSS points = 1 inch, per spec]
    - physicalHeight × 72 / resY is dimY;
    - resUnit is 2 (Inch)

    PhotoPea can produce images like this. In this case, browsers use the
    dimensions given in EXIF when displaying the image, per the spec.
    However, it doesn't make sense for the annotation tool to respect these
    EXIF dimensions: the canvas is already being scaled to the annotation
    tool's interactable area.
    So we make sure the annotation tool ignores these EXIF dimensions.

    (For the record, this test's equivalent for centimeters instead
    of inches did not get interpreted the same way by browsers. Not sure why
    the spec only stipulates inches, but that's indeed how it is.)
    */
    test("EXIF resolution and dimension fields present, with dimensions * resolution / pixel data dimensions = 72", async function(assert) {
        let zeroth = {};
        // Rational: array of numerator and denominator
        zeroth[piexif.ImageIFD.XResolution] = [240, 1];
        zeroth[piexif.ImageIFD.YResolution] = [240, 1];
        zeroth[piexif.ImageIFD.ResolutionUnit] = 2;
        let exif = {};
        exif[piexif.ExifIFD.PixelXDimension] = SCALED_WIDTH;
        exif[piexif.ExifIFD.PixelYDimension] = SCALED_HEIGHT;
        let exifObj = {'0th': zeroth, 'Exif': exif};

        await doExifScalingTest(assert, exifObj);
    });

    /*
    Images like this can come from Photoshop on Windows, or can come directly
    from cameras.
    Not known to be a special case in any image viewers, but just making sure
    our EXIF-related code doesn't do anything weird with it.
    */
    test("EXIF resolution and dimension fields present, with dimensions = pixel data dimensions", async function(assert) {
        let zeroth = {};
        // Rational: array of numerator and denominator
        zeroth[piexif.ImageIFD.XResolution] = [240, 1];
        zeroth[piexif.ImageIFD.YResolution] = [240, 1];
        zeroth[piexif.ImageIFD.ResolutionUnit] = 2;
        let exif = {};
        exif[piexif.ExifIFD.PixelXDimension] = FULL_WIDTH;
        exif[piexif.ExifIFD.PixelYDimension] = FULL_HEIGHT;
        let exifObj = {'0th': zeroth, 'Exif': exif};

        await doExifScalingTest(assert, exifObj);
    });
});


async function makeImageWithExif(exifObj) {
    let canvas = makeCanvas(FULL_WIDTH, FULL_HEIGHT, 'solid', 'red');
    let blob = await new Promise(
        resolve => canvas.toBlob(resolve, 'image/jpeg'));
    let imageAsString =
        await AnnotationToolImageHelper.readBlob(blob);
    let editedExifStr = piexif.dump(exifObj);
    return piexif.insert(editedExifStr, imageAsString);
}


async function makeImageWithResolutionExif() {
    let zeroth = {};
    zeroth[piexif.ImageIFD.XResolution] = [240, 1];
    zeroth[piexif.ImageIFD.YResolution] = [240, 1];
    zeroth[piexif.ImageIFD.ResolutionUnit] = 2;
    let exifObj = {'0th': zeroth};

    return makeImageWithExif(exifObj);
}


async function assertExifIntact(assert, imageAsString, message) {
    let exifObj = piexif.load(imageAsString);
    let zeroth = exifObj['0th']
    assert.deepEqual(
        // These are the resolution fields.
        [zeroth['282'], zeroth['283'], zeroth['296']],
        [[240, 1], [240, 1], 2],
        message,
    );
}


QUnit.module("EXIF error cases", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');
    });
    hooks.afterEach(() => {
        fetchMock.reset();
        window.alert = originalWindowAlert;
        piexif.load = originalPiexifLoad;
        piexif.remove = originalPiexifRemove;
    });

    /*
    This test ensures that the general pattern of the following tests,
    excluding the mocking of piexif.load() to throw certain errors,
    results in the EXIF remaining intact.
    */
    test("No error leaves EXIF intact", async function(assert) {
        let imageWithExifAsString = await makeImageWithResolutionExif();

        let processedImageAsString = AnnotationToolImageHelper
            .resetImageExifOrientation(imageWithExifAsString);

        await assertExifIntact(
            assert, processedImageAsString,
            "EXIF should be intact after loading into canvas");
    });

    /*
    Ensure that this piexif error results in the EXIF being stripped
    before further processing.

    This test deals directly with the image binary data, because
    testing at the canvas level instead does not preserve EXIF. That is,
    while writing image data to a canvas takes the EXIF into account when
    writing the pixels to the canvas, the canvas does not contain
    EXIF data in it. So going back out from canvas to image binary data
    cannot get any EXIF, which makes it impossible to test the specific
    thing we want to test.
    */
    test("Unpack error", async function(assert) {
        let imageWithExifAsString = await makeImageWithResolutionExif();

        // Ideally we'd be able to construct some EXIF data which actually
        // gets this error, but that seemingly requires either an externally
        // constructed fixture or substantial duplication of low-level
        // piexif logic.
        // We'll just go simpler and fake it.

        piexif.load = () => {
            throw new Error("'unpack' error. Got invalid type argument.");
        };
        let processedImageAsString = AnnotationToolImageHelper
            .resetImageExifOrientation(imageWithExifAsString);
        piexif.load = originalPiexifLoad;

        let processedImageExifObj = piexif.load(processedImageAsString);
        assert.equal(
            Object.keys(processedImageExifObj['0th']).length, 0,
            "Entire EXIF should be stripped after detecting an invalid type",
        );
    });

    test("Invalid file data", async function(assert) {
        let imageWithExifAsString = await makeImageWithResolutionExif();

        // Ideally we'd be able to construct an image with "EXIF" data which
        // actually gets this error, but that seemingly requires either an
        // externally constructed fixture or substantial duplication of
        // low-level piexif logic.
        // We'll just go simpler and fake it.

        piexif.load = () => {
            throw new Error("'load' gots invalid file data.");
        };
        let processedImageAsString = AnnotationToolImageHelper
            .resetImageExifOrientation(imageWithExifAsString);
        piexif.load = originalPiexifLoad;

        let processedImageExifObj = piexif.load(processedImageAsString);
        assert.equal(
            Object.keys(processedImageExifObj['0th']).length, 0,
            "Entire EXIF should be stripped after detecting invalid data",
        );
    });

    test("Incorrect value type to decode", async function(assert) {
        let imageWithExifAsString = await makeImageWithResolutionExif();

        // Ideally we'd be able to construct some EXIF data which actually
        // gets this error, but that seemingly requires either a fixture or
        // substantial duplication of low-level piexif logic.
        // We'll just go simpler and fake it.
        piexif.load = () => {
            throw new Error(
                "Exif might be wrong. Got incorrect value type to decode." +
                " type:0");
        };
        let processedImageAsString = AnnotationToolImageHelper
            .resetImageExifOrientation(imageWithExifAsString);
        piexif.load = originalPiexifLoad;

        let processedImageExifObj = piexif.load(processedImageAsString);
        assert.equal(
            Object.keys(processedImageExifObj['0th']).length, 0,
            "Entire EXIF should be stripped after detecting an incorrect" +
            " value type",
        );
    });

    /*
    A more meaningful version of this test would involve using a PNG that
    actually has EXIF data. However, that would currently require an externally
    constructed fixture, which we haven't bothered to make yet.
    */
    test("Not jpeg", async function(assert) {
        let canvas = makeCanvas(
            FULL_WIDTH, FULL_HEIGHT, 'first_pixel', 'red',
        );

        let blob = await new Promise(
            resolve => canvas.toBlob(resolve, 'image/png'));
        let originalImageString =
            await AnnotationToolImageHelper.readBlob(blob);
        let processedImageString = AnnotationToolImageHelper
            .resetImageExifOrientation(originalImageString);
        assert.strictEqual(
            originalImageString, processedImageString,
            "PNG should be unedited");
    });

    test("Error when loading", async function(assert) {
        // Mock window.alert() so that we don't actually have to interact
        // with an alert dialog. Also, so we can assert its contents.
        let alertMessage;
        window.alert = (message) => {alertMessage = message;};

        try {
            // It's expecting the image as a string, and we're giving
            // a Number.
            AnnotationToolImageHelper
                .resetImageExifOrientation(10);
        }
        catch {
            // We could get the thrown error's message here, but
            // we're just asserting on the alert message which
            // contains that already.
        }

        assert.strictEqual(
            alertMessage,
            `Error when loading the image: "'load' gots invalid`
            + ` type argument."`
            + ` \nIf the problem persists, please notify the admins.`);
    });

    test("Error when setting up", async function(assert) {
        // This case shouldn't happen unless there's a possible situation we
        // don't know about. But we want to ensure the user is alerted in
        // this case.
        // resetImageExifOrientation() has a piexif.load() call and a
        // piexif.remove() call, both taking the same arg. To test this case,
        // we want the arg to be invalid for only the second call.
        // To fake this, we mock piexif.remove() to just throw an unexpected
        // error.
        piexif.remove = () => {throw new Error("Unexpected error");};

        let alertMessage;
        window.alert = (message) => {alertMessage = message;};

        try {
            // We get to the remove() call using the invalid file data case.
            AnnotationToolImageHelper.resetImageExifOrientation('test');
        }
        catch {
        }

        assert.strictEqual(
            alertMessage,
            `Error when setting up the image: "Unexpected error"`
            + ` \nIf the problem persists, please notify the admins.`);
    });
});


QUnit.module("Other error cases", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');
    });
    hooks.afterEach(() => {
        fetchMock.reset();
        window.alert = originalWindowAlert;
    });

    test("Error when retrieving image", async function(assert) {
        fetchMock.get('full.jpg', () => {throw new Error("An error");});
        instantiateFullOnly();

        let alertMessage;
        window.alert = (message) => {alertMessage = message;};

        try {
            await imageHelper.loadSourceImages();
        }
        catch {
        }

        assert.strictEqual(
            alertMessage,
            `Error when retrieving the full image: "An error"`
            + ` \nIf the problem persists, please notify the admins.`);
    });
});
