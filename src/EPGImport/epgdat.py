#!/usr/bin/python
# epgdat.py  by Ambrosa http://www.dreamboxonline.com
# Heavily modified by MiLo http://www.sat4all.com/
# Lots of stuff removed that i did not need.

import os
import sys
import codecs
import struct
from datetime import datetime

try:
	import dreamcrc
	crc32_dreambox = lambda d, t: dreamcrc.crc32(d, t) & 0xffffffff
	print "[EPGImport] using C module, yay"
except:
	print "[EPGImport] failed to load C implementation, sorry"

	# this table is used by CRC32 routine below (used by Dreambox for
	# computing REF DESC value).
	# The original DM routine is a modified CRC32 standard routine,
	# so cannot use Python standard binascii.crc32()
	CRCTABLE = (
		0x00000000, 0x04C11DB7, 0x09823B6E, 0x0D4326D9,
		0x130476DC, 0x17C56B6B, 0x1A864DB2, 0x1E475005,
		0x2608EDB8, 0x22C9F00F, 0x2F8AD6D6, 0x2B4BCB61,
		0x350C9B64, 0x31CD86D3, 0x3C8EA00A, 0x384FBDBD,
		0x4C11DB70, 0x48D0C6C7, 0x4593E01E, 0x4152FDA9,
		0x5F15ADAC, 0x5BD4B01B, 0x569796C2, 0x52568B75,
		0x6A1936C8, 0x6ED82B7F, 0x639B0DA6, 0x675A1011,
		0x791D4014, 0x7DDC5DA3, 0x709F7B7A, 0x745E66CD,
		0x9823B6E0, 0x9CE2AB57, 0x91A18D8E, 0x95609039,
		0x8B27C03C, 0x8FE6DD8B, 0x82A5FB52, 0x8664E6E5,
		0xBE2B5B58, 0xBAEA46EF, 0xB7A96036, 0xB3687D81,
		0xAD2F2D84, 0xA9EE3033, 0xA4AD16EA, 0xA06C0B5D,
		0xD4326D90, 0xD0F37027, 0xDDB056FE, 0xD9714B49,
		0xC7361B4C, 0xC3F706FB, 0xCEB42022, 0xCA753D95,
		0xF23A8028, 0xF6FB9D9F, 0xFBB8BB46, 0xFF79A6F1,
		0xE13EF6F4, 0xE5FFEB43, 0xE8BCCD9A, 0xEC7DD02D,
		0x34867077, 0x30476DC0, 0x3D044B19, 0x39C556AE,
		0x278206AB, 0x23431B1C, 0x2E003DC5, 0x2AC12072,
		0x128E9DCF, 0x164F8078, 0x1B0CA6A1, 0x1FCDBB16,
		0x018AEB13, 0x054BF6A4, 0x0808D07D, 0x0CC9CDCA,
		0x7897AB07, 0x7C56B6B0, 0x71159069, 0x75D48DDE,
		0x6B93DDDB, 0x6F52C06C, 0x6211E6B5, 0x66D0FB02,
		0x5E9F46BF, 0x5A5E5B08, 0x571D7DD1, 0x53DC6066,
		0x4D9B3063, 0x495A2DD4, 0x44190B0D, 0x40D816BA,
		0xACA5C697, 0xA864DB20, 0xA527FDF9, 0xA1E6E04E,
		0xBFA1B04B, 0xBB60ADFC, 0xB6238B25, 0xB2E29692,
		0x8AAD2B2F, 0x8E6C3698, 0x832F1041, 0x87EE0DF6,
		0x99A95DF3, 0x9D684044, 0x902B669D, 0x94EA7B2A,
		0xE0B41DE7, 0xE4750050, 0xE9362689, 0xEDF73B3E,
		0xF3B06B3B, 0xF771768C, 0xFA325055, 0xFEF34DE2,
		0xC6BCF05F, 0xC27DEDE8, 0xCF3ECB31, 0xCBFFD686,
		0xD5B88683, 0xD1799B34, 0xDC3ABDED, 0xD8FBA05A,
		0x690CE0EE, 0x6DCDFD59, 0x608EDB80, 0x644FC637,
		0x7A089632, 0x7EC98B85, 0x738AAD5C, 0x774BB0EB,
		0x4F040D56, 0x4BC510E1, 0x46863638, 0x42472B8F,
		0x5C007B8A, 0x58C1663D, 0x558240E4, 0x51435D53,
		0x251D3B9E, 0x21DC2629, 0x2C9F00F0, 0x285E1D47,
		0x36194D42, 0x32D850F5, 0x3F9B762C, 0x3B5A6B9B,
		0x0315D626, 0x07D4CB91, 0x0A97ED48, 0x0E56F0FF,
		0x1011A0FA, 0x14D0BD4D, 0x19939B94, 0x1D528623,
		0xF12F560E, 0xF5EE4BB9, 0xF8AD6D60, 0xFC6C70D7,
		0xE22B20D2, 0xE6EA3D65, 0xEBA91BBC, 0xEF68060B,
		0xD727BBB6, 0xD3E6A601, 0xDEA580D8, 0xDA649D6F,
		0xC423CD6A, 0xC0E2D0DD, 0xCDA1F604, 0xC960EBB3,
		0xBD3E8D7E, 0xB9FF90C9, 0xB4BCB610, 0xB07DABA7,
		0xAE3AFBA2, 0xAAFBE615, 0xA7B8C0CC, 0xA379DD7B,
		0x9B3660C6, 0x9FF77D71, 0x92B45BA8, 0x9675461F,
		0x8832161A, 0x8CF30BAD, 0x81B02D74, 0x857130C3,
		0x5D8A9099, 0x594B8D2E, 0x5408ABF7, 0x50C9B640,
		0x4E8EE645, 0x4A4FFBF2, 0x470CDD2B, 0x43CDC09C,
		0x7B827D21, 0x7F436096, 0x7200464F, 0x76C15BF8,
		0x68860BFD, 0x6C47164A, 0x61043093, 0x65C52D24,
		0x119B4BE9, 0x155A565E, 0x18197087, 0x1CD86D30,
		0x029F3D35, 0x065E2082, 0x0B1D065B, 0x0FDC1BEC,
		0x3793A651, 0x3352BBE6, 0x3E119D3F, 0x3AD08088,
		0x2497D08D, 0x2056CD3A, 0x2D15EBE3, 0x29D4F654,
		0xC5A92679, 0xC1683BCE, 0xCC2B1D17, 0xC8EA00A0,
		0xD6AD50A5, 0xD26C4D12, 0xDF2F6BCB, 0xDBEE767C,
		0xE3A1CBC1, 0xE760D676, 0xEA23F0AF, 0xEEE2ED18,
		0xF0A5BD1D, 0xF464A0AA, 0xF9278673, 0xFDE69BC4,
		0x89B8FD09, 0x8D79E0BE, 0x803AC667, 0x84FBDBD0,
		0x9ABC8BD5, 0x9E7D9662, 0x933EB0BB, 0x97FFAD0C,
		0xAFB010B1, 0xAB710D06, 0xA6322BDF, 0xA2F33668,
		0xBCB4666D, 0xB8757BDA, 0xB5365D03, 0xB1F740B4
	)
	# CRC32 in Dreambox/DVB way (see CRCTABLE comment above)
	# "crcdata" is the description string
	# "crctype" is the description type (1 byte 0x4d or 0x4e)
	# !!!!!!!!! IT'S VERY TIME CONSUMING !!!!!!!!!

	def crc32_dreambox(crcdata, crctype, crctable=CRCTABLE):
		# ML Optimized: local CRCTABLE (locals are faster), remove self, remove code that has no effect, faster loop
		#crc=0x00000000L
		#crc=((crc << 8 ) & 0xffffff00L) ^ crctable[((crc >> 24) ^ crctype) & 0x000000ffL ]
		crc = crctable[crctype & 0x000000ffL]
		crc = ((crc << 8) & 0xffffff00L) ^ crctable[((crc >> 24) ^ len(crcdata)) & 0x000000ffL]
		for d in crcdata:
		    crc = ((crc << 8) & 0xffffff00L) ^ crctable[((crc >> 24) ^ ord(d)) & 0x000000ffL]
		return crc

