# for localized messages
from . import _

import time
import os
import enigma
import log

# Config
from Components.config import config, configfile, ConfigEnableDisable, ConfigSubsection, ConfigYesNo, ConfigClock, getConfigListEntry,  ConfigSelection, ConfigNumber, ConfigText
import Screens.Standby
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Components.ConfigList import ConfigListScreen
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.Label import Label
from Components.Sources.StaticText import StaticText
from Components.SelectionList import SelectionList, SelectionEntryComponent
from Components.ScrollLabel import ScrollLabel
import Components.PluginComponent
from Tools.FuzzyDate import FuzzyTime
import NavigationInstance

from Components.PluginComponent import plugins
from Tools.Directories import resolveFilename, SCOPE_PLUGINS

from boxbranding import getImageDistro

#Set default configuration
config.plugins.xmltvimport = ConfigSubsection()
config.plugins.xmltvimport.enabled = ConfigEnableDisable(default = False)
config.plugins.xmltvimport.runboot = ConfigEnableDisable(default = False)
config.plugins.xmltvimport.wakeupsleep = ConfigEnableDisable(default = False)
config.plugins.xmltvimport.wakeup = ConfigClock(default = 7*60 * 60) # 7:00
config.plugins.xmltvimport.showinplugins = ConfigYesNo(default = False)
config.plugins.xmltvimport.showinextensions = ConfigYesNo(default = False)
config.plugins.xmltvimport.deepstandby = ConfigSelection(default = "skip", choices = [
		("wakeup", _("Wake up and import")),
#		("later", _("Import on next boot")),
		("skip", _("Skip the import")) 
		])
config.plugins.xmltvimport.longDescDays = ConfigNumber(default = 5)
config.plugins.xmltvimport.sources = ConfigText("", False)

# Plugin
import XMLTVImport
import XMLTVConfig

# Plugin definition
from Plugins.Plugin import PluginDescriptor

# historically located (not a problem, we want to update it)
CONFIG_PATH = '/etc/xmltvimport'

# Global variable
autoStartTimer = None
_session = None

# Filter servicerefs that this box can display by starting a fake recording.
def channelFilter(ref):
	fakeRecService = NavigationInstance.instance.recordService(enigma.eServiceReference(ref), True)
	if fakeRecService:
		fakeRecResult = fakeRecService.start(True)
		NavigationInstance.instance.stopRecordService(fakeRecService)
		# -7 (errNoSourceFound) occurs when tuner is disconnected. 
		r = fakeRecResult in (0, -7)
		#if not r:
		#	print>>log, "Rejected (%d): %s" % (fakeRecResult, ref) 			
		return r
	print>>log, "Invalid serviceref string:", ref
	return False

xmltvimport = XMLTVImport.XMLTVImport(enigma.eEPGCache.getInstance(), channelFilter)

lastImportResult = None

##################################
# Configuration GUI

