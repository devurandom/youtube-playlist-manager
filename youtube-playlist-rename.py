#!/usr/bin/python
# -*- coding: utf-8 -*-

import httplib
import httplib2
import os
import random
import sys
import time
import argparse
import re

from apiclient.discovery import build
from apiclient.errors import HttpError
from apiclient.http import MediaFileUpload

from oauth2client.file import Storage
from oauth2client.client import flow_from_clientsecrets
from oauth2client.tools import run

import simplejson as json


# Maximum number of results YouTube allows us to retrieve in one list request
MAX_RESULTS = 50

# Explicitly tell the underlying HTTP transport library not to retry, since
# we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError, httplib.NotConnected,
	httplib.IncompleteRead, httplib.ImproperConnectionState,
	httplib.CannotSendRequest, httplib.CannotSendHeader,
	httplib.ResponseNotReady, httplib.BadStatusLine)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

# CLIENT_SECRETS_FILE, name of a file containing the OAuth 2.0 information for
# this application, including client_id and client_secret. You can acquire an
# ID/secret pair from the API Access tab on the Google APIs Console
#   http://code.google.com/apis/console#access
# For more information about using OAuth2 to access Google APIs, please visit:
#   https://developers.google.com/accounts/docs/OAuth2
# For more information about the client_secrets.json file format, please visit:
#   https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
# Please ensure that you have enabled the YouTube Data API for your project.
CLIENT_SECRETS_FILE = "client_secrets.json"

# An OAuth 2 access scope that allows for full read/write access.
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# Helpful message to display if the CLIENT_SECRETS_FILE is missing.
MISSING_CLIENT_SECRETS_MESSAGE = """
WARNING: Please configure OAuth 2.0

To make this sample run you will need to populate the client_secrets.json file
found at:

   %s

with information from the APIs Console
https://code.google.com/apis/console#access

For more information about the client_secrets.json file format, please visit:
https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
""" % os.path.abspath(os.path.join(os.path.dirname(__file__),
                      CLIENT_SECRETS_FILE))

def get_authenticated_service():
	http = httplib2.Http(cache=".cache")
	flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE, scope=YOUTUBE_SCOPE,
	                               message=MISSING_CLIENT_SECRETS_MESSAGE)

	storage = Storage("%s-oauth2.json" % sys.argv[0])
	credentials = storage.get()

	if credentials is None or credentials.invalid:
		credentials = run(flow, storage)

	return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
	             http=credentials.authorize(http))


def rename_playlists(youtube, args):
	playlists_req = youtube.playlists().list(
		part = "id,snippet",
		mine = True,
		maxResults = MAX_RESULTS,
	)

	while playlists_req:
		playlists = playlists_req.execute()

		for playlist in playlists["items"]:
			old_title = playlist["snippet"]["title"]
			if re.match(args.pattern, old_title):
				new_title = re.sub(args.pattern, args.replacement, old_title)
				sys.stderr.write(u"Renaming '{old}' to '{new}'\n".format(old = old_title, new = new_title))
				if not args.pretend:
					update_req = youtube.playlists().update(
						part = "snippet",
						body = {
							"id": playlist["id"],
							"snippet": {
								"title": new_title,
							},
						},
					)
					response = update_req.execute()

		playlists_req = youtube.playlists().list_next(playlists_req, playlists)

if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument("pattern")
	parser.add_argument("replacement")
	parser.add_argument("-p", "--pretend", action="store_true")
	args = parser.parse_args()

	if args.pretend:
		sys.stderr.write("WARNING: Only pretending\n")

	youtube = get_authenticated_service()
	rename_playlists(youtube, args)
