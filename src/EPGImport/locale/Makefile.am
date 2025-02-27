LANGS = ar bg ca cs da de el en en_GB es et fa fi fr fy he hr hu is it lt lv nl no nb pl pt pt_BR ro ru sv sk sl sr th tr uk
LANGMO = $(LANGS:=.mo)
LANGPO = $(LANGS:=.po)

EXTRA_DIST = $(LANGPO)

if UPDATE_PO
# the TRANSLATORS: allows putting translation comments before the to-be-translated line.
EPGImport-py.pot: $(top_srcdir)/src/*.py
	$(XGETTEXT) --no-wrap -L Python --from-code=UTF-8 -kpgettext:1c,2 --add-comments="TRANSLATORS:" -d @PACKAGE_NAME@ -s -o $@ $^

EPGImport.pot: EPGImport-py.pot
	sed --in-place EPGImport-py.pot --expression=s/CHARSET/UTF-8/
	$(MSGUNIQ) --no-wrap --no-location $^ -o $@

%.po: EPGImport.pot
	if [ -f $@ ]; then \
		$(MSGMERGE) --backup=none --no-wrap --no-location -s -N -U $@ $< && touch $@; \
	else \
		$(MSGINIT) -l $@ -o $@ -i $< --no-translator; \
	fi
endif

.po.mo:
	$(MSGFMT) -o $@ $<

BUILT_SOURCES = $(LANGMO)
CLEANFILES = $(LANGMO) EPGImport-py.pot EPGImport.pot

dist-hook: $(LANGPO)

install-data-local: $(LANGMO)
	for lang in $(LANGS); do \
		$(mkinstalldirs) $(DESTDIR)/usr/lib/enigma2/python/Plugins/Extensions/EPGImport/locale/$$lang/LC_MESSAGES; \
		$(INSTALL_DATA) $$lang.mo $(DESTDIR)/usr/lib/enigma2/python/Plugins/Extensions/EPGImport/locale/$$lang/LC_MESSAGES/EPGImport.mo; \
		$(INSTALL_DATA) $$lang.po $(DESTDIR)/usr/lib/enigma2/python/Plugins/Extensions/EPGImport/locale/$$lang.po; \
	done

uninstall-local:
	for lang in $(LANGS); do \
		$(RM) $(DESTDIR)/usr/lib/enigma2/python/Plugins/Extensions/EPGImport/locale/$$lang/LC_MESSAGES/EPGImport.mo; \
		$(RM) $(DESTDIR)/usr/lib/enigma2/python/Plugins/Extensions/EPGImport/locale/$$lang.po; \
	done