class EPGMainSetup(ConfigListScreen,Screen):
	skin = """
<screen position="center,center" size="560,400" >
	<ePixmap name="red"    position="0,0"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
	<ePixmap name="green"  position="140,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
	<ePixmap name="yellow" position="280,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/yellow.png" transparent="1" alphatest="on" /> 
	<ePixmap name="blue"   position="420,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/blue.png" transparent="1" alphatest="on" /> 

	<widget name="key_red" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" /> 
	<widget name="key_green" position="140,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" /> 
	<widget name="key_yellow" position="280,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
	<widget name="key_blue" position="420,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />

	<widget name="config" position="10,40" size="540,240" scrollbarMode="showOnDemand" />

	<ePixmap alphatest="on" pixmap="skin_default/icons/clock.png" position="480,383" size="14,14" zPosition="3"/>
	<widget font="Regular;18" halign="left" position="505,380" render="Label" size="55,20" source="global.CurrentTime" transparent="1" valign="center" zPosition="3">
		<convert type="ClockToText">Default</convert>
	</widget>
	<widget name="statusbar" position="10,380" size="470,20" font="Regular;18" />
	<widget name="status" position="10,300" size="540,60" font="Regular;20" />
</screen>"""
		
	def __init__(self, session, args = 0):
		self.session = session
		Screen.__init__(self, session)
		self.setup_title = _("XMLTV Import Configuration")
		Screen.setTitle(self, self.setup_title)
		cfg = config.plugins.xmltvimport
		self.list = [
			getConfigListEntry(_("Daily automatic import"), cfg.enabled),
			getConfigListEntry(_("Automatic start time"), cfg.wakeup),   
			getConfigListEntry(_("Standby at startup"), cfg.wakeupsleep),
			getConfigListEntry(_("When in deep standby"), cfg.deepstandby),
			getConfigListEntry(_("Show in plugin browser"), cfg.showinplugins),
			getConfigListEntry(_("Show in extensions"), cfg.showinextensions),
			getConfigListEntry(_("Start import after booting up"), cfg.runboot),
			getConfigListEntry(_("Load long descriptions up to X days"), cfg.longDescDays)
			]
		ConfigListScreen.__init__(self, self.list, session = self.session, on_change = self.changedEntry)
		self["status"] = Label()
		self["statusbar"] = Label()
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Ok"))
		self["key_yellow"] = Button(_("Manual"))
		self["key_blue"] = Button(_("Sources"))
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions", "TimerEditActions", "MenuActions"],
		{
			"red": self.cancel,
			"green": self.save,
			"yellow": self.doimport,
			"blue": self.dosources,
			"save": self.save,
			"cancel": self.cancel,
			"ok": self.save,
			"log": self.showLog,
			"menu": self.cancel,
		}, -2)
		self.lastImportResult = None
		self.onChangedEntry = []
		self.updateTimer = enigma.eTimer()
		self.updateTimer.callback.append(self.updateStatus)
		self.updateTimer.start(2000)
		self.updateStatus()
	
	# for summary:
	def changedEntry(self):
		for x in self.onChangedEntry:
			x()
	def getCurrentEntry(self):
		return self["config"].getCurrent()[0]
	def getCurrentValue(self):
		return str(self["config"].getCurrent()[1].getText())
	def createSummary(self):
		from Screens.Setup import SetupSummary
		return SetupSummary

	def saveAll(self):
		for x in self["config"].list:
			x[1].save()
		configfile.save()

	def save(self):
		#print "saving"
		self.updateTimer.stop()
		self.saveAll()
		if not config.plugins.xmltvimport.showinplugins.value:
			for plugin in plugins.getPlugins(PluginDescriptor.WHERE_PLUGINMENU):
				if plugin.name == _("XMLTV-Importer"):
					plugins.removePlugin(plugin)

		if not config.plugins.xmltvimport.showinextensions.value:
			for plugin in plugins.getPlugins(PluginDescriptor.WHERE_EXTENSIONSMENU):
				if plugin.name == _("XMLTV-Importer"):
					plugins.removePlugin(plugin)
				
		plugins.readPluginList(resolveFilename(SCOPE_PLUGINS))
		self.close(True,self.session)

	def cancel(self):
		#print "cancel"
		self.updateTimer.stop()
		for x in self["config"].list:
			x[1].cancel()
		self.close(False,self.session)
		
	def updateStatus(self):
		text = ""
		if xmltvimport.isImportRunning():
			text = _("Importing:")
			src = xmltvimport.source
			text += " %s\n%s events" % (src.description, xmltvimport.eventCount)
		self["status"].setText(text)
		if lastImportResult and (lastImportResult != self.lastImportResult):
			start, count = lastImportResult
			try:
				d, t = FuzzyTime(start, inPast=True)
			except:
				# Not all images have inPast
				d, t = FuzzyTime(start)
			self["statusbar"].setText(_("Last: %s %s, %d events") % (d,t,count))
			self.lastImportResult = lastImportResult 

	def doimport(self):
		if xmltvimport.isImportRunning():
			print>>log, "[XMLTVImport] Already running, won't start again"
			self.session.open(MessageBox, _("XMLTVImport Plugin\nImport of epg data is still in progress. Please wait."), MessageBox.TYPE_ERROR, timeout = 10, close_on_any_key = True)
			return
		cfg = config.plugins.xmltvimport.sources.getValue().split("|")
		sources = [ s for s in XMLTVConfig.enumSources(CONFIG_PATH, filter = cfg) ]
		if not sources:
			self.session.open(MessageBox, _("No active EPG sources found, nothing to do"), MessageBox.TYPE_INFO, timeout = 10, close_on_any_key = True)
			return
		# make it a stack, first on top.
		sources.reverse()
		xmltvimport.sources = sources
		self.session.openWithCallback(self.do_import_callback, MessageBox, _("XMLTVImport Plugin\nImport of epg data will start\nThis may take a few minutes\nIs this ok?"), MessageBox.TYPE_YESNO, timeout = 15, default = True)

	def do_import_callback(self, confirmed):
		if not confirmed:
			return
		try:
			xmltvimport.onDone = doneImport
			xmltvimport.beginImport(longDescUntil = config.plugins.xmltvimport.longDescDays.value * 24 * 3600 + time.time())
		except Exception, e:
			print>>log, "[XMLTVImport] Error at start:", e 
			self.session.open(MessageBox, _("XMLTVImport Plugin\nFailed to start:\n") + str(e), MessageBox.TYPE_ERROR, timeout = 15, close_on_any_key = True)
		self.updateStatus()

	def dosources(self):
		self.session.openWithCallback(self.sourcesDone, XMLTVImportSources)

	def sourcesDone(self, confirmed, sources):
		# Called with True and list of config items on Okay.
		print>>log, "sourcesDone(): ", confirmed, sources
		pass
		import glob
		for filename in glob.glob('/tmp/*.xml'):
			os.remove(filename) 

	def showLog(self):
		self.session.open(XMLTVImportLog)

