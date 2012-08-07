#!/usr/bin/env python

"""warmup.py: Pre-caching Application Code via a Warmup Handler."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import os
import sys

from google.appengine.ext import webapp

# Add lib to the system path
LIB_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if LIB_DIR not in sys.path:
  sys.path[0:0] = [LIB_DIR]

class WarmupWorker(webapp.RequestHandler):
    """Optimization: Warmup handler that pre-caches application code."""
    def get(self):
        import aircraft_types
        import api.v1
        import config
        import cron
        import custom_exceptions
        import main
        import models.v1
        import notifications
        import reporting
        import utils
        import web_handlers