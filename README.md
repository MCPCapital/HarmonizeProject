Harmonize Project *for Philips Hue*
============================
Harmonize Project is a low latency video analysis and pass-through application built in Python which alters Philips Hue lights based on their location relative to a screen; creating an ambient lighting effect and expanding content past the boundaries of a screen. Check out our Reddit thread [here](https://www.reddit.com/r/Hue/comments/i1ngqt/release_harmonize_project_sync_hue_lights_with/) and watch the demo below!

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
* HDMI Splitter (Must be able to output 4k & 1080/720p simultaneously) [Here is a good one for $25](https://www.amazon.com/gp/product/B07YTWV8PR/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1), though it breaks HDR when downscaling output 2. The goal here is one output of 4K and another output of 1080/720p.
* USB3.0 HDMI Capture Card (Capable of capturing 720/1080p; delay should be 50ms or under.) [I got this when it was $45.](https://www.amazon.com/gp/product/B07Z7RNDBZ/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1) A similar one should be fine. These are untested: [Panoraxy](https://www.amazon.com/Panoraxy-Capture-1080PFHD-Broadcast-Camcorder/dp/B088PYDJ22/ref=sr_1_21?dchild=1&keywords=hdmi+to+usb+3.0+capture&qid=1596386201&refinements=p_36%3A1253504011%2Cp_85%3A2470955011&rnid=2470954011&rps=1&s=electronics&sr=1-21) | [Aliexpress - Cards that have this shape/style tend to perform well.](https://www.aliexpress.com/item/4000834496145.html?spm=a2g0o.productlist.0.0.27a14df5Wc5Qoc&algo_pvid=e745d484-c811-4d2e-aebd-1403e862f148&algo_expid=e745d484-c811-4d2e-aebd-1403e862f148-15&btsid=0ab50f4415963867142714634e7e8e&ws_ab_test=searchweb0_0,searchweb201602_,searchweb201603_) | [LEADNOVO (Questionable quality but cheap)](https://www.amazon.com/LEADNOVO-actualizaci%C3%B3n-adquisici%C3%B3n-definici%C3%B3n-transmisi%C3%B3n/dp/B0899YQ6M2/ref=cm_cr_arp_d_product_top?ie=UTF8)

APT-retrievable software: 
* sudo apt install git python3 pip3 python3-dev libpython-dev python3-opencv libqtgui4 libqt4-test libgstreamer1.0-0 libjpeg62 libjpeg62-turbo-dev libmbedtls12 libmbedtls-dev screen autoconf gettext libtool autopoint

Python Modules: (http_parser and python-mbedtls)
* sudo pip3 install http_parser 
* git clone https://github.com/Synss/python-mbedtls
* cd python-mbedtls
* sudo pip3 install -r requirements.txt
* sudo python3 ./setup.py install

Video input driver: (v4l2 - most compatible driver)
* sudo rpi-update     (update to newer kernels which include this driver)
* sudo reboot         (load the updated kernel)
* git clone git://git.linuxtv.org/v4l-utils.git
* cd v4l-utils
* ./bootstrap.sh
* ./configure
* make
* sudo make install 
* sudo modprobe bcm2835-v4l2

That should do it. You may need a different driver based on your HDMI->USB Capture card, but this one is compatible with most cards. Information on drivers for cheap video cards is [here](https://linuxtv.org/wiki/index.php/Easycap#Making_it_work_4).

# Setup & Usage

Hardware Setup:
* Connect Video Device (PS4, FireStick, etc.) to the splitter input. 
* Connect an HDMI cable from the 4k output to the TV; and from Output 2 (downscaled) to the video capture card connected to your device.
* Ensure your splitter's switches are set to downscale Output 2 to 1080 or 720p!
![Connection Diagram](http://harmonizeproject.matthewpilsbury.com/diagram.png)

Download the latest script from https://github.com/MCPCapital/harmonizeproject/releases

Set up your entertainment area:
* Hue App -> Settings -> Entertainment Areas
* Harmonize will use the **height** and the **horizontal position** of lights in relation to the TV. **The depth/vertial position are currently ignored.**
* In the example below, the light on the left is to the left of the TV at the bottom of it. The light on the right is on the right side of the TV at the top of it.
![Example Entertainment Area](http://harmonizeproject.matthewpilsbury.com/examplearea1.jpg)

To start the program:
* screen
* ./harmonizeproject.py -CommandLineArgumentsGoHere

* if you have not set up a bridge before, this program will attempt to register you on the bridge
* If multiple bridges are found, you will be given the option to select one
* If multiple entertainment areas are found, you will be given the option to select one. You can also enter this as a command line argument.
* Enter Ctrl+A and then Ctrl+D; then, feel free to disconnect from the device. To resume the terminal use       *screen -r
* Press ENTER to safely stop the program. Using Ctrl+C works but does not formally end the entertainment streaming session and thus, for an additional 10 seconds, the lights are rendered uncommunicable.

Command line arguments:
* -v            Display verbose output
* -g #          Use specific entertainment group number (#)

Configurable values within the scripts:
* Line 237 - 'breadth' - determines the % of the edges of the screen to use in calculations. Default is 15%.
* Line 293 - 'if ct % 1 == 0:' - Edit to skip frames if performance is poor on your device. (Not reccomended)
* Line 315 - 'time.sleep(0.01)' - Determines how frequently messages are sent to the bridge. Keep in mind the rest of the function takes some time to run in addition to this sleep command. Bridge requests are capped by Philips at a rate of 60/s and the excess are dropped.

# Troubleshooting

* No video device found - Run *sudo modprobe bcm2835-v4l2* and consider [running it on every boot.](https://www.raspberrypi.org/documentation/linux/usage/rc-local.md)

# Contributions & License

Pull requests are encouraged and accepted! Whether you have some code changes or enhancements to the readme, feel free to open a pull request.

Please see the license file at the root level of the source code for the applicable license.

Development credits to Matthew C. Pilsbury and Ares N. Vlahos.
