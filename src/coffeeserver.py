#!/usr/bin/env python

'''coffeeserver.py - Waqas Bhatti (wbhatti@astro.princeton.edu) - Jul 2014

This is the Tornado web-server for astroph-coffee. It uses URL handlers defined
in coffeehandlers.py.

'''

import os
import os.path
import ConfigParser

try:
    from pysqlite2 import dbapi2 as sqlite3
except:
    print("can't find internal pysqlite2, falling back to Python sqlite3 "
          "full-text search may not work right "
          "if your sqlite3.sqlite3_version is old (< 3.8.6 or so)")
    import sqlite3

import signal
import logging

from datetime import time
from pytz import utc

# for signing flash messages
from itsdangerous import Signer

# for geofencing
import geoip2.database
import ipaddress


# setup signal trapping on SIGINT
def recv_sigint(signum, stack):
    '''
    handler function to receive and process a SIGINT

    '''

    LOGGER.info('received SIGINT.')
    raise KeyboardInterrupt

# register the signal callback
signal.signal(signal.SIGINT,recv_sigint)
signal.signal(signal.SIGTERM,recv_sigint)


#####################
## TORNADO IMPORTS ##
#####################

import tornado.ioloop
import tornado.httpserver
import tornado.web
import tornado.options
from tornado.options import define, options

####################################
## LOCAL IMPORTS FOR URL HANDLERS ##
####################################

import coffeehandlers


###############################
### APPLICATION SETUP BELOW ###
###############################

# define our commandline options
define('port',
       default=5005,
       help='run on the given port.',
       type=int)
define('serve',
       default='127.0.0.1',
       help='bind to given address and serve content.',
       type=str)
define('debugmode',
       default=0,
       help='start up in debug mode if set to 1.',
       type=int)

############
### MAIN ###
############

