from os import makedirs, remove
from os.path import exists, join
from time import localtime, mktime, strftime, strptime, time, asctime

from enigma import eServiceCenter, eServiceReference, eEPGCache, eTimer

# for localized messages
from . import _
from . import log
from . import ExpandableSelectionList
from . import filtersServices
# Plugin
from . import EPGImport
from . import EPGConfig


from Components.SystemInfo import BoxInfo

# Config
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.config import config, ConfigEnableDisable, ConfigSubsection, ConfigYesNo, ConfigClock, ConfigText, ConfigInteger, ConfigSelection, ConfigNumber, ConfigSubDict, NoSave
import Components.PluginComponent
from Components.ScrollLabel import ScrollLabel
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
import Screens.Standby
from Tools import Notifications
from Tools.Directories import isPluginInstalled
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
STANDBY_FLAG_FILE = "/tmp/enigmastandby"
ANSWER_BOOT_FILE = "/tmp/.EPGImportAnswerBoot"
# Global variable
autoStartTimer = None
_session = None
BouquetChannelListList = None
serviceIgnoreList = None
filterCounter = 0
isFilterRunning = 0
IMAGEDISTRO = BoxInfo.getItem("distro")

SOURCE_LINKS = {
	0: "https://github.com/oe-alliance/EPGimport-Sources/archive/refs/heads/main.tar.gz",
	1: "https://github.com/Belfagor2005/EPGimport-Sources/archive/refs/heads/main.tar.gz"
}

# Set default configuration
config.plugins.epgimport = ConfigSubsection()
config.plugins.epgimport.enabled = ConfigEnableDisable(default=False)
config.plugins.epgimport.runboot = ConfigSelection(
	default=4,
	choices=[
		(1, _("always")),
		(2, _("only manual boot")),
		(3, _("only automatic boot")),
		(4, _("never"))
	]
)
config.plugins.epgimport.repeat_import = ConfigInteger(default=0, limits=(0, 23))
config.plugins.epgimport.runboot_restart = ConfigYesNo(default=False)
config.plugins.epgimport.runboot_day = ConfigYesNo(default=False)
config.plugins.epgimport.wakeup = ConfigClock(default=calcDefaultStarttime())
# Different default in OpenATV:
config.plugins.epgimport.showinplugins = ConfigYesNo(default=IMAGEDISTRO != "openatv")
config.plugins.epgimport.showinextensions = ConfigYesNo(default=True)
# config.plugins.epgimport.showinmainmenu = ConfigYesNo(default=False)
config.plugins.epgimport.deepstandby = ConfigSelection(
	default="skip",
	choices=[
		("wakeup", _("wake up and import")),
		("skip", _("skip the import"))
	]
)

config.plugins.epgimport.extra_source = ConfigSelection(
	default=0,
	choices=[
		(0, "OE-Alliance"),
		(1, "Lululla")
	]
)

