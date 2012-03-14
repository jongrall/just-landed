#!/usr/bin/python

"""api_handlers.py: This module defines the Just Landed API handlers. All
requests by Just Landed clients are routed through here.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
import json

from google.appengine.ext import webapp
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from data_sources import FlightAwareSource, GoogleDistanceSource, BingMapsDistanceSource

from datasource_exceptions import *
from config import on_local
import utils

# Currently using FlightAware and Google Distance APIs
source = FlightAwareSource()
#distance_source = GoogleDistanceSource()
distance_source = BingMapsDistanceSource()

###############################################################################
"""Base Handlers"""
###############################################################################

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

    def respond(self, response_data, debug=False):
        """Takes a dictionary or list as input and responds to the client using
        JSON.

        If 'debug' is set to true, the output is nicely formatted and indented
        for reading in the browser.
        """
        if debug or self.request.GET.get('debug'):
            # Pretty print JSON to be read as HTML
            self.response.content_type = 'text/html'
            formatted_resp = json.dumps(response_data, sort_keys=True, indent=4)
            self.response.write(utils.text_to_html(formatted_resp))
        else:
            # Set response content type to JSON
            self.response.content_type = 'application/json'
            self.response.write(json.dumps(response_data))


class AuthenticatedAPIHandler(BaseAPIHandler):
    """An API handler that also authenticates incoming API requests."""
    def dispatch(self):
        is_server = self.request.headers.get('User-Agent').startswith('AppEngine')
        client = (is_server and 'Server') or 'iOS'
        if on_local() or utils.authenticate_api_request(self.request, client=client):
            # Parent class will call the method to be dispatched
            # -- get() or post() or etc.
            super(AuthenticatedAPIHandler, self).dispatch()
        else:
            self.abort(403)

###############################################################################
"""Search / Lookup"""
###############################################################################

class SearchHandler(AuthenticatedAPIHandler):
    """Handles looking up a flight by flight number."""
    @ndb.toplevel
    def get(self, flight_number):
        """Returns top-level information about flights matching a specific
        flight number. The flights returned will be flights that have landed
        no more than an hour ago or are en-route or scheduled for the future.

        This handler responds to the client using JSON.

        """
        if not utils.valid_flight_number(flight_number):
            raise InvalidFlightNumberException(flight_number)

        flights = yield source.lookup_flights(flight_number)
        flight_data = []

        for f in flights:
            flight_data.append(f.dict_for_client())

        self.respond(flight_data)

###############################################################################
"""Tracking Flights"""
###############################################################################


class TrackWorker(webapp.RequestHandler):
    """Deferred work when tracking a flight."""
    @ndb.toplevel
    def post(self):
        params = self.request.params
        flight_id = params.get('flight_id')
        flight_number = params.get('flight_number')
        assert (isinstance(flight_id, basestring) and len(flight_id) and
            utils.valid_flight_number(flight_number))

        uuid = params.get('uuid')
        push_token = params.get('push_token')
        yield source.start_tracking_flight(flight_id,
                                        flight_number,
                                        uuid=uuid,
                                        push_token=push_token)


class TrackHandler(AuthenticatedAPIHandler):
    """Handles tracking a flight by flight number and id."""
    @ndb.toplevel
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
        # Get the current flight information
        flight = yield source.flight_info(flight_id=flight_id,
                                          flight_number=flight_number)

        # FIXME: Assume iOS device for now
        uuid = self.request.headers.get('X-Just-Landed-UUID')
        push_token = self.request.params.get('push_token')

        # Get driving distance, if we have their location
        latitude = self.request.params.get('latitude')
        latitude = utils.is_number(latitude) and float(latitude)
        longitude = self.request.params.get('longitude')
        longitude = utils.is_number(longitude) and float(longitude)
        dest_latitude = flight.destination.latitude
        dest_longitude = flight.destination.longitude

        if (latitude and longitude and
            not utils.too_close_or_far(latitude,
                                        longitude,
                                        dest_latitude,
                                        dest_longitude)):
            # Fail gracefully if we can't get driving distance
            try:
                driving_time = yield distance_source.driving_time(latitude,
                                                                  longitude,
                                                                  dest_latitude,
                                                                  dest_longitude)
                flight.set_driving_time(driving_time)
            except (UnknownDrivingTimeException, DrivingDistanceDeniedException,
                    DrivingAPIQuotaException) as e:
                logging.error(e.message)

        self.respond(flight.dict_for_client())

        # Track the flight (deferred)
        task = taskqueue.Task(params = {
            'flight_id' : flight_id,
            'flight_number' : flight_number,
            'uuid' : uuid,
            'push_token' : push_token,
        })
        taskqueue.Queue('track').add(task)


class UntrackWorker(webapp.RequestHandler):
    """Deferred work when untracking a flight."""
    @ndb.toplevel
    def post(self):
        params = self.request.params
        flight_id = params.get('flight_id')
        assert isinstance(flight_id, basestring) and len(flight_id)

        uuid = params.get('uuid')
        yield source.stop_tracking_flight(flight_id, uuid=uuid)


class UntrackHandler(AuthenticatedAPIHandler):
    """Handles untracking a specific flight. Usually called when a user is no
    longer tracking a flight and doesn't want to receive future notifications
    for that flight.

    """
    def get(self, flight_id):
        if not flight_id or not isinstance(flight_id, basestring):
            raise FlightNotFoundException(flight_id)

        # FIXME: Assume iOS device for now
        uuid = self.request.headers.get('X-Just-Landed-UUID')
        self.respond({'untracked' : flight_id})

        # Untrack the flight (deferred)
        task = taskqueue.Task(params = {
            'flight_id' : flight_id,
            'uuid' : uuid,
        })
        taskqueue.Queue('untrack').add(task)

###############################################################################
"""Processing Alerts"""
###############################################################################

class AlertWorker(webapp.RequestHandler):
    """Deferred work when handling an alert."""
    @ndb.toplevel
    def post(self):
        alert_body = self.request.params
        assert alert_body
        yield source.process_alert(alert_body)


class AlertHandler(BaseAPIHandler):
    """Handles flight alert callbacks from a 3rd party API, potentially
    triggering notifications to users tracking the flight associated with the
    alert.

    """
    def post(self):
        # Make sure the POST came from the trusted datasource
        if (source.authenticate_remote_request(self.request)):
            alert_body = json.loads(self.request.body)

            # Process the alert (deferred)
            task = taskqueue.Task(params=alert_body)
            taskqueue.Queue('process-alert').add(task)
        else:
            logging.error('Unknown user-agent or host posting alert: (%s, %s)' %
                            (self.request.environ.get('HTTP_USER_AGENT'),
                            self.request.remote_addr))