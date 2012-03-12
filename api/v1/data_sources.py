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
import json

# We use memcache service to cache results from 3rd party APIs. This improves
# performance and also reduces our bill :)
from google.appengine.api import memcache
from google.appengine.ext import deferred

from config import config, on_local
from models import (Airport, FlightAwareTrackedFlight, FlightAwareAlert, iOSUser,
    Origin, Destination, Flight)
from datasource_exceptions import *
from notifications import *
import utils
import aircraft_types

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

    def start_tracking_flight(self, flight_id, flight_num, **kwargs):
        """Marks a flight as tracked. If there is a uuid supplied, we also mark
        the user as tracking the flight. If there is a push_token, we set an
        alert and make sure the user is notified of incoming alerts for that
        flight.

        """
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

def fa_delete_alerts(alert_ids):
    source = FlightAwareSource()
    for alert_id in alert_ids:
        source.delete_alert(alert_id)


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

    @property
    def base_url(self):
        return "http://flightxml.flightaware.com/json/FlightXML2/"

    @property
    def api_key_mapping(self):
        return config['flightaware']['key_mapping']

    def __init__(self):
        from lib.python_rest_client.restful_lib import Connection
        if on_local():
            self.conn = Connection(self.base_url,
                username=config['flightaware']['development']['username'],
                password=config['flightaware']['development']['key'])
        else:
            self.conn = Connection(self.base_url,
                username=config['flightaware']['production']['username'],
                password=config['flightaware']['production']['key'])

    def raw_flight_data_to_flight(self, data, sanitized_flight_num):
        if data and utils.valid_flight_number(sanitized_flight_num):
            # Keep a subset of the response fields
            fields = config['flightaware']['flight_info_fields']
            data = utils.sub_dict_strict(data, fields);

            # Map the response dict keys
            data = utils.map_dict_keys(data, self.api_key_mapping)

            origin_code = data['origin']
            origin = Origin(self.airport_info(origin_code))
            destination_code = data['destination']
            destination = Destination(self.airport_info(destination_code))

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

            flight.origin.city = data['originCity'].split(',')[0]
            flight.origin.name = utils.proper_airport_name(data['originName'])
            flight.destination.city = data['destinationCity'].split(',')[0]
            flight.destination.name = utils.proper_airport_name(data['destinationName'])
            return flight

    def airport_info(self, airport_code):
        """Looks up information about an airport using its ICAO or IATA code."""
        airport = None
        assert utils.is_valid_icao(airport_code) or utils.is_valid_iata(airport_code)

        # Check the DB first
        airport = Airport.get_by_icao_code(airport_code) or Airport.get_by_iata_code(airport_code)

        if airport:
            return airport.dict_for_client()
        elif utils.is_valid_icao(airport_code):
            # Check FlightAware for the AiportInfo
            memcache_key = FlightAwareSource.airport_info_cache_key(airport_code)

            airport = memcache.get(memcache_key)
            if airport is not None:
                if debug_cache:
                    logging.info('AIRPORT INFO CACHE HIT')

                return airport
            else:
                if debug_cache:
                    logging.info('AIRPORT INFO CACHE MISS')
                resp = self.conn.request_get('/AirportInfo',
                                             args={'airportCode':airport_code})
                # Turn the JSON response into a dict
                result = json.loads(resp['body'])

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
                    if debug_cache:
                        logging.info('AIRPORT INFO CACHE SET')

                    return airport
        else:
            raise AirportNotFoundException(airport_code)

    def register_alert_endpoint(self, **kwargs):
        endpoint_url = config['flightaware']['alert_endpoint']

        resp = self.conn.request_get('/RegisterAlertEndpoint',
                 args={'address': endpoint_url,
                       'format_type': 'json/post'})

        result = json.loads(resp['body'])
        error = result.get('error')

        if not error and result.get('RegisterAlertEndpointResult') == 1:
            return {'endpoint_url' : endpoint_url}
        else:
            raise UnableToSetEndpointException(endpoint=endpoint_url)

    def flight_info(self, flight_id, **kwargs):
        """Implements flight_info method of FlightDataSource and provides
        additional kwargs:

        - `no_cache` : Set to True to not use cache.
        - `flight_number` : Required by FlightAware to lookup flights.
        """
        use_cache = not kwargs.get('no_cache')
        flight_number = kwargs.get('flight_number')

        if not utils.valid_flight_number(flight_number):
            raise InvalidFlightNumberException(flight_number)

        if not flight_id:
            raise FlightNotFoundException(flight_number)

        flight = None
        flight_cache_key = FlightAwareSource.flight_info_cache_key(flight_id)
        airline_cache_key = FlightAwareSource.airline_info_cache_key(flight_id)

        # Find the flight, try cache first
        if use_cache:
            flight = memcache.get(flight_cache_key)
            if flight and debug_cache:
                logging.info('FLIGHT CACHE HIT')

        # Cache miss
        if flight is None:
            if use_cache and debug_cache:
                logging.info('FLIGHT CACHE MISS')

            # Do filtered lookup without introducing 2nd layer of caching
            flights = self.lookup_flights(flight_number,
                                          find_flight_id=flight_id,
                                          no_cache=True)
            if len(flights):
                # Take first match
                flight = flights[0]
                if use_cache and not memcache.set(flight_cache_key, flight,
                    config['flightaware']['flight_cache_time']):
                    logging.error("Unable to cache flight lookup!")
                elif use_cache and debug_cache:
                    logging.info('FLIGHT CACHE SET')

        # Missing flight indicates probably tracking an old flight
        if not flight or flight.is_old_flight:
            raise OldFlightException(flight_number=flight_number,
                                     flight_id=flight_id)

        # Get detailed terminal & gate information
        airline_info = None

        # Check cache
        if use_cache:
            airline_info = memcache.get(airline_cache_key)
            if (airline_info is not None) and debug_cache:
                logging.info('AIRLINE INFO CACHE HIT')

        if not airline_info:
            if use_cache and debug_cache:
                logging.info('AIRLINE INFO CACHE MISS')

            resp = self.conn.request_get('/AirlineFlightInfo',
                                         args={'faFlightID': flight_id})
            # Turn the JSON response into a dict
            result = json.loads(resp['body'])

            if result.get('error'):
                raise TerminalsUnknownException(flight_id)

            # Filter & map the result
            fields = config['flightaware']['airline_flight_info_fields']
            airline_info = result['AirlineFlightInfoResult']
            airline_info = utils.sub_dict_strict(airline_info, fields)
            airline_info = utils.map_dict_keys(airline_info, self.api_key_mapping)

            if use_cache and not memcache.set(airline_cache_key, airline_info):
                logging.error("Unable to cache airline flight info!")
            elif use_cache and debug_cache:
                logging.info('AIRLINE INFO CACHE SET')

        # Add in the airline info and user-entered flight number
        flight.flight_number = utils.sanitize_flight_number(flight_number)
        flight.origin.terminal = airline_info['originTerminal']
        flight.destination.terminal = airline_info['destinationTerminal']
        flight.destination.bag_claim = airline_info['bagClaim']

        return flight

    def lookup_flights(self, flight_number, **kwargs):
        """Concrete implementation of lookup_flights of FlightDataSource.

        Supports two additional kwargs:
        - `find_flight_id` : Filter results to look for a specific flight id.
        - `no_cache` : Set to True to not use any caching.

        """
        find_flight_id = kwargs.get('find_flight_id')
        use_cache = not kwargs.get('no_cache') # Cache by default
        sanitized_f_num = utils.sanitize_flight_number(flight_number)
        flights = None
        lookup_cache_key = FlightAwareSource.lookup_flights_cache_key(sanitized_f_num)

        if use_cache:
            flights = memcache.get(lookup_cache_key)

        def cache_stale():
            for f in flights:
                if f.is_old_flight:
                    return True
            return False

        if use_cache and flights is not None and not cache_stale():
            if debug_cache:
                logging.info('LOOKUP CACHE HIT')
            return flights
        else:
            if use_cache and debug_cache:
                logging.info('LOOKUP CACHE MISS')

            resp = self.conn.request_get('/FlightInfoEx',
                     args={'ident': sanitized_f_num,
                           'howMany': 15})

            # Turn the JSON response into a dict
            flight_data = json.loads(resp['body'])

            if flight_data.get('error'):
                raise FlightNotFoundException(sanitized_f_num)
            else:
                flight_data = flight_data['FlightInfoExResult']['flights']

                # Convert raw flight data to instances of Flight
                flights = []

                for data in flight_data:
                    flight = self.raw_flight_data_to_flight(data, sanitized_f_num)
                    flights.append(flight)

                # Filter out old flights & sort by departure date (earliest first)
                flights = [f for f in flights if not f.is_old_flight]
                flights.sort(key=lambda f: f.scheduled_departure_time)

            if use_cache and not memcache.set(lookup_cache_key, flights,
                                config['flightaware']['flight_lookup_cache_time']):
                logging.error("Unable to cache lookup response!")
            elif use_cache and debug_cache:
                logging.info('LOOKUP CACHE SET')

            # If we're looking for a specific flight, filter the flights
            if find_flight_id:
                flights = [f for f in flights if f.flight_id == find_flight_id]

            return flights

    def process_alert(self, alert_body):
        assert isinstance(alert_body, dict)
        alert_id = alert_body.get('alert_id')
        event_code = alert_body.get('eventcode')
        flight_data = alert_body.get('flight')
        flight_id = flight_data.get('faFlightID')
        origin = flight_data.get('origin')
        destination = flight_data.get('destination')

        if alert_id and event_code and flight_id and origin and destination:
            # Clear memcache keys for flight & airline info
            flight_cache_key = FlightAwareSource.flight_info_cache_key(flight_id)
            airline_cache_key = FlightAwareSource.airline_info_cache_key(flight_id)
            res = memcache.delete_multi([flight_cache_key, airline_cache_key])
            if res:
                logging.info('DELETED FLIGHT INFO CACHE KEYS %s' %
                        [flight_cache_key, airline_cache_key])

            # Get current flight information for the flight mentioned by the alert
            flight_num = utils.flight_num_from_fa_flight_id(flight_id)
            alerted_flight = self.flight_info(flight_id=flight_id,
                                              flight_number=flight_num)

            if alerted_flight:
                # Send out push notifications
                push_types = config['push_types']
                flight_numbers = set()

                # FIXME: Assume iOS user
                for u in iOSUser.users_to_notify(alert_id, flight_id, source=DATA_SOURCES.FlightAware):
                    user_flight_num = u.flight_num_for_flight_id(flight_id) or flight_num
                    flight_numbers.add(utils.sanitize_flight_number(user_flight_num))
                    device_token = u.push_token

                    # Send notifications to each user, only if they want that notification type
                    # Filed
                    if event_code == 'filed' and u.wants_notification_type(push_types.FILED):
                        FlightFiledAlert(device_token, alerted_flight, user_flight_num).push()

                    # Early / delayed / on time
                    elif event_code == 'change' and u.wants_notification_type(push_types.CHANGED):
                        FlightPlanChangeAlert(device_token, alerted_flight, user_flight_num).push()

                    # Take off
                    elif event_code == 'departure' and u.wants_notification_type(push_types.DEPARTED):
                        FlightDepartedAlert(device_token, alerted_flight, user_flight_num).push()

                    # Arrival
                    elif event_code == 'arrival' and u.wants_notification_type(push_types.ARRIVED):
                        FlightArrivedAlert(device_token, alerted_flight, user_flight_num).push()

                    # Diverted
                    elif event_code == 'diverted' and u.wants_notification_type(push_types.DIVERTED):
                        FlightDivertedAlert(device_token, alerted_flight, user_flight_num).push()

                    # Canceled
                    elif event_code == 'cancelled' and u.wants_notification_type(push_types.CANCELED):
                        FlightCanceledAlert(device_token, alerted_flight, user_flight_num).push()

                    else:
                        logging.error('Unknown eventcode.')

                # Clear memcache keys for lookup
                cache_keys = []
                for f_num in flight_numbers:
                    cache_keys.append(FlightAwareSource.lookup_flights_cache_key(f_num))
                if cache_keys:
                    res = memcache.delete_multi(cache_keys)
                    if res:
                        logging.info('DELETED LOOKUP CACHE KEYS %s' % cache_keys)

    def set_alert(self, **kwargs):
        flight_id = kwargs.get('flight_id')
        assert isinstance(flight_id, basestring) and len(flight_id)
        alert_id = None

        # Derive flight num from flight_id so we can use common flight_num for alerts
        flight_num = utils.sanitize_flight_number(
                        utils.flight_num_from_fa_flight_id(flight_id))

        # See if the alert exists (according to our datastore) and is enabled
        alert_id = FlightAwareAlert.existing_enabled_alert(flight_num)

        if isinstance(alert_id, (int, long)) and alert_id > 0:
            if debug_alerts:
                logging.info('EXISTING ALERT FOR %s' % flight_num)
            return alert_id
        else:
            # Set the alert with FlightAware and keep a record of it in our system
            channels = "{16 e_filed e_departure e_arrival e_diverted e_cancelled}"
            resp = self.conn.request_get('/SetAlert',
                     args={'alert_id': 0,
                           'ident': flight_num,
                           'channels': channels,
                           'max_weekly': 1000})

            result = json.loads(resp['body'])
            error = result.get('error')
            alert_id = result.get('SetAlertResult')

            if error or not alert_id:
                raise UnableToSetAlertException(reason=error)
            else:
                if debug_alerts:
                    logging.info('REGISTERED NEW ALERT')
                # Store the alert so we don't recreate it
                if FlightAwareAlert.create_alert(alert_id, flight_num):
                    return alert_id
                else:
                    raise UnableToSetAlertException(reason='Bad Alert Id')

    def get_all_alerts(self):
        resp = self.conn.request_get('/GetAlerts', args={})
        result = json.loads(resp['body'])
        error = result.get('error')
        alert_info = result.get('GetAlertsResult')

        if not error and alert_info:
            alerts = alert_info.get('alerts')
            if debug_alerts:
                logging.info('%d ALERTS ARE SET' % len(alerts))
            return alerts
        else:
            raise UnableToGetAlertsException()

    def delete_alert(self, alert_id):
        resp = self.conn.request_get('/DeleteAlert',
                                    args={'alert_id':alert_id})
        result = json.loads(resp['body'])
        error = result.get('error')
        success = result.get('DeleteAlertResult')

        if not error and success == 1:
            if debug_alerts:
                logging.info('DELETED ALERT %d' % alert_id)

            # Disable the alert in the datastore, remove from users
            if FlightAwareAlert.disable_alert(alert_id):
                iOSUser.remove_alert(alert_id, source=DATA_SOURCES.FlightAware)
                return True
        raise UnableToDeleteAlertException(alert_id)

    def clear_all_alerts(self):
        alerts = self.get_all_alerts()

        # Get all the alert ids
        alert_ids = [alert.get('alert_id') for alert in alerts]

        if debug_alerts:
            logging.info('CLEARING %d ALERTS' % len(alert_ids))

        # Defer removal of all alerts
        deferred.defer(fa_delete_alerts,
                       alert_ids,
                       _queue='admin')

        return {'clearing_alert_count': len(alert_ids)}

    def start_tracking_flight(self, flight_id, flight_num, **kwargs):
        assert isinstance(flight_id, basestring) and len(flight_id)
        assert utils.valid_flight_number(flight_num)

        uuid = kwargs.get('uuid')
        push_token = kwargs.get('push_token')

        # Mark the flight as being tracked
        success = FlightAwareTrackedFlight.create_or_update_flight(flight_id)

        # Save the user's tracking activity if we have a uuid
        if uuid and success:
            alert_id = None
            old_push_token = None

            if push_token:
                alert_id = self.set_alert(flight_id=flight_id)
                existing_user = iOSUser.get_by_uuid(uuid)
                old_push_token = existing_user and existing_user.push_token

            user = iOSUser.track_flight(uuid=uuid,
                                        flight_id=flight_id,
                                        flight_num=flight_num,
                                        push_token=push_token,
                                        alert_id=alert_id,
                                        source=DATA_SOURCES.FlightAware)

            # Tell UrbanAirship about push tokens
            if push_token and (not old_push_token or (old_push_token != push_token)):
                register_token(push_token)
            if old_push_token and push_token != old_push_token:
                deregister_token(old_push_token)

    def stop_tracking_flight(self, flight_id, **kwargs):
        uuid = kwargs.get('uuid')
        flight_num = utils.flight_num_from_fa_flight_id(flight_id)

        # Lookup the alert by flight number
        alert_id = FlightAwareAlert.existing_enabled_alert(flight_num)

        # Mark the user as no longer tracking the flight or the alert
        if uuid:
            iOSUser.untrack_flight(uuid,
                                  flight_id,
                                  alert_id=alert_id,
                                  source=DATA_SOURCES.FlightAware)

        # If there are no more users tracking the alert, delete it
        if alert_id and not iOSUser.alert_in_use(alert_id, source=DATA_SOURCES.FlightAware):
            self.delete_alert(alert_id)

        # See if any users are still tracking the flight
        if not iOSUser.flight_still_tracked(flight_id, source=DATA_SOURCES.FlightAware):
            FlightAwareTrackedFlight.stop_tracking(flight_id)

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
        return 'http://maps.googleapis.com/maps/api/distancematrix'

    def __init__(self):
        from lib.python_rest_client.restful_lib import Connection
        self.conn = Connection(self.base_url)

    def driving_time(self, origin_lat, origin_lon, dest_lat, dest_lon, **kwargs):
        """Implements driving_time method of DrivingTimeDataSource. Supports
        additional kwargs:

        - `no_cache` : Set to True to not use any caching.

        """
        use_cache = not kwargs.get('no_cache')
        time = None
        driving_cache_key = GoogleDistanceSource.driving_cache_key(origin_lat,
                                                                   origin_lon,
                                                                   dest_lat,
                                                                   dest_lon)
        if use_cache:
            time = memcache.get(driving_cache_key)

        if use_cache and time is not None:
            if debug_cache:
                logging.info('DRIVING CACHE HIT')
            return time
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
            resp = self.conn.request_get('/json', args=params)

            # Turn the JSON response into a dict
            result = json.loads(resp.get('body'))
            status = result.get('status')

            if status == 'OK':
                try:
                    time = result['rows'][0]['elements'][0]['duration']['value']
                    if use_cache and not memcache.set(driving_cache_key, time):
                        logging.error("Unable to cache driving time!")
                    if use_cache and debug_cache:
                        logging.info('DRIVING CACHE SET')
                    return time
                except Exception:
                    raise UnknownDrivingTimeException(origin_lat, origin_lon,
                                                      dest_lat, dest_lon)
            elif status == 'REQUEST_DENIED':
                raise DrivingDistanceDeniedException(origin_lat, origin_lon,
                                                     dest_lat, dest_lon)
            elif status == 'OVER_QUERY_LIMIT':
                raise DrivingAPIQuotaException()
            else:
                raise UnknownDrivingTimeException(origin_lat, origin_lon,
                                                  dest_lat, dest_lon)
