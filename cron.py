#!/usr/bin/python

"""cron.py: Handlers for cron jobs."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging

from google.appengine.ext import ndb
from google.appengine.ext import webapp
from google.appengine.api import urlfetch

from config import on_production
from models import FlightAwareTrackedFlight, iOSUser
from api.v1.data_sources import FlightAwareSource
from api.v1.datasource_exceptions import *
import utils

source = FlightAwareSource()


class UntrackOldFlightsWorker(webapp.RequestHandler):
    """Cron worker for untracking old flights."""
    @ndb.toplevel
    def get(self):
        # Get all flights that are currently tracking
        flight_keys = yield FlightAwareTrackedFlight.tracked_flights()

        while (yield flight_keys.has_next_async()):
            f_key = flight_keys.next()
            flight_id = f_key.string_id()
            flight_num = utils.flight_num_from_fa_flight_id(flight_id)

            # Find out if the flight is old
            try:
                flight = yield source.flight_info(flight_id=flight_id,
                                                flight_number=flight_num)
            except Exception as e:
                if isinstance(e, OldFlightException): # Only care about old flights
                    # We should untrack this flight for each user who was tracking it
                    user_keys_tracking = yield iOSUser.users_tracking_flight(flight_id)

                    # Generate the URL and API signature
                    url_scheme = (on_production() and 'https') or 'http'
                    to_sign = self.uri_for('untrack', flight_id=flight_id)
                    sig = utils.api_query_signature(to_sign, client='Server')
                    untrack_url = self.uri_for('untrack',
                                                flight_id=flight_id,
                                                _full=True,
                                                _scheme=url_scheme)
                    requests =[]

                    while (yield user_keys_tracking.has_next_async()):
                        u_key = user_keys_tracking.next()
                        headers = {'X-Just-Landed-UUID' : u_key.string_id(),
                                   'X-Just-Landed-Signature' : sig}

                        ctx = ndb.get_context()
                        req_fut = ctx.urlfetch(untrack_url,
                                                headers=headers,
                                                deadline=120,
                                                validate_certificate=on_production())
                        requests.append(req_fut)

                    yield requests # Parallel yield of all requests