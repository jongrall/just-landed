#!/usr/bin/env python

"""models.py: This module defines model classes used by the Just Landed app.

Some of these models are persisted to the GAE datastore, while others exist only
in memory as a way of keeping data organized and providing a clear interface.
"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import logging
from datetime import timedelta, datetime

# Optimization : extensive use of NDB and tasklets to improve concurrency and
# performance of datastore operations.
from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets

from config import config, on_development
import utils

FLIGHT_STATES = config['flight_states']
REMINDER_TYPES = config['reminder_types']
PUSH_SETTINGS = config['push_settings']

# Set to true to log informational messages about datastore operations
debug_datastore = on_development() and False

# Optimization: indexed=False is set for most datastore properties to improve
# write performance of entities. Also, short names are set to reduce space
# used by property names in the datastore.

class Airport(ndb.Model):
    """ Model associated with an Airport entity stored in the GAE datastore.

    Fields:
    - `__key__` : The ICAO code associated with the airport.
    - `altitude` : The altitude (in feet) the airport is at.
    - `city` : The name of the closest city to the aiport.
    - `country` : The country the airport is in.
    - `dst` : The daylight saving zone the airport is in.
    - `iata_code` : The IATA code associated with the airport.
    - `location` : The location of the airport (lat, long)
    - `name` : The name of the aiport.
    - `timezone_name` : The standard name of the timezone.
    - `timezone_offset` : The timezone offset from GMT where the airport is.

    """
    altitude = ndb.IntegerProperty('alt')
    city = ndb.TextProperty()
    country = ndb.TextProperty()
    dst = ndb.TextProperty()
    iata_code = ndb.StringProperty('iata', required=True)
    location = ndb.GeoPtProperty('loc', required=True, indexed=False)
    name = ndb.TextProperty(required=True)
    timezone_name = ndb.TextProperty('tz')
    timezone_offset = ndb.FloatProperty('tz_off', indexed=False)

    @classmethod
    @ndb.tasklet
    def get_by_icao_code(cls, icao_code):
        airport_key = ndb.Key(cls, icao_code)
        airport = yield airport_key.get_async()
        raise tasklets.Return(airport)

    @classmethod
    @ndb.tasklet
    def get_by_iata_code(cls, iata_code):
        qry = cls.query(cls.iata_code == iata_code)
        airport = yield qry.get_async()
        raise tasklets.Return(airport)

    def dict_for_client(self):
        """Returns the Airport as a dictionary suitable for being converted to
        JSON and returned to a client.

        """
        return dict(city=self.city,
                    country=self.country,
                    altitude=self.altitude,
                    icaoCode=self.key.string_id(),
                    iataCode=self.iata_code,
                    latitude=utils.round_coord(self.location.lat),
                    longitude=utils.round_coord(self.location.lon),
                    timezone=self.timezone_name,
                    name=utils.proper_airport_name(self.name))


class FlightReminder(ndb.Model):
    """Model for a reminder telling a user to leave for the airport.

    Fields:
    - `fire_time` : The date and time when the reminder should be sent.
    - `reminder_type` : The type of the reminder.
    - `sent` : Whether the reminder has been sent or not.
    - `body` : The body of the reminder.
    """
    fire_time = ndb.DateTimeProperty(required=True)
    reminder_type = ndb.StringProperty('type', choices=[REMINDER_TYPES.LEAVE_SOON, REMINDER_TYPES.LEAVE_NOW],
                                       required=True, indexed=False)
    sent = ndb.BooleanProperty(default=False, indexed=False)
    body = ndb.TextProperty(required=True)


class _TrackedFlight(ndb.Model):
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


class FlightAwareTrackedFlight(_TrackedFlight):
    """ Subclass of _TrackedFlight specialized for the FlightAware datasource.

    Fields:
    - `last_flight_data` : The last flight data we have.
    - `orig_departure_time` : The original departure time as far as we know.
    - `orig_flight_duration` : The original flight duration as far as we know.
    - `alert_id` : The id of the FlightAware alert set for this flight.
    - `user_flight_num` : The flight number the user entered to find this flight.
    - `reminders` : The reminders that are set for this flight.
    - `has_unsent_reminders` : Whether this user has unsent reminders.
    - `reminder_lead_time` : The number of seconds before it is time to leave that the
                             first reminder is sent.
    """
    last_flight_data = ndb.JsonProperty('data', required=True)
    orig_departure_time = ndb.IntegerProperty('orig_dep', required=True, indexed=False)
    orig_flight_duration = ndb.IntegerProperty('orig_dur', required=True, indexed=False)
    alert_id = ndb.IntegerProperty('alert', default=0)
    user_flight_num = ndb.StringProperty('u_f_num', required=True)
    reminders = ndb.StructuredProperty(FlightReminder, repeated=True)
    has_unsent_reminders = ndb.ComputedProperty(lambda f: bool([r for r in f.reminders if r.sent == False]))
    reminder_lead_time = ndb.IntegerProperty('lead_time', default=config['leave_soon_seconds_before'], indexed=False)

    @classmethod
    def _get_kind(cls):
        return 'FlightAwareTrackedFlight_v2' # Versioned model kind

    @classmethod
    def create(cls, parent, flight, alert_id, driving_time=None, reminder_lead_time=None):
        assert isinstance(parent, ndb.Key)
        assert isinstance(flight, Flight)
        assert isinstance(alert_id, (int, long))
        new_flight = cls(id=flight.flight_id,
                         parent=parent,
                         last_flight_data=flight.to_dict(),
                         orig_departure_time=flight.scheduled_departure_time,
                         orig_flight_duration=flight.scheduled_flight_duration,
                         alert_id=alert_id,
                         user_flight_num=flight.flight_number)

        # If we have a reminder lead time specified, store it
        if reminder_lead_time:
            new_flight.reminder_lead_time = reminder_lead_time

        # If we have driving time, update their reminders
        if driving_time is not None:
            new_flight.set_or_update_flight_reminders(flight, driving_time)

        if debug_datastore:
            logging.info('USER %s STARTED TRACKING FLIGHT %s' % (parent.string_id(), flight.flight_id))
            logging.info('USER SUBSCRIBED TO ALERT %s' % alert_id)

        return new_flight

    @classmethod
    @ndb.tasklet
    def get_by_flight_id_alert_id(cls, flight_id, alert_id):
        assert utils.is_valid_fa_flight_id(flight_id)
        q = cls.query(cls.alert_id == int(alert_id))
        qit = q.iter()
        orphaned_alert = True
        while (yield qit.has_next_async()):
            next_flight = qit.next()
            orphaned_alert = False
            if next_flight.key.string_id() == flight_id:
                raise tasklets.Return(next_flight)
        if orphaned_alert:
            logging.info('ORPHANED ALERT %d' % alert_id)

    @classmethod
    @ndb.tasklet
    def all_flight_keys(cls):
        q = cls.query()
        qit = q.iter(keys_only=True)
        keys = []
        while (yield qit.has_next_async()):
            keys.append(qit.next())
        raise tasklets.Return(keys)

    @classmethod
    @ndb.tasklet
    def all_users_tracking(cls):
        flight_keys = yield cls.all_flight_keys()
        user_ids = list(set([k.parent().string_id() for k in flight_keys]))
        raise tasklets.Return(user_ids)

    @classmethod
    @ndb.tasklet
    def all_tracked_flight_ids(cls):
        flight_keys = yield cls.all_flight_keys()
        flight_ids = list(set([k.string_id() for k in flight_keys]))
        raise tasklets.Return(flight_ids)

    @classmethod
    @ndb.tasklet
    def flight_ids_tracked_by_user(cls, user_key):
        assert isinstance(user_key, ndb.Key)
        q = cls.query(ancestor=user_key)
        @ndb.tasklet
        def cbk(flight_key):
            raise tasklets.Return(flight_key.string_id())
        flight_ids = yield q.map_async(cbk, keys_only=True)
        raise tasklets.Return(flight_ids)

    @classmethod
    @ndb.tasklet
    def old_flight_keys(cls):
        maybe_old = []
        definitely_old = []
        q = cls.query()
        qit = q.iter()
        while (yield qit.has_next_async()):
            flight_ent = qit.next()
            flight_key = flight_ent.key
            try:
                flight = Flight.from_dict(flight_ent.last_flight_data)
                if flight.is_old_flight:
                    definitely_old.append(flight_key)
                else:
                    maybe_old.append(flight_key)
            except Exception as e: # Catch exceptions when parsing last_flight_data
                maybe_old.append(flight_key)

        # Some flights will have newer last_flight_data, be more precise about what is old
        old_flight_ids = set([f_key.string_id() for f_key in definitely_old])
        definitely_old.extend([f_key for f_key in maybe_old if f_key.string_id() in old_flight_ids])
        maybe_old = [f_key for f_key in maybe_old if f_key.string_id() not in old_flight_ids]
        raise tasklets.Return(definitely_old, maybe_old)

    @classmethod
    @ndb.tasklet
    def flight_alert_in_use(cls, alert_id):
        q = cls.query(cls.alert_id == alert_id)
        count = yield q.count_async(limit=1)
        if count > 0:
            raise tasklets.Return(True)
        else:
            raise tasklets.Return(False)

    @classmethod
    def flights_with_overdue_reminders_qry(cls):
        return cls.query(cls.has_unsent_reminders == True,
                         cls.reminders.fire_time < datetime.utcnow())

    def update(self, flight, alert_id, driving_time=None, reminder_lead_time=None):
        assert isinstance(flight, Flight)
        assert isinstance(alert_id, (int, long))
        new_data = flight.to_dict()

        # Optimization: only write data if it has changed
        if new_data != self.last_flight_data:
            self.last_flight_data = new_data
            if debug_datastore:
                logging.info('FLIGHT DATA UPDATED %s' % self.key.string_id())
        if alert_id != self.alert_id:
            self.alert_id = alert_id
            if debug_datastore:
                logging.info('FLIGHT ALERT ID UPDATED %s' % alert_id)
        if reminder_lead_time and reminder_lead_time != self.reminder_lead_time:
            self.reminder_lead_time = reminder_lead_time
            if debug_datastore:
                logging.info('FLIGHT REMINDER LEAD TIME CHANGED %d' % reminder_lead_time)
                
        # If we have driving time, update their reminders
        if driving_time is not None:
            self.set_or_update_flight_reminders(flight, driving_time)

    def get_unsent_reminders(self):
        unsent = []
        for r in self.reminders:
            if r.sent == False:
                unsent.append(r)
        return unsent

    def set_or_update_flight_reminders(self, flight, driving_time):
        assert isinstance(flight, Flight)
        assert isinstance(driving_time, (int, long))

        flight_id = flight.flight_id

        # If the flight is canceled or diverted, remove the alerts and don't add or update them
        if flight.status in [FLIGHT_STATES.CANCELED, FLIGHT_STATES.DIVERTED]:
            self.reminders = []
            return

        flight_num = self.user_flight_num
        dest_terminal = flight.destination.terminal
        dest_name = flight.destination.best_name
        lead_time = self.reminder_lead_time or config['leave_soon_seconds_before']
        leave_soon_pretty_interval = utils.pretty_time_interval(lead_time, round_days=True)

        # Figure out the reminder messages
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
        leave_soon_time = utils.leave_soon_time(flight, driving_time, lead_time)
        leave_now_time = utils.leave_now_time(flight, driving_time)

        # If there are no reminders for this flight, set them (even if they were supposed to fire in the past)
        if not self.reminders:
            # Set a leave soon reminder, mark it as sent if it was in the past
            leave_soon = FlightReminder(fire_time=leave_soon_time,
                                        reminder_type=REMINDER_TYPES.LEAVE_SOON,
                                        body=leave_soon_body,
                                        sent=leave_soon_time < datetime.utcnow())

            # Set a leave now reminder
            leave_now = FlightReminder(fire_time=leave_now_time,
                                       reminder_type=REMINDER_TYPES.LEAVE_NOW,
                                       body=leave_now_body)
            self.reminders = [leave_soon, leave_now]
        else:
            for r in self.reminders:
                # Only update unsent reminders (stops reminders from potentially being sent again)
                if r.sent == False:
                    if r.reminder_type == REMINDER_TYPES.LEAVE_SOON:
                        r.fire_time = leave_soon_time
                        r.body = leave_soon_body
                    else:
                        r.fire_time = leave_now_time
                        r.body = leave_now_body


class PushNotificationSetting(ndb.Model):
    """Model for a push notification setting (stored as key-value).

    E.g. push_arrived = True

    Represents a single push notification setting that will be associated with
    a specific Device.

    Fields:
    - `name` : The name of the setting.
    - `value` : The value of the setting (True/False)

    """
    name = ndb.StringProperty('n', required=True, indexed=False)
    value = ndb.BooleanProperty('v', required=True, indexed=False)


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
    - `app_version` : The version of the iOS app that the user most recently used.
    - `preferred_language` : The preferred language of the user.
    - `last_known_location` : The user's last known location.
    - `push_token` : The push token associated with this user.
    - `push_settings` : The push notification settings for this user.
    - `push_enabled` : Whether this user accepts push notifications.

    """
    app_version = ndb.StringProperty('version', default='1.2.1', indexed=False)
    preferred_language = ndb.StringProperty('language', default='en', indexed=False)
    last_known_location = ndb.GeoPtProperty('loc', indexed=False)
    push_token = ndb.TextProperty()
    push_settings = ndb.StructuredProperty(PushNotificationSetting, repeated=True)
    push_enabled = ndb.ComputedProperty(lambda u: bool(u.push_token))

    @classmethod
    def _get_kind(cls):
        return 'iOSUser_v2' # Versioned model kind

    @classmethod
    @ndb.tasklet
    def get_by_uuid(cls, uuid):
        assert utils.is_valid_uuid(uuid)
        user_key = ndb.Key(cls, uuid)
        user = yield user_key.get_async()
        raise tasklets.Return(user)

    @classmethod
    def create(cls, uuid, app_version=None, preferred_language=None, 
               user_latitude=None, user_longitude=None, push_token=None,
               send_reminders=None, send_flight_events=None, play_flight_sounds=None):
        assert utils.is_valid_uuid(uuid)
        user = cls(id=uuid,
                   push_settings=cls.default_settings())
        if app_version:
            user.app_version = app_version
        if preferred_language:
            user.preferred_language = preferred_language
        if push_token:
            user.push_token = push_token
        if user_latitude is not None and user_longitude is not None:
            user.last_known_location = ndb.GeoPt(user_latitude, lon=user_longitude)
            
        user.update_push_settings(send_reminders=send_reminders,
                                  send_flight_events=send_flight_events,
                                  play_flight_sounds=play_flight_sounds)    
                                          
        if debug_datastore:
            logging.info('CREATED NEW USER %s' % uuid)
        return user

    @classmethod
    def default_settings(cls):
        """Returns a list of the default PushNotificationSettings for an iOS user."""
        settings = []
        # Prefs are True by default
        for setting in PUSH_SETTINGS:
            settings.append(PushNotificationSetting(name=setting, value=True))
        return settings
        
    def update_push_settings(self, send_reminders=None, send_flight_events=None,
                             play_flight_sounds=None):
        # Add any missing settings
        existing_settings = [s.name for s in self.push_settings]
        missing_settings = [name for name in PUSH_SETTINGS if name not in existing_settings]
        for setting in missing_settings:
            self.push_settings.append(PushNotificationSetting(name=setting, value=True))
                             
        for setting in self.push_settings:
            if setting.name in REMINDER_TYPES and send_reminders is not None:
                setting.value = bool(send_reminders)
            elif (setting.name in [PUSH_SETTINGS.FILED, PUSH_SETTINGS.DIVERTED,
                PUSH_SETTINGS.CANCELED, PUSH_SETTINGS.DEPARTED, PUSH_SETTINGS.ARRIVED,
                PUSH_SETTINGS.CHANGED] and send_flight_events is not None):
                setting.value = bool(send_flight_events)
            elif setting.name == PUSH_SETTINGS.PLAY_FLIGHT_SOUNDS and play_flight_sounds is not None:
                setting.value = bool(play_flight_sounds)

    def update(self, app_version=None, preferred_language=None, 
               user_latitude=None, user_longitude=None, push_token=None,
               send_reminders=None, send_flight_events=None, play_flight_sounds=None):
        if debug_datastore:
            logging.info('UPDATING EXISTING USER %s' % self.key.string_id())

        # Only update the version if it has changed
        if app_version and app_version != self.app_version:
            self.app_version = app_version
            
        # Only update the language if it has changed
        if preferred_language and preferred_language != self.preferred_language:
            self.preferred_language = preferred_language

        # Only update the user's location if it has changed
        if ((user_latitude is not None) and (user_longitude is not None) and
            not self.location_is_current(user_latitude, user_longitude)):
            self.last_known_location = ndb.GeoPt(user_latitude, lon=user_longitude)
            if debug_datastore:
                logging.info('USER LOCATION UPDATED')

        # Only update the push token if we have a new one
        if push_token and push_token != self.push_token:
            self.push_token = push_token
            if debug_datastore:
                logging.info('USER PUSH TOKEN UPDATED')
                
        # Update the push settings
        self.update_push_settings(send_reminders=send_reminders,
                                  send_flight_events=send_flight_events,
                                  play_flight_sounds=play_flight_sounds)   

    def wants_notification_type(self, push_type):
        assert push_type
        for setting in self.push_settings:
            if setting.name == push_type:
                return setting.value
        return True # Default is True
    
    def wants_flight_sounds(self):
        for setting in self.push_settings:
            if setting.name == PUSH_SETTINGS.PLAY_FLIGHT_SOUNDS:
                return setting.value
        return True # Default is True

    def location_is_current(self, latitude, longitude):
        loc = self.last_known_location
        return loc and loc.lat == latitude and loc.lon == longitude


class Origin(object):
    """Container class for a flight origin being returned by the Just Landed API"""
    def __init__(self, origin_info):
        if isinstance(origin_info, dict):
            self._data = origin_info
        else:
            self._data = {}

    @property
    def altitude(self):
        return self._data.get('altitude')

    @altitude.setter
    def altitude(self, value):
        self._data['altitude'] = value

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
    def country(self):
        return self._data.get('country')

    @country.setter
    def country(self, value):
        self._data['country'] = value

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

    @property
    def timezone(self):
        """Returns the name of the timezone."""
        return self._data.get('timezone') or ''

    @timezone.setter
    def timezone(self, value):
        self._data['timezone'] = value

    def dict_for_client(self):
        info = {}
        info.update(self._data)
        info = utils.sub_dict_select(info, config['airport_fields'])
        return info


class Destination(Origin):
    """Container class for a flight destination being returned by the Just Landed API"""
    @property
    def bag_claim(self):
        return self._data.get('bagClaim')

    @bag_claim.setter
    def bag_claim(self, value):
        self._data['bagClaim'] = value

    @property
    def gate(self):
        return self._data.get('gate')

    @gate.setter
    def gate(self, value):
        self._data['gate'] = value


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
            if utils.timestamp(datetime.utcnow()) > self.scheduled_departure_time + config['on_time_buffer']:
                return FLIGHT_STATES.DELAYED
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
        """Returns true if the flight is definitely old."""
        if self.has_landed:
            arrival_time = datetime.utcfromtimestamp(self.actual_arrival_time)
            hours_ago = datetime.utcnow() - timedelta(hours=config['flight_old_hours'])
            return arrival_time < hours_ago
        else:
            return False

    @property
    def is_probably_old(self):
        """Returns true if the flight is probably old based on the estimated
        arrival time."""
        est_arrival_timestamp = self.estimated_arrival_time
        if utils.is_int(est_arrival_timestamp) and est_arrival_timestamp > 0:
            est_arrival_time = datetime.utcfromtimestamp(est_arrival_timestamp)
            hours_ago = datetime.utcnow() - timedelta(hours=config['flight_old_hours'])
            return est_arrival_time < hours_ago
        else:
            return False

    @property
    def is_in_flight(self):
        return (self.actual_departure_time > 0 and
                self.actual_arrival_time == 0)

    @property
    def has_landed(self):
        return self.actual_arrival_time > 0

    @property
    def is_night(self):
        if not self.is_in_flight:
            if self.status == FLIGHT_STATES.LANDED:
                # The flight has arrived, use the destination
                return utils.is_dark_now(self.destination.latitude,
                                         self.destination.longitude,
                                         altitude_in_feet=self.destination.altitude or 0)
            else:
                # The flight hasn't left, use the origin
                return utils.is_dark_now(self.origin.latitude,
                                         self.origin.longitude,
                                         altitude_in_feet=self.origin.altitude or 0)
        else:
            # The flight is in progress, approximate whether it is light or dark
            origin_sun_angle = utils.sun_altitude_degrees(self.origin.latitude,
                                                          self.origin.longitude,
                                                          altitude_in_feet=self.origin.altitude or 0)
            dest_sun_angle = utils.sun_altitude_degrees(self.destination.latitude,
                                                        self.destination.longitude,
                                                        altitude_in_feet=self.destination.altitude or 0)
            now = utils.timestamp(datetime.utcnow())
            progress = 0.0

            if now > self.estimated_arrival_time:
                progress = 0.999 # Landing overdue
            else:
                time_since_takeoff = now - self.actual_departure_time
                total_flight_time = self.estimated_arrival_time - self.actual_departure_time
                progress = time_since_takeoff / float(total_flight_time)

            sun_angle_approx = ((dest_sun_angle - origin_sun_angle) * progress) + origin_sun_angle
            return sun_angle_approx < 0.0

    def to_dict(self):
        info = utils.sub_dict_select(self._data, config['flight_fields'])
        info['origin'] = self.origin.dict_for_client()
        info['destination'] = self.destination.dict_for_client()
        return info

    def dict_for_client(self):
        info = self.to_dict()
        info['status'] = self.status
        info['detailedStatus'] = self.detailed_status
        info['isNight'] = self.is_night
        return info