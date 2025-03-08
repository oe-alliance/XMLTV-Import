#!/bin/bash
# Script to generate po files outside of the normal build process
#
# Pre-requisite:
# The following tools must be installed on your system and accessible from path
# gawk, find, xgettext, $localgsed, python, msguniq, msgmerge, msgattrib, msgfmt, msginit
#
# Run this script from within the po folder.
#
# Author: Pr2
# Version: 1.3
PluginName="EPGImport"
findoptions=""
printf "Po files update/creation from script starting.\n"
#
# Retrieve languages from Makefile.am LANGS variable for backward compatibility
#
# languages=($(gawk ' BEGIN { FS=" " }
#		/^LANGS/ {
#			for (i=3; i<=NF; i++)
#				printf "%s ", $i
#		} ' Makefile.am ))		
#
# To use the existing files as reference for languages
#
localgsed="sed"
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

languages=($(ls *.po | $localgsed 's/\.po//'))		

# If you want to define the language locally in this script uncomment and defined languages
#languages=("ar" "bg" "ca" "cs" "da" "de" "el" "en" "es" "et" "fa" "fi" "fr" "fy" "he" "hk" "hr" "hu" "id" "is" "it" "ku" "lt" "lv" "nl" "nb" "nn" "pl" "pt" "pt_BR" "ro" "ru" "sk" "sl" "sr" "sv" "th" "tr" "uk" "zh")

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
OLDIFS=$IFS
IFS=" "
for lang in "${languages[@]}" ; do
	if [ -f $lang.po ]; then
		printf "Updating existing translation file %s.po\n" $lang
		msgmerge --backup=none --no-wrap -U $lang.po $PluginName.pot && touch $lang.po
		msgattrib --no-wrap --no-obsolete $lang.po -o $lang.po
		msgfmt -o $lang.mo $lang.po
	else \
		printf "New file created: %s.po, please add it to github before commit\n" $lang
		msginit -l $lang.po -o $lang.po -i $PluginName.pot --no-translator
		msgfmt -o $lang.mo $lang.po
	fi
done
rm $PluginName-py.pot $PluginName-xml.pot
IFS=$OLDIFS
printf "Po files update/creation from script finished!\n"


