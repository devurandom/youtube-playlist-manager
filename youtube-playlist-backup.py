#!/usr/bin/python
# -*- coding: utf-8 -*-

import httplib
import httplib2
import os
import random
import sys
import argparse
import logging

from apiclient.discovery import build
from apiclient.errors import HttpError
from apiclient.http import BatchHttpRequest

from oauth2client.file import Storage
from oauth2client.client import flow_from_clientsecrets
from oauth2client.tools import run

import simplejson as json


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


def dump_playlists(youtube, args):
	playlists_req = youtube.playlists().list(
		part = "id,snippet,status",
		mine = True,
	)

	my_playlists = []
	while playlists_req:
		playlists = playlists_req.execute()

		for playlist in playlists["items"]:
			sys.stderr.write(playlist["snippet"]["title"])
			sys.stderr.write(": ")

			videos_req = youtube.playlistItems().list(
				part = "id,contentDetails,snippet",
				playlistId = playlist["id"],
			)

			my_videos = []
			while videos_req:
				videos = videos_req.execute()

				for video in videos["items"]:
					sys.stderr.write(".")
					my_videos.append(video)

				videos_req = youtube.playlistItems().list_next(videos_req, videos)

			sys.stderr.write("\n")

			my_playlists.append({
				"info": playlist,
				"videos": my_videos,
			})

		playlists_req = youtube.playlists().list_next(playlists_req, playlists)

	if args.reverse:
		my_playlists.reverse()

	json.dump(my_playlists, sys.stdout, indent="\t")

def load_playlists(youtube, args):
	playlists = json.load(sys.stdin)

	if args.reverse:
		playlists.reverse()

	for playlist in playlists:
		sys.stderr.write(playlist["info"]["snippet"]["title"])
		sys.stderr.write(": ")

		if args.prefix:
			playlist["info"]["snippet"]["title"] = args.prefix + playlist["info"]["snippet"]["title"]
		# Try not to confuse YouTube:
		del playlist["info"]["id"]
		del playlist["info"]["etag"]

		playlist_new = None
		if args.pretend:
			playlist_new = playlist["info"]
		else:
			playlist_req = youtube.playlists().insert(
				part = "snippet,status",
				body = playlist["info"],
			)
			playlist_new = playlist_req.execute()

		request_payloads = {}
		insert_requests = []
		finished_requests = []

		def insert_video(request_id, response, exception):
			payload = request_payloads[request_id]
			video_id = payload["snippet"]["resourceId"]["videoId"]

			if exception:
				if not args.debug:
					sys.stderr.write("\n")

				if exception.resp.status == 403:
					sys.stderr.write("WARNING: Video {id} private, skipping\n".format(id = video_id))
					finished_requests.append(request_id)
				elif exception.resp.status == 404:
					sys.stderr.write("WARNING: Video {id} deleted, skipping\n".format(id = video_id))
					finished_requests.append(request_id)
				elif exception.resp.status in RETRIABLE_STATUS_CODES:
					sys.stderr.write("WARNING: Server returned status {status} for video {id}, trying again\n".format(status = exception.resp.status, id = video_id))
				else:
					raise exception
			else:
				if args.debug:
					sys.stderr.write("Inserted video {id}\n".format(id = video_id))
				else:
					sys.stderr.write(".")
				finished_requests.append(request_id)

		for video in playlist["videos"]:
			request_id = video["id"]
			request_payloads[request_id] = video

			video["snippet"]["playlistId"] = playlist_new["id"]
			# Try not to confuse YouTube:
			del video["id"]
			del video["etag"]

			if not args.pretend:
				insert_requests.append(request_id)

		while insert_requests:
			if args.batch:
				batch_req = BatchHttpRequest(callback = insert_video)

			for request_id in insert_requests:
				video = request_payloads[request_id]

				video_req = youtube.playlistItems().insert(
					part = "contentDetails,snippet",
					body = video,
				)

				if args.batch:
					batch_req.add(video_req, request_id = request_id)
				else:
					response = None
					try:
						response = video_req.execute()
					except Exception as e:
						insert_video(request_id, None, e)
					else:
						insert_video(request_id, response, None)

			if args.batch:
				batch_req.execute()

			for request_id in finished_requests:
				insert_requests.remove(request_id)
			del finished_requests[:]

			sys.stderr.write("\n")

		sys.stderr.write("\n")

if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument("action", choices = ["dump", "load"])
	parser.add_argument("-b", "--batch", action="store_true")
	parser.add_argument("-d", "--debug", action="store_true")
	parser.add_argument("-p", "--pretend", action="store_true")
	parser.add_argument("-r", "--reverse", action="store_true")
	parser.add_argument("--prefix")
	args = parser.parse_args()

	if args.debug:
		sys.stderr.write("Debugging ...\n")
		logger = logging.getLogger()
		logger.setLevel(logging.INFO)
		#httplib2.debuglevel = 4
	if args.batch:
		sys.stderr.write("Batching ...\n")
	if args.pretend:
		sys.stderr.write("Pretending ...\n")

	youtube = get_authenticated_service()
	if args.action == "dump":
		dump_playlists(youtube, args)
	elif args.action == "load":
		load_playlists(youtube, args)