config.plugins.epgimport.standby_afterwakeup = ConfigYesNo(default=False)
config.plugins.epgimport.run_after_standby = ConfigYesNo(default=False)
config.plugins.epgimport.shutdown = ConfigYesNo(default=False)
config.plugins.epgimport.longDescDays = ConfigNumber(default=5)
config.plugins.epgimport.deepstandby_afterimport = NoSave(ConfigYesNo(default=False))
config.plugins.epgimport.parse_autotimer = ConfigYesNo(default=False)
config.plugins.epgimport.import_onlybouquet = ConfigYesNo(default=False)
config.plugins.epgimport.import_onlyiptv = ConfigYesNo(default=False)
config.plugins.epgimport.clear_oldepg = ConfigYesNo(default=False)
config.plugins.epgimport.filter_custom_channel = ConfigYesNo(default=True)
config.plugins.epgimport.day_profile = NoSave(ConfigSelection(choices=[("1", _("Press OK"))], default="1"))
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
	global isFilterRunning, filterCounter
	isFilterRunning = 1
	serviceHandler = eServiceCenter.getInstance()
	mask = (eServiceReference.isMarker | eServiceReference.isDirectory)
	alternative = eServiceReference.isGroup
	if config.usage.multibouquet.value:
		bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "bouquets.tv" ORDER BY bouquet'
		bouquet_root = eServiceReference(bouquet_rootstr)
		service_list = serviceHandler.list(bouquet_root)
		if service_list:
			while True:
				s = service_list.getNext()
				if not s.valid():
					break
				if s.flags & eServiceReference.isDirectory:
					info = serviceHandler.info(s)
					if info:
						clist = serviceHandler.list(s)
						if clist:
							while True:
								service = clist.getNext()
								filterCounter += 1
								if not service.valid():
									break
								if not (service.flags & mask):
									if service.flags & alternative:
										alternative_list = getAlternatives(service)
										if alternative_list:
											for channel in alternative_list:
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
				filterCounter += 1
				if not service.valid():
					break
				if not (service.flags & mask):
					if service.flags & alternative:
						alternative_list = getAlternatives(service)
						if alternative_list:
							for channel in alternative_list:
								refnum = getRefNum(channel)
								if refnum and refnum not in channels:
									channels.append(refnum)
					else:
						refnum = getRefNum(service.toString())
						if refnum and refnum not in channels:
							channels.append(refnum)
	isFilterRunning = 0
	return channels


# Filter servicerefs that this box can display by starting a fake recording.


def channelFilter(ref):
	if not ref:
		return False
	# Ignore non IPTV
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
		return True

	fakeRecService = NavigationInstance.instance.recordService(sref, True)
	if fakeRecService:
		fakeRecResult = fakeRecService.start(True)
		NavigationInstance.instance.stopRecordService(fakeRecService)
		# -7 (errNoSourceFound) occurs when tuner is disconnected.
		return fakeRecResult in (0, -7)
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
	EPGImport.HDD_EPG_DAT = config.misc.epgcache_filename.value
	if config.plugins.epgimport.clear_oldepg.value and hasattr(epgimport.epgcache, "flushEPG"):
		EPGImport.unlink_if_exists(EPGImport.HDD_EPG_DAT)
		EPGImport.unlink_if_exists(f"{EPGImport.HDD_EPG_DAT}.backup")
		epgimport.epgcache.flushEPG()
	epgimport.onDone = doneImport
	epgimport.beginImport(longDescUntil=config.plugins.epgimport.longDescDays.value * 24 * 3600 + time())


# #################################
# Configuration GUI
# FHD = True if getDesktop(0).size().width() >= 1280 else False


