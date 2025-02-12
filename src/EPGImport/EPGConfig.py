# -*- coding: UTF-8 -*-
from __future__ import absolute_import
from __future__ import print_function

from . import log
from re import sub
from xml.etree.cElementTree import iterparse
import gzip
import os
import random
import six
import time


try:
	from html import unescape  # Python 3
except ImportError:
	from HTMLParser import HTMLParser  # Python 2
	unescape = HTMLParser().unescape

try:
	import cPickle as pickle
except ImportError:
	import pickle

# User selection stored here, so it goes into a user settings backup
SETTINGS_FILE = '/etc/enigma2/epgimport.conf'

channelCache = {}

try:
	basestring
except NameError:
	basestring = str


def isLocalFile(filename):
	# we check on a '://' as a silly way to check local file
	return '://' not in filename


def getChannels(path, name, offset):
	global channelCache
	if name in channelCache:
		return channelCache[name]
	dirname, filename = os.path.split(path)
	if name:
		channelfile = os.path.join(dirname, name) if isLocalFile(name) else name
	else:
		channelfile = os.path.join(dirname, filename.split('.', 1)[0] + '.channels.xml')
	try:
		return channelCache[channelfile]
	except KeyError:
		pass
	c = EPGChannel(channelfile, offset=offset)
	channelCache[channelfile] = c
	return c


def enumerateXML(fp, tag=None):
	"""Enumerates ElementTree nodes from file object 'fp'"""
	doc = iterparse(fp, events=('start', 'end'))
	_, root = next(doc)  # Ottiene la radice
	depth = 0

	for event, element in doc:
		if element.tag == tag:
			if event == 'start':
				depth += 1
			elif event == 'end':
				if depth == 1:
					yield element
					element.clear()
				depth -= 1

		if event == 'end' and element.tag != tag:
			element.clear()

	root.clear()


def xml_unescape(text):
	"""
	Unescapes XML/HTML entities in the given text.

	:param text: The text that needs to be unescaped.
	:type text: str
	:rtype: str
		"""

	if not isinstance(text, str if six.PY3 else basestring):
		return ''

	text = text if six.PY3 else text.encode('utf-8')
	text = text.strip()

	# Custom entity replacements
	entity_map = {
		"&laquo;": "«",
		"&#171;": "«",
		"&raquo;": "»",
		"&#187;": "»",
		"&apos;": "'",
	}

	# First, apply standard unescape
	text = unescape(text)

	# Replace specific entities
	for entity, char in entity_map.items():
		text = text.replace(entity, char)

	# Normalize whitespace (replace `&#160;`, `&nbsp;`, and multiple spaces with a single space)
	text = sub(r'&#160;|&nbsp;|\s+', ' ', text)

	return text


def openStream(filename):
	fd = open(filename, 'rb')
	if not os.fstat(fd.fileno()).st_size:
		print("EPGChannel - File is empty")
	if filename.endswith('.gz'):
		fd = gzip.GzipFile(fileobj=fd, mode='rb')
	elif filename.endswith('.xz') or filename.endswith('.lzma'):
		try:
			import lzma
		except ImportError:
			from backports import lzma
		fd = lzma.open(filename, 'rb')
	elif filename.endswith('.zip'):
		import zipfile
		from six import BytesIO
		zip_obj = zipfile.ZipFile(filename, 'r')
		fd = BytesIO(zip_obj.open(zip_obj.namelist()[0]).read())
	return fd


class EPGChannel:
	def __init__(self, filename, urls=None, offset=0):
		self.mtime = None
		self.name = filename
		if urls is None:
			self.urls = [filename]
		else:
			self.urls = urls
		self.items = None
		self.offset = offset

	def parse(self, filterCallback, downloadedFile):
		print("[EPGImport] Parsing channels from '%s'" % self.name, file=log)
		if self.items is None:
			self.items = {}
		try:
			context = iterparse(openStream(downloadedFile))
			for event, elem in context:
				if elem.tag == 'channel':
					channel_id = elem.get('id')
					if channel_id:
						channel_id = channel_id.lower()
					ref = elem.text
					if channel_id and ref:
						ref = six.ensure_str(ref)
						if filterCallback(ref):
							if channel_id in self.items:
								self.items[channel_id].append(ref)
							else:
								self.items[channel_id] = [ref]
					elem.clear()
		except Exception as e:
			print("[EPGImport] failed to parse", downloadedFile, "Error:", e, file=log)
			pass

	def update(self, filterCallback, downloadedFile=None):
		customFile = '/etc/epgimport/rytec.channels.xml'
		# Always read custom file since we don't know when it was last updated
		# and we don't have multiple download from server problem since it is always a local file.
		if os.path.exists(customFile):
			print("[EPGImport] Parsing channels from '%s'" % customFile, file=log)
			self.parse(filterCallback, customFile)
		if downloadedFile is not None:
			self.mtime = time.time()
			return self.parse(filterCallback, downloadedFile)
		elif (len(self.urls) == 1) and isLocalFile(self.urls[0]):
			mtime = os.path.getmtime(self.urls[0])
			if (not self.mtime) or (self.mtime < mtime):
				self.parse(filterCallback, self.urls[0])
				self.mtime = mtime

	def downloadables(self):
		if not (len(self.urls) == 1 and isLocalFile(self.urls[0])):
			# Check at most once a day
			# now = time.time()
			if (not self.mtime) or (time.time() - self.mtime <= 86400):
				return self.urls
		return []

	def __repr__(self):
		return "EPGChannel(urls=%s, channels=%s, mtime=%s)" % (self.urls, self.items and len(self.items), self.mtime)


