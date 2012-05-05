#!/usr/bin/env python

"""appengine_config.py: Additional App-Engine specific config."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

from config import on_development
appstats_enabled = False

def webapp_add_wsgi_middleware(app):
    # Optimization: only add appstats middleware in the development environment
    if not appstats_enabled or not on_development():
        return app

    from google.appengine.ext.appstats import recording
    app = recording.appstats_wsgi_middleware(app)
    return app

def appstats_should_record(env):
    # Don't record admin stuff
    if env.get('PATH_INFO').startswith('/_ah/admin'):
        return False
    return True