from gzip import GzipFile
from os import fstat, listdir, remove
from os.path import exists, getmtime, join, split
from pickle import dump, load, HIGHEST_PROTOCOL
from secrets import choice
from time import time
from xml.etree.cElementTree import iterparse
from zipfile import ZipFile

from . import log

# User selection stored here, so it goes into a user settings backup
SETTINGS_FILE = "/etc/enigma2/epgimport.conf"

channelCache = {}


def isLocalFile(filename):
	# we check on a "://" as a silly way to check local file
	return "://" not in filename


def getChannels(path, name, offset):
	global channelCache
	if name in channelCache:
		return channelCache[name]
	dirname, filename = split(path)
	if name:
		channelfile = join(dirname, name) if isLocalFile(name) else name
	else:
		channelfile = join(dirname, filename.split(".", 1)[0] + ".channels.xml")
	try:
		return channelCache[channelfile]
	except KeyError:
		pass
	c = EPGChannel(channelfile, offset=offset)
	channelCache[channelfile] = c
	return c


"""
elem.clear()
When you parse an XML file with iterparse(),
the elements are loaded into memory one at a time. However,
if you don't explicitly clear them,
the parser will keep everything in memory until the end of parsing,
which can consume a lot of RAM, especially with large files.
"""


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

	def openStream(self, filename):
		fd = open(filename, "rb")
		if not fstat(fd.fileno()).st_size:
			raise Exception("File is empty")
		if filename.endswith(".gz"):
			fd = GzipFile(fileobj=fd, mode="rb")
		elif filename.endswith(".xz") or filename.endswith(".lzma"):
			try:
				import lzma
			except ImportError:
				from backports import lzma
			fd = lzma.open(filename, "rb")
		elif filename.endswith(".zip"):
			from io import BytesIO
			zip_obj = ZipFile(filename, "r")
			fd = BytesIO(zip_obj.open(zip_obj.namelist()[0]).read())
		return fd

	def parse(self, filterCallback, downloadedFile):
		print(f"[EPGImport] Parsing channels from '{self.name}'", file=log)

		if self.items is None:
			self.items = {}

		try:
			stream = self.openStream(downloadedFile)
			if stream is None:
				print(f"[EPGImport] Error: Unable to open stream for {downloadedFile}", file=log)
				return

			context = iterparse(stream)
			for event, elem in context:
				if elem.tag == "channel":
					channel_id = elem.get("id").lower()
					ref = str(elem.text or '').strip()

					if not channel_id or not ref:
						continue  # Skip empty values
					if ref:
						if filterCallback(ref):
							"""
							if channel_id in self.items:
								self.items[channel_id].append(ref)
							else:
								self.items[channel_id] = [ref]
							"""
							if channel_id in self.items:
								self.items[channel_id].append(ref)
								self.items[channel_id] = list(dict.fromkeys(self.items[channel_id]))  # Ensure uniqueness
							else:
								self.items[channel_id] = [ref]
					elem.clear()
		except Exception as e:
			print(f"[EPGImport] Failed to parse {downloadedFile} Error: {e}", file=log)
			import traceback
			traceback.print_exc()

	def update(self, filterCallback, downloadedFile=None):
		customFile = "/etc/epgimport/custom.channels.xml"
		# Always read custom file since we don't know when it was last updated
		# and we don't have multiple download from server problem since it is always a local file.
		if not exists(customFile):
			customFile = "/etc/epgimport/rytec.channels.xml"

		if exists(customFile):
			print(f"[EPGImport] Parsing channels from '{customFile}'", file=log)
			self.parse(filterCallback, customFile)
		if downloadedFile is not None:
			self.mtime = time()
			return self.parse(filterCallback, downloadedFile)
		elif (len(self.urls) == 1) and isLocalFile(self.urls[0]):
			mtime = getmtime(self.urls[0])
			if (not self.mtime) or (self.mtime < mtime):
				self.parse(filterCallback, self.urls[0])
				self.mtime = mtime

	def downloadables(self):
		if (len(self.urls) == 1) and isLocalFile(self.urls[0]):
			return None
		else:
			# Check at most once a day
			now = time()
			if (not self.mtime) or (self.mtime + 86400 < now):
				return self.urls
		return None

	def __repr__(self):
		return f"EPGChannel(urls={self.urls}, channels={self.items and len(self.items)}, mtime={self.mtime})"


