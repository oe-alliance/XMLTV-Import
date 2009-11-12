import time
import os
from random import random

import enigma

# Config
from Components.config import config, ConfigEnableDisable, ConfigSubsection, \
			 ConfigYesNo, ConfigClock, getConfigListEntry, \
			 ConfigSelection
import Screens.Standby
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Components.ConfigList import ConfigListScreen
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.Label import Label
from Components.SelectionList import SelectionList, SelectionEntryComponent

#Set default configuration
config.plugins.epgimport = ConfigSubsection()
config.plugins.epgimport.enabled = ConfigEnableDisable(default = True)
config.plugins.epgimport.wakeup = ConfigClock(default = ((4*60) + 45) * 60) # 4:45
config.plugins.epgimport.showinextensions = ConfigYesNo(default = True)
config.plugins.epgimport.deepstandby = ConfigSelection(default = "skip", choices = [
		("wakeup", _("Wake up and import")),
#		("later", _("Import on next boot")),
		("skip", _("Skip the import")) 
		])

# Plugin
import EPGImport
import EPGConfig

# Plugin definition
from Plugins.Plugin import PluginDescriptor

# historically located (not a problem, we want to update it)
CONFIG_PATH = '/etc/epgimport'

# Global variable
autoStartTimer = None
_session = None
epgimport = EPGImport.EPGImport(enigma.eEPGCache.getInstance())

##################################
# Configuration GUI

class Config(ConfigListScreen,Screen):
	skin = """
<screen position="center,center" size="560,400" title="EPG Import Configuration" >
	<ePixmap name="red"    position="0,0"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
	<ePixmap name="green"  position="140,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
	<ePixmap name="yellow" position="280,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/yellow.png" transparent="1" alphatest="on" /> 
	<ePixmap name="blue"   position="420,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/blue.png" transparent="1" alphatest="on" /> 

	<widget name="key_red" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" /> 
	<widget name="key_green" position="140,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" /> 
	<widget name="key_yellow" position="280,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
	<widget name="key_blue" position="420,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />

	<ePixmap alphatest="on" pixmap="skin_default/icons/clock.png" position="480,383" size="14,14" zPosition="3"/>
	<widget font="Regular;18" halign="left" position="505,380" render="Label" size="55,20" source="global.CurrentTime" transparent="1" valign="center" zPosition="3">
		<convert type="ClockToText">Default</convert>
	</widget>
	
	<widget name="config" position="10,40" size="540,240" scrollbarMode="showOnDemand" />
	<widget name="status" position="10,300" size="540,60" font="Regular;20" />
</screen>"""
		
	def __init__(self, session, args = 0):
		self.session = session
		Screen.__init__(self, session)
		cfg = config.plugins.epgimport
		self.list = [
			getConfigListEntry(_("Daily automatic import"), cfg.enabled),
			getConfigListEntry(_("Automatic start time"), cfg.wakeup),
			getConfigListEntry(_("When in deep standby"), cfg.deepstandby),
			getConfigListEntry(_("Show in extensions"), cfg.showinextensions)
			]
		ConfigListScreen.__init__(self, self.list)
		self["status"] = Label()
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Ok"))
		self["key_yellow"] = Button(_("Manual"))
		self["key_blue"] = Button(_("Sources"))
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"],
		{
			"red": self.cancel,
			"green": self.save,
			"yellow": self.doimport,
			"blue": self.dosources,
			"save": self.save,
			"cancel": self.cancel,
			"ok": self.save,
		}, -2)
		self.updateTimer = enigma.eTimer()
	    	self.updateTimer.callback.append(self.updateStatus)
		self.updateTimer.start(2000)
	
	def save(self):
		#print "saving"
		self.updateTimer.stop()
		self.saveAll()
		self.close(True,self.session)

	def cancel(self):
		#print "cancel"
		self.updateTimer.stop()
		for x in self["config"].list:
			x[1].cancel()
		self.close(False,self.session)
		
	def updateStatus(self):
		text = ""
		if epgimport.isImportRunning():
			text = _("Importing:")
			src = epgimport.source
			text += " %s\n%s events" % (src.description, epgimport.eventCount)
		# test
		#ec = enigma.eEPGCache.getInstance()
		#text += "\nOudeis patch: " + str(hasattr(ec, 'importEvent'))
		#text += "\nLoad() patch: " + str(hasattr(ec, 'load'))
		#text += "\nMiLo patch: "   + str(hasattr(ec, 'importEvents'))
		# end test
		#print "Status:", text
		self["status"].setText(text)
		
	def doimport(self):
        	if epgimport.isImportRunning():
  	    		print "[EPGImport] Already running, won't start again"
                	self.session.open(MessageBox, _("EPGImport Plugin\nImport of epg data is still in progress. Please wait."), MessageBox.TYPE_ERROR, timeout = 10, close_on_any_key = True)
			return
		config = EPGConfig.loadUserSettings()
    		sources = [ s for s in EPGConfig.enumSources(CONFIG_PATH, filter = config["sources"]) ]
    		if not sources:
    			self.session.open(MessageBox, _("No active EPG sources found, nothing to do"), MessageBox.TYPE_INFO, timeout = 10, close_on_any_key = True)
	    		return
    		# make it a stack, first on top.
    		sources.reverse()
    		epgimport.sources = sources
        	self.session.openWithCallback(self.do_import_callback, MessageBox, _("EPGImport Plugin\nImport of epg data will start\nThis may take a few minutes\nIs this ok?"), MessageBox.TYPE_YESNO, timeout = 15, default = True)

	def do_import_callback(self, confirmed):
      		if not confirmed:
      			return
      		try:
      			epgimport.onDone = doneImport
			epgimport.beginImport()
      		except Exception, e:
        		print "[EPGImport] Error at start:", e 
        		self.session.open(MessageBox, _("EPGImport Plugin\nFailed to start:\n") + str(e), MessageBox.TYPE_ERROR, timeout = 15, close_on_any_key = True)
		self.updateStatus()
		
	def dosources(self):
		self.session.openWithCallback(self.sourcesDone, EPGImportSources)
		
	def sourcesDone(self, confirmed, sources):
		# Called with True and list of config items on Okay.
		print "sourcesDone(): ", confirmed, sources
		pass
		
