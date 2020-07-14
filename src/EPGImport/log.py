# logging for XMLTV importer
#
# One can simply use
# import log
# print("Some text", file=log)
# because the log unit looks enough like a file!

from __future__ import print_function

import sys
import threading

from six.moves import cStringIO as StringIO


logfile = StringIO()
# Need to make our operations thread-safe.
mutex = threading.Lock()

def write(data):
	mutex.acquire()
	try:
		if logfile.tell() > 8000:
			# Do a sort of 8k round robin
			logfile.reset()
		logfile.write(data)
	finally:
		mutex.release()
	sys.stdout.write(data)

def getvalue():
	mutex.acquire()
	try:
		pos = logfile.tell()
		head = logfile.read()
		logfile.reset()
		tail = logfile.read(pos)
	finally:
		mutex.release()
	return head + tail
