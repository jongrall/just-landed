from distutils.core import setup

setup(name='JustLandedServer',
	  version='1.3.4',
	  author='Jon Grall',
	  author_email='jon@littledetails.net',
	  description='The Just Landed App Engine Server',
	  platforms=['Google App Engine Python 2.7 Runtime'],
	  packages=['server'],
	  package_data={'server': ['data/*.csv']},
	  scripts=['server/data/extract_airline_codes', 'server/data/fix_airport_locations',
	           'server/data/load_airlines', 'server/data/load_airports'],
	  url='https://github.com/jongrall/just-landed.git',
	  license='Just Landed is closed-source proprietary commercial software. Copyright Little Details LLC. All Rights Reserved.',
)