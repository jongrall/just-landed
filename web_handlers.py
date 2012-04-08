#!/usr/bin/python

"""web_handlers.py: Module that defines handlers for (static) web content on the
getjustlanded.com website.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging

from main import StaticHandler


class iPhoneFAQHandler(StaticHandler):
    """Generic handler for static pages on the website."""
    def get(self):
        super(iPhoneFAQHandler, self).get(page_name='iphonefaq.html')


class BlitzHandler(StaticHandler):
    """Verification handler to enable Blitz.io performance testing."""
    def get(self):
        self.response.write('42')