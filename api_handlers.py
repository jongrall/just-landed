#!/usr/bin/python

"""api_handlers.py: This module defines the Just Landed API handlers. All
requests by Just Landed clients are routed through here.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
import json

from lib import webapp2 as webapp

from data_sources import FlightAwareSource, GoogleDistanceSource

from config import config
from datasource_exceptions import *
import utils

# Currently using FlightAware and Google Distance APIs
source = FlightAwareSource()
distance_source = GoogleDistanceSource()

class BaseAPIHandler(webapp.RequestHandler):
    """Base API handler that other handlers inherit from. This base class
    provides basic exception handling and methods for creating JSON responses."""
    def handle_exception(self, exception, debug):
        """Override standard webapp exception handling and do our own logging.
        Clients get a generic error and status code corresponding to the type
        of problem encountered."""
        self.respond({'error' : exception.message or 'An error occurred.'})
        if hasattr(exception, 'code'):
            if exception.code == 500:
                # Only log 500s as exceptions
                logging.exception(exception)
            else:
                # Log others as errors
                logging.error(exception.message)
            self.response.set_status(exception.code)
        else:
            logging.exception(exception)
            self.response.set_status(500)

    def respond(self, response_dict, debug=False):
        """Takes a dictionary as input and responds to the client using JSON.

        If 'debug' is set to true, the output is nicely formatted and indented
        for reading in the browser.
        """
        if debug or self.request.GET.get('debug'):
            # Pretty print JSON to be read as HTML
            self.response.content_type = 'text/html'
            formatted_resp = json.dumps(response_dict, sort_keys=True, indent=4)
            self.response.write(utils.text_to_html(formatted_resp))
        else:
            # Set response content type to JSON
            self.response.content_type = 'application/json'
            self.response.write(json.dumps(response_dict))

class TrackHandler(BaseAPIHandler):
    """Handles tracking a flight by flight number and id."""
    def get(self, flight_number, flight_id):
        """Returns detailed information for tracking a flight given a flight
        number and flight id (this uniquely identifies a single flight). This
        handler responds to the client using JSON.

        In addition to the required flight number and id, the client may also
        provide the following arguments as query parameters:

        - `latitude`: The latitude component of the user's location.
        - `longitude`: The longitude component of the user's location.
        - `push`: Whether the user should receive push notifications.
        - `begin_track`: The client sets this to true when doing the initial
            tracking request after looking up a flight. This has the side effect
            of potentially registering flight status notifications for this user
            for this flight.
        - `debug`: If this is set to true, the response is nicely formatted for
        reading in the browser.

        """
        if not utils.valid_flight_number(flight_number):
            raise InvalidFlightNumberException(flight_number)

        info = source.flight_info(flight_id=flight_id,
                                  flight_number=flight_number)

        push =  (utils.is_number(latitude) and
                bool(int(self.request.params.get('push'))))
        begin_track = (utils.is_number(latitude) and
                        bool(int(self.request.params.get('begin_track'))))

        if push and begin_track:
            # TODO(jon): Register the client's UDID for push notifications
            pass

        latitude = self.request.params.get('latitude')
        latitude = utils.is_number(latitude) and float(latitude)
        longitude = self.request.params.get('longitude')
        longitude = utils.is_number(longitude) and float(longitude)
        dest_latitude = info['destination']['latitude']
        dest_longitude = info['destination']['longitude']

        if (latitude and longitude and utils.is_in_flight(info) and
            not utils.too_close_or_far(latitude,
                                        longitude,
                                        dest_latitude,
                                        dest_longitude)):
            # Fail gracefully if we can't get driving distance
            try:
                driving_time = distance_source.driving_time(latitude,
                                                            longitude,
                                                            dest_latitude,
                                                            dest_longitude)
                info.update(utils.leave_for_airport(info, driving_time))
            except (UnknownDrivingTimeException, DrivingDistanceDeniedException,
                    DrivingAPIQuotaException) as e:
                logging.error(e.message)

        info = utils.sub_dict_select(info, config['track_fields'])
        self.respond(info)

class SearchHandler(BaseAPIHandler):
    """Handles looking up a flight by flight number."""
    def get(self, flight_number):
        """Returns top-level information about flights matching a specific
        flight number. The flights returned will be flights that have landed
        no more than an hour ago or are en-route or scheduled for the future.

        This handler responds to the client using JSON.

        """
        if not utils.valid_flight_number(flight_number):
            raise InvalidFlightNumberException(flight_number)

        flights = source.lookup_flights(flight_number)
        self.respond(flights)

class UntrackHandler(BaseAPIHandler):
    """Handles untracking a specific flight. Usually called when a user is no
    longer tracking a flight and doesn't want to receive future notifications
    for that flight.

    """
    def get(self, flight_id):
        self.respond('Untrack %s goes here.' % flight_id)

class AlertHandler(BaseAPIHandler):
    """Handles flight alert callbacks from a 3rd party API, potentially
    triggering notifications to users tracking the flight associated with the
    alert.

    """
    def post(self):
        self.respond('Alert handler goes here.')