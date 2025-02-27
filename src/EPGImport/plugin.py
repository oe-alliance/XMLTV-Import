from os import remove
from os.path import exists
from time import localtime, mktime, strftime, strptime, time, asctime

from enigma import eServiceCenter, eServiceReference, eEPGCache, eTimer, getDesktop

# for localized messages
from . import _
from . import log
from . import ExpandableSelectionList
from . import filtersServices
# Plugin
from . import EPGImport
from . import EPGConfig


try:
	from Components.SystemInfo import BoxInfo
	IMAGEDISTRO = BoxInfo.getItem("distro")
except:
	from boxbranding import getImageDistro
	IMAGEDISTRO = getImageDistro()

# Config
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.config import config, ConfigEnableDisable, ConfigSubsection, ConfigYesNo, ConfigClock, getConfigListEntry, ConfigText, ConfigSelection, ConfigNumber, ConfigSubDict, NoSave
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
import Components.PluginComponent
from Components.ScrollLabel import ScrollLabel
from Plugins.Plugin import PluginDescriptor
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
import Screens.Standby
from Tools import Notifications
from Tools.Directories import fileExists, SCOPE_PLUGINS, resolveFilename, isPluginInstalled
from Tools.FuzzyDate import FuzzyTime
from Tools.StbHardware import getFPWasTimerWakeup

import NavigationInstance


def lastMACbyte():
	try:
		return int(open("/sys/class/net/eth0/address").readline().strip()[-2:], 16)
	except:
		return 256


def calcDefaultStarttime():
	try:
		# Use the last MAC byte as time offset (half-minute intervals)
		offset = lastMACbyte() * 30
	except:
		offset = 7680
	return (5 * 60 * 60) + offset


# historically located (not a problem, we want to update it)
CONFIG_PATH = "/etc/epgimport"

# Global variable
autoStartTimer = None
_session = None
BouquetChannelListList = None
serviceIgnoreList = None

# Set default configuration
config.plugins.epgimport = ConfigSubsection()
config.plugins.epgimport.enabled = ConfigEnableDisable(default=False)
config.plugins.epgimport.runboot = ConfigSelection(default="4", choices=[
	("1", _("always")),
	("2", _("only manual boot")),
	("3", _("only automatic boot")),
	("4", _("never"))
])
config.plugins.epgimport.runboot_restart = ConfigYesNo(default=False)
config.plugins.epgimport.runboot_day = ConfigYesNo(default=False)
config.plugins.epgimport.wakeupsleep = ConfigEnableDisable(default=False)
config.plugins.epgimport.wakeup = ConfigClock(default=calcDefaultStarttime())
# Different default in OpenATV:
config.plugins.epgimport.showinplugins = ConfigYesNo(default=IMAGEDISTRO != "openatv")
config.plugins.epgimport.showinextensions = ConfigYesNo(default=True)
config.plugins.epgimport.deepstandby = ConfigSelection(default="skip", choices=[
	("wakeup", _("wake up and import")),
	("skip", _("skip the import"))
])
config.plugins.epgimport.standby_afterwakeup = ConfigYesNo(default=False)
config.plugins.epgimport.shutdown = ConfigYesNo(default=False)
config.plugins.epgimport.longDescDays = ConfigNumber(default=5)
# config.plugins.epgimport.showinmainmenu = ConfigYesNo(default=False)
config.plugins.epgimport.deepstandby_afterimport = NoSave(ConfigYesNo(default=False))
config.plugins.epgimport.parse_autotimer = ConfigYesNo(default=False)
config.plugins.epgimport.import_onlybouquet = ConfigYesNo(default=False)
config.plugins.epgimport.import_onlyiptv = ConfigYesNo(default=False)
config.plugins.epgimport.clear_oldepg = ConfigYesNo(default=False)
config.plugins.epgimport.day_profile = ConfigSelection(choices=[("1", _("Press OK"))], default="1")
config.plugins.extra_epgimport = ConfigSubsection()
config.plugins.extra_epgimport.last_import = ConfigText(default="0")
config.plugins.extra_epgimport.day_import = ConfigSubDict()

for i in range(7):
	config.plugins.extra_epgimport.day_import[i] = ConfigEnableDisable(default=True)

weekdays = [
	_("Monday"),
	_("Tuesday"),
	_("Wednesday"),
	_("Thursday"),
	_("Friday"),
	_("Saturday"),
	_("Sunday"),
]


def getAlternatives(service):
	if not service:
		return None
	alternativeServices = eServiceCenter.getInstance().list(service)
	return alternativeServices and alternativeServices.getContent("S", True)


def getRefNum(ref):
	ref = ref.split(":")[3:7]
	try:
		return int(ref[0], 16) << 48 | int(ref[1], 16) << 32 | int(ref[2], 16) << 16 | int(ref[3], 16) >> 16
	except:
		return


