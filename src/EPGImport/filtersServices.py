from . import _
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.ChoiceBox import ChoiceBox
from Components.ActionMap import ActionMap
from ServiceReference import ServiceReference
from Screens.ChannelSelection import service_types_radio, service_types_tv, ChannelSelectionBase
from enigma import eServiceReference, eServiceCenter
from Components.Sources.List import List
from Components.Label import Label
from os.path import isdir
from os import system
from . import EPGConfig


OFF = 0
EDIT_BOUQUET = 1
EDIT_ALTERNATIVES = 2


def getProviderName(ref):
	typestr = ref.getData(0) in (2, 10) and service_types_radio or service_types_tv
	pos = typestr.rfind(":")
	rootstr = "%s (channelID == %08x%04x%04x) && %s FROM PROVIDERS ORDER BY name" % (typestr[:pos + 1], ref.getUnsignedData(4), ref.getUnsignedData(2), ref.getUnsignedData(3), typestr[pos + 1:])
	provider_root = eServiceReference(rootstr)
	serviceHandler = eServiceCenter.getInstance()
	providerlist = serviceHandler.list(provider_root)
	if providerlist is not None:
		while True:
			provider = providerlist.getNext()
			if not provider.valid():
				break
			if provider.flags & eServiceReference.isDirectory:
				servicelist = serviceHandler.list(provider)
				if servicelist is not None:
					while True:
						service = servicelist.getNext()
						if not service.valid():
							break
						if service == ref:
							info = serviceHandler.info(provider)
							return info and info.getName(provider) or "Unknown"
	return ""


class FiltersList():
	def __init__(self):
		self.services = []
		self.load()

	def loadFrom(self, filename):
		try:
			with open(filename, "r") as cfg:
				for line in cfg:
					if line[0] in "#;\n":
						continue
					ref = line.strip()
					if ref not in self.services:
						self.services.append(ref)
		except Exception as e:
			print(f"Error loading from {filename}: {e}")

	def saveTo(self, filename):
		try:
			if not isdir("/etc/epgimport"):
				system("mkdir /etc/epgimport")
			cfg = open(filename, "w")
		except:
			return
		for ref in self.services:
			cfg.write("%s\n" % (ref))
		cfg.close()

	def load(self):
		self.loadFrom("/etc/epgimport/ignore.conf")

	def reload_module(self):
		self.services = []
		self.load()

	def servicesList(self):
		return self.services

	def save(self):
		self.saveTo("/etc/epgimport/ignore.conf")

	def addService(self, ref):
		if isinstance(ref, str) and ref not in self.services:
			self.services.append(ref)

	def addServices(self, services):
		if isinstance(services, list):
			for s in services:
				if s not in self.services:
					self.services.append(s)

	def delService(self, ref):
		if isinstance(ref, str) and ref in self.services:
			self.services.remove(ref)

	def delAll(self):
		self.services = []
		self.save()


filtersServicesList = FiltersList()


