from distutils.core import setup, Extension

plugdir = '/usr/lib/enigma2/python/Plugins/Extensions/XMLTVImport'

dreamcrc = Extension('dreamcrc',
                    sources = ['dreamcrc.c'])

setup (name = 'enigma2-plugin-extensions-xmltvimport',
       version = '0.9.12',
       description = 'C implementation of Dream CRC32 algorithm',
#        packages = ['XMLTVImport'],
# 	package_data = {'XMLTVImport': ['XMLTVImport/*.png']},
#	data_files = [('etc/xmltvimport', ['*.xml'])],
       ext_modules = [dreamcrc])
