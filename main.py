import logging

from lib import webapp2 as webapp
from lib.webapp2_extras.routes import PathPrefixRoute, HandlerPrefixRoute

################################################################################
# WSGI APP CONFIGURATION
################################################################################

def handle_500(request, response, exception):
    logging.exception(exception)
    response.set_status(500)

routes = [
    PathPrefixRoute('/api/v1', [
        HandlerPrefixRoute('api_handlers.',[
        webapp.Route('/track/<flight_id:[^/]+>', 'TrackHandler'),
        webapp.Route('/search/<flight_number:[^/]+>', 'SearchHandler'),
        webapp.Route('/handle_alert', 'AlertHandler'),
        webapp.Route('/untrack/<flight_id:[^/]+>', 'UntrackHandler'),
        ]),
    ]),
    webapp.Route('/', 'web_handlers.StaticHandler'),
]

app = webapp.WSGIApplication(routes, debug=True)
app.error_handlers[404] = 'web_handlers.handle_404'
app.error_handlers[500] = handle_500

def main():
    app.run()

if __name__ == "__main__":
    main()