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

import reporting
from reporting import prodeagle_counter

FLIGHT_STATES = config['flight_states']
DATA_SOURCES = config['data_sources']
debug_datastore = False
reminder_types = config['reminder_types']

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
    - `num_users_tracking` : The number of users currently tracking a flight.
    - `flight_number` : The flight number computed from the flight_id.
    - `is_tracking` : Whether the flight is still being tracked.
    - `last_flight_data` : The last flight data we have.
    - `orig_departure_time` : The original departure time as far as we know.
    - `orig_flight_duration` : The original flight duration as far as we know.
    """
    num_users_tracking = ndb.IntegerProperty('num_u', default=0)
    flight_number = ndb.ComputedProperty(lambda f: utils.flight_num_from_fa_flight_id(f.key.string_id()), 'f_num')
    is_tracking = ndb.ComputedProperty(lambda f: f.num_users_tracking > 0)
    last_flight_data = ndb.JsonProperty(required=True)
    orig_departure_time = ndb.IntegerProperty(required=True)
    orig_flight_duration = ndb.IntegerProperty(required=True)

    @classmethod
    @ndb.tasklet
    def get_flight_by_id(cls, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_key = ndb.Key(cls, flight_id)
        flight = yield flight_key.get_async()
        raise tasklets.Return(flight)

    @classmethod
    @ndb.tasklet
    def create_flight(cls, flight):
        assert isinstance(flight, Flight)
        new_flight = yield cls(id=flight.flight_id,
                               orig_departure_time=flight.scheduled_departure_time,
                               orig_flight_duration=flight.scheduled_flight_duration,
                               last_flight_data=flight.to_dict()).put_async()
        raise tasklets.Return(new_flight)

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

    def update_last_flight_data(self, flight_data):
        @ndb.tasklet
        def update():
            self.last_flight_data = flight_data
            yield self.put_async()
        yield update()


class FlightAlert(ndb.Model):
    """Model class associated with a push alert that has been registered with
    a 3rd party API. Not intended to be used directly, but rather subclassed.

    Fields:
    - `created` : The date the alert was created.
    - `updated` : The date the alert was last updated.

    """
    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True)


class FlightAwareAlert(FlightAlert):
    """Model class associated with a FlightAware push alert. Key is the
    flight number.

    Fields:
    - `alert_id` : The id of the alert in the FlightAware system.
    - `is_enabled` : Whether the alert is still set.
    """
    num_users_with_alert = ndb.IntegerProperty('num_u', default=0)
    alert_id = ndb.IntegerProperty(required=True)
    is_enabled = ndb.ComputedProperty(lambda a: a.num_users_with_alert > 0)

    @classmethod
    @ndb.tasklet
    def get_by_flight_id(cls, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_num = utils.flight_num_from_fa_flight_id(flight_id)
        assert utils.valid_flight_number(flight_num)
        alert = yield ndb.Key(cls, flight_num).get_async()
        raise tasklets.Return(alert)

    @classmethod
    @ndb.tasklet
    def get_by_alert_id(cls, alert_id):
        assert isinstance(alert_id, (int, long)) and alert_id > 0
        q = cls.query(cls.alert_id == alert_id)
        alert = yield q.get_async()
        raise tasklets.Return(alert)

    @classmethod
    @ndb.tasklet
    def create_or_reuse_alert(cls, flight_id, alert_id):
        assert isinstance(alert_id, (int, long)) and alert_id > 0
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_num = utils.flight_num_from_fa_flight_id(flight_id)
        assert isinstance(flight_num, basestring) and utils.valid_flight_number(flight_num)

        alert = yield ndb.Key(cls, flight_num).get_async()

        if not alert:
            # Create alert in DB
            alert = cls(id=flight_num,
                        alert_id=alert_id)
            if debug_datastore:
                logging.info('CREATED ALERT %s, %d' % (flight_num, alert_id))
        else:
            # Previous alert existed for flight_num, recycle it with new alert_id
            alert.alert_id = alert_id
            alert.num_users_with_alert = 0
            if debug_datastore:
                logging.info('RECYCLED ALERT %s, %d' % (flight_num, alert_id))

        yield alert.put_async()
        raise tasklets.Return(alert)

    @ndb.tasklet
    def disable(self):
        if self.is_enabled: # Optimization
            self.num_users_with_alert = 0
            yield self.put_async()


class FlightReminder(ndb.Model):
    """Model for a reminder telling a user to leave for the airport.

    Fields:
    - `created` : The date the reminder was created.
    - `updated` : The date the reminder was last updated.
    - `fire_time` : The date and time when the reminder should be sent.
    - `reminder_type` : The type of the reminder.
    - `sent` : Whether the reminder has been sent or not.
    - `body` : The body of the reminder.
    - `flight` : The flight this reminder is associated with.
    """
    created = ndb.DateTimeProperty(auto_now_add=True)
    updated = ndb.DateTimeProperty(auto_now=True)
    fire_time = ndb.DateTimeProperty(required=True)
    reminder_type = ndb.StringProperty('type', choices=[reminder_types.LEAVE_SOON, reminder_types.LEAVE_NOW],
                                       required=True)
    sent = ndb.BooleanProperty(default=False)
    body = ndb.TextProperty(required=True)
    flight = ndb.KeyProperty(required=True)


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


class UserTrackedFlight(ndb.Model):
    """Model representing a flight that a user is tracking.

    Fields:
    - `flight` : The flight being tracked.
    - `user_flight_num` : The flight number the user entered to find this flight.
    """
    flight = ndb.KeyProperty(required=True)
    flight_id = ndb.StringProperty(required=True)
    user_flight_num = ndb.StringProperty('u_f_num', required=True)


class iOSUser(_User):
    """An iOS user/client. The key of the user is their UUID, which is unique
    to each device/client. So really, a single person may have multiple users
    in the system - one for each device with Just Landed installed.

    Fields:
    - `last_known_location` : The user's last known location.
    - `has_location` : Whether we know the user's last known location.
    - `tracked_flights` : The flight(s) that the user is currently tracking.
    - `is_tracking_flights` : Whether the user is currently tracking flights.
    - `alerts` : The flight alert(s) that this user should receive.
    - `has_alerts` : Whether this user has alerts set.
    - `reminders` : The flight reminders that are set for this user.
    - `has_reminders` : Whether this user has reminders set.
    - `has_unsent_reminders` : Whether this user has unsent reminders.
    - `push_token` : The push token associated with this user.
    - `push_settings` : The push notification settings for this user.
    - `push_enabled` : Whether this user accepts push notifications.

    """
    last_known_location = ndb.GeoPtProperty('last_loc')
    has_location = ndb.ComputedProperty(lambda u: bool(u.last_known_location))
    tracked_flights = ndb.StructuredProperty(UserTrackedFlight, 'flights', repeated=True)
    is_tracking_flights = ndb.ComputedProperty(lambda u: bool(len(u.tracked_flights)), 'is_tracking')
    alerts = ndb.KeyProperty(repeated=True)
    has_alerts = ndb.ComputedProperty(lambda u: bool(len(u.alerts)))
    reminders = ndb.StructuredProperty(FlightReminder, repeated=True)
    has_reminders = ndb.ComputedProperty(lambda u: bool(len(u.reminders)))
    has_unsent_reminders = ndb.ComputedProperty(lambda u: bool([r for r in u.reminders if r.sent == False]))
    push_token = ndb.TextProperty()
    push_settings = ndb.StructuredProperty(PushNotificationSetting, repeated=True)
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
    def track_flight(cls, uuid, flight, user_latitude=None, user_longitude=None,
                     driving_time=None, push_token=None, alert=None,
                     source=DATA_SOURCES.FlightAware):
        assert isinstance(uuid, basestring) and len(uuid)
        assert isinstance(flight, Flight)
        flight_id = flight.flight_id
        flight_num = flight.flight_number
        flight_key = None

        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)

        assert flight_key

        # See if the user exists
        existing_user = yield cls.get_by_uuid(uuid)

        # Return the user key if it's already up-to-date
        if (existing_user and existing_user.is_tracking_flight(flight_id) and
            existing_user.location_is_current(user_latitude, user_longitude) and
            existing_user.push_token == push_token and
            (alert is None or alert.key in existing_user.alerts)):
            if debug_datastore:
                logging.info('USER ALREADY TRACKING %s' % existing_user)
            raise tasklets.Return(existing_user)
        else:
            to_put = []
            user = existing_user
            if not user:
                user = cls(id=uuid,
                           push_settings=cls.default_settings())
                prodeagle_counter.incr(reporting.NEW_USER)
                if debug_datastore:
                    logging.info('CREATED NEW USER %s' % user)
            elif debug_datastore:
                logging.info('UPDATING EXISTING USER %s' % user)

            # Update the user's location
            if user_latitude and user_longitude:
                user.last_known_location = ndb.GeoPt(user_latitude, lon=user_longitude)

            if not user.is_tracking_flight(flight_id):
                user.add_tracked_flight(flight_id, flight_num, source=source)
                tracked_flight = yield flight_key.get_async()
                tracked_flight.num_users_tracking += 1
                to_put.append(tracked_flight.put_async())

                if debug_datastore:
                    logging.info('USER STARTED TRACKING FLIGHT %s' % flight_key)

            if alert and alert.key not in user.alerts:
                user.alerts.append(alert.key)
                alert.num_users_with_alert += 1
                to_put.append(alert.put_async())
                if debug_datastore:
                    logging.info('USER SUBSCRIBED TO ALERT %s' % alert.alert_id)

            if debug_datastore and push_token != user.push_token:
                logging.info('USER PUSH TOKEN UPDATED')

            # Only update the push token if we have a new one
            user.push_token = push_token or user.push_token

            if driving_time is not None:
                user.set_or_update_flight_reminders(flight, driving_time, source=source)

            to_put.append(user.put_async())
            yield to_put # Parallel yield
            raise tasklets.Return(user)


    @classmethod
    @ndb.tasklet
    def clear_alert_from_users(cls, alert):
        assert isinstance(alert, ndb.Model)
        alert_key = alert.key

        @ndb.tasklet
        @ndb.transactional
        def remove_alert(u):
            if alert_key in u.alerts: # Optimization
                u.alerts.remove(alert_key)
                yield u.put_async()
        qry = cls.query(cls.alerts == alert_key)
        yield qry.map_async(remove_alert)

    @classmethod
    @ndb.tasklet
    def untrack_flight(cls, uuid, flight_id, alert=None, source=DATA_SOURCES.FlightAware):
        assert isinstance(uuid, basestring) and len(uuid)
        assert isinstance(flight_id, basestring) and len(flight_id)

        user = yield cls.get_by_uuid(uuid)

        if user:
            flight = None
            to_put = []

            if source == DATA_SOURCES.FlightAware:
                flight = yield FlightAwareTrackedFlight.get_flight_by_id(flight_id)

            # Remove the tracked flight
            if user.is_tracking_flight(flight_id):
                user.remove_tracked_flight(flight_id)
                if flight and flight.num_users_tracking > 0:
                    flight.num_users_tracking -= 1
                    to_put.append(flight.put_async())

            if alert and alert.key in user.alerts:
                # EDGE CASE: User could be tracking several different flights with same ident
                # => Remove alert from the user only if no other flight they are tracking needs it
                # Find out if the alert is still needed by any other flights they are tracking
                needs_alert = False
                if source == DATA_SOURCES.FlightAware:
                    for f in user.tracked_flights: # They could be tracking
                        # Only interested in FlightAware flights
                        if f.flight == ndb.Key(FlightAwareTrackedFlight, f.flight_id):
                            if (utils.flight_num_from_fa_flight_id(flight_id) ==
                                utils.flight_num_from_fa_flight_id(f.flight_id)):
                                needs_alert = True
                                break

                if not needs_alert:
                    user.alerts.remove(alert.key)
                    if alert.num_users_with_alert > 0:
                        alert.num_users_with_alert -= 1
                        to_put.append(alert.put_async())

            # Remove reminders
            user.remove_flight_reminders(flight_id, source=source)
            to_put.append(user.put_async())

            # Parallel yield
            yield to_put
            raise tasklets.Return((flight, alert))

    @classmethod
    @ndb.tasklet
    def users_tracking_flight(cls, flight_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(flight_id, basestring) and len(flight_id)
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
            q = cls.query(cls.tracked_flights.flight == flight_key)
            raise tasklets.Return(q.iter(keys_only=True))

    @classmethod
    @ndb.tasklet
    def users_to_notify(cls, alert, flight_id, source=DATA_SOURCES.FlightAware):
        assert isinstance(alert, ndb.Model)
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_key = None
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)

        assert flight_key
        q = cls.query(cls.tracked_flights.flight == flight_key,
                      cls.alerts == alert.key,
                      cls.push_enabled == True)
        # Returns an iterator
        raise tasklets.Return(q.iter())

    @classmethod
    @ndb.tasklet
    def users_with_overdue_reminders(cls):
        q = cls.query(cls.has_unsent_reminders == True,
                      cls.push_enabled == True,
                      cls.reminders.fire_time < datetime.utcnow())
        raise tasklets.Return(q.iter(keys_only=True))

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
        for f in self.tracked_flights:
            if f.flight_id == flight_id:
                return f.user_flight_num

    def is_tracking_flight(self, flight_id):
        for f in self.tracked_flights:
            if f.flight_id == flight_id:
                return True
        return False

    def add_tracked_flight(self, flight_id, flight_num, source=DATA_SOURCES.FlightAware):
        flight_key = None
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)

        assert flight_key
        assert isinstance(flight_id, basestring) and len(flight_id)
        assert utils.valid_flight_number(flight_num)

        new_flight = UserTrackedFlight(flight=flight_key,
                                       flight_id=flight_id,
                                       user_flight_num=flight_num)
        self.tracked_flights.append(new_flight)

    def remove_tracked_flight(self, flight_id):
        to_remove = []
        for f in self.tracked_flights:
            if f.flight_id == flight_id:
                to_remove.append(f)
        for f in to_remove:
            self.tracked_flights.remove(f)

    def get_reminders_for_flight(self, flight_id, source=DATA_SOURCES.FlightAware):
        flight_key = None
        matches = []
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
        assert flight_key

        for r in self.reminders:
            if r.flight == flight_key:
                matches.append(r)
        return matches

    def location_is_current(self, latitude, longitude):
        loc = self.last_known_location
        if loc is None and latitude is None and longitude is None:
            return True
        elif loc is None and latitude is not None:
            return False
        else:
            return loc.lat == latitude and loc.lon == longitude

    def get_unsent_reminders(self):
        unsent = []
        for r in self.reminders:
            if r.sent == False:
                unsent.append(r)
        return unsent

    def remove_flight_reminders(self, flight_id, source=DATA_SOURCES.FlightAware):
        flight_key = None
        if source == DATA_SOURCES.FlightAware:
            flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id)
        assert flight_key
        to_remove = []
        for r in self.reminders:
            if r.flight == flight_key:
                to_remove.append(r)
        for r in to_remove:
            self.reminders.remove(r)

    def set_or_update_flight_reminders(self, flight, driving_time, source=DATA_SOURCES.FlightAware):
        assert isinstance(driving_time, (int, long))
        assert isinstance(flight, Flight)
        reminders = self.get_reminders_for_flight(flight.flight_id, source=source)
        flight_num = self.flight_num_for_flight_id(flight.flight_id)
        dest_terminal = flight.destination.terminal
        dest_name = (flight.destination.name or flight.destination.iata_code or
                    flight.destination.icao_code)
        leave_soon_interval = config['leave_soon_seconds_before']
        leave_soon_pretty_interval = utils.pretty_time_interval(leave_soon_interval, round_days=True)
        now = datetime.utcnow()

        # Figure out the reminder bodies
        leave_soon_body = None
        leave_now_body = None
        if dest_terminal and dest_terminal == 'I':
            leave_soon_body = 'Leave for %s in %s. Flight %s arrives at the international terminal.' % (
                                dest_name, leave_soon_pretty_interval, flight_num)
            leave_now_body = 'Leave now for %s. Flight %s arrives at the international terminal.' % (
                                dest_name, flight_num)
        elif dest_terminal:
            leave_soon_body = 'Leave for %s in %s. Flight %s arrives at terminal %s.' % (
                                dest_name, leave_soon_pretty_interval, flight_num, dest_terminal)
            leave_now_body = 'Leave now for %s. Flight %s arrives at terminal %s.' % (
                                dest_name, flight_num, dest_terminal)
        else:
            leave_soon_body = 'Leave for %s in %s. Flight %s arrives soon.' % (
                                dest_name, leave_soon_pretty_interval, flight_num)
            leave_now_body = 'Leave now for %s. Flight %s arrives soon.' % (
                                dest_name, flight_num)

        # Calculate the reminder times
        leave_soon_time = utils.leave_soon_time(flight.estimated_arrival_time, driving_time)
        leave_now_time = utils.leave_now_time(flight.estimated_arrival_time, driving_time)

        # If they have no reminders for this flight, set them (even if they were supposed to fire in the past)
        if not reminders:
            flight_key = None
            if source == DATA_SOURCES.FlightAware:
                flight_key = ndb.Key(FlightAwareTrackedFlight, flight.flight_id)
            assert flight_key
            # Set a leave soon reminder
            leave_soon = FlightReminder(created=now,
                                        updated=now,
                                        fire_time=leave_soon_time,
                                        reminder_type=reminder_types.LEAVE_SOON,
                                        flight=flight_key,
                                        body=leave_soon_body)

            # Set a leave now reminder
            leave_now = FlightReminder(created=now,
                                       updated=now,
                                       fire_time=leave_now_time,
                                       reminder_type=reminder_types.LEAVE_NOW,
                                       flight=flight_key,
                                       body=leave_now_body)

            self.reminders.extend([leave_soon, leave_now])
        else:
            for r in reminders:
                # Only update unsent reminders (stops reminders from being sent twice)
                if r.sent == False:
                    r.updated = now
                    if r.reminder_type == reminder_types.LEAVE_SOON:
                        r.fire_time = leave_soon_time
                        r.body = leave_soon_body
                    else:
                        r.fire_time = leave_now_time
                        r.body = leave_now_body


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
        return self._data.get('terminal')

    @property
    def best_name(self):
        """Returns city, then name, falling back to iata_code, falling back to icao_code"""
        return self.name or self.iata_code or self.icao_code

    @terminal.setter
    def terminal(self, value):
        self._data['terminal'] = value.upper().strip()

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

    @classmethod
    def from_dict(cls, flight_dict):
        assert isinstance(flight_dict, dict)
        f = cls(flight_dict)
        assert isinstance(f.flight_id, basestring) and len(f.flight_id)
        assert utils.valid_flight_number(f.flight_number)
        f.origin = Origin(flight_dict.get('origin'))
        f.destination = Destination(flight_dict.get('destination'))
        return f

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
    def scheduled_arrival_time(self):
        return self.scheduled_departure_time + self.scheduled_flight_duration

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
        self.leave_for_airport_time = (self.estimated_arrival_time +
            config['touchdown_to_terminal'] - driving_time)

    def to_dict(self):
        info = utils.sub_dict_select(self._data, config['flight_fields'])
        info['origin'] = self.origin.dict_for_client()
        info['destination'] = self.destination.dict_for_client()
        return info

    def dict_for_client(self):
        info = self.to_dict()
        info['status'] = self.status
        info['detailedStatus'] = self.detailed_status
        return info