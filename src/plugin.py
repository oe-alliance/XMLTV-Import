# for localized messages
from . import _
import time
import os
import enigma
import log

# Config
from Components.config import config, configfile, ConfigEnableDisable, ConfigSubsection, ConfigYesNo, ConfigClock, getConfigListEntry, ConfigText, ConfigSelection, ConfigNumber, ConfigSubDict, NoSave
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
from Tools import Notifications
from Tools.FuzzyDate import FuzzyTime
from Tools.Directories import fileExists
try:
	from Tools.StbHardware import getFPWasTimerWakeup
except:
	from Tools.DreamboxHardware import getFPWasTimerWakeup
import NavigationInstance

def lastMACbyte():
	try:
		return int(open('/sys/class/net/eth0/address').readline().strip()[-2:], 16)
	except:
		return 256

def calcDefaultStarttime():
	try:
		# Use the last MAC byte as time offset (half-minute intervals)
		offset = lastMACbyte() * 30
	except:
		offset = 7680
	return (5 * 60 * 60) + offset

from boxbranding import getImageDistro
#Set default configuration
config.plugins.xmltvimport = ConfigSubsection()
config.plugins.xmltvimport.enabled = ConfigEnableDisable(default = True)
config.plugins.xmltvimport.runboot = ConfigSelection(default = "4", choices = [
		("1", _("always")),
		("2", _("only manual boot")),
		("3", _("only automatic boot")),
		("4", _("never"))
		])
config.plugins.xmltvimport.runboot_restart = ConfigYesNo(default = False)
config.plugins.xmltvimport.runboot_day = ConfigYesNo(default = False)
config.plugins.xmltvimport.wakeupsleep = ConfigEnableDisable(default = False)
config.plugins.xmltvimport.wakeup = ConfigClock(default = calcDefaultStarttime())
config.plugins.xmltvimport.showinplugins = ConfigYesNo(default = False)
config.plugins.xmltvimport.showinextensions = ConfigYesNo(default = True)
config.plugins.xmltvimport.deepstandby = ConfigSelection(default = "skip", choices = [
		("wakeup", _("wake up and import")),
		("skip", _("skip the import"))
		])
config.plugins.xmltvimport.standby_afterwakeup = ConfigYesNo(default = False)
config.plugins.xmltvimport.shutdown = ConfigYesNo(default = False)
config.plugins.xmltvimport.longDescDays = ConfigNumber(default = 5)
config.plugins.xmltvimport.showinmainmenu = ConfigYesNo(default = False)
config.plugins.xmltvimport.deepstandby_afterimport = NoSave(ConfigYesNo(default = False))
config.plugins.xmltvimport.parse_autotimer = ConfigYesNo(default = False)
config.plugins.xmltvimport.import_onlybouquet = ConfigYesNo(default = False)
config.plugins.xmltvimport.clear_oldepg = ConfigYesNo(default = False)
config.plugins.xmltvimport.day_profile = ConfigSelection(choices = [("1", _("Press OK"))], default = "1")
config.plugins.extra_xmltvimport = ConfigSubsection()
config.plugins.extra_xmltvimport.last_import = ConfigText(default = "none")
config.plugins.extra_xmltvimport.day_import = ConfigSubDict()
for i in range(7):
	config.plugins.extra_xmltvimport.day_import[i] = ConfigEnableDisable(default = True)

weekdays = [
	_("Monday"),
	_("Tuesday"),
	_("Wednesday"),
	_("Thursday"),
	_("Friday"),
	_("Saturday"),
	_("Sunday"),
	]

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
parse_autotimer = False
BouquetChannelListList = None

def getAlternatives(service):
	if not service:
		return None
	alternativeServices = enigma.eServiceCenter.getInstance().list(service)
	return alternativeServices and alternativeServices.getContent("S", True)

def getBouquetChannelList():
	channels = [ ]
	serviceHandler = enigma.eServiceCenter.getInstance()
	mask = (enigma.eServiceReference.isMarker | enigma.eServiceReference.isDirectory)
	altrernative = enigma.eServiceReference.isGroup
	if config.usage.multibouquet.value:
		bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "bouquets.tv" ORDER BY bouquet'
		bouquet_root = enigma.eServiceReference(bouquet_rootstr)
		list = serviceHandler.list(bouquet_root)
		if list:
			while True:
				s = list.getNext()
				if not s.valid():
					break
				if s.flags & enigma.eServiceReference.isDirectory:
					info = serviceHandler.info(s)
					if info:
						clist = serviceHandler.list(s)
						if clist:
							while True:
								service = clist.getNext()
								if not service.valid(): break
								if not (service.flags & mask):
									if service.flags & altrernative:
										altrernative_list = getAlternatives(service)
										if altrernative_list:
											for channel in altrernative_list:
												refstr = ':'.join(channel.split(':')[:11])
												if refstr not in channels:
													channels.append(refstr)
									else:
										refstr = ':'.join(service.toString().split(':')[:11])
										if refstr not in channels:
											channels.append(refstr)
	else:
		bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.favourites.tv" ORDER BY bouquet'
		bouquet_root = enigma.eServiceReference(bouquet_rootstr)
		services = serviceHandler.list(bouquet_root)
		if not services is None:
			while True:
				service = services.getNext()
				if not service.valid(): break
				if not (service.flags & mask):
					if service.flags & altrernative:
						altrernative_list = getAlternatives(service)
						if altrernative_list:
							for channel in altrernative_list:
								refstr = ':'.join(channel.split(':')[:11])
								if refstr not in channels:
									channels.append(refstr)
					else:
						refstr = ':'.join(service.toString().split(':')[:11])
						if refstr not in channels:
							channels.append(refstr)
	return channels

