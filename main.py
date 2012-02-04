import os
import sys
import logging
from zlib import adler32

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

from tracker import TrackHandler

template_dir = os.path.join(os.path.dirname(__file__), 'templates')

APP_VERSION = os.environ.get('CURRENT_VERSION_ID', '')
SERVER_SOFTWARE = os.environ.get('SERVER_SOFTWARE', '')
VERSION_CHKSM = adler32(APP_VERSION + SERVER_SOFTWARE)
template_context = {
    'version' : VERSION_CHKSM,
}


class BaseHandler(webapp.RequestHandler):

    def handle_exception(self, exception, debug):
        if isinstance(exception, TemplateDoesNotExist):
            self.error(404)
        else:
            self.error(500)


    def error(self, code):
        super(BaseHandler, self).error(code)
        if code == 404:
            path = os.path.join(template_dir, '404.html')
            self.response.out.write(template.render(path, template_context))
            return
        elif code == 500:
            path = os.path.join(template_dir, '500.html')
            self.response.out.write(template.render(path, template_context))
            return


class StaticHandler(BaseHandler):
    def get(self, page_name):
        template_name = page_name

        if not page_name or page_name.count('index'):
            template_name = 'index.html'
            template_path = os.path.join(template_dir, template_name)
        else:
            if not template_name.endswith('.html'):
                template_name = template_name + '.html'

            template_path = os.path.join(template_dir, template_name)

        template_context['current_page'] = template_name
        self.response.out.write(template.render(template_path, template_context))


application = webapp.WSGIApplication([('/track/(.+)', TrackHandler),
                                    ('/(.*)', StaticHandler)],
                                     debug=False)

def main():
    application.run()

if __name__ == "__main__":
    main()