class XMLTVImportSources(Screen):
	"Pick sources from config"
	skin = """
		<screen position="center,center" size="560,400" >
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
			
			<widget name="list" position="10,40" size="540,340" scrollbarMode="showOnDemand" />
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self.setup_title = _("XMLTV Import Sources")
		Screen.setTitle(self, self.setup_title)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Ok"))
		self["key_yellow"] = Button() # _("Import now"))
		self["key_blue"] = Button()
		self.onChangedEntry = []
		filter = config.plugins.xmltvimport.sources.getValue().split("|")
		sources = [
			# (description, value, index, selected)
			SelectionEntryComponent(x.description, x.description, 0, (filter is None) or (x.description in filter))
			for x in XMLTVConfig.enumSources(CONFIG_PATH, filter=None)
			]
		self["list"] = SelectionList(sources)
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions", "MenuActions"],
		{
			"red": self.cancel,
			"green": self.save,
			"yellow": self.doimport,
			"save": self.save,
			"cancel": self.cancel,
			"ok": self["list"].toggleSelection,
			"menu": self.cancel,
		}, -2)

	# for summary:
	def changedEntry(self):
		for x in self.onChangedEntry:
			x()
	def getCurrentEntry(self):
		return str(self["list"].getCurrent()[0][1])
	def getCurrentValue(self):
		return str(self["list"].getCurrent()[0][3])
	def createSummary(self):
		return SetupSummary

	def save(self):
		sources = [ item[0][1] for item in self["list"].list if item[0][3] ]
		print>>log, "[XMLTVImport] Selected sources:", sources
		config_string = ""
		for source in sources:
			if len(config_string) > 0:
				config_string += "|"
			config_string += source
		config.plugins.xmltvimport.sources.setValue(config_string)
		config.plugins.xmltvimport.sources.save()
		configfile.save()
		self.close(True, sources)

	def cancel(self):
		self.close(False, None)

	def doimport(self):
		pass

class XMLTVImportLog(Screen):
	skin = """
		<screen position="center,center" size="560,400" >
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
			<widget name="list" position="10,40" size="540,340" />
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		Screen.setTitle(self, _("XMLTV Import Log"))
		self["key_red"] = Button(_("Clear"))
		self["key_green"] = Button()
		self["key_yellow"] = Button()
		self["key_blue"] = Button(_("Save"))
		self["list"] = ScrollLabel(log.getvalue())
		self["actions"] = ActionMap(["DirectionActions", "OkCancelActions", "ColorActions", "MenuActions"],
		{
			"red": self.clear,
			"green": self.cancel,
			"yellow": self.cancel,
			"save": self.save,
			"blue": self.save,
			"cancel": self.cancel,
			"ok": self.cancel,
			"left": self["list"].pageUp,
			"right": self["list"].pageDown,
			"up": self["list"].pageUp,
			"down": self["list"].pageDown,
			"pageUp": self["list"].pageUp,
			"pageDown": self["list"].pageDown,
			"menu": self.cancel,
		}, -2)

	def save(self):
		try:
			f = open('/tmp/xmltvimport.log', 'w')
			f.write(log.getvalue())
			f.close()
		except Exception, e:
			self["list"].setText("Failed to write /tmp/xmltvimport.log:str" + str(e))
		self.close(True)

	def cancel(self):
		self.close(False)

	def clear(self):
		log.logfile.reset()
		log.logfile.truncate()
		self.close(False)

