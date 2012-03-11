#!/usr/bin/python

"""aircraft_types.py: Utilities for mapping aircraft codes to simplified types."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed"
__email__ = "grall@alum.mit.edu"

aircraft_types = {
    'JET2': [
        'A306',
        'A30B',
        'A310',
        'A318',
        'A319',
        'A320',
        'A321',
        'A332',
        'A333',
        'B731',
        'B732',
        'B733',
        'B734',
        'B735',
        'B736',
        'B737',
        'B738',
        'B739',
        'B73Q',
        'B752',
        'B753',
        'B762',
        'B763',
        'B764',
        'B772',
        'B773',
        'MD11',
        'R721',
        'R722',
    ],
    'JET2REAR': [
        'B712',
        'B721',
        'B722',
        'B72Q',
        'RJ1',
        'CRJ2',
        'CRJ7',
        'CRJ9',
        'DC91',
        'DC91',
        'DC92',
        'DC92',
        'DC93',
        'DC93',
        'DC94',
        'DC94',
        'DC95',
        'DC95',
        'DC9Q',
        'DC9Q',
        'LJ23',
        'LJ24',
        'LJ24',
        'LJ25',
        'LJ25',
        'LJ28',
        'LJ31',
        'LJ31',
        'LJ35',
        'LJ35',
        'LJ35',
        'LJ40',
        'LJ45',
        'LJ55',
        'LJ55',
        'LJ60',
        'MD81',
        'MD82',
        'MD83',
        'MD87',
        'MD88',
        'MD90',
    ],
    'JET4': [
        'A342',
        'A343',
        'A345',
        'A346',
        'A380',
        'B720',
        'B741',
        'B742',
        'B743',
        'B744',
        'B74D',
        'B74R',
        'B74S',
        'C135',
        'C141',
        'YC15',
        'DC85',
        'DC85',
        'DC86',
        'DC86',
        'DC87',
        'DC87',
        'DC8Q',
        'DC8Q',
        'E3CF',
        'E3TF',
    ],
    'PROP4': [
        'C130',
        'C133',
        'C97',
        'DC4',
        'DC6',
        'DC7',
    ],
}

# Invert the mapping type => major_type
type_mapping = {}
for major_type in aircraft_types.keys():
    subtypes = aircraft_types[major_type]
    for minor_type in subtypes:
        type_mapping[minor_type] = major_type

def type_to_major_type(aircraft_type):
    if not aircraft_type:
        return 'PROP2'
    match = type_mapping.get(aircraft_type)
    return match or 'PROP2'