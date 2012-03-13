#!/usr/bin/python

"""models.py: This module defines model classes used by the Just Landed app.

Some of these models are persisted to the GAE datastore, while others exist only
in memory as a way of keeping data organized and providing a clear interface.
"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
from datetime import timedelta, datetime

from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets
import utils

from config import config

FLIGHT_STATES = config['flight_states']
DATA_SOURCES = config['data_sources']
debug_datastore = False

class Airport(ndb.Model):
    """ Model associated with an Airport entity stored in the GAE datastore.

    Fields:
    - `altitude` : The altitude (in feet) the airport is at.
    - `city` : The name of the closest city to the aiport.
    - `country` : The country the airport is in.
    - `dst` : The daylight saving zone the airport is in.
    - `iata_code` : The IATA code associated with the airport.
    - `location` : The location of the airport (lat, long)
    - `name` : The name of the aiport.
    - `timezone_offset` : The timezone offset from GMT where the airport is.

    """
    altitude = ndb.IntegerProperty('alt')
    city = ndb.TextProperty()
    country = ndb.TextProperty()
    dst = ndb.TextProperty()
    iata_code = ndb.StringProperty('iata', required=True)
    location = ndb.GeoPtProperty('loc', required=True)
    name = ndb.TextProperty(required=True)
    timezone_offset = ndb.FloatProperty('tz_off')

    @classmethod
    @ndb.tasklet
    def get_by_icao_code(cls, icao_code):
        if utils.is_valid_icao(icao_code):
            airport_key = ndb.Key(cls, icao_code)
            airport = yield airport_key.get_async()
            raise tasklets.Return(airport)

    @classmethod
    @ndb.tasklet
    def get_by_iata_code(cls, iata_code):
        if utils.is_valid_iata(iata_code):
            qry = cls.query(cls.iata_code == iata_code)
            airport = yield qry.get_async()
            raise tasklets.Return(airport)

    def dict_for_client(self):
        """Returns the Airport as a dictionary suitable for being converted to
        JSON and returned to a client.

        """
        return dict(city=self.city,
                    icaoCode=self.key.string_id(),
                    iataCode=self.iata_code,
                    latitude=utils.round_coord(self.location.lat),
                    longitude=utils.round_coord(self.location.lon),
                    name=utils.proper_airport_name(self.name))


class TrackedFlight(ndb.Model):
    """ Model associated with a flight that is being tracked by Just Landed
    users. Each flight tracked is a unique leg of a potentially multi-leg flight
    with the same tail number. The key of tracked flight is a unique FlightID.

    Intended to be subclassed for each 3rd party flight data API to keep track
    of flights tracked for each datasource.

    Fields:
    - `__key__` : The unique flight_id for the flight.
    - `created` : When the entity was created.
    - `updated` : When the entity was last updated.

    """
    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True)


class FlightAwareTrackedFlight(TrackedFlight):
    """ Subclass of TrackedFlight specialized for the FlightAware datasource.

    Fields:
    - `flight_number` : The flight number computed from the flight_id.
    - `is_tracking` : Whether the flight is still being tracked.

    """
    flight_number = ndb.ComputedProperty(lambda f: utils.flight_num_from_fa_flight_id(f.key.string_id()), 'f_num')
    is_tracking = ndb.BooleanProperty('tracking', default=True)

    @classmethod
    @ndb.tasklet
    def create_or_update_flight(cls, flight_id):
        """Looks up a Flight by flight_id, if it exists, sets is_tracking to
        True. If it doesn't exist, creates a new flight with that flight_id.

        Returns the key of the created/updated flight.

        """
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_key = ndb.Key(cls, flight_id)
        flight = yield flight_key.get_async()

        if flight and flight.is_tracking:
            if debug_datastore:
                logging.info('EXISTING TRACKED FLIGHT: %s' % flight)
            raise tasklets.Return(True)
        else:
            @ndb.transactional
            @ndb.tasklet
            def create_or_update_tracked_flight(flight_exists=False):
                flight = flight_exists and (yield flight_key.get_async())
                if not flight:
                    flight = cls(id=flight_id)
                    if debug_datastore:
                        logging.info('FLIGHT CREATED')
                elif debug_datastore:
                    logging.info('FLIGHT UPDATED')

                flight.is_tracking = True
                flight.put_async()

            create_or_update_tracked_flight(flight is not None)
            raise tasklets.Return(True)

    @classmethod
    @ndb.tasklet
    def tracked_flights(cls):
        q = cls.query(cls.is_tracking == True)
        raise tasklets.Return(q.iter(keys_only=True))

    @classmethod
    @ndb.tasklet
    def count_tracked_flights(cls):
        q = cls.query(cls.is_tracking == True)
        count = yield q.count_async(keys_only=True)
        raise tasklets.Return(count)

    @classmethod
    @ndb.tasklet
    def stop_tracking(cls, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_key = ndb.Key(cls, flight_id)
        @ndb.transactional
        @ndb.tasklet
        def stop_txn():
            flight = yield flight_key.get_async()
            flight.is_tracking = False
            flight.put_async()
        stop_txn()


class FlightAlert(ndb.Model):
    """Model class associated with a push alert that has been registered with
    a 3rd party API. Not intended to be used directly, but rather subclassed.

    Fields:
    - `created` : The date the alert was created.
    - `updated` : The date the alert was last updated.
    - `is_enabled` : Whether the alert is still set.

    """
    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True)
    is_enabled = ndb.BooleanProperty('enabled', default=True)


class FlightAwareAlert(FlightAlert):
    """Model class associated with a FlightAware push alert. Key is the
    alert_id.

    Fields:
    - `flight_number` : The flight (tail) number of the flight associated with this alert.
    """
    flight_number = ndb.StringProperty('f_num', required=True)

    @classmethod
    @ndb.tasklet
    def existing_enabled_alert(cls, flight_num):
        assert isinstance(flight_num, basestring) and utils.valid_flight_number(flight_num)
        q = cls.query(cls.flight_number == flight_num,
                      cls.is_enabled == True)
        alert_key = yield q.get_async(keys_only=True)
        if alert_key:
            raise tasklets.Return(alert_key.integer_id())

    @classmethod
    @ndb.tasklet
    def disable_alert(cls, alert_id):
        assert isinstance(alert_id, (int, long)) and alert_id > 0

        @ndb.transactional
        @ndb.tasklet
        def disable_alert_txn():
            alert_key = ndb.Key(cls, alert_id)
            alert = yield alert_key.get_async()
            if alert:
                alert.is_enabled = False
                alert.put_async()

        disable_alert_txn()
        if debug_datastore:
            logging.info('DISABLED ALERT %d' % alert_id)
        raise tasklets.Return(True)

    @classmethod
    @ndb.tasklet
    def create_alert(cls, alert_id, flight_number):
        assert isinstance(alert_id, (int, long)) and alert_id > 0
        assert isinstance(flight_number, basestring) and utils.valid_flight_number(flight_number)

        @ndb.transactional
        @ndb.tasklet
        def create_alert_txn():
            alert = cls(id=alert_id,
                        flight_number=flight_number)
            alert.put_async()

        create_alert_txn()
        if debug_datastore:
            logging.info('CREATED ALERT %d' % alert_id)
        raise tasklets.Return(True)


class PushNotificationSetting(ndb.Model):
  """Model for a push notification setting (stored as key-value).

  E.g. push_arrived = True

  Represents a single push notification setting that will be associated with
  a specific Device.

  Fields:
  - `name` : The name of the setting.
  - `value` : The value of the setting (True/False)

  """
  name = ndb.StringProperty(required=True)
  value = ndb.BooleanProperty(required=True)


class UserSuppliedFlightNumberMapping(ndb.Model):
    """Model representing a mapping of flight IDs to flight numbers (tail
    numbers) that the user entered. This mapping enables us to recover what
    the user entered when searching for a flight so that notifications to
    that user can be returned using the flight number that they are familiar
    with and yet multiple users can share the same alert under a standardized
    and sanitized flight_num.

    """
    flight_id = ndb.StringProperty(required=True)
    user_flight_num = ndb.StringProperty(required=True)


class _User(ndb.Model):
    """A user/client who is tracking their flights using Just Landed.

    Not intended to be used directly, but rather subclassed.

    Fields:
    - `created` : When the user first tracked a flight.
    - `updated` : When the user was last updated.
    - `banned` : Whether this user has been banned.

    """
    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True)
    banned = ndb.BooleanProperty(default=False)


class iOSUser(_User):
    """An iOS user/client. The key of the user is their UUID, which is unique
    to each device/client. So really, a single person may have multiple users
    in the system - one for each device with Just Landed installed.

    Fields:
    - `tracked_flights` : The flight(s) that the user is currently tracking.
    - `is_tracking_flights` : Whether the user is currently tracking flights.
    - `alerts` : The alert(s) that this user should receive.
    - `has_alerts` : Whether this user has alerterts set.
    - `push_token` : The push token associated with this user.
    - `push_enabled` : Whether this user accepts push notifications.

    """
    tracked_flights = ndb.KeyProperty('flights', repeated=True)
    is_tracking_flights = ndb.ComputedProperty(lambda u: bool(len(u.tracked_flights)), 'is_tracking')
    alerts = ndb.KeyProperty(repeated=True)
    has_alerts = ndb.ComputedProperty(lambda u: bool(len(u.alerts)))
    push_token = ndb.TextProperty()
    push_settings = ndb.StructuredProperty(PushNotificationSetting, repeated=True)
    flight_num_mappings = ndb.StructuredProperty(UserSuppliedFlightNumberMapping, 'f_num_mappings', repeated=True)
    push_enabled = ndb.ComputedProperty(lambda u: bool(len(u.push_token)))

    @classmethod
    @ndb.tasklet
    def get_by_uuid(cls, uuid):
        assert isinstance(uuid, basestring) and len(uuid)
        user_key = ndb.Key(cls, uuid)
        user = yield user_key.get_async()
        raise tasklets.Return(user)

    @classmethod
    def default_settings(cls):
        """Returns a list of the default PushNotificationSettings for an iOS user."""
        settings = []
        # All prefs are True by default
        for push in config['push_types']:
            settings.append(PushNotificationSetting(name=push, value=True))
        return settings

    @classmethod
    @ndb.tasklet
    def track_flight(cls, uuid, flight_id, flight_num, push_token=None,
                     alert_id=None, source=DATA_SOURCES.FlightAware):
        assert isinstance(uuid, basestring) and len(uuid)
        assert isinstance(flight_id, basestring) and len(flight_id)
        assert isinstance(flight_num, basestring) and utils.valid_flight_number(flight_num)

        flight_key = None
        alert_key = None

        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
            if isinstance(alert_id, (int, long)) and alert_id > 0:
                alert_key = ndb.Key(FlightAwareAlert, alert_id)

        assert flight_key

        # See if the user exists
        existing_user = yield cls.get_by_uuid(uuid)

        # Return the user key if it's already up-to-date
        if (existing_user and (flight_key in existing_user.tracked_flights) and
            existing_user.push_token == push_token and
            (alert_key is None or alert_key in existing_user.alerts)):
            if debug_datastore:
                logging.info('USER ALREADY TRACKING %s' % existing_user)
            raise tasklets.Return(True)
        else:
            @ndb.transactional
            @ndb.tasklet
            def create_or_update_user(user_exists=False):
                user = user_exists and (yield cls.get_by_uuid(uuid))
                if not user:
                    user = cls(id=uuid,
                               push_settings=cls.default_settings())
                    if debug_datastore:
                        logging.info('CREATED NEW USER %s' % user)
                elif debug_datastore:
                    logging.info('UPDATING EXISTING USER %s' % user)

                if flight_key not in user.tracked_flights:
                    user.tracked_flights.append(flight_key)
                    mapping = UserSuppliedFlightNumberMapping(flight_id=flight_key.id(),
                                                              user_flight_num=flight_num)
                    user.flight_num_mappings.append(mapping)
                    if debug_datastore:
                        logging.info('USER STARTED TRACKING FLIGHT %s' % flight_key)

                if alert_key and alert_key not in user.alerts:
                    user.alerts.append(alert_key)
                    if debug_datastore:
                        logging.info('USER SUBSCRIBED TO ALERT %s' % alert_key)

                # Only update the push token if we have a new one
                if debug_datastore and push_token != user.push_token:
                    logging.info('USER PUSH TOKEN UPDATED')

                user.push_token = push_token or user.push_token
                user.put_async()

            create_or_update_user(existing_user is not None)
            raise tasklets.Return(True)

    @classmethod
    @ndb.tasklet
    def remove_alert(cls, alert_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(alert_id, (int, long)) and alert_id > 0
        alert_key = None
        if source == DATA_SOURCES.FlightAware:
            alert_key = ndb.Key(FlightAwareAlert, alert_id)
        assert alert_key

        @ndb.transactional
        @ndb.tasklet
        def remove_callback(usr_key):
            usr = yield usr_key.get_async()
            if alert_key in usr.alerts:
                usr.alerts.remove(alert_key)
                if debug_datastore:
                    logging.info('USER UNSUBSCRIBED FROM ALERT %s' % alert_key)
                usr.put_async()

        qry = cls.query(cls.alerts == alert_key)
        qry.map_async(remove_callback, keys_only=True)

    @classmethod
    @ndb.tasklet
    def untrack_flight(cls, uuid, flight_id, alert_id=None, source=DATA_SOURCES.FlightAware):
        assert isinstance(uuid, basestring) and len(uuid)
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_key = None
        alert_key = None
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
            if isinstance(alert_id, (int, long)) and alert_id > 0:
                alert_key = ndb.Key(FlightAwareAlert, alert_id)
        assert flight_key

        @ndb.transactional
        @ndb.tasklet
        def untrack_txn():
            user = yield cls.get_by_uuid(uuid)
            if user:
                # Remove the tracked flight
                if flight_key in user.tracked_flights:
                    user.tracked_flights.remove(flight_key)

                # Remove alert
                if alert_key and alert_key in user.alerts:
                    user.alerts.remove(alert_key)

                # Remove the flight_id to flight_num mapping
                for mapping in user.flight_num_mappings:
                    if mapping.flight_id == flight_key.id():
                        user.flight_num_mappings.remove(mapping)
                user.put_async()
        untrack_txn()

    @classmethod
    @ndb.tasklet
    def alert_in_use(cls, alert_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(alert_id, (int, long)) and alert_id > 0
        if source == DATA_SOURCES.FlightAware:
            alert_key = ndb.Key(FlightAwareAlert, alert_id)
            q = cls.query(cls.alerts == alert_key)
            count = yield q.count_async(limit=1)
            raise tasklets.Return(count > 0)

    @classmethod
    @ndb.tasklet
    def flight_still_tracked(cls, flight_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(flight_id, basestring) and len(flight_id)
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
            q = cls.query(cls.tracked_flights == flight_key)
            count = yield q.count_async(limit=1)
            raise tasklets.Return(count > 0)

    @classmethod
    @ndb.tasklet
    def users_tracking_flight(cls, flight_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(flight_id, basestring) and len(flight_id)
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
            q = cls.query(cls.tracked_flights == flight_key)
            raise tasklets.Return(q.iter(keys_only=True))

    @classmethod
    @ndb.tasklet
    def users_to_notify(cls, alert_id, flight_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(alert_id, (int, long)) and alert_id > 0
        assert isinstance(flight_id, basestring) and len(flight_id)
        if source == DATA_SOURCES.FlightAware:
            alert_key = ndb.Key(FlightAwareAlert, alert_id)
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)

            q = cls.query(cls.tracked_flights == flight_key,
                          cls.alerts == alert_key,
                          cls.push_enabled == True)
            # Returns an iterator
            raise tasklets.Return(q.iter(batch_size=50))

    @classmethod
    @ndb.tasklet
    def count_users_tracking(cls):
        q = cls.query(cls.is_tracking_flights == True)
        count = yield q.count_async(keys_only=True)
        raise tasklets.Return(count)

    def wants_notification_type(self, push_type):
        assert push_type
        for setting in self.push_settings:
            if setting.name == push_type and setting.value == True:
                return True
        return False

    def flight_num_for_flight_id(self, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        for mapping in self.flight_num_mappings:
            if mapping.flight_id == flight_id:
                return mapping.user_flight_num


class Origin(object):
    """Container class for a flight origin being returned by the Just Landed API"""
    def __init__(self, origin_info):
        if isinstance(origin_info, dict):
            self._data = origin_info
        else:
            self._data = {}

    @property
    def iata_code(self):
        return self._data.get('iataCode')

    @iata_code.setter
    def iata_code(self, value):
        self._data['iataCode'] = value

    @property
    def icao_code(self):
        return self._data.get('icaoCode')

    @icao_code.setter
    def icao_code(self, value):
        self._data['icaoCode'] = value

    @property
    def city(self):
        return self._data.get('city')

    @city.setter
    def city(self, value):
        self._data['city'] = value

    @property
    def name(self):
        return self._data.get('name')

    @name.setter
    def name(self, value):
        self._data['name'] = value

    @property
    def latitude(self):
        return self._data.get('latitude')

    @latitude.setter
    def latitude(self, value):
        self._data['latitude'] = value

    @property
    def longitude(self):
        return self._data.get('longitude')

    @longitude.setter
    def longitude(self, value):
        self._data['longitude'] = value

    @property
    def terminal(self):
        return self._data.get('terminal').upper().strip()

    @property
    def best_name(self):
        """Returns city, then name, falling back to iata_code, falling back to icao_code"""
        return self.name or self.iata_code or self.icao_code

    @terminal.setter
    def terminal(self, value):
        self._data['terminal'] = value

    def dict_for_client(self):
        info = {}
        info.update(self._data)
        return info


class Destination(Origin):
    """Container class for a flight destination being returned by the Just Landed API"""
    @property
    def bag_claim(self):
        return self._data.get('bagClaim')

    @bag_claim.setter
    def bag_claim(self, value):
        self._data['bagClaim'] = value


class Flight(object):
    """Container class for a flight being returned by the Just Landed API"""

    def __init__(self, flight_info):
        if isinstance(flight_info, dict):
            self._data = flight_info
        else:
            self._data = {}

    @property
    def aircraft_type(self):
        return self._data.get('aircraftType')

    @aircraft_type.setter
    def aircraft_type(self, value):
        self._data['aircraftType'] = value

    @property
    def actual_arrival_time(self):
        return self._data.get('actualArrivalTime')

    @actual_arrival_time.setter
    def actual_arrival_time(self, value):
        self._data['actualArrivalTime'] = value

    @property
    def actual_departure_time(self):
        return self._data.get('actualDepartureTime')

    @actual_departure_time.setter
    def actual_departure_time(self, value):
        self._data['actualDepartureTime'] = value

    @property
    def destination(self):
        return self._data.get('destination')

    @destination.setter
    def destination(self, value):
        self._data['destination'] = value

    @property
    def diverted(self):
        return self._data.get('diverted')

    @diverted.setter
    def diverted(self, value):
        self._data['diverted'] = value

    @property
    def estimated_arrival_time(self):
        return self._data.get('estimatedArrivalTime')

    @estimated_arrival_time.setter
    def estimated_arrival_time(self, value):
        self._data['estimatedArrivalTime'] = value

    @property
    def flight_id(self):
        return self._data.get('flightID')

    @flight_id.setter
    def flight_id(self, value):
        self._data['flightID'] = value

    @property
    def flight_number(self):
        return self._data.get('flightNumber')

    @flight_number.setter
    def flight_number(self, value):
        self._data['flightNumber'] = value

    @property
    def last_updated(self):
        return self._data.get('lastUpdated')

    @last_updated.setter
    def last_updated(self, value):
        self._data['lastUpdated'] = value

    @property
    def origin(self):
        return self._data.get('origin')

    @origin.setter
    def origin(self, value):
        self._data['origin'] = value

    @property
    def scheduled_departure_time(self):
        return self._data.get('scheduledDepartureTime')

    @scheduled_departure_time.setter
    def scheduled_departure_time(self, value):
        self._data['scheduledDepartureTime'] = value

    @property
    def scheduled_flight_duration(self):
        return self._data.get('scheduledFlightDuration')

    @scheduled_flight_duration.setter
    def scheduled_flight_duration(self, value):
        self._data['scheduledFlightDuration'] = value

    @property
    def est_arrival_diff_from_schedule(self):
        return (self.estimated_arrival_time -
            (self.scheduled_departure_time + self.scheduled_flight_duration))

    @property
    def status(self):
        if self.actual_departure_time == 0:
            # See if it has missed its take-off time
            if utils.timestamp(datetime.utcnow()) > self.scheduled_departure_time:
                time_diff = (self.estimated_arrival_time -
                (self.scheduled_departure_time + self.scheduled_flight_duration))
                if time_diff > config['on_time_buffer']:
                    return FLIGHT_STATES.DELAYED
                else:
                    return FLIGHT_STATES.SCHEDULED
            else:
                return FLIGHT_STATES.SCHEDULED
        elif self.diverted:
            return FLIGHT_STATES.DIVERTED
        elif self.actual_departure_time == -1:
            return FLIGHT_STATES.CANCELED
        elif self.actual_arrival_time > 0:
            return FLIGHT_STATES.LANDED
        else:
            time_diff = self.est_arrival_diff_from_schedule
            time_buff = config['on_time_buffer']
            if abs(time_diff) < time_buff:
                return FLIGHT_STATES.ON_TIME
            elif time_diff < 0:
                return FLIGHT_STATES.EARLY
            else:
                return FLIGHT_STATES.DELAYED

    @property
    def detailed_status(self):
        status = self.status

        if status == FLIGHT_STATES.SCHEDULED:
            interval = (self.scheduled_departure_time + self.scheduled_flight_duration
                        - utils.timestamp(datetime.utcnow()))
            return 'Scheduled to arrive in %s.' % utils.pretty_time_interval(interval)
        elif status == FLIGHT_STATES.LANDED:
            interval = utils.timestamp(datetime.utcnow()) - self.actual_arrival_time
            return 'Landed %s ago.' % utils.pretty_time_interval(interval)
        elif status == FLIGHT_STATES.CANCELED:
            return 'Flight canceled.'
        elif status == FLIGHT_STATES.DIVERTED:
            return 'Flight diverted to another airport.'
        else:
            interval = (self.estimated_arrival_time - utils.timestamp(datetime.utcnow()))
            if interval > 0:
                return 'Arrives in %s.' % utils.pretty_time_interval(interval)
            else:
                # Estimated arrival time is before now, arrival is imminent
                return 'Arriving shortly'

    @property
    def is_old_flight(self):
        arrival_timestamp = self.actual_arrival_time
        arrival_time = datetime.utcfromtimestamp(arrival_timestamp)
        est_arrival_time = datetime.utcfromtimestamp(self.estimated_arrival_time)
        hours_ago = datetime.utcnow() - timedelta(hours=config['flight_old_hours'])
        return ((arrival_timestamp > 0 and arrival_time < hours_ago) or
                est_arrival_time < hours_ago)

    @property
    def is_in_flight(self):
        return (self.actual_departure_time > 0 and
                self.actual_arrival_time == 0)

    @property
    def has_landed(self):
        return self.actual_arrival_time > 0

    @property
    def leave_for_airport_time(self):
        return self._data.get('leaveForAirportTime')

    @leave_for_airport_time.setter
    def leave_for_airport_time(self, value):
        self._data['leaveForAirportTime'] = value

    def set_driving_time(self, driving_time):
        self.leave_for_airport_time = self.estimated_arrival_time - driving_time

    def dict_for_client(self):
        info = utils.sub_dict_select(self._data, config['flight_fields'])
        info['origin'] = self.origin.dict_for_client()
        info['destination'] = self.destination.dict_for_client()
        info['status'] = self.status
        info['detailedStatus'] = self.detailed_status
        return info