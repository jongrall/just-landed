from google.appengine.ext import webapp

from lib.python_rest_client.restful_lib import Connection

from config import config

import json

class TrackHandler(webapp.RequestHandler):
    def get(self, flight_id):
        base_url = 'http://flightxml.flightaware.com/json/FlightXML2'
        conn = Connection(base_url, username=config['flightaware']['username'],
            password=config['flightaware']['key'])

        resp = conn.request_get('/FlightInfo', args={'ident':flight_id, 'howMany': 3})
        parsed_resp = json.loads(resp['body'])
        formatted_resp = json.dumps(parsed_resp, sort_keys=True, indent=4)
        htmlresp = '<br />'.join([l.rstrip() for l in formatted_resp.splitlines()])

        self.response.out.write(htmlresp)