from __future__ import absolute_import
from __future__ import print_function

from . import log

from xml.etree.cElementTree import iterparse
from xml.sax.saxutils import unescape
import calendar
import six
import time
# %Y%m%d%H%M%S


def quickptime(date_str):
    return time.struct_time(
        (
            int(date_str[0:4]),     # Year
            int(date_str[4:6]),     # Month
            int(date_str[6:8]),     # Day
            int(date_str[8:10]),    # Hour
            int(date_str[10:12]),   # Minute
            0,                      # Second (set to 0)
            -1,                     # Weekday (set to -1 as unknown)
            -1,                     # Julian day (set to -1 as unknown)
            0                       # DST (Daylight Saving Time, set to 0 as unknown)
        )
    )


def get_time_utc(timestring, fdateparse):
    try:
        values = timestring.split(' ')
        tm = fdateparse(values[0])
        timegm = calendar.timegm(tm)
        timegm -= (3600 * int(values[1]) // 100)
        return timegm
    except Exception as e:
        print("[XMLTVConverter] get_time_utc error:", e)
        return 0


# Preferred language should be configurable, but for now,
# we just like Dutch better!


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

    # Now returning UTF-8 by default, the epgdat/oudeis must be adjusted to make this work.
    # Note that the default xml.sax.saxutils.unescape() function don't unescape
    # some characters and we have to manually add them to the entities dictionary.

    r = unescape(r, entities={
        r"&apos;": r"'",
        r"&quot;": r'"',
        r"&#124;": r"|",
        r"&nbsp;": r" ",
        r"&#91;": r"[",
        r"&#93;": r"]",
    })
    return six.ensure_str(r)


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
    return six.ensure_str(r)


def enumerateProgrammes(fp):
    """Enumerates programme ElementTree nodes from file object 'fp'"""
    for event, elem in iterparse(fp):
        try:
            if elem.tag == 'programme':
                yield elem
                elem.clear()
            elif elem.tag == 'channel':
                # Throw away channel elements, save memory
                elem.clear()
        except Exception as e:
            print("[XMLTVConverter] enumerateProgrammes error:", e)


class XMLTVConverter:
    def __init__(self, channels_dict, category_dict, dateformat='%Y%m%d%H%M%S %Z', offset=0):
        self.channels = channels_dict
        self.categories = category_dict
        if dateformat.startswith('%Y%m%d%H%M%S'):
            self.dateParser = quickptime
        else:
            self.dateParser = lambda x: time.strptime(x, dateformat)
        self.offset = offset
        print("[XMLTVConverter] Using a custom time offset of %d" % offset)

    def enumFile(self, fileobj):
        print("[XMLTVConverter] Enumerating event information", file=log)
        lastUnknown = None
        # there is nothing no enumerate if there are no channels loaded
        if not self.channels:
            return
        for elem in enumerateProgrammes(fileobj):
            channel = elem.get('channel')
            channel = channel.lower()
            if channel not in self.channels:
                if lastUnknown != channel:
                    print("Unknown channel: ", channel, file=log)
                    lastUnknown = channel
                # return a None object to give up time to the reactor.
                yield None
                continue
            try:
                services = self.channels[channel]
                start = get_time_utc(elem.get('start'), self.dateParser) + self.offset
                stop = get_time_utc(elem.get('stop'), self.dateParser) + self.offset
                title = get_xml_string(elem, 'title')
                # try/except for EPG XML files with program entries containing <sub-title ... />
                try:
                    subtitle = get_xml_string(elem, 'sub-title')
                except:
                    subtitle = ''
                # try/except for EPG XML files with program entries containing <desc ... />
                try:
                    description = get_xml_string(elem, 'desc')
                except:
                    description = ''
                category = get_xml_string(elem, 'category')
                cat_nr = self.get_category(category, stop - start)

                try:
                    rating_str = get_xml_rating_string(elem)
                    # hardcode country as ENG since there is no handling for parental certification systems per country yet
                    # also we support currently only number like values like "12+" since the epgcache works only with bytes right now
                    rating = [("eng", int(rating_str) - 3)]
                except:
                    rating = None

                # data_tuple = (data.start, data.duration, data.title, data.short_description, data.long_description, data.type)
                if not stop or not start or (stop <= start):
                    print("[XMLTVConverter] Bad start/stop time: %s (%s) - %s (%s) [%s]" % (elem.get('start'), start, elem.get('stop'), stop, title))
                if rating:
                    yield (services, (start, stop - start, title, subtitle, description, cat_nr, 0, rating))
                else:
                    yield (services, (start, stop - start, title, subtitle, description, cat_nr))
            except Exception as e:
                print("[XMLTVConverter] parsing event error:", e)

    def get_category(self, cat, duration):
        if (not cat) or (not isinstance(cat, type('str'))):
            return 0
        if cat in self.categories:
            category = self.categories[cat]
            if len(category) > 1:
                if duration > 60 * category[1]:
                    return category[0]
            elif len(category) > 0:
                return category[0]
        return 0

    # def get_category(self, str, duration):
        # if (not str) or (not isinstance(str, type('str'))):
            # return 0
        # if str in self.categories:
            # category = self.categories[str]
            # if len(category) > 1:
                # if duration > 60 * category[1]:
                    # return category[0]
            # elif len(category) > 0:
                # return category
        # return 0
