# -*- coding: UTF-8 -*-
from gzip import GzipFile
from os import fstat, listdir, remove
from os.path import exists, getmtime, join, split
from random import choice
from time import time
from html import unescape
from re import compile, sub, error as reError
from pickle import dump, load, HIGHEST_PROTOCOL
from xml.etree.cElementTree import iterparse

from . import log
from . filterCustomChannel import filterCustomChannel


# User selection stored here, so it goes into a user settings backup
SETTINGS_FILE = '/etc/enigma2/epgimport.conf'

channelCache = {}


def isLocalFile(filename):
	# we check on a '://' as a silly way to check local file
	return '://' not in filename


def getChannels(path, name, offset):
	global channelCache
	if name in channelCache:
		return channelCache[name]
	dirname, filename = split(path)
	if name:
		channelfile = join(dirname, name) if isLocalFile(name) else name
	else:
		channelfile = join(dirname, filename.split('.', 1)[0] + '.channels.xml')
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

	if not isinstance(text, str):
		return ''

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
	if not fstat(fd.fileno()).st_size:
		raise Exception("File is empty")
	if filename.endswith('.gz'):
		fd = GzipFile(fileobj=fd, mode='rb')
	elif filename.endswith('.xz') or filename.endswith('.lzma'):
		import lzma
		fd = lzma.open(filename, 'rb')
	elif filename.endswith('.zip'):
		from zipfile import ZipFile
		from io import BytesIO
		zip_obj = ZipFile(filename, 'r')
		fd = BytesIO(zip_obj.open(zip_obj.namelist()[0]).read())
	return fd


