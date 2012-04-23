#!/usr/bin/python

"""warmup.py: Pre-caching Application Code via a Warmup Handler."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import os
import sys

# Add lib to the system path
LIB_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if LIB_DIR not in sys.path:
  sys.path[0:0] = [LIB_DIR]

from google.appengine.ext import webapp

class WarmupWorker(webapp.RequestHandler):
    """Warmup handler that precaches application code."""
    def get(self):
        import aircraft_types
        import api.v1
        import config
        import cron
        import custom_exceptions
        import main
        import models
        import notifications
        import reporting
        import utils
        import web_handlers