# Filter servicerefs that this box can display by starting a fake recording.
def channelFilter(ref):
	if not ref:
		return False
	sref = enigma.eServiceReference(ref)
	if config.plugins.xmltvimport.import_onlybouquet.value:
		global BouquetChannelListList
		if BouquetChannelListList is None:
			BouquetChannelListList = getBouquetChannelList()
		refstr = ':'.join(sref.toString().split(':')[:11])
		if refstr not in BouquetChannelListList:
			print>>log, "Serviceref not in bouquets:", refstr
			return False
	fakeRecService = NavigationInstance.instance.recordService(sref, True)
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

def startImport():
	XMLTVImport.HDD_EPG_DAT = config.misc.epgcache_filename.value
	if config.plugins.xmltvimport.clear_oldepg.value and hasattr(xmltvimport.epgcache, 'flushEPG'):
		XMLTVImport.unlink_if_exists(XMLTVImport.HDD_EPG_DAT)
		XMLTVImport.unlink_if_exists(XMLTVImport.HDD_EPG_DAT + '.backup')
		xmltvimport.epgcache.flushEPG()
	xmltvimport.onDone = doneImport
	xmltvimport.beginImport(longDescUntil = config.plugins.xmltvimport.longDescDays.value * 24 * 3600 + time.time())


##################################
# Configuration GUI
HD = False
try:
	if enigma.getDesktop(0).size().width() >= 1280:
		HD = True
except:
	pass
