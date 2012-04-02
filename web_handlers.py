#!/usr/bin/python

"""web_handlers.py: Module that defines handlers for (static) web content on the
getjustlanded.com website.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import os
import logging
from zlib import adler32

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

from config import config
template_dir = config['template_dir']

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
}

def handle_exception(request, response, exception, code=500):
    """Custom exception handler for static web pages."""
    if code != 404:
        logging.exception(exception)
    path = os.path.join(template_dir, '%d.html' % code)
    response.write(template.render(path, template_context))
    response.set_status(code)

def handle_404(request, response, exception):
    handle_exception(request, response, exception, code=404)

class BaseHandler(webapp.RequestHandler):
    """Base handler that handles exceptions for the website."""
    def handle_exception(self, exception, debug):
        if isinstance(exception, webapp.HTTPException):
            handle_exception(self.request, self.response, exception, exception.code)
        else:
            logging.exception(exception)
            self.response.set_status(500)

class StaticHandler(BaseHandler):
    """Generic handler for static pages on the website."""
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
        self.response.write(template.render(template_path, context))

class iPhoneFAQHandler(StaticHandler):
    """Generic handler for static pages on the website."""
    def get(self):
        super(iPhoneFAQHandler, self).get(page_name='iphonefaq.html')

class BlitzHandler(StaticHandler):
    """Verification handler to enable Blitz.io performance testing."""
    def get(self):
        self.response.write('42')