#!/usr/bin/python

"""admin_handlers.py: Module that defines handlers for admin web handlers."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging

from web_handlers import StaticHandler
from api_handlers import BaseAPIHandler
from data_sources import FlightAwareSource

from models import FlightAwareTrackedFlight, FlightAwareAlert, iOSUser
from config import config, on_local

source = FlightAwareSource()

class FlightAwareAdminHandler(StaticHandler):

    def get(self):
        # Compute some basic stats
        alert_count = len(source.get_all_alerts())
        tracking_count = FlightAwareTrackedFlight.count_tracked_flights()
        users_tracking_count = iOSUser.count_users_tracking()

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

    def register_endpoint(self):
        result = source.register_alert_endpoint()
        self.respond(result)

    def clear_alerts(self):
        result = source.clear_all_alerts()
        self.respond(result)