class filtersServicesSetup(Screen):
	skin = """
	<screen name="filtersServicesSetup" position="center,center" size="680,470" title="Ignore services list">
		<ePixmap position="0,390" size="140,40" pixmap="skin_default/buttons/red.png" alphatest="on" />
		<ePixmap position="170,390"  size="140,40" pixmap="skin_default/buttons/green.png"  alphatest="on" />
		<ePixmap position="340,390" size="140,40" pixmap="skin_default/buttons/yellow.png" alphatest="on" />
		<ePixmap position="510,390" size="140,40" pixmap="skin_default/buttons/blue.png" alphatest="on" />
		<widget name="key_red" position="0,390" zPosition="1" size="140,40" font="Regular;17" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" />
		<widget name="key_green" position="170,390" zPosition="1" size="140,40" font="Regular;17" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" />
		<widget name="key_yellow" position="340,390" zPosition="1" size="140,40" font="Regular;17" halign="center" valign="center" backgroundColor="#a08500" transparent="1" />
		<widget name="key_blue" position="510,390" zPosition="1" size="140,40" font="Regular;17" halign="center" valign="center" backgroundColor="#18188b" transparent="1" />
		<widget source="list" render="Listbox" position="10,10" size="660,330" scrollbarMode="showOnDemand">
			<convert type="TemplatedMultiContent">
				{"template": [
						MultiContentEntryText(pos = (10, 5), size = (420, 23), font = 0, flags = RT_HALIGN_LEFT, text = 0),
						MultiContentEntryText(pos = (50, 25), size = (380, 20), font = 1, flags = RT_HALIGN_LEFT, text = 1),
						MultiContentEntryText(pos = (100, 47), size = (400, 17), font = 2, flags = RT_HALIGN_LEFT, text = 2),
					],
				"fonts": [gFont("Regular", 21), gFont("Regular", 19), gFont("Regular", 16)],
				"itemHeight": 65
				}
			</convert>
		</widget>
		<widget name="introduction" position="0,440" size="680,30" font="Regular;20" halign="center" valign="center" />
	</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.RefList = filtersServicesList
		self.prev_list = self.RefList.services[:]

		self["list"] = List([])
		self.updateList()

		self["key_red"] = Label(" ")
		self["key_green"] = Label(_("Add Provider"))
		self["key_yellow"] = Label(_("Add Channel"))
		self["key_blue"] = Label(" ")
		self["introduction"] = Label(_("press OK to save list"))
		self.updateButtons()

		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"],
			{
				"cancel": self.exit,
				"ok": self.keyOk,
				"red": self.keyRed,
				"green": self.keyGreen,
				"yellow": self.keyYellow,
				"blue": self.keyBlue
			},
			-1
		)
		self.setTitle(_("Ignore services list"))

	def keyRed(self):
		cur = self["list"].getCurrent()
		if cur and len(cur) > 2:
			self.RefList.delService(cur[2])
			self.updateList()
			self.updateButtons()

	def keyGreen(self):
		self.session.openWithCallback(self.addServiceCallback, filtersServicesSelection, providers=True)

	def keyYellow(self):
		self.session.openWithCallback(self.addServiceCallback, filtersServicesSelection)

	def addServiceCallback(self, *service):
		if service:
			ref = service[0]
			if isinstance(ref, list):
				self.RefList.addServices(ref)
			else:
				refstr = ":".join(ref.toString().split(":")[:11])
				if any(x in refstr for x in ("1:0:", "4097:0:", "5001:0:", "5002:0:")):
					self.RefList.addService(refstr)
			self.updateList()
			self.updateButtons()

	def keyBlue(self):
		if len(self.list):
			self.session.openWithCallback(self.removeCallback, MessageBox, _("Really delete all list?"), MessageBox.TYPE_YESNO)

	def removeCallback(self, answer):
		if answer:
			self.RefList.delAll()
			self.updateList()
			self.updateButtons()
			self.prev_list = self.RefList.services[:]

	def keyOk(self):
		self.RefList.save()
		if self.RefList.services != self.prev_list:
			self.RefList.reload_module()
			EPGConfig.channelCache = {}
		self.close()

	def exit(self):
		self.RefList.services = self.prev_list
		self.RefList.save()
		self.close()

	def updateList(self):
		self.list = []
		for service in self.RefList.servicesList():
			if any(x in service for x in ("1:0:", "4097:0:", "5001:0:", "5002:0:")):
				provname = getProviderName(eServiceReference(service))
				servname = ServiceReference(service).getServiceName() or "N/A"
				self.list.append((servname, provname, service))
		self["list"].setList(self.list)
		self["list"].updateList(self.list)

	def updateButtons(self):
		if len(self.list):
			self["key_red"].setText(_("Delete selected"))
			self["key_blue"].setText(_("Delete all"))
		else:
			self["key_red"].setText(" ")
			self["key_blue"].setText(" ")


class filtersServicesSelection(ChannelSelectionBase):
	skin = """
	<screen position="center,center" size="560,430" title="Select service to add...">
		<ePixmap pixmap="skin_default/buttons/red.png" position="0,0" size="140,40" alphatest="on" />
		<ePixmap pixmap="skin_default/buttons/green.png" position="140,0" size="140,40" alphatest="on" />
		<ePixmap pixmap="skin_default/buttons/yellow.png" position="280,0" size="140,40" alphatest="on" />
		<ePixmap pixmap="skin_default/buttons/blue.png" position="420,0" size="140,40" alphatest="on" />
		<widget name="key_red" position="0,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" />
		<widget name="key_green" position="140,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" />
		<widget name="key_yellow" position="280,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#a08500" transparent="1" />
		<widget name="key_blue" position="420,0" zPosition="1" size="140,40" font="Regular;20" halign="center" valign="center" backgroundColor="#18188b" transparent="1" />
		<widget name="list" position="00,45" size="560,364" scrollbarMode="showOnDemand" />
	</screen>
	"""

	def __init__(self, session, providers=False):
		self.providers = providers
		ChannelSelectionBase.__init__(self, session)
		self.bouquet_mark_edit = OFF
		self.setTitle(_("Select service to add..."))
		self["actions"] = ActionMap(["OkCancelActions", "TvRadioActions"], {"cancel": self.close, "ok": self.channelSelected, "keyRadio": self.setModeRadio, "keyTV": self.setModeTv})
		self.onLayoutFinish.append(self.setModeTv)

	def channelSelected(self):
		ref = self.getCurrentSelection()
		if self.providers and (ref.flags & 7) == 7:
			if "provider" in ref.toString():
				menu = [(_("All services provider"), "providerlist")]

				def addAction(choice):
					if choice is not None:
						if choice[1] == "providerlist":
							serviceHandler = eServiceCenter.getInstance()
							servicelist = serviceHandler.list(ref)
							if servicelist is not None:
								providerlist = []
								while True:
									service = servicelist.getNext()
									if not service.valid():
										break
									refstr = ":".join(service.toString().split(":")[:11])
									providerlist.append((refstr))
								if providerlist:
									self.close(providerlist)
								else:
									self.close(None)
				self.session.openWithCallback(addAction, ChoiceBox, title=_("Select action"), list=menu)
			else:
				self.enterPath(ref)
		elif (ref.flags & 7) == 7:
			self.enterPath(ref)
		elif "provider" not in ref.toString() and not self.providers and not (ref.flags & (64 | 128)) and "%3a//" not in ref.toString():
			if ref.valid():
				self.close(ref)

	def setModeTv(self):
		self.setTvMode()
		if self.providers:
			self.showProviders()
		else:
			self.showFavourites()

	def setModeRadio(self):
		self.setRadioMode()
		if self.providers:
			self.showProviders()
		else:
			self.showFavourites()
