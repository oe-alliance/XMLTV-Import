import os
import log
from xml.etree.cElementTree import ElementTree, Element, SubElement, tostring, iterparse
from Tools.Directories import fileExists
import gzip
import time
import socket
import urllib
import urllib2

# timeout in seconds
timeout = 5
socket.setdefaulttimeout(timeout)

channelCache = {}

def isLocalFile(filename):
	# we check on a '://' as a silly way to check local file
	return '://' not in filename

def getChannels(path, name):
	global channelCache
	dirname, filename = os.path.split(path)
	if name:
		if isLocalFile(name):
			channelfile = os.path.join(dirname, name)
		else:
			channelfile = name
	else:
		channelfile = os.path.join(dirname, filename.split('.', 1)[0] + '.channels.xml')
	try:
		return channelCache[channelfile]
	except KeyError:
		pass
	c = EPGChannel(channelfile)
	channelCache[channelfile] = c
	return c
	

class EPGChannel:
	def __init__(self, filename):
		self.mtime = None
		self.filename = filename
		self.items = None

	def openStream(self):
		if not isLocalFile(self.filename):
			# just returning urlopen() does not work, parser needs 'tell'
			filename,headers = urllib.urlretrieve(self.filename)
		else:
			filename = self.filename
		fd = open(filename, 'rb')
		if self.filename.endswith('.gz'):
			fd = gzip.GzipFile(fileobj = fd, mode = 'rb')
		if filename != self.filename:
			os.unlink(filename)
		return fd

	def parse(self, filterCallback):
		print>>log,"[XMLTVImport] Parsing channels from '%s'" % self.filename
		self.items = {}
		file = self.openStream()
		for event, elem in iterparse(file):
			if elem.tag == 'channel':
				id = elem.get('id')
				ref = elem.text
				if id and ref:
					ref = ref.encode('latin-1')
					if filterCallback(ref):
						if self.items.has_key(id):
							self.items[id].append(ref)
						else:
							self.items[id] = [ref]
				elem.clear()
		file.close()

	def update(self, filterCallback = lambda x: True):
		try:
			if isLocalFile(self.filename):
				mtime = os.path.getmtime(self.filename)
				if (not self.mtime) or (self.mtime < mtime):
					self.parse(filterCallback)
					self.mtime = mtime
			else:
				# Check at most once a day
				now = time.time()
				if (not self.mtime) or (self.mtime + 86400 < now):
					self.mtime = now
					self.parse(filterCallback)
		except Exception, e:
			print>>log, "[XMLTVImport] Failed to parse channels from '%s':" % self.filename, e

	def __repr__(self):
		return "EPGChannel(file=%s, channels=%s, mtime=%s)" % (self.filename, self.items and len(self.items), self.mtime) 

class EPGSource:
	def __init__(self, path, elem):
		self.parser = elem.get('type')
		self.url = elem.findtext('url')
		self.description = elem.findtext('description')
		if not self.description:
			self.description = self.url
		self.format = elem.get('format', 'xml')
		self.channels = getChannels(path, elem.get('channels'))

def enumSourcesFile(sourcefile, filter=None):
	result = ""
	file = open(sourcefile, 'rb')
	for event, elem in iterparse(file):
		if elem.tag == 'source':
			s = EPGSource(sourcefile, elem)
			elem.clear()
			if (filter is None) or (s.description in filter):
				yield s
	file.close()

def enumSources(path, filter=None):
	try:
		for sourcefile in os.listdir(path):
			if sourcefile.endswith('.sources.xml') and not sourcefile.startswith('rytec'):
				sourcefile = os.path.join(path, sourcefile)
				print>>log, "[XMLTVImport] using source",sourcefile
				try: 
					for s in enumSourcesFile(sourcefile, filter):
						yield s
				except Exception, e:
					print>>log, "[XMLTVImport] failed to open", sourcefile, "Error:", e
		try:
			print "downloading source list from EPGalfasite"
			filename,headers = urllib.urlretrieve('http://home.scarlet.be/epgalfasite/crossepgsources.gz')
			fd = open(filename, 'rb')
			sfd = gzip.GzipFile(fileobj = fd, mode = 'rb')
			os.unlink(filename)
		except Exception, e:
			print e
		import random
		count = 0
		if sfd:
			sourcelist = sfd.readlines()
			noofsources = int(len(sourcelist))
			while (count < noofsources):
				try: 
					sourcefile = random.choice(sourcelist)
					sourcefile = sourcefile.replace("\n","")
					print>>log, "[XMLTVImport] using source",sourcefile
					sourcefile,headers = urllib.urlretrieve(sourcefile)
					for s in enumSourcesFile(sourcefile, filter):
						yield s
					count = noofsources + 1
				except Exception, e:
					print>>log, "[XMLTVImport] source is unavailble"
					sourcelist = [l for l in sourcelist if sourcefile not in l]
					count = count + 1
					if count == 3:
						print>>log, "[XMLTVImport] all online sources are unavailble."
	except Exception, e:
		print>>log, "[XMLTVImport] failed to list", path, "Error:", e
