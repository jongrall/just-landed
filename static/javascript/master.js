/* Site Global Variables
------------------------------------------------------------ */

var emailRegExp = new RegExp("(?:[a-z0-9!#$%\\&'*+/=?\\^_`{|}~-]+(?:\\.[a-z0-9!#$%\\&'*+/=?\\^_`{|}~-]+)*|\"(?:[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x21\\x23-\\x5b\\x5d-\\x7f]|\\\\[\\x01-\\x09\\x0b\\x0c\\x0e-\\x7f])*\")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x21-\\x5a\\x53-\\x7f]|\\\\[\\x01-\\x09\\x0b\\x0c\\x0e-\\x7f])+)\\])");


/* Toggle the grid overlay when the "g" key is pressed
------------------------------------------------------------ */

$(document).keypress(function(e) {
    if (e.charCode == 103) {
        $('#grid').toggle();
    }
});


/* Inline Field Labels (loaded last so markup is there to get the handlers right)
----------------------------------------------------------------------------------- */

// Fade out the focused field's label
function labelFadeIn() {
    // Get the ID of the focused element
    var fieldId = $(this).attr('id');

    // fade the field's corresponding <label>
    if ($(this).val().length == 0) {
        $('label[for="' + fieldId + '"]').fadeTo(100, 0.6);
    }
}

// Fade in the now blurred field's label
function labelFadeOut() {
    // Get the ID of the focused element
    var fieldId = $(this).attr('id');

    // fade the field's corresponding <label>
    if ($(this).val().length == 0) {
        $('label[for="' + fieldId + '"]').fadeTo(100, 1);
    }
}

// Determine if the label should be visible
function labelHide() {
    // Get the ID of the focused element
    var fieldId = $(this).attr('id');

    // If there's text in the field, hide the label, show label if not
    if ($(this).val().length > 0) {
        $('label[for="' + fieldId + '"]').hide();
    } else {
        $('label[for="' + fieldId + '"]').show();
    }
}

// Check for inputs with no values, and show its label if they're empty
function checkInputValues() {
    // Get all the inputs on the page
    var pageInputs = $('textarea, input[type="text"], input[type="password"]');
    var currentFieldId;

    // Loop over all the inputs
    for (i = 0; i < pageInputs.length; i++) {
        // We want fields that don't have values
        if ($(pageInputs[i]).val().length == 0) {
            // Get the ID of that field
            currentFieldId = $(pageInputs[i]).attr('id');

            // Show the associating label for that field
            $('label[for="' + currentFieldId + '"]').show();
        }
    }
}

// Form Field Handling
$(document).ready(function() { checkInputValues(); });
$('textarea, input[type="text"], input[type="password"]').focus(labelFadeIn);
$('textarea, input[type="text"], input[type="password"]').blur(labelFadeOut);
$('textarea, input[type="text"], input[type="password"]').bind('input', labelHide); // Modern browsers
$('textarea, input[type="text"], input[type="password"]').keyup(labelHide); // For IE