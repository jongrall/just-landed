#!/usr/bin/env python

"""uploadutil.py: Helper functions used in the transformation of airport data
when bulk uploading from airports.csv to the datastore.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

from google.appengine.ext import db

def make_key(key_name):
    """Returns a db.Key given an airport name (usually the ICAO code)."""
    if key_name:
        return db.Key.from_path('Airport', key_name)
    return None

def geo_converter(geo_str):
    """Turns a string containing a latitude and longitude into a db.GeoPt"""
    if geo_str:
        lat, lng = geo_str.split()
        return db.GeoPt(lat=float(lat), lon=float(lng))
    return None