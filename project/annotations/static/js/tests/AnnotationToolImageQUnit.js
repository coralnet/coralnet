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


function instantiate({scaled_name = 'scaled.jpg', full_name = 'full.jpg'} = {}) {
    imageHelper = new AnnotationToolImageHelper(
        {
            'scaled': {
                'url': scaled_name,
                'width': SCALED_WIDTH,
                'height': SCALED_HEIGHT,
            },
            'full': {
                'url': full_name,
                'width': FULL_WIDTH,
                'height': FULL_HEIGHT,
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
    context.fillStyle = color;

    if (pattern === 'solid') {
        // Fill entire image with this color.
        context.fillRect(0, 0, canvas.width, canvas.height);
    }
    if (pattern === 'first_pixel') {
        // Fill just the upper left pixel with this color.
        // This can help to check that an image wasn't rotated
        // unexpectedly.
        context.fillRect(0, 0, 1, 1);
    }
    if (pattern === 'border') {
        // Draw a thin outer border with this color.
        // This can help to check that an image wasn't scaled down or up
        // unexpectedly.
        context.fillRect(0, 0, canvas.width, 1);
        context.fillRect(0, 0, 1, canvas.height);
        context.fillRect(0, canvas.height-1, canvas.width, 1);
        context.fillRect(canvas.width-1, 0, 1, canvas.height);
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