# convert time or length from datetime format to 3 bytes hex value
# i.e. 20:25:30 -> 0x20 , 0x25 , 0x30


def TL_hexconv(dt):
	return (
		(dt.hour % 10) + (16 * (dt.hour / 10)),
		(dt.minute % 10) + (16 * (dt.minute / 10)),
		(dt.second % 10) + (16 * (dt.second / 10))
		)


class epgdat_class:
	# temp files used for EPG.DAT creation

	LAMEDB = '/etc/enigma2/lamedb'

	EPGDAT_FILENAME = 'epgtest.dat'
	EPGDAT_TMP_FILENAME = 'epgdat.tmp'

	LB_ENDIAN = '<'

	EPG_HEADER1_channel_count = 0
	EPG_HEADER2_description_count = 0
	EPG_TOTAL_EVENTS = 0

	EXCLUDED_SID = []

	# initialize an empty dictionary (Python array)
	# as total events container postprocessed
	EPGDAT_HASH_EVENT_MEMORY_CONTAINER = {}

	# initialize an empty dictionary (Python array)
	# as channel events container before preprocessing
	events = []

	# initialize an empty dictionary (Python array)
	# the following format can handle duplicated channel name
	# format: { channel_name : [ sid , sid , .... ] }
	lamedb_dict = {}

	# DVB/EPG count days with a 'modified Julian calendar' where day 1 is 17 November 1858
	# Python can use a 'proleptic Gregorian calendar' ('import datetime') where day 1 is 01/01/0001
	# Using 'proleptic' we can compute correct days as difference from NOW and 17/11/1858
	#   datetime.datetime.toordinal(1858,11,17) => 678576
	EPG_PROLEPTIC_ZERO_DAY = 678576

	def __init__(self, tmp_path, lamedb_path, epgdat_path):
		self.EPGDAT_FILENAME = epgdat_path
		self.EPGDAT_TMP_FILENAME = os.path.join(tmp_path, self.EPGDAT_TMP_FILENAME)
		self.EPG_TMP_FD = open(self.EPGDAT_TMP_FILENAME, "wb")
		self.LAMEDB = lamedb_path
		self.s_B = struct.Struct("B")
		self.s_BB = struct.Struct("BB")
		self.s_BBB = struct.Struct("BBB")
		self.s_b_HH = struct.Struct(">HH")
		self.s_I = struct.Struct(self.LB_ENDIAN + "I")
		self.s_II = struct.Struct(self.LB_ENDIAN + "II")
		self.s_IIII = struct.Struct(self.LB_ENDIAN + "IIII")
		self.s_B3sBBB = struct.Struct("B3sBBB")
		self.s_3sBB = struct.Struct("3sBB")

	def set_endian(self, endian):
		self.LB_ENDIAN = endian
		self.s_I = struct.Struct(self.LB_ENDIAN + "I")
		self.s_II = struct.Struct(self.LB_ENDIAN + "II")
		self.s_IIII = struct.Struct(self.LB_ENDIAN + "IIII")

	def set_excludedsid(self, exsidlist):
		self.EXCLUDED_SID = exsidlist

	# assembling short description (type 0x4d , it's the Title) and compute its crc
	def short_desc(self, s):
		# 0x15 is UTF-8 encoding.
		res = self.s_3sBB.pack('eng', len(s) + 1, 0x15) + str(s) + "\0"
		return (crc32_dreambox(res, 0x4d), res)

	# assembling long description (type 0x4e) and compute its crc
	def long_desc(self, s):
		r = []
		# compute total number of descriptions, block 245 bytes each
		# number of descriptions start to index 0
		num_tot_desc = (len(s) + 244) // 245
		for i in range(num_tot_desc):
			ssub = s[i * 245:i * 245 + 245]
			sres = self.s_B3sBBB.pack((i << 4) + (num_tot_desc - 1), 'eng', 0x00, len(ssub) + 1, 0x15) + str(ssub)
			r.append((crc32_dreambox(sres, 0x4e), sres))
		return r

	def add_event(self, starttime, duration, title, description):
		#print "add event : ",event_starttime_unix_gmt, "title : " ,event_title
		self.events.append((starttime, duration, self.short_desc(title[:240]), self.long_desc(description)))

	def preprocess_events_channel(self, services):
		EPG_EVENT_DATA_id = 0
		for service in services:
			# skip empty lines, they make a mess
			if not service.strip():
				continue
			# prepare and write CHANNEL INFO record
			ssid = service.split(":")
			# write CHANNEL INFO record (sid, onid, tsid, eventcount)
			self.EPG_TMP_FD.write(self.s_IIII.pack(
				int(ssid[3], 16), int(ssid[5], 16),
				int(ssid[4], 16), len(self.events)))
			self.EPG_HEADER1_channel_count += 1
			# event_dict.keys() are numeric so indexing is possibile
			# key is the same thing as counter and is more simple to manage last-1 item
			events = self.events
			s_BB = self.s_BB
			s_BBB = self.s_BBB
			s_I = self.s_I
			for event in events:
				# **** (1) : create DESCRIPTION HEADER / DATA ****
				EPG_EVENT_HEADER_datasize = 0
				# short description (title) type 0x4d
				short_d = event[2]
				EPG_EVENT_HEADER_datasize += 4  # add 4 bytes for a sigle REF DESC (CRC32)
				#if not epg_event_description_dict.has_key(short_d[0]):
				#if not exist_event(short_d[0]) :
				if not self.EPGDAT_HASH_EVENT_MEMORY_CONTAINER.has_key(short_d[0]):
					# DESCRIPTION DATA
					pack_1 = s_BB.pack(0x4d, len(short_d[1])) + short_d[1]
					# DESCRIPTION HEADER (2 int) will be computed at the end just before EPG.DAT write
					# because it need the total number of the same description called by many channel section
					#save_event(short_d[0],[pack_1,1])
					self.EPGDAT_HASH_EVENT_MEMORY_CONTAINER[short_d[0]] = [pack_1, 1]
					self.EPG_HEADER2_description_count += 1
				else:
					#increment_event(short_d[0])
					self.EPGDAT_HASH_EVENT_MEMORY_CONTAINER[short_d[0]][1] += 1
				# long description type 0x4e
				long_d = event[3]
				EPG_EVENT_HEADER_datasize += 4 * len(long_d) # add 4 bytes for a single REF DESC (CRC32)
				for desc in long_d:
					#if not epg_event_description_dict.has_key(long_d[i][0]):
					#if not exist_event(long_d[i][0]) :
					if not self.EPGDAT_HASH_EVENT_MEMORY_CONTAINER.has_key(desc[0]):
						# DESCRIPTION DATA
						pack_1 = s_BB.pack(0x4e, len(desc[1])) + desc[1]
						self.EPG_HEADER2_description_count += 1
						# DESCRIPTION HEADER (2 int) will be computed at the end just before EPG.DAT write
						# because it need the total number of the same description called by different channel section
						#save_event(long_d[i][0],[pack_1,1])
						self.EPGDAT_HASH_EVENT_MEMORY_CONTAINER[desc[0]] = [pack_1, 1]
					else:
						#increment_event(long_d[i][0])
						self.EPGDAT_HASH_EVENT_MEMORY_CONTAINER[desc[0]][1] += 1
				# **** (2) : have REF DESC and now can create EVENT HEADER / DATA ****
				# EVENT HEADER (2 bytes: 0x01 , 10 bytes + number of CRC32 * 4)
				pack_1 = s_BB.pack(0x01, 0x0a + EPG_EVENT_HEADER_datasize)
				self.EPG_TMP_FD.write(pack_1)
				# extract date and time from <event>
				# unix format (second since 1970) and already GMT corrected
				event_time_HMS = datetime.utcfromtimestamp(event[0])
				event_length_HMS = datetime.utcfromtimestamp(event[1])
				# epg.dat date is = (proleptic date - epg_zero_day)
				dvb_date = event_time_HMS.toordinal() - self.EPG_PROLEPTIC_ZERO_DAY
				# EVENT DATA
				# simply create an incremental ID,  starting from '1'
				# event_id appears to be per channel, so this should be okay.
				EPG_EVENT_DATA_id += 1
				pack_1 = self.s_b_HH.pack(EPG_EVENT_DATA_id, dvb_date) # ID and DATE , always in BIG_ENDIAN
				pack_2 = s_BBB.pack(*TL_hexconv(event_time_HMS)) # START TIME
				pack_3 = s_BBB.pack(*TL_hexconv(event_length_HMS)) # LENGTH
				pack_4 = s_I.pack(short_d[0]) # REF DESC short (title)
				for d in long_d:
					pack_4 += s_I.pack(d[0]) # REF DESC long
				self.EPG_TMP_FD.write(pack_1 + pack_2 + pack_3 + pack_4)
		# reset again event container
		self.EPG_TOTAL_EVENTS += len(self.events)
		self.events = []

	def final_process(self):
		if self.EPG_TOTAL_EVENTS > 0:
			self.EPG_TMP_FD.close()
			epgdat_fd = open(self.EPGDAT_FILENAME, "wb")
			# HEADER 1
			pack_1 = struct.pack(self.LB_ENDIAN + "I13sI", 0x98765432, 'ENIGMA_EPG_V7', self.EPG_HEADER1_channel_count)
			epgdat_fd.write(pack_1)
			# write first EPG.DAT section
			EPG_TMP_FD = open(self.EPGDAT_TMP_FILENAME, "rb")
			while True:
				pack_1 = EPG_TMP_FD.read(4096)
				if not pack_1:
					break
				epgdat_fd.write(pack_1)
			EPG_TMP_FD.close()
			# HEADER 2
			s_ii = self.s_II
			pack_1 = self.s_I.pack(self.EPG_HEADER2_description_count)
			epgdat_fd.write(pack_1)
			# event MUST BE WRITTEN IN ASCENDING ORDERED using HASH CODE as index
			for temp in sorted(self.EPGDAT_HASH_EVENT_MEMORY_CONTAINER.keys()):
				pack_2 = self.EPGDAT_HASH_EVENT_MEMORY_CONTAINER[temp]
				#pack_1=struct.pack(LB_ENDIAN+"II",int(temp,16),pack_2[1])
				pack_1 = s_ii.pack(temp, pack_2[1])
				epgdat_fd.write(pack_1 + pack_2[0])
			epgdat_fd.close()
		# *** cleanup **
		if os.path.exists(self.EPGDAT_TMP_FILENAME):
			os.unlink(self.EPGDAT_TMP_FILENAME)