def set_channel_id_filter():
	full_filter = ""
	try:
		with open('/etc/epgimport/channel_id_filter.conf', 'r') as channel_id_file:
			for channel_id_line in channel_id_file:
				# Skipping comments in channel_id_filter.conf
				if not channel_id_line.startswith("#"):
					clean_channel_id_line = channel_id_line.strip()
					# Blank line in channel_id_filter.conf will produce a full match so we need to skip them.
					if clean_channel_id_line:
						try:
							# We compile indivually every line just to report error
							full_filter = compile(clean_channel_id_line)
						except reError:
							print("[EPGImport] ERROR: " + clean_channel_id_line + " is not a valid regex. It will be ignored.", file=log)
						else:
							full_filter = full_filter + clean_channel_id_line + "|"
	except IOError:
		print("[EPGImport] INFO: no channel_id_filter.conf file found.", file=log)
		# Return a dummy filter (empty line filter) all accepted except empty channel id
		compiled_filter = compile("^$")
		return (compiled_filter)
	# Last char is | so remove it
	full_filter = full_filter[:-1]
	# all channel id are matched in lower case so creating the filter in lowercase too
	full_filter = full_filter.lower()
	# channel_id_filter.conf file exist but is empty, it has only comments, or only invalid regex
	if len(full_filter) == 0:
		# full_filter is empty returning dummy filter
		compiled_filter = compile("^$")
	else:
		try:
			compiled_filter = compile(full_filter)
		except reError:
			print("[EPGImport] ERROR: final regex " + full_filter + " doesn't compile properly.", file=log)
			# Return a dummy filter  (empty line filter) all accepted except empty channel id
			compiled_filter = compile("^$")
		else:
			print("[EPGImport] INFO : final regex " + full_filter + " compiled successfully.", file=log)

	return (compiled_filter)


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

	def parse(self, filterCallback, downloadedFile, FilterChannelEnabled):
		print("[EPGImport] Parsing channels from '%s'" % self.name, file=log)
		channel_id_filter = set_channel_id_filter()
		if self.items is None:
			self.items = {}
		try:
			context = iterparse(openStream(downloadedFile))
			for event, elem in context:
				if elem.tag == 'channel':
					id = elem.get('id')
					id = id.lower()
					filter_result = channel_id_filter.match(id)
					if filter_result and FilterChannelEnabled:
						# Just to avoid false positive in logging since the same parse function is used in two different cases.
						if filter_result.group():
							print("[EPGImport] INFO : skipping", filter_result.group(), "due to channel_id_filter.conf", file=log)
						ref = str(elem.text)
						if id and ref:
							if filterCallback(ref):
								if id in self.items:
									try:
										if ref in self.items[id]:
											# remove only remove the first occurrence turning list into dict will make the reference unique so remove will work as expected.
											self.items[id] = list(dict.fromkeys(self.items[id]))
											self.items[id].remove(ref)
									except Exception as e:
										print("[EPGImport] failed to remove from list ", self.items[id], " ref ", ref, "Error:", e, file=log)
					else:
						# print("[EPGImport] INFO : processing", id, file=log)
						ref = str(elem.text)
						if id and ref:
							if filterCallback(ref):
								if id in self.items:
									self.items[id].append(ref)
									# turning list into dict will make the reference unique to avoid loading twice the same EPG data.
									self.items[id] = list(dict.fromkeys(self.items[id]))
								else:
									self.items[id] = [ref]
					elem.clear()
		except Exception as e:
			print("[EPGImport] failed to parse", downloadedFile, "Error:", e, file=log)
			pass

	def update(self, filterCallback, downloadedFile=None):
		customFile = '/etc/epgimport/custom.channels.xml'
		# Always read custom file since we don't know when it was last updated
		# and we don't have multiple download from server problem since it is always a local file.
		if not exists(customFile):
			customFile = '/etc/epgimport/rytec.channels.xml'

		if exists(customFile):
			print("[EPGImport] Parsing channels from '%s'" % customFile, file=log)
			self.parse(filterCallback, customFile, filterCustomChannel)
		if downloadedFile is not None:
			self.mtime = time()
			return self.parse(filterCallback, downloadedFile, True)
		elif (len(self.urls) == 1) and isLocalFile(self.urls[0]):
			try:
				mtime = getmtime(self.urls[0])
			except:
				mtime = None
			if (not self.mtime) or (mtime is not None and self.mtime < mtime):
				self.parse(filterCallback, self.urls[0], True)
				self.mtime = mtime

	def downloadables(self):
		if (len(self.urls) == 1) and isLocalFile(self.urls[0]):
			return None
		else:
			# Check at most once a day
			now = time()
			if (not self.mtime) or (self.mtime + 86400 < now):
				return self.urls
		return []

	def __repr__(self):
		return "EPGChannel(urls=%s, channels=%s, mtime=%s)" % (self.urls, self.items and len(self.items), self.mtime)


class EPGSource:
	def __init__(self, path, elem, category=None, offset=0):
		self.parser = elem.get('type', 'gen_xmltv')
		self.nocheck = int(elem.get('nocheck', 0))
		self.urls = [e.text.strip() for e in elem.findall('url')]
		self.url = choice(self.urls)
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
		for filename in listdir(path):
			if filename.endswith('.sources.xml'):
				sourcefile = join(path, filename)
				try:
					for s in enumSourcesFile(sourcefile, filter, categories):
						yield s
				except Exception as e:
					print("[EPGImport] failed to open", sourcefile, "Error:", e, file=log)
	except Exception as e:
		print("[EPGImport] failed to list", path, "Error:", e, file=log)


def loadUserSettings(filename=SETTINGS_FILE):
	try:
		return load(open(filename, 'rb'))
	except Exception as e:
		print("[EPGImport]loadUserSettings No settings", e, file=log)
		return {"sources": []}


def storeUserSettings(filename=SETTINGS_FILE, sources=None):
	container = {"[EPGImport]loadUserSettings sources": sources}
	dump(container, open(filename, 'wb'), HIGHEST_PROTOCOL)


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
	remove('settings.pkl')
	for p in enumSources(path, x):
		t = (p.description, p.urls, p.parser, p.format, p.channels, p.nocheck)
		assert t in lx
		lx.remove(t)
	assert not lx
	for name, c in channelCache.items():
		print("Update:", name)
		c.update()
		print("# of channels:", len(c.items))
