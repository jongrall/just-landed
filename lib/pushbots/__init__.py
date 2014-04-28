#!/usr/bin/env python

"""A simple Python client wrapper for the Push API provided by Pushbots."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2014, Little Details LLC"
__email__ = "jon@littledetails.net"

import urllib
import json
import logging

from httplib2 import Http

SERVER = 'api.pushbots.com'
BASE_URL = 'https://' + SERVER
PUSH_URL = BASE_URL + '/push/one'
REGISTER_URL = BASE_URL + '/deviceToken'
DEREGISTER_URL = BASE_URL + '/deviceToken/del'

class Unauthorized(Exception):
    """Raised when we get a 401 from the server."""

class PushBotsFailure(Exception):
    """Raised when we get an error response from the server."""
    def __init__(self, status_code=500, message=''):
        self.message = message
        self.code = status_code

# FIXME: Assumes iOS
class PushBots(object):

    def __init__(self, app_id, secret, production=True):
        """Custom initialization."""
        self.app_id = app_id
        self.secret = secret
        self.is_production = production
        self.http = Http(timeout=5) # Set an aggressive timeout appropriate for GAE

    def _request(self, method, data, url, content_type='application/json'):
        """Initiates an HTTP request containing PushBots authentication headers."""
        body = None
        params = {}

        if method == 'GET' and isinstance(data, dict) and len(data) > 0:
            url = url + '?' + urllib.urlencode(data)
        else:
            if isinstance(data, dict):
                body = urllib.urlencode(data)
            else:
                body = data

        req_headers = {
            'x-pushbots-appid' : self.app_id,
            'x-pushbots-secret' : self.secret,
            'Content-Type' : content_type,
        }

        resp_headers, response = self.http.request(url, method, body=body, headers=req_headers)
        status = int(resp_headers['status'])

        if 200 <= status < 300:
            return
        elif status == 401:
            raise Unauthorized()
        else:
            raise PushBotsFailure(status_code=status, message=response.get('message'))

    def register(self, device_token):
        """Register the device token with PushBots."""
        assert isinstance(device_token, basestring) and len(device_token) == 64
        body = {
            'token': device_token,
            'platform' : '0', # iOS
        }
        self._request('PUT', json.dumps(body), REGISTER_URL)

    def deregister(self, device_token):
        """Mark this device token as inactive."""
        assert isinstance(device_token, basestring) and len(device_token) == 64
        body = {
            'token': device_token,
            'platform' : '0', # iOS
        }
        self._request('PUT', json.dumps(body), DEREGISTER_URL)

    def push(self, payload, device_tokens=None):
        """Push the payload to the the specified device tokens."""
        assert isinstance(payload, dict) and payload

        if device_tokens and isinstance(device_tokens, list) and len(device_tokens) > 0:
            body = {
                'platform' : '0', # iOS
                'token' : device_tokens[0], # sends only to a single device
                'msg' : payload['aps']['alert'],
                'sound' : payload['aps']['sound'],
                'badge' : '0',
                'payload': {
                    'notification_type': payload['notification_type'],
                }
            }
            self._request('POST', json.dumps(body), PUSH_URL)