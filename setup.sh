#!/bin/sh
# Install pyxhook lib
wget https://github.com/JeffHoogland/pyxhook/archive/master.zip
unzip master.zip
rm -v master.zip
rm -rf pyxhook
mv -v pyxhook-master pyxhook
touch pyxhook/__init__.py
