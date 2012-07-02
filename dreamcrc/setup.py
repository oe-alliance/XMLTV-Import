from distutils.core import setup, Extension

plugdir = '/usr/lib/enigma2/python/Plugins/Extensions/EPGImport'

dreamcrc = Extension('dreamcrc',
                    sources = ['dreamcrc.c'])

setup (name = 'enigma2-plugin-extensions-xmltvimport',
       version = '0.9.12',
       description = 'C implementation of Dream CRC32 algorithm',
#        packages = ['EPGImport'],
# 	package_data = {'EPGImport': ['EPGImport/*.png']},
#	data_files = [('etc/epgimport', ['*.xml'])],
       ext_modules = [dreamcrc])
