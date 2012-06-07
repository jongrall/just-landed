#!/usr/bin/env python

"""extract_airline_codes.py: Script that extracts the airline codes from a file
and prints them out.

"""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@getjustlanded.com"

import sys
import logging
import csv

def main():
    # Load the files
    src_file = open('airline_codes.csv', 'rU')
    dest_file = open('airline_code_mapping.txt', 'w')
    airline_data = csv.reader(src_file)
    count = 0

    try:
        for airline in airline_data:
            # Process airport
            count += 1
            iata, icao = airline[0], airline[1]
            dest_file.write("'%s' : '%s',\n" % (iata, icao))
    finally:
        src_file.close()
        dest_file.close()
        print '\nPROCESSED: %d AIRLINES' % count

if __name__ == '__main__':
    main()