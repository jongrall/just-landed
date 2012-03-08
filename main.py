#!/usr/bin/python

"""main.py: Main WSGI app instantiation and configuration for Just Landed."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging

# Avoid using the webapp2 version hosted by Google - it changes often.
from lib import webapp2 as webapp
from lib.webapp2_extras.routes import PathPrefixRoute, HandlerPrefixRoute

def handle_500(request, response, exception):
    """Custom 500 error handler that overrides the WSGI app default."""
    logging.exception(exception)
    response.set_status(500)

# Configuration of supported routes
routes = [
    PathPrefixRoute('/api/v1', [
        HandlerPrefixRoute('api.v1.api_handlers.',[
        webapp.Route('/track/<flight_number>/<flight_id:[^/]+>', 'TrackHandler'),
        webapp.Route('/search/<flight_number:[^/]+>', 'SearchHandler'),
        webapp.Route('/handle_alert', 'AlertHandler'),
        webapp.Route('/untrack/<flight_id:[^/]+>', 'UntrackHandler'),
        ]),
    ]),
    PathPrefixRoute('/admin/flightaware', [
        HandlerPrefixRoute('admin.admin_handlers.',[
        webapp.Route('/', 'FlightAwareAdminHandler'),
        webapp.Route('/register_endpoint', 'FlightAwareAdminAPIHandler',
                    handler_method='register_endpoint'),
        webapp.Route('/clear_alerts', 'FlightAwareAdminAPIHandler',
                    handler_method='clear_alerts'),
        ]),
    ]),
    PathPrefixRoute('/_ah', [
        webapp.Route('/queue/mobile-push', handler='notifications.PushWorker'),
    ]),
    webapp.Route('/', 'web_handlers.StaticHandler'),
]

# Instantiate the app. IMPORTANT: set debug to False in production.
app = webapp.WSGIApplication(routes, debug=True)

# Register custom error handlers.
app.error_handlers[404] = 'web_handlers.handle_404'
app.error_handlers[500] = handle_500

def main():
    app.run()

if __name__ == "__main__":
    main()