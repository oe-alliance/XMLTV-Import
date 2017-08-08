from Components.SelectionList import SelectionList, SelectionEntryComponent
from Tools.Directories import resolveFilename, SCOPE_CURRENT_SKIN
from enigma import eListboxPythonMultiContent, eListbox, gFont, RT_HALIGN_LEFT
from Tools.LoadPixmap import LoadPixmap
import skin

expandableIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/expandable.png"))
expandedIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/expanded.png"))

def CategoryEntryComponent(description, isExpanded=False, children=[]):
	dx, dy, dw, dh = skin.parameters.get("SelectionListDescr",(25, 3, 650, 30))
	ix, iy, iw, ih = skin.parameters.get("SelectionListLock",(0, 2, 25, 24))
	if isExpanded:
		icon = expandedIcon
	else:
		icon = expandableIcon
	return [
		(description, isExpanded, children),
		(eListboxPythonMultiContent.TYPE_TEXT, dx, dy, dw, dh, 0, RT_HALIGN_LEFT, description),
		(eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST, ix, iy, iw, ih, icon)
	]

def expand(cat, value=True):
	# cat is a list of data and icons
	if cat[0][1] != value:
		ix, iy, iw, ih = skin.parameters.get("SelectionListLock",(0, 2, 25, 24))
		if value:
			icon = expandedIcon
		else:
			icon = expandableIcon
		t = cat[0]
		cat[0] = (t[0], value, t[2])
		cat[2] = (eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST, ix, iy, iw, ih, icon)

class ExpandableSelectionList(SelectionList):
	def toggleSelection(self):
		idx = self.getSelectedIndex()
		item = self.list[idx][0]
		# Only toggle selections, not expandables...
		if len(item) == 4:
			self.list[idx] = SelectionEntryComponent(item[0], item[1], item[2], not item[3])
		else:
			expand(self.list[idx], not item[1])
		self.setList(self.list)

	def getSelectionsList(self):
		return [ (item[0][0], item[0][1], item[0][2]) for item in self.list if (len(item[0]) == 4) and item[0][3] ]

	def toggleAllSelection(self):
		for idx,item in enumerate(self.list):
			item = self.list[idx][0]
			if len(item) == 4:
				self.list[idx] = SelectionEntryComponent(item[0], item[1], item[2], not item[3])
		self.setList(self.list)

	def sort(self, sortType=False, flag=False):
		# Cannot sort this list
		pass
