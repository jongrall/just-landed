import logging
import json

from google.appengine.ext import webapp

from data_sources import FlightAwareSource
source = FlightAwareSource()

import utils

class BaseAPIHandler(webapp.RequestHandler):
    def respond(self, response_dict):
        if self.request.GET.get('debug'):
            # Pretty print JSON
            formatted_resp = json.dumps(response_dict, sort_keys=True, indent=4)
            self.response.write(utils.text_to_html(formatted_resp))
        else:
            self.response.write(json.dumps(response_dict))


class TrackHandler(BaseAPIHandler):
    def get(self, flight_id):
        self.respond('Tracking %s goes here.' % flight_id)


class SearchHandler(BaseAPIHandler):
    def get(self, flight_number):
        flights = source.lookup_flights(flight_number)
        self.respond(flights)


class UntrackHandler(BaseAPIHandler):
    def get(self, flight_id):
        self.respond('Untrack %s goes here.' % flight_id)


class AlertHandler(BaseAPIHandler):
    def post(self):
        self.respond('Alert handler goes here.')