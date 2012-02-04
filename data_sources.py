#!/usr/bin/python

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__credits__ = ["Jon Grall", "Sean Nelson", "Graham Beer"]
__license__ = "GPL"
__maintainer__ = "Jon Grall"
__email__ = "grall@alum.mit.edu"

from config import config

import json

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
        resp = self.conn.request_get('/FlightInfo', args={'ident':flight_number, 'howMany': 3})
        return json.loads(resp['body'])

    def process_alert(self, alert_body):
        pass

    def set_alert(self, **kwargs):
        pass

    def delete_alert(self, alert_id):
        pass