class XMLTVImportConfig(ConfigListScreen,Screen):
	if HD:
		skin = """
			<screen position="center,center" size="600,500" title="XMLTV Import Configuration" >
				<ePixmap name="red"    position="0,0"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
				<ePixmap name="green"  position="140,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
				<ePixmap name="yellow" position="280,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/yellow.png" transparent="1" alphatest="on" />
				<ePixmap name="blue"   position="420,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/blue.png" transparent="1" alphatest="on" />
				<ePixmap position="562,0" size="35,25"  pixmap="skin_default/buttons/key_info.png" alphatest="on" />
				<ePixmap position="562,30" size="35,25" pixmap="skin_default/buttons/key_menu.png" alphatest="on" />
				<widget name="key_red" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;19" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
				<widget name="key_green" position="140,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;19" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
				<widget name="key_yellow" position="280,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;19" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
				<widget name="key_blue" position="420,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;19" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
				<widget name="config" position="10,70" size="590,320" scrollbarMode="showOnDemand" />
				<ePixmap alphatest="on" pixmap="skin_default/icons/clock.png" position="520,483" size="14,14" zPosition="3"/>
				<widget font="Regular;18" halign="left" position="545,480" render="Label" size="55,20" source="global.CurrentTime" transparent="1" valign="center" zPosition="3">
					<convert type="ClockToText">Default</convert>
				</widget>
				<widget name="statusbar" position="10,480" size="500,20" font="Regular;18" />
				<widget name="status" position="10,400" size="580,60" font="Regular;20" />
			</screen>"""
	else:
		skin = """
			<screen position="center,center" size="600,430" title="XMLTV Import Configuration" >
				<ePixmap name="red"    position="0,0"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
				<ePixmap name="green"  position="140,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
				<ePixmap name="yellow" position="280,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/yellow.png" transparent="1" alphatest="on" />
				<ePixmap name="blue"   position="420,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/blue.png" transparent="1" alphatest="on" />
				<ePixmap position="562,0" size="35,25" pixmap="skin_default/buttons/key_info.png" alphatest="on" />
				<ePixmap position="562,30" size="35,25" pixmap="skin_default/buttons/key_menu.png" alphatest="on" />
				<widget name="key_red" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
				<widget name="key_green" position="140,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
				<widget name="key_yellow" position="280,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
				<widget name="key_blue" position="420,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;20" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
				<widget name="config" position="10,60" size="590,250" scrollbarMode="showOnDemand" />
				<ePixmap alphatest="on" pixmap="skin_default/icons/clock.png" position="520,403" size="14,14" zPosition="3"/>
				<widget font="Regular;18" halign="left" position="545,400" render="Label" size="55,20" source="global.CurrentTime" transparent="1" valign="center" zPosition="3">
					<convert type="ClockToText">Default</convert>
				</widget>
				<widget name="statusbar" position="10,410" size="500,20" font="Regular;18" />
				<widget name="status" position="10,330" size="580,60" font="Regular;20" />
			</screen>"""
	def __init__(self, session, args = 0):
		self.session = session
		self.skin = XMLTVImportConfig.skin
		self.setup_title = _("XMLTV Import Configuration")
		Screen.__init__(self, session)
		self["status"] = Label()
		self["statusbar"] = Label()
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))
		self["key_yellow"] = Button(_("Manual"))
		self["key_blue"] = Button(_("Sources"))
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions", "TimerEditActions", "MovieSelectionActions"],
		{
			"red": self.keyRed,
			"green": self.keyGreen,
			"yellow": self.doimport,
			"blue": self.dosources,
			"cancel": self.keyRed,
			"ok": self.keyOk,
			"log": self.keyInfo,
			"contextMenu": self.showLog,
		}, -1)
		ConfigListScreen.__init__(self, [], session = self.session)
		self.lastImportResult = None
		self.onChangedEntry = []
		self.prev_onlybouquet = config.plugins.xmltvimport.import_onlybouquet.value
		self.initConfig()
		self.createSetup()
		self.importStatusTemplate = _("Importing: %s\n%s events")
		self.updateTimer = enigma.eTimer()
		self.updateTimer.callback.append(self.updateStatus)
		self.updateTimer.start(2000)
		self.updateStatus()
		self.onLayoutFinish.append(self.__layoutFinished)

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

	def __layoutFinished(self):
		self.setTitle(self.setup_title)

	def initConfig(self):
		def getPrevValues(section):
			res = { }
			for (key,val) in section.content.items.items():
				if isinstance(val, ConfigSubsection):
					res[key] = getPrevValues(val)
				else:
					res[key] = val.value
			return res
		self.EPG = config.plugins.xmltvimport
		self.prev_values = getPrevValues(self.EPG)
		self.cfg_enabled = getConfigListEntry(_("Automatic import EPG"), self.EPG.enabled)
		self.cfg_wakeup = getConfigListEntry(_("Automatic start time"), self.EPG.wakeup)
		self.cfg_deepstandby = getConfigListEntry(_("When in deep standby"), self.EPG.deepstandby)
		self.cfg_shutdown = getConfigListEntry(_("Return to deep standby after import"), self.EPG.shutdown)
		self.cfg_standby_afterwakeup = getConfigListEntry(_("Standby at startup"), self.EPG.standby_afterwakeup)
		self.cfg_day_profile = getConfigListEntry(_("Choice days for start import"), self.EPG.day_profile)
		self.cfg_runboot = getConfigListEntry(_("Start import after booting up"), self.EPG.runboot)
		self.cfg_import_onlybouquet = getConfigListEntry(_("Load EPG only services in bouquets"), self.EPG.import_onlybouquet)
		self.cfg_runboot_day = getConfigListEntry(_("Consider setting \"Days Profile\""), self.EPG.runboot_day)
		self.cfg_runboot_restart = getConfigListEntry(_("Skip import on restart GUI"), self.EPG.runboot_restart)
		self.cfg_showinextensions = getConfigListEntry(_("Show \"XMLTVImport\" in extensions"), self.EPG.showinextensions)
		self.cfg_showinmainmenu = getConfigListEntry(_("Show \"XMLTV Importer\" in main menu"), self.EPG.showinmainmenu)
		self.cfg_longDescDays = getConfigListEntry(_("Load long descriptions up to X days"), self.EPG.longDescDays)
		self.cfg_parse_autotimer = getConfigListEntry(_("Run AutoTimer after import"), self.EPG.parse_autotimer)
		self.cfg_clear_oldepg = getConfigListEntry(_("Clearing current EPG before import"), config.plugins.xmltvimport.clear_oldepg)

	def createSetup(self):
		list = [ self.cfg_enabled ]
		if self.EPG.enabled.value:
			list.append(self.cfg_wakeup)
			list.append(self.cfg_deepstandby)
			if self.EPG.deepstandby.value == "wakeup":
				list.append(self.cfg_shutdown)
				if not self.EPG.shutdown.value:
					list.append(self.cfg_standby_afterwakeup)
		list.append(self.cfg_day_profile)
		list.append(self.cfg_runboot)
		if self.EPG.runboot.value != "4":
			list.append(self.cfg_runboot_day)
			if self.EPG.runboot.value == "1" or self.EPG.runboot.value == "2":
				list.append(self.cfg_runboot_restart)
		list.append(self.cfg_showinextensions)
		list.append(self.cfg_showinmainmenu)
		list.append(self.cfg_import_onlybouquet)
		if hasattr(enigma.eEPGCache, 'flushEPG'):
			list.append(self.cfg_clear_oldepg)
		list.append(self.cfg_longDescDays)
		if fileExists("/usr/lib/enigma2/python/Plugins/Extensions/AutoTimer/plugin.py"):
			try:
				from Plugins.Extensions.AutoTimer.AutoTimer import AutoTimer
				list.append(self.cfg_parse_autotimer)
			except:
				print>>log, "[XMLTVImport] AutoTimer Plugin not installed"
		self["config"].list = list
		self["config"].l.setList(list)

	def newConfig(self):
		cur = self["config"].getCurrent()
		if cur in (self.cfg_enabled, self.cfg_shutdown, self.cfg_deepstandby, self.cfg_runboot):
			self.createSetup()

	def keyRed(self):
		def setPrevValues(section, values):
			for (key,val) in section.content.items.items():
				value = values.get(key, None)
				if value is not None:
					if isinstance(val, ConfigSubsection):
						setPrevValues(val, value)
					else:
						val.value = value
		setPrevValues(self.EPG, self.prev_values)
		self.keyGreen()

	def keyGreen(self):
		self.updateTimer.stop()
		if not fileExists("/usr/lib/enigma2/python/Plugins/Extensions/AutoTimer/plugin.py") and self.EPG.parse_autotimer.value:
			self.EPG.parse_autotimer.value = False
		if self.EPG.shutdown.value:
			self.EPG.standby_afterwakeup.value = False
		self.EPG.save()
		if self.prev_onlybouquet != config.plugins.xmltvimport.import_onlybouquet.value or (autoStartTimer is not None and autoStartTimer.prev_multibouquet != config.usage.multibouquet.value):
			XMLTVConfig.channelCache = {}
		self.close(True,self.session)

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.newConfig()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.newConfig()

	def keyOk(self):
		ConfigListScreen.keyOK(self)
		sel = self["config"].getCurrent()[1]
		if sel and sel == self.EPG.day_profile:
			self.session.open(XMLTVImportProfile)

	def updateStatus(self):
		text = ""
		if xmltvimport.isImportRunning():
			src = xmltvimport.source
			text = self.importStatusTemplate % (src.description, xmltvimport.eventCount)
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

	def keyInfo(self):
		last_import = config.plugins.extra_xmltvimport.last_import.value
		self.session.open(MessageBox,_("Last import: %s events") % (last_import),type=MessageBox.TYPE_INFO)

	def doimport(self, one_source=None):
		if xmltvimport.isImportRunning():
			print>>log, "[XMLTVImport] Already running, won't start again"
			self.session.open(MessageBox, _("XMLTVImport\nImport of epg data is still in progress. Please wait."), MessageBox.TYPE_ERROR, timeout = 10, close_on_any_key = True)
			return
		if self.prev_onlybouquet != config.plugins.xmltvimport.import_onlybouquet.value or (autoStartTimer is not None and autoStartTimer.prev_multibouquet != config.usage.multibouquet.value):
			XMLTVConfig.channelCache = {}
		if one_source is None:
			cfg = XMLTVConfig.loadUserSettings()
		else:
			cfg = one_source
		sources = [ s for s in XMLTVConfig.enumSources(CONFIG_PATH, filter = cfg["sources"]) ]
		if not sources:
			self.session.open(MessageBox, _("No active EPG sources found, nothing to do"), MessageBox.TYPE_INFO, timeout = 10, close_on_any_key = True)
			return
		# make it a stack, first on top.
		sources.reverse()
		xmltvimport.sources = sources
		self.session.openWithCallback(self.do_import_callback, MessageBox, _("XMLTVImport\nImport of epg data will start.\nThis may take a few minutes.\nIs this ok?"), MessageBox.TYPE_YESNO, timeout = 15, default = True)

	def do_import_callback(self, confirmed):
		if not confirmed:
			return
		try:
			startImport()
		except Exception, e:
			print>>log, "[XMLTVImport] Error at start:", e
			self.session.open(MessageBox, _("XMLTVImport Plugin\nFailed to start:\n") + str(e), MessageBox.TYPE_ERROR, timeout = 15, close_on_any_key = True)
		self.updateStatus()

	def dosources(self):
		self.session.openWithCallback(self.sourcesDone, XMLTVImportSources)

	def sourcesDone(self, confirmed, sources, cfg):
		# Called with True and list of config items on Okay.
		print>>log, "sourcesDone(): ", confirmed, sources
		if cfg is not None:
			self.doimport(one_source=cfg)

	def showLog(self):
		self.session.open(XMLTVImportLog)

