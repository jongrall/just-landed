#!/usr/bin/python

"""api_handlers.py: This module defines the Just Landed API handlers. All
requests by Just Landed clients are routed through here.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
import json
import traceback
from datetime import timedelta, datetime

from google.appengine.ext import webapp
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from data_sources import FlightAwareSource, GoogleDistanceSource, BingMapsDistanceSource

from datasource_exceptions import *
from config import on_local, config
import utils

import reporting
from reporting import prodeagle_counter

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
        traceback_as_string = traceback.format_exc()

        if isinstance(exception, FlightNotFoundException):
            prodeagle_counter.incr(reporting.FLIGHT_NOT_FOUND)

        elif isinstance(exception, (UnknownDrivingTimeException,
                                    MalformedDrivingDataException,
                                    DrivingAPIQuotaException,
                                    DrivingDistanceDeniedException)):
            prodeagle_counter.incr(reporting.CANT_FETCH_DRIVING_TIME)

        elif isinstance(exception, InvalidFlightNumberException):
            prodeagle_counter.incr(reporting.FLIGHT_NUMBER_INVALID)

        if hasattr(exception, 'code'):
            if exception.code == 500:
                # Only log 500s as exceptions
                logging.exception(exception)
                utils.report_exception(exception, traceback_as_string)
                prodeagle_counter.incr(reporting.ERROR_500)
            else:
                # Log others as errors
                logging.error(exception.message)

                # Report certain errors to admin
                if isinstance(exception, (TerminalsUnknownException,
                                          AirportNotFoundException,
                                          UnableToSetAlertException,
                                          UnableToSetEndpointException,
                                          UnableToGetAlertsException,
                                          UnableToDeleteAlertException,
                                          MalformedDrivingDataException,
                                          DrivingAPIQuotaException,
                                          DrivingDistanceDeniedException)):
                    utils.report_exception(exception, traceback_as_string)

            self.response.set_status(exception.code)
        else:
            logging.exception(exception)
            utils.report_exception(exception, traceback_as_string)
            prodeagle_counter.incr(reporting.ERROR_500)
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
        self.client = (is_server and 'Server') or 'iOS'
        if on_local() or utils.authenticate_api_request(self.request, client=self.client):
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
        if self.client != 'Server':
            prodeagle_counter.incr(reporting.LOOKUP_FLIGHT)

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


class TrackWorker(BaseAPIHandler):
    """Deferred work when tracking a flight."""
    @ndb.toplevel
    def post(self):
        params = self.request.params
        flight_data = json.loads(params.get('flight'))
        uuid = params.get('uuid')
        push_token = params.get('push_token')
        user_latitude = params.get('user_latitude')
        user_longitude = params.get('user_longitude')
        driving_time = params.get('driving_time')

        if utils.is_float(user_latitude) and utils.is_float(user_longitude):
            user_latitude = float(user_latitude)
            user_longitude = float(user_longitude)
        else:
            user_latitude = None
            user_longitude = None

        if utils.is_int(driving_time):
            driving_time = int(driving_time)
        else:
            driving_time = None

        yield source.track_flight(flight_data,
                                  uuid=uuid,
                                  push_token=push_token,
                                  user_latitude=user_latitude,
                                  user_longitude=user_longitude,
                                  driving_time=driving_time)


class DelayedTrackWorker(BaseAPIHandler):
    """Delayed track worker - used when updating reminders for latest traffic
    conditions."""
    @ndb.toplevel
    def post(self):
        params = self.request.params
        uuid = params.get('uuid')
        flight_id = params.get('flight_id')
        assert isinstance(uuid, basestring) and len(uuid)
        assert isinstance(flight_id, basestring) and len(flight_id)
        yield source.delayed_track(self, flight_id, uuid)


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
        if self.client != 'Server':
            prodeagle_counter.incr(reporting.TRACK_FLIGHT)
        else:
            prodeagle_counter.incr(reporting.DELAYED_TRACK)

        # Get the current flight information
        flight_fut = source.flight_info(flight_id=flight_id,
                                        flight_number=flight_number)

        # FIXME: Assume iOS device for now
        uuid = self.request.headers.get('X-Just-Landed-UUID')
        push_token = self.request.params.get('push_token')

        # Was this a server-initiated, delayed /track?
        delayed = self.request.params.get('delayed')
        server_scheduled = (utils.is_int(delayed) and bool(int(delayed))) or False

        # Get driving time, if we have their location
        driving_time = None
        latitude = self.request.params.get('latitude')
        latitude = utils.is_float(latitude) and float(latitude)
        longitude = self.request.params.get('longitude')
        longitude = utils.is_float(longitude) and float(longitude)

        flight = yield flight_fut
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
                    DrivingAPIQuotaException, MalformedDrivingDataException) as e:
                logging.error(e.message)

        self.respond(flight.dict_for_client())

        # Track the flight (deferred)
        task = taskqueue.Task(params={
            'flight' : json.dumps(flight.to_dict()),
            'uuid' : uuid,
            'push_token' : push_token,
            'user_latitude' : (utils.is_float(latitude) and latitude) or '',
            'user_longitude' : (utils.is_float(longitude) and longitude) or '',
            'driving_time' : (utils.is_int(driving_time) and int(driving_time)) or '',
        })
        taskqueue.Queue('track').add(task)

        # Schedule a /track to happen a couple of times in the future before landing - this will ensure that their
        # leave alerts are accurate - taking into account traffic conditions
        # checking server_scheduled prevents a cascade of calls to /track
        if not server_scheduled and utils.is_int(driving_time) and uuid and flight.is_in_flight :
            driving_time = int(driving_time)
            now = datetime.utcnow()
            retry_options = taskqueue.TaskRetryOptions(task_retry_limit=0) # No more than 1 try

            # Allow for 50% fluctuation in driving time, 1 min cron delay
            first_check_time = utils.leave_now_time(flight.estimated_arrival_time, (driving_time * 1.5) + 60)
            # Check again at leave soon minus 1 min
            second_check_time = utils.leave_soon_time(flight.estimated_arrival_time, driving_time + 60)

            if first_check_time > now:
                delayed_task = taskqueue.Task(params={
                                                'flight_id' : flight_id,
                                                'uuid' : uuid,
                                                },
                                                eta=first_check_time,
                                                retry_options=retry_options)
                taskqueue.Queue('delayed-track').add(delayed_task)

            if second_check_time > now:
                delayed_task = taskqueue.Task(params={
                                                'flight_id' : flight_id,
                                                'uuid' : uuid,
                                                },
                                                eta=second_check_time,
                                                retry_options=retry_options)
                taskqueue.Queue('delayed-track').add(delayed_task)


class UntrackWorker(BaseAPIHandler):
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

        if self.client != 'Server':
            prodeagle_counter.incr(reporting.UNTRACK_FLIGHT)
        else:
            prodeagle_counter.incr(reporting.DELAYED_UNTRACK)

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

class AlertWorker(BaseAPIHandler):
    """Deferred work when handling an alert."""
    @ndb.toplevel
    def post(self):
        alert_body = json.loads(self.request.body)
        assert isinstance(alert_body, dict)
        yield source.process_alert(alert_body, self)


class AlertHandler(BaseAPIHandler):
    """Handles flight alert callbacks from a 3rd party API, potentially
    triggering notifications to users tracking the flight associated with the
    alert.

    """
    def post(self):
        # Make sure the POST came from the trusted datasource
        if (source.authenticate_remote_request(self.request)):
            prodeagle_counter.incr(reporting.GOT_FLIGHT_ALERT_CALLBACK)

            # Process the alert (deferred)
            retry_opts = taskqueue.TaskRetryOptions(task_retry_limit=0) # Can't risk a flood of push notifications
            task = taskqueue.Task(payload=self.request.body,
                                  retry_options=retry_opts)
            taskqueue.Queue('process-alert').add(task)
        else:
            logging.error('Unknown user-agent or host posting alert: (%s, %s)' %
                            (self.request.environ.get('HTTP_USER_AGENT'),
                            self.request.remote_addr))