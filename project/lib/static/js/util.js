/*
General-purpose JS utility functions can go here.
*/

var util = {

    /*
    Add a JS event that will run when the page is loaded.
    This will just add to the "events to run" list, it won't
    override previously specified events.

    From http://simonwillison.net/2004/May/26/addLoadEvent/
    */
    addLoadEvent: function(func) {
        var oldonload = window.onload;
        if (typeof window.onload != 'function') {
            window.onload = func;
        } else {
            window.onload = function() {
                if (oldonload) {
                    oldonload();
                }
                func();
            }
        }
    },

    /*
    Wrapper around the standard fetch() which does error handling.
    @param resource - url or other resource to fetch (see standard fetch())
    @param options - see standard fetch()
    @param callback - function to call when the response is OK and converted
      to JSON. Optional; a no-op if not specified.
    @return - the Promise that fetch() returns. One possible use is to
      `await` this Promise and then run some code, instead of using the
      callback param.
    */
    fetch: function(resource, options, callback) {
        // Default callback is a no-op
        callback = callback || ((responseJson) => {return responseJson});

        return fetch(resource, options)
            .then(response => {
                if (!response.ok) {
                    // This can be "Internal server error" for example.
                    throw new Error(response.statusText);
                }
                return response.json();
            })
            .then(callback)
            .catch(error => {
                alert(
                    "There was an error:" +
                    `\n${error}` +
                    "\nIf the problem persists, please notify us on the forum."
                );
                throw error;
            });
    },

    /* Takes a number representing a number of bytes, and returns a
     * human-readable filesize string in B, KB, or MB. */
    filesizeDisplay: function(bytes) {
        var KILO = 1024;
        var MEGA = 1024*1024;

        if (bytes < KILO) {
            return bytes + " B";
        }
        else if (bytes < MEGA) {
            return Math.floor(bytes / KILO) + " KB";
        }
        else {
            return (Math.floor(bytes * 100 / MEGA) / 100) + " MB";
        }
    },

    /*
    Can be used to catch and alert about errors from jQuery ajax calls.
    For the non-jQuery fetch(), see util.fetch() instead.
    */
    handleServerError: function(jqXHR, textStatus, errorThrown) {
        if (textStatus === 'abort') {
            // A manually aborted request, not a server issue.
            return;
        }
        if (textStatus === 'error' && errorThrown === '') {
            // As far as we've seen so far, this case only happens when you
            // interrupt an Ajax request with another action. So the alert
            // below will be more confusing than helpful to users.
            //
            // For example, go to a label-detail page and
            // navigate away before the example patches finish loading.
            // That should trigger this case. On the server side, we observe
            // something like "error: [Errno 10053] An established connection
            // was aborted by the software in your host machine".
            console.log("There was a server error: error / [blank]");
            return;
        }

        // The most common case is "error" / "Internal Server Error",
        // but there may be other cases too.
        // See: https://api.jquery.com/jQuery.ajax/
        alert(
            "There was a server error:" +
            "\n{0} / {1}".format(textStatus, errorThrown) +
            "\nIf the problem persists, please let us know on the forum."
        )
    },

    /*
    Take a mouse event and return "LEFT", "MIDDLE", or "RIGHT" depending
    on which mouse button was clicked.

    From http://unixpapa.com/js/mouse.html
    "The following test works for all browsers except Opera 7."
    As of Aug 17, 2011
    */
    identifyMouseButton: function(event) {
        if (event.which == null)
           /* IE case */
           return (event.button < 2) ? "LEFT" :
                     ((event.button == 4) ? "MIDDLE" : "RIGHT");
        else
           /* All others */
           return (event.which < 2) ? "LEFT" :
                     ((event.which == 2) ? "MIDDLE" : "RIGHT");
    },

    /*
    When the user tries to leave the page by clicking a link, closing the
    tab, etc., a confirmation dialog will pop up. In most browsers, the
    dialog will have the specified message, along with a generic message
    from the browser like "Are you sure you want to leave this page?".
    */
    pageLeaveWarningEnable: function(message) {
        var helper = function (message, e) {

            // Apparently some browsers take the message with e.returnValue,
            // and other browsers take it with this function's return value.
            // (Other browsers don't take any message...)
            e.returnValue = message;
            return message;
        };

        window.onbeforeunload = helper.curry(message)
    },

    /*
    Turn off the 'are you sure you want to leave' dialog.
     */
    pageLeaveWarningDisable: function() {
        window.onbeforeunload = null;
    },

    /*
    Generates a random string of the specified length.
    Idea from: http://stackoverflow.com/a/1349426/859858
    */
    randomString: function(strLength) {
        var chars = [];
        var allowed_chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';

        for (var i = 0; i < strLength; i++)
            chars.append(allowed_chars.charAt(Math.floor(Math.random() * allowed_chars.length)));

        return chars;
    },

    /*
    Checks a string or number to see if it represents a number.
    Source: http://stackoverflow.com/a/1830844/859858
    */
    representsNumber: function(x) {
        return !isNaN(parseFloat(x)) && isFinite(x);
    },

    /*
    Checks a string or number to see if it represents an integer.
    Based on: http://stackoverflow.com/a/3886106/859858
    */
    representsInt: function(x) {
        return util.representsNumber(x) && parseFloat(x) % 1 === 0;
    },

    /*
    Returns true if the user's OS is Mac, false otherwise.

    If the appVersion contains the substring "Mac", then it's probably a mac...
    */
    osIsMac: function() {
        return (navigator.appVersion.indexOf("Mac") !== -1);
    },

    /*
    Converts an arguments object to an array.
    Source: http://javascriptweblog.wordpress.com/2010/04/05/curry-cooking-up-tastier-functions/
    */
    toArray: function(argumentsObj) {
        return Array.prototype.slice.call(argumentsObj);
    },

    /*
    Trim leading and trailing spaces from a string.

    From http://blog.stevenlevithan.com/archives/faster-trim-javascript
    */
    trimSpaces: function(str) {
        return str.replace(/^\s\s*/, '').replace(/\s\s*$/, '');
    }
};