class XMLTVImportSources(Screen):
	"Pick sources from config"
	skin = """
		<screen name="XMLTVImportSources" position="center,center" size="560,400" title="XMLTV Import Sources" >
			<ePixmap name="red"    position="0,0"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
			<ePixmap name="green"  position="140,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
			<ePixmap name="yellow" position="280,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/yellow.png" transparent="1" alphatest="on" />
			<ePixmap name="blue"   position="420,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/blue.png" transparent="1" alphatest="on" />
			<widget name="key_red" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget name="key_green" position="140,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget name="key_yellow" position="280,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget name="key_blue" position="420,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<ePixmap alphatest="on" pixmap="skin_default/icons/clock.png" position="480,383" size="14,14" zPosition="3"/>
			<widget font="Regular;18" halign="left" position="505,380" render="Label" size="55,20" source="global.CurrentTime" transparent="1" valign="center" zPosition="3">
				<convert type="ClockToText">Default</convert>
			</widget>
			<widget name="list" position="10,40" size="540,336" scrollbarMode="showOnDemand" />
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))
		self["key_blue"] = Button()
		cfg = XMLTVConfig.loadUserSettings()
		filter = cfg["sources"]
		sources = [
			# (description, value, index, selected)
			SelectionEntryComponent(x.description, x.description, 0, (filter is None) or (x.description in filter))
			for x in XMLTVConfig.enumSources(CONFIG_PATH, filter=None)
			]
		self["list"] = SelectionList(sources, enableWrapAround=True)
		list = self["list"].list
		if list and len(list) > 0:
			self["key_yellow"] = Button(_("Import current source"))
		else:
			self["key_yellow"] = Button()
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"],
		{
			"red": self.cancel,
			"green": self.save,
			"yellow": self.do_import,
			"save": self.save,
			"cancel": self.cancel,
			"ok": self["list"].toggleSelection,
		}, -2)
		self.setTitle(_("XMLTV Import Sources"))

	def save(self):
		sources = [ item[0][1] for item in self["list"].list if item[0][3] ]
		print>>log, "[XMLTVImport] Selected sources:", sources
		XMLTVConfig.storeUserSettings(sources=sources)
		self.close(True, sources, None)

	def cancel(self):
		self.close(False, None, None)

	def do_import(self):
		list = self["list"].list
		if list and len(list) > 0:
			try:
				idx = self["list"].getSelectedIndex()
				item = self["list"].list[idx][0]
				source = [ item[1] or "" ]
				cfg = {"sources": source}
				print>>log, "[XMLTVImport] Selected source: ", source
			except Exception, e:
				print>>log, "[XMLTVImport] Error at selected source:", e
			else:
				if cfg["sources"] != "":
					self.close(False, None, cfg)

class XMLTVImportProfile(ConfigListScreen, Screen):
	skin = """
		<screen position="center,center" size="400,230" title="XMLTVImportProfile" >
			<widget name="config" position="0,0" size="400,180" scrollbarMode="showOnDemand" />
			<widget name="key_red" position="0,190" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;18" transparent="1"/>
			<widget name="key_green" position="140,190" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;18" transparent="1"/>
			<ePixmap name="red"    position="0,190"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
			<ePixmap name="green"  position="140,190" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
		</screen>"""

	def __init__(self, session, args = 0):
		self.session = session
		Screen.__init__(self, session)
		self.list = []
		for i in range(7):
			self.list.append(getConfigListEntry(weekdays[i], config.plugins.extra_xmltvimport.day_import[i]))
		ConfigListScreen.__init__(self, self.list)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"],
		{
			"red": self.cancel,
			"green": self.save,
			"save": self.save,
			"cancel": self.cancel,
			"ok": self.save,
		}, -2)
		self.onLayoutFinish.append(self.setCustomTitle)

	def setCustomTitle(self):
		self.setTitle(_("Days Profile"))

	def save(self):
		if not config.plugins.extra_xmltvimport.day_import[0].value:
			if not config.plugins.extra_xmltvimport.day_import[1].value:
				if not config.plugins.extra_xmltvimport.day_import[2].value:
					if not config.plugins.extra_xmltvimport.day_import[3].value:
						if not config.plugins.extra_xmltvimport.day_import[4].value:
							if not config.plugins.extra_xmltvimport.day_import[5].value:
								if not config.plugins.extra_xmltvimport.day_import[6].value:
									self.session.open(MessageBox, _("You may not use this settings!\nAt least one day a week should be included!"), MessageBox.TYPE_INFO, timeout = 6)
									return
		for x in self["config"].list:
			x[1].save()
		self.close()

	def cancel(self):
		for x in self["config"].list:
			x[1].cancel()
		self.close()

class XMLTVImportLog(Screen):
	skin = """
		<screen position="center,center" size="560,400" title="XMLTV Import Log" >
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
		self.onLayoutFinish.append(self.setCustomTitle)

	def setCustomTitle(self):
		self.setTitle(_("XMLTV Import Log"))

	def save(self):
		try:
			f = open('/tmp/xmltvimport.log', 'w')
			f.write(log.getvalue())
			self.session.open(MessageBox, _("Write to /tmp/xmltvimport.log"), MessageBox.TYPE_INFO, timeout = 5, close_on_any_key = True)
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

