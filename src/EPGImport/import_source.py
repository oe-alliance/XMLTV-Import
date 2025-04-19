#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
****************************************
*        coded by Lululla              *
*             15/02/2025               *
****************************************
# Info corvoboys.org
"""

from os import chdir, listdir, makedirs, remove, sync
from os.path import dirname, join
from shutil import rmtree, copyfileobj, copy2
import ssl
import tarfile
from urllib.request import urlopen


def url_open(url, context):
	return urlopen(url, context=context)


def main(url, removeExisting=False):
	TMPSources = "/tmp/EPGImport-Sources"
	dest_dir = "/etc/epgimport"

	makedirs(TMPSources, exist_ok=True)
	makedirs(dest_dir, exist_ok=True)

	chdir(TMPSources)
	tarball = "main.tar.gz"
	context = ssl._create_unverified_context()
	"""
	# with urllib.request.urlopen(url, context=context) as response, open(tarball, "wb") as out_file:
		# copyfileobj(response, out_file)
	"""
	response = None
	try:
		response = url_open(url, context)
		with open(tarball, "wb") as out_file:
			copyfileobj(response, out_file)
	finally:
		if response:
			response.close()

	extracted_dir = "EPGImport-Sources-main"

	try:
		with tarfile.open(tarball, "r:gz") as tar:
			for file in tar.getmembers():
				if file.isfile() and file.name.endswith(".xml"):
					extracted_dir = dirname(file.path)
					tar.extract(file, path=TMPSources, filter="data")
	except tarfile.TarError:
		print("Error extracting tar file")
		return

	extracted_dir = join(TMPSources, extracted_dir)

	if removeExisting:
		for item in listdir(dest_dir):
			if item.endswith(".xml"):
				remove(join(dest_dir, item))

	for item in listdir(extracted_dir):
		src_item = join(extracted_dir, item)
		copy2(src_item, dest_dir)

	rmtree(TMPSources, ignore_errors=True)
	sync()