/*
 * Extensions of standard types can go here.
 * Always make sure these don't conflict with third-party JS files'
 * extensions of standard types.
 *
 * Though, third-party JS plugins really shouldn't extend standard types.
 * (So if this becomes a JS plugin, rework this code!)
 */


/* Array indexOf(), in case the browser doesn't have it (hi, IE)
 * Source: https://developer.mozilla.org/en/JavaScript/Reference/Global_Objects/Array/IndexOf
 */
if (!Array.prototype.indexOf) {
    Array.prototype.indexOf = function (searchElement /*, fromIndex */ ) {
        "use strict";
        if (this === void 0 || this === null) {
            throw new TypeError();
        }
        var t = Object(this);
        var len = t.length >>> 0;
        if (len === 0) {
            return -1;
        }
        var n = 0;
        if (arguments.length > 0) {
            n = Number(arguments[1]);
            if (n !== n) { // shortcut for verifying if it's NaN
                n = 0;
            } else if (n !== 0 && n !== Infinity && n !== -Infinity) {
                n = (n > 0 || -1) * Math.floor(Math.abs(n));
            }
        }
        if (n >= len) {
            return -1;
        }
        var k = n >= 0 ? n : Math.max(len - Math.abs(n), 0);
        for (; k < len; k++) {
            if (k in t && t[k] === searchElement) {
                return k;
            }
        }
        return -1;
    }
}


/* Curry function.
 *
 * Example:
 * function converter(toUnit, factor, offset, input) {
 *     offset = offset || 0;
 *     return [((offset+input)*factor).toFixed(2), toUnit].join(" ");
 * }
 * var fahrenheitToCelsius = converter.curry('degrees C',0.5556, -32);
 * fahrenheitToCelsius(98); //"36.67 degrees C"
 *
 * Source: http://javascriptweblog.wordpress.com/2010/04/05/curry-cooking-up-tastier-functions/
 */
