from __future__ import absolute_import
from __future__ import print_function
from . import xmltvconverter

date_format = '%Y%m%d%H%M%S'
gen_categories = {
'Talk': (0x00, 0),
'Animated': (0x55, 0),
'Comedy': (0x14, 0),
'Documentary': (0x23, 0),
'Educational': (0x90, 0),
'Film': (0x10, 0),
'Children': (0x50, 0),
'Arts/Culture': (0x70, 0),
'Crime/Mystery': (0x10, 85),
'Music': (0x60, 0),
'Science/Nature': (0x91, 0),
'News': (0x20, 0),
'Unknown': (0x00, 0),
'Religion': (0x73, 0),
'Drama': (0x15, 0),
'Sports': (0x40, 0),
'Science/Nature': (0x90, 0)
}


def new():
	'Factory method to return main class instance'
	return Gen_Xmltv()

class Gen_Xmltv():
	def iterator(self, fd, channelsDict):
		try:
			xmltv_parser = xmltvconverter.XMLTVConverter(channelsDict, gen_categories, date_format)
			for r in xmltv_parser.enumFile(fd):
				yield r
		except Exception as e:
			print("[gen_xmltv] Error:", e)
			import traceback
			traceback.print_exc()