class EPGImportConfig(Setup):
	def __init__(self, session, args=0):
		self.hasAutoTimer = isPluginInstalled("AutoTimer")
		Setup.__init__(self, session, "EPGImportConfig", plugin="Extensions/EPGImport", PluginLanguageDomain="EPGImport")
		self.setTitle(_("EPG Import Configuration"))
		self.skinName = "Setup"
		# self.updateStatus()
		self.setFootnote(_("Last import: %s events") % config.plugins.extra_epgimport.last_import.value)
		self["key_yellow"] = StaticText(_("Manual"))
		self["key_blue"] = StaticText(_("Sources"))
		self["key_info"] = StaticText(_("INFO"))
		self["colorActions"] = ActionMap(["ColorActions", "MenuActions", "InfoActions"], {
			"yellow": self.doimport,
			"blue": self.dosources,
			"menu": self.openMenu,
			"info": self.keyInfo
		}, -1)
		self.lastImportResult = None
		self.filterStatusTemplate = _("Filtering: %s Please wait!")
		self.importStatusTemplate = _("Importing: %s %s events")
		self.updateTimer = eTimer()
		self.updateTimer.callback.append(self.updateStatus)
		self.updateTimer.start(1000)

	def updateStatus(self):
		text = ""
		global isFilterRunning, filterCounter
		if isFilterRunning == 1:
			text = self.filterStatusTemplate % (str(filterCounter))
			self.setFootnote(text)
		elif epgimport.isImportRunning():
			src = epgimport.source
			text = self.importStatusTemplate % (src.description, epgimport.eventCount)
			self.setFootnote(text)
			return
		if lastImportResult:  # and (lastImportResult != self.lastImportResult):
			start, count = lastImportResult
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
			last_import = f"{d} {t}, {count}"
			self.setFootnote(_("Last import: %s events") % last_import)
			self.lastImportResult = lastImportResult

	def keyInfo(self):
		last_import = config.plugins.extra_epgimport.last_import.value
		msg = _("Last import: %s events") % last_import
		self.session.open(
			MessageBox,
			msg,
			type=MessageBox.TYPE_INFO,
			timeout=10,
			close_on_any_key=True
		)

	def showLog(self):
		self.session.open(EPGImportLog)

	def openIgnoreList(self):
		self.session.open(filtersServices.filtersServicesSetup)

	def openMenu(self):
		menu = [(_("Show log"), self.showLog), (_("Ignore services list"), self.openIgnoreList)]
		text = _("Select action")

		def setAction(choice):
			if choice:
				choice[1]()
		self.session.openWithCallback(setAction, ChoiceBox, title=text, list=menu)

	def doimport(self, one_source=None):
		if epgimport.isImportRunning():
			print("[XMLTVImport] Already running, won't start again", file=log)
			msg = _("EPGImport\nImport of epg data is still in progress. Please wait.")
			self.session.open(
				MessageBox,
				msg,
				MessageBox.TYPE_ERROR,
				timeout=10,
				close_on_any_key=True
			)
			return

		if config.plugins.epgimport.import_onlybouquet.isChanged() or (autoStartTimer is not None and autoStartTimer.prev_multibouquet != config.usage.multibouquet.value):
			EPGConfig.channelCache = {}
		if one_source is None:
			cfg = EPGConfig.loadUserSettings()
		else:
			cfg = one_source
		sources = [s for s in EPGConfig.enumSources(CONFIG_PATH, filter=cfg["sources"])]
		if not sources:
			msg = _("No active EPG sources found, nothing to do")
			self.session.open(
				MessageBox,
				msg,
				type=MessageBox.TYPE_INFO,
				timeout=10,
				close_on_any_key=True
			)
			return
		# make it a stack, first on top.
		sources.reverse()
		epgimport.sources = sources
		msg = _("EPGImport\nImport of epg data will start.\nThis may take a few minutes.\nIs this ok?")
		self.session.openWithCallback(
			self.do_import_callback,
			MessageBox,
			msg,
			MessageBox.TYPE_YESNO,
			timeout=15,
			default=True
		)

	def do_import_callback(self, confirmed):
		if not confirmed:
			return
		try:
			startImport()
		except Exception as e:
			print(f"[XMLTVImport] Error at start:{e}", file=log)
			msg = _("EPGImport Plugin\nFailed to start:\n") + str(e)
			self.session.open(
				MessageBox,
				msg,
				MessageBox.TYPE_ERROR,
				timeout=15,
				close_on_any_key=True
			)

		self.updateStatus()

	def dosources(self):
		self.session.openWithCallback(self.sourcesDone, EPGImportSources)

	def sourcesDone(self, confirmed, sources, cfg):
		# Called with True and list of config items on Okay.
		print("sourcesDone(): ", confirmed, sources, file=log)
		if cfg is not None:
			self.doimport(one_source=cfg)

	def setFootnote(self, footnote):
		if footnote is None:
			self["footnote"].setText("")
			self["footnote"].hide()
		else:
			self["footnote"].setText(footnote)
			self["footnote"].setVisible(footnote != "")

	def keySave(self):
		self.updateTimer.stop()
		if config.plugins.epgimport.parse_autotimer.value and not isPluginInstalled("AutoTimer"):
			config.plugins.epgimport.parse_autotimer.value = False
		if config.plugins.epgimport.shutdown.value:
			config.plugins.epgimport.standby_afterwakeup.value = False
			config.plugins.epgimport.repeat_import.value = 0
		if config.plugins.epgimport.import_onlybouquet.isChanged() or (autoStartTimer is not None and autoStartTimer.prev_multibouquet != config.usage.multibouquet.value):
			EPGConfig.channelCache = {}
		Setup.keySave(self)

	def keySelect(self):
		if self.getCurrentItem() == config.plugins.epgimport.day_profile:
			self.session.open(EPGImportProfile)
		else:
			Setup.keySelect(self)

	def handleInputHelpers(self):
		Setup.handleInputHelpers(self)
		if "key_menu" in self:  # sanity for distros without key_menu in ConfigList
			self["key_menu"].setText(_("MENU"))  # force permanent display of key_menu


