#!/usr/bin/python
#
# This file no longer has a direct link to Enigma2, allowing its use anywhere
# you can supply a similar interface. See plugin.py and OfflineImport.py for
# the contract.
#
import time
import os
import gzip
import log
import random
from twisted import version
from sys import version_info
from socket import getaddrinfo, AF_INET6, has_ipv6

HDD_EPG_DAT = "/hdd/epg.dat"

from twisted.internet import reactor, threads
from twisted.web.client import downloadPage
import twisted.python.runtime

import urllib2, httplib
from datetime import datetime

# Used to check server validity
date_format = "%Y-%m-%d"
now = datetime.now()
alloweddelta = 2
CheckFile = "LastUpdate.log"
ServerStatusList = {}

PARSERS = {
	'xmltv': 'gen_xmltv',
	'genxmltv': 'gen_xmltv',
}

def relImport(name):
	fullname = __name__.split('.')
	fullname[-1] = name
	mod = __import__('.'.join(fullname))
	for n in fullname[1:]:
		mod = getattr(mod, n)
	return mod

def getParser(name):
	module = PARSERS.get(name, name)
	mod = relImport(module)
	return mod.new()

def getTimeFromHourAndMinutes(hour, minute):
	now = time.localtime()
	begin = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
						hour, minute, 0, now.tm_wday, now.tm_yday, now.tm_isdst)))
	return begin

def bigStorage(minFree, default, *candidates):
	try:
		diskstat = os.statvfs(default)
		free = diskstat.f_bfree * diskstat.f_bsize
		if (free > minFree) and (free > 50000000):
			return default
	except Exception, e:
		print>>log, "[EPGImport] Failed to stat %s:" % default, e
	mounts = open('/proc/mounts', 'rb').readlines()
	# format: device mountpoint fstype options #
	mountpoints = [x.split(' ', 2)[1] for x in mounts]
	for candidate in candidates:
		if candidate in mountpoints:
			try:
				diskstat = os.statvfs(candidate)
				free = diskstat.f_bfree * diskstat.f_bsize
				if free > minFree:
					return candidate
			except:
				pass
	return default

class OudeisImporter:
	'Wrapper to convert original patch to new one that accepts multiple services'
	def __init__(self, epgcache):
		self.epgcache = epgcache
	# difference with old patch is that services is a list or tuple, this
	# wrapper works around it.
	def importEvents(self, services, events):
		for service in services:
			self.epgcache.importEvent(service, events)

def unlink_if_exists(filename):
	try:
		os.unlink(filename)
	except:
		pass

