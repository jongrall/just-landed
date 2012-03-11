#!/usr/bin/python

"""main.py: Main WSGI app instantiation and configuration for Just Landed."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
from config import on_local

# Avoid using the webapp2 version hosted by Google - it changes often.
from google.appengine.ext import webapp
from lib.webapp2_extras.routes import PathPrefixRoute, HandlerPrefixRoute

Route = webapp.Route

def handle_500(request, response, exception):
    """Custom 500 error handler that overrides the WSGI app default."""
    logging.exception(exception)
    response.set_status(500)

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
        ]),
    ]),
    PathPrefixRoute('/_ah', [
        Route('/queue/mobile-push', handler='notifications.PushWorker'),
    ]),
    Route('/', 'web_handlers.StaticHandler'),
]

# Instantiate the app.
app = webapp.WSGIApplication(routes, debug=on_local())

# Register custom error handlers.
app.error_handlers[404] = 'web_handlers.handle_404'
app.error_handlers[500] = handle_500

def main():
    app.run()

if __name__ == "__main__":
    main()