def getBouquetChannelList():
	channels = []
	serviceHandler = eServiceCenter.getInstance()
	mask = (eServiceReference.isMarker | eServiceReference.isDirectory)
	altrernative = eServiceReference.isGroup
	if config.usage.multibouquet.value:
		bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "bouquets.tv" ORDER BY bouquet'
		bouquet_root = eServiceReference(bouquet_rootstr)
		list = serviceHandler.list(bouquet_root)
		if list:
			while True:
				s = list.getNext()
				if not s.valid():
					break
				if s.flags & eServiceReference.isDirectory:
					info = serviceHandler.info(s)
					if info:
						clist = serviceHandler.list(s)
						if clist:
							while True:
								service = clist.getNext()
								if not service.valid():
									break
								if not (service.flags & mask):
									if service.flags & altrernative:
										altrernative_list = getAlternatives(service)
										if altrernative_list:
											for channel in altrernative_list:
												refnum = getRefNum(channel)
												if refnum and refnum not in channels:
													channels.append(refnum)
									else:
										refnum = getRefNum(service.toString())
										if refnum and refnum not in channels:
											channels.append(refnum)
	else:
		bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.favourites.tv" ORDER BY bouquet'
		bouquet_root = eServiceReference(bouquet_rootstr)
		services = serviceHandler.list(bouquet_root)
		if services is not None:
			while True:
				service = services.getNext()
				if not service.valid():
					break
				if not (service.flags & mask):
					if service.flags & altrernative:
						altrernative_list = getAlternatives(service)
						if altrernative_list:
							for channel in altrernative_list:
								refnum = getRefNum(channel)
								if refnum and refnum not in channels:
									channels.append(refnum)
					else:
						refnum = getRefNum(service.toString())
						if refnum and refnum not in channels:
							channels.append(refnum)
	return channels

# Filter servicerefs that this box can display by starting a fake recording.


def channelFilter(ref):
	if not ref:
		return False
	# ignore non IPTV
	if config.plugins.epgimport.import_onlyiptv.value and ("%3a//" not in ref.lower() or ref.startswith("1")):
		return False
	sref = eServiceReference(ref)
	refnum = getRefNum(sref.toString())
	if config.plugins.epgimport.import_onlybouquet.value:
		global BouquetChannelListList
		if BouquetChannelListList is None:
			BouquetChannelListList = getBouquetChannelList()
		if refnum not in BouquetChannelListList:
			print("Serviceref not in bouquets:", sref.toString(), file=log)
			return False
	global serviceIgnoreList
	if serviceIgnoreList is None:
		serviceIgnoreList = [getRefNum(x) for x in filtersServices.filtersServicesList.servicesList()]
	if refnum in serviceIgnoreList:
		print(f"Serviceref is in ignore list:{sref.toString()}", file=log)
		return False
	if "%3a//" in ref.lower():
		# print("URL detected in serviceref, not checking fake recording on serviceref:", ref, file=log)
		return True
	fakeRecService = NavigationInstance.instance.recordService(sref, True)
	if fakeRecService:
		fakeRecResult = fakeRecService.start(True)
		NavigationInstance.instance.stopRecordService(fakeRecService)
		# -7 (errNoSourceFound) occurs when tuner is disconnected.
		r = fakeRecResult in (0, -7)
		return r
	print(f"Invalid serviceref string: {ref}", file=log)
	return False


try:
	epgcache_instance = eEPGCache.getInstance()
	if not epgcache_instance:
		print("[EPGImport] Failed to get valid EPGCache instance.", file=log)
	else:
		print("[EPGImport] EPGCache instance obtained successfully.", file=log)
	epgimport = EPGImport.EPGImport(epgcache_instance, channelFilter)
except Exception as e:
	print(f"[EPGImport] Error obtaining EPGCache instance: {e}", file=log)

lastImportResult = None


def startImport():
	if not epgimport.isImportRunning():
		EPGImport.HDD_EPG_DAT = config.misc.epgcache_filename.value
		if config.plugins.epgimport.clear_oldepg.value and hasattr(epgimport.epgcache, "flushEPG"):
			EPGImport.unlink_if_exists(EPGImport.HDD_EPG_DAT)
			EPGImport.unlink_if_exists(f"{EPGImport.HDD_EPG_DAT}.backup")
			epgimport.epgcache.flushEPG()
		epgimport.onDone = doneImport
		epgimport.beginImport(longDescUntil=config.plugins.epgimport.longDescDays.value * 24 * 3600 + time())
	else:
		print("[startImport] Already running, won't start again")


##################################
# Configuration GUI
HD = True if getDesktop(0).size().width() >= 1280 else False