class XMLTVImportDownloader(MessageBox):
	def __init__(self, session):
		MessageBox.__init__(self, session, _("Last import: ")+ config.plugins.extra_xmltvimport.last_import.value + _(" events\n") + _("\nImport of epg data will start.\nThis may take a few minutes.\nIs this ok?"), MessageBox.TYPE_YESNO)
		self.skinName = "MessageBox"

def msgClosed(ret):
	global autoStartTimer
	if ret:
		if autoStartTimer is not None and not xmltvimport.isImportRunning():
			print>>log, "[XMLTVImport] Run manual starting import"
			autoStartTimer.runImport()

def start_import(session, **kwargs):
	session.openWithCallback(msgClosed, XMLTVImportDownloader)

def main(session, **kwargs):
	session.openWithCallback(doneConfiguring, XMLTVImportConfig)

def main_menu(menuid, **kwargs):
	if menuid == "mainmenu" and config.plugins.xmltvimport.showinmainmenu.getValue():
		return [(_("XMLTV Importer"), start_import, "xmltvimporter", 45)]
	else:
		return []

def doneConfiguring(session, retval):
	"user has closed configuration, check new values...."
	if autoStartTimer is not None:
		autoStartTimer.update()

def doneImport(reboot=False, epgfile=None):
	global _session, lastImportResult, BouquetChannelListList, parse_autotimer
	BouquetChannelListList = None
	lastImportResult = (time.time(), xmltvimport.eventCount)
	try:
		start, count = lastImportResult
		localtime = time.asctime( time.localtime(time.time()))
		lastimport = "%s, %d" % (localtime, count)
		config.plugins.extra_xmltvimport.last_import.value = lastimport
		config.plugins.extra_xmltvimport.last_import.save()
		print>>log, "[XMLTVImport] Save last import date and count event"
	except:
		print>>log, "[XMLTVImport] Error to save last import date and count event"
	if reboot:
		if Screens.Standby.inStandby:
			print>>log, "[XMLTVImport] Restart enigma2"
			restartEnigma(True)
		else:
			msg = _("XMLTV Import finished, %d events") % xmltvimport.eventCount + "\n" + _("You must restart Enigma2 to load the EPG data,\nis this OK?")
			_session.openWithCallback(restartEnigma, MessageBox, msg, MessageBox.TYPE_YESNO, timeout = 15, default = True)
			print>>log, "[XMLTVImport] Need restart enigma2"
	else:
		if config.plugins.xmltvimport.parse_autotimer.value and fileExists("/usr/lib/enigma2/python/Plugins/Extensions/AutoTimer/plugin.py"):
			try:
				from Plugins.Extensions.AutoTimer.plugin import autotimer
				if autotimer is None:
					from Plugins.Extensions.AutoTimer.AutoTimer import AutoTimer
					autotimer = AutoTimer()
				if not parse_autotimer:
					autotimer.readXml()
					checkDeepstandby(_session, parse=True)
					autotimer.parseEPGAsync(simulateOnly=False)
					print>>log, "[XMLTVImport] Run start parse autotimers"
					parse_autotimer = True
			except:
				print>>log, "[XMLTVImport] Could not start autotimers"
				checkDeepstandby(_session, parse=False)
		else:
			checkDeepstandby(_session, parse=False)

