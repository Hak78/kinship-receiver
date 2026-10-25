[app]
title = Kinship Receiver
package.name = kinshipreceiver
package.domain = org.kinship
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
requirements = python3,kivy,pyjnius
orientation = portrait
osx.kivy_version = 2.2.1
fullscreen = 0
android.permissions = BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_CONNECT, BLUETOOTH_SCAN, ACCESS_FINE_LOCATION
android.api = 33
android.minapi = 21
android.ndk = 25b

[buildozer]
log_level = 2
warn_on_root = 1