class EPGImportConfig(ConfigListScreen, Screen):
	if HD:
		skin = """
			<screen position="center,center" size="600,500" title="EPG Import Configuration" >
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
			<screen position="center,center" size="600,430" title="EPG Import Configuration" >
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

	def __init__(self, session, args=0):
		self.skin = EPGImportConfig.skin
		self.setup_title = _("EPG Import Configuration")
		Screen.__init__(self, session)
		self["status"] = Label()
		self["statusbar"] = Label(_("Last import: %s events") % config.plugins.extra_epgimport.last_import.value)
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
			"contextMenu": self.openMenu,
		}, -1)
		ConfigListScreen.__init__(self, [], session=self.session)
		self.lastImportResult = None
		self.onChangedEntry = []
		self.prev_onlybouquet = config.plugins.epgimport.import_onlybouquet.value
		self.initConfig()
		self.createSetup()
		self.importStatusTemplate = _("Importing:\n%s %s events")
		self.updateTimer = eTimer()
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
			res = {}
			for (key, val) in section.content.items.items():
				if isinstance(val, ConfigSubsection):
					res[key] = getPrevValues(val)
				else:
					res[key] = val.value
			return res

		self.EPG = config.plugins.epgimport
		self.prev_values = getPrevValues(self.EPG)
		self.cfg_enabled = getConfigListEntry(_("Automatic import EPG"), self.EPG.enabled)
		self.cfg_wakeup = getConfigListEntry(_("Automatic start time"), self.EPG.wakeup)
		self.cfg_deepstandby = getConfigListEntry(_("When in deep standby"), self.EPG.deepstandby)
		self.cfg_shutdown = getConfigListEntry(_("Return to deep standby after import"), self.EPG.shutdown)
		self.cfg_standby_afterwakeup = getConfigListEntry(_("Standby at startup"), self.EPG.standby_afterwakeup)
		self.cfg_day_profile = getConfigListEntry(_("Choice days for start import"), self.EPG.day_profile)
		self.cfg_runboot = getConfigListEntry(_("Start import after booting up"), self.EPG.runboot)
		self.cfg_import_onlybouquet = getConfigListEntry(_("Load EPG only services in bouquets"), self.EPG.import_onlybouquet)
		self.cfg_import_onlyiptv = getConfigListEntry(_("Load EPG only for IPTV channels"), self.EPG.import_onlyiptv)
		self.cfg_runboot_day = getConfigListEntry(_("Consider setting \"Days Profile\""), self.EPG.runboot_day)
		self.cfg_runboot_restart = getConfigListEntry(_("Skip import on restart GUI"), self.EPG.runboot_restart)
		self.cfg_showinextensions = getConfigListEntry(_("Show \"EPGImport\" in extensions"), self.EPG.showinextensions)
		self.cfg_showinplugins = getConfigListEntry(_("Show \"EPGImport\" in plugins"), self.EPG.showinplugins)
#       self.cfg_showinmainmenu = getConfigListEntry(_("Show \"EPG Importer\" in main menu"), self.EPG.showinmainmenu)
		self.cfg_longDescDays = getConfigListEntry(_("Load long descriptions up to X days"), self.EPG.longDescDays)
		self.cfg_parse_autotimer = getConfigListEntry(_("Run AutoTimer after import"), self.EPG.parse_autotimer)
		self.cfg_clear_oldepg = getConfigListEntry(_("Delete current EPG before import"), config.plugins.epgimport.clear_oldepg)

	def createSetup(self):
		list = [self.cfg_enabled]
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
		list.append(self.cfg_import_onlybouquet)
		list.append(self.cfg_import_onlyiptv)
		if hasattr(eEPGCache, "flushEPG"):
			list.append(self.cfg_clear_oldepg)
		list.append(self.cfg_longDescDays)
		if isPluginInstalled("AutoTimer"):
			try:
				list.append(self.cfg_parse_autotimer)
			except:
				print("[XMLTVImport] AutoTimer Plugin not installed", file=log)
		list.append(self.cfg_showinextensions)
		list.append(self.cfg_showinplugins)
		self["config"].list = list
		self["config"].l.setList(list)

	def newConfig(self):
		cur = self["config"].getCurrent()
		if cur in (self.cfg_enabled, self.cfg_shutdown, self.cfg_deepstandby, self.cfg_runboot):
			self.createSetup()

	def keyRed(self):

		def setPrevValues(section, values):
			for (key, val) in section.content.items.items():
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
		if self.EPG.parse_autotimer.value and not isPluginInstalled("AutoTimer"):
			self.EPG.parse_autotimer.value = False
		if self.EPG.shutdown.value:
			self.EPG.standby_afterwakeup.value = False
		if self.prev_onlybouquet != config.plugins.epgimport.import_onlybouquet.value or (autoStartTimer is not None and autoStartTimer.prev_multibouquet != config.usage.multibouquet.value):
			EPGConfig.channelCache = {}
		self.save()

	def save(self):
		if self["config"].isChanged():
			for x in self["config"].list:
				x[1].save()
			self.EPG.save()
			self.session.open(MessageBox, _("Settings saved successfully !"), MessageBox.TYPE_INFO, timeout=5)
		self.close(True, self.session)

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.newConfig()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.newConfig()

	def keyOk(self):
		# ConfigListScreen.keyOK(self)
		sel = self["config"].getCurrent()[1]
		if sel and sel == self.EPG.day_profile:
			self.session.open(EPGImportProfile)

	def updateStatus(self):
		text = ""
		if epgimport.isImportRunning():
			src = epgimport.source
			text = self.importStatusTemplate % (src.description, epgimport.eventCount)
		self["status"].setText(text)
		if lastImportResult and (lastImportResult != self.lastImportResult):
			start, count = lastImportResult
			"""
			## issue crash trhead
			# try:
				# d, t = FuzzyTime(start, inPast=True)
			# except:
				# # Not all images have inPast
				# d, t = FuzzyTime(start)
			"""
			try:
				if isinstance(start, str):
					start = mktime(strptime(start, "%Y-%m-%d %H:%M:%S"))
				elif not isinstance(start, (int, float)):
					raise ValueError("Start value is not a valid timestamp or string")

				d, t = FuzzyTime(int(start), inPast=True)
			except Exception as e:
				print(f"[EPGImport] Error FuzzyTime: {e}")
				try:
					d, t = FuzzyTime(int(start))
				except Exception as e:
					print(f"[EPGImport] Fallback with FuzzyTime also failed: {e}")

			self["statusbar"].setText(_(f"Last import: {d} {t}, {count} events"))
		self.lastImportResult = lastImportResult

	def keyInfo(self):
		last_import = config.plugins.extra_epgimport.last_import.value
		self.session.open(MessageBox, _("Last import: %s events") % last_import, type=MessageBox.TYPE_INFO)

	def doimport(self, one_source=None):
		if epgimport.isImportRunning():
			print("[XMLTVImport] Already running, won't start again", file=log)
			self.session.open(MessageBox, _("EPGImport\nImport of epg data is still in progress. Please wait."), MessageBox.TYPE_ERROR, timeout=10, close_on_any_key=True)
			return
		if self.prev_onlybouquet != config.plugins.epgimport.import_onlybouquet.value or (autoStartTimer is not None and autoStartTimer.prev_multibouquet != config.usage.multibouquet.value):
			EPGConfig.channelCache = {}
		if one_source is None:
			cfg = EPGConfig.loadUserSettings()
		else:
			cfg = one_source
		sources = [s for s in EPGConfig.enumSources(CONFIG_PATH, filter=cfg["sources"])]
		if not sources:
			self.session.open(MessageBox, _("No active EPG sources found, nothing to do"), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
			return
		# make it a stack, first on top.
		sources.reverse()
		epgimport.sources = sources
		self.session.openWithCallback(self.do_import_callback, MessageBox, _("EPGImport\nImport of epg data will start.\nThis may take a few minutes.\nIs this ok?"), MessageBox.TYPE_YESNO, timeout=15, default=True)

	def do_import_callback(self, confirmed):
		if not confirmed:
			return
		try:
			startImport()
		except Exception as e:
			print("[XMLTVImport] Error at start:", e, file=log)
			self.session.open(MessageBox, _("EPGImport Plugin\nFailed to start:\n") + str(e), MessageBox.TYPE_ERROR, timeout=15, close_on_any_key=True)
		self.updateStatus()

	def dosources(self):
		self.session.openWithCallback(self.sourcesDone, EPGImportSources)

	def sourcesDone(self, confirmed, sources, cfg):
		# Called with True and list of config items on Okay.
		print("sourcesDone(): ", confirmed, sources, file=log)
		if cfg is not None:
			self.doimport(one_source=cfg)

	def openMenu(self):
		menu = [(_("Show log"), self.showLog), (_("Ignore services list"), self.openIgnoreList)]
		text = _("Select action")

		def setAction(choice):
			if choice:
				choice[1]()
		self.session.openWithCallback(setAction, ChoiceBox, title=text, list=menu)

	def openIgnoreList(self):
		self.session.open(filtersServices.filtersServicesSetup)

	def showLog(self):
		self.session.open(EPGImportLog)


class EPGImportSources(Screen):
	"Pick sources from config"
	skin = """
		<screen name="EPGImportSources" position="center,center" size="560,400" title="EPG Import Sources" >
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
		Screen.__init__(self, session)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))
		self["key_yellow"] = Button(_("Import"))
		self["key_blue"] = Button()
		cfg = EPGConfig.loadUserSettings()
		filter = cfg["sources"]
		tree = []
		cat = None
		for x in EPGConfig.enumSources(CONFIG_PATH, filter=None, categories=True):
			if hasattr(x, "description"):
				sel = (filter is None) or (x.description in filter)
				entry = (x.description, x.description, sel)
				if cat is None:
					# If no category defined, use a default one.
					cat = ExpandableSelectionList.category("[.]")
					tree.append(cat)
				cat[0][2].append(entry)
				if sel:
					ExpandableSelectionList.expand(cat, True)
			else:
				cat = ExpandableSelectionList.category(x)
				tree.append(cat)
		self["list"] = ExpandableSelectionList.ExpandableSelectionList(tree, enableWrapAround=True)
		if tree:
			self["key_yellow"].show()
		else:
			self["key_yellow"].hide()
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"],
		{
			"red": self.cancel,
			"green": self.save,
			"yellow": self.do_import,
			"save": self.save,
			"cancel": self.cancel,
			"ok": self["list"].toggleSelection,
		}, -2)
		self.setTitle(_("EPG Import Sources"))

	def save(self):
		""" Make the entries unique through a set """
		sources = list(set([item[1] for item in self["list"].enumSelected()]))
		print(f"[XMLTVImport] Selected sources:{sources}", file=log)
		EPGConfig.storeUserSettings(sources=sources)
		self.close(True, sources, None)

	def cancel(self):
		self.close(False, None, None)

	def do_import(self):
		list = self["list"].list
		if list and len(list) > 0:
			try:
				idx = self["list"].getSelectedIndex()
				item = self["list"].list[idx][0]
				source = [item[1] or ""]
				cfg = {"sources": source}
				print(f"[XMLTVImport] Selected source: {source}", file=log)
			except Exception as e:
				print(f"[XMLTVImport] Error at selected source:{e}", file=log)
			else:
				if cfg["sources"] != "":
					self.close(False, None, cfg)