class checkDeepstandby:
	def __init__(self, session, parse=False):
		self.session = session
		if parse:
			self.FirstwaitCheck = enigma.eTimer()
			self.FirstwaitCheck.callback.append(self.runCheckDeepstandby)
			self.FirstwaitCheck.startLongTimer(30)
			print>>log, "[XMLTVImport] Wait for parse autotimers 30 sec."
		else:
			self.runCheckDeepstandby()

	def runCheckDeepstandby(self):
		print>>log, "[XMLTVImport] Run check deep standby after import"
		global parse_autotimer
		parse_autotimer = False
		if config.plugins.xmltvimport.shutdown.value and config.plugins.xmltvimport.deepstandby.value == 'wakeup':
			if config.plugins.xmltvimport.deepstandby_afterimport.value and getFPWasTimerWakeup():
				config.plugins.xmltvimport.deepstandby_afterimport.value = False
				if Screens.Standby.inStandby and not self.session.nav.getRecordings() and not Screens.Standby.inTryQuitMainloop:
					print>>log, "[XMLTVImport] Returning to deep standby after wake up for import"
					self.session.open(Screens.Standby.TryQuitMainloop, 1)
				else:
					print>>log, "[XMLTVImport] No return to deep standby, not standby or running recording"


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
		self.prev_onlybouquet = config.plugins.xmltvimport.import_onlybouquet.value
		self.prev_multibouquet = config.usage.multibouquet.value
		self.timer = enigma.eTimer()
		self.timer.callback.append(self.onTimer)
		self.pauseAfterFinishImportCheck = enigma.eTimer()
		self.pauseAfterFinishImportCheck.callback.append(self.afterFinishImportCheck)
		self.pauseAfterFinishImportCheck.startLongTimer(30)
		self.update()

	def getWakeTime(self):
		if config.plugins.xmltvimport.enabled.value:
			clock = config.plugins.xmltvimport.wakeup.value
			nowt = time.time()
			now = time.localtime(nowt)
			return int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, clock[0], clock[1], lastMACbyte()/5, 0, now.tm_yday, now.tm_isdst)))
		else:
			return -1

	def update(self, atLeast = 0):
		self.timer.stop()
		wake = self.getWakeTime()
		now_t = time.time()
		now = int(now_t)
		now_day = time.localtime(now_t)
		if wake > 0:
			cur_day = int(now_day.tm_wday)
			wakeup_day = WakeupDayOfWeek()
			if wakeup_day == -1:
				return -1
				print>>log, "[XMLTVImport] wakeup day of week disabled"
			if wake < now + atLeast:
				wake += 86400*wakeup_day
			else:
				if not config.plugins.extra_xmltvimport.day_import[cur_day].value:
					wake += 86400*wakeup_day
			next = wake - now
			self.timer.startLongTimer(next)
		else:
			wake = -1
		print>>log, "[XMLTVImport] WakeUpTime now set to", wake, "(now=%s)" % now
		return wake

	def runImport(self):
		if self.prev_onlybouquet != config.plugins.xmltvimport.import_onlybouquet.value or self.prev_multibouquet != config.usage.multibouquet.value:
			self.prev_onlybouquet = config.plugins.xmltvimport.import_onlybouquet.value
			self.prev_multibouquet = config.usage.multibouquet.value
			XMLTVConfig.channelCache = {}
		cfg = XMLTVConfig.loadUserSettings()
		sources = [ s for s in XMLTVConfig.enumSources(CONFIG_PATH, filter = cfg["sources"]) ]
		if sources:
			sources.reverse()
			xmltvimport.sources = sources
			startImport()

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

	def getSources(self):
		cfg = XMLTVConfig.loadUserSettings()
		sources = [ s for s in XMLTVConfig.enumSources(CONFIG_PATH, filter = cfg["sources"]) ]
		if sources:
			return True
		return False

	def getStatus(self):
		wake_up = self.getWakeTime()
		now_t = time.time()
		now = int(now_t)
		now_day = time.localtime(now_t)
		if wake_up > 0:
			cur_day = int(now_day.tm_wday)
			wakeup_day = WakeupDayOfWeek()
			if wakeup_day == -1:
				return -1
				print>>log, "[XMLTVImport] wakeup day of week disabled"
			if wake_up < now:
				wake_up += 86400*wakeup_day
			else:
				if not config.plugins.extra_xmltvimport.day_import[cur_day].value:
					wake_up += 86400*wakeup_day
		else:
			wake_up = -1
		return wake_up

	def afterFinishImportCheck(self):
		if config.plugins.xmltvimport.deepstandby.value == 'wakeup' and getFPWasTimerWakeup():
			if os.path.exists("/tmp/enigmastandby") or os.path.exists("/tmp/.XMLTVImportAnswerBoot"):
				print>>log, "[XMLTVImport] is restart enigma2"
			else:
				wake = self.getStatus()
				now_t = time.time()
				now = int(now_t)
				if 0 < wake - now <= 60*5:
					if config.plugins.xmltvimport.standby_afterwakeup.value:
						if not Screens.Standby.inStandby:
							Notifications.AddNotification(Screens.Standby.Standby)
							print>>log, "[XMLTVImport] Run to standby after wake up"
					if config.plugins.xmltvimport.shutdown.value:
						if not config.plugins.xmltvimport.standby_afterwakeup.value:
							if not Screens.Standby.inStandby:
								Notifications.AddNotification(Screens.Standby.Standby)
								print>>log, "[XMLTVImport] Run to standby after wake up for checking"
						if not config.plugins.xmltvimport.deepstandby_afterimport.value:
							config.plugins.xmltvimport.deepstandby_afterimport.value = True
							self.wait_timer = enigma.eTimer()
							self.wait_timer.timeout.get().append(self.startStandby)
							print>>log, "[XMLTVImport] start wait_timer (10sec) for goto standby"
							self.wait_timer.start(10000, True)

	def startStandby(self):
		if Screens.Standby.inStandby:
			print>>log, "[XMLTVImport] add checking standby"
			try:
				Screens.Standby.inStandby.onClose.append(self.onLeaveStandby)
			except:
				pass

	def onLeaveStandby(self):
		if config.plugins.xmltvimport.deepstandby_afterimport.value:
			config.plugins.xmltvimport.deepstandby_afterimport.value = False
			print>>log, "[XMLTVImport] checking standby remove, not deep standby after import"

