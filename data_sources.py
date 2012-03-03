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
from datasource_exceptions import *
from models import *
import utils

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

    def stop_tracking_flight(self, flight_id, **kwargs):
        """Stops tracking a flight. If there are alerts set and no users tracking
        the flight any longer, we delete & disable the alerts.

        """
        pass

class FlightAwareSource (FlightDataSource):
    """Concrete subclass of FlightDataSource that pulls its data from the
    commercial FlightAware FlightXML2 API:

    http://flightaware.com/commercial/flightxml/documentation2.rvt

    """
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
                username=config['flightaware']['username'],
                password=config['flightaware']['keys']['development'])
        else:
            self.conn = Connection(self.base_url,
                username=config['flightaware']['username'],
                password=config['flightaware']['keys']['production'])

    def airport_info(self, icao_code="", iata_code=""):
        """Looks up information about an airport using its ICAO or IATA code."""
        if utils.is_valid_iata(iata_code):
            # Check the DB
            qry = Airport.query(Airport.iata_code == iata_code)
            airport = qry.get()
            return (airport and airport.dict_for_client()) or None
        elif utils.is_valid_icao(icao_code):
            # Check the DB first
            airport = Airport.get_by_id(icao_code)
            if airport:
                return airport.dict_for_client()
            else:
                # Check FlightAware for the AiportInfo
                memcache_key = "%s-airport_info-%s" % (self.__class__.__name__,
                                                       icao_code)
                airport = memcache.get(memcache_key)
                if airport is not None:
                    if debug_cache:
                        logging.info('AIRPORT INFO CACHE HIT')

                    return airport
                else:
                    if debug_cache:
                        logging.info('AIRPORT INFO CACHE MISS')
                    resp = self.conn.request_get('/AirportInfo',
                                                 args={'airportCode':icao_code})
                    # Turn the JSON response into a dict
                    result = json.loads(resp['body'])

                    if result.get('error'):
                        raise AirportNotFoundException(iata_code)
                    else:
                        airport = result['AirportInfoResult']

                        # Filter out fields we don't want
                        fields = config['flightaware']['airport_info_fields']
                        airport = utils.sub_dict_strict(airport, fields)

                        # Map field names
                        airport = utils.map_dict_keys(airport,
                                                      self.api_key_mapping)

                        # Add ICAO code back in (we don't have IATA)
                        airport['icaoCode'] = icao_code
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
            raise AirportNotFoundException(icao_code or iata_code)

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
        flight_cache_key = '%s-flight_info-%s' % (self.__class__.__name__,
                                                  flight_id)
        airline_cache_key = "%s-airline_info-%s" % (self.__class__.__name__,
                                                   flight_id)

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

        # Mark the flight as being tracked
        flight_key = FlightAwareTrackedFlight.create_or_update_flight(flight_id)

        # Add in the airline info and user-entered flight number
        flight.flight_number = utils.sanitize_flight_number(flight_number)
        flight.origin.terminal = airline_info['originTerminal']
        flight.destination.terminal = airline_info['destinationTerminal']
        flight.destination.bag_claim = airline_info['bagClaim']

        return flight_key, flight

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
        lookup_cache_key = '%s-lookup_flights-%s' % (self.__class__.__name__,
                                                    sanitized_f_num)

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

                # Keep a subset of the response fields
                fields = config['flightaware']['flight_info_fields']
                flight_data = [utils.sub_dict_strict(f, fields)
                                for f in flight_data]

                # Map the response dict keys
                flight_data = [utils.map_dict_keys(f, self.api_key_mapping)
                                for f in flight_data]

                # Convert raw flight data to instances of Flight
                flights = []

                for f in flight_data:
                    origin = None
                    origin_code = f['origin']

                    if utils.is_valid_iata(origin_code):
                        origin = Origin(self.airport_info(iata_code=origin_code))
                    else:
                        origin = Origin(self.airport_info(icao_code=origin_code))

                    destination = None
                    destination_code = f['destination']

                    if utils.is_valid_iata(destination_code):
                        destination = Destination(self.airport_info(
                                                  iata_code=destination_code))
                    else:
                        destination = Destination(self.airport_info(
                                                  icao_code=destination_code))

                    flight = Flight(f)
                    flight.flight_number = sanitized_f_num
                    flight.origin = origin
                    flight.destination = destination

                    # Convert flight duration to integer number of seconds
                    flight_duration = f['scheduledFlightDuration'].split(':')
                    secs = (int(flight_duration[0]) * 3600) + (int(flight_duration[1]) * 60)
                    flight.scheduled_flight_duration = secs

                    flight.origin.city = f['originCity'].split(',')[0]
                    flight.origin.name = utils.proper_airport_name(f['originName'])
                    flight.destination.city = f['destinationCity'].split(',')[0]
                    flight.destination.name = utils.proper_airport_name(f['destinationName'])
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
        pass

    def set_alert(self, **kwargs):
        flight_id = kwargs.get('flight_id')
        assert isinstance(flight_id, basestring) and len(flight_id)

        # Derive flight num from flight_id so we can use common flight_num for alerts
        flight_num = utils.sanitize_flight_number(flight_id.split('-')[0])

        # See if the alert exists (according to our datastore) and is enabled
        alert = FlightAwareAlert.existing_enabled_alert(flight_num)

        if alert:
            if debug_alerts:
                logging.info('EXISTING ALERT FOR %s' % flight_num)
            return alert
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
                if alert_id > 0:
                    # Store the alert so we don't recreate it
                    return FlightAwareAlert.create_alert(alert_id, flight_num)
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
            alert = FlightAwareAlert.disable_alert(alert_id)
            if alert:
                iOSUser.remove_alert(alert.key)
        else:
            raise UnableToDeleteAlertException(alert_id)

    def clear_all_alerts(self):
        alerts = self.get_all_alerts()

        # Get all the alert ids
        alert_ids = [alert.get('alert_id') for alert in alerts]

        if debug_alerts:
            logging.info('CLEARING %d ALERTS' % len(alert_ids))

        # Defer removal of all alerts
        for alert_id in alert_ids:
            self.delete_alert(alert_id)

        return {'clearing_alert_count': len(alert_ids)}

    def stop_tracking_flight(self, flight_id, **kwargs):
        uuid = kwargs.get('uuid')
        flight_num = flight_id.split('-')[0]
        flight_key = model.Key('FlightAwareTrackedFlight', flight_id)

        # Lookup the alert by flight number
        alert = FlightAwareAlert.existing_enabled_alert(flight_num)
        alert_key = alert.key

        # Mark the user as no longer tracking the flight or the alert
        if uuid:
            iOSUser.untrack_flight(uuid, flight_key, alert_key=alert_key)

        # If there are no more users tracking the alert, delete it
        if alert_key:
            alert_unused = not iOSUser.alert_in_use(alert_key)
            if alert_unused:
                self.delete_alert(alert_key.integer_id())

        # See if any users are still tracking the flight
        if not iOSUser.flight_still_tracked(flight_key):
            FlightAwareTrackedFlight.stop_tracking(flight_key)


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
        driving_cache_key = '%s-driving_time-%f,%f,%f,%f' % (
            self.__class__.__name__,
            utils.round_coord(origin_lat, sf=2),
            utils.round_coord(origin_lon, sf=2),
            utils.round_coord(dest_lat, sf=2),
            utils.round_coord(dest_lon, sf=2),
        )

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