class EPGSource:
	def __init__(self, path, elem, category=None, offset=0):
		self.parser = elem.get("type", "gen_xmltv")
		self.nocheck = int(elem.get("nocheck", 0))
		"""
		self.parser = elem.get("type")
		nocheck = elem.get("nocheck")
		if nocheck is None:
			self.nocheck = 0
		elif nocheck == "1":
			self.nocheck = 1
		else:
			self.nocheck = 0
		"""
		self.urls = [e.text.strip() for e in elem.findall("url")]
		self.url = choice(self.urls)
		self.description = elem.findtext("description")
		self.category = category
		self.offset = offset
		if not self.description:
			self.description = self.url
		self.format = elem.get("format", "xml")
		self.channels = getChannels(path, elem.get("channels"), offset)


def enumSourcesFile(sourcefile, filter=None, categories=False):
	global channelCache
	category = None
	try:
		with open(sourcefile, "rb") as f:
			for event, elem in iterparse(f, events=("start", "end")):
				if event == "end":
					if elem.tag == "source":
						# Calculate custom time offset in minutes
						try:
							offset = int(elem.get("offset", "+0000")) * 3600 // 100
						except ValueError:
							offset = 0  # Default offset if parsing fails

						s = EPGSource(sourcefile, elem, category, offset)
						elem.clear()
						if filter is None or s.description in filter:
							yield s

					elif elem.tag == "channel":
						name = elem.get("name")
						if name:
							urls = [e.text.strip() for e in elem.findall("url")]
							if name in channelCache:
								channelCache[name].urls = urls
							else:
								channelCache[name] = EPGChannel(name, urls)
						elem.clear()

					elif elem.tag == "sourcecat":
						category = None
						elem.clear()

				elif event == "start" and elem.tag == "sourcecat":
					category = elem.get("sourcecatname")
					if categories:
						yield category
	except Exception as e:
		print(f"[EPGImport] Error reading source file: {sourcefile} Error: {e}")


def enumSources(path, filter=None, categories=False):
	try:
		for sourcefile in listdir(path):
			if sourcefile.endswith(".sources.xml"):
				sourcefile = join(path, sourcefile)
				try:
					for s in enumSourcesFile(sourcefile, filter, categories):
						yield s
				except Exception as e:
					print(f"[EPGImport] failed to open {sourcefile} Error: {e}", file=log)
	except Exception as e:
		print(f"[EPGImport] failed to list {path} Error: {e}", file=log)


def loadUserSettings(filename=SETTINGS_FILE):
	try:
		return load(open(filename, "rb"))
	except Exception as e:
		print(f"[EPGImport] No settings {e}", file=log)
		return {"sources": []}


def storeUserSettings(filename=SETTINGS_FILE, sources=None):
	container = {"sources": sources}
	dump(container, open(filename, "wb"), HIGHEST_PROTOCOL)


if __name__ == "__main__":
	import sys
	x = []
	ln = []
	path = "."
	if len(sys.argv) > 1:
		path = sys.argv[1]
	for p in enumSources(path):
		t = (p.description, p.urls, p.parser, p.format, p.channels, p.nocheck)
		ln.append(t)
		print(t)
		x.append(p.description)
	storeUserSettings("settings.pkl", [1, "twee"])
	assert loadUserSettings("settings.pkl") == {"sources": [1, "twee"]}
	remove("settings.pkl")
	for p in enumSources(path, x):
		t = (p.description, p.urls, p.parser, p.format, p.channels, p.nocheck)
		assert t in ln
		ln.remove(t)
	assert not ln
	for name, c in channelCache.items():
		print(f"Update:{name}")
		c.update()
		print(f"# of channels: {len(c.items)}")
