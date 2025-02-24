#!/usr/bin/python
# -*- coding: utf-8 -*-

from Components.config import config
from re import sub
from xml.sax.saxutils import unescape
from xml.etree.cElementTree import iterparse


global filterCustomChannel


# Verifica che la configurazione epgimport sia definita
if hasattr(config.plugins, "epgimport") and hasattr(config.plugins.epgimport, "filter_custom_channel"):
	filterCustomChannel = config.plugins.epgimport.filter_custom_channel.value
else:
	filterCustomChannel = False  # Fallback se non è definito


def get_xml_rating_string(elem):
	r = ''
	try:
		for node in elem.findall("rating"):
			for val in node.findall("value"):
				txt = val.text.replace("+", "")
				if not r:
					r = txt
	except Exception as e:
		print("[XMLTVConverter] get_xml_rating_string error:", e)
	return r.decode() if isinstance(r, bytes) else r


def xml_unescape(text):
	if not isinstance(text, str):
		return ''
	return sub(
		r'&#160;|&nbsp;|\s+',
		' ',
		unescape(
			text.strip(),
			entities={
				r"&laquo;": "«",
				r"&#171;": "«",
				r"&raquo;": "»",
				r"&#187;": "»",
				r"&apos;": r"'",
				r"&quot;": r'"',
				r"&#124;": r"|",
				r"&#91;": r"[",
				r"&#93;": r"]",
			}
		)
	)


def get_xml_string(elem, name):
	r = ''
	try:
		for node in elem.findall(name):
			txt = node.text
			lang = node.get('lang', None)
			if not r and txt is not None:
				r = txt
			elif lang == "nl":
				r = txt
	except Exception as e:
		print("[XMLTVConverter] get_xml_string error:", e)

	# Ora ritorniamo UTF-8 di default
	r = unescape(r, entities={
		r"&apos;": r"'",
		r"&quot;": r'"',
		r"&#124;": r"|",
		r"&nbsp;": r" ",
		r"&#91;": r"[",
		r"&#93;": r"]",
	})

	try:
		# Assicura che il risultato sia una stringa
		return r.encode('utf-8').decode('utf-8')  # Compatibile con Python 2 e 3
	except UnicodeEncodeError as e:
		print("[XMLTVConverter] Encoding error:", e)
		return r  # Ritorna come fallback


def enumerateXML(fp, tag=None):
	"""
	Enumerates ElementTree nodes from file object 'fp' for a specific tag.
	Args:
		fp: File-like object containing XML data.
		tag: The XML tag to search for. If None, processes all nodes.
	Yields:
		ElementTree.Element objects matching the specified tag.
	"""
	doc = iterparse(fp, events=('start', 'end'))
	_, root = next(doc)  # Get the root element
	depth = 0

	for event, element in doc:
		if tag is None or element.tag == tag:  # Process all nodes if no tag is specified
			if event == 'start':
				depth += 1
			elif event == 'end':
				depth -= 1
				if depth == 0:  # Tag is fully parsed
					yield element
					element.clear()  # Free memory for the element
		elif event == 'end':  # Clear other elements to free memory
			root.clear()
