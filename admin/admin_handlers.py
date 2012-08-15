#!/usr/bin/env python

"""admin_handlers.py: Module that defines admin web handlers."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import logging

from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets
from google.appengine.api import taskqueue

from api.v1.data_sources import FlightAwareSource
from main import StaticHandler, BaseHandler, BaseAPIHandler
from models.v2 import FlightAwareTrackedFlight
from config import config, on_development, on_staging
import utils

source = FlightAwareSource()

class FlightAwareAdminHandler(StaticHandler):
    @ndb.toplevel
    def get(self):
        """Renders a basic FlightAware admin page with some stats and the
        ability to clear flight alerts.

        """
        alerts = yield source.get_all_alerts()
        alert_count = len(alerts)
        tracking_count = len((yield FlightAwareTrackedFlight.all_tracked_flight_ids()))
        users_tracking_count = len((yield FlightAwareTrackedFlight.all_users_tracking()))

        # Database invariant under one flight per user
        consistent = tracking_count <= users_tracking_count <= alert_count

        # Figure out what environment we're running in
        environment = (on_development() and 'Development') or (on_staging() and 'Staging') or 'Production'

        context = dict(alert_count=alert_count,
                       environment=environment,
                       flights_tracking_count=tracking_count,
                       users_tracking_count=users_tracking_count,
                       db_consistent=consistent)

        # Flight Aware Admin Handlers shouldn't be cached
        super(FlightAwareAdminHandler, self).get(page_name="fa_admin.html",
                                                 context=context,
                                                 use_cache=False)


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

    @ndb.toplevel
    def reset_alerts(self):
        """Resets flight alerts for all flights currently being tracked."""
        taskqueue.Queue('reset-alerts').add(taskqueue.Task())
        self.respond({'resetting' : True})


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


class ResetAlertsWorker(BaseHandler):
    """Taskqueue worker that resets all alerts for currently tracked flights."""
    @ndb.toplevel
    def post(self):
        # No retries allowed
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

        all_keys = yield FlightAwareTrackedFlight.all_flight_keys()

        @ndb.tasklet
        @ndb.transactional
        def reset_alert_txn(f_key):
            flight_id = f_key.string_id()
            assert utils.is_valid_fa_flight_id(flight_id)
            new_alert_id = yield source.set_alert(flight_id=flight_id)

            if new_alert_id and new_alert_id > 0:
                flight = yield f_key.get_async()
                flight.alert_id = new_alert_id
                yield flight.put_async()

        for key in all_keys:
            yield reset_alert_txn(key)
        logging.info('RESET %d ALERTS' % len(all_keys))