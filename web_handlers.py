import os

from google.appengine.ext.webapp import template

from lib import webapp2 as webapp

from config import config
template_dir = config['template_dir']


class StaticHandler(webapp.RequestHandler):
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