Function.prototype.curry = function() {
    if (arguments.length<1) {
        return this; //nothing to curry with - return function
    }
    var __method = this;
    var args = util.toArray(arguments);
    return function() {
        return __method.apply(this, args.concat(util.toArray(arguments)));
    }
};


/*
 * Check whether a string ends with the given suffix.
 * http://stackoverflow.com/questions/280634/endswith-in-javascript
 */

String.prototype.endsWith = function(suffix) {
    return this.indexOf(suffix, this.length - suffix.length) !== -1;
};

/*
 * Case-insensitive compare of strings.
 *
 * Source: http://stackoverflow.com/a/2140644
 * Generally doesn't work with non-English letters like an accented i.
 * http://www.i18nguy.com/unicode/turkish-i18n.html
 */
String.prototype.equalsIgnoreCase = function(other) {
    return (this.toUpperCase() === other.toUpperCase());
};

/* String format function, similar to Python's.
 * Example usage: "{0} is dead, but {1} is alive! {0} {2}".format("ASP", "ASP.NET")
 * Example output: ASP is dead, but ASP.NET is alive! ASP {2}
 * 
 * Source: http://stackoverflow.com/a/4673436
 */
String.prototype.format = function() {
  var args = arguments;
  return this.replace(/{(\d+)}/g, function(match, number) {
    return typeof args[number] != 'undefined'
      ? args[number]
      : match
    ;
  });
};

/*
 * Check whether a string starts with the given prefix.
 * http://stackoverflow.com/a/4579228
 */

String.prototype.startsWith = function(prefix) {
    return this.lastIndexOf(prefix, 0) === 0;
};



/*
 * jQuery extensions can go here.
 */

/* autoWidth
 *
 * Automatically make a group of elements the same width, by taking the maximum width of all
 * the elements and then setting the whole group to this width.
 *
 * Parameters:
 * limitWidth - Maximum allowed width.  If any element's width is greater than limitWidth,
 *              make the elements use width=limitWidth instead.
 *
 * Side effects:
 * On slow computers, the elements will appear without their width set for the first
 * 0.5 second or so, and then will shift position on the page once they have their
 * widths set.  It can be jarring to see this on nearly every page load.
 *
 * Original source (though it's been slightly modified):
 * http://stackoverflow.com/a/4641390 (http://stackoverflow.com/questions/4641346/css-to-align-label-and-input)
 * http://www.jankoatwarpspeed.com/post/2008/07/09/Justify-elements-using-jQuery-and-CSS.aspx#id_b16cb791-5bd7-4bb3-abc2-dc414fc1bd07
 * - (1 mistake: maxWidth >= settings.limitWidth should be $(this).width >= settings.limitWidth)
 */
jQuery.fn.autoWidth = function(options) {
  var settings = {
      limitWidth: false
  };

  if(options) {
      jQuery.extend(settings, options);
  }

  var maxWidth = 0;

  this.each(function(){
      var thisWidth = $(this).width();
      if (thisWidth > maxWidth){
          if(settings.limitWidth && thisWidth >= settings.limitWidth) {
            maxWidth = settings.limitWidth;
          } else {
            maxWidth = thisWidth;
          }
      }
  });

  this.width(maxWidth);
};

/* changeFontSize
 *
 * Change the font size of an element.
 *
 * Parameters:
 * changeFactor - a number specifying how much to multiply the font size by.
 *   For example, changeFactor = 0.9 will make the font 90% of its original size.
 */
jQuery.fn.changeFontSize = function(changeFactor) {
    this.each( function(){
        var oldFontSize = $(this).css('font-size');
        var oldFontSizeNumber = parseFloat(oldFontSize);
        var fontSizeUnits = oldFontSize.substring(oldFontSizeNumber.toString().length);

        var newFontSizeNumber = oldFontSizeNumber * changeFactor;
        var newFontSize = newFontSizeNumber.toString() + fontSizeUnits;
        $(this).css('font-size', newFontSize);
    });
};

/* disable
 *
 * Disable a jQuery element.
 *
 * See also:
 * enable
 */
jQuery.fn.disable = function() {
    $(this).prop('disabled', true);
};

