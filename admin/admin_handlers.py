#!/usr/bin/python

"""admin_handlers.py: Module that defines admin web handlers."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

import logging

from google.appengine.ext import ndb

from api.v1.data_sources import FlightAwareSource
from main import StaticHandler, BaseHandler, BaseAPIHandler
from models import FlightAwareTrackedFlight, iOSUser
from config import config, on_development, on_staging

source = FlightAwareSource()

class FlightAwareAdminHandler(StaticHandler):
    @ndb.toplevel
    def get(self):
        """Renders a basic FlightAware admin page with some stats and the
        ability to clear flight alerts.

        """
        alerts = yield source.get_all_alerts()
        alert_count = len(alerts)
        tracking_count = yield FlightAwareTrackedFlight.count_tracked_flights()
        users_tracking_count = yield iOSUser.count_users_tracking()

        # Database invariant under one flight per user
        consistent = alert_count <= tracking_count <= users_tracking_count

        # Figure out what environment we're running in
        environment = (on_development() and 'Development') or (on_staging() and 'Staging') or 'Production'

        context = dict(alert_count=alert_count,
                       environment=environment,
                       flights_tracking_count=tracking_count,
                       users_tracking_count=users_tracking_count,
                       db_consistent=consistent)

        super(FlightAwareAdminHandler, self).get(page_name="fa_admin.html",
                                                 context=context)


class FlightAwareAdminAPIHandler(BaseAPIHandler):
    """A handler that provides functionality to our internal FlightAware admin. These
    methods are called via AJAX from the web browser of a logged-in admin.

    """
    @ndb.toplevel
    def register_endpoint(self):
        """Registers the push notification endpoint with FlightAware."""
        result = yield source.register_alert_endpoint()
        self.respond(result)

    @ndb.toplevel
    def clear_alerts(self):
        """Clears all FlightAware alerts."""
        result = yield source.clear_all_alerts()
        self.respond(result)


class ClearAlertsWorker(BaseHandler):
    """Taskqueue worker that clears alerts."""
    @ndb.toplevel
    def post(self):
        # No retries allowed
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

        alert_list = self.request.body
        if alert_list:
            alert_ids = alert_list.split(',')
            alert_ids = [int(alert_id) for alert_id in alert_ids]
            yield source.delete_alerts(alert_ids)