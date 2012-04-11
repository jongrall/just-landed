#!/usr/bin/python

"""main.py: Main WSGI app instantiation and configuration for Just Landed."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import os
import sys
import logging
import json
from zlib import adler32

# Add lib to the system path
LIB_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if LIB_DIR not in sys.path:
  sys.path[0:0] = [LIB_DIR]

from google.appengine.api import capabilities
from google.appengine.ext import webapp, ereporter
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.runtime.apiproxy_errors import (OverQuotaError,
    CapabilityDisabledError, FeatureNotEnabledError, DeadlineExceededError)

from lib.webapp2_extras.routes import PathPrefixRoute, HandlerPrefixRoute

from custom_exceptions import *
from config import config, on_local, on_staging, google_analytics_account
import utils

if not on_local(): # On local, ereporter causes unwanted stacktraces
    ereporter.register_logger()
Route = webapp.Route

# Define a default template context which uses the app software version number
# to ensure that static content isn't cached to the detriment of freshness. The
# version number provided by this context is supposed to be appended to all
# resource URLs for resources hosted by getjustlanded.com in order to ensure it
# is up-to-date.
APP_VERSION = os.environ.get('CURRENT_VERSION_ID', '')
SERVER_SOFTWARE = os.environ.get('SERVER_SOFTWARE', '')
VERSION_CHKSM = adler32(APP_VERSION + SERVER_SOFTWARE)
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
        of problem encountered."""

        gae_outage = False

        # These exceptions are not serious and should be logged as warnings
        if isinstance(exception, (InvalidFlightNumberException,
                                  FlightNotFoundException,
                                  OldFlightException)):
            logging.warning(exception.message)

        else:
            # Detect and report service outages if possible
            if capabilities.CapabilitySet('urlfetch').is_enabled():

                # Some exceptions should trigger SMS notifications to the admin
                if isinstance(exception, (FlightAwareUnavailableError,
                                          DrivingTimeUnavailableError,
                                          OverQuotaError,
                                          CapabilityDisabledError,
                                          FeatureNotEnabledError,
                                          DeadlineExceededError,
                                          PushNotificationsUnavailableError,
                                          PushNotificationsUnauthorizedError,
                                          PushNotificationsUnknownError,
                                          CampaignMonitorUnauthorizedError,
                                          CampaignMonitorUnavailableError)):
                    utils.sms_report_exception(exception)

                system_status = {
                    'DATASTORE READS' : capabilities.CapabilitySet('datastore_v3').is_enabled(),
                    'DATASTORE WRITES' : capabilities.CapabilitySet('datastore_v3', capabilities=['write']).is_enabled(),
                    'MAIL SERVICE' : capabilities.CapabilitySet('mail').is_enabled(),
                    'MEMCACHE SERVICE' : capabilities.CapabilitySet('memcache').is_enabled(),
                    'TASKQUEUE SERVICE' : capabilities.CapabilitySet('taskqueue').is_enabled(),
                }

                disabled_services = [k for k in system_status.keys() if not system_status[k]]
                if disabled_services:
                    utils.report_outage(disabled_services)
                    gae_outage = True
            else:
                gae_outage = True

            # Logged exceptions get automatically picked up by ereporter
            logging.exception(exception)

        if gae_outage or isinstance(exception, (OverQuotaError, CapabilityDisabledError,
                                        FeatureNotEnabledError, DeadlineExceededError)):
            self.response.set_status(503) # Service unavailable
        elif hasattr(exception, 'code'):
            self.response.set_status(exception.code)
        else:
            self.response.set_status(500)


class StaticHandler(BaseHandler):
    """Generic handler for static pages on the website driven by templates."""
    def get(self, page_name="", context={}):
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
            self.response.write(template.render(template_path, context))
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
        if debug or self.request.GET.get('debug'):
            # Pretty print JSON to be read as HTML
            self.response.content_type = 'text/html'
            formatted_resp = json.dumps(response_data, sort_keys=True, indent=4)
            self.response.write(utils.text_to_html(formatted_resp))
        else:
            # Set response content type to JSON
            self.response.content_type = 'application/json'
            self.response.write(json.dumps(response_data))


class AuthenticatedAPIHandler(BaseAPIHandler):
    """An API handler that also authenticates incoming API requests."""
    def dispatch(self):
        is_server = self.request.headers.get('User-Agent').startswith('AppEngine')
        self.client = (is_server and 'Server') or 'iOS'
        if on_local() or on_staging() or utils.authenticate_api_request(self.request, client=self.client):
            # Parent class will call the method to be dispatched
            # -- get() or post() or etc.
            super(AuthenticatedAPIHandler, self).dispatch()
        else:
            self.abort(403)

###############################################################################
"""Routes & WSGI App Instantiation"""
###############################################################################

# Configuration of supported routes
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
        Route('/warmup', handler='warmup.WarmupWorker'),
    ]),
    Route('/', handler=StaticHandler),
    HandlerPrefixRoute('web_handlers.', [
        Route('/mailing-list/subscribe', handler="CampaignMonitorHandler"),
        Route('/mu-ddc4496d-5d1fac34-63470606-c5358264', handler='BlitzHandler'),
    ]),
    Route('/<page_name:[^/]+>', handler=StaticHandler),
]

# Instantiate the app.
app = webapp.WSGIApplication(routes, debug=on_local())

# Register custom 404 handler.
def handle_404(request, response, exception):
    path = os.path.join(template_dir, '404.html')
    response.write(template.render(path, template_context))
    response.set_status(404)

app.error_handlers[404] = handle_404

def main():
    run_wsgi_app(app)

if __name__ == "__main__":
    main()