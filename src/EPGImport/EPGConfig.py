from gzip import GzipFile
import lzma
from os import fstat, listdir, remove
from os.path import exists, getmtime, join, split
from Components.config import config
from pickle import dump, load, HIGHEST_PROTOCOL
from secrets import choice
from time import time
from xml.etree.cElementTree import iterparse
from zipfile import ZipFile
from re import compile

from . import log


# User selection stored here, so it goes into a user settings backup
SETTINGS_FILE = "/etc/enigma2/epgimport.conf"

channelCache = {}

global filterCustomChannel

# Verify that the epgimport configuration is defined
if hasattr(config.plugins, "epgimport") and hasattr(config.plugins.epgimport, "filter_custom_channel"):
	filterCustomChannel = config.plugins.epgimport.filter_custom_channel.value
else:
	filterCustomChannel = False  # Fallback is not defined


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


def enumerateXML(fp, tag=None):
	"""
	Enumerates ElementTree nodes from file object 'fp' for a specific tag.
	Args:
		fp: File-like object containing XML data.
		tag: The XML tag to search for. If None, processes all nodes.
	Yields:
		ElementTree.Element objects matching the specified tag.
	"""
	doc = iterparse(fp, events=("start", "end"))
	_, root = next(doc)  # Get the root element
	depth = 0

	for event, element in doc:
		if tag is None or element.tag == tag:  # Process all nodes if no tag is specified
			if event == "start":
				depth += 1
			elif event == "end":
				depth -= 1
				if depth == 0:  # Tag is fully parsed
					yield element
					element.clear()  # Free memory for the element
				depth -= 1
		if event == "end" and element.tag != tag:  # Clear other elements to free memory
			element.clear()
	root.clear()


"""
elem.clear()
When you parse an XML file with iterparse(),
the elements are loaded into memory one at a time. However,
if you don't explicitly clear them,
the parser will keep everything in memory until the end of parsing,
which can consume a lot of RAM, especially with large files.
"""


def set_channel_id_filter():
	full_filter = ""
	try:
		with open("/etc/epgimport/channel_id_filter.conf", "r") as channel_id_file:
			for channel_id_line in channel_id_file:
				# Skipping comments in channel_id_filter.conf
				if not channel_id_line.startswith("#"):
					clean_channel_id_line = channel_id_line.strip()
					# Blank line in channel_id_filter.conf will produce a full match so we need to skip them.
					if clean_channel_id_line:
						try:
							# We compile individually every line just to report error
							full_filter = compile(clean_channel_id_line)
						except:
							print(f"[EPGImport] ERROR: {clean_channel_id_line} is not a valid regex. It will be ignored.", file=log)
						else:
							full_filter = full_filter + clean_channel_id_line + "|"
	except IOError:
		print("[EPGImport] INFO: no channel_id_filter.conf file found.", file=log)
		# Return a dummy filter (empty line filter) all accepted except empty channel id
		compiled_filter = compile("^$")
		return compiled_filter

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
		except:
			print(f"[EPGImport] ERROR: final regex {full_filter} doesn't compile properly.", file=log)
			# Return a dummy filter (empty line filter) all accepted except empty channel id
			compiled_filter = compile("^$")
		else:
			print(f"[EPGImport] INFO : final regex {full_filter} compiled successfully.", file=log)

	return compiled_filter


class EPGChannel:
	def __init__(self, filename, urls=None, offset=0):
		self.mtime = None
		self.name = filename
		self.urls = [filename] if urls is None else urls
		self.items = None  # defaultdict(set)
		self.offset = offset

	def openStream(self, filename):
		if not exists(filename):
			raise FileNotFoundError("EPGChannel - File not found: " + filename)

		fd = open(filename, "rb")
		if not fstat(fd.fileno()).st_size:
			raise Exception("File is empty")

		if filename.endswith(".gz"):
			fd = GzipFile(fileobj=fd, mode="rb")
		elif filename.endswith((".xz", ".lzma")):
			fd = lzma.open(filename, "rb")
		elif filename.endswith(".zip"):
			from io import BytesIO
			zip_obj = ZipFile(filename, "r")
			fd = BytesIO(zip_obj.open(zip_obj.namelist()[0]).read())
		return fd

	def parse(self, filterCallback, downloadedFile, FilterChannelEnabled):
		print(f"[EPGImport] Parsing channels from '{self.name}'", file=log)
		channel_id_filter = set_channel_id_filter()
		if self.items is None:
			self.items = {}
		# self.items = defaultdict(list)
		try:
			context = iterparse(self.openStream(downloadedFile))
			for event, elem in context:
				if elem.tag == "channel":
					id_channel = elem.get("id")
					if id_channel:
						id_channel = id_channel.lower()
					ref = str(elem.text)
					filter_result = channel_id_filter.match(id_channel)
					if filter_result and FilterChannelEnabled:
						if filter_result.group():
							print(f"[EPGImport] INFO : skipping {filter_result.group()} due to channel_id_filter.conf", file=log)
						if id_channel and ref:
							if filterCallback(ref):
								if id_channel in self.items:
									try:
										if ref in self.items[id_channel]:
											# deduplicate before remove
											unique_refs = list(dict.fromkeys(self.items[id_channel]))
											unique_refs.remove(ref)
											self.items[id_channel] = unique_refs
									except Exception as e:
										print(f"[EPGImport] failed to remove from list {self.items[id_channel]} ref {ref} Error: {e}", file=log)
					else:
						if id_channel and ref:
							if filterCallback(ref):
								if id_channel not in self.items:
									self.items[id_channel] = []
								self.items[id_channel].append(ref)
								# deduplicate just once here
								self.items[id_channel] = list(dict.fromkeys(self.items[id_channel]))

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
		return None

	def __repr__(self):
		return f"EPGChannel(urls={self.urls}, channels={self.items and len(self.items)}, mtime={self.mtime})"


class EPGSource:
	def __init__(self, path, elem, category=None, offset=0):
		self.parser = elem.get("type", "gen_xmltv")
		self.nocheck = int(elem.get("nocheck", 0))
		self.urls = [e.text.strip() for e in elem.findall("url")]
		self.url = choice(self.urls)
		self.description = elem.findtext("description", self.url)
		self.category = category
		if not self.description:
			self.description = self.url
		self.offset = offset
		self.format = elem.get("format", "xml")
		self.channels = getChannels(path, elem.get("channels"), offset)


def enumSourcesFile(sourcefile, filter=None, categories=False):
	global channelCache
	category = None
	try:
		with open(sourcefile, "rb") as file:
			for event, elem in iterparse(file, events=("start", "end")):
				if event == "end":
					if elem.tag == "source":
						# Calculate custom time offset in minutes
						try:
							offset = int(elem.get("offset", "+0000")) * 3600 // 100
						except ValueError:
							offset = 0  # Default offset if parsing fails

						s = EPGSource(sourcefile, elem, category, offset)
						elem.clear()
						if (filter is None) or (s.description in filter):
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
	SETTINGS_FILE_PKL = "settings.pkl"
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
	storeUserSettings(SETTINGS_FILE_PKL, [1, "twee"])
	assert loadUserSettings(SETTINGS_FILE_PKL) == {"sources": [1, "twee"]}
	remove(SETTINGS_FILE_PKL)
	for p in enumSources(path, x):
		t = (p.description, p.urls, p.parser, p.format, p.channels, p.nocheck)
		assert t in ln
		ln.remove(t)
	assert not ln
	for name, c in channelCache.items():
		print(f"Update:{name}")
		c.update()
		print(f"# of channels: {len(c.items)}")
