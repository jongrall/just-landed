#!/usr/bin/env python

"""web_handlers.py: Module that defines handlers for (static) web content on the
getjustlanded.com website.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import logging
import urllib
import json

from main import StaticHandler, BaseHandler, BaseAPIHandler
import utils

class BlitzHandler(StaticHandler):
    """Verification handler to enable Blitz.io performance testing."""
    def get(self):
        self.response.write('42')