class EPGImportSources(Screen):
	"Pick sources from config"
	skin = """
		<screen name="EPGImportSources" position="center,center" size="560,400" resolution="1280,720" title="EPG Import Sources" >
			<widget name="key_red" render="Pixmap" position="0,0"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on"/>
			<widget name="key_green" render="Pixmap" position="140,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on"/>
			<widget name="key_yellow" render="Pixmap" position="280,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/yellow.png" transparent="1" alphatest="on">
				<convert type="ConditionalShowHide" />
			</widget>
			<widget name="key_blue" render="Pixmap" position="420,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/blue.png" transparent="1" alphatest="on">
				<convert type="ConditionalShowHide" />
			</widget>
			<widget source="key_red" render="Label" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget source="key_green" render="Label" position="140,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget source="key_yellow" render="Label" position="280,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget source="key_blue" render="Label" position="420,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<ePixmap alphatest="on" pixmap="skin_default/icons/clock.png" position="480,383" size="14,14" zPosition="3"/>
			<widget font="Regular;18" halign="left" position="505,380" render="Label" size="55,20" source="global.CurrentTime" transparent="1" valign="center" zPosition="3">
				<convert type="ClockToText">Default</convert>
			</widget>
			<widget name="list" position="10,40" size="540,336" scrollbarMode="showOnDemand" />
		</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Save"))
		self["key_yellow"] = StaticText(_("Import"))
		self["key_blue"] = StaticText(_("Update Sources"))
		self.tree = []
		self.giturl = SOURCE_LINKS.get(config.plugins.epgimport.extra_source.value)

		cfg = EPGConfig.loadUserSettings()
		filter = cfg["sources"]
		cat = None
		for x in EPGConfig.enumSources(CONFIG_PATH, filter=None, categories=True):
			if hasattr(x, "description"):
				sel = (filter is None) or (x.description in filter)
				entry = (x.description, x.description, sel)
				if cat is None:
					cat = ExpandableSelectionList.category("[.]")
					if not any(cat[0][0] == c[0][0] for c in self.tree):
						self.tree.append(cat)
				if not any(entry[0] == e[0] for e in cat[0][2]):
					cat[0][2].append(entry)
				if sel:
					ExpandableSelectionList.expand(cat, True)
			else:
				cat = ExpandableSelectionList.category(x)
				if not any(cat[0][0] == c[0][0] for c in self.tree):
					self.tree.append(cat)
		self["list"] = ExpandableSelectionList.ExpandableSelectionList(self.tree, enableWrapAround=True)
		self["key_yellow"].setText(_("Import") if self.tree else "")

		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"], {
			"red": self.cancel,
			"green": self.save,
			"yellow": self.do_import,
			"blue": self.git_import,
			"save": self.save,
			"cancel": self.cancel,
			"ok": self["list"].toggleSelection,
		}, -2)
		self.setTitle(_("EPG Import Sources"))

	def git_import(self):
		choiceList = [
			(_("No"), 0),
			(_("Yes"), 1),
			(_("Yes - and clear existing"), 2)
		]
		self.session.openWithCallback(self.install_update, MessageBox, text=_("Do you want to update Source now?\n\nWait for the import successful message!"), list=choiceList, timeout=15)

	def install_update(self, answer=False):
		if answer:
			try:
				from . import import_source
				import_source.main(self.giturl, removeExisting=answer == 2)
			except Exception as e:
				self.session.open(
					MessageBox,
					_("Import failed with error: {}").format(e),
					MessageBox.TYPE_ERROR,
					timeout=10,
					close_on_any_key=True
				)
				return

			self.refresh_tree()

	def refresh_tree(self):
		print("Refreshing tree...")
		cfg = EPGConfig.loadUserSettings()
		filter = cfg["sources"]
		self.tree = []
		cat = None
		for x in EPGConfig.enumSources(CONFIG_PATH, filter=None, categories=True):
			if hasattr(x, "description"):
				sel = (filter is None) or (x.description in filter)
				entry = (x.description, x.description, sel)
				if cat is None:
					cat = ExpandableSelectionList.category("[.]")
					self.tree.append(cat)
				cat[0][2].append(entry)
				if sel:
					ExpandableSelectionList.expand(cat, True)
			else:
				cat = ExpandableSelectionList.category(x)
				self.tree.append(cat)
		self["list"].setList(self.tree)
		# Show or hide the yellow key based on the tree content
		self["key_yellow"].setText(_("Import") if self.tree else "")
		# Set the updated tree in the list
		msg = _("Sources saved successfully!")
		self.session.open(
			MessageBox,
			msg,
			MessageBox.TYPE_INFO,
			timeout=10
		)
		self.cancel()

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


class EPGImportProfile(Setup):
	def __init__(self, session):
		Setup.__init__(self, session, "EPGImportProfile", plugin="Extensions/EPGImport", PluginLanguageDomain="EPGImport")
		self.setTitle(_("Days Profile"))
		self.skinName = "Setup"

	def createSetup(self, appendItems=None, prependItems=None):
		settingsList = []
		for i in range(7):
			settingsList.append(((weekdays[i], config.plugins.extra_epgimport.day_import[i])))
		self["config"].list = settingsList

	def keySave(self):
		if all(not config.plugins.extra_epgimport.day_import[i].value for i in range(7)):
			msg = _("You may not use this settings!\nAt least one day a week should be included!")
			self.session.open(
				MessageBox,
				msg,
				MessageBox.TYPE_INFO,
				timeout=10
			)
			return
		Setup.keySave(self)


class EPGImportLog(Screen):
	skin = """
		<screen position="center,center" size="560,400" resolution="1280,720" title="EPG Import Log" >
			<widget name="key_red" render="Pixmap" position="0,0"   zPosition="2" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on"/>
			<widget name="key_green" render="Pixmap" position="140,0" zPosition="2" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on"/>
			<widget source="key_red" render="Label" position="0,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
			<widget source="key_green" render="Label" position="140,0" size="140,40" valign="center" halign="center" zPosition="4"  foregroundColor="white" font="Regular;17" transparent="1" shadowColor="background" shadowOffset="-2,-2" />
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
		self["key_red"] = StaticText(_("Clear"))
		self["key_green"] = StaticText(_("Save"))
		self["list"] = ScrollLabel(self.log.getvalue())
		self["actions"] = ActionMap(["DirectionActions", "OkCancelActions", "ColorActions", "MenuActions"], {
			"red": self.clear,
			"green": self.cancel,
			"save": self.save,
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
			msg = _("Write to /tmp/epgimport.log")
			self.session.open(
				MessageBox,
				msg,
				MessageBox.TYPE_INFO,
				timeout=10
			)
		except Exception as e:
			self["list"].setText(f"Failed to write /tmp/epgimport.log:str{str(e)}")
		self.close(True)

	def cancel(self):
		self.close(False)

	def clear(self):
		self.log.logfile.seek(0)
		self.log.logfile.truncate(0)
		self.close(False)


def start_import(session, **kwargs):
	def msgClosed(ret):
		if ret:
			print("[XMLTVImport] Run manual starting import", file=log)
			autoStartTimer.runImport()
	if epgimport.isImportRunning():
		msg = _("EPGImport\nImport of epg data is still in progress. Please wait.")
		session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=10, close_on_any_key=True)
	else:
		msg = _("Last import: ") + config.plugins.extra_epgimport.last_import.value + _(" events\n") + _("\nImport of epg data will start.\nThis may take a few minutes.\nIs this ok?")
		session.openWithCallback(msgClosed, MessageBox, msg, MessageBox.TYPE_YESNO, timeout=15)


def main(session, **kwargs):
	session.openWithCallback(doneConfiguring, EPGImportConfig)


def doneConfiguring(*retVal):
	"""user has closed configuration, check new values...."""
	if autoStartTimer is not None:
		autoStartTimer.update()


def doneImport(reboot=False, epgfile=None):
	global _session, lastImportResult, BouquetChannelListList, serviceIgnoreList
	BouquetChannelListList = None
	serviceIgnoreList = None

	import logging
	# Configurazione base del logging
	logging.basicConfig(level=logging.DEBUG)
	if epgfile is None:
		logging.warning("EPG file not provided, proceeding without file.")
	else:
		logging.info(f"Import EPG file: {epgfile}")

	timestamp = time()
	formatted_time = strftime("%Y-%m-%d %H:%M:%S", localtime(timestamp))
	# Log dei risultati dell'importazione
	logging.info(f"Import completed at {formatted_time}")
	lastImportResult = (formatted_time, epgimport.eventCount)
	try:
		if lastImportResult:  # and (lastImportResult != lastImportResult):
			print(f"doneImport lastimport== {lastImportResult}")
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
			_session.openWithCallback(
				restartEnigma,
				MessageBox,
				msg,
				MessageBox.TYPE_YESNO,
				timeout=15,
				default=True
			)
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
			open(STANDBY_FLAG_FILE, "wb").close()
		except:
			print(f"Failed to create {STANDBY_FLAG_FILE}", file=log)
	else:
		try:
			remove(STANDBY_FLAG_FILE)
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
		self.onceRepeatImport = eTimer()
		self.onceRepeatImport.callback.append(self.runImport)
		self.pauseAfterFinishImportCheck = eTimer()
		self.pauseAfterFinishImportCheck.callback.append(self.afterFinishImportCheck)
		self.pauseAfterFinishImportCheck.startLongTimer(30)
		config.misc.standbyCounter.addNotifier(self.standbyCounterChangedRunImport)
		self.update()

	def getWakeTime(self):
		if config.plugins.epgimport.enabled.value:
			nowt = time()
			now = localtime(nowt)
			return int(mktime((now.tm_year, now.tm_mon, now.tm_mday, self.clock[0], self.clock[1], lastMACbyte() // 5, 0, now.tm_yday, now.tm_isdst)))
		else:
			return -1

	def update(self, atLeast=0, clock=False):
		self.autoStartImport.stop()
		if clock and self.clock != config.plugins.epgimport.wakeup.value:
			self.clock = config.plugins.epgimport.wakeup.value
			self.onceRepeatImport.stop()
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
			self.onceRepeatImport.stop()
			wake = -1
		now_str = strftime("%Y-%m-%d %H:%M:%S", localtime(now))
		wake_str = strftime("%Y-%m-%d %H:%M:%S", localtime(wake)) if wake > 0 else "Not set"
		print(f"[XMLTVImport] WakeUpTime now set to {wake_str} (now={now_str})", file=log)
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
		else:
			self.session.open(
				MessageBox,
				_("No source file found !"),
				MessageBox.TYPE_INFO,
				timeout=10
			)

	def onTimer(self):
		self.autoStartImport.stop()
		now = int(time())
		print(f"[XMLTVImport] onTimer occured at {now}", file=log)
		wake = self.getWakeTime()
		# If we're close enough, we're okay...
		atLeast = 0
		if wake - now < 60:
			self.runImport()
			repeat_time = config.plugins.epgimport.repeat_import.value
			if repeat_time:
				self.onceRepeatImport.startLongTimer(repeat_time * 3600)
				print(f"[EPGImport] start once repeat timer, wait in hours - {repeat_time}", file=log)
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
			if exists(STANDBY_FLAG_FILE) or exists(ANSWER_BOOT_FILE):
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

	def afterStandbyRunImport(self):
		if config.plugins.epgimport.run_after_standby.value:
			print("[EPGImport] start import after standby", file=log)
			self.runImport()

	def standbyCounterChangedRunImport(self, configElement):
		if Screens.Standby.inStandby:
			try:
				if self.afterStandbyRunImport not in Screens.Standby.inStandby.onClose:
					Screens.Standby.inStandby.onClose.append(self.afterStandbyRunImport)
			except:
				print("[EPGImport] error inStandby.onClose append afterStandbyRunImport", file=log)

	def startStandby(self):
		if Screens.Standby.inStandby:
			print("[XMLTVImport] add checking standby", file=log)
			try:
				if self.onLeaveStandby not in Screens.Standby.inStandby.onClose:
					Screens.Standby.inStandby.onClose.append(self.onLeaveStandby)
			except:
				print("[EPGImport] error inStandby.onClose append .onLeaveStandby", file=log)

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
		if runboot == 1:
			on_start = True
			print("[XMLTVImport] is boot", file=log)
		elif runboot == 2 and not getFPWasTimerWakeup():
			on_start = True
			print("[XMLTVImport] is manual boot", file=log)
		elif runboot == 3 and getFPWasTimerWakeup():
			on_start = True
			print("[XMLTVImport] is automatic boot", file=log)
		if config.plugins.epgimport.runboot_restart.value and runboot != 3:
			if exists(ANSWER_BOOT_FILE):
				on_start = False
				print("[XMLTVImport] not starting import - is restart enigma2", file=log)
			else:
				try:
					open(ANSWER_BOOT_FILE, "wb").close()
				except:
					print(f"Failed to create {ANSWER_BOOT_FILE}", file=log)
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
	if reason == 0:  # and _session is None:
		if session is not None:
			_session = session
			if autoStartTimer is None:
				autoStartTimer = AutoStartTimer(session)
			if config.plugins.epgimport.runboot.value != 4:
				onBootStartCheck()
		# If WE caused the reboot, put the box back in standby.
		if exists(STANDBY_FLAG_FILE):
			print("[XMLTVImport] Returning to standby", file=log)
			if not Screens.Standby.inStandby:
				Notifications.AddNotification(Screens.Standby.Standby)
			try:
				remove(STANDBY_FLAG_FILE)
			except:
				pass

		sourcesFile = "/etc/epgimport.tar.gz"
		if not exists(CONFIG_PATH):
			makedirs(CONFIG_PATH)

		if exists(sourcesFile):
			try:
				import tarfile
				with tarfile.open(sourcesFile, 'r:gz') as tar:
					tar.extractall(path=CONFIG_PATH)
				remove(sourcesFile)
			except Exception as e:
				print(f"[XMLTVImport] Error extract sources {e}", file=log)

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
			where=PluginDescriptor.WHERE_SESSIONSTART,
#			where=[
#				PluginDescriptor.WHERE_AUTOSTART,
#				PluginDescriptor.WHERE_SESSIONSTART
#			],
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
