#!/usr/bin/env python

"""main.py: Main WSGI app instantiation and configuration for Just Landed."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import logging
import os
import sys
import json
from zlib import adler32

# Add lib to the system path
LIB_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if LIB_DIR not in sys.path:
  sys.path[0:0] = [LIB_DIR]

from google.appengine.ext import webapp, ndb
from google.appengine.api import memcache
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.runtime.apiproxy_errors import (OverQuotaError,
    CapabilityDisabledError, FeatureNotEnabledError, DeadlineExceededError)

# Optimization: path prefix speeds up request routing
from lib.webapp2_extras.routes import PathPrefixRoute, HandlerPrefixRoute

from custom_exceptions import *
from config import config, on_development, on_staging, google_analytics_account
from simulate_read_only import * # FIXME
import utils

Route = webapp.Route

# Optimization: allow browsers to cache content indefinitely, use version string
# to ensure immediate updates when content changes.
# Define a default template context which uses the app software version number
# to ensure that static content isn't cached to the detriment of freshness. The
# version number provided by this context is supposed to be appended to all
# resource URLs for resources hosted by getjustlanded.com in order to ensure it
# is up-to-date.
APP_VERSION = os.environ.get('CURRENT_VERSION_ID', '')
SERVER_SOFTWARE = os.environ.get('SERVER_SOFTWARE', '')
VERSION_CHKSM = abs(adler32(APP_VERSION + SERVER_SOFTWARE))
template_context = {
    'version' : VERSION_CHKSM,
    'ga_account' : google_analytics_account(),
}

template_dir = config['template_dir']

###############################################################################
"""Custom Request Handlers"""
###############################################################################

class BaseHandler(webapp.RequestHandler):
    """Base handler that includes custom exception reporting & handling."""
    def handle_exception(self, exception, debug):
        """Override standard webapp exception handling and do our own logging.
        Clients get a generic error and status code corresponding to the type
        of problem encountered.

        """
        gae_outage = False

        informational_errors = (InvalidFlightNumberException,
                                FlightNotFoundException,
                                OldFlightException)

        outage_errors = (FlightDataUnavailableError,
                         DrivingTimeUnavailableError,
                         PushNotificationsUnavailableError,
                         ReportingServiceUnavailableError)

        urgent_errors = (OverQuotaError,
                         CapabilityDisabledError,
                         FeatureNotEnabledError,
                         DeadlineExceededError,
                         PushNotificationsUnauthorizedError,
                         PushNotificationsUnknownError,
                         MalformedDrivingDataException,
                         DrivingAPIQuotaException,
                         DrivingTimeUnauthorizedException,
                         AirportNotFoundException,
                         UnableToSetAlertException,
                         FlightDurationUnknown,
                         InvalidAlertCallbackException,
                         EventClassNotFoundException,
                         UnableToCreateUniqueEventKey)

        unrecoverable_errors = (OverQuotaError,
                                CapabilityDisabledError,
                                FeatureNotEnabledError)

        # Some exceptions are not serious and should be logged as info
        if isinstance(exception, informational_errors):
            logging.info(exception.message)
        else:
            # Reliability: some exceptions should trigger immediate SMS notifications
            if isinstance(exception, urgent_errors):
                utils.sms_report_exception(exception)

            # Outage-type errors are delayed to verify outage
            if isinstance(exception, outage_errors):
                utils.report_service_error(exception)

            # Reliability: detect and report GAE service outages if possible
            disabled_services = utils.disabled_services()
            gae_outage = len(disabled_services) > 0
            if gae_outage:
                utils.try_reporting_outage(disabled_services)

            # Log exceptions
            logging.exception(exception)

        # Use response status to indicate to clients what happened
        if gae_outage or isinstance(exception, unrecoverable_errors):
            self.response.set_status(503)
        elif hasattr(exception, 'code'):
            self.response.set_status(exception.code)
        else:
            self.response.set_status(500)


class StaticHandler(BaseHandler):
    """Generic handler for static pages on the website driven by templates."""
    def static_response(self, content):
        self.response.write(content)
        self.response.headers['Cache-Control'] = 'public, max-age=7200' # 2hr cache
        self.response.headers['Pragma'] = 'Public'

    def get(self, page_name="", context={}, use_cache=True):
        # Optimization: use memcache to cache static page content
        if use_cache:
            page_cache_key = '%s_%s' % (page_name, VERSION_CHKSM)
            cached_page = memcache.get(page_cache_key)
            if cached_page:
                self.static_response(cached_page)
                return

        template_name = page_name
        if not page_name or page_name.count('index'):
            template_name = 'index.html'
            template_path = os.path.join(template_dir, template_name)
        else:
            if not template_name.endswith('.html'):
                template_name = template_name + '.html'

            template_path = os.path.join(template_dir, template_name)

        context.update({'current_page' : template_name})

        # Add in the version context
        context.update(template_context)
        try:
            rendered_content = template.render(template_path, context)
            if use_cache:
                memcache.set(page_cache_key, rendered_content)
                self.static_response(rendered_content)
            else:
                self.response.write(rendered_content)
        except Exception as e:
            handle_404(self.request, self.response, e)


class BaseAPIHandler(BaseHandler):
    """Base API handler that provides custom JSON responses."""
    def handle_exception(self, exception, debug):
        super(BaseAPIHandler, self).handle_exception(exception, debug)
        self.respond({'error' : exception.message or 'An error occurred.'})

    def respond(self, response_data, debug=False):
        """Takes a dictionary or list as input and responds to the client using
        JSON.

        If 'debug' is set to true, the output is nicely formatted and indented
        for reading in the browser.
        """
        self.response.headers['Cache-Control'] = 'no-cache' # Caching not allowed

        if debug or self.request.GET.get('debug'):
            # Pretty print JSON to be read as HTML
            self.response.content_type = 'text/html'
            formatted_resp = json.dumps(response_data, sort_keys=True, indent=4)
            self.response.write(utils.text_to_html(formatted_resp))
        else:
            # Set response content type to JSON
            self.response.content_type = 'application/json'
            self.response.write(json.dumps(response_data))

    def dispatch(self): # FIXME
        if not utils.datastore_writes_enabled():
            self.response.set_status(503)
            self.respond({'error' : 'Just Landed is currently unavailable.'})
        else:
            super(BaseAPIHandler, self).dispatch()


class AuthenticatedAPIHandler(BaseAPIHandler):
    """An API handler that authenticates all incoming API requests before
    dispatching them to the handler.

    """
    def dispatch(self):
        is_server = self.request.headers.get('User-Agent').startswith('AppEngine')
        self.client = (is_server and 'Server') or 'iOS'

        # For convenience, don't authenticate in development environment
        if on_development() or utils.authenticate_api_request(self.request, client=self.client):
            super(AuthenticatedAPIHandler, self).dispatch()
        else:
            self.abort(403)

###############################################################################
"""Routes & WSGI App Instantiation"""
###############################################################################

routes = [
    PathPrefixRoute('/api/v1', [
        HandlerPrefixRoute('api.v1.api_handlers.', [
        Route('/track/<flight_number>/<flight_id:[^/]+>', 'TrackHandler', name='track'),
        Route('/search/<flight_number:[^/]+>', 'SearchHandler', name='search'),
        Route('/handle_alert', 'AlertHandler'),
        Route('/untrack/<flight_id:[^/]+>', 'UntrackHandler', name='untrack'),
        ]),
    ]),
    PathPrefixRoute('/admin/flightaware', [
        HandlerPrefixRoute('admin.admin_handlers.', [
        Route('/', 'FlightAwareAdminHandler'),
        Route('/register_endpoint', 'FlightAwareAdminAPIHandler',
                handler_method='register_endpoint'),
        Route('/clear_alerts', 'FlightAwareAdminAPIHandler',
                handler_method='clear_alerts'),
        ]),
    ]),
    PathPrefixRoute('/cron',[
        HandlerPrefixRoute('cron.', [
        Route('/untrack_old_flights', 'UntrackOldFlightsWorker'),
        Route('/send_reminders', 'SendRemindersWorker'),
        Route('/clear_orphaned_alerts', 'ClearOrphanedAlertsWorker'),
        Route('/detect_finished_outages', 'OutageCheckerWorker'),
        ]),
    ]),
    PathPrefixRoute('/_ah', [
        Route('/queue/track', handler='api.v1.api_handlers.TrackWorker'),
        Route('/queue/delayed-track', handler='api.v1.api_handlers.DelayedTrackWorker'),
        Route('/queue/untrack', handler='api.v1.api_handlers.UntrackWorker'),
        Route('/queue/process-alert', handler='api.v1.api_handlers.AlertWorker'),
        Route('/queue/mobile-push', handler='notifications.PushWorker'),
        Route('/queue/clear-alerts', handler='admin.admin_handlers.ClearAlertsWorker'),
        Route('/queue/report-event', handler='reporting.ReportWorker'),
        Route('/queue/log-event', handler='reporting.DatastoreLogWorker'),
        Route('/warmup', handler='warmup.WarmupWorker'),
    ]),
    Route('/', handler=StaticHandler),
    HandlerPrefixRoute('web_handlers.', [
        Route('/mu-ddc4496d-5d1fac34-63470606-c5358264', handler='BlitzHandler'),
    ]),
    Route('/<page_name:[^/]+>', handler=StaticHandler),
]

# Instantiate the app.
app = webapp.WSGIApplication(routes, debug=on_development())

def handle_404(request, response, exception):
    """Custom 404 handler."""
    path = os.path.join(template_dir, '404.html')
    response.write(template.render(path, template_context))
    response.set_status(404)

# Register custom 404 handler.
app.error_handlers[404] = handle_404

def main():
    run_wsgi_app(app)

if __name__ == '__main__':
    main()