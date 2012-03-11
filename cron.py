#!/usr/bin/python

"""cron.py: Handlers for cron jobs."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging

from google.appengine.ext import webapp
from google.appengine.api import urlfetch

from config import on_production
from models import *
from api.v1.data_sources import FlightAwareSource
from api.v1.datasource_exceptions import *
import utils

source = FlightAwareSource()


class UntrackOldFlightsWorker(webapp.RequestHandler):
    """Cron worker for untracking old flights."""
    def get(self):
        # Get all flights that are currently tracking
        flight_keys = FlightAwareTrackedFlight.tracked_flights()

        for f_key in flight_keys:
            flight_id = f_key.string_id()
            flight_num = utils.flight_num_from_fa_flight_id(flight_id)

            # Find out if the flight is old
            try:
                flight = source.flight_info(flight_id=flight_id,
                                            flight_number=flight_num)
            except Exception as e:
                if isinstance(e, OldFlightException):
                    # We should untrack this flight for each user who was tracking it
                    user_keys_tracking = iOSUser.users_tracking_flight(f_key)

                    # Generate the URL and API signature
                    url_scheme = (on_production() and 'https') or 'http'
                    to_sign = self.uri_for('untrack', flight_id=flight_id)
                    sig = utils.api_query_signature(to_sign, client='Server')
                    untrack_url = self.uri_for('untrack',
                                                flight_id=flight_id,
                                                _full=True,
                                                _scheme=url_scheme)

                    for u_key in user_keys_tracking:
                        headers = {'X-Just-Landed-UUID' : u_key.string_id(),
                                   'X-Just-Landed-Signature' : sig}

                        if on_production():
                            # Async fetch
                            rpc = urlfetch.create_rpc(deadline=120)
                            urlfetch.make_fetch_call(rpc,
                                                    untrack_url,
                                                    headers=headers)
                        else:
                            # Dev server doesn't do async requests
                            urlfetch.fetch(untrack_url,
                                           headers=headers,
                                           deadline=60)