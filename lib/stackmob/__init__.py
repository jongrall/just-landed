#!/usr/bin/env python

"""A simple Python client wrapper for the Push API provided by StackMob."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import urllib
import json
import logging

import oauth2 as oauth
from httplib2 import Http

SERVER = 'push.mob1.stackmob.com'
BASE_URL = 'https://' + SERVER
PUSH_URL = BASE_URL + '/push_tokens_universal'
REGISTER_URL = BASE_URL + '/register_device_token_universal'
DEREGISTER_URL = BASE_URL + '/remove_token_universal'

class Unauthorized(Exception):
    """Raised when we get a 401 from the server."""

class StackMobFailure(Exception):
    """Raised when we get an error response from the server."""
    def __init__(self, status_code=500, message=''):
        self.message = message
        self.code = status_code

# FIXME: Assumes iOS
class StackMob(object):

    def __init__(self, public_key, private_key, production=True):
        """Custom initialization."""
        self.public_key = public_key
        self.private_key = private_key
        self.is_production = production
        self.consumer = oauth.Consumer(public_key, private_key)
        self.signature = oauth.SignatureMethod_HMAC_SHA1()
        self.headers = {}
        self.http = Http(timeout=5) # Set an aggressive timeout appropriate for GAE

    def _request(self, method, data, url, content_type='application/json'):
        """Initiates an HTTP request secured using OAuth."""
        body = None
        params = {}

        if method == 'GET' and isinstance(data, dict) and len(data) > 0:
            url = url + '?' + urllib.urlencode(data)
        else:
            if isinstance(data, dict):
                body = urllib.urlencode(data)
            else:
                body = data

        request = oauth.Request.from_consumer_and_token(self.consumer,
            http_method=method, http_url=url, parameters=params)
        request.sign_request(self.signature, self.consumer, None)
        headers = request.to_header(BASE_URL)
        version = (self.is_production and 1) or 0
        headers.update({
            'Accept' : 'application/vnd.stackmob+json; version=%d' % version,
            'Content-Type' : content_type,
        })

        self.headers, response = self.http.request(url, method, body=body, headers=headers)
        status = int(self.headers['status'])

        if 200 <= status < 300 or status in [400, 409]: # 400/409 can be existing registered token (doesn't work like UA)
            return
        elif status == 401:
            raise Unauthorized()
        else:
            raise StackMobFailure(status_code=status, message=response)

    def register(self, device_token):
        """Register the device token with StackMob."""
        assert isinstance(device_token, basestring) and len(device_token) == 64
        body = {
            'token': {
                'type': 'ios',
                'token': device_token,
            },
            'userId': 'just-landed-iOS-user',
        }
        self._request('POST', json.dumps(body), REGISTER_URL)

    def deregister(self, device_token):
        """Mark this device token as inactive."""
        assert isinstance(device_token, basestring) and len(device_token) == 64
        body = {
            'token': device_token,
            'type': 'ios',
        }
        self._request('POST', json.dumps(body), DEREGISTER_URL)

    def push(self, payload, device_tokens=None):
        """Push the payload to the the specified device tokens."""
        assert isinstance(payload, dict) and payload

        if device_tokens and isinstance(device_tokens, list):
            tokens = []
            for t in device_tokens:
                tokens.append({
                    'type': 'ios',
                    'token' : t,
                })

            body = {
                'payload': {
                    "kvPairs": {
                        'sound': payload['aps']['sound'],
                        'alert': payload['aps']['alert'],
                        'notification_type': payload['notification_type'],
                    },
                },
                'tokens': tokens,
            }
            self._request('POST', json.dumps(body), PUSH_URL)