/* enable
 *
 * Enable a jQuery element.
 *
 * See also:
 * disable
 */
jQuery.fn.enable = function() {
    $(this).prop('disabled', false);
};

/* hideAndDisable
 *
 * Hide and disable a jQuery element.
 *
 * See also:
 * showAndEnable
 */
jQuery.fn.hideAndDisable = function() {
    $(this).hide();
    $(this).prop('disabled', true);
};

/* showAndEnable
 *
 * Show and enable a jQuery element.
 *
 * See also:
 * hideAndDisable
 */
jQuery.fn.showAndEnable = function() {
    $(this).show();
    $(this).prop('disabled', false);
};

/* Selector - exactlycontains
 *
 * Variation of the jQuery selector 'contains':
 * 'exactlycontains' will match an element if its entire inner text is
 * exactly what is specified in the argument, as opposed to simply
 * finding the argument as a substring.
 * 
 * Source: http://api.jquery.com/contains-selector/ - see comment by Gibran
 */
$.expr[":"].exactlycontains = function(obj, index, meta, stack){
    return (obj.textContent || obj.innerText || $(obj).text() || "").toLowerCase() == meta[3].toLowerCase();
};

/* ajaxSend() configuration
 *
 * Whenever an Ajax request is sent, a X-CSRFToken header will be
 * automatically sent along with it for CSRF checking.
 *
 * Source: https://docs.djangoproject.com/en/1.3/ref/contrib/csrf/
 */
$(document).ajaxSend(function(event, xhr, settings) {
    function getCookie(name) {
        var cookieValue = null;
        if (document.cookie && document.cookie != '') {
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {
                var cookie = jQuery.trim(cookies[i]);
                // Does this cookie string begin with the name we want?
                if (cookie.substring(0, name.length + 1) == (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    function sameOrigin(url) {
        // url could be relative or scheme relative or absolute
        var host = document.location.host; // host + port
        var protocol = document.location.protocol;
        var sr_origin = '//' + host;
        var origin = protocol + sr_origin;
        // Allow absolute or scheme relative URLs to same origin
        return (url == origin || url.slice(0, origin.length + 1) == origin + '/') ||
            (url == sr_origin || url.slice(0, sr_origin.length + 1) == sr_origin + '/') ||
            // or any other URL that isn't scheme relative or absolute i.e relative.
            !(/^(\/\/|http:|https:).*/.test(url));
    }
    function safeMethod(method) {
        return (/^(GET|HEAD|OPTIONS|TRACE)$/.test(method));
    }

    if (!safeMethod(settings.type) && sameOrigin(settings.url)) {
        xhr.setRequestHeader("X-CSRFToken", getCookie('csrftoken'));
    }
});



/*
 * Below: Document-manipulating JS to run at every page load.
 */



/* Make all labels with class 'form_label' the same width,
 * and figure out this width dynamically (the longest width
 * needed by any field, with a max allowed width of 250px).
 *
 * See previously defined: jQuery.fn.autoWidth
 */
/*util.addLoadEvent( function() {
    $('label.column_form_text_field').autoWidth({limitWidth: 250});
});*/


/*
When you have a div with the class name "tutorial-message", this function
will turn that into a question-mark button which you click to display the
div contents in a pop-up.

Example: <div class="tutorial-message">This is my message</div>
*/
util.addLoadEvent( function() {
    var $tutorialMessages = $(".tutorial-message");
    $tutorialMessages.each ( function() {
        var $helpImage = $('<img style="display:inline;cursor:pointer" width="20" />');
        $helpImage.attr('src', window.utilQuestionMarkImage);
        // Insert the help image before the tutorial message element
        // (which should have display:none, so effectively, insert the
        // help image in place of the tutorial message).
        $(this).before($helpImage);
        openDialogFunction = function($element) {
            $element.dialog({
                height: 400,
                width: 600,
                modal: true
            });
        };
        // When the help image is clicked, display the tutorial message
        // contents in a dialog.
        $helpImage.bind("click", openDialogFunction.curry($(this)));
    });

});
