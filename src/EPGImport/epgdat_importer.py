import epgdat
import os
import sys

import sys
# Hack to make this test run on Windows (where the reactor cannot handle files)
if sys.platform.startswith('win'):	
	tmppath = '.'
	settingspath = '.'
else:
	tmppath = '/tmp'
	settingspath = '/etc/enigma2'

class epgdatclass:
	def __init__(self):
		self.data = None
		self.services = None
		path = tmppath
		if self.checkPath('/media/cf'):
			path='/media/cf'
		if self.checkPath('/media/usb'):
			path='/media/usb'
		if self.checkPath('/media/hdd'):
			path='/media/hdd'
		self.epgfile = os.path.join(path, 'epg_new.dat')
		self.epg = epgdat.epgdat_class(path, settingspath, self.epgfile)

	def importEvents(self, services, dataTupleList):
		'This method is called repeatedly for each bit of data'
		if services != self.services:
			self.commitService()
			self.services = services
		for program in dataTupleList:
			if program[3]:
				desc = program[3] + '\n' + program[4]
			else:
				desc = program[4]
			self.epg.add_event(program[0], program[1], program[2], desc)

	def commitService(self):
		if self.services is not None:
			self.epg.preprocess_events_channel(self.services)  

	def epg_done(self):
		try:
			self.commitService()
			self.epg.final_process()
		except:
			print "[EPGImport] Failure in epg_done"
			import traceback
			traceback.print_exc()
		self.epg = None

	def checkPath(self,path):
		f = os.popen('mount', "r")
		for l in f.xreadlines():
			if l.find(path)!=-1:
				return True
		return False

	def __del__(self):
		'Destructor - finalize the file when done'
		if self.epg is not None:
			self.epg_done()
