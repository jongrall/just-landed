#!/usr/bin/env python

"""web_handlers.py: Module that defines handlers for (static) web content on the
getjustlanded.com website.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

import logging
import urllib
import json

from lib import createsend
CreateSend = createsend.CreateSend
List = createsend.List
Subscriber = createsend.Subscriber

from main import StaticHandler, BaseHandler, BaseAPIHandler
from config import config, subscriber_list_id
from custom_exceptions import *
import utils

CreateSend.api_key = config['campaignmonitor']['key']
create_send_client = CreateSend()

class BlitzHandler(StaticHandler):
    """Verification handler to enable Blitz.io performance testing."""
    def get(self):
        self.response.write('42')


class CampaignMonitorHandler(BaseAPIHandler):
    """Handlers that allow users to join/unsubscribe from the mailing list."""
    def post(self):
        body = json.loads(self.request.body)
        email = body.get('email') or ''
        email = urllib.unquote(email)

        if not utils.valid_email(email):
            self.respond({'error' : 'invalid'})
            self.response.set_status(400)
            return

        # Email is valid, try to register with campaign monitor
        try:
            response = Subscriber().add(subscriber_list_id(), email, '', [],
                                        resubscribe=True)
        except createsend.Unauthorized:
            raise CampaignMonitorUnauthorizedError()
        except Exception:
            raise CampaignMonitorUnavailableError()

        self.respond({'success' : 'subscribed'})