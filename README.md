Harmonize Project for Philips Hue 
============================
Harmonize project is a low latency video analysis and pass-through application built in Python which alters Philips Hue lights based on their location relative to a screen; creating an ambient lighting effect and expanding content past the boundries of a screen. Watch the demo below!

Currently in development - Expected release in August 2020

Due to litigation with Signify (owner of the Philips Hue brand), our website was taken down. Harmonize Project (formerly known as Harmonize Hue) has no affiliation with Signify or Philips Hue.

[![Harmonize Project Demo Video](http://img.youtube.com/vi/OkyUntgiYzQ/0.jpg)](http://www.youtube.com/watch?v=OkyUntgiYzQ "Harmonize Project Demo Video")

# Features:
* Low Latency loop-through HDMI output
* Location based light changes
* Streaming to Hue Lights via Entertainment API
* Sending 50-75 color updates per second

# Requirements 
Hardware: (Tested on Raspberry Pi 4B)
* RAM: 256MB Free Minimum (512MB reccommended)
* CPU: 1.5GHz+, 4 Cores strongly reccomended due to running three simultaneous threads.
* HDMI Splitter (Must be able to output 4k & 1080/720p simultaneously) [Here is a good one.](https://www.amazon.com/gp/product/B07YTWV8PR/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1)
* USB3.0 HDMI Capture Card (Capable of capturing 720/1080p) [I got this one for $45.](https://www.amazon.com/gp/product/B07Z7RNDBZ/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1) A similar one should be fine.

Software:
* python3 (Project written and tested on 3.6)
* python3-dev
* pip3
* screen (if you intend to run this on a headless server; recommended)
* v4l2 (You may need a different driver based on your HDMI->USB Capture card. Information on drivers for cheap video cards is [here](https://linuxtv.org/wiki/index.php/Easycap#Making_it_work_4)). For Raspberry Pi install *libjpeg62* via apt and then follow [this guide](https://www.raspberrypi.org/forums/viewtopic.php?t=62364)

Python Modules:
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
* cv2 (Also known as OpenCV. You may have to compile from source depending on your setup. First though, try installing it with pip *sudo pip3 install opencv-python*
* mbedtls (python-mbedtls, may also have to be compiled from source. Use [this](https://github.com/ARMmbed/mbedtls) for Raspberry Pi or other ARM computers.)

# Installation & Usage

Perform this once:
* git clone https://github.com/MCPCapital/harmonizeproject.git

Then, to start the program:
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
* 'breadth' within function 'averageimage' - determines the % of the edges of the screen to use in calculations. Default is 15%.
* 'if ct % 1 == 0:' within funciton 'cv2input_to_buffer' - Edit to skip frames if performance is poor on your device. 
* 'time.sleep(0.005)' within funciton 'buffer_to_light' - Determines how frequently messages are sent to the bridge. Keep in mind the rest of the function takes some time to run in addition to this sleep command. Bridge requests are capped by Philips at about 100 if I recall correctly.

# Contributions & License

Pull requests are encouraged and accepted! Whether you have some code changes or enhancements to the readme, feel free to open a pull request.

Please see the license file at the root level of the source code for the applicable license.