def WakeupDayOfWeek():
	start_day = -1
	try:
		now = time.time()
		now_day = time.localtime(now)
		cur_day = int(now_day.tm_wday)
	except:
		cur_day = -1
	if cur_day >= 0:
		for i in (1,2,3,4,5,6,7):
			if config.plugins.extra_xmltvimport.day_import[(cur_day+i)%7].value:
				return i
	return start_day

def onBootStartCheck():
	global autoStartTimer
	print>>log, "[XMLTVImport] onBootStartCheck"
	now = int(time.time())
	wake = autoStartTimer.getStatus()
	print>>log, "[XMLTVImport] now=%d wake=%d wake-now=%d" % (now, wake, wake-now)
	if (wake < 0) or (wake - now > 600):
		on_start = False
		if config.plugins.xmltvimport.runboot.value == "1":
			on_start = True
			print>>log, "[XMLTVImport] is boot"
		elif config.plugins.xmltvimport.runboot.value == "2" and not getFPWasTimerWakeup():
			on_start = True
			print>>log, "[XMLTVImport] is manual boot"
		elif config.plugins.xmltvimport.runboot.value == "3" and getFPWasTimerWakeup():
			on_start = True
			print>>log, "[XMLTVImport] is automatic boot"
		flag = '/tmp/.XMLTVImportAnswerBoot'
		if config.plugins.xmltvimport.runboot_restart.value and config.plugins.xmltvimport.runboot.value != "3":
			if os.path.exists(flag):
				on_start = False
				print>>log, "[XMLTVImport] not starting import - is restart enigma2"
			else:
				try:
					open(flag, 'wb').close()
				except:
					print>>log, "Failed to create /tmp/.XMLTVImportAnswerBoot"
		if config.plugins.xmltvimport.runboot_day.value:
			now = time.localtime()
			cur_day = int(now.tm_wday)
			if not config.plugins.extra_xmltvimport.day_import[cur_day].value:
				on_start = False
				print>>log, "[XMLTVImport] wakeup day of week does not match"
		if on_start:
			print>>log, "[XMLTVImport] starting import because auto-run on boot is enabled"
			autoStartTimer.runImport()
	else:
		print>>log, "[XMLTVImport] import to start in less than 10 minutes anyway, skipping..."

