#!/usr/bin/python

"""api_handlers.py: This module defines the Just Landed API handlers. All
requests by Just Landed clients are routed through here.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
import json
from datetime import datetime

from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from main import BaseHandler, BaseAPIHandler, AuthenticatedAPIHandler
from data_sources import FlightAwareSource, BingMapsDistanceSource
from exceptions import *
import utils

# Currently using FlightAware and Google Distance APIs
source = FlightAwareSource()
distance_source = BingMapsDistanceSource()

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
        flight_data = [f.dict_for_client() for f in flights]
        self.respond(flight_data)

###############################################################################
"""Tracking Flights"""
###############################################################################


class TrackWorker(BaseHandler):
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


class DelayedTrackWorker(BaseHandler):
    """Delayed track worker - used when updating reminders for latest traffic
    conditions."""
    @ndb.toplevel
    def post(self):
        # Disable retries
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

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
        # Get the current flight information
        flight = yield source.flight_info(flight_id=flight_id,
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
            'uuid' : uuid or '',
            'push_token' : push_token or '',
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

            # Allow for 50% fluctuation in driving time, 1 min cron delay
            first_check_time = utils.leave_now_time(flight.estimated_arrival_time, (driving_time * 1.5) + 60)
            # Check again at leave soon minus 1 min
            second_check_time = utils.leave_soon_time(flight.estimated_arrival_time, driving_time + 60)

            if first_check_time > now:
                delayed_task = taskqueue.Task(params={
                                                'flight_id' : flight_id,
                                                'uuid' : uuid,
                                                },
                                                eta=first_check_time)
                taskqueue.Queue('delayed-track').add(delayed_task)

            if second_check_time > now:
                delayed_task = taskqueue.Task(params={
                                                'flight_id' : flight_id,
                                                'uuid' : uuid,
                                                },
                                                eta=second_check_time)
                taskqueue.Queue('delayed-track').add(delayed_task)


class UntrackWorker(BaseHandler):
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

class AlertWorker(BaseHandler):
    """Deferred work when handling an alert."""
    @ndb.toplevel
    def post(self):
        # Disable retries, can't risk a flood of alerts
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

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
            task = taskqueue.Task(payload=self.request.body)
            taskqueue.Queue('process-alert').add(task)
        else:
            logging.error('Unknown user-agent or host posting alert: (%s, %s)' %
                            (self.request.environ.get('HTTP_USER_AGENT'),
                            self.request.remote_addr))