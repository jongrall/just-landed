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
from google.appengine.runtime.apiproxy_errors import DeadlineExceededError

from config import config, on_development, flightaware_credentials
from api.v1.connections import Connection, build_url
from models.v2 import (Airport, Airline, FlightAwareTrackedFlight, iOSUser,
    Origin, Destination, Flight)
from custom_exceptions import *
from notifications import *

import utils
from data import aircraft_types

import reporting
from reporting import report_event, log_event_transactionally, FlightTrackedEvent

FLIGHT_STATES = config['flight_states']
PUSH_TYPES = config['push_types']
debug_cache = on_development() and False
debug_alerts = on_development() and False
memcache_client = memcache.Client()

###############################################################################
# Flight Data Sources
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
# FlightAware
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
            logging.info('DELETED FLIGHT INFO CACHE KEYS %s', keys)

    @classmethod
    def clear_flight_lookup_cache(cls, flight_numbers=[]):
        # De-dupe
        flight_numbers = set(flight_numbers)
        cache_keys = [cls.lookup_flights_cache_key(f_num) for f_num in flight_numbers]

        if cache_keys:
            # Optimization: Multi-key delete
            if memcache.delete_multi(cache_keys) and debug_cache:
                logging.info('DELETED LOOKUP CACHE KEYS %s', cache_keys)

    @property
    def base_url(self):
        return "http://flightxml.flightaware.com/json/FlightXML2" # HTTPS supported but not used

    @property
    def api_key_mapping(self):
        return config['flightaware']['key_mapping']

    def __init__(self):
        super(FlightAwareSource, self).__init__()
        uname, pwd = flightaware_credentials()
        self.conn = Connection(self.base_url, username=uname, password=pwd)

    @ndb.tasklet
    def do_track(self, request_handler, flight_id, uuid):
        assert request_handler
        assert utils.is_valid_uuid(uuid)
        assert utils.is_valid_fa_flight_id(flight_id)
        # FIXME: Assumes iOS
        # Optimization: parallel yield
        u_key = ndb.Key(iOSUser, uuid)
        flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id, parent=u_key)
        user, flight = yield ndb.get_multi_async([u_key, flight_key])
        assert user

        # Don't track if we don't need to
        if (not flight or not user.push_enabled or not flight.has_unsent_reminders):
            raise tasklets.Return()

        user_flight_num = flight.user_flight_num

        # Fire off a /track for the user, which will update their reminders
        url_scheme = (on_development() and 'http') or 'https'
        track_url = request_handler.uri_for('track',
                                    flight_number=user_flight_num,
                                    flight_id=flight_id,
                                    _full=True,
                                    _scheme=url_scheme)

        req_args =  {'push_token' : user.push_token,
                    'latitude' : user.last_known_location and user.last_known_location.lat,
                    'longitude' : user.last_known_location and user.last_known_location.lon,
                    # FIXME: Assumes grouped settings for reminders & flight events
                    'send_reminders' : int(user.wants_notification_type(PUSH_TYPES.LEAVE_NOW)),
                    'send_flight_events' : int(user.wants_notification_type(PUSH_TYPES.ARRIVED)),
                    'play_flight_sounds' : int(user.wants_flight_sounds()),
        }

        full_track_url = build_url(track_url, '', args=req_args)

        to_sign = request_handler.uri_for('track',
                                   flight_number=user_flight_num,
                                   flight_id=flight_id)

        to_sign = to_sign + '?' + utils.sorted_request_params(req_args)
        sig = utils.api_query_signature(to_sign, client='Server')
        headers = {'X-Just-Landed-UUID' : uuid,
                   'X-Just-Landed-Signature' : sig}
        ctx = ndb.get_context()

        yield ctx.urlfetch(full_track_url,
                            headers=headers,
                            deadline=120,
                            validate_certificate=full_track_url.startswith('https'))

    @ndb.tasklet
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

                # Figure out the airline name
                airline_code, f_num_digits = utils.split_flight_number(sanitized_flight_num)
                airline_name = ''
                if airline_code is not None:
                    airline_name = yield Airline.name_for_code(airline_code)
                flight.airline_name = airline_name

                # Figure out the flight name
                if airline_name:
                    flight.flight_name = '%s %s' % (airline_name, f_num_digits)
                else:
                    flight.flight_name = ''

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

                raise tasklets.Return(flight)

        except FlightDurationUnknown as e:
            if return_none_on_error:
                logging.exception(e) # Report it, but recover gracefully
                utils.sms_report_exception(e)
                raise tasklets.Return()
            else:
                raise e # Re-raise the exception

    @ndb.tasklet
    def airport_info(self, airport_code, flight_num='', raise_not_found=True):
        """Looks up information about an airport using its ICAO or IATA code."""
        try:
            airport = None
            valid_icao = False
            if utils.is_valid_icao(airport_code):
                valid_icao = True
                airport = yield Airport.get_by_icao_code(airport_code)
            elif utils.is_valid_iata(airport_code):
                airport = yield Airport.get_by_iata_code(airport_code)
            else:
                raise AirportNotFoundException(airport_code, flight_num)

            if airport:
                raise tasklets.Return(airport.dict_for_client())

            elif valid_icao:
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
                    except (DownloadError, DeadlineExceededError, ValueError) as e:
                        raise FlightAwareUnavailableError()

                    report_event(reporting.FA_AIRPORT_INFO)

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

                        # Cleanup the timezone
                        if airport.get('timezone'):
                            if airport['timezone'].startswith(':'):
                                airport['timezone'] = airport['timezone'][1:]

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
                raise tasklets.Return() # Return None

    @ndb.tasklet
    def register_alert_endpoint(self, **kwargs):
        endpoint_url = config['flightaware']['alert_endpoint']

        try:
            result = yield self.conn.get_json('/RegisterAlertEndpoint',
                                            args={'address': endpoint_url,
                                                  'format_type': 'json/post'})
        except (DownloadError, DeadlineExceededError, ValueError) as e:
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
        - `use_cache` : Whether or not memcache should be used for getting data.
                        Cache is still set after retrieving data from datasource.
        """
        flight_number = kwargs.get('flight_number')
        use_cache = kwargs.get('use_cache')

        # Default to using cache if not specified
        if use_cache is None:
            use_cache = True

        if not utils.valid_flight_number(flight_number):
            raise InvalidFlightNumberException(flight_number)

        if not utils.is_valid_fa_flight_id(flight_id):
            raise InvalidFlightNumberException(flight_number)

        flight_cache_key = FlightAwareSource.flight_info_cache_key(flight_id)
        sanitized_f_num = utils.sanitize_flight_number(flight_number)

        # Optimization: check memcache first
        flight = None
        if use_cache:
            flight = memcache.get(flight_cache_key)
        elif debug_cache:
            logging.info('IGNORING FLIGHT CACHE')

        if flight:
            if use_cache and debug_cache:
                logging.info('FLIGHT CACHE HIT')
            if flight.is_old_flight:
                raise OldFlightException(flight_number=flight_number,
                                         flight_id=flight_id)
            flight.flight_number = sanitized_f_num
            raise tasklets.Return(flight)
        else:
            if use_cache and debug_cache:
                logging.info('FLIGHT CACHE MISS')

            # Optimization: check to see if we have cached flight info from recent lookup
            if use_cache:
                flight_result_cache_key = FlightAwareSource.flight_result_cache_key(flight_id)
                flight = memcache.get(flight_result_cache_key)
            elif debug_cache:
                logging.info('IGNORING LOOKUP CACHE')

            airline_data = None

            if flight:
                # We have a cached flight from lookup but still need airline info
                if use_cache and debug_cache:
                    logging.info('FLIGHT RESULT CACHE HIT')

                try:
                    airline_data = yield self.conn.get_json('/AirlineFlightInfo',
                                                        args={'faFlightID': flight_id,
                                                              'howMany': 1})
                    report_event(reporting.FA_AIRLINE_FLIGHT_INFO)
                except (DownloadError, DeadlineExceededError, ValueError) as e:
                    raise FlightAwareUnavailableError()

                if airline_data.get('error'):
                    raise TerminalsUnknownException(flight_id)
            else:
                if use_cache and debug_cache:
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
                    report_event(reporting.FA_FLIGHT_INFO_EX)
                    report_event(reporting.FA_AIRLINE_FLIGHT_INFO)
                except (DownloadError, DeadlineExceededError, ValueError) as e:
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
                flight = yield self.raw_flight_data_to_flight(flight_data, sanitized_f_num, airport_info)

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
            for flight in flights:
                if flight.is_old_flight:
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
                except (DownloadError, DeadlineExceededError, ValueError) as e:
                    raise FlightAwareUnavailableError()

                report_event(reporting.FA_FLIGHT_INFO_EX)

                if data.get('error'):
                    raise FlightNotFoundException(sanitized_f_num)

                data = data['FlightInfoExResult']['flights']

                # Filter out old flights before conversion to Flight
                current_flights = [f for f in data if not utils.is_old_fa_flight(f)]
                flight_data.extend(current_flights)

                # If we have some old flights, or less than 15 flights for this batch, we're done
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
            flights = yield [self.raw_flight_data_to_flight(data,
                                                      sanitized_f_num,
                                                      airport_info,
                                                      return_none_on_error=True)
                                    for data in flight_data]
            flights = [f for f in flights if f is not None] # Filter out bad results

            # If there are no good flights left, raise CurrentFlightNotFound
            if len(flights) == 0:
                raise CurrentFlightNotFoundException(sanitized_f_num)

            # Optimization: cache flight info so /track doesn't have cache miss on selecting a flight
            flights_to_cache = {}
            for flight in flights:
                cache_key = FlightAwareSource.flight_result_cache_key(flight.flight_id)
                flights_to_cache[cache_key] = flight

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
    def process_alert(self, alert_body, request_handler):
        # Note: alert_body has already been validated
        alert_id = alert_body['alert_id']
        event_code = alert_body['eventcode']
        flight_id = alert_body['flight']['faFlightID']
        report_event(reporting.FA_FLIGHT_ALERT_CALLBACK)

        # Cache freshness: clear memcache keys for flight info
        FlightAwareSource.clear_flight_info_cache(flight_id)

        # Lookup the flight that the alert is about
        stored_flight = yield FlightAwareTrackedFlight.get_by_flight_id_alert_id(flight_id, alert_id)

        # Only process the alert if we still care about it
        if not stored_flight:
            logging.info('IGNORING ALERT %d FOR FLIGHT %s', alert_id, flight_id)
            raise tasklets.Return()
        else:
            flight_num = stored_flight.user_flight_num
            alerted_flight = None

            # Cache freshness: clear memcache keys for lookup
            FlightAwareSource.clear_flight_lookup_cache([flight_num])

            # Get current and last flight information for the flight mentioned by the alert
            if event_code == 'cancelled':
                # Canceled flights can't be looked up, use stored flight data
                alerted_flight = Flight.from_dict(stored_flight.last_flight_data)
            else:
                alerted_flight = yield self.flight_info(flight_id=flight_id,
                                                        flight_number=flight_num,
                                                        use_cache=False)

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

            # Figure out which user to alert
            u_key = stored_flight.key.parent()
            u = yield u_key.get_async()

            if u and u.push_enabled:
                device_token = u.push_token
                alert_type = None

                # Send notifications to each user, only if they want that notification type
                # Early / delayed / on time
                if event_code in ['change', 'minutes_out'] and u.wants_notification_type(PUSH_TYPES.CHANGED):
                    if terminal_changed:
                        alert_type = TerminalChangeAlert
                    else:
                        alert_type = FlightPlanChangeAlert

                # Take off
                elif event_code == 'departure' and u.wants_notification_type(PUSH_TYPES.DEPARTED):
                    alert_type = FlightDepartedAlert

                # Arrival
                elif event_code == 'arrival' and u.wants_notification_type(PUSH_TYPES.ARRIVED):
                    alert_type = FlightArrivedAlert

                # Diverted
                elif event_code == 'diverted' and u.wants_notification_type(PUSH_TYPES.DIVERTED):
                    alert_type = FlightDivertedAlert

                # Canceled
                elif event_code == 'cancelled' and u.wants_notification_type(PUSH_TYPES.CANCELED):
                    alert_type = FlightCanceledAlert

                else:
                    logging.info('Unhandled eventcode: %s', event_code)

                # Push the notification if we need to send one
                if alert_type:
                    alert = alert_type(device_token, alerted_flight, flight_num)
                    alert.push(play_flight_sounds=u.wants_flight_sounds())

                # IMPORTANT: Fire off a /track for the user, which will update their reminders
                yield self.do_track(request_handler, flight_id, u_key.string_id())

                logging.info('ALERT %d %s CALLBACK PROCESSED', alert_id, event_code.upper())

            elif u and not u.push_enabled:
                logging.info('ALERT %d PROCESSED FOR USER %s WITH PUSH DISABLED', alert_id, u.key.string_id())

            elif not u:
                logging.error('ALERT %d HAS FLIGHT %s BUT NO USER %s!', alert_id, flight_id, u_key.string_id())

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
        except (DownloadError, DeadlineExceededError, ValueError) as e:
            raise FlightAwareUnavailableError()

        error = result.get('error')
        alert_id = result.get('SetAlertResult')
        is_valid_alert_id = utils.is_int(alert_id)

        if not error and is_valid_alert_id:
            report_event(reporting.FA_SET_ALERT)
            if debug_alerts:
                logging.info('REGISTERED NEW ALERT')
            raise tasklets.Return(int(alert_id))
        elif error:
            raise UnableToSetAlertException(reason=error)
        elif not is_valid_alert_id:
             raise UnableToSetAlertException(reason='Bad Alert ID')

    @ndb.tasklet
    def get_all_alerts(self):
        try:
            result = yield self.conn.get_json('/GetAlerts', args={})
        except (DownloadError, DeadlineExceededError, ValueError) as e:
            raise FlightAwareUnavailableError()

        report_event(reporting.FA_GET_ALERTS)
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
    def delete_alert(self, alert_id, orphaned=False):
        try:
            result = yield self.conn.get_json('/DeleteAlert',
                                            args={'alert_id':alert_id})
        except (DownloadError, DeadlineExceededError, ValueError) as e:
            raise FlightAwareUnavailableError()

        report_event(reporting.FA_DELETED_ALERT)
        error = result.get('error')
        success = result.get('DeleteAlertResult')

        if not error and success == 1:
            if debug_alerts:
                logging.info('DELETED ALERT %d' % alert_id)
            if orphaned:
                report_event(reporting.DELETED_ORPHANED_ALERT)
            raise tasklets.Return(True)
        else:
            raise UnableToDeleteAlertException(alert_id)

    @ndb.tasklet
    def delete_alerts(self, alert_ids, orphaned=False):
        for batch in utils.chunks(alert_ids, 20): # Batches of 20
            try:
                # Optimization: parallel yield of batches
                futs = [self.delete_alert(alert_id, orphaned=orphaned) for alert_id in batch]
                yield futs
            except Exception as e:
                logging.exception(e) # Log the exception
                if isinstance(e, FlightAwareUnavailableError):
                    utils.report_service_error(e) # Report service errors

    @ndb.tasklet
    def clear_all_alerts(self):
        alerts = yield self.get_all_alerts()
        alert_ids = [alert.get('alert_id') for alert in alerts]
        if debug_alerts:
            logging.info('CLEARING %d ALERTS' % len(alert_ids))

        # Optimization: defer removal of all alerts
        alert_ids = [str(alert_id) for alert_id in alert_ids if isinstance(alert_id, (int, long))]
        alert_list = ','.join(alert_ids)
        task = taskqueue.Task(payload=alert_list)
        taskqueue.Queue('clear-alerts').add(task)
        raise tasklets.Return({'clearing_alert_count': len(alert_ids)})

    @ndb.tasklet
    def track_flight(self, flight_data, **kwargs):
        uuid = kwargs.get('uuid')
        app_version = kwargs.get('app_version')
        preferred_language = kwargs.get('preferred_language')
        push_token = kwargs.get('push_token')
        user_latitude = kwargs.get('user_latitude')
        user_longitude = kwargs.get('user_longitude')
        driving_time = kwargs.get('driving_time')
        reminder_lead_time = kwargs.get('reminder_lead_time')
        send_reminders = kwargs.get('send_reminders')
        send_flight_events = kwargs.get('send_flight_events')
        play_flight_sounds = kwargs.get('play_flight_sounds')

        flight = Flight.from_dict(flight_data)
        flight_id = flight.flight_id
        user_key = ndb.Key(iOSUser, uuid) # FIXME: Assumes iOS
        flight_key = ndb.Key(FlightAwareTrackedFlight, flight_id, parent=user_key)
        now = datetime.utcnow()
        alert_id = 0

        # Set an alert_id if we don't have one or it isn't enabled
        existing_flight = yield flight_key.get_async()
        if not existing_flight or existing_flight.alert_id == 0:
            alert_id = yield self.set_alert(flight_id=flight_id)

        @ndb.tasklet
        def track_txn():
            # Optimization: multi-get
            user, tracked_flight = yield ndb.get_multi_async([user_key, flight_key])
            already_tracking = bool(tracked_flight)
            existing_user = bool(user)
            old_push_token = None

            # Create/update the user as necessary
            if user:
                old_push_token = user.push_token
                user.update(app_version=app_version,
                            preferred_language=preferred_language,
                            user_latitude=user_latitude,
                            user_longitude=user_longitude,
                            push_token=push_token,
                            send_reminders=send_reminders,
                            send_flight_events=send_flight_events,
                            play_flight_sounds=play_flight_sounds)
            else:
                # FIXME: Assumes iOS
                user = iOSUser.create(uuid,
                                      app_version=app_version,
                                      preferred_language=preferred_language,
                                      user_latitude=user_latitude,
                                      user_longitude=user_longitude,
                                      push_token=push_token,
                                      send_reminders=send_reminders,
                                      send_flight_events=send_flight_events,
                                      play_flight_sounds=play_flight_sounds)

            # Create/update the flight as necessary
            if tracked_flight:
                tracked_flight.update(flight,
                                      alert_id or tracked_flight.alert_id,
                                      driving_time=driving_time,
                                      reminder_lead_time=reminder_lead_time)
            else:
                tracked_flight = FlightAwareTrackedFlight.create(user_key,
                                                                 flight,
                                                                 alert_id,
                                                                 driving_time=driving_time,
                                                                 reminder_lead_time=reminder_lead_time)
                log_event_transactionally(FlightTrackedEvent, user_id=uuid, flight_id=flight_id)

            # Optimization: multi-put
            put_futs = ndb.put_multi_async([user, tracked_flight])

            # If they are an existing user and tracking any other flights than this one, untrack them
            if existing_user:
                flight_ids_tracked = yield FlightAwareTrackedFlight.flight_ids_tracked_by_user(user_key)
                other_flight_ids = [f_id for f_id in flight_ids_tracked if f_id != flight_id]
                if other_flight_ids:
                    # Optimization: batch task add, TQ max batch size is 100
                    for batch in utils.chunks(other_flight_ids, 100):
                        untrack_tasks = []
                        for f_id in batch:
                            untrack_tasks.append(taskqueue.Task(params={
                            'flight_id' : f_id,
                            'uuid' : uuid,
                        }))
                        taskqueue.Queue('untrack').add(untrack_tasks)
                    logging.info('USER TRACKING %d OTHER FLIGHTS, NOW UNTRACKED' % len(other_flight_ids))

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
                delayed_track_tasks = []

                # Allow for 75% fluctuation in driving time
                first_check_time = utils.leave_now_time(flight,
                                                        (driving_time * 1.75))

                # Check again at leave soon minus 1 min, want to beat the cron job
                second_check_time = utils.leave_soon_time(flight,
                                                          driving_time,
                                                          tracked_flight.reminder_lead_time) - timedelta(seconds=60)

                check_times = [first_check_time, second_check_time]
                delayed_track_tasks = [taskqueue.Task(params={
                                                        'flight_id' : flight_id,
                                                        'uuid' : uuid
                                                        }, eta=ct) for ct in check_times if ct > now]

                # Optimization: batch task add
                if delayed_track_tasks:
                    taskqueue.Queue('delayed-track').add(delayed_track_tasks, transactional=True)

            # Commit the datastore writes
            yield put_futs

        # TRANSACTIONAL TRACKING!
        yield ndb.transaction_async(track_txn)

    @ndb.tasklet
    def untrack_flight(self, flight_id, **kwargs):
        uuid = kwargs.get('uuid')
        u_key = ndb.Key(iOSUser, uuid) # FIXME: Assumes iOS
        f_key = ndb.Key(FlightAwareTrackedFlight, flight_id, parent=u_key)

        @ndb.tasklet
        def untrack_txn():
            flight = yield f_key.get_async()
            if flight:
                flight_num, alert_id = flight.user_flight_num, flight.alert_id
                yield f_key.delete_async()
                raise tasklets.Return(flight_num, alert_id)

        # TRANSACTIONAL UNTRACKING!
        result = yield ndb.transaction_async(untrack_txn)

        if result:
            flight_num, alert_id = result

            if alert_id > 0:
                # Delete the alert now that it's no longer needed
                yield self.delete_alert(alert_id)

            # Cache freshness: clear cache for this flight_id
            FlightAwareSource.clear_flight_info_cache(flight_id)

            # Cache freshness: clear lookup cache for the flight ident
            FlightAwareSource.clear_flight_lookup_cache([flight_num])

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
        """Implements driving_time method of DrivingTimeDataSource.

        Fields:
        - `origin_lat` : The latitude of the origin to route from.
        - `origin_lon` : The longitude of the origin to route from.
        - `dest_lat` : The latitude of the destination to route to.
        - `dest_lon` : The longitude of the destination to route to.
        - `use_cache` : Whether or not to use memcache. Will always update the cache
                        when fetching new data regardless of whether this is set.

        """
        driving_cache_key = GoogleDistanceSource.driving_cache_key(origin_lat,
                                                                   origin_lon,
                                                                   dest_lat,
                                                                   dest_lon)
        use_cache = kwargs.get('use_cache')

        # Default to using cache if not specified
        if use_cache is None:
            use_cache = True

        time = None
        if use_cache:
            time = memcache.get(driving_cache_key)
        elif debug_cache:
            logging.info('IGNORING DRIVING CACHE')

        if time is not None:
            if use_cache and debug_cache:
                logging.info('DRIVING CACHE HIT')
            raise tasklets.Return(time)
        else:
            if use_cache and debug_cache:
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
            except (DownloadError, DeadlineExceededError) as e:
                raise GoogleDistanceAPIUnavailableError()

            report_event(reporting.GOOG_FETCH_DRIVING_TIME)
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
        """Implements driving_time method of DrivingTimeDataSource.

        Fields:
        - `origin_lat` : The latitude of the origin to route from.
        - `origin_lon` : The longitude of the origin to route from.
        - `dest_lat` : The latitude of the destination to route to.
        - `dest_lon` : The longitude of the destination to route to.
        - `use_cache` : Whether or not to use memcache. Will always update the cache
                        when fetching new data regardless of whether this is set.

        """
        driving_cache_key = BingMapsDistanceSource.driving_cache_key(origin_lat,
                                                                    origin_lon,
                                                                    dest_lat,
                                                                    dest_lon)
        use_cache = kwargs.get('use_cache')

        # Default to using cache if not specified
        if use_cache is None:
            use_cache = True

        time = None
        if use_cache:
            time = memcache.get(driving_cache_key)
        elif debug_cache:
            logging.info('IGNORING DRIVING CACHE')

        if time is not None:
            if use_cache and debug_cache:
                logging.info('DRIVING CACHE HIT')
            raise tasklets.Return(time)
        else:
            if use_cache and debug_cache:
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
            except (DownloadError, DeadlineExceededError) as e:
                raise BingMapsUnavailableError()

            report_event(reporting.BING_FETCH_DRIVING_TIME)
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