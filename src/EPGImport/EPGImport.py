#!/usr/bin/python
#
# This file no longer has a direct link to Enigma2, allowing its use anywhere
# you can supply a similar interface. See plugin.py and OfflineImport.py for
# the contract.

import gzip
from os import statvfs, symlink, unlink
from os.path import exists, getsize, join, splitext
from requests import packages, Session
from requests.exceptions import HTTPError, RequestException
from secrets import choice
from string import ascii_lowercase
from time import localtime, mktime, time
from twisted.internet import reactor, threads
from twisted.internet.reactor import callInThread
import twisted.python.runtime

import lzma
from Components.config import config


packages.urllib3.disable_warnings(packages.urllib3.exceptions.InsecureRequestWarning)

# Used to check server validity
HDD_EPG_DAT = "/hdd/epg.dat"
if config.misc.epgcache_filename.value:
	HDD_EPG_DAT = config.misc.epgcache_filename.value
else:
	config.misc.epgcache_filename.setValue(HDD_EPG_DAT)
PARSERS = {"xmltv": "gen_xmltv", "genxmltv": "gen_xmltv"}


def threadGetPage(url=None, file=None, urlheaders=None, success=None, fail=None, *args, **kwargs):
	# print("[EPGImport][threadGetPage] url, file, args, kwargs", url, "   ", file, "   ", args, "   ", kwargs)
	try:
		s = Session()
		s.headers = {}
		response = s.get(url, verify=False, headers=urlheaders, timeout=15, allow_redirects=True)
		response.raise_for_status()
		# check here for content-disposition header so to extract the actual filename (if the url doesnt contain it)
		content_disp = response.headers.get("Content-Disposition", "")
		filename = content_disp.split('filename="')[-1].split('"')[0]
		ext = splitext(file)[1]
		if filename:
			ext = splitext(filename)[1]
			if ext and len(ext) < 6:
				file += ext
		if not ext:
			ext = splitext(response.url)[1]
			if ext and len(ext) < 6:
				file += ext

		with open(file, "wb") as f:
			f.write(response.content)
		# print("[EPGImport][threadGetPage] file completed: ", file)
		success(file, deleteFile=True)

	except HTTPError as httperror:
		print("EPGImport][threadGetPage] Http error: ", httperror)
		fail(httperror)  # E0602 undefined name "error"

	except RequestException as error:
		print("[EPGImport][threadGetPage] error: ", error)
		# if fail is not None:
		fail(error)


def relImport(name):
	fullname = __name__.split(".")
	fullname[-1] = name
	mod = __import__(".".join(fullname))
	for n in fullname[1:]:
		mod = getattr(mod, n)

	return mod


def getParser(name):
	module = PARSERS.get(name, name)
	mod = relImport(module)
	return mod.new()


def getTimeFromHourAndMinutes(hour, minute):
	# Check if the hour and minute are within valid ranges
	if not (0 <= hour < 24):
		raise ValueError("Hour must be between 0 and 23")
	if not (0 <= minute < 60):
		raise ValueError("Minute must be between 0 and 59")

	# Get the current local time
	now = localtime()

	# Calculate the timestamp for the specified time (today with the given hour and minute)
	begin = int(mktime((
		now.tm_year,     # Current year
		now.tm_mon,      # Current month
		now.tm_mday,     # Current day
		hour,            # Specified hour
		minute,          # Specified minute
		0,               # Seconds (set to 0)
		now.tm_wday,     # Day of the week
		now.tm_yday,     # Day of the year
		now.tm_isdst     # Daylight saving time (DST)
	)))

	return begin


def bigStorage(minFree, default, *candidates):
	try:
		diskstat = statvfs(default)
		free = diskstat.f_bfree * diskstat.f_bsize
		if free > minFree and free > 50000000:
			return default
	except Exception as e:
		print(f"[EPGImport][bigStorage] Failed to stat {default}:", e)

	with open("/proc/mounts", "rb") as f:
		# format: device mountpoint fstype options #
		mountpoints = [x.decode().split(" ", 2)[1] for x in f.readlines()]

	for candidate in candidates:
		if candidate in mountpoints:
			try:
				diskstat = statvfs(candidate)
				free = diskstat.f_bfree * diskstat.f_bsize
				if free > minFree:
					return candidate
			except Exception as e:
				print(f"[EPGImport][bigStorage] Failed to stat {candidate}:", e)
				continue
	print("[EPGImport][bigStorage] Insufficient storage for download")
	return None


