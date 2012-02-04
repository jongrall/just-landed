import os
import sys
import logging
from zlib import adler32

from google.appengine.ext.webapp import template

from lib import webapp2 as webapp
from lib.webapp2_extras.routes import PathPrefixRoute, HandlerPrefixRoute

from config import config
template_dir = config['template_dir']

APP_VERSION = os.environ.get('CURRENT_VERSION_ID', '')
SERVER_SOFTWARE = os.environ.get('SERVER_SOFTWARE', '')
VERSION_CHKSM = adler32(APP_VERSION + SERVER_SOFTWARE)
template_context = {
    'version' : VERSION_CHKSM,
}

def handle_exception(request, response, exception, code=500):
    logging.exception(exception)
    path = os.path.join(template_dir, '%d.html' % code)
    response.write(template.render(path, template_context))
    response.set_status(code)

def handle_404(request, response, exception):
    handle_exception(request, response, exception, code=404)


def handle_500(request, response, exception):
    handle_exception(request, response, exception, code=500)

################################################################################
# WSGI APP CONFIGURATION
################################################################################

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
app = webapp.WSGIApplication(routes, debug=False)
app.error_handlers[404] = handle_404
app.error_handlers[500] = handle_500

def main():
    app.run()

if __name__ == "__main__":
    main()