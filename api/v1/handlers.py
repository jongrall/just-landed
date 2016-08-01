"""handlers.py: This module defines the Just Landed API handlers. All
requests by Just Landed clients are routed through here.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Little Details LLC"
__email__ = "jon@littledetails.net"

import logging
import json
import pickle
from datetime import datetime, timedelta

from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from main import BaseHandler, BaseAPIHandler, AuthenticatedAPIHandler
from api.v1.data_sources import FlightAwareSource, BingMapsDistanceSource, HereRoutesDistanceSource, GoogleDistanceSource
from custom_exceptions import *
import utils

from reporting import log_event, FlightSearchEvent, FlightSearchMissEvent, UserAtAirportEvent

# Currently using FlightAware for flight data
source = FlightAwareSource()

# Driving time sources with fallbacks
distance_source = HereRoutesDistanceSource()
fallback_distance_source = GoogleDistanceSource()
last_resort_distance_source = BingMapsDistanceSource()

###############################################################################
# Search / Lookup
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
		# FIXME: Assumes iOS device for now
        uuid = self.request.headers.get('X-Just-Landed-UUID')
        sanitized_f_num = utils.sanitize_flight_number(flight_number)

        if not utils.valid_flight_number(flight_number):
            if utils.is_int(sanitized_f_num):
                raise FlightNotFoundException(flight_number)
            else:
                raise InvalidFlightNumberException(flight_number)

        try:
            log_event(FlightSearchEvent, user_id=uuid, flight_number=sanitized_f_num)
            flights = yield source.lookup_flights(flight_number)

        except CurrentFlightNotFoundException as e:
            raise e # Not worth trying again, we found the flight but it's old

        except FlightNotFoundException as e:
            log_event(FlightSearchMissEvent, user_id=uuid, flight_number=sanitized_f_num)
            # Flight lookup failed, see if we can translate their airline code
            translated_f_num = utils.translate_flight_number_to_icao(flight_number)
            if not translated_f_num:
                raise e
            flights = yield source.lookup_flights(translated_f_num)

        flight_data = [f.dict_for_client() for f in flights]
        self.respond(flight_data)

###############################################################################
# Tracking Flights
###############################################################################

class TrackWorker(BaseHandler):
    """Deferred work when tracking a flight."""
    @ndb.toplevel
    def post(self):
        params = self.request.params
        flight_data = json.loads(params.get('flight'))
        uuid = params.get('uuid')
        app_version = params.get('app_version')
        preferred_language = params.get('preferred_language')
        push_token = params.get('push_token')
        user_latitude = utils.sanitize_float(params.get('user_latitude'))
        user_longitude = utils.sanitize_float(params.get('user_longitude'))
        driving_time = utils.sanitize_positive_int(params.get('driving_time'))
        reminder_lead_time = utils.sanitize_positive_int(params.get('reminder_lead_time'))
        send_reminders = utils.sanitize_bool(params.get('send_reminders'), default=True)
        send_flight_events = utils.sanitize_bool(params.get('send_flight_events'), default=True)
        play_flight_sounds = utils.sanitize_bool(params.get('play_flight_sounds'), default=True)

        yield source.track_flight(flight_data,
                                  uuid=uuid,
                                  app_version=app_version,
                                  preferred_language=preferred_language,
                                  push_token=push_token,
                                  user_latitude=user_latitude,
                                  user_longitude=user_longitude,
                                  driving_time=driving_time,
                                  reminder_lead_time=reminder_lead_time,
                                  send_reminders=send_reminders,
                                  send_flight_events=send_flight_events,
                                  play_flight_sounds=play_flight_sounds)


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
        assert utils.is_valid_uuid(uuid)
        assert utils.is_valid_flight_id(flight_id)
        yield source.do_track(self, flight_id, uuid)


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
        # FIXME: Assumes iOS device for now
        uuid = self.request.headers.get('X-Just-Landed-UUID')
        app_version = self.request.headers.get('X-Just-Landed-App-Version')
        preferred_language = self.request.headers.get('X-Just-Landed-User-Language')
        push_token = self.request.params.get('push_token')
        reminder_lead_time = self.request.params.get('reminder_lead_time')
        send_reminders = self.request.params.get('send_reminders')
        send_flight_events = self.request.params.get('send_flight_events')
        play_flight_sounds = self.request.params.get('play_flight_sounds')

        # /track requests from server should not use the cache - we want the latest data
        use_cache = self.client != 'Server'

        assert utils.is_valid_uuid(uuid)

        if not utils.is_valid_flight_id(flight_id):
            raise InvalidFlightNumberException(flight_id)

        # Get the current flight information
        flight = yield source.flight_info(flight_id=flight_id,
                                          flight_number=flight_number,
                                          use_cache=use_cache)

        # Get driving time, if we have their location
        driving_time = None
        latitude = utils.sanitize_float(self.request.params.get('latitude'), default='')
        longitude = utils.sanitize_float(self.request.params.get('longitude'), default='')
        dest_latitude = flight.destination.latitude
        dest_longitude = flight.destination.longitude

        # Optimization: only get driving distance if they're not too close or too far from the airport
        if (latitude and longitude and
            not utils.too_close_or_far(latitude,
                                        longitude,
                                        dest_latitude,
                                        dest_longitude)):

            # Fail gracefully if we can't get driving distance
            for driving_source in [distance_source, fallback_distance_source, last_resort_distance_source]:
                try:
                    driving_time = yield driving_source.driving_time(latitude,
                                                                     longitude,
                                                                     dest_latitude,
                                                                     dest_longitude,
                                                                     use_cache=use_cache)
                    break

                except Exception as e:
                    if isinstance(e, NoDrivingRouteException):
                        logging.warn(e) # No route is a warn, skip fallback service
                        break
                    if driving_source == last_resort_distance_source:
                        raise # Give up, re-raise
                    else:
                        logging.exception(e)
                        if isinstance(e, DrivingTimeUnavailableError):
                            utils.report_service_error(e) # Outage reporting delayed
                        elif isinstance(e, (MalformedDrivingDataException,
                                            DrivingAPIQuotaException,
                                            DrivingTimeUnauthorizedException)):
                            utils.sms_report_exception(e) # Unexpected errors reported immediately

        response = flight.dict_for_client()

        if driving_time and driving_time > 0:
            response['drivingTime'] = driving_time
            response['leaveForAirportTime'] = utils.timestamp(utils.leave_now_time(flight, driving_time))
        elif latitude and longitude and utils.at_airport(latitude, longitude, dest_latitude, dest_longitude):
            response['drivingTime'] = 0
            log_event(UserAtAirportEvent,
                    user_id=uuid,
                    flight_id=flight.flight_id,
                    airport=(flight.destination.iata_code or flight.destination.icao_code))

        self.respond(response)

        # Optimization: defer the bulk of the work to track the flight
        if uuid:
            task = taskqueue.Task(params={
                'flight' : json.dumps(flight.to_dict()),
                'uuid' : uuid or '',
                'app_version' : app_version or '',
                'preferred_language' : preferred_language or '',
                'push_token' : push_token or '',
                'user_latitude' : latitude,
                'user_longitude' : longitude,
                'driving_time' : utils.sanitize_positive_int(driving_time, default=''),
                'reminder_lead_time' : utils.sanitize_positive_int(reminder_lead_time, default=''),
                'send_reminders' : send_reminders,
                'send_flight_events' : send_flight_events,
                'play_flight_sounds' : play_flight_sounds,
            },
            retry_options=taskqueue.TaskRetryOptions(task_retry_limit=25,
                                                    task_age_limit=14400,
                                                    min_backoff_seconds=15))
            taskqueue.Queue('track').add(task)


class UntrackWorker(BaseHandler):
    """Deferred work when untracking a flight."""
    @ndb.toplevel
    def post(self):
        params = self.request.params
        flight_id = params.get('flight_id')
        uuid = params.get('uuid')
        yield source.untrack_flight(flight_id, uuid=uuid)


class UntrackHandler(AuthenticatedAPIHandler):
    """Handles untracking a specific flight. Usually called when a user is no
    longer tracking a flight and doesn't want to receive future notifications
    for that flight.

    """
    def get(self, flight_id):
        if not utils.is_valid_flight_id(flight_id):
            raise InvalidFlightNumberException(flight_id)

        # FIXME: Assumes iOS device for now
        uuid = self.request.headers.get('X-Just-Landed-UUID')
        assert utils.is_valid_uuid(uuid)

        # Optimization: defer untracking the flight
        task = taskqueue.Task(params = {
            'flight_id' : flight_id,
            'uuid' : uuid,
        })
        taskqueue.Queue('untrack').add(task)
        self.respond({'untracked' : flight_id})

###############################################################################
# Processing Alerts
###############################################################################

class AlertWorker(BaseHandler):
    """Deferred work when handling an alert."""
    @ndb.toplevel
    def post(self):
        # Disable retries, can't risk a flood of alerts
        if int(self.request.headers['X-AppEngine-TaskRetryCount']) > 0:
            return

        # Alert body already been validated in AlertHandler
        alert_body = pickle.loads(self.request.body)
        yield source.process_alert(alert_body, self)


class AlertHandler(BaseAPIHandler):
    """Handles flight alert callbacks from a 3rd party API, potentially
    triggering notifications to users tracking the flight associated with the
    alert.

    """
    def post(self):
        # FIXME: Assumes FlightAware
        # Make sure the POST came from the trusted datasource
        if (source.authenticate_remote_request(self.request)):
            try:
                # Load and decode the utf-8 json bytestring
                unicode_body = unicode(self.request.body, 'utf-8')
                alert_body = json.loads(unicode_body, 'utf-8')
                assert utils.is_valid_fa_alert_body(alert_body)
            except Exception as e:
                logging.exception(e)
                logging.info(self.request.headers)
                logging.info(self.request.body)
                raise InvalidAlertCallbackException()

            # Optimization: defer processing the alert
            content_header = self.request.headers.get('Content-Type') or 'text/plain'

            # FIXME: Ugly hack to introduce a delay in alert processing. This is needed
            # because there is a propagation delay in FlightAware's system that means
            # /FlightInfoEx is not guaranteed to immediately return consistent data after an alert.
            process_time = datetime.utcnow() + timedelta(seconds=10)
            task = taskqueue.Task(headers={'Content-Type': content_header},
                                  payload=pickle.dumps(alert_body),
                                  eta=process_time)
            taskqueue.Queue('process-alert').add(task)
            self.respond({'alert_id' : alert_body.get('alert_id')})
        else:
            logging.error('Unknown user-agent or host posting alert: (%s, %s)',
                            self.request.environ.get('HTTP_USER_AGENT'),
                            self.request.remote_addr)
            self.response.set_status(403) # Forbidden host posting alert