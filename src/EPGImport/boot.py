#!/usr/bin/python
from os import listdir, unlink
from os.path import exists, getctime, join
from time import time
from shutil import copy2

MEDIA = ("/media/hdd/", "/media/usb/", "/media/mmc/", "/media/cf/", "/tmp")


def findEpg():
	candidates = []
	for path in MEDIA:
		try:
			if exists(path):
				for fn in listdir(path):
					if "epg.dat" in fn:
						ffn = join(path, fn)
						candidates.append((getctime(ffn), ffn))
		except:
			pass  # ignore errors.
	if not candidates:
		return None
	candidates.sort()  # order by ctime...
	# best candidate is most recent filename.
	return candidates[-1][1]


def checkCrashLog():
	for path in MEDIA[:-1]:
		try:
			dirList = listdir(path)
			for fname in dirList:
				if fname[0:13] == "enigma2_crash":
					try:
						crashtime = 0
						crashtime = int(fname[14:24])
						howold = time() - crashtime
					except Exception:
						print("no time found in filename")
					if howold < 120:
						print("recent crashfile found analysing")
						crashfile = open(path + fname, "r")
						crashtext = crashfile.read()
						crashfile.close()
						if (crashtext.find("FATAL: LINE ") != -1):
							print("string found, deleting epg.dat")
							return True
		except Exception:
			pass
	return False


def findNewEpg():
	for path in MEDIA:
		fn = join(path, "epg_new.dat")
		if exists(fn):
			return fn


epg = findEpg()
newepg = findNewEpg()

print(f"Epg.dat found at : {epg}")
print(f"newepg  found at : {newepg}")

# Delete epg.dat if last crash was because of error in epg.dat
if checkCrashLog():
	try:
		unlink(epg)
	except:
		print("delete error")

# if excists cp epg_new.dat epg.dat
if newepg:
	if epg:
		print("replacing epg.dat with newmade version")
		unlink(epg)
		copy2(newepg, epg)
