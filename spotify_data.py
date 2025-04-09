import dbus 
from math import ceil

session_bus = dbus.SessionBus()
spotify_bus = session_bus.get_object("org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2")
spotify_properties = dbus.Interface(spotify_bus, "org.freedesktop.DBus.Properties")

def timestring(microseconds):
    seconds = ceil(microseconds/1000000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
    else:
        return "{:02}:{:02}".format(int(minutes), int(seconds))

def trackinfo():
    info = dict()
    metadata = spotify_properties.Get("org.mpris.MediaPlayer2.Player", "Metadata")
    info['position'] = timestring(spotify_properties.Get("org.mpris.MediaPlayer2.Player", "Position"))
    info['length'] = timestring(metadata['mpris:length'])
    info['title'] = str(metadata['xesam:title'])
    info['album'] = str(metadata['xesam:album'])
    info['artist'] = str(metadata['xesam:artist'][0])
    return info
