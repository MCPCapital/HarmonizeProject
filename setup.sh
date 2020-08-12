#!/bin/bash
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root / with sudo!" 
   exit 1
fi
apt update --yes
apt dist-upgrade --yes
apt upgrade --yes
apt install --yes git python3 python3-pip python3-requests python3-dev libpython-dev libqtgui4 libqt4-test libgstreamer1.0-0 libjpeg62-turbo-dev libmbedtls12 libmbedtls-dev screen
echo "############### BASE DEPENDENCIES DONE ###############" 
apt --yes install python3-opencv
echo "############### OPENCV DONE ###############" 
git clone https://github.com/Synss/python-mbedtls
cd python-mbedtls
pip3 install -r requirements.txt
python3 ./setup.py install
echo "############### MBEDTLS DONE ###############" 
echo "############### FULLY COMPLETE ###############" 
exit
