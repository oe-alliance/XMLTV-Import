#!/usr/bin/python
#
# This file no longer has a direct link to Enigma2, allowing its use anywhere
# you can supply a similar interface. See plugin.py and OfflineImport.py for
# the contract. 
# 
import time
import os
import gzip

HDD_EPG_DAT = "/hdd/epg.dat" 

from twisted.internet import reactor, threads
from twisted.web.client import downloadPage
import twisted.python.runtime

PARSERS = {
#	'radiotimes': 'uk_radiotimes',
	'xmltv': 'gen_xmltv',
	'genxmltv': 'gen_xmltv',
#	'mythxmltv': 'myth_xmltv',
#	'nlwolf': 'nl_wolf'
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

class OudeisImporter:
	'Wrapper to convert original patch to new one that accepts multiple services'
	def __init__(self, epgcache):
		self.epgcache = epgcache
	# difference with old patch is that services is a list or tuple, this
	# wrapper works around it.
	def importEvents(self, services, events):
		for service in services:
			self.epgcache.importEvent(service, events)
        
class EPGImport:
    """Simple Class to import EPGData"""

    def __init__(self, epgcache):
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
        print "[EPGImport] nextImport, source=", self.source.description
 	filename = self.source.url
	if filename.startswith('http:') or filename.startswith('ftp:'):
	    self.do_download(filename)
	else:
	    self.afterDownload(None, filename, deleteFile=False)

    def createIterator(self):
	self.source.channels.update()
	return getParser(self.source.parser).iterator(self.fd, self.source.channels.items)

    def readEpgDatFile(self, filename, deleteFile=False):
    	if not hasattr(self.epgcache, 'load'):
            print "[EPGImport] Cannot load EPG.DAT files on unpatched enigma. Need CrossEPG patch."
            return
	try:
	    os.unlink(HDD_EPG_DAT)
	except:
	    pass # ignore...
        try:
            if filename.endswith('.gz'):
                print "[EPGImport] Uncompressing", filename
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
            print "[EPGImport] Importing", HDD_EPG_DAT
            self.epgcache.load()
            if deleteFile:
        	    try:
        	        os.unlink(filename)
        	    except:
        	        pass # ignore...
        except Exception, e:
            print "[EPGImport] Failed to import %s:" % filename, e


    def afterDownload(self, result, filename, deleteFile=False):
        print "[EPGImport] afterDownload", filename
        if self.source.parser == 'epg.dat':
	    if twisted.python.runtime.platform.supportsThreads():
		print "[EPGImport] Using twisted thread for DAT file"
		threads.deferToThread(self.readEpgDatFile, filename, deleteFile).addCallback(lambda ignore: self.nextImport())
            else:
                self.readEpgDatFile(filename, deleteFile)
            return
        if filename.endswith('.gz'):
            self.fd = gzip.open(filename, 'rb')
        else:
            self.fd = open(filename, 'rb')
	if twisted.python.runtime.platform.supportsThreads():
		print "[EPGImport] Using twisted thread!"
		threads.deferToThread(self.doThreadRead).addCallback(lambda ignore: self.nextImport())
	else:
		self.iterator = createIterator(self)
                reactor.addReader(self)
	if deleteFile:
		try:
			print "[EPGImport] unlink", filename
			os.unlink(filename)
		except Exception, e:
			print "[EPGImport] warning: Could not remove '%s' intermediate" % filename, e

    def fileno(self):
    	if self.fd is not None:
    		return self.fd.fileno()
    		
    def doThreadRead(self):
    	'This is used on PLi with threading'
    	for data in self.createIterator():
    		if data is not None:
    		    self.eventCount += 1
	            try:
                        r,d = data
                        if d[0] > self.longDescUntil:
                                # Remove long description (save RAM memory)
                                d = d[:4] + ('',) + d[5:]
	            	self.storage.importEvents(r, (d,))
	            except Exception, e:
	        	print "[EPGImport] ### importEvents exception:", e
	print "[EPGImport] ### thread is ready ### Events:", self.eventCount 

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
	        	print "[EPGImport] importEvents exception:", e
    	except StopIteration:
    		self.nextImport()

    def connectionLost(self, failure):
    	'called from reactor on lost connection'
    	# This happens because enigma calls us after removeReader
    	print "[EPGImport] connectionLost", failure

    def downloadFail(self, failure):
    	print "[EPGImport] download failed:", failure
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
    	    print "[EPGImport] imported %d events" % self.eventCount
    	    reboot = False
    	    if self.eventCount:
    	    	if needLoad:
	    	    print "[EPGImport] no Oudeis patch, load(%s) required" % needLoad
  	    	    reboot = True
  	    	    try:
                    	if hasattr(self.epgcache, 'load'):
  	    	    	    print "[EPGImport] attempt load() patch"
  	    	    	    if needLoad != HDD_EPG_DAT:
	  	    	    	os.symlink(needLoad, HDD_EPG_DAT)
			    self.epgcache.load()
			    reboot = False
			    try:
			    	os.unlink(needLoad)
			    except:
			    	pass # ignore...
		    except Exception, e:
		    	print "[EPGImport] load() failed:", e
    	    if self.onDone:
    		self.onDone(reboot=reboot, epgfile=needLoad)
    	self.eventCount = None
        print "[EPGImport] #### Finished ####"
	
    def isImportRunning(self):
    	return self.source is not None
        
    def do_download(self,sourcefile):
        path = self.bigStorage('/tmp', '/media/hdd', '/media/cf', '/media/usb')
        print "do_download path:", path
        filename = os.path.join(path, 'epgimport')
        if sourcefile.endswith('.gz'):
            filename += '.gz'
        sourcefile = sourcefile.encode('utf-8')
        print "Downloading: " + sourcefile + " To local path: " + filename
        downloadPage(sourcefile, filename).addCallbacks(self.afterDownload, self.downloadFail, callbackArgs=(filename,True))
        return filename

    def bigStorage(self, default, *candidates):
        mounts = open('/proc/mounts', 'rb').readlines()
	# format: device mountpoint fstype options #
        mountpoints = [x.split(' ', 2)[1] for x in mounts]
        for candidate in candidates:
            if candidate in mountpoints:
                return candidate
    	return default
    
# Test code moved to OfflineImport.py
