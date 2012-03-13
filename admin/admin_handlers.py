#!/usr/bin/python

"""admin_handlers.py: Module that defines handlers for admin web handlers."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging

from google.appengine.ext import ndb

from web_handlers import StaticHandler
from api.v1.api_handlers import BaseAPIHandler
from api.v1.data_sources import FlightAwareSource

from models import FlightAwareTrackedFlight, iOSUser
from config import config, on_local

source = FlightAwareSource()

class FlightAwareAdminHandler(StaticHandler):

    @ndb.toplevel
    def get(self):
        # Compute some basic stats
        alerts = yield source.get_all_alerts()
        alert_count = len(alerts)
        tracking_count = yield FlightAwareTrackedFlight.count_tracked_flights()
        users_tracking_count = yield iOSUser.count_users_tracking()

        context = dict(alert_count=alert_count,
                       flights_tracking_count=tracking_count,
                       users_tracking_count=users_tracking_count)
        super(FlightAwareAdminHandler, self).get(page_name="fa_admin.html",
                                                 context=context)

class FlightAwareAdminAPIHandler(BaseAPIHandler):
    """A handler that provides functionality to our internal FlightAware admin. These
    methods are called via AJAX from the web browser of a logged-in admin. At the
    point where the admin is able to call these methods, it is safe to assume they
    are already logged in. Currently callable over HTTP.

    """
    @ndb.toplevel
    def register_endpoint(self):
        result = yield source.register_alert_endpoint()
        self.respond(result)

    @ndb.toplevel
    def clear_alerts(self):
        result = yield source.clear_all_alerts()
        self.respond(result)