class EPGImportSources(Screen):
	"Pick sources from config"
	skin = """
<screen position="center,center" size="560,400" title="EPG Import Sources" >
	<ePixmap name="red"    position="0,0"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
	<ePixmap name="green"  position="140,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
	<ePixmap name="yellow" position="280,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/yellow.png" transparent="1" alphatest="on" /> 
	<ePixmap name="blue"   position="420,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/blue.png" transparent="1" alphatest="on" /> 

	<widget name="key_red" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" /> 
	<widget name="key_green" position="140,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" /> 
	<widget name="key_yellow" position="280,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
	<widget name="key_blue" position="420,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />

	<ePixmap alphatest="on" pixmap="skin_default/icons/clock.png" position="480,383" size="14,14" zPosition="3"/>
	<widget font="Regular;18" halign="left" position="505,380" render="Label" size="55,20" source="global.CurrentTime" transparent="1" valign="center" zPosition="3">
		<convert type="ClockToText">Default</convert>
	</widget>
	
	<widget name="list" position="10,40" size="540,240" scrollbarMode="showOnDemand" />
</screen>"""
		
	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Ok"))
		self["key_yellow"] = Button() # _("Import now"))
		self["key_blue"] = Button()
		config = EPGConfig.loadUserSettings()
		filter = config["sources"]
		sources = [
			# (description, value, index, selected)
			SelectionEntryComponent(x.description, x.description, 0, (filter is None) or (x.description in filter))
			for x in EPGConfig.enumSources(CONFIG_PATH, filter=None)
			]
		self["list"] = SelectionList(sources)
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"],
		{
			"red": self.cancel,
			"green": self.save,
			"yellow": self.doimport,
			"save": self.save,
			"cancel": self.cancel,
			"ok": self["list"].toggleSelection,
		}, -2)
		
	def save(self):
		sources = [ item[0][1] for item in self["list"].list if item[0][3] ]
		print "[EPGImport] Selected sources:", sources
		EPGConfig.storeUserSettings(sources=sources)
		self.close(True, sources)
		
	def cancel(self):
		self.close(False, None)
		
	def doimport(self):
		pass


def main(session, **kwargs):
    session.openWithCallback(doneConfiguring, Config)

def doneConfiguring(session, retval):
    "user has closed configuration, check new values...."
    if autoStartTimer is not None:
        autoStartTimer.update()

