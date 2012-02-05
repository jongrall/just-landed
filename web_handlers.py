import os
import logging
from zlib import adler32

from google.appengine.ext.webapp import template

from lib import webapp2 as webapp

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
    response.set_status(500)

def handle_404(request, response, exception):
    handle_exception(request, response, exception, 404)

def handle_500(request, response, exception):
    handle_exception(request, response, exception, 500)


class BaseHandler(webapp.RequestHandler):
    def handle_exception(self, exception, debug):
        if isinstance(exception, webapp.HTTPException):
            handle_exception(self.request, self.response, exception, exception.code)
        else:
            logging.exception(exception)
            self.response.set_status(500)


class StaticHandler(BaseHandler):
    def get(self, page_name=""):
        template_name = page_name

        if not page_name or page_name.count('index'):
            template_name = 'index.html'
            template_path = os.path.join(template_dir, template_name)
        else:
            if not template_name.endswith('.html'):
                template_name = template_name + '.html'

            template_path = os.path.join(template_dir, template_name)

        template_context = {'current_page' : template_name}
        self.response.write(template.render(template_path, template_context))