class EPGImport:
	"""Simple Class to import EPGData"""

	def __init__(self, epgcache, channelFilter):
		self.eventCount = None
		self.epgcache = None
		self.storage = None
		self.sources = []
		self.source = None
		self.epgsource = None
		self.fd = None
		self.iterator = None
		self.onDone = None
		self.epgcache = epgcache
		self.channelFilter = channelFilter

	def checkValidServer(self, serverurl):
		dirname, filename = os.path.split(serverurl)
		FullString = dirname + "/" + CheckFile
		req = urllib2.build_opener()
		req.addheaders = [('User-Agent', 'Twisted Client')]
		dlderror=0
		if ServerStatusList.has_key(dirname):
			# If server is know return its status immediately
			return ServerStatusList[dirname]
		else:
			# Server not in the list so checking it
			try:
				response = req.open(FullString)
			except urllib2.HTTPError, e:
				print ('[EPGImport] HTTPError in checkValidServer= ' + str(e.code))
				dlderror=1
			except urllib2.URLError, e:
				print ('[EPGImport] URLError in checkValidServer= ' + str(e.reason))
				dlderror=1
			except httplib.HTTPException, e:
				print ('[EPGImport] HTTPException in checkValidServer')
				dlderror=1
			except Exception:
				print ('[EPGImport] Generic exception in checkValidServer')
				dlderror=1

			if not dlderror:
				LastTime = response.read().strip('\n')
				try:
					FileDate = datetime.strptime(LastTime, date_format)
				except ValueError:
					print>>log, "[EPGImport] checkValidServer wrong date format in file rejecting server %s" % dirname
					ServerStatusList[dirname]=0
					return ServerStatusList[dirname]
				delta = (now - FileDate).days
				if delta <= alloweddelta:
					# OK the delta is in the foreseen windows
					ServerStatusList[dirname]=1
				else:
					# Sorry the delta is higher removing this site
					print>>log, "[EPGImport] checkValidServer rejected server delta days too high: %s" % dirname
					ServerStatusList[dirname]=0

			else:
				# We need to exclude this server
				print>>log, "[EPGImport] checkValidServer rejected server download error for: %s" % dirname
				ServerStatusList[dirname]=0
		return ServerStatusList[dirname]

	def beginImport(self, longDescUntil = None):
		'Starts importing using Enigma reactor. Set self.sources before calling this.'
		if hasattr(self.epgcache, 'importEvents'):
			self.storage = self.epgcache
		elif hasattr(self.epgcache, 'importEvent'):
			self.storage = OudeisImporter(self.epgcache)
		else:
			print "[EPGImport] oudeis patch not detected, using epg.dat instead."
			import epgdat_importer
			self.storage = epgdat_importer.epgdatclass()
		self.eventCount = 0
		if longDescUntil is None:
			# default to 7 days ahead
			self.longDescUntil = time.time() + 24*3600*7
		else:
			self.longDescUntil = longDescUntil;
		self.nextImport()

	def nextImport(self):
		self.closeReader()
		if not self.sources:
			self.closeImport()
			return
		self.source = self.sources.pop()
		print>>log, "[EPGImport] nextImport, source=", self.source.description
		self.fetchUrl(self.source.url)

	def fetchUrl(self, filename):
		if filename.startswith('http:') or filename.startswith('ftp:'):
			self.do_download(filename, self.afterDownload, self.downloadFail)
		else:
			self.afterDownload(None, filename, deleteFile=False)

	def createIterator(self, filename):
		self.source.channels.update(self.channelFilter, filename)
		return getParser(self.source.parser).iterator(self.fd, self.source.channels.items)

	def readEpgDatFile(self, filename, deleteFile=False):
		if not hasattr(self.epgcache, 'load'):
			print>>log, "[EPGImport] Cannot load EPG.DAT files on unpatched enigma. Need CrossEPG patch."
			return
		unlink_if_exists(HDD_EPG_DAT)
		try:
			if filename.endswith('.gz'):
				print>>log, "[EPGImport] Uncompressing", filename
				import shutil
				fd = gzip.open(filename, 'rb')
				epgdat = open(HDD_EPG_DAT, 'wb')
				shutil.copyfileobj(fd, epgdat)
				del fd
				epgdat.close()
				del epgdat
			else:
				if filename != HDD_EPG_DAT:
					os.symlink(filename, HDD_EPG_DAT)
			print>>log, "[EPGImport] Importing", HDD_EPG_DAT
			self.epgcache.load()
			if deleteFile:
				unlink_if_exists(filename)
		except Exception, e:
			print>>log, "[EPGImport] Failed to import %s:" % filename, e

	def afterDownload(self, result, filename, deleteFile=False):
		print>>log, "[EPGImport] afterDownload", filename
		try:
			if not os.path.getsize(filename):
				raise Exception, "File is empty"
		except Exception, e:
			self.downloadFail(e)
			return
		if self.source.parser == 'epg.dat':
			if twisted.python.runtime.platform.supportsThreads():
				print>>log, "[EPGImport] Using twisted thread for DAT file"
				threads.deferToThread(self.readEpgDatFile, filename, deleteFile).addCallback(lambda ignore: self.nextImport())
			else:
				self.readEpgDatFile(filename, deleteFile)
				return
		if filename.endswith('.gz'):
			self.fd = gzip.open(filename, 'rb')
			try:
				# read a bit to make sure it's a gzip file
				self.fd.read(10)
				self.fd.seek(0,0)
			except Exception, e:
				print>>log, "[EPGImport] File downloaded is not a valid gzip file", filename
				self.downloadFail(e)
				return
		elif filename.endswith('.xz') or filename.endswith('.lzma'):
			try:
				import lzma
			except ImportError:
				from backports import lzma
			self.fd = lzma.open(filename, 'rb')
			try:
				# read a bit to make sure it's an xz file
				self.fd.read(10)
				self.fd.seek(0,0)
			except Exception, e:
				print>>log, "[EPGImport] File downloaded is not a valid xz file", filename
				self.downloadFail(e)
				return
		else:
			self.fd = open(filename, 'rb')
		if deleteFile and self.source.parser != 'epg.dat':
			try:
				print>>log, "[EPGImport] unlink", filename
				os.unlink(filename)
			except Exception, e:
				print>>log, "[EPGImport] warning: Could not remove '%s' intermediate" % filename, e
		self.channelFiles = self.source.channels.downloadables()
		if not self.channelFiles:
			self.afterChannelDownload(None, None)
		else:
			filename = random.choice(self.channelFiles)
			self.channelFiles.remove(filename)
			self.do_download(filename, self.afterChannelDownload, self.channelDownloadFail)

	def afterChannelDownload(self, result, filename, deleteFile=True):
		print>>log, "[EPGImport] afterChannelDownload", filename
		if filename:
			try:
				if not os.path.getsize(filename):
					raise Exception, "File is empty"
			except Exception, e:
				self.channelDownloadFail(e)
				return
		if twisted.python.runtime.platform.supportsThreads():
			print>>log, "[EPGImport] Using twisted thread"
			threads.deferToThread(self.doThreadRead, filename).addCallback(lambda ignore: self.nextImport())
			deleteFile = False # Thread will delete it
		else:
			self.iterator = self.createIterator(filename)
			reactor.addReader(self)
		if deleteFile and filename:
			try:
				os.unlink(filename)
			except Exception, e:
				print>>log, "[EPGImport] warning: Could not remove '%s' intermediate" % filename, e

	def fileno(self):
		if self.fd is not None:
			return self.fd.fileno()

	def doThreadRead(self, filename):
		'This is used on PLi with threading'
		for data in self.createIterator(filename):
			if data is not None:
				self.eventCount += 1
				try:
					r,d = data
					if d[0] > self.longDescUntil:
						# Remove long description (save RAM memory)
						d = d[:4] + ('',) + d[5:]
					self.storage.importEvents(r, (d,))
				except Exception, e:
					print>>log, "[EPGImport] ### importEvents exception:", e
		print>>log, "[EPGImport] ### thread is ready ### Events:", self.eventCount
		if filename:
			try:
				os.unlink(filename)
			except Exception, e:
				print>>log, "[EPGImport] warning: Could not remove '%s' intermediate" % filename, e

	def doRead(self):
		'called from reactor to read some data'
		try:
			# returns tuple (ref, data) or None when nothing available yet.
			data = self.iterator.next()
			if data is not None:
				self.eventCount += 1
				try:
					r,d = data
					if d[0] > self.longDescUntil:
						# Remove long description (save RAM memory)
						d = d[:4] + ('',) + d[5:]
					self.storage.importEvents(r, (d,))
				except Exception, e:
					print>>log, "[EPGImport] importEvents exception:", e
		except StopIteration:
			self.nextImport()

	def connectionLost(self, failure):
		'called from reactor on lost connection'
		# This happens because enigma calls us after removeReader
		print>>log, "[EPGImport] connectionLost", failure

	def channelDownloadFail(self, failure):
		print>>log, "[EPGImport] download channel failed:", failure
		if self.channelFiles:
			filename = random.choice(self.channelFiles)
			self.channelFiles.remove(filename)
			self.do_download(filename, self.afterChannelDownload, self.channelDownloadFail)
		else:
			print>>log, "[EPGImport] no more alternatives for channels"
			self.nextImport()

	def downloadFail(self, failure):
		print>>log, "[EPGImport] download failed:", failure
		self.source.urls.remove(self.source.url)
		if self.source.urls:
			print>>log, "[EPGImport] Attempting alternative URL"
			self.source.url = random.choice(self.source.urls)
			self.fetchUrl(self.source.url)
		else:
			self.nextImport()

	def logPrefix(self):
		return '[EPGImport]'

	def closeReader(self):
		if self.fd is not None:
			reactor.removeReader(self)
			self.fd.close()
			self.fd = None
			self.iterator = None

	def closeImport(self):
		self.closeReader()
		self.iterator = None
		self.source = None
		if hasattr(self.storage, 'epgfile'):
			needLoad = self.storage.epgfile
		else:
			needLoad = None
		self.storage = None
		if self.eventCount is not None:
			print>>log, "[EPGImport] imported %d events" % self.eventCount
			reboot = False
			if self.eventCount:
				if needLoad:
					print>>log, "[EPGImport] no Oudeis patch, load(%s) required" % needLoad
					reboot = True
					try:
						if hasattr(self.epgcache, 'load'):
							print>>log, "[EPGImport] attempt load() patch"
							if needLoad != HDD_EPG_DAT:
								os.symlink(needLoad, HDD_EPG_DAT)
							self.epgcache.load()
							reboot = False
							unlink_if_exists(needLoad)
					except Exception, e:
						print>>log, "[EPGImport] load() failed:", e
				elif hasattr(self.epgcache, 'save'):
					self.epgcache.save()
			elif hasattr(self.epgcache, 'timeUpdated'):
				self.epgcache.timeUpdated()
			if self.onDone:
				self.onDone(reboot=reboot, epgfile=needLoad)
		self.eventCount = None
		print>>log, "[EPGImport] #### Finished ####"

	def isImportRunning(self):
		return self.source is not None

	def do_download(self, sourcefile, afterDownload, downloadFail):
		path = bigStorage(9000000, '/tmp', '/media/DOMExtender', '/media/cf', '/media/mmc', '/media/usb', '/media/hdd')
		filename = os.path.join(path, 'epgimport')
		ext = os.path.splitext(sourcefile)[1]
		# Keep sensible extension, in particular the compression type
		if ext and len(ext) < 6:
			filename += ext
		sourcefile = sourcefile.encode('utf-8')
		print>>log, "[EPGImport] Downloading: " + sourcefile + " to local path: " + filename
		if self.checkValidServer(sourcefile) == 1:
			downloadPage(sourcefile, filename).addCallbacks(afterDownload, downloadFail, callbackArgs=(filename,True))
			return filename
		else:
			self.downloadFail("checkValidServer reject the server")