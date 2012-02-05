#!/usr/bin/python

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

import logging
import json

from google.appengine.api import memcache

from config import config
from api_exceptions import *


class FlightDataSource (object):

    @classmethod
    def base_url(cls):
        pass

    def airport_info(self, icao_code="", iata_code=""):
        pass

    def register_alert_endpoint(self, url, **kwargs):
        pass

    def flight_info(self, flight_number, **kwargs):
        pass

    def lookup_flights(self, flight_number, **kwargs):
        pass

    def process_alert(self, alert_body):
        pass

    def set_alert(self, **kwargs):
        pass

    def delete_alert(self, alert_id):
        pass


class FlightAwareSource (FlightDataSource):

    @classmethod
    def base_url(cls):
        return "http://flightxml.flightaware.com/json/FlightXML2/"

    def __init__(self):
        from lib.python_rest_client.restful_lib import Connection
        self.conn = Connection(self.base_url(),
            username=config['flightaware']['username'],
            password=config['flightaware']['key'])

    def airport_info(self, icao_code="", iata_code=""):
        pass

    def register_alert_endpoint(self, url, **kwargs):
        pass

    def flight_info(self, flight_number, **kwargs):
        pass

    def lookup_flights(self, flight_number, **kwargs):
        memcache_key = "%s-lookup_flights-%s" % (self.__class__.__name__,
                                                flight_number)
        flights = memcache.get(memcache_key)

        if flights is not None:
            return flights
        else:
            resp = self.conn.request_get('/FlightInfoEx',
                                         args={'ident':flight_number,
                                               'howMany': 15})
            flights = json.loads(resp['body'])

            if flights.get('error'):
                raise FlightNotFoundException()
            else:
                flights = flights['FlightInfoExResult']['flights']
            if not memcache.set(memcache_key, flights, 10800):
                logging.error("Unable to cache lookup response!")
            return flights

    def process_alert(self, alert_body):
        pass

    def set_alert(self, **kwargs):
        pass

    def delete_alert(self, alert_id):
        pass