#!/usr/bin/env python

"""connections.py: Utilities for fetching URLs using urllib2 and urllib."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

import json
import urllib2
from urllib import urlencode

def build_url(base, path, args={}):
    """Builds a properly encoded URL from base, path and query arguments."""
    url = base + path
    if args:
        encoded_args = urlencode(args)
        url = url + '?' + encoded_args
    return url

class Connection(object):
    """Connection class to help with making HTTP requests."""
    def __init__(self, base_url, username=None, password=None):
        self._base_url = base_url
        self._auth = None
        if username:
            assert password
            self._username = username
            self._password = password
            self._auth = ('%s:%s' % (username, password)).encode('base64')[:-1]

    def request(self, url, payload=None, headers={}, timeout=20):
        """Helper for making asynchornous HTTP requests."""
        if self._auth:
            headers.update({
                'Authorization': 'Basic %s' % self._auth,
            })

        req = urllib2.Request(url, payload, headers)
        try:
            resp = urllib2.urlopen(req, timeout=timeout)
            return 200, resp.read()
        except urllib2.HTTPError as e:
            return e.code, ''
        except urllib2.URLError:
            return 503, ''

    def get_json(self, path, args, payload=None, headers={}, timeout=20):
        """Convenience function for issuing a JSON GET request."""
        url = build_url(self._base_url, path, args)
        status, resp = self.request(url,
                                    payload=payload,
                                    headers=headers,
                                    timeout=timeout)
        return status, (resp and json.loads(resp)) or {}