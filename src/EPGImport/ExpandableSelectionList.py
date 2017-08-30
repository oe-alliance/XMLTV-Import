from Components.MenuList import MenuList
from Tools.Directories import resolveFilename, SCOPE_CURRENT_SKIN
from enigma import eListboxPythonMultiContent, eListbox, gFont, RT_HALIGN_LEFT
from Tools.LoadPixmap import LoadPixmap

from boxbranding import getImageDistro
if getImageDistro() in ('openatv', 'openbh', 'openhdf'):
	from Components.SelectionList import selectiononpng
	selectionpng = selectiononpng
else:
	from Components.SelectionList import selectionpng

import skin


expandableIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/expandable.png"))
expandedIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/expanded.png"))

def loadSettings():
	global cat_desc_loc, entry_desc_loc, cat_icon_loc, entry_icon_loc
	x, y, w, h = skin.parameters.get("SelectionListDescr", (25, 3, 650, 30))
	ind = x # Indent the entries by the same amount as the icon.
	cat_desc_loc = (x, y, w, h)
	entry_desc_loc = (x + ind, y, w - ind, h)
	x, y, w, h = skin.parameters.get("SelectionListLock", (0, 2, 25, 24))
	cat_icon_loc = (x, 0, w, y + y + h) # The category icon is larger
	entry_icon_loc = (x + ind, y, w, h)

def category(description, isExpanded=False):
	global cat_desc_loc, cat_icon_loc
	if isExpanded:
		icon = expandedIcon
	else:
		icon = expandableIcon
	return [
		(description, isExpanded, []),
		(eListboxPythonMultiContent.TYPE_TEXT,) + cat_desc_loc + (0, RT_HALIGN_LEFT, description),
		(eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST,) + cat_icon_loc + (icon,)
	]

def entry(description, value, selected):
	global entry_desc_loc, entry_icon_loc
	res = [
		(description, value, selected),
		(eListboxPythonMultiContent.TYPE_TEXT,) + entry_desc_loc + (0, RT_HALIGN_LEFT, description)
	]
	if selected:
		res.append((eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST,) + entry_icon_loc + (selectionpng,))
	return res

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
		cat[2] = (eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST,) + cat_icon_loc + (icon,)

def isExpanded(cat):
	return cat[0][1]

def isCategory(item):
	# Return whether list enty is a Category
	return hasattr(item[0][2], 'append')

class ExpandableSelectionList(MenuList):
	def __init__(self, tree = None, enableWrapAround = False):
		'tree is expected to be a list of categories'
		MenuList.__init__(self, [], enableWrapAround, content = eListboxPythonMultiContent)
		font = skin.fonts.get("SelectionList", ("Regular", 20, 30))
		self.l.setFont(0, gFont(font[0], font[1]))
		self.l.setItemHeight(font[2])
		self.tree = tree or []
		self.updateFlatList()

	def updateFlatList(self):
		# Update the view of the items by flattening the tree
		l = []
		for cat in self.tree:
			l.append(cat)
			if isExpanded(cat):
				for item in cat[0][2]:
					l.append(entry(*item))
		self.setList(l)

	def toggleSelection(self):
		idx = self.getSelectedIndex()
		item = self.list[idx]
		# Only toggle selections, not expandables...
		if isCategory(item):
			expand(item, not item[0][1])
			self.updateFlatList()
		else:
			# Multiple items may have the same key. Toggle them all,
			# in both the visual list and the hidden items
			i = item[0]
			key = i[1]
			sel = not i[2]
			for idx, e in enumerate(self.list):
				if e[0][1] == key:
					self.list[idx] = entry(e[0][0], key, sel)
			for cat in self.tree:
				for idx, e in enumerate(cat[0][2]):
					if e[1] == key and e[2] != sel:
						cat[0][2][idx] = (e[0], e[1], sel)
			self.setList(self.list)

	def enumSelected(self):
		for cat in self.tree:
			for entry in cat[0][2]:
				if entry[2]:
					yield entry

loadSettings()