def autostart(reason, session=None, **kwargs):
	"called with reason=1 to during shutdown, with reason=0 at startup?"
	global autoStartTimer
	global _session
	print>>log, "[XMLTVImport] autostart (%s) occured at" % reason, time.time()
	if reason == 0 and _session is None:
		if session is not None:
			_session = session
			if autoStartTimer is None:
				autoStartTimer = AutoStartTimer(session)
			if config.plugins.xmltvimport.runboot.value != "4":
				onBootStartCheck()
		# If WE caused the reboot, put the box back in standby.
		if os.path.exists("/tmp/enigmastandby"):
			print>>log, "[XMLTVImport] Returning to standby"
			if not Screens.Standby.inStandby:
				Notifications.AddNotification(Screens.Standby.Standby)
			try:
				os.remove("/tmp/enigmastandby")
			except:
				pass
	else:
		print>>log, "[XMLTVImport] Stop"

def getNextWakeup():
	"returns timestamp of next time when autostart should be called"
	if autoStartTimer:
		if config.plugins.xmltvimport.deepstandby.value == 'wakeup' and autoStartTimer.getSources():
			print>>log, "[XMLTVImport] Will wake up from deep sleep"
			return autoStartTimer.getStatus()
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
extDescriptor = PluginDescriptor(name= _("XMLTV-Importer"), description = description, where = PluginDescriptor.WHERE_EXTENSIONSMENU, fnc = extensionsmenu)
pluginlist = PluginDescriptor(name=_("XMLTV-Importer"), description = description, where = PluginDescriptor.WHERE_PLUGINMENU, icon = 'plugin.png', fnc = main)

def epgmenu(menuid, **kwargs):
	if getImageDistro() in ("openvix", "ventonsupport", "egami", "openatv"):
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
			where = PluginDescriptor.WHERE_PLUGINMENU,
			icon = 'plugin.png',
			fnc = main
		),
		PluginDescriptor(
			name=_("XMLTV-importer"),
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

