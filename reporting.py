from lib.prodeagle import counter

prodeagle_counter = counter

###############################################################################
"""User Counters"""
###############################################################################

NEW_USER = 'User.Created'
LOOKUP_FLIGHT = 'User.LookupFlight'
TRACK_FLIGHT = 'User.TrackFlight'
UNTRACK_FLIGHT = 'User.UntrackFlight'

###############################################################################
"""Flight Counters"""
###############################################################################

NEW_FLIGHT = 'Flight.NewFlight'
DELAYED_TRACK = 'Flight.DelayedTrack'
DELAYED_UNTRACK = 'Flight.DelayedUntrack'
UNTRACKED_OLD_FLIGHT = 'Flight.UntrackedOld'
GOT_FLIGHT_ALERT_CALLBACK = 'Flight.GotAlertCallback'
FLIGHT_NOT_FOUND = 'Flight.NotFound'
FLIGHT_NUMBER_INVALID = 'Flight.InvalidFlightNumber'
FLIGHT_TAKEOFF = 'Flight.Takeoff'
FLIGHT_LANDED = 'Flight.Landed'
FLIGHT_CANCELED = 'Flight.Canceled'
FLIGHT_DIVERTED = 'Flight.Diverted'
FLIGHT_CHANGE = 'Flight.Change'

###############################################################################
"""System Counters"""
###############################################################################

ERROR_500 = 'System.Error500'
SENT_LEAVE_SOON_NOTIFICATION = 'System.SentLeaveSoon'
SENT_LEAVE_NOW_NOTIFICATION = 'System.SentLeaveNow'
SENT_CHANGE_NOTIFICATION = 'System.SentChangeNotification'
SENT_TAKEOFF_NOTIFICATION = 'System.SentTakeoffNotification'
SENT_LANDED_NOTIFICATION = 'System.SentLandedNotification'
SENT_CANCELED_NOTIFICATION = 'System.SentCanceledNotification'
SENT_DIVERTED_NOTIFICATION = 'System.SentDivertedNotification'
SENT_PUSH_NOTIFICATION = 'System.SentPushNotification'
DELETED_ORPHANED_ALERT = 'System.DeletedOrphanedAlert'
FETCH_AIRPORT_INFO = 'System.FetchAirportInfo'
FETCH_AIRLINE_FLIGHT_INFO = 'System.FetchAirlineFlightInfo'
FETCH_FLIGHT_INFO = 'System.FetchFlightInfo'
SET_ALERT = 'System.SetAlert'
FETCH_ALERTS = 'System.FetchAlerts'
DELETED_ALERT = 'System.DeletedAlert'
FETCH_DRIVING_TIME = 'System.FetchDrivingTime'
CANT_FETCH_DRIVING_TIME = 'System.CantFetchDrivingTime'