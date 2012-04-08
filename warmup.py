#!/usr/bin/python

"""warmup.py: Pre-caching Application Code via a Warmup Handler."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

from google.appengine.ext import webapp

class WarmupWorker(webapp.RequestHandler):
    """Warmup handler that precaches application code."""
    def get(self):
        import aircraft_types

        import api.v1
        import api.v1.api_handlers
        import api.v1.connections
        import api.v1.data_sources

        import config
        import cron
        import exceptions
        import main
        import models
        import notifications
        import reporting
        import utils
        import web_handlers