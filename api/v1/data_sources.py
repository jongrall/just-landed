#!/usr/bin/env python

"""data_sources.py: This module defines all the data sources that power
the Just Landed app.

Flight data is pulled from either commercial APIs or from the datastore (in the
case of static data such as airport codes and locations). Commercial flight API
data sources are made to conform to a common FlightDataSource interface in
anticipation of possibly switching to alternate data sources in the future.

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

TODO: Document request & response formats.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

import logging
from datetime import datetime, timedelta

# We use memcache service to cache results from 3rd party APIs. This improves
# performance and also reduces our bill :)
from google.appengine.api import memcache, taskqueue
from google.appengine.ext import ndb
from google.appengine.ext.ndb import tasklets
from google.appengine.api.urlfetch import DownloadError
from google.appengine.runtime.apiproxy_errors import CapabilityDisabledError

from config import config, on_development, flightaware_credentials
from connections import Connection, build_url
from models import (Airport, FlightAwareTrackedFlight, FlightAwareAlert, iOSUser,
    Origin, Destination, Flight)
from custom_exceptions import *
from notifications import *

import utils
import aircraft_types

import reporting
from reporting import report_event, report_event_transactionally

FLIGHT_STATES = config['flight_states']
DATA_SOURCES = config['data_sources']
debug_cache = on_development() and False
debug_alerts = on_development() and False
memcache_client = memcache.Client()

###############################################################################
"""Flight Data Sources"""
###############################################################################

class FlightDataSource (object):
    """Defines a flight data source interface that subclasses should implement."""
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
        only flights that have recently landed or are arriving soon.

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

    def untrack_flight(self, flight_id, **kwargs):
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
        assert utils.is_valid_fa_flight_id(flight_id)
        return "%s-flight_info-%s" % (cls.__name__, flight_id)

    @classmethod
    def flight_result_cache_key(cls, flight_id):
        assert utils.is_valid_fa_flight_id(flight_id)
        return "%s-flight_result-%s" % (cls.__name__, flight_id)

    @classmethod
    def lookup_flights_cache_key(cls, flight_num):
        assert utils.valid_flight_number(flight_num)
        return "%s-lookup_flights-%s" % (cls.__name__,
                                        utils.sanitize_flight_number(flight_num))

    @classmethod
    def clear_flight_info_cache(cls, flight_id):
        flight_cache_key = cls.flight_info_cache_key(flight_id)
        flight_result_cache_key = cls.flight_result_cache_key(flight_id)
        keys = [flight_cache_key, flight_result_cache_key]

        # Optimization: multi-key delete
        if memcache.delete_multi(keys) and debug_cache:
            logging.info('DELETED FLIGHT INFO CACHE KEYS %s' % keys)

    @classmethod
    def clear_flight_lookup_cache(cls, flight_numbers=[]):
        # De-dupe
        flight_numbers = set(flight_numbers)
        cache_keys = [cls.lookup_flights_cache_key(f_num) for f_num in flight_numbers]

        if cache_keys:
            # Optimization: Multi-key delete
            if memcache.delete_multi(cache_keys) and debug_cache:
                logging.info('DELETED LOOKUP CACHE KEYS %s' % cache_keys)

    @property
    def base_url(self):
        return "http://flightxml.flightaware.com/json/FlightXML2" # HTTPS supported but not used

    @property
    def api_key_mapping(self):
        return config['flightaware']['key_mapping']

    def __init__(self):
        uname, pwd = flightaware_credentials()
        self.conn = Connection(self.base_url, username=uname, password=pwd)

    @ndb.tasklet
    def do_track(self, request, flight_id, uuid, user=None):
        assert request
        assert utils.is_valid_uuid(uuid)
        assert utils.is_valid_fa_flight_id(flight_id)
        user = user or (yield iOSUser.get_by_uuid(uuid))
        assert user

        # Don't track if they're no longer tracking this flight or if it's pointless
        if (not user.is_tracking_flight(flight_id) or not user.push_enabled or
            not user.has_unsent_reminders):
            return # We're done

        user_flight_num = user.flight_num_for_flight_id(flight_id)

        # Fire off a /track for the user, which will update their reminders
        url_scheme = (on_development() and 'http') or 'https'
        track_url = request.uri_for('track',
                                    flight_number=user_flight_num,
                                    flight_id=flight_id,
                                    _full=True,
                                    _scheme=url_scheme)

        req_args =  {'push_token' : user.push_token or '',
                    'latitude' : user.last_known_location and user.last_known_location.lat,
                    'longitude' : user.last_known_location and user.last_known_location.lon,
        }

        full_track_url = build_url(track_url, '', args=req_args)

        to_sign = request.uri_for('track',
                                   flight_number=user_flight_num,
                                   flight_id=flight_id)

        to_sign = to_sign + '?' + utils.sorted_request_params(req_args)
        sig = utils.api_query_signature(to_sign, client='Server')
        headers = {'X-Just-Landed-UUID' : user.key.string_id(),
                   'X-Just-Landed-Signature' : sig}
        ctx = ndb.get_context()
        yield ctx.urlfetch(full_track_url,
                            headers=headers,
                            deadline=120,
                            validate_certificate=full_track_url.startswith('https'))

    def raw_flight_data_to_flight(self, data, sanitized_flight_num, airport_info={}, return_none_on_error=False):
        try:
            if data and utils.valid_flight_number(sanitized_flight_num):
                # Keep a subset of the response fields
                fields = config['flightaware']['flight_info_fields']
                data = utils.sub_dict_strict(data, fields)

                # Map the response dict keys
                data = utils.map_dict_keys(data, self.api_key_mapping)

                origin_code = data['origin']
                destination_code = data['destination']

                # Optimization: fetch in parallel
                origin_info = airport_info.get(origin_code)
                destination_info = airport_info.get(destination_code)

                # Give up if the origin or destination is missing
                if origin_info is None or destination_info is None:
                    return

                origin, destination = Origin(origin_info), Destination(destination_info)

                flight = Flight(data)
                flight.flight_number = sanitized_flight_num
                flight.origin = origin
                flight.destination = destination

                # Convert flight duration to integer number of seconds
                ete = data['scheduledFlightDuration']
                try:
                    flight.scheduled_flight_duration = utils.fa_flight_ete_to_duration(ete)
                except ValueError:
                    raise FlightDurationUnknown(flight_id=flight.flight_id, ete=ete)

                # Convert aircraft type
                flight.aircraft_type = aircraft_types.type_to_major_type(data.get('aircraftType'))

                # Clean up airport names (take FlightAware's, dump ours)
                flight.origin.name = utils.proper_airport_name(data['originName'])
                flight.destination.name = utils.proper_airport_name(data['destinationName'])

                # Dispose of states e.g. 'San Francisco, CA' => 'San Francisco'
                flight.origin.city = flight.origin.city.split(', ')[0]
                flight.destination.city = flight.destination.city.split(', ')[0]

                return flight

        except FlightDurationUnknown as e:
            if return_none_on_error:
                logging.exception(e) # Report it, but recover gracefully
                utils.sms_report_exception(e)
                return
            else:
                raise # Re-raise the exception

    @ndb.tasklet
    def airport_info(self, airport_code, flight_num='', raise_not_found=True):
        """Looks up information about an airport using its ICAO or IATA code."""
        try:
            if not (utils.is_valid_icao(airport_code) or utils.is_valid_iata(airport_code)):
                raise AirportNotFoundException(airport_code, flight_num)

            # Optimization: check the DB first (faster, cheaper than FA)
            airport = ((yield Airport.get_by_icao_code(airport_code)) or
                        (yield Airport.get_by_iata_code(airport_code)))

            if airport:
                raise tasklets.Return(airport.dict_for_client())

            elif utils.is_valid_icao(airport_code):
                logging.warning('AIRPORT NOT IN DB: %s', airport_code)

                # Check FlightAware for the AiportInfo
                airport_cache_key = FlightAwareSource.airport_info_cache_key(airport_code)

                # Optimization: check memcache for the airport info
                airport = memcache.get(airport_cache_key)

                if airport is not None:
                    if debug_cache:
                        logging.info('AIRPORT INFO CACHE HIT')
                    raise tasklets.Return(airport)
                else:
                    if debug_cache:
                        logging.info('AIRPORT INFO CACHE MISS')

                    try:
                        result = yield self.conn.get_json('/AirportInfo',
                                                        args={'airportCode':airport_code})
                    except DownloadError:
                        raise FlightAwareUnavailableError()

                    # report_event(reporting.FA_AIRPORT_INFO)

                    if result.get('error'):
                        raise AirportNotFoundException(airport_code, flight_num)
                    else:
                        airport = result['AirportInfoResult']

                        # Filter out fields we don't want
                        fields = config['flightaware']['airport_info_fields']
                        airport = utils.sub_dict_strict(airport, fields)

                        # Map field names
                        airport = utils.map_dict_keys(airport, self.api_key_mapping)

                        # Add ICAO code back in (we don't have IATA)
                        airport['icaoCode'] = airport_code
                        airport['iataCode'] = None

                        # Add placeholder altitude (AirportInfo doesn't support it)
                        airport['altitude'] = 0

                        # Make sure the name is well formed
                        airport['name'] = utils.proper_airport_name(airport['name'])

                        # Round lat & long
                        airport['latitude'] = utils.round_coord(airport['latitude'])
                        airport['longitude'] = utils.round_coord(airport['longitude'])

                        if not memcache.set(airport_cache_key, airport):
                            logging.error("Unable to cache airport info!")
                        elif debug_cache:
                            logging.info('AIRPORT INFO CACHE SET')

                        raise tasklets.Return(airport)
            else:
                raise AirportNotFoundException(airport_code, flight_num)
        except AirportNotFoundException as e:
            if raise_not_found:
                raise # Re-raise
            else:
                raise tasklets.Return() # Return none


    @ndb.tasklet
    def register_alert_endpoint(self, **kwargs):
        endpoint_url = config['flightaware']['alert_endpoint']

        try:
            result = yield self.conn.get_json('/RegisterAlertEndpoint',
                                            args={'address': endpoint_url,
                                                  'format_type': 'json/post'})
        except DownloadError:
            raise FlightAwareUnavailableError()

        error = result.get('error')

        if not error and result.get('RegisterAlertEndpointResult') == 1:
            raise tasklets.Return({'endpoint_url' : endpoint_url})
        else:
            raise UnableToSetEndpointException(endpoint=endpoint_url)

    @ndb.tasklet
    def flight_info(self, flight_id, **kwargs):
        """Implements flight_info method of FlightDataSource and requires
        additional kwargs:

        - `flight_number` : Required by FlightAware to lookup flights.
        """
        flight_number = kwargs.get('flight_number')

        if not utils.valid_flight_number(flight_number):
            raise InvalidFlightNumberException(flight_number)

        if not utils.is_valid_fa_flight_id(flight_id):
            raise FlightNotFoundException(flight_number)

        flight_cache_key = FlightAwareSource.flight_info_cache_key(flight_id)
        sanitized_f_num = utils.sanitize_flight_number(flight_number)

        # Optimization: check memcache first
        flight = memcache.get(flight_cache_key)

        if flight:
            if debug_cache:
                logging.info('FLIGHT CACHE HIT')
            if flight.is_old_flight:
                raise OldFlightException(flight_number=flight_number,
                                         flight_id=flight_id)
            flight.flight_number = sanitized_f_num
            raise tasklets.Return(flight)
        else:
            if debug_cache:
                logging.info('FLIGHT CACHE MISS')

            # Optimization: check to see if we have cached flight info from recent lookup
            flight_result_cache_key = FlightAwareSource.flight_result_cache_key(flight_id)
            flight = memcache.get(flight_result_cache_key)
            airline_data = None

            if flight:
                # We have a cached flight from lookup but still need airline info
                if debug_cache:
                    logging.info('FLIGHT RESULT CACHE HIT')

                try:
                    airline_data = yield self.conn.get_json('/AirlineFlightInfo',
                                                        args={'faFlightID': flight_id,
                                                              'howMany': 1})
                    # report_event(reporting.FA_AIRLINE_FLIGHT_INFO)
                except DownloadError:
                    raise FlightAwareUnavailableError()

                if airline_data.get('error'):
                    raise TerminalsUnknownException(flight_id)
            else:
                if debug_cache:
                    logging.info('FLIGHT RESULT CACHE MISS')
                to_fetch = []
                to_fetch.append(self.conn.get_json('/FlightInfoEx',
                                                    args={'ident': flight_id}))
                to_fetch.append(self.conn.get_json('/AirlineFlightInfo',
                                                        args={'faFlightID': flight_id,
                                                              'howMany': 1}))
                try:
                    # Optimization: parallel fetch
                    flight_data, airline_data = yield to_fetch
                    # report_event(reporting.FA_FLIGHT_INFO_EX)
                    # report_event(reporting.FA_AIRLINE_FLIGHT_INFO)
                except DownloadError:
                    raise FlightAwareUnavailableError()

                if flight_data.get('error'):
                    raise FlightNotFoundException(sanitized_f_num)
                if airline_data.get('error'):
                    raise TerminalsUnknownException(flight_id)

                # First flight returned is the match
                flight_data = flight_data['FlightInfoExResult']['flights'][0]

                # Get information on all the airports involved
                airport_codes = [flight_data['origin'], flight_data['destination']]
                airports = yield [self.airport_info(code, sanitized_f_num) for code in airport_codes]
                airport_info = dict(zip(airport_codes, airports))
                flight = self.raw_flight_data_to_flight(flight_data, sanitized_f_num, airport_info)

            # We now have flight and airline_data
            fields = config['flightaware']['airline_flight_info_fields']
            airline_info = airline_data['AirlineFlightInfoResult']
            airline_info = utils.sub_dict_strict(airline_info, fields)
            airline_info = utils.map_dict_keys(airline_info, self.api_key_mapping)

            # Missing flight indicates probably tracking an old flight
            if not flight or not airline_info or flight.is_old_flight:
                raise OldFlightException(flight_number=flight_number,
                                         flight_id=flight_id)

            # Add in the airline info and user-entered flight number
            flight.flight_number = sanitized_f_num
            flight.origin.terminal = airline_info['originTerminal']
            flight.destination.terminal = airline_info['destinationTerminal']
            flight.destination.bag_claim = airline_info['bagClaim']
            flight.destination.gate = airline_info['destinationGate']

            # Cache the result
            if not memcache.set(flight_cache_key, flight,
                                time=config['flightaware']['flight_cache_time']):
                logging.error('Unable to cache flight info!')
            elif debug_cache:
                logging.info('FLIGHT CACHE SET')

            raise tasklets.Return(flight)

    @ndb.tasklet
    def lookup_flights(self, flight_number, **kwargs):
        """Concrete implementation of lookup_flights of FlightDataSource."""
        sanitized_f_num = utils.sanitize_flight_number(flight_number)
        lookup_cache_key = FlightAwareSource.lookup_flights_cache_key(sanitized_f_num)

        # Optimization: check memcache for flight lookup results
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

            flight_data = []
            offset = 0

            while len(flight_data) % 15 == 0 and len(flight_data) < config['max_lookup_results']:
                try:
                    data = yield self.conn.get_json('/FlightInfoEx',
                                                    args={'ident': sanitized_f_num,
                                                    'howMany': 15,
                                                    'offset' : offset})
                except DownloadError:
                    raise FlightAwareUnavailableError()

                # report_event(reporting.FA_FLIGHT_INFO_EX)

                if data.get('error'):
                    raise FlightNotFoundException(sanitized_f_num)

                data = data['FlightInfoExResult']['flights']

                # Filter out old flights before conversion to Flight
                current_flights = [f for f in data if not utils.is_old_fa_flight(f)]
                flight_data.extend(current_flights)

                # If we have some old flights, or less than 15 flights, we're done
                if len(current_flights) < 15:
                    break
                else:
                    offset += 15

            # Get information on all the airports involved
            airport_codes = set()
            for data in flight_data:
                airport_codes.add(data['origin'])
                airport_codes.add(data['destination'])
            airport_codes = list(airport_codes)

            # Optimization: yield all the airports in parallel, don't raise on not found
            airports = yield [self.airport_info(code, sanitized_f_num, raise_not_found=False)
                                for code in airport_codes]
            airport_info = dict(zip(airport_codes, airports))

            # Detect missing airports and report them
            for code, airport in airport_info.iteritems():
                if airport is None:
                    e = AirportNotFoundException(code, sanitized_f_num)
                    logging.exception(e)
                    utils.sms_report_exception(e)

            # Convert raw flight data to instances of Flight
            flights = [self.raw_flight_data_to_flight(data,
                                                      sanitized_f_num,
                                                      airport_info,
                                                      return_none_on_error=True)
                                for data in flight_data]
            flights = [f for f in flights if f is not None] # Filter out bad results

            # If there are no good flights left, raise FlightNotFound
            if len(flights) == 0:
                raise FlightNotFoundException(sanitized_f_num)

            # Optimization: cache flight info so /track doesn't have cache miss on selecting a flight
            flights_to_cache = {}
            for f in flights:
                cache_key = FlightAwareSource.flight_result_cache_key(f.flight_id)
                flights_to_cache[cache_key] = f

            # Optimization: set multiple memcache keys in one async rpc
            cache_flights_rpc = memcache_client.set_multi_async(
                flights_to_cache,
                time=config['flightaware']['flight_from_lookup_cache_time'])

            # Sort by departure date (earliest first)
            flights.sort(key=lambda f: f.scheduled_departure_time)

            if not memcache.set(lookup_cache_key, flights,
                                config['flightaware']['flight_lookup_cache_time']):
                logging.error('Unable to cache lookup response!')
            elif debug_cache:
                logging.info('LOOKUP CACHE SET')

            def flights_cached_successfully():
                result = cache_flights_rpc.get_result()
                if result is None:
                    return False
                status_set = set(result.values())
                return ('ERROR' not in status_set) and ('NOT_STORED' not in status_set)

            if not flights_cached_successfully():
                logging.error('Unable to cache some flight info on lookup.')
            elif debug_cache:
                logging.info('CACHED %d FLIGHTS FROM LOOKUP', len(flights))

            raise tasklets.Return(flights)

    @ndb.tasklet
    def process_alert(self, alert_body, request):
        if not utils.is_valid_fa_alert_body(alert_body):
            logging.info(alert_body)
            raise InvalidAlertCallbackException()

        alert_id = alert_body['alert_id']
        event_code = alert_body['eventcode']
        flight_id = alert_body['flight']['faFlightID']
        report_event(reporting.FA_FLIGHT_ALERT_CALLBACK)

        # Cache freshness: clear memcache keys for flight info
        FlightAwareSource.clear_flight_info_cache(flight_id)

        # Lookup the alert
        alert = yield FlightAwareAlert.get_by_alert_id(alert_id)

        # Only process the alert if we still care about it and we have the necessary data
        if alert and alert.is_enabled:

            # Get current flight information for the flight mentioned by the alert
            flight_num = utils.flight_num_from_fa_flight_id(flight_id)

            # Optimization: parallel fetch
            alerted_flight = None
            stored_flight = None

            if event_code == 'cancelled':
                # Canceled flights can't be looked up
                stored_flight = yield FlightAwareTrackedFlight.get_flight_by_id(flight_id)
                alerted_flight = stored_flight # Use the stored flight data
            else:
                alerted_flight, stored_flight = yield (self.flight_info(flight_id=flight_id, flight_number=flight_num),
                                                        FlightAwareTrackedFlight.get_flight_by_id(flight_id))

            if alerted_flight and stored_flight:
                # Reconstruct the flight from the datastore so we can compare before/after alert
                orig_flight = Flight.from_dict(stored_flight.last_flight_data)
                orig_flight.scheduled_flight_duration = stored_flight.orig_flight_duration
                orig_flight.scheduled_departure_time = stored_flight.orig_departure_time
                alerted_flight.scheduled_flight_duration = stored_flight.orig_flight_duration
                alerted_flight.scheduled_departure_time = stored_flight.orig_departure_time

                terminal_changed = alerted_flight.destination.terminal != orig_flight.destination.terminal

                # Reporting (once per callback)
                if event_code in ['change', 'minutes_out']:
                    if terminal_changed:
                        report_event(reporting.FLIGHT_TERMINAL_CHANGE)
                    else:
                        report_event(reporting.FLIGHT_CHANGE)
                elif event_code == 'departure':
                    report_event(reporting.FLIGHT_TAKEOFF)
                elif event_code == 'arrival':
                    report_event(reporting.FLIGHT_LANDED)
                elif event_code == 'diverted':
                    report_event(reporting.FLIGHT_DIVERTED)
                elif event_code == 'cancelled':
                    report_event(reporting.FLIGHT_CANCELED)

                push_types = config['push_types']

                @ndb.tasklet
                def notify_cbk(u):
                    user_flight_num = u.flight_num_for_flight_id(flight_id) or flight_num
                    device_token = u.push_token

                    # Send notifications to each user, only if they want that notification type
                    # Early / delayed / on time
                    if event_code in ['change', 'minutes_out'] and u.wants_notification_type(push_types.CHANGED):
                        if terminal_changed:
                            TerminalChangeAlert(device_token, alerted_flight, user_flight_num).push()
                        else:
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
                        logging.info('Unhandled eventcode: %s' % event_code)

                    # Fire off a /track for the user, which will update their reminders
                    yield self.do_track(request, flight_id, u.key.string_id(), user=u)

                    # Return the user-entered flight number so we can clear it from the cache
                    raise tasklets.Return(utils.sanitize_flight_number(user_flight_num))

                # FIXME: Assumes iOS user
                notify_qry = iOSUser.users_to_notify_qry(alert, flight_id, source=DATA_SOURCES.FlightAware)
                flight_numbers = yield notify_qry.map_async(notify_cbk)

                # Cache freshness: clear memcache keys for lookup
                FlightAwareSource.clear_flight_lookup_cache(flight_numbers)

    @ndb.tasklet
    def set_alert(self, **kwargs):
        flight_id = kwargs.get('flight_id')
        assert utils.is_valid_fa_flight_id(flight_id)
        flight_num = utils.flight_num_from_fa_flight_id(flight_id)
        assert utils.valid_flight_number(flight_num)

        # Set the alert with FlightAware and keep a record of it in our system
        channels = "{16 e_filed e_departure e_arrival e_diverted e_cancelled}"
        try:
            result = yield self.conn.get_json('/SetAlert',
                                args={'alert_id': 0,
                                    'ident': flight_num,
                                    'channels': channels,
                                    'max_weekly': 1000})
        except DownloadError:
            raise FlightAwareUnavailableError()

        error = result.get('error')
        alert_id = result.get('SetAlertResult')

        if not error and alert_id:
            # report_event(reporting.FA_SET_ALERT)
            if debug_alerts:
                logging.info('REGISTERED NEW ALERT')

            # Store the alert so we don't recreate it
            alert = yield FlightAwareAlert.create_or_reuse_alert(flight_id, alert_id)
            if alert:
                raise tasklets.Return(alert)
            else:
                raise UnableToSetAlertException(reason='Unable to create or reuse alert.')
        else:
            raise UnableToSetAlertException(reason=(error or 'Bad Alert Id'))

    @ndb.tasklet
    def get_all_alerts(self):
        try:
            result = yield self.conn.get_json('/GetAlerts', args={})
        except DownloadError:
            raise FlightAwareUnavailableError()

        # report_event(reporting.FA_GET_ALERTS)
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
        try:
            result = yield self.conn.get_json('/DeleteAlert',
                                            args={'alert_id':alert_id})
        except DownloadError:
            raise FlightAwareUnavailableError()

        # report_event(reporting.FA_DELETED_ALERT)
        error = result.get('error')
        success = result.get('DeleteAlertResult')

        if not error and success == 1:
            if debug_alerts:
                logging.info('DELETED ALERT %d' % alert_id)
            raise tasklets.Return(True)
        else:
            raise UnableToDeleteAlertException(alert_id)

    @ndb.tasklet
    def delete_alerts(self, alert_ids, orphaned=False):
        # Note: can't be run in a transaction - easily too many alerts / users per alert
        for alert_id in alert_ids:
            # See if the alert exists
            alert = yield FlightAwareAlert.get_by_alert_id(alert_id)
            futs = []
            if alert:
                futs.append(alert.disable())
                futs.append(iOSUser.clear_alert_from_users(alert))
            futs.append(self.delete_alert(alert_id))

            # Optimization: parallel yield
            yield futs
            # if orphaned:
            #     report_event(reporting.DELETED_ORPHANED_ALERT)

    @ndb.tasklet
    def clear_all_alerts(self):
        alerts = yield self.get_all_alerts()
        alert_ids = [alert.get('alert_id') for alert in alerts]
        if debug_alerts:
            logging.info('CLEARING %d ALERTS' % len(alert_ids))

        # Optimizaiton: defer removal of all alerts
        alert_ids = [str(alert_id) for alert_id in alert_ids if isinstance(alert_id, (int, long))]
        alert_list = ','.join(alert_ids)
        task = taskqueue.Task(payload=alert_list)
        taskqueue.Queue('clear-alerts').add(task)
        raise tasklets.Return({'clearing_alert_count': len(alert_ids)})

    @ndb.tasklet
    def track_flight(self, flight_data, **kwargs):
        flight = Flight.from_dict(flight_data)
        uuid = kwargs.get('uuid')
        push_token = kwargs.get('push_token')
        user_latitude = kwargs.get('user_latitude')
        user_longitude = kwargs.get('user_longitude')
        driving_time = kwargs.get('driving_time')
        flight_id = flight.flight_id

        @ndb.tasklet
        def track_txn():
            # Optimization: parallel fetch
            tracked_flight, alert, existing_user = yield [FlightAwareTrackedFlight.get_flight_by_id(flight_id),
                                            FlightAwareAlert.get_by_flight_id(flight_id),
                                            iOSUser.get_by_uuid(uuid)]

            # Only set an alert_id if we don't have one or it isn't enabled
            futs = []
            if not alert or not alert.is_enabled:
                futs.append(self.set_alert(flight_id=flight_id))

            # Mark the flight as being tracked
            if not tracked_flight:
                futs.append(FlightAwareTrackedFlight.create_flight(flight))
                report_event_transactionally(reporting.NEW_FLIGHT)
            else:
                flight_data = flight.to_dict()
                # Optimization: only write the flight data if it has changed
                if flight_data != tracked_flight.last_flight_data:
                    futs.append(tracked_flight.update_last_flight_data(flight_data))

            # Optimization: parallel yield
            if futs:
                results = yield futs
                for r in results:
                    if isinstance(r, FlightAwareAlert):
                        alert = r
                    elif isinstance(r, FlightAwareTrackedFlight):
                        tracked_flight = r

            # Save the user's tracking activity if we have a uuid
            old_push_token = existing_user and existing_user.push_token
            already_tracking = existing_user and existing_user.is_tracking_flight(flight_id)

            user = yield iOSUser.track_flight(uuid,
                                       flight,
                                       tracked_flight,
                                       flight.flight_number,
                                       user_latitude=user_latitude,
                                       user_longitude=user_longitude,
                                       driving_time=driving_time,
                                       push_token=push_token,
                                       alert=alert,
                                       source=DATA_SOURCES.FlightAware)

            # If the user is tracking any other flights than this one, untrack them
            if user:
                for f in user.tracked_flights:
                    f_id = f.flight.string_id()
                    if f_id != flight_id:
                        # untrack
                        untrack_task = taskqueue.Task(params = {
                            'flight_id' : f_id,
                            'uuid' : uuid,
                        })
                        taskqueue.Queue('untrack').add(untrack_task)

            # Tell UrbanAirship about expired push tokens
            if old_push_token and push_token != old_push_token:
                deregister_token(old_push_token, _transactional=True)

            # Tell UA about the push token
            if push_token:
                register_token(push_token, _transactional=True, force=(not already_tracking))

            # Schedule /track to happen a couple of times in the future before
            # landing - this will ensure that their leave alerts are accurate
            # even if the user is not checking on it. Only do this the first
            # time they track this flight otherwise it will trigger a flood of
            # delayed tracking tasks.
            if driving_time and not already_tracking:
                now = datetime.utcnow()
                # Allow for 75% fluctuation in driving time
                first_check_time = utils.leave_now_time(flight,
                                                        (driving_time * 1.75))

                # Check again at leave soon minus 1 min, want to beat the cron job
                second_check_time = utils.leave_soon_time(flight,
                                                          driving_time) - timedelta(seconds=60)

                check_times = [first_check_time, second_check_time]
                check_times = [ct for ct in check_times if ct > now]

                for ct in check_times:
                    check = taskqueue.Task(params={
                                                    'flight_id' : flight_id,
                                                    'uuid' : uuid
                                                    }, eta=ct)
                    taskqueue.Queue('delayed-track').add(check, transactional=True)

        # Checking write support guards against flood of set_alerts in read-only situation
        writes_enabled = utils.datastore_writes_enabled()
        tasks_enabled = utils.taskqueue_enabled()
        valid_uuid = utils.is_valid_uuid(uuid)

        if writes_enabled and tasks_enabled and valid_uuid:
            # TRANSACTIONAL TRACKING!
            yield ndb.transaction_async(track_txn, xg=True)
        elif not writes_enabled:
            raise CapabilityDisabledError('Datastore is in read-only mode.')
        elif not tasks_enabled:
            raise CapabilityDisabledError('Taskqueue is unavailable.')
        elif not valid_uuid:
            logging.error('Track called with invalid UUID.')

    @ndb.tasklet
    def untrack_flight(self, flight_id, **kwargs):
        uuid = kwargs.get('uuid')

        @ndb.tasklet
        def untrack_txn():
            # Lookup any existing alert by flight number
            alert = yield FlightAwareAlert.get_by_flight_id(flight_id)
            flight = None

            # Mark the user as no longer tracking the flight or the alert
            if utils.is_valid_uuid(uuid):
                flight, alert = yield iOSUser.stop_tracking_flight(uuid,
                                                            flight_id,
                                                            alert=alert,
                                                            source=DATA_SOURCES.FlightAware)

            # If there are no more users tracking the alert, delete it
            if alert and alert.num_users_with_alert == 0:
                yield self.delete_alert(alert.alert_id)

            # Cache freshness: If there are no more users tracking the flight, clear the cache
            # since we won't get any alerts in the meantime that would invalidate the cache
            if not flight or not flight.is_tracking:
                FlightAwareSource.clear_flight_info_cache(flight_id)

        # Checking write support guards against flood of delete_alerts in read-only situation
        if utils.datastore_writes_enabled():
            user = utils.is_valid_uuid(uuid) and (yield iOSUser.get_by_uuid(uuid))
            user_flight_num = user and user.flight_num_for_flight_id(flight_id)
            clear_lookup_cache = user_flight_num and not (yield iOSUser.multiple_users_tracking_flight_num(user_flight_num))

            # TRANSACTIONAL UNTRACKING!
            yield ndb.transaction_async(untrack_txn, xg=True)

            # Cache freshness: clear lookup cache if nobody is tracking the flight ident anymore
            if clear_lookup_cache:
                FlightAwareSource.clear_flight_lookup_cache([user_flight_num])
        else:
            raise CapabilityDisabledError('Datastore is in read-only mode.')

    def authenticate_remote_request(self, request):
        """Returns True if the incoming request is in fact from the trusted
        3rd party datasource, False otherwise."""
        remote_addr = request.remote_addr
        return utils.is_trusted_flightaware_host(remote_addr)


###############################################################################
"""Driving Time Data Sources"""
###############################################################################

class DrivingTimeDataSource (object):
    """A class that defines a DrivingTimeDataSource interface that driving time
    data sources should implement."""
    @classmethod
    def driving_cache_key(cls, orig_lat, orig_lon, dest_lat, dest_lon):
        # Optimization: rounding the coordinates has the effect of re-using
        # driving distance calculations for locations close to each other
        return '%s-driving_time-%f,%f,%f,%f' % (
                cls.__name__,
                utils.round_coord(orig_lat, sf=3),
                utils.round_coord(orig_lon, sf=3),
                utils.round_coord(dest_lat, sf=3),
                utils.round_coord(dest_lon, sf=3),
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
        return 'http://maps.googleapis.com/maps/api/distancematrix' # HTTPS supported but not used

    def __init__(self):
        self.conn = Connection(self.base_url)

    @ndb.tasklet
    def driving_time(self, origin_lat, origin_lon, dest_lat, dest_lon, **kwargs):
        """Implements driving_time method of DrivingTimeDataSource."""
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

            try:
                data = yield self.conn.get_json('/json', args=params)
            except DownloadError:
                raise GoogleDistanceAPIUnavailableError()

            # report_event(reporting.GOOG_FETCH_DRIVING_TIME)
            status = data.get('status')

            if status == 'OK':
                try:
                    elt_status = data['rows'][0]['elements'][0]['status']
                    if elt_status in ['NOT_FOUND', 'ZERO_RESULTS']:
                        raise NoDrivingRouteException(404, origin_lat, origin_lon,
                                                      dest_lat, dest_lon)

                    time = data['rows'][0]['elements'][0]['duration']['value']

                    # Optimization: Cache data, not using traffic info, so data good indefinitely
                    if not memcache.set(driving_cache_key, time):
                        logging.error("Unable to cache driving time!")
                    elif debug_cache:
                        logging.info('DRIVING CACHE SET')
                    raise tasklets.Return(time)
                except (KeyError, IndexError, TypeError):
                    raise MalformedDrivingDataException(origin_lat, origin_lon,
                                                      dest_lat, dest_lon, data)
            elif status == 'REQUEST_DENIED':
                raise DrivingTimeUnauthorizedException()
            elif status in ['INVALID_REQUEST', 'MAX_ELEMENTS_EXCEEDED']:
                raise NoDrivingRouteException(400, origin_lat, origin_lon,
                                              dest_lat, dest_lon)
            elif status == 'OVER_QUERY_LIMIT':
                raise DrivingAPIQuotaException()
            else:
                raise GoogleDistanceAPIUnavailableError()


class BingMapsDistanceSource (DrivingTimeDataSource):
    """Concrete subclass of DrivingTimeDataSource that pulls its data from the
    commercial Bing Maps API:

    http://msdn.microsoft.com/en-us/library/ff701722.aspx

    """
    @property
    def base_url(self):
        return 'http://dev.virtualearth.net/REST/v1' # HTTPS supported but not used

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

            try:
                data = yield self.conn.get_json('/Routes', args=params)
            except DownloadError:
                raise BingMapsUnavailableError()

            # report_event(reporting.BING_FETCH_DRIVING_TIME)
            status = data.get('statusCode')

            if status == 200:
                try:
                    time = data['resourceSets'][0]['resources'][0]['travelDuration']
                    # Optimization: cache driving time w/ traffic
                    if not memcache.set(driving_cache_key, time, config['traffic_cache_time']):
                        logging.error("Unable to cache driving time!")
                    elif debug_cache:
                        logging.info('DRIVING CACHE SET')
                    raise tasklets.Return(time)
                except (KeyError, IndexError, TypeError):
                    raise MalformedDrivingDataException(origin_lat, origin_lon,
                                                      dest_lat, dest_lon, data)
            elif status == 401:
                raise DrivingTimeUnauthorizedException()
            elif status in [400, 404]:
                raise NoDrivingRouteException(status, origin_lat, origin_lon,
                                              dest_lat, dest_lon)
            elif status == 403:
                raise DrivingAPIQuotaException()
            else:
                raise BingMapsUnavailableError()