def main(session, **kwargs):
    session.openWithCallback(doneConfiguring, EPGMainSetup)

def doneConfiguring(session, retval):
	"user has closed configuration, check new values...."
	if autoStartTimer is not None:
		autoStartTimer.update()

def doneImport(reboot=False, epgfile=None):
	global _session, lastImportResult
	lastImportResult = (time.time(), xmltvimport.eventCount)
	if reboot:
		msg = _("XMLTV Import finished, %d events") % xmltvimport.eventCount + "\n" + _("You must restart Enigma2 to load the EPG data,\nis this OK?")
		_session.openWithCallback(restartEnigma, MessageBox, msg, MessageBox.TYPE_YESNO, timeout = 15, default = True)

      
def restartEnigma(confirmed):
	if not confirmed:
		return
		# save state of enigma, so we can return to previeus state
		if Screens.Standby.inStandby:
			try:
				open('/tmp/enigmastandby', 'wb').close()
			except:
				print>>log, "Failed to create /tmp/enigmastandby"
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
		if config.plugins.xmltvimport.enabled.value:
			clock = config.plugins.xmltvimport.wakeup.value
			nowt = time.time()
			now = time.localtime(nowt)
			return int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday,  
				clock[0], clock[1], 0, 0, now.tm_yday, now.tm_isdst)))
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
		print>>log, "[XMLTVImport] WakeUpTime now set to", wake, "(now=%s)" % now
		return wake

	def runImport(self):
		cfg = config.plugins.xmltvimport.sources.getValue().split("|")
		sources = [ s for s in XMLTVConfig.enumSources(CONFIG_PATH, filter = cfg) ]
		if sources:
			sources.reverse()
			xmltvimport.sources = sources
			xmltvimport.onDone = doneImport
			xmltvimport.beginImport(longDescUntil = config.plugins.xmltvimport.longDescDays.value * 24 * 3600 + time.time())

	def onTimer(self):
		self.timer.stop()
		now = int(time.time())
		print>>log, "[XMLTVImport] onTimer occured at", now
		wake = self.getWakeTime()
		# If we're close enough, we're okay...
		atLeast = 0
		if wake - now < 60:
			self.runImport() 
			atLeast = 60
		self.update(atLeast)

def onBootStartCheck():
	global autoStartTimer
	print>>log, "[XMLTVImport] onBootStartCheck"
	now = int(time.time())
	wake = autoStartTimer.update()
	print>>log, "[XMLTVImport] now=%d wake=%d wake-now=%d" % (now, wake, wake-now)
	if (wake < 0) or (wake - now > 600):
		print>>log, "[XMLTVImport] starting import because auto-run on boot is enabled"
		autoStartTimer.runImport()
	else:
		print>>log, "[XMLTVImport] import to start in less than 10 minutes anyway, skipping..."