class EPGSource:
	def __init__(self, path, elem, category=None, offset=0):
		self.parser = elem.get('type', 'gen_xmltv')
		self.nocheck = int(elem.get('nocheck', 0))
		self.urls = [e.text.strip() for e in elem.findall('url')]
		self.url = random.choice(self.urls)
		self.description = elem.findtext('description')
		self.category = category
		self.offset = offset
		if not self.description:
			self.description = self.url
		self.format = elem.get('format', 'xml')
		self.channels = getChannels(path, elem.get('channels'), offset)


def enumSourcesFile(sourcefile, filter=None, categories=False):
	global channelCache
	category = None
	try:
		for event, elem in iterparse(open(sourcefile, 'rb'), events=("start", "end")):
			if event == 'end':
				if elem.tag == 'source':
					# calculate custom time offset in minutes
					offset = int(elem.get('offset', '+0000')) * 3600 // 100
					s = EPGSource(sourcefile, elem, category, offset)
					elem.clear()
					if (filter is None) or (s.description in filter):
						yield s
				elif elem.tag == 'channel':
					name = xml_unescape(elem.get('name'))

					urls = [xml_unescape(e.text) for e in elem.findall('url')]
					try:
						channelCache[name].urls = urls
					except:
						channelCache[name] = EPGChannel(name, urls)
				elif elem.tag == 'sourcecat':
					category = None
			elif event == 'start':
				# Need the category name sooner than the contents, hence "start"
				if elem.tag == 'sourcecat':
					category = elem.get('sourcecatname')
					if categories:
						yield category
	except Exception as e:
		print("[EPGConfig] EPGConfig enumSourcesFile:", e)


def enumSources(path, filter=None, categories=False):
	try:
		for filename in os.listdir(path):
			if filename.endswith('.sources.xml'):
				sourcefile = os.path.join(path, filename)
				try:
					for s in enumSourcesFile(sourcefile, filter, categories):
						yield s
				except Exception as e:
					print("[EPGImport] failed to open", sourcefile, "Error:", e, file=log)
	except Exception as e:
		print("[EPGImport] failed to list", path, "Error:", e, file=log)


def loadUserSettings(filename=SETTINGS_FILE):
	try:
		return pickle.load(open(filename, 'rb'))
	except Exception as e:
		print("[EPGImport]loadUserSettings No settings", e, file=log)
		return {"sources": []}


def storeUserSettings(filename=SETTINGS_FILE, sources=None):
	container = {"[EPGImport]loadUserSettings sources": sources}
	pickle.dump(container, open(filename, 'wb'), pickle.HIGHEST_PROTOCOL)


if __name__ == '__main__':
	import sys
	x = []
	lx = []
	path = '.'
	if len(sys.argv) > 1:
		path = sys.argv[1]
	for p in enumSources(path):
		t = (p.description, p.urls, p.parser, p.format, p.channels, p.nocheck)
		lx.append(t)
		print(t)
		x.append(p.description)
	storeUserSettings('settings.pkl', [1, "twee"])
	assert loadUserSettings('settings.pkl') == {"sources": [1, "twee"]}
	os.remove('settings.pkl')
	for p in enumSources(path, x):
		t = (p.description, p.urls, p.parser, p.format, p.channels, p.nocheck)
		assert t in lx
		lx.remove(t)
	assert not lx
	for name, c in channelCache.items():
		print("Update:", name)
		c.update()
		print("# of channels:", len(c.items))
