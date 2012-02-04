from google.appengine.ext import db

def make_key(key_name):
    if key_name:
        return db.Key.from_path('Airport', key_name)
    return None

def geo_converter(geo_str):
    if geo_str:
        lat, lng = geo_str.split()
        return db.GeoPt(lat=float(lat), lon=float(lng))
    return None