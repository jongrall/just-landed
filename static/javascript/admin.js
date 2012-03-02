// Faux-JavaScript Classes by John Resig at ejohn.org
(function(){var initializing=false,fnTest=/xyz/.test(function(){xyz;})?/\b_super\b/:/.*/;this.Class=function(){};Class.extend=function(prop){var _super=this.prototype;initializing=true;var prototype=new this();initializing=false;for(var name in prop){prototype[name]=typeof prop[name]=="function"&&typeof _super[name]=="function"&&fnTest.test(prop[name])?(function(name,fn){return function(){var tmp=this._super;this._super=_super[name];var ret=fn.apply(this,arguments);this._super=tmp;return ret;};})(name,prop[name]):prop[name];}
function Class(){if(!initializing&&this.init)
this.init.apply(this,arguments);}
Class.prototype=prototype;Class.prototype.constructor=Class;Class.extend=arguments.callee;return Class;};})();

// Relative Time Function by jherdman at github.com/jherdman/javascript-relative-time-helpers
Date.prototype.toRelativeTime=function(now_threshold){var delta=new Date()-this;now_threshold=parseInt(now_threshold,10);if(isNaN(now_threshold)){now_threshold=0;}
if(delta<=now_threshold){return'Just now';}
var units=null;var conversions={ms:1,sec:1000,min:60,hr:60,day:24,month:30,year:12};for(var key in conversions){if(delta<conversions[key]){break;}else{units=key;delta=delta/conversions[key];}}
delta=Math.floor(delta);if(delta!==1){units+="s";}
return[delta,units,"ago"].join(" ");};Date.fromString=function(str){return new Date(Date.parse(str));};

// DST Time checker
function isDST(date) {
    var d = new Date(date);
    var dY=d.getFullYear();
    var d1=new Date(dY,0,1,0,0,0,0);
    var d2=new Date(dY,6,1,0,0,0,0);
    var d1a=new Date((d1.toUTCString()).replace(" GMT",""));
    var d2a=new Date((d2.toUTCString()).replace(" GMT",""));
    var o1=(d1-d1a)/3600000;
    var o2=(d2-d2a)/3600000;
    var rV=false;
    if (o1!=o2) {
        d.setHours(0);d.setMinutes(0);d.setSeconds(0);d.setMilliseconds(0);
        var da=new Date((d.toUTCString()).replace(" GMT",""));
        o3=(d-da)/3600000;
        rV=(o3==o1)?false:true;
    }
    return rV;
}

/***********************************************************************************
AJAX and other things for admin
***********************************************************************************/

// AJAX error report
function printError(jqXHR, textStatus, errorThrown) {
    // Convert error to JSON
    var response = JSON.parse(jqXHR.responseText);

    // Display error in log
    alert(response.error);
}

// Connect to admin
function callRemoteMethodWithCallbacks(context, baseURL, methodName, request, preflight, success, error) {
    var ajaxSettings = {
        context: context,
        contentType: "application/json",
        data: JSON.stringify(request),
        type: "POST",
        beforeSend: preflight,
        success: success,
        error: error
    };

    $.ajax(baseURL + '/' + methodName, ajaxSettings);
}

// Call remote method shortcut
function callRemoteAdminMethod(context, methodName, request, success) {
    return callRemoteMethodWithCallbacks(context, "/admin/flightaware", methodName, request, null, success, printError);
}

/***********************************************************************************
Globals
***********************************************************************************/

var admin;
var isSecure = (window.location.protocol == 'https:') ? true : false;


/***********************************************************************************
Admin Class
***********************************************************************************/

var Admin = Class.extend({
    init: function() {
        $('#set-endpoint').click({context: this}, this.setEndpoint);
        $('#clear-alerts').click({context: this}, this.clearAlerts);
    },

    setEndpoint: function(e) {
        var context = e.data.context;
        callRemoteAdminMethod(context, 'register_endpoint', {}, context.printEndpointResult);
    },

    printEndpointResult: function(data, textStatus, jqXHR) {
        var url = data.endpoint_url;
        $('#endpoint-success').html('Set endpoint: ' + url);

        /* Remove the success message after a few seconds. */
        window.setTimeout(function () {
           $('#endpoint-success').html('');
        }, 5000);
    },

    clearAlerts: function(e) {
        var context = e.data.context;
        callRemoteAdminMethod(context, 'clear_alerts', {}, context.clearAlertInProgress);
    },

    clearAlertInProgress: function(data, textStatus, jqXHR) {
      $('#clear-result').html('Clearing ' + data.clearing_alert_count + ' alerts.');

      /* Remove the clearing message after a few seconds. */
      window.setTimeout(function () {
         $('#clear-result').html('');
      }, 5000);
    },
});


/***********************************************************************************
Page Load Handler
***********************************************************************************/

$(document).ready(function(){
    // Get initial listings for sidebar
    admin = new Admin();
});