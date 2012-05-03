#!/usr/bin/python

"""connections.py: This module defines helper functions for making asynchronous
urlfetch requests using the ndb.urlfetch() function.
"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

import json
import urllib

from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets

def build_url(base, path, args={}):
    """Builds a properly encoded URL from base, path and query arguments."""
    url = base + path
    if args:
        encoded_args = urllib.urlencode(args)
        url = url + '?' + encoded_args
    return url


class Connection(object):
    """Connection class to help with making HTTP requests."""
    def __init__(self, base_url, username=None, password=None):
        self._base_url = base_url
        self._auth = None
        self._ssl = False
        if username:
            assert password
            self._username = username
            self._password = password
            self._auth = ('%s:%s' % (username, password)).encode('base64')[:-1]
        if base_url.startswith('https'):
            self._ssl = True

    @ndb.tasklet
    def request(self, url, payload=None, method='GET', headers={}, deadline=20):
        """Helper for making asynchornous HTTP requests."""
        if self._auth:
            headers.update({
                'Authorization': 'Basic %s' % self._auth,
            })
        ctx = ndb.get_context()
        result = yield ctx.urlfetch(url, payload=payload, method=method,
                                    headers=headers, deadline=deadline,
                                    validate_certificate=self._ssl)
        raise ndb.Return(result)

    @ndb.tasklet
    def get_json(self, path, args, payload=None, headers={}, deadline=20):
        """Convenience function for issuing a JSON GET request."""
        url = build_url(self._base_url, path, args)
        result = yield self.request(url, payload=payload, method='GET', headers=headers,
                        deadline=deadline)
        parsed_json = json.loads(result.content)
        raise tasklets.Return(parsed_json)