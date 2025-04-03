#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
****************************************
*        coded by Lululla              *
*             15/02/2025               *
****************************************
# Info corvoboys.org
"""

from os import listdir, makedirs, chdir, remove, walk, sync
from os.path import join, isdir, exists
from shutil import rmtree, copyfileobj, copytree, copy2
import tarfile
import urllib.request
import ssl


def url_open(url, context):
	return urllib.request.urlopen(url, context=context)


def main(url):
	TMPSources = "/var/volatile/tmp/EPGimport-Sources-main"
	dest_dir = "/etc/epgimport"
	SETTINGS_FILE = "/etc/enigma2/epgimport.conf"

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

	# Remove existing files in dest_dir before extracting
	for item in listdir(dest_dir):
		item_path = join(dest_dir, item)
		if isdir(item_path):
			rmtree(item_path, ignore_errors=True)
		else:
			remove(item_path)

	try:
		with tarfile.open(tarball, "r:gz") as tar:
			for member in tar.getmembers():
				tar.extract(member, path=TMPSources)
	except tarfile.TarError:
		print("Error extracting tar file")
		return

	extracted_dir = join(TMPSources, "EPGimport-Sources-main")

	for root, _, files in walk(extracted_dir):
		for file in files:
			if file.endswith(".bb"):
				remove(join(root, file))

	for item in listdir(extracted_dir):
		src_item = join(extracted_dir, item)
		if isdir(src_item):
			copytree(src_item, join(dest_dir, item), dirs_exist_ok=True)
		else:
			copy2(src_item, dest_dir)

	rmtree(TMPSources, ignore_errors=True)
	if exists(SETTINGS_FILE):
		remove(SETTINGS_FILE)
	sync()
