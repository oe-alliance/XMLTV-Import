#!/usr/bin/python
#
# To test this script on something that is not a Dreambox, such as a Windows PC
# just run it with Python. You'll need Python's "twisted" library.
# Supply the test .xml files on the command line, and the input files
# where they can be found. On Linux, you can also download from the internet,
# on windows the xmltv files must be local files.
# 
import os
import sys
import time
import XMLTVConfig
import XLMTVImport

XLMTVImport.HDD_EPG_DAT = "./epg.dat.new" 

# Emulate an Enigma that has no patch whatsoever.
class FakeEnigma:
	def getInstance(self):
		return self
#	def load(self):
#		print "...load..."
#	def importEvents(self, *args):
#		print args

def importFrom(epgimport, sourceXml):
	# Hack to make this test run on Windows (where the reactor cannot handle files)
	if sys.platform.startswith('win'):
		import twisted.python.runtime
		twisted.python.runtime.platform.supportsThreads = lambda: False
		class FakeReactor:
			def addReader(self, r):
				self.r = r
			def removeReader(self, r):
				if self.r is r:
					self.r = None
				else:
					raise Exception, "Removed reader without adding it"
			def run(self):
				while self.r is not None:
					self.r.doRead()
			def stop(self):
				print "reactor stopped"
				pass
		XLMTVImport.reactor = FakeReactor()
	sources = [ s for s in XMLTVConfig.enumSourcesFile(sourceXml, filter = None) ]
	sources.reverse()
	epgimport.sources = sources
	epgimport.onDone = done
	epgimport.beginImport(longDescUntil = time.time() + (5*24*3600))
	XLMTVImport.reactor.run()

#----------------------------------------------
def done(reboot=False, epgfile=None):
	XLMTVImport.reactor.stop()
	print "Done, data is in", epgfile
	### When code arrives here, EPG data is stored in filename XLMTVImport.HDD_EPG_DAT
	### So to copy it to FTP or whatever, this is the place to add that code. 

if len(sys.argv) <= 1:
	print "Usage: %s source.xml [...]" % sys.argv[0]
epgimport = XLMTVImport.XLMTVImport(FakeEnigma(), lambda x: True)
for xml in sys.argv[1:]:
	importFrom(epgimport, xml)