class OudeisImporter:
	"""Wrapper to convert original patch to new one that accepts multiple services"""

	def __init__(self, epgcache):
		self.epgcache = epgcache

	# difference with old patch is that services is a list or tuple, this
	# wrapper works around it.

	def importEvents(self, services, events):
		for service in services:
			try:
				self.epgcache.importEvent(service, events)
			except Exception as e:
				import traceback
				traceback.print_exc()
				print(f"[EPGImport][OudeisImporter][importEvents] ### importEvents exception: {e}")


def unlink_if_exists(filename):
	try:
		unlink(filename)
	except Exception as e:
		print(f"[EPGImport] warning: Could not remove '{filename}' intermediate {repr(e)}")


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
		return

	def beginImport(self, longDescUntil=None):
		"""Starts importing using Enigma reactor. Set self.sources before calling this."""
		if hasattr(self.epgcache, "importEvents"):
			print("[EPGImport][beginImport] using importEvents.")
			self.storage = self.epgcache
		elif hasattr(self.epgcache, "importEvent"):
			print("[EPGImport][beginImport] using importEvent(Oudis).")
			self.storage = OudeisImporter(self.epgcache)
		else:
			print("[EPGImport][beginImport] oudeis patch not detected, using using epgdat_importer.epgdatclass/epg.dat instead.")
			from . import epgdat_importer
			self.storage = epgdat_importer.epgdatclass()

		self.eventCount = 0
		if longDescUntil is None:
			# default to 7 days ahead
			self.longDescUntil = time() + 24 * 3600 * 7
		else:
			self.longDescUntil = longDescUntil
		self.nextImport()

	def nextImport(self):
		self.closeReader()
		if not self.sources:
			self.closeImport()
			return

		self.source = self.sources.pop()

		print(f"[EPGImport][nextImport], source= {self.source.description}")
		self.fetchUrl(self.source.url)

	def fetchUrl(self, filename):
		if filename.startswith("http:") or filename.startswith("https:") or filename.startswith("ftp:"):
			# print("[EPGImport][fetchurl] download Basic ...url filename", filename)
			self.urlDownload(filename, self.afterDownload, self.downloadFail)
		else:
			self.afterDownload(filename, deleteFile=False)

	def urlDownload(self, sourcefile, afterDownload, downloadFail):
		media_path = "/media/hdd"
		host = "".join([choice(ascii_lowercase) for i in range(5)])
		check_mount = False
		if exists(media_path):
			with open("/proc/mounts", "r") as f:
				for line in f:
					ln = line.split()
					if len(ln) > 1 and ln[1] == media_path:
						check_mount = True

		# print("[EPGImport][urlDownload]2 check_mount ", check_mount)
		pathDefault = media_path if check_mount else "/tmp"
		path = bigStorage(9000000, pathDefault, "/media/usb", "/media/cf")  # lets use HDD and flash as main backup media
		if not path:
			path = "/tmp"
		filename = join(path, host)
		ext = splitext(sourcefile)[1]
		# Keep sensible extension, in particular the compression type
		if ext and len(ext) < 6:
			filename += ext
		Headers = {
			"User-Agent": "Twisted Client",
			"Accept-Encoding": "gzip, deflate",
			"Accept": "*/*",
			"Connection": "keep-alive"}

		print(f"[EPGImport][urlDownload] Downloading: {sourcefile} to local path: {filename}")
		callInThread(threadGetPage, url=sourcefile, file=filename, urlheaders=Headers, success=afterDownload, fail=downloadFail)

	def afterDownload(self, filename, deleteFile=False):
		# print("[EPGImport][afterDownload] filename", filename)
		if not exists(filename):
			self.downloadFail("File not exists")
			return
		try:
			if not getsize(filename):
				raise Exception("[EPGImport][afterDownload] File is empty")
		except Exception as e:
			print(f"[EPGImport][afterDownload] Exception filename 0 {filename}")
			self.downloadFail(e)
			return

		if self.source.parser == "epg.dat":
			if twisted.python.runtime.platform.supportsThreads():
				print("[EPGImport][afterDownload] Using twisted thread for DAT file")
				threads.deferToThread(self.readEpgDatFile, filename, deleteFile).addCallback(lambda ignore: self.nextImport())
			else:
				self.readEpgDatFile(filename, deleteFile)
				return

		if filename.endswith(".gz"):
			self.fd = gzip.open(filename, "rb")
			try:  # read a bit to make sure it's a gzip file
				self.fd.read(10)
				self.fd.seek(0, 0)
			except gzip.BadGzipFile as e:
				print(f"[EPGImport][afterDownload] File downloaded is not a valid gzip file {filename}")
				try:
					print(f"[EPGImport][afterDownload] unlink {filename}")
					unlink_if_exists(filename)
				except Exception as e:
					print(f"[EPGImport][afterDownload] warning: Could not remove '{filename}' intermediate", str(e))
				self.downloadFail(e)
				return

		elif filename.endswith(".xz") or filename.endswith(".lzma"):
			self.fd = lzma.open(filename, "rb")
			try:  # read a bit to make sure it's an xz file
				self.fd.read(10)
				self.fd.seek(0, 0)
			except lzma.LZMAError as e:
				print(f"[EPGImport][afterDownload] File downloaded is not a valid xz file {filename}")
				try:
					print(f"[EPGImport][afterDownload] unlink {filename}")
					unlink_if_exists(filename)
				except Exception as e:
					print(f"[EPGImport][afterDownload] warning: Could not remove '{filename}' intermediate", e)
				self.downloadFail(e)
				return

		else:
			self.fd = open(filename, "rb")

		if deleteFile and self.source.parser != "epg.dat":
			try:
				print(f"[EPGImport][afterDownload] unlink {filename}")
				unlink_if_exists(filename)
			except Exception as e:
				print(f"[EPGImport][afterDownload] warning: Could not remove '{filename}' intermediate", e)

		self.channelFiles = self.source.channels.downloadables()
		if not self.channelFiles:
			self.afterChannelDownload(None, None)
		else:
			filename = choice(self.channelFiles)
			self.channelFiles.remove(filename)
			self.urlDownload(filename, self.afterChannelDownload, self.channelDownloadFail)
		return

	def downloadFail(self, failure):
		print(f"[EPGImport][downloadFail] download failed: {failure}")
		if self.source.url in self.source.urls:
			self.source.urls.remove(self.source.url)
		if self.source.urls:
			print("[EPGImport][downloadFail] Attempting alternative URL for Basic")
			self.source.url = choice(self.source.urls)
			print(f"[EPGImport][downloadFail] try alternative download url {self.source.url}")
			self.fetchUrl(self.source.url)
		else:
			self.nextImport()

	def afterChannelDownload(self, filename, deleteFile=True):
		if filename:
			try:
				if not getsize(filename):
					raise Exception("File is empty")
			except Exception as e:
				print(f"[EPGImport][afterChannelDownload] Exception filename {filename}")
				self.channelDownloadFail(e)
				return
		if twisted.python.runtime.platform.supportsThreads():
			print(f"[EPGImport][afterChannelDownload] Using twisted thread - filename  {filename}")
			threads.deferToThread(self.doThreadRead, filename).addCallback(lambda ignore: self.nextImport())
			deleteFile = False  # Thread will delete it
		else:
			self.iterator = self.createIterator(filename)
			reactor.addReader(self)
		if deleteFile and filename:
			try:
				unlink_if_exists(filename)
			except Exception as e:
				print(f"[EPGImport][afterChannelDownload] warning: Could not remove '{filename}' intermediate", e)

	def channelDownloadFail(self, failure):
		print(f"[EPGImport][channelDownloadFail] download channel failed: {failure}")
		if self.channelFiles:
			filename = choice(self.channelFiles)
			if filename in self.channelFiles:
				self.channelFiles.remove(filename)
			print(f"[EPGImport][channelDownloadFail] retry alternative download channel - new url filename {filename}")
			self.urlDownload(filename, self.afterChannelDownload, self.channelDownloadFail)
		else:
			print("[EPGImport][channelDownloadFail] no more alternatives for channels")
			self.nextImport()

	def createIterator(self, filename):
		# print("[EPGImport][createIterator], filename", filename)
		self.source.channels.update(self.channelFilter, filename)
		return getParser(self.source.parser).iterator(self.fd, self.source.channels.items, self.source.offset)

	def readEpgDatFile(self, filename, deleteFile=False):
		if not hasattr(self.epgcache, "load"):
			print("[EPGImport][readEpgDatFile] Cannot load EPG.DAT files on unpatched enigma. Need CrossEPG patch.")
			return

		unlink_if_exists(HDD_EPG_DAT)

		try:
			if filename.endswith(".gz"):
				print(f"[EPGImport] Uncompressing {filename}")
				from shutil import copyfileobj
				fd = gzip.open(filename, "rb")
				epgdat = open(HDD_EPG_DAT, "wb")
				copyfileobj(fd, epgdat)
				del fd
				epgdat.close()
				del epgdat

			elif filename != HDD_EPG_DAT:
				symlink(filename, HDD_EPG_DAT)

			print(f"[EPGImport][readEpgDatFile] Importing {HDD_EPG_DAT}")
			self.epgcache.load()

			if deleteFile:
				unlink_if_exists(filename)
		except Exception as e:
			print(f"[EPGImport][readEpgDatFile] Failed to import {filename}: {e}")

	def fileno(self):
		if self.fd is not None:
			return self.fd.fileno()
		else:
			return

	def doThreadRead(self, filename):
		try:
			for data in self.createIterator(filename):
				if data is not None:
					self.eventCount += 1
					r, d = data
					if len(d) >= 5:
						if d[0] > self.longDescUntil:
							d = d[:4] + ("",) + d[5:]

						# for i, item in enumerate(d):
							# print(f"[EPGImport][doThreadRead] ### Checking item {i}: {item}, type: {type(item)}")

						d = tuple(
							int(item) if isinstance(item, (str, bytes)) and self.is_numeric(item) else  # Converte in intero se numerico
							(item.decode('utf-8') if isinstance(item, bytes) else item)  # Decodifica i bytes in stringhe
							for item in d
						)

						try:
							self.storage.importEvents(r, (d,))
						except Exception as e:
							print(f"[EPGImport][doThreadRead] ### importEvents exception: {e}")
							# print(f"[EPGImport][doThreadRead] ### Event data: {r}, {d}")
							print("[EPGImport][doThreadRead] ### Stack trace:")
							import traceback
							traceback.print_exc()  # Stampa lo stack trace per diagnosticare meglio
					else:
						print("[EPGImport][doThreadRead] ### Invalid data tuple length, skipping event.")
		except Exception as e:
			print(f"### Exception in doThreadRead: {e}")
			import traceback
			traceback.print_exc()

		finally:
			if filename:
				try:
					unlink_if_exists(filename)
				except Exception as e:
					print(f"[EPGImport][doThreadRead] warning: Could not remove '{filename}' intermediate {e}")
			print("[EPGImport][doThreadRead] ### thread is ready ### Events:", self.eventCount)
			return

	def is_numeric(self, value):
		"""Check if integer value"""
		try:
			int(value)
			return True
		except ValueError:
			return False

	def doRead(self):
		"""called from reactor to read some data"""
		try:
			data = next(self.iterator)
			if data is not None:
				self.eventCount += 1
				try:
					r, d = data
					if d[0] > self.longDescUntil:
						# Remove long description (save RAM memory)
						d = d[:4] + ("",) + d[5:]
					self.storage.importEvents(r, (d,))
				except Exception as e:
					print(f"[EPGImport][doRead] importEvents exception: {e}")
		except StopIteration:
			self.nextImport()
		return

	def connectionLost(self, failure):
		"""called from reactor on lost connection"""
		# This happens because enigma calls us after removeReader
		print(f"[EPGImport] connectionLost {failure}")

	def closeReader(self):
		if self.fd is not None:
			reactor.removeReader(self)
			self.fd.close()
			self.fd = None
			self.iterator = None
		return

	def closeImport(self):
		self.closeReader()
		self.iterator = None
		self.source = None
		if hasattr(self.storage, "epgfile"):
			needLoad = self.storage.epgfile
		else:
			needLoad = None

		self.storage = None

		if self.eventCount is not None:
			print(f"[EPGImport] imported {self.eventCount} events")
			reboot = False
			if self.eventCount:
				if needLoad:
					print(f"[EPGImport] no Oudeis patch, load({needLoad}) required")
					reboot = True
					try:
						if hasattr(self.epgcache, "load"):
							print("[EPGImport] attempt load() patch")
							if needLoad != HDD_EPG_DAT:
								symlink(needLoad, HDD_EPG_DAT)
							self.epgcache.load()
							reboot = False
							unlink_if_exists(needLoad)
					except Exception as e:
						print(f"[EPGImport] load() failed: {e}")
				elif hasattr(self.epgcache, "save"):
					self.epgcache.save()
			elif hasattr(self.epgcache, "timeUpdated"):
				self.epgcache.timeUpdated()
			if self.onDone:
				self.onDone(reboot=reboot, epgfile=needLoad)
		self.eventCount = None
		print("[EPGImport] #### Finished ####")

	def isImportRunning(self):
		return self.source is not None
