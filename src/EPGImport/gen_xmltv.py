from . import xmltvconverter

date_format = "%Y%m%d%H%M%S"

""" New category add from Lululla """
gen_categories = {
	"Action sports": 0x40,
	"Action": 0x10,
	"Adult Movie/Drama": 0x18,
	"Adults only": 0x18,
	"Adventure/Western/War": 0x12,
	"Advertisement/Shopping": 0xA6,
	"Aerobics": 0xA4,
	"Animated": (0x55, 0),
	"Archery": 0x46,
	"Arts/Culture": 0x70,
	"Athletics": 0x46,
	"Ballet": 0x66,
	"Baseball": 0x45,
	"Basketball": 0x45,
	"Bicycle": 0x40,
	"Billiards": 0x40,
	"Black & White": 0xB2,
	"Boxing": 0x40,
	"Broadcasting/Press": 0x78,
	"Cartoons/Puppets": 0x55,
	"Children's/Youth Programme": 0x50,
	"Comedy": 0x14,
	"Comedy-drama": 0x14,
	"Cooking": 0xA5,
	"Crime drama": 0x10,
	"Crime/Mystery": (0x10, 85),
	"Detective/Thriller": 0x11,
	"Discussion/Interview/Debate": 0x24,
	"Documentary": (0x23, 0),
	"Drama": 0x10,
	"Economics/Social Advisory": 0x82,
	"Education/Science/Factual": 0x90,
	"Educational": (0x90, 0),
	"Entertainment Programme for 10 to 16": 0x53,
	"Entertainment Programme for 6 to 14": 0x52,
	"Equestrian": 0x4A,
	"Experimental Film/Video": 0x77,
	"Fashion": 0x7B,
	"Film": (0x10, 0),
	"Film/Cinema": 0x76,
	"Fine Arts": 0x72,
	"Fitness & Health": 0xA4,
	"Folk/Traditional Music": 0x63,
	"Football/Soccer": 0x43,
	"Foreign Countries/Expeditions": 0x94,
	"Further Education": 0x96,
	"Game Show/Quiz/Contest": 0x31,
	"Gardening": 0xA7,
	"Handicraft": 0xA2,
	"Hobbies": (0x30, 0),
	"Informational/Educational/School Programme": 0x54,
	"Jazz": 0x64,
	"Languages": 0x97,
	"Leisure/Hobbies": 0xA0,
	"Literature": 0x75,
	"Live Broadcast": 0xB4,
	"Magazine/Report/Documentary": 0x81,
	"Martial Sports": 0x4B,
	"Medicine/Physiology/Psychology": 0x93,
	"Motor Sport": 0x47,
	"Motoring": 0xA3,
	"Movie/Drama": 0x10,
	"Music": (0x60, 0),
	"Music/Ballet/Dance": 0x60,
	"Musical/Opera": 0x65,
	"Nature/Animals/Environment": 0x91,
	"New Media": 0x79,
	"News Magazine": 0x22,
	"News": 0x20,
	"News/Current Affairs": 0x20,
	"News/Weather Report": 0x21,
	"Original Language": 0xB1,
	"Paid Programming": 0x54,
	"Performing Arts": 0x71,
	"Popular Culture/Traditional Arts": 0x74,
	"Pre-school Children's Programme": 0x51,
	"Reality": (0x34, 0),
	"Religion": 0x73,
	"Religious": 0x73,
	"Remarkable People": 0x83,
	"Rock/Pop": 0x61,
	"Romance": 0x16,
	"Science Fiction/Fantasy/Horror": 0x13,
	"Science/Nature": (0x90, 0),
	"Serious/Classical Music": 0x62,
	"Serious/Classical/Religious/Historical Movie/Drama": 0x17,
	"Show/Game Show": 0x30,
	"Soap": 0x15,
	"Soap/Melodrama/Folkloric": 0x15,
	"Social/Political/Economics": 0x80,
	"Social/Spiritual Sciences": 0x95,
	"Special Event": 0x41,
	"Sport Magazine": 0x42,
	"Sports": 0x40,
	"Standup": 0x14,
	"Talk Show": 0x33,
	"Talk": 0x33,
	"Team Sports": 0x45,
	"Technology/Natural Sciences": 0x92,
	"Tennis/Squash": 0x44,
	"Tourism/Travel": 0xA1,
	"Unknown": (0x00, 0),
	"Unpublished": 0xB3,
	"Variety Show": 0x32,
	"Water Sport": 0x48,
	"Weather": 0x21,
	"Winter Sports": 0x49,
}


def new():
	"""Factory method to return main class instance"""
	return Gen_Xmltv()


class Gen_Xmltv():

	def iterator(self, fd, channelsDict, offset=0):
		try:
			if not isinstance(channelsDict, dict):
				raise ValueError("channelsDict must be a dictionary")
			xmltv_parser = xmltvconverter.XMLTVConverter(channelsDict, gen_categories, date_format, offset)
			for r in xmltv_parser.enumFile(fd):
				yield r
		except Exception as e:
			print("[gen_xmltv] Error:", e)
			import traceback
			traceback.print_exc()
