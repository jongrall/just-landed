"""appengine_config.py: Additional App-Engine specific config."""

__author__ = "Jon Grall"
__copyright__ = "Copyright 2012, Just Landed LLC"
__email__ = "jon@littledetails.net"

from config import on_production

# Numerical limits on how much information is saved for each event.
# MAX_STACK limits the number of stack frames saved; MAX_LOCALS limits
# the number of local variables saved per stack frame.  MAX_REPR
# limits the length of the string representation of each variable
# saved; MAX_DEPTH limits the nesting depth used when computing the
# string representation of structured variables (e.g. lists of lists).

appstats_MAX_STACK = 20
appstats_MAX_LOCALS = 10
appstats_MAX_REPR = 100
appstats_MAX_DEPTH = 10

def webapp_add_wsgi_middleware(app):
    # Optimization: only add appstats middleware in the development environment
    appstats_enabled = False
    if not appstats_enabled or on_production():
        return app

    from google.appengine.ext.appstats import recording
    app = recording.appstats_wsgi_middleware(app)
    return app

def appstats_should_record(env):
    if env.get('PATH_INFO').startswith('/_ah/admin'):
        # Don't record admin stuff
        return False
    if env.get('PATH_INFO').startswith('/_ah/queue/report-event'):
        # Don't record event reporting
        return False
    return True

remoteapi_CUSTOM_ENVIRONMENT_AUTHENTICATION = ('HTTP_X_APPENGINE_INBOUND_APPID',
['just-landed'])