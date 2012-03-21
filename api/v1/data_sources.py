#!/usr/bin/python

"""data_sources.py: This module defines all the data sources that power
the Just Landed app.

Flight data is pulled from either commercial APIs or from the datastore (in the
case of static data such as airport codes and locations). Commercial flight API
data sources are made to conform to a common FlightDataSource interface in
anticipation of possibly switching to alternate datasources in the future.

In addition to flight data, Just Landed estimates the user's driving time to the
airport so that it can make recommendations about when you should leave to
pick someone up at the terminal. This data also comes from commercial APIs, and
again is made to conform to a common DrivingTimeDataSource in case we switch
to new datasources in the future.

In addition to conforming to common interfaces, datasource responses are also
mapped to a predetermined JSON data format, and the JSON keys used are
standardized in config.py so that switching to new data sources in the future
will not break clients that are expecting a specific API from the JustLanded
server.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging

# We use memcache service to cache results from 3rd party APIs. This improves
# performance and also reduces our bill :)
from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets

from config import config, on_local
from models import (Airport, FlightAwareTrackedFlight, FlightAwareAlert, iOSUser,
    Origin, Destination, Flight)
from datasource_exceptions import *
from notifications import *
from connections import Connection, build_url
import utils
import aircraft_types

import reporting
from reporting import prodeagle_counter

FLIGHT_STATES = config['flight_states']
DATA_SOURCES = config['data_sources']
debug_cache = False
debug_alerts = False

###############################################################################
"""Flight Data Sources"""
###############################################################################

class FlightDataSource (object):
    """A class that defines a FlightDataSource interface that flight data
    sources should implement."""
    @property
    def base_url(self):
        """Returns the base URL of the API used by the datasource."""
        pass

    @property
    def api_key_mapping(self):
        """Returns a mapping of keys from the commercial API to keys used
        by the Just Landed API which is in turn consumed by our clients. This
        translation ensures that new datasources don't break clients.

        """
        pass

    def register_alert_endpoint(self, **kwargs):
        """Registers a Just Landed endpoint with the 3rd party API. This
        endpoint will handle flight status callbacks e.g. by triggering push
        notifications to clients.

        """
        pass

    def flight_info(self, flight_id, **kwargs):
        """Looks up and returns a specific Flight. The amount of information
        returned depends on whether or not the flight is en route or whether it
        is commercial, private or international.

        """
        pass

    def lookup_flights(self, flight_number, **kwargs):
        """Looks up flights by flight/tail number. This number is made up of
        the airline code and the flight number e.g. 'CO 1101'. Returns a list of
        flights matching this flight number. Flights returned should include
        only flights that are no older than those that landed an hour or so ago.

        The flights are sorted by departure time from earliest to latest.

        """
        pass

    def process_alert(self, alert_body):
        """Processes an incoming alert body posted to a Just Landed endpoint
        by a 3rd party API callback and returns an instance of a FlightAlert
        to the Just Landed application.

        """
        pass

    def set_alert(self, **kwargs):
        """Registers a callback with the 3rd party API for a specific flight.

        Returns the alert key.

        """
        pass

    def delete_alert(self, alert_id):
        """Deletes a callback from the 3rd party API e.g. when a flight is no
        longer being tracked by the user.

        """
        pass

    def track_flight(self, flight_id, flight_num, **kwargs):
        """Marks a flight as tracked. If there is a uuid supplied, we also mark
        the user as tracking the flight. If there is a push_token, we set an
        alert and make sure the user is notified of incoming alerts for that
        flight.

        """
        pass

    def delayed_track(self, flight_id, uuid):
        """Initiates a delayed track for a user of a specific flight."""
        pass

    def stop_tracking_flight(self, flight_id, **kwargs):
        """Stops tracking a flight. If there are alerts set and no users tracking
        the flight any longer, we delete & disable the alerts.

        """
        pass

    def authenticate_remote_request(self, request):
        """Returns True if the incoming request is in fact from the trusted
        3rd party datasource, False otherwise."""
        pass


###############################################################################
"""FlightAware"""
###############################################################################


class FlightAwareSource (FlightDataSource):
    """Concrete subclass of FlightDataSource that pulls its data from the
    commercial FlightAware FlightXML2 API:

    http://flightaware.com/commercial/flightxml/documentation2.rvt

    """
    @classmethod
    def airport_info_cache_key(cls, airport_code):
        assert utils.is_valid_icao(airport_code) or utils.is_valid_iata(airport_code)
        return "%s-airport_info-%s" % (cls.__name__, airport_code)

    @classmethod
    def flight_info_cache_key(cls, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        return "%s-flight_info-%s" % (cls.__name__, flight_id)

    @classmethod
    def airline_info_cache_key(cls, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        return "%s-airline_info-%s" % (cls.__name__, flight_id)

    @classmethod
    def lookup_flights_cache_key(cls, flight_num):
        assert utils.valid_flight_number(flight_num)
        return "%s-lookup_flights-%s" % (cls.__name__,
                                        utils.sanitize_flight_number(flight_num))

    @classmethod
    def clear_flight_info_cache(cls, flight_id):
        assert isinstance(flight_id, basestring) and len(flight_id)
        flight_cache_key = cls.flight_info_cache_key(flight_id)
        airline_cache_key = cls.airline_info_cache_key(flight_id)
        res = memcache.delete_multi([flight_cache_key, airline_cache_key])
        if res and debug_cache:
            logging.info('DELETED FLIGHT INFO CACHE KEYS %s' %
                    [flight_cache_key, airline_cache_key])

    @classmethod
    def  clear_flight_lookup_cache(cls, flight_numbers=[]):
        # De-dupe
        flight_numbers = set(flight_numbers)
        cache_keys = [cls.lookup_flights_cache_key(f_num) for f_num in flight_numbers]

        if cache_keys:
            res = memcache.delete_multi(cache_keys)
            if res and debug_cache:
                logging.info('DELETED LOOKUP CACHE KEYS %s' % cache_keys)

    @property
    def base_url(self):
        return "http://flightxml.flightaware.com/json/FlightXML2"

    @property
    def api_key_mapping(self):
        return config['flightaware']['key_mapping']

    def __init__(self):
        if on_local():
            self.conn = Connection(self.base_url,
                username=config['flightaware']['development']['username'],
                password=config['flightaware']['development']['key'])
        else:
            self.conn = Connection(self.base_url,
                username=config['flightaware']['production']['username'],
                password=config['flightaware']['production']['key'])

    @ndb.tasklet
    def do_track(self, request, user, flight_id, delayed=False):
        assert request
        assert isinstance(user, iOSUser)
        assert isinstance(flight_id, basestring) and len(flight_id)

        user_flight_num = user.flight_num_for_flight_id(flight_id)
        # Fire off a /track for the user, which will update their reminders
        url_scheme = (on_local() and 'http') or 'https'
        track_url = request.uri_for('track',
                                    flight_number=user_flight_num,
                                    flight_id=flight_id,
                                    _full=True,
                                    _scheme=url_scheme)
        full_track_url = build_url(track_url, '', args={
            'push_token' : user.push_token,
            'latitude' : user.last_known_location and user.last_known_location.lat,
            'longitude' : user.last_known_location and user.last_known_location.lon,
            'delayed' : (delayed and 1) or 0,
        })

        sig = utils.api_query_signature(full_track_url, client='Server')
        headers = {'X-Just-Landed-UUID' : user.key.string_id(),
                   'X-Just-Landed-Signature' : sig}

        ctx = ndb.get_context()
        yield ctx.urlfetch(full_track_url,
                            headers=headers,
                            deadline=120,
                            validate_certificate=(not on_local()))

    @ndb.tasklet
    def raw_flight_data_to_flight(self, data, sanitized_flight_num):
        if data and utils.valid_flight_number(sanitized_flight_num):
            # Keep a subset of the response fields
            fields = config['flightaware']['flight_info_fields']
            data = utils.sub_dict_strict(data, fields);

            # Map the response dict keys
            data = utils.map_dict_keys(data, self.api_key_mapping)

            origin_code = data['origin']
            destination_code = data['destination']
            origin_info, destination_info = yield self.airport_info(origin_code), self.airport_info(destination_code)
            origin = Origin(origin_info)
            destination = Destination(destination_info)

            flight = Flight(data)
            flight.flight_number = sanitized_flight_num
            flight.origin = origin
            flight.destination = destination

            # Convert flight duration to integer number of seconds
            flight_duration = data['scheduledFlightDuration'].split(':')
            secs = (int(flight_duration[0]) * 3600) + (int(flight_duration[1]) * 60)
            flight.scheduled_flight_duration = secs

            # Convert aircraft type
            flight.aircraft_type = aircraft_types.type_to_major_type(data.get('aircraftType'))
            flight.origin.name = utils.proper_airport_name(data['originName'])
            flight.destination.name = utils.proper_airport_name(data['destinationName'])
            raise tasklets.Return(flight)

    @ndb.tasklet
    def airport_info(self, airport_code):
        """Looks up information about an airport using its ICAO or IATA code."""
        airport = None
        assert utils.is_valid_icao(airport_code) or utils.is_valid_iata(airport_code)

        # Check the DB first
        airport = ((yield Airport.get_by_icao_code(airport_code)) or
                    (yield Airport.get_by_iata_code(airport_code)))

        if airport:
            raise tasklets.Return(airport.dict_for_client())
        elif utils.is_valid_icao(airport_code):
            logging.info('NOT FOUND %s', airport_code)
            # Check FlightAware for the AiportInfo
            memcache_key = FlightAwareSource.airport_info_cache_key(airport_code)

            airport = memcache.get(memcache_key)
            if airport is not None:
                if debug_cache:
                    logging.info('AIRPORT INFO CACHE HIT')

                raise tasklets.Return(airport)
            else:
                if debug_cache:
                    logging.info('AIRPORT INFO CACHE MISS')
                result = yield self.conn.get_json('/AirportInfo',
                                                args={'airportCode':airport_code})
                prodeagle_counter.incr(reporting.FETCH_AIRPORT_INFO)

                if result.get('error'):
                    raise AirportNotFoundException(airport_code)
                else:
                    airport = result['AirportInfoResult']

                    # Filter out fields we don't want
                    fields = config['flightaware']['airport_info_fields']
                    airport = utils.sub_dict_strict(airport, fields)

                    # Map field names
                    airport = utils.map_dict_keys(airport,
                                                  self.api_key_mapping)

                    # Add ICAO code back in (we don't have IATA)
                    airport['icaoCode'] = airport_code
                    airport['iataCode'] = None

                    # Make sure the name is well formed
                    airport['name'] = utils.proper_airport_name(airport['name'])

                    # Round lat & long
                    airport['latitude'] = utils.round_coord(airport['latitude'])
                    airport['longitude'] = utils.round_coord(airport['longitude'])

                    if not memcache.set(memcache_key, airport):
                        logging.error("Unable to cache airport info!")
                    elif debug_cache:
                        logging.info('AIRPORT INFO CACHE SET')

                    raise tasklets.Return(airport)
        else:
            raise AirportNotFoundException(airport_code)

    @ndb.tasklet
    def register_alert_endpoint(self, **kwargs):
        endpoint_url = config['flightaware']['alert_endpoint']
        result = yield self.conn.get_json('/RegisterAlertEndpoint',
                                        args={'address': endpoint_url,
                                              'format_type': 'json/post'})
        error = result.get('error')

        if not error and result.get('RegisterAlertEndpointResult') == 1:
            raise tasklets.Return({'endpoint_url' : endpoint_url})
        else:
            raise UnableToSetEndpointException(endpoint=endpoint_url)

    @ndb.tasklet
    def flight_info(self, flight_id, **kwargs):
        """Implements flight_info method of FlightDataSource and provides
        additional kwargs:

        - `flight_number` : Required by FlightAware to lookup flights.
        """
        flight_number = kwargs.get('flight_number')

        if not utils.valid_flight_number(flight_number):
            raise InvalidFlightNumberException(flight_number)

        if not flight_id:
            raise FlightNotFoundException(flight_number)

        flight_cache_key = FlightAwareSource.flight_info_cache_key(flight_id)
        airline_cache_key = FlightAwareSource.airline_info_cache_key(flight_id)
        sanitized_f_num = utils.sanitize_flight_number(flight_number)

        result = memcache.get_multi([flight_cache_key, airline_cache_key])
        to_fetch = []

        # Find the flight, try cache first
        flight = result.get(flight_cache_key)
        airline_info = result.get(airline_cache_key)

        if flight:
            if debug_cache:
                logging.info('FLIGHT CACHE HIT')
        else:
            if debug_cache:
                logging.info('FLIGHT CACHE MISS')
            to_fetch.append(self.conn.get_json('/FlightInfoEx',
                                                args={'ident': sanitized_f_num,
                                                      'howMany': 15}))
            prodeagle_counter.incr(reporting.FETCH_FLIGHT_INFO)

        if airline_info:
            if debug_cache:
                logging.info('AIRLINE INFO CACHE HIT')
        else:
            if debug_cache:
                logging.info('AIRLINE INFO CACHE MISS')
            to_fetch.append(self.conn.get_json('/AirlineFlightInfo',
                                                args={'faFlightID': flight_id}))
            prodeagle_counter.incr(reporting.FETCH_AIRLINE_FLIGHT_INFO)

        flight_data = None
        airline_data = None

        if not flight and not airline_info:
            flight_data, airline_data = yield to_fetch
        elif not flight:
            flight_data = yield to_fetch[0]
        elif not airline_info:
            airline_data = yield to_fetch[0]

        cache_to_set = {}

        if flight_data:
            if flight_data.get('error'):
                raise FlightNotFoundException(sanitized_f_num)
            flight_data = flight_data['FlightInfoExResult']['flights']
            for data in flight_data:
                if data['faFlightID'] == flight_id:
                    flight = yield self.raw_flight_data_to_flight(data, sanitized_f_num)
                    cache_to_set[flight_cache_key] = flight
                    break

        if airline_data:
            if airline_data.get('error'):
                raise TerminalsUnknownException(flight_id)
            fields = config['flightaware']['airline_flight_info_fields']
            airline_info = airline_data['AirlineFlightInfoResult']
            airline_info = utils.sub_dict_strict(airline_info, fields)
            airline_info = utils.map_dict_keys(airline_info, self.api_key_mapping)
            cache_to_set[airline_cache_key] = airline_info

        if cache_to_set:
            cache_keys = cache_to_set.keys()
            not_set = memcache.set_multi(cache_to_set,
                                time=config['flightaware']['flight_cache_time'])

            if flight_cache_key in cache_keys:
                if flight_cache_key in not_set:
                    logging.error("Unable to cache flight lookup!")
                elif debug_cache:
                    logging.info('FLIGHT CACHE SET')

            if airline_cache_key in cache_keys:
                if airline_cache_key in not_set:
                    logging.error("Unable to cache airline flight info!")
                elif debug_cache:
                    logging.info('AIRLINE INFO CACHE SET')

        # Missing flight indicates probably tracking an old flight
        if not flight or not airline_info or flight.is_old_flight:
            raise OldFlightException(flight_number=flight_number,
                                     flight_id=flight_id)

        # Add in the airline info and user-entered flight number
        flight.flight_number = utils.sanitize_flight_number(flight_number)
        flight.origin.terminal = airline_info['originTerminal']
        flight.destination.terminal = airline_info['destinationTerminal']
        flight.destination.bag_claim = airline_info['bagClaim']
        raise tasklets.Return(flight)

    @ndb.tasklet
    def lookup_flights(self, flight_number, **kwargs):
        """Concrete implementation of lookup_flights of FlightDataSource."""
        sanitized_f_num = utils.sanitize_flight_number(flight_number)
        lookup_cache_key = FlightAwareSource.lookup_flights_cache_key(sanitized_f_num)
        flights = memcache.get(lookup_cache_key)

        def cache_stale():
            for f in flights:
                if f.is_old_flight:
                    return True
            return False

        if flights is not None and not cache_stale():
            if debug_cache:
                logging.info('LOOKUP CACHE HIT')
            raise tasklets.Return(flights)
        else:
            if debug_cache:
                logging.info('LOOKUP CACHE MISS')

            flight_data = yield self.conn.get_json('/FlightInfoEx',
                                        args={'ident': sanitized_f_num,
                                              'howMany': 15})
            prodeagle_counter.incr(reporting.FETCH_FLIGHT_INFO)

            if flight_data.get('error'):
                raise FlightNotFoundException(sanitized_f_num)
            else:
                flight_data = flight_data['FlightInfoExResult']['flights']

                # Convert raw flight data to instances of Flight
                yield_flights = []

                for data in flight_data:
                    flight_fut = self.raw_flight_data_to_flight(data, sanitized_f_num)
                    yield_flights.append(flight_fut)

                flights_tup = yield yield_flights
                flights = list(flights_tup)

                # Filter out old flights & sort by departure date (earliest first)
                flights = [f for f in flights if not f.is_old_flight]
                flights.sort(key=lambda f: f.scheduled_departure_time)

            if not memcache.set(lookup_cache_key, flights,
                                config['flightaware']['flight_lookup_cache_time']):
                logging.error("Unable to cache lookup response!")
            elif debug_cache:
                logging.info('LOOKUP CACHE SET')

            raise tasklets.Return(flights)

    @ndb.tasklet
    def process_alert(self, alert_body, request):
        assert isinstance(alert_body, dict)
        alert_id = alert_body.get('alert_id')
        event_code = alert_body.get('eventcode')
        flight_data = alert_body.get('flight')
        flight_id = flight_data.get('faFlightID')
        origin = flight_data.get('origin')
        destination = flight_data.get('destination')

        if alert_id and event_code and flight_id and origin and destination:
            # Clear memcache keys for flight & airline info
            FlightAwareSource.clear_flight_info_cache(flight_id)

            # Get current flight information for the flight mentioned by the alert
            flight_num = utils.flight_num_from_fa_flight_id(flight_id)
            alerted_flight, stored_flight = yield (self.flight_info(flight_id=flight_id, flight_number=flight_num),
                                                    FlightAwareTrackedFlight.get_flight_by_id(flight_id))

            if alerted_flight and stored_flight:
                # Reconstruct the flight from the datastore
                orig_flight = Flight.from_dict(stored_flight.last_flight_data)
                orig_flight.scheduled_flight_duration = stored_flight.orig_flight_duration
                orig_flight.scheduled_departure_time = stored_flight.orig_departure_time
                alerted_flight.scheduled_flight_duration = stored_flight.orig_flight_duration
                alerted_flight.scheduled_departure_time = stored_flight.orig_departure_time

                terminal_changed = (alerted_flight.destination.terminal and (alerted_flight.destination.terminal !=
                                    orig_flight.destination.terminal))

                # Send out push notifications
                push_types = config['push_types']
                ctx = ndb.get_context()
                flight_numbers = []
                track_requests = []

                # Reporting
                if event_code == 'change':
                    prodeagle_counter.incr(reporting.FLIGHT_CHANGE)
                elif event_code == 'departure':
                    prodeagle_counter.incr(reporting.FLIGHT_TAKEOFF)
                elif event_code == 'arrival':
                    prodeagle_counter.incr(reporting.FLIGHT_LANDED)
                elif event_code == 'diverted':
                    prodeagle_counter.incr(reporting.FLIGHT_DIVERTED)
                elif event_code == 'cancelled':
                    prodeagle_counter.incr(reporting.FLIGHT_CANCELED)

                # FIXME: Assume iOS user
                users_to_notify = yield iOSUser.users_to_notify(alert_id, flight_id, source=DATA_SOURCES.FlightAware)
                while (yield users_to_notify.has_next_async()):
                    u = users_to_notify.next()
                    user_flight_num = u.flight_num_for_flight_id(flight_id) or flight_num
                    flight_numbers.append(utils.sanitize_flight_number(user_flight_num))
                    device_token = u.push_token

                    # Send notifications to each user, only if they want that notification type
                    # Early / delayed / on time
                    if ((event_code == 'change' or event_code == 'minutes_out') and
                        u.wants_notification_type(push_types.CHANGED)):
                        if terminal_changed:
                            TerminalChangeAlert(device_token, alerted_flight, user_flight_num).push()
                            prodeagle_counter.incr(reporting.SENT_CHANGE_NOTIFICATION)
                        else:
                            FlightPlanChangeAlert(device_token, alerted_flight, user_flight_num).push()
                            prodeagle_counter.incr(reporting.SENT_CHANGE_NOTIFICATION)

                    # Take off
                    elif event_code == 'departure' and u.wants_notification_type(push_types.DEPARTED):
                        FlightDepartedAlert(device_token, alerted_flight, user_flight_num).push()
                        prodeagle_counter.incr(reporting.SENT_TAKEOFF_NOTIFICATION)

                    # Arrival
                    elif event_code == 'arrival' and u.wants_notification_type(push_types.ARRIVED):
                        FlightArrivedAlert(device_token, alerted_flight, user_flight_num).push()
                        prodeagle_counter.incr(reporting.SENT_LANDED_NOTIFICATION)

                    # Diverted
                    elif event_code == 'diverted' and u.wants_notification_type(push_types.DIVERTED):
                        FlightDivertedAlert(device_token, alerted_flight, user_flight_num).push()
                        prodeagle_counter.incr(reporting.SENT_DIVERTED_NOTIFICATION)

                    # Canceled
                    elif event_code == 'cancelled' and u.wants_notification_type(push_types.CANCELED):
                        FlightCanceledAlert(device_token, alerted_flight, user_flight_num).push()
                        prodeagle_counter.incr(reporting.SENT_CANCELED_NOTIFICATION)

                    else:
                        logging.error('Unknown eventcode.')

                    # Fire off a /track for the user, which will update their reminders
                    track_requests.append(self.do_track(request, u, flight_id))

                # Clear memcache keys for lookup
                FlightAwareSource.clear_flight_lookup_cache(flight_numbers)

                # Parallel yield track requests
                yield track_requests

    @ndb.tasklet
    def set_alert(self, **kwargs):
        flight_id = kwargs.get('flight_id')
        assert isinstance(flight_id, basestring) and len(flight_id)
        # Derive flight num from flight_id so we can use common flight_num for alerts
        flight_num = utils.sanitize_flight_number(
                        utils.flight_num_from_fa_flight_id(flight_id))

        # Set the alert with FlightAware and keep a record of it in our system
        # Only set if the alert wasn't already there
        alert_id = yield self.alert_already_set(flight_num) # Checks FA, not DB
        if not alert_id:
            channels = "{16 e_filed e_departure e_arrival e_diverted e_cancelled}"
            result = yield self.conn.get_json('/SetAlert',
                                args={'alert_id': 0,
                                    'ident': flight_num,
                                    'channels': channels,
                                    'max_weekly': 1000})
            prodeagle_counter.incr(reporting.SET_ALERT)

            error = result.get('error')
            alert_id = result.get('SetAlertResult')
            if error or not alert_id:
                raise UnableToSetAlertException(reason=error)

        if debug_alerts:
            logging.info('REGISTERED NEW ALERT')
        # Store the alert so we don't recreate it
        created = yield FlightAwareAlert.create_or_reuse_alert(alert_id, flight_num)
        if created:
            raise tasklets.Return(alert_id)
        else:
            raise UnableToSetAlertException(reason='Bad Alert Id')

    @ndb.tasklet
    def alert_already_set(self, flight_num):
        alerts = yield self.get_all_alerts()
        for alert in alerts:
            if alert.get('ident') == flight_num:
                raise tasklets.Return(alert.get('alert_id'))

    @ndb.tasklet
    def get_all_alerts(self):
        result = yield self.conn.get_json('/GetAlerts', args={})
        prodeagle_counter.incr(reporting.FETCH_ALERTS)

        error = result.get('error')
        alert_info = result.get('GetAlertsResult')

        if not error and alert_info:
            alerts = alert_info.get('alerts')
            if debug_alerts:
                logging.info('%d ALERTS ARE SET' % len(alerts))
            raise tasklets.Return(alerts)
        else:
            raise UnableToGetAlertsException()

    @ndb.tasklet
    def delete_alert(self, alert_id):
        result = yield self.conn.get_json('/DeleteAlert',
                                        args={'alert_id':alert_id})
        prodeagle_counter.incr(reporting.DELETED_ALERT)
        error = result.get('error')
        success = result.get('DeleteAlertResult')

        if not error and success == 1:
            if debug_alerts:
                logging.info('DELETED ALERT %d' % alert_id)

            # Disable the alert in the datastore
            yield FlightAwareAlert.disable_alert(alert_id)
            raise tasklets.Return(True)
        raise UnableToDeleteAlertException(alert_id)

    @ndb.tasklet
    def delete_alerts(self, alert_ids):
        # Can't be run in a transaction - there could easily be too many alerts & users
        # Delete the alerts from FlightAware & users
        for alert_id in alert_ids:
            del_fut = self.delete_alert(alert_id)
            clear_fut = iOSUser.clear_alert_from_users(alert_id,
                                                source=DATA_SOURCES.FlightAware)
            yield del_fut, clear_fut

    @ndb.tasklet
    def clear_all_alerts(self):
        alerts = yield self.get_all_alerts()
        # Get all the alert ids
        alert_ids = [alert.get('alert_id') for alert in alerts]
        if debug_alerts:
            logging.info('CLEARING %d ALERTS' % len(alert_ids))

        # Defer removal of all alerts
        alert_ids = [str(alert_id) for alert_id in alert_ids if isinstance(alert_id, (int, long))]
        alert_list = ','.join(alert_ids)
        task = taskqueue.Task(payload=alert_list)
        taskqueue.Queue('clear-alerts').add(task)
        raise tasklets.Return({'clearing_alert_count': len(alert_ids)})

    @ndb.tasklet
    def track_flight(self, flight_data, **kwargs):
        flight = Flight.from_dict(flight_data)
        flight_id = flight.flight_id
        flight_num = flight.flight_number
        assert isinstance(flight_id, basestring) and len(flight_id)
        assert utils.valid_flight_number(flight_num)

        uuid = kwargs.get('uuid')
        push_token = kwargs.get('push_token')
        user_latitude = kwargs.get('user_latitude')
        user_longitude = kwargs.get('user_longitude')
        driving_time = kwargs.get('driving_time')

        # Derive flight num from flight_id so we can use common flight_num for alerts
        der_flight_num = utils.sanitize_flight_number(
                            utils.flight_num_from_fa_flight_id(flight_id))

        # See if the alert exists (according to our datastore) and is enabled
        alert_id = yield FlightAwareAlert.existing_enabled_alert(der_flight_num)
        if debug_alerts and isinstance(alert_id, (int, long)) and alert_id > 0 :
            logging.info('EXISTING ALERT FOR %s' % der_flight_num)

        @ndb.tasklet
        def track_txn(flight_id, flight_num, uuid, push_token, alert_id):
            valid_alert_id = isinstance(alert_id, (int, long)) and alert_id > 0

            # Check the alert is still good and enabled
            if valid_alert_id:
                alert = yield FlightAwareAlert.get_by_alert_id(alert_id)
                if not alert or not alert.is_enabled:
                    valid_alert_id = False # Trigger new alert creation

            if not valid_alert_id:
                # Only set an alert_id if we don't have one or it isn't enabled
                alert_id = yield self.set_alert(flight_id=flight_id)

            # Mark the flight as being tracked
            existing_flight = yield FlightAwareTrackedFlight.get_flight_by_id(flight_id)
            if not existing_flight:
                prodeagle_counter.incr(reporting.NEW_FLIGHT)
                yield FlightAwareTrackedFlight.create_flight(flight)
            else:
                existing_flight.last_flight_data = flight.to_dict()
                yield existing_flight.put_async()

            # Save the user's tracking activity if we have a uuid
            if uuid:
                old_push_token = None

                if push_token:
                    existing_user = yield iOSUser.get_by_uuid(uuid)
                    old_push_token = existing_user and existing_user.push_token

                user = yield iOSUser.track_flight(uuid=uuid,
                                                  flight_id=flight_id,
                                                  flight_num=flight_num,
                                                  user_latitude=user_latitude,
                                                  user_longitude=user_longitude,
                                                  push_token=push_token,
                                                  alert_id=alert_id,
                                                  source=DATA_SOURCES.FlightAware)

                if driving_time is not None:
                    user.set_or_update_flight_reminders(flight, driving_time, source=DATA_SOURCES.FlightAware)
                    yield user.put_async()

                # Tell UrbanAirship about push tokens
                if old_push_token and push_token != old_push_token:
                    deregister_token(old_push_token)
                if push_token:
                    register_token(push_token) # Need to tell UA that token is still active

        # TRANSACTIONAL TRACKING!
        yield ndb.transaction_async(lambda: track_txn(flight_id, flight_num, uuid, push_token, alert_id), xg=True)

    @ndb.tasklet
    def delayed_track(self, request, flight_id, uuid):
        """Initiates a delayed track for a user of a specific flight to update their reminders."""
        assert request
        assert isinstance(flight_id, basestring) and len(flight_id)
        assert isinstance(uuid, basestring) and len(uuid)
        user = yield iOSUser.get_by_uuid(uuid)
        if user.is_tracking_flight(flight_id) and user.push_enabled and user.has_unsent_reminders:
            # Clear the cache (we want fresh data)
            FlightAwareSource.clear_flight_info_cache(flight_id)
            yield self.do_track(request, user, flight_id, delayed=True)

    @ndb.tasklet
    def stop_tracking_flight(self, flight_id, **kwargs):
        uuid = kwargs.get('uuid')
        flight_num = utils.flight_num_from_fa_flight_id(flight_id)

        # Lookup any existing alert by flight number
        alert_id = yield FlightAwareAlert.existing_enabled_alert(flight_num)

        @ndb.tasklet
        def untrack_txn(flight_id, flight_num, uuid, alert_id):
            # Mark the user as no longer tracking the flight or the alert
            if uuid:
                yield iOSUser.untrack_flight(uuid,
                                            flight_id,
                                            alert_id=alert_id,
                                            source=DATA_SOURCES.FlightAware)

            # If there are no more users tracking the alert, delete it
            if alert_id:
                alert = yield FlightAwareAlert.get_by_alert_id(alert_id)
                if alert.num_users_with_alert == 0:
                    yield self.delete_alert(alert_id)

        yield ndb.transaction_async(lambda: untrack_txn(flight_id, flight_num, uuid, alert_id), xg=True)

    def authenticate_remote_request(self, request):
        """Returns True if the incoming request is in fact from the trusted
        3rd party datasource, False otherwise."""
        # FIXME: Maybe don't check user agent
        user_agent = request.environ.get('HTTP_USER_AGENT')
        remote_addr = request.remote_addr
        return (user_agent == config['flightaware']['remote_user_agent'] and
                utils.is_trusted_flightaware_host(remote_addr))


###############################################################################
"""Driving Time Data Sources"""
###############################################################################

class DrivingTimeDataSource (object):
    """A class that defines a DrivingTimeDataSource interface that driving time
    data sources should implement."""
    @classmethod
    def driving_cache_key(cls, orig_lat, orig_lon, dest_lat, dest_lon):
        # Rounding the coordinates has the effect of re-using driving distance
        # calculations for locations close to each other
        return '%s-driving_time-%f,%f,%f,%f' % (
                cls.__name__,
                utils.round_coord(orig_lat, sf=2),
                utils.round_coord(orig_lon, sf=2),
                utils.round_coord(dest_lat, sf=2),
                utils.round_coord(dest_lon, sf=2),
        )

    @property
    def base_url(self):
        """Returns the base URL of the API used by the datasource."""
        pass

    def driving_time(origin_lat, origin_lon, dest_lat, dest_lon, **kwargs):
        """Returns an estimate of the driving time from (origin_lat, origin_lon)
        to (dest_lat, dest_lon) or throws an exception if this estimate cannot
        be calculated - either due to a problem with the datasource, or due
        to there being no driving route between the two points.

        The driving time returned is in seconds.

        """
        pass

class GoogleDistanceSource (DrivingTimeDataSource):
    """Concrete subclass of DrivingTimeDataSource that pulls its data from the
    commercial Google Distance Matrix API:

    http://code.google.com/apis/maps/documentation/distancematrix/

    """
    @property
    def base_url(self):
        return 'https://maps.googleapis.com/maps/api/distancematrix'

    def __init__(self):
        self.conn = Connection(self.base_url)

    @ndb.tasklet
    def driving_time(self, origin_lat, origin_lon, dest_lat, dest_lon, **kwargs):
        """Implements driving_time method of DrivingTimeDataSource. """
        driving_cache_key = GoogleDistanceSource.driving_cache_key(origin_lat,
                                                                   origin_lon,
                                                                   dest_lat,
                                                                   dest_lon)
        time = memcache.get(driving_cache_key)

        if time is not None:
            if debug_cache:
                logging.info('DRIVING CACHE HIT')
            raise tasklets.Return(time)
        else:
            if debug_cache:
                logging.info('DRIVING CACHE MISS')
            params = dict(
                origins='%f,%f' % (origin_lat, origin_lon),
                destinations='%f,%f' % (dest_lat, dest_lon),
                sensor='true',
                mode='driving',
                units='imperial',
            )

            data = yield self.conn.get_json('/json', args=params)
            prodeagle_counter.incr(reporting.FETCH_DRIVING_TIME)
            status = data.get('status')

            if status == 'OK':
                try:
                    time = data['rows'][0]['elements'][0]['duration']['value']
                    # Cache data, not using traffic info, so data good indefinitely
                    if not memcache.set(driving_cache_key, time):
                        logging.error("Unable to cache driving time!")
                    elif debug_cache:
                        logging.info('DRIVING CACHE SET')
                    raise tasklets.Return(time)
                except (KeyError, IndexError, TypeError):
                    raise MalformedDrivingDataException(origin_lat, origin_lon,
                                                      dest_lat, dest_lon, data)
            elif status == 'REQUEST_DENIED':
                raise DrivingDistanceDeniedException(origin_lat, origin_lon,
                                                     dest_lat, dest_lon)
            elif status == 'OVER_QUERY_LIMIT':
                raise DrivingAPIQuotaException()
            else:
                raise UnknownDrivingTimeException(origin_lat, origin_lon,
                                                  dest_lat, dest_lon)


class BingMapsDistanceSource (DrivingTimeDataSource):
    """Concrete subclass of DrivingTimeDataSource that pulls its data from the
    commercial Bing Maps API:

    http://msdn.microsoft.com/en-us/library/ff701722.aspx

    """
    @property
    def base_url(self):
        return 'https://dev.virtualearth.net/REST/v1'

    def __init__(self):
        self.conn = Connection(self.base_url)

    @ndb.tasklet
    def driving_time(self, origin_lat, origin_lon, dest_lat, dest_lon, **kwargs):
        """Implements driving_time method of DrivingTimeDataSource."""
        driving_cache_key = BingMapsDistanceSource.driving_cache_key(origin_lat,
                                                                    origin_lon,
                                                                    dest_lat,
                                                                    dest_lon)
        time = memcache.get(driving_cache_key)

        if time is not None:
            if debug_cache:
                logging.info('DRIVING CACHE HIT')
            raise tasklets.Return(time)
        else:
            if debug_cache:
                logging.info('DRIVING CACHE MISS')
            params = {
                'key' : config['bing_maps']['key'],
                'wp.0' : '%f,%f' % (origin_lat, origin_lon),
                'wp.1' : '%f,%f' % (dest_lat, dest_lon),
                'optmz' : 'timeWithTraffic',
                'du' : 'mi',
                'rpo' : 'None',
            }

            data = yield self.conn.get_json('/Routes', args=params)
            prodeagle_counter.incr(reporting.FETCH_DRIVING_TIME)
            status = data.get('statusCode')

            if status == 200:
                try:
                    time = data['resourceSets'][0]['resources'][0]['travelDuration']
                    if not memcache.set(driving_cache_key, time, config['traffic_cache_time']):
                        logging.error("Unable to cache driving time!")
                    elif debug_cache:
                        logging.info('DRIVING CACHE SET')
                    raise tasklets.Return(time)
                except (KeyError, IndexError, TypeError):
                    raise MalformedDrivingDataException(origin_lat, origin_lon,
                                                      dest_lat, dest_lon, data)
            elif status == 401 or status == 404:
                raise DrivingDistanceDeniedException(origin_lat, origin_lon,
                                                     dest_lat, dest_lon)
            elif status == 403:
                raise DrivingAPIQuotaException()
            else:
                raise UnknownDrivingTimeException(origin_lat, origin_lon,
                                                  dest_lat, dest_lon)
