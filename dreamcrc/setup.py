from distutils.core import setup, Extension

plugdir = '/usr/lib/enigma2/python/Plugins/Extensions/XLMTVImport'

dreamcrc = Extension('dreamcrc',
                    sources = ['dreamcrc.c'])

setup (name = 'enigma2-plugin-extensions-xmltvimport',
       version = '0.9.12',
       description = 'C implementation of Dream CRC32 algorithm',
#        packages = ['XLMTVImport'],
# 	package_data = {'XLMTVImport': ['XLMTVImport/*.png']},
#	data_files = [('etc/epgimport', ['*.xml'])],
       ext_modules = [dreamcrc])
