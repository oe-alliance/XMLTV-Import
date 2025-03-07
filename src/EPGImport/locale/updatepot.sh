#!/bin/bash
# Script to generate po files outside of the normal build process
#  
# Pre-requisite:
# The following tools must be installed on your system and accessible from path
# gawk, find, xgettext, sed, python, msguniq, msgmerge, msgattrib, msgfmt, msginit
#
# Run this script from within the po folder.
#
# Author: Pr2 for OpenPLi Team
# Version: 1.1
#
# Retrieve languages from Makefile.am LANGS variable for backward compatibility
#
PluginName="EPGImport"
localgsed="sed"
findoptions=""

#
# Script only run with sed but on some distro normal sed is already sed so checking it.
#
sed --version 2> /dev/null | grep -q "GNU"
if [ $? -eq 0 ]; then
	localgsed="sed"
else
	"$localgsed" --version | grep -q "GNU"
	if [ $? -eq 0 ]; then
		printf "GNU sed found: [%s]\n" $localgsed
	fi
fi

which python
if [ $? -eq 1 ]; then
	which python3
	if [ $? -eq 1 ]; then
		printf "python not found on this system, please install it first or ensure that it is in the PATH variable.\n"
		exit 1
	fi
fi

which xgettext
if [ $? -eq 1 ]; then
	printf "xgettext not found on this system, please install it first or ensure that it is in the PATH variable.\n"
	exit 1
fi


#
# On Mac OSX find option are specific
#
if [[ "$OSTYPE" == "darwin"* ]]
	then
		# Mac OSX
		printf "Script running on Mac OSX [%s]\n" "$OSTYPE"
    	findoptions=" -s -X "
        localgsed="gsed"
fi

#
# Arguments to generate the pot and po files are not retrieved from the Makefile.
# So if parameters are changed in Makefile please report the same changes in this script.
#
printf "Creating temporary file $PluginName-py.pot\n"
find $findoptions .. -name "*.py" -exec xgettext --no-wrap -L Python --from-code=UTF-8 -kpgettext:1c,2 --add-comments="TRANSLATORS:" -d $PluginName -o $PluginName-py.pot {} \+
$localgsed --in-place $PluginName-py.pot --expression=s/CHARSET/UTF-8/
printf "Creating temporary file $PluginName-xml.pot\n"
which python
if [ $? -eq 0 ]; then
	find $findoptions .. -name "setup.xml" -exec python xml2po.py {} \+ > $PluginName-xml.pot
else
	find $findoptions .. -name "setup.xml" -exec python3 xml2po.py {} \+ > $PluginName-xml.pot
fi
printf "Merging pot files to create: $PluginName.pot\n"
cat $PluginName-py.pot $PluginName-xml.pot | msguniq --sort-output --no-location --no-wrap -o $PluginName.pot -
#printf "remove pot Creation date\n"
#$localgsed -i -e'/POT-Creation/d' $PluginName.pot
printf "remove temp pot files\n"
rm $PluginName-py.pot $PluginName-xml.pot
printf "pot update from script finished!\n"