# run the server
if __name__ == '__main__':

    # parse the command line
    tornado.options.parse_command_line()

    DEBUG = True if options.debugmode == 1 else False

    CURR_PID = os.getpid()
    PID_FNAME = 'coffeeserver'
    PID_FILE = open(os.path.join('pids',PID_FNAME),'w')
    PID_FILE.write('%s\n' % CURR_PID)
    PID_FILE.close()

    # get a logger
    LOGGER = logging.getLogger('coffeeserver')
    if DEBUG:
        LOGGER.setLevel(logging.DEBUG)
    else:
        LOGGER.setLevel(logging.INFO)


    ###################
    ## SET UP CONFIG ##
    ###################

    # read the conf files
    CONF = ConfigParser.ConfigParser()
    CONF.read(os.path.join(os.getcwd(),'conf','astroph.conf'))

    # get the web config vars
    SESSIONSECRET = CONF.get('keys','secret')
    STATICPATH = os.path.abspath(
        os.path.join(os.getcwd(), CONF.get('paths','static'))
    )
    TEMPLATEPATH = os.path.join(STATICPATH,'templates')

    # set up the database
    DBPATH = os.path.abspath(
        os.path.join(os.getcwd(), CONF.get('sqlite3','database'))
    )
    DATABASE = sqlite3.connect(
        DBPATH,
        detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES
    )

    # get the times of day (UTC) to switch between voting and list mode
    VOTING_START = CONF.get('times','voting_start')
    VOTING_END = CONF.get('times','voting_end')
    COFFEE_TIME = CONF.get('times','coffee_time')
    RESERVE_INTERVAL_DAYS = int(CONF.get('times','reserve_interval_days'))

    VOTING_START = [int(x) for x in VOTING_START.split(':')]
    VOTING_START = time(VOTING_START[0], VOTING_START[1], tzinfo=utc)
    VOTING_END = [int(x) for x in VOTING_END.split(':')]
    VOTING_END = time(VOTING_END[0], VOTING_END[1], tzinfo=utc)
    COFFEE_TIME = [int(x) for x in COFFEE_TIME.split(':')]
    COFFEE_TIME = time(COFFEE_TIME[0], COFFEE_TIME[1], tzinfo=utc)

    # get the server timezone
    SERVER_TZ = CONF.get('times','server_tz')

    # get the coffee place info
    COFFEE_ROOM = CONF.get('places','room')
    COFFEE_BUILDING = CONF.get('places','building')
    COFFEE_DEPARTMENT = CONF.get('places','department')
    COFFEE_INSTITUTION = CONF.get('places','institution')

    # get the geofencing config
    GEOFENCE_ACTIVE = CONF.get('access_control','active')

    if GEOFENCE_ACTIVE == 'True':

        # check geographical regions
        GEOFENCE_DB = CONF.get('access_control','database')
        LOGGER.info('geofence active, using database: %s' % GEOFENCE_DB)
        GEOFENCE_DB = geoip2.database.Reader(GEOFENCE_DB)
        GEOFENCE_COUNTRIES = [
            x.strip() for x in
            CONF.get('access_control','allowed_countries').split(',')
        ]
        GEOFENCE_REGIONS = (
            [x.strip() for x in
             CONF.get('access_control','allowed_subdivisions').split(',')]
        )

        # check the IP address restrictions for people always allowed to
        # vote/reserve papers
        GEOFENCE_IPS = CONF.get('access_control', 'allowed_cidr')
        GEOFENCE_IPS = [ipaddress.IPv4Network(x.strip().decode())
                        for x in GEOFENCE_IPS.split(',')]

        # check the IP address restrictions for people always allowed to
        # vote/reserve papers
        EDITOR_IPS = CONF.get('access_control', 'edit_cidr')
        EDITOR_IPS = [ipaddress.IPv4Network(x.strip().decode())
                        for x in EDITOR_IPS.split(',')]

    else:

        GEOFENCE_DB = None
        GEOFENCE_COUNTRIES = None
        GEOFENCE_REGIONS = None
        GEOFENCE_IPS = None

    # this is used to sign flash messages so they can't be forged
    FLASHSIGNER = Signer(SESSIONSECRET)

    # this is used to get the interval for which reserved papers stay active
    RESERVE_INTERVAL = CONF.get('times','reserve_interval_days')


    # the local website admin info
    ADMINCONTACT = CONF.get('places','admincontact')
    ADMINEMAIL = CONF.get('places','adminemail')

    ##################
    ## URL HANDLERS ##
    ##################

    HANDLERS = [
        (r'/astroph-coffee/',coffeehandlers.CoffeeHandler,
         {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'coffee_time':COFFEE_TIME,
          'server_tz':SERVER_TZ,
          'signer':FLASHSIGNER,
          'room':COFFEE_ROOM,
          'building':COFFEE_BUILDING,
          'department':COFFEE_DEPARTMENT,
          'institution':COFFEE_INSTITUTION}),
        (r'/astroph-coffee',coffeehandlers.CoffeeHandler,
         {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'coffee_time':COFFEE_TIME,
          'server_tz':SERVER_TZ,
          'signer':FLASHSIGNER,
          'room':COFFEE_ROOM,
          'building':COFFEE_BUILDING,
          'department':COFFEE_DEPARTMENT,
          'institution':COFFEE_INSTITUTION}),
        (r'/astroph-coffee/papers',tornado.web.RedirectHandler,
         {'url':'/astroph-coffee/papers/today'}),
        (r'/astroph-coffee/papers/',tornado.web.RedirectHandler,
         {'url':'/astroph-coffee/papers/today'}),
        (r'/astroph-coffee/papers/today',coffeehandlers.ArticleListHandler,
         {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'server_tz':SERVER_TZ,
          'reserve_interval':RESERVE_INTERVAL_DAYS,
          'signer':FLASHSIGNER}),
        (r'/astroph-coffee/papers/today/',coffeehandlers.ArticleListHandler,
         {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'server_tz':SERVER_TZ,
          'reserve_interval':RESERVE_INTERVAL_DAYS,
          'signer':FLASHSIGNER}),
        (r'/astroph-coffee/archive/?(.*)',coffeehandlers.ArchiveHandler,
         {'database':DATABASE,
          'reserve_interval':RESERVE_INTERVAL_DAYS,
          'signer':FLASHSIGNER}),
        (r'/astroph-coffee/vote',coffeehandlers.VotingHandler,
         {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'debug':DEBUG,
          'signer':FLASHSIGNER,
          'geofence': (GEOFENCE_DB, GEOFENCE_IPS, EDITOR_IPS),
          'countries':GEOFENCE_COUNTRIES,
          'regions':GEOFENCE_REGIONS}),
        (r'/astroph-coffee/reserve',coffeehandlers.ReservationHandler,
         {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'debug':DEBUG,
          'signer':FLASHSIGNER,
          'geofence': (GEOFENCE_DB, GEOFENCE_IPS, EDITOR_IPS),
          'countries':GEOFENCE_COUNTRIES,
          'regions':GEOFENCE_REGIONS}),
        (r'/astroph-coffee/edit',coffeehandlers.EditHandler,
         {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'debug':DEBUG,
          'signer':FLASHSIGNER,
          'geofence': (GEOFENCE_DB, GEOFENCE_IPS, EDITOR_IPS),
          'countries':GEOFENCE_COUNTRIES,
          'regions':GEOFENCE_REGIONS}),
        (r'/astroph-coffee/search',coffeehandlers.FTSHandler,
         {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'debug':DEBUG,
          'signer':FLASHSIGNER,
          'geofence': (GEOFENCE_DB, GEOFENCE_IPS, EDITOR_IPS),
          'countries':GEOFENCE_COUNTRIES,
          'regions':GEOFENCE_REGIONS}),
 	(r'/astroph-coffee/calendar',coffeehandlers.CalendarHandler,
          {'database':DATABASE,
          'voting_start':VOTING_START,
          'voting_end':VOTING_END,
          'coffee_time':COFFEE_TIME,
          'server_tz':SERVER_TZ,
          'signer':FLASHSIGNER,
          'room':COFFEE_ROOM,
          'building':COFFEE_BUILDING,
          'department':COFFEE_DEPARTMENT,
          'institution':COFFEE_INSTITUTION}), 
        (r'/astroph-coffee/about',coffeehandlers.AboutHandler,
         {'database':DATABASE}),
        (r'/astroph-coffee/about/',coffeehandlers.AboutHandler,
         {'database':DATABASE}),
        (r'/astroph-coffee/local-authors',coffeehandlers.LocalListHandler,
         {'database':DATABASE,
          'admincontact':ADMINCONTACT, 'adminemail':ADMINEMAIL}),
        (r'/astroph-coffee/local-authors/',coffeehandlers.LocalListHandler,
         {'database':DATABASE,
          'admincontact':ADMINCONTACT, 'adminemail':ADMINEMAIL}),
    ]

    #######################
    ## APPLICATION SETUP ##
    #######################

    app = tornado.web.Application(
        handlers=HANDLERS,
        cookie_secret=SESSIONSECRET,
        static_path=STATICPATH,
        template_path=TEMPLATEPATH,
        static_url_prefix='/astroph-coffee/static/',
        xsrf_cookies=True,
        debug=DEBUG,
    )

    # start up the HTTP server and our application. xheaders = True turns on
    # X-Forwarded-For support so we can see the remote IP in the logs
    http_server = tornado.httpserver.HTTPServer(app, xheaders=True)
    http_server.listen(options.port, options.serve)

    LOGGER.info('starting event loop...')

    # start the IOLoop and begin serving requests
    try:
        tornado.ioloop.IOLoop.instance().start()

    except KeyboardInterrupt:
        LOGGER.info('shutting down...')

        DATABASE.close()
        if GEOFENCE_DB:
           GEOFENCE_DB.close()