def autostart(reason, session=None, **kwargs):
	"called with reason=1 to during shutdown, with reason=0 at startup?"
	global autoStartTimer
	global _session
	print>>log, "[XMLTVImport] autostart (%s) occured at" % reason, time.time()
	if reason == 0:
		if session is not None:
			_session = session
			if autoStartTimer is None:
				autoStartTimer = AutoStartTimer(session)
			if config.plugins.xmltvimport.runboot.value:
				# timer isn't reliable here, damn
				onBootStartCheck()
		# If WE caused the reboot, put the box back in standby.
		if os.path.exists("/tmp/enigmastandby"):
			print>>log, "[XMLTVImport] Returning to standby"
			from Tools import Notifications
			Notifications.AddNotification(Screens.Standby.Standby)
			try:
				os.remove("/tmp/enigmastandby")
			except:
				pass
		else:
			if config.plugins.xmltvimport.deepstandby.value == 'wakeup':
				if config.plugins.xmltvimport.wakeupsleep.value:
					print>>log, "[XMLTVImport] Returning to standby"
					from Tools import Notifications
					Notifications.AddNotification(Screens.Standby.Standby)
	else:
		print>>log, "[XMLTVImport] Stop"
		#if autoStartTimer:
		#	autoStartTimer.stop()        

def getNextWakeup():
	"returns timestamp of next time when autostart should be called"
	if autoStartTimer:
		if config.plugins.xmltvimport.deepstandby.value == 'wakeup':
			print>>log, "[XMLTVImport] Will wake up from deep sleep"
			return autoStartTimer.update()
	return -1

# we need this helper function to identify the descriptor
def extensionsmenu(session, **kwargs):
	main(session, **kwargs)

def housekeepingExtensionsmenu(el):
	try:
		if el.value:
			Components.PluginComponent.plugins.addPlugin(extDescriptor)
		else:
			Components.PluginComponent.plugins.removePlugin(extDescriptor)
	except Exception, e:
		print "[XMLTVImport] Failed to update extensions menu:", e

description = _("Automated XMLTV Importer")
config.plugins.xmltvimport.showinextensions.addNotifier(housekeepingExtensionsmenu, initial_call = False, immediate_feedback = False)
extDescriptor = PluginDescriptor(name=_("XMLTV-Importer"), description = description, where = PluginDescriptor.WHERE_EXTENSIONSMENU, fnc = extensionsmenu)
pluginlist = PluginDescriptor(name=_("XMLTV-Importer"), description = description, where = PluginDescriptor.WHERE_PLUGINMENU, icon = 'plugin.png', fnc = main)


def epgmenu(menuid, **kwargs):
	if getImageDistro() in ("openvix", "openvixhd", "ventonsupport", "egami"):
		if menuid == "epg":
			return [(_("XMLTV-Importer"), main, "xmltvimporter", 1002)]
		else:
			return []
	else:
		if menuid == "setup":
			return [(_("XMLTV-Importer"), main, "xmltvimporter", 1002)]
		else:
			return []

def Plugins(**kwargs):
	result = [
		PluginDescriptor(
			name=_("XMLTV-Importer"),
			description = description,
			where = [
				PluginDescriptor.WHERE_AUTOSTART,
				PluginDescriptor.WHERE_SESSIONSTART
			],
			fnc = autostart,
			wakeupfnc = getNextWakeup
		),
		PluginDescriptor(
			name=_("XMLTV-Importer"),
			description = description,
			where = PluginDescriptor.WHERE_MENU,
			fnc = epgmenu
		),
	]
	if config.plugins.xmltvimport.showinextensions.value:
		result.append(extDescriptor)
	if config.plugins.xmltvimport.showinplugins.value:
		result.append(pluginlist)
	return result

class SetupSummary(Screen):
	def __init__(self, session, parent):
		Screen.__init__(self, session, parent = parent)
		self["SetupTitle"] = StaticText(_(parent.setup_title))
		self["SetupEntry"] = StaticText("")
		self["SetupValue"] = StaticText("")
		self.onShow.append(self.addWatcher)
		self.onHide.append(self.removeWatcher)

	def addWatcher(self):
		self.parent.onChangedEntry.append(self.selectionChanged)
		self.parent["list"].onSelectionChanged.append(self.selectionChanged)
		self.selectionChanged()

	def removeWatcher(self):
		self.parent.onChangedEntry.remove(self.selectionChanged)
		self.parent["list"].onSelectionChanged.remove(self.selectionChanged)

	def selectionChanged(self):
		self["SetupEntry"].text = self.parent.getCurrentEntry()
		self["SetupValue"].text = self.parent.getCurrentValue()