def doneImport(reboot=False, epgfile=None):
	global _session
	msg = _("EPG Import finished, %d events" % epgimport.eventCount)
	if reboot:
		msg += "\n" + _("You must restart Enigma2 to load the EPG data,\nis this OK?")
		_session.openWithCallback(restartEnigma, MessageBox, msg, MessageBox.TYPE_YESNO, timeout = 15, default = True)
	else:
		_session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout = 10, close_on_any_key = True)

      
def restartEnigma(confirmed):
	if not confirmed:
		return
       	# save state of enigma, so we can return to previeus state
       	if Screens.Standby.inStandby:
       	    try:
                open('/tmp/enigmastandby', 'wb').close()
            except:
                print "Failed to create /tmp/enigmastandby"
       	else:
       	    try:
       	        os.remove("/tmp/enigmastandby")
            except:
	        pass	
	# now reboot
    	_session.open(Screens.Standby.TryQuitMainloop, 3)


##################################
# Autostart section

class AutoStartTimer:
	def __init__(self, session):
		self.session = session
		self.timer = enigma.eTimer() 
	    	self.timer.callback.append(self.onTimer)
	    	self.update()
	def getWakeTime(self):
	    if config.plugins.epgimport.enabled.value:
	        clock = config.plugins.epgimport.wakeup.value
	        nowt = time.time()
		now = time.localtime(nowt)
		return int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday,  
	                      clock[0], clock[1], 0, now.tm_wday, now.tm_yday, now.tm_isdst)))
	    else:
	        return -1 
	def update(self, atLeast = 0):
	    self.timer.stop()
	    wake = self.getWakeTime()
	    now = int(time.time())
	    if wake > 0:
		if wake < now + atLeast:
		    # Tomorrow.
		    wake += 24*3600
	        next = wake - now
		self.timer.startLongTimer(next)
	    else:
	    	wake = -1
	    print "[EPGImport] WakeUpTime now set to", wake, "(now=%s)" % now
	    return wake
	def onTimer(self):
		self.timer.stop()
		now = int(time.time())
		print "[EPGImport] onTimer occured at", now
		wake = self.getWakeTime()
		# If we're close enough, we're okay...
		atLeast = 0
		if wake - now < 60: 
			config = EPGConfig.loadUserSettings()
			sources = [ s for s in EPGConfig.enumSources(CONFIG_PATH, filter = config["sources"]) ]
			if sources:
				sources.reverse()
				epgimport.sources = sources
				epgimport.onDone = doneImport
				epgimport.beginImport()
			atLeast = 60
	        self.update(atLeast)

def autostart(reason, session=None, **kwargs):
    "called with reason=1 to during shutdown, with reason=0 at startup?"
    global autoStartTimer
    global _session
    print "[EPGImport] autostart (%s) occured at" % reason, time.time()
    if reason == 0:
    	if session is not None:
		_session = session
		if autoStartTimer is None:
	    		autoStartTimer = AutoStartTimer(session)
	# If WE caused the reboot, put the box back in standby.
	if os.path.exists("/tmp/enigmastandby"):
	    print "[EPGImport] Returning to standby"
	    from Tools import Notifications
	    Notifications.AddNotification(Screens.Standby.Standby)
       	    try:
       	        os.remove("/tmp/enigmastandby")
            except:
	        pass	
    else:
        print "[EPGImport] Stop"
        #if autoStartTimer:
	#	autoStartTimer.stop()        

def getNextWakeup():
    "returns timestamp of next time when autostart should be called"
    if autoStartTimer:
    	if config.plugins.epgimport.deepstandby.value == 'wakeup':
		print "[EPGImport] Will wake up from deep sleep"
		return autoStartTimer.update()
    return -1


def Plugins(**kwargs):
    description = _("Automated EPG Importer")
    where = [PluginDescriptor.WHERE_PLUGINMENU]
    if config.plugins.epgimport.showinextensions.value:
    	where.append(PluginDescriptor.WHERE_EXTENSIONSMENU)
    return [
        PluginDescriptor(
            name="EPGImport",
            description = description,
            where = [
                PluginDescriptor.WHERE_AUTOSTART,
                PluginDescriptor.WHERE_SESSIONSTART
            ],
            fnc = autostart,
            wakeupfnc = getNextWakeup
        ),
    
        PluginDescriptor(
            name="EPGImport",
            description = description,
            where = where,
            icon = 'plugin.png',
            fnc = main
        ),
    ]
