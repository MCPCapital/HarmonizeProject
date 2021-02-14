Harmonize Project *for Philips Hue* [![ForTheBadge built-with-love](http://ForTheBadge.com/images/badges/built-with-love.svg)](https://matthewpilsbury.com)
============================
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://GitHub.com/MCPCapital/HarmonizeProject/graphs/commit-activity) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](http://makeapullrequest.com)<!--[![Trust](https://img.shields.io/endpoint.svg?url=https%3A%2F%2Fastronomer.ullaakut.eu%2Fshields%3Fowner%3DMCPCapital%26name%3DHarmonizeProject)](#)--> [![Open Source Love svg2](https://badges.frapsoft.com/os/v2/open-source.svg?v=103)](https://matthewpilsbury.com)
[![Author](https://img.shields.io/badge/Meet%20the%20Author-MCP-blue)](https://matthewpilsbury.com "matthewpilsbury.com") [![forthebadge made-with-python](http://ForTheBadge.com/images/badges/made-with-python.svg)](#)

Harmonize Project is a low latency video analysis and pass-through application built in Python which alters Philips Hue lights based on their location relative to a screen; creating an ambient lighting effect and expanding content past the boundaries of a screen. 

Check out our Reddit thread [here](https://www.reddit.com/r/Hue/comments/i1ngqt/release_harmonize_project_sync_hue_lights_with/) and watch the demo below! Electromaker explains how our application works at a high level in his podcast [here!](https://youtu.be/tYnvYYWedVc?t=1790)

[![Harmonize Project Demo Video](http://img.youtube.com/vi/OkyUntgiYzQ/0.jpg)](http://www.youtube.com/watch?v=OkyUntgiYzQ "Harmonize Project Demo Video")

[![GitHub Deleted our Account](https://matthewpilsbury.com/github-deleted.PNG)](#)

GitHub deleted our account at 250 stars! Prior to deletion, we were in the top 20,000 repositories and top 7,000 Python-based projects on GitHub. Sorry for the interruption and loss of issues.

Harmonize Project (formerly known as Harmonize Hue) has no affiliation with Signify or Philips Hue. Hue and Philips Hue are trademarks of Signify.

# Features:
* Light color and intensity changes based on pixels in its relative set location
* Video -> Light latency of 80ms via Streaming to Hue Lights via Entertainment API
* Sending 50-75 color updates per second

# Requirements 
Hardware: (Tested on Raspberry Pi 4B)
* RAM: 256MB Free Minimum (512MB recommended)
* CPU: 1.5GHz+, 4 Cores strongly recommended due to running three simultaneous threads.
* HDMI Splitter (Must be able to output 4k & 1080/720p simultaneously) [Here is a good one for $25](https://www.amazon.com/gp/product/B07YTWV8PR/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1), though it breaks HDR when downscaling output 2. The goal here is one output of 4K and another output of 1080/720p.
* USB3.0 HDMI Capture Card (Capable of capturing 720/1080p; delay should be 50ms or under.) [I got this when it was $45.](https://www.amazon.com/gp/product/B07Z7RNDBZ/ref=ppx_yo_dt_b_search_asin_title?ie=UTF8&psc=1) A similar one should be fine. These are untested: [Panoraxy](https://www.amazon.com/Panoraxy-Capture-1080PFHD-Broadcast-Camcorder/dp/B088PYDJ22/ref=sr_1_21?dchild=1&keywords=hdmi+to+usb+3.0+capture&qid=1596386201&refinements=p_36%3A1253504011%2Cp_85%3A2470955011&rnid=2470954011&rps=1&s=electronics&sr=1-21) | [Aliexpress (This shape/style tends to perform well.)](https://www.aliexpress.com/item/4000834496145.html?spm=a2g0o.productlist.0.0.27a14df5Wc5Qoc&algo_pvid=e745d484-c811-4d2e-aebd-1403e862f148&algo_expid=e745d484-c811-4d2e-aebd-1403e862f148-15&btsid=0ab50f4415963867142714634e7e8e&ws_ab_test=searchweb0_0,searchweb201602_,searchweb201603_)

# Setup

**Software Setup:**

Download the latest scripts and install all dependencies via the following commands. **Be sure to watch for errors!** You will need about 1GB of free space. The script can run for up to an hour.

```
git clone https://github.com/MCPCapital/HarmonizeProject.git
cd HarmonizeProject
sudo ./setup.sh
```

**Hardware Setup:**

* Connect Video Device (PS4, FireStick, etc.) to the splitter input. 
* Connect an HDMI cable from the 4k output to the TV; and from Output 2 (downscaled) to the video capture card connected to your device.
* Ensure your splitter's switches are set to downscale Output 2 to 1080 or 720p!
![Connection Diagram](http://harmonizeproject.matthewpilsbury.com/diagram.png)

**Entertainment Area Configuration:**

* Hue App -> Settings -> Entertainment Areas
* Harmonize will use the **height** and the **horizontal position** of lights in relation to the TV. **The depth/vertical position are currently ignored.**
* In the example below, the light on the left is to the left of the TV at the bottom of it. The light on the right is on the right side of the TV at the top of it.
![Example Entertainment Area](http://harmonizeproject.matthewpilsbury.com/examplearea1.jpg)

**First-Time Run Instructions:**

* If you have not set up a bridge before, the program will attempt to register you on the bridge. You will have 45 second to push the button on the bridge. *Current Bug* - After registering, the script will store the clientdata but fail & exit. *Workaround* - Simply run the script again since the data was saved.
* If multiple bridges are found, you will be given the option to select one. You will have to do this every time if you have multiple bridges (for now).
* If multiple entertainment areas are found, you will be given the option to select one. You can also enter this as a command line argument.

# Usage

**To start the program:**

* `screen`
* `cd harmonizeproject`
* `./harmonize.py`
* Type Ctrl+A and Ctrl-D to continue running the script in the background.
* To resume the terminal session use `screen -r`
* Press *ENTER* to safely stop the program.

**Command line arguments:**

* `-v `           Display verbose output
* `-g # `         Use specific entertainment group number (#)

**Configurable values within the script:** (Advanced users only)

* Line 237 - `breadth` - determines the % from the edges of the screen to use in calculations. Default is 15%. Lower values can result in less lag time, but less color accuracy.
* Line 315 - `time.sleep(0.01)` - Determines how frequently messages are sent to the bridge. Keep in mind the rest of the function takes some time to run in addition to this sleep command. Bridge requests are capped by Philips at a rate of 60/s (1 per ~16.6ms) and the excess are dropped.
* Run with `sudo` to give Harmonize higher priority over other CPU tasks.

# Troubleshooting

* "Import Error" - Ensure you have all the dependencies installed. Run through the manual dependency install instructions above.
* No video input // lights are all dim gray - Run `python3 ./videotest.py` to see if your device (via OpenCV) can properly read the video input.
* w, h, or rgbframe not defined - Increase the waiting time from 0.75 seconds - Line 330 {time.sleep(.75)} *This is a known bug (race condition).
* python3-opencv installation fails - Compile from source - [Follow this guide.](https://pimylifeup.com/raspberry-pi-opencv/)
* Many questions are answered on our Reddit release thread [here.](https://www.reddit.com/r/Hue/comments/i1ngqt/release_harmonize_project_sync_hue_lights_with/) New issues should be raised on GitLab.

# Contributions & License

Pull requests are encouraged and accepted! Whether you have some code changes or enhancements to the readme, feel free to open a pull request. Harmonize Project is licensed under [The Creative Commons Attribution-NonCommercial 4.0 International Public License.](https://creativecommons.org/licenses/by-nc/4.0/legalcode)

Development credits to [Matthew C. Pilsbury](https://matthewpilsbury.com) ([MCP Capital, LLC](http://mcpcapital.net)) and Ares N. Vlahos.

[![licensebuttons by-nc](https://licensebuttons.net/l/by-nc/3.0/88x31.png)](https://creativecommons.org/licenses/by-nc/4.0/legalcode)  [![ForTheBadge makes-people-smile](http://ForTheBadge.com/images/badges/makes-people-smile.svg)](https://matthewpilsbury.com) [![forthebadge](https://forthebadge.com/images/badges/pretty-risque.svg)](https://matthewpilsbury.com) [![forthebadge](https://forthebadge.com/images/badges/uses-badges.svg)](https://forthebadge.com) [![forthebadge](https://forthebadge.com/images/badges/built-with-resentment.svg)](https://www.wipo.int/amc/en/domains/search/text.jsp?case=D2020-0278)