class EPGImportProfile(ConfigListScreen, Screen):
	skin = """
		<screen position="center,center" size="400,230" title="EPGImportProfile" >
			<widget name="config" position="0,0" size="400,180" scrollbarMode="showOnDemand" />
			<widget name="key_red" position="0,190" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;18" transparent="1"/>
			<widget name="key_green" position="140,190" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;18" transparent="1"/>
			<ePixmap name="red"    position="0,190"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
			<ePixmap name="green"  position="140,190" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
		</screen>"""

	def __init__(self, session, args=0):
		Screen.__init__(self, session)
		self.list = []
		for i in range(7):
			self.list.append(getConfigListEntry(weekdays[i], config.plugins.extra_epgimport.day_import[i]))
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
		if all(not config.plugins.extra_epgimport.day_import[i].value for i in range(7)):
			self.session.open(
				MessageBox,
				_("You may not use this settings!\nAt least one day a week should be included!"),
				MessageBox.TYPE_INFO,
				timeout=6
			)
			return
		for x in self["config"].list:
			x[1].save()
		self.close()

	def cancel(self):
		for x in self["config"].list:
			x[1].cancel()
		self.close()


class EPGImportLog(Screen):
	skin = """
		<screen position="center,center" size="560,400" title="EPG Import Log" >
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
		self.log = log
		self["key_red"] = Button(_("Clear"))
		self["key_green"] = Button()
		self["key_yellow"] = Button()
		self["key_blue"] = Button(_("Save"))
		self["list"] = ScrollLabel(self.log.getvalue())
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
		self.setTitle(_("EPG Import Log"))

	def save(self):
		try:
			with open("/tmp/epgimport.log", "w") as f:
				f.write(self.log.getvalue())
			self.session.open(MessageBox, _("Write to /tmp/epgimport.log"), MessageBox.TYPE_INFO, timeout=5, close_on_any_key=True)
		except Exception as e:
			self["list"].setText(f"Failed to write /tmp/epgimport.log:str{str(e)}")
		self.close(True)

	def cancel(self):
		self.close(False)

	def clear(self):
		self.log.logfile.seek(0)
		self.log.logfile.truncate(0)
		self.close(False)


class EPGImportDownloader(MessageBox):
	def __init__(self, session):
		MessageBox.__init__(self, session, _("Last import: ") + config.plugins.extra_epgimport.last_import.value + _(" events\n") + _("\nImport of epg data will start.\nThis may take a few minutes.\nIs this ok?"), MessageBox.TYPE_YESNO)
		self.skinName = "MessageBox"


def msgClosed(ret):
	global autoStartTimer
	if ret:
		if autoStartTimer is not None and not epgimport.isImportRunning():
			print("[XMLTVImport] Run manual starting import", file=log)
			autoStartTimer.runImport()


def start_import(session, **kwargs):
	session.openWithCallback(msgClosed, EPGImportDownloader)


def main(session, **kwargs):
	session.openWithCallback(doneConfiguring, EPGImportConfig)


def doneConfiguring(session, retval=False):
	"""user has closed configuration, check new values...."""
	if retval is True:
		if autoStartTimer is not None:
			autoStartTimer.update()


def doneImport(reboot=False, epgfile=None):
	global _session, lastImportResult, BouquetChannelListList, serviceIgnoreList
	BouquetChannelListList = None
	serviceIgnoreList = None
	timestamp = time()
	formatted_time = strftime("%Y-%m-%d %H:%M:%S", localtime(timestamp))
	lastImportResult = (formatted_time, epgimport.eventCount)
	try:
		start, count = lastImportResult
		current_time = asctime(localtime(time()))
		lastimport = "%s, %d" % (current_time, count)
		config.plugins.extra_epgimport.last_import.value = lastimport
		config.plugins.extra_epgimport.last_import.save()
		print("[XMLTVImport] Save last import date and count event", file=log)
	except:
		print("[XMLTVImport] Error to save last import date and count event", file=log)
	if reboot:
		if Screens.Standby.inStandby:
			print("[XMLTVImport] Restart enigma2", file=log)
			restartEnigma(True)
		else:
			msg = _("EPG Import finished, %d events") % epgimport.eventCount + "\n" + _("You must restart Enigma2 to load the EPG data,\nis this OK?")
			_session.openWithCallback(restartEnigma, MessageBox, msg, MessageBox.TYPE_YESNO, timeout=15, default=True)
			print("[XMLTVImport] Need restart enigma2", file=log)
	else:
		if config.plugins.epgimport.parse_autotimer.value and isPluginInstalled("AutoTimer"):
			try:
				from Plugins.Extensions.AutoTimer.plugin import autotimer
				if autotimer is None:
					from Plugins.Extensions.AutoTimer.AutoTimer import AutoTimer
					autotimer = AutoTimer()
				autotimer.readXml()
				checkDeepstandby(_session, parse=True)
				autotimer.parseEPGAsync(simulateOnly=False)
				print("[XMLTVImport] Run start parse autotimers", file=log)
			except:
				print("[XMLTVImport] Could not start autotimers", file=log)
				checkDeepstandby(_session, parse=False)
		else:
			checkDeepstandby(_session, parse=False)


class checkDeepstandby:
	def __init__(self, session, parse=False):
		self.session = session
		if config.plugins.epgimport.enabled.value:
			if parse:
				self.FirstwaitCheck = eTimer()
				self.FirstwaitCheck.callback.append(self.runCheckDeepstandby)
				self.FirstwaitCheck.startLongTimer(600)
				print("[XMLTVImport] Wait for parse autotimers 600 sec.", file=log)
			else:
				self.runCheckDeepstandby()

	def runCheckDeepstandby(self):
		print("[XMLTVImport] Run check deep standby after import", file=log)
		if config.plugins.epgimport.shutdown.value and config.plugins.epgimport.deepstandby.value == "wakeup":
			if config.plugins.epgimport.deepstandby_afterimport.value and getFPWasTimerWakeup():
				config.plugins.epgimport.deepstandby_afterimport.value = False
				if Screens.Standby.inStandby and not self.session.nav.getRecordings() and not Screens.Standby.inTryQuitMainloop:
					print("[XMLTVImport] Returning to deep standby after wake up for import", file=log)
					self.session.open(Screens.Standby.TryQuitMainloop, 1)
				else:
					print("[XMLTVImport] No return to deep standby, not standby or running recording", file=log)


def restartEnigma(confirmed):
	if not confirmed:
		return
		# save state of enigma, so we can return to previeus state
	if Screens.Standby.inStandby:
		try:
			open("/tmp/enigmastandby", "wb").close()
		except:
			print("Failed to create /tmp/enigmastandby", file=log)
	else:
		try:
			remove("/tmp/enigmastandby")
		except:
			pass
	# now reboot
	_session.open(Screens.Standby.TryQuitMainloop, 3)


# Autostart section

class AutoStartTimer:
	def __init__(self, session):
		self.session = session
		self.prev_onlybouquet = config.plugins.epgimport.import_onlybouquet.value
		self.prev_multibouquet = config.usage.multibouquet.value
		self.clock = config.plugins.epgimport.wakeup.value
		self.autoStartImport = eTimer()
		self.autoStartImport.callback.append(self.onTimer)
		self.pauseAfterFinishImportCheck = eTimer()
		self.pauseAfterFinishImportCheck.callback.append(self.afterFinishImportCheck)
		self.pauseAfterFinishImportCheck.startLongTimer(30)
		self.update()

	def getWakeTime(self):
		if config.plugins.epgimport.enabled.value:
			nowt = time()
			now = localtime(nowt)
			return int(mktime((now.tm_year, now.tm_mon, now.tm_mday, self.clock[0], self.clock[1], lastMACbyte() // 5, 0, now.tm_yday, now.tm_isdst)))
		else:
			return -1

	def update(self, atLeast=0):
		self.autoStartImport.stop()
		wake = self.getWakeTime()
		now_t = time()
		now = int(now_t)
		now_day = localtime(now_t)
		if wake > 0:
			cur_day = int(now_day.tm_wday)
			wakeup_day = WakeupDayOfWeek()
			if wakeup_day == -1:
				return -1
			if wake < now + atLeast:
				wake += 86400 * wakeup_day
			else:
				if not config.plugins.extra_epgimport.day_import[cur_day].value:
					wake += 86400 * wakeup_day
			next = wake - now
			self.autoStartImport.startLongTimer(next)
		else:
			wake = -1
		print(f"[XMLTVImport] WakeUpTime now set to {wake} (now={now})", file=log)
		return wake

	def runImport(self):
		if self.prev_onlybouquet != config.plugins.epgimport.import_onlybouquet.value or self.prev_multibouquet != config.usage.multibouquet.value:
			self.prev_onlybouquet = config.plugins.epgimport.import_onlybouquet.value
			self.prev_multibouquet = config.usage.multibouquet.value
			EPGConfig.channelCache = {}
		cfg = EPGConfig.loadUserSettings()
		sources = [s for s in EPGConfig.enumSources(CONFIG_PATH, filter=cfg["sources"])]
		if sources:
			sources.reverse()
			epgimport.sources = sources
			startImport()

	def onTimer(self):
		self.autoStartImport.stop()
		now = int(time())
		print(f"[XMLTVImport] onTimer occured at {now}", file=log)
		wake = self.getWakeTime()
		# If we're close enough, we're okay...
		atLeast = 0
		if wake - now < 60:
			self.runImport()
			atLeast = 60
		self.update(atLeast)

	def getSources(self):
		cfg = EPGConfig.loadUserSettings()
		sources = [s for s in EPGConfig.enumSources(CONFIG_PATH, filter=cfg["sources"])]
		if sources:
			return True
		return False

	def getStatus(self):
		wake_up = self.getWakeTime()
		now_t = time()
		now = int(now_t)
		now_day = localtime(now_t)
		if wake_up > 0:
			cur_day = int(now_day.tm_wday)
			wakeup_day = WakeupDayOfWeek()
			if wakeup_day == -1:
				return -1
			if wake_up < now:
				wake_up += 86400 * wakeup_day
			else:
				if not config.plugins.extra_epgimport.day_import[cur_day].value:
					wake_up += 86400 * wakeup_day
		else:
			wake_up = -1
		return wake_up

	def afterFinishImportCheck(self):
		if config.plugins.epgimport.deepstandby.value == "wakeup" and getFPWasTimerWakeup():
			if exists("/tmp/enigmastandby") or exists("/tmp/.EPGImportAnswerBoot"):
				print("[XMLTVImport] is restart enigma2", file=log)
			else:
				wake = self.getStatus()
				now_t = time()
				now = int(now_t)
				if 0 < wake - now <= 60 * 5:
					if config.plugins.epgimport.standby_afterwakeup.value:
						if not Screens.Standby.inStandby:
							Notifications.AddNotification(Screens.Standby.Standby)
							print("[XMLTVImport] Run to standby after wake up", file=log)
					if config.plugins.epgimport.shutdown.value:
						if not config.plugins.epgimport.standby_afterwakeup.value:
							if not Screens.Standby.inStandby:
								Notifications.AddNotification(Screens.Standby.Standby)
								print("[XMLTVImport] Run to standby after wake up for checking", file=log)
						if not config.plugins.epgimport.deepstandby_afterimport.value:
							config.plugins.epgimport.deepstandby_afterimport.value = True
							self.wait_timer = eTimer()
							self.wait_timer.timeout.get().append(self.startStandby)
							print("[XMLTVImport] start wait_timer (10sec) for goto standby", file=log)
							self.wait_timer.start(10000, True)

	def startStandby(self):
		if Screens.Standby.inStandby:
			print("[XMLTVImport] add checking standby", file=log)
			try:
				Screens.Standby.inStandby.onClose.append(self.onLeaveStandby)
			except:
				pass

	def onLeaveStandby(self):
		if config.plugins.epgimport.deepstandby_afterimport.value:
			config.plugins.epgimport.deepstandby_afterimport.value = False
			print("[XMLTVImport] checking standby remove, not deep standby after import", file=log)


def WakeupDayOfWeek():
	start_day = -1
	try:
		now = time()
		now_day = localtime(now)
		cur_day = int(now_day.tm_wday)
	except:
		cur_day = -1
	if cur_day >= 0:
		for i in range(1, 8):
			if config.plugins.extra_epgimport.day_import[(cur_day + i) % 7].value:
				return i
	return start_day


def onBootStartCheck():
	global autoStartTimer
	print("[XMLTVImport] onBootStartCheck", file=log)
	now = int(time())
	wake = autoStartTimer.getStatus()
	print(f"[XMLTVImport] now={now} wake={wake} wake-now={wake - now}", file=log)
	if (wake < 0) or (wake - now > 600):
		runboot = config.plugins.epgimport.runboot.value
		on_start = False
		if runboot == "1":
			on_start = True
			print("[XMLTVImport] is boot", file=log)
		elif runboot == "2" and not getFPWasTimerWakeup():
			on_start = True
			print("[XMLTVImport] is manual boot", file=log)
		elif runboot == "3" and getFPWasTimerWakeup():
			on_start = True
			print("[XMLTVImport] is automatic boot", file=log)
		flag = "/tmp/.EPGImportAnswerBoot"
		if config.plugins.epgimport.runboot_restart.value and runboot != "3":
			if exists(flag):
				on_start = False
				print("[XMLTVImport] not starting import - is restart enigma2", file=log)
			else:
				try:
					open(flag, "wb").close()
				except:
					print("Failed to create /tmp/.EPGImportAnswerBoot", file=log)
		if config.plugins.epgimport.runboot_day.value:
			now = localtime()
			cur_day = int(now.tm_wday)
			if not config.plugins.extra_epgimport.day_import[cur_day].value:
				on_start = False
				print("[XMLTVImport] wakeup day of week does not match", file=log)
		if on_start:
			print("[XMLTVImport] starting import because auto-run on boot is enabled", file=log)
			autoStartTimer.runImport()
	else:
		print("[XMLTVImport] import to start in less than 10 minutes anyway, skipping...", file=log)


def autostart(reason, session=None, **kwargs):
	"""called with reason=1 to during shutdown, with reason=0 at startup?"""
	global autoStartTimer
	global _session
	print(f"[XMLTVImport] autostart ({reason}) occured at {int(time())}", file=log)
	if reason == 0 and _session is None:
		if session is not None:
			_session = session
			if autoStartTimer is None:
				autoStartTimer = AutoStartTimer(session)
			if config.plugins.epgimport.runboot.value != "4":
				onBootStartCheck()
		# If WE caused the reboot, put the box back in standby.
		if exists("/tmp/enigmastandby"):
			print("[XMLTVImport] Returning to standby", file=log)
			if not Screens.Standby.inStandby:
				Notifications.AddNotification(Screens.Standby.Standby)
			try:
				remove("/tmp/enigmastandby")
			except:
				pass
	else:
		print("[XMLTVImport] Stop", file=log)


def getNextWakeup():
	"""returns timestamp of next time when autostart should be called"""
	if autoStartTimer:
		if config.plugins.epgimport.enabled.value and config.plugins.epgimport.deepstandby.value == "wakeup" and autoStartTimer.getSources():
			print("[XMLTVImport] Will wake up from deep sleep", file=log)
			return autoStartTimer.getStatus()
	return -1


# we need this helper function to identify the descriptor
def extensionsmenu(session, **kwargs):
	main(session, **kwargs)


def setExtensionsmenu(el):
	try:
		if el.value:
			Components.PluginComponent.plugins.addPlugin(extDescriptor)
		else:
			Components.PluginComponent.plugins.removePlugin(extDescriptor)
	except Exception as e:
		print(f"[EPGImport] Failed to update extensions menu:{e}")


description = _("Automated EPG Importer")
config.plugins.epgimport.showinextensions.addNotifier(setExtensionsmenu, initial_call=False, immediate_feedback=False)
extDescriptor = PluginDescriptor(name=_("EPG-Importer Now"), description=description, where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=start_import)
pluginlist = PluginDescriptor(name=_("EPG-Importer"), description=description, where=PluginDescriptor.WHERE_PLUGINMENU, icon="plugin.png", fnc=main)


def epgmenu(menuid, **kwargs):
	if IMAGEDISTRO in ("openvix", "openbh", "ventonsupport", "egami", "openhdf", "opendroid"):
		if menuid == "epg":
			return [(_("EPG-Importer"), main, "epgimporter", 1002)]
		else:
			return []
	elif IMAGEDISTRO in ("openatv"):
		if menuid == "epg":
			return [(_("EPG-Importer"), main, "epgimporter", None)]
		else:
			return []
	elif IMAGEDISTRO in ("teamblue"):
		if menuid == "epg_menu":
			return [(_("EPG-Importer"), main, "epgimporter", 95)]
		else:
			return []
	else:
		if menuid == "setup":
			return [(_("EPG-Importer"), main, "epgimporter", 1002)]
		else:
			return []


def Plugins(**kwargs):
	result = [
		PluginDescriptor(
			name=_("EPG-Importer"),
			description=description,
			where=[
				PluginDescriptor.WHERE_AUTOSTART,
				PluginDescriptor.WHERE_SESSIONSTART
			],
			fnc=autostart,
			wakeupfnc=getNextWakeup
		),
		PluginDescriptor(
			name=_("EPG-Importer"),
			description=description,
			where=PluginDescriptor.WHERE_MENU,
			fnc=epgmenu
		),
	]
	if config.plugins.epgimport.showinextensions.value:
		result.append(extDescriptor)
	if config.plugins.epgimport.showinplugins.value:
		result.append(pluginlist)
	return result
