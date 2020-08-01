Harmonize Project for Philips Hue 
============================
Harmonize project is a low latency video analysis and pass-through application built in Python which alters Philips Hue lights based on their location relative to a screen; creating an ambient lighting effect and expanding content past the boundries of a screen. Watch the demo below!

[![Harmonize Project Demo Video](http://img.youtube.com/vi/OkyUntgiYzQ/0.jpg)](http://www.youtube.com/watch?v=OkyUntgiYzQ "Harmonize Project Demo Video")

Harmonize Project (formerly known as Harmonize Hue) has no affiliation with Signify or Philips Hue. Hue and Philips Hue are trademarks of Signify.

# Features:
* Light color and intensity changes based on pixels in its relative set location
* Video -> Light latency of 80ms via Streaming to Hue Lights via Entertainment API
* Sending 50-75 color updates per second

# Requirements 
Hardware: (Tested on Raspberry Pi 4B)
* RAM: 256MB Free Minimum (512MB reccommended)
* CPU: 1.5GHz+, 4 Cores strongly reccomended due to running three simultaneous threads.
* HDMI Splitter (Must be able to output 4k & 1080/720p simultaneously) [Here is a good one for $25](https://www.amazon.com/gp/product/B07YTWV8PR/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1), though it breaks HDR.
* USB3.0 HDMI Capture Card (Capable of capturing 720/1080p; delay should be 50ms or under.) [I got this one for $45.](https://www.amazon.com/gp/product/B07Z7RNDBZ/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1) A similar one should be fine.

Software: (sudo apt install *packagename*)
* python3 (Project written and tested on 3.6)
* pip3
* python3-dev (and libpython-dev)
* python3-opencv
* libqtgui4
* libqt4-test
* libgstreamer1.0-0
* libjpeg62-dev (and its dependency libjpeg62)
* libmbedtls-dev (and libmbedtls12)
* screen (if you intend to run this on a headless server; recommended)
* v4l2 (You may need a different driver based on your HDMI->USB Capture card. Information on drivers for cheap video cards is [here](https://linuxtv.org/wiki/index.php/Easycap#Making_it_work_4)). For Raspberry Pi run *rpi-update* to update to newer kernels which include this driver, then *sudo modprobe bcm2835-v4l2*   [More info here](https://www.raspberrypi.org/forums/viewtopic.php?f=43&t=62364&sid=239323676f4f6952da3d5c38e2ac9575)
I may be missing something - if you discover another dependency, please open an issue and I shall add it to the list.
Run *sudo apt clean* and *sudo apt autoremove* to clear up some space after installing dependencies.

Python Modules: (sudo pip3 install *modulename*)
* sys
* http_parser
* argparse
* requests
* time
* json
* pathlib
* socket
* subprocess
* threading
* fileinput
* numpy
* cv2 (opencv-python==3.4.6.27 for Raspberry Pi) You may have to compile from source depending on your setup.
* [mbedtls](https://github.com/Synss/python-mbedtls/) (Download source code, *sudo pip3 install -r requirements.txt* and then *sudo python3 ./setup.py install*)

# Installation & Usage

Perform this once:
* git clone https://github.com/MCPCapital/harmonizeproject.git

Set up your entertainment area:
* Step 1
* Step 2
Image of entertainment area

To start the program:
* cd harmonizeproject
* screen
* ./harmonizeproject.py -CommandLineArgumentsGoHere
* Ctrl+A , Ctrl+D
* Feel free to disconnect from the device. To resume the terminal use       *screen -r
* Press ENTER to safely stop the program. Using Ctrl+C works but does not formally end the entertainment streaming session and thus, for an additional 10 seconds, the lights are rendered uncommunicable.

Command line arguments:
* -v            Display verbose output
* -g #          Use specific entertainment group number (#)

Configurable values within the scripts:
* Line 237 - 'breadth' - determines the % of the edges of the screen to use in calculations. Default is 15%.
* Line 293 - 'if ct % 1 == 0:' - Edit to skip frames if performance is poor on your device. (Not reccomended)
* Line 315 - 'time.sleep(0.01)' - Determines how frequently messages are sent to the bridge. Keep in mind the rest of the function takes some time to run in addition to this sleep command. Bridge requests are capped by Philips at a rate of 60/s and the excess are dropped.

# Contributions & License

Pull requests are encouraged and accepted! Whether you have some code changes or enhancements to the readme, feel free to open a pull request.

Please see the license file at the root level of the source code for the applicable license.
