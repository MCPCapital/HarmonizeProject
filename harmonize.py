#!/usr/bin/python3

########################################
########## Harmonize Project ###########
##########        by         ###########
########## MCP Capital, LLC  ###########
########################################
# Github.com/MCPCapital/harmonizeproject
# Script Last Updated - Release 2.3
########################################
### -v to enable verbose messages     ##
### -g # to pre-select a group number ##
### -b # to pre-select a bridge by id ##
### -i # to pre-select bridge IP      ##
### -w # to pre-select video wait time #
### -f # to pre-select stream filename #
### -s # single light source optimized #
### -l # to adjust maximum brightness  #
########################################

import sys
import argparse
import requests 
import time
import json
import socket
import subprocess
import threading
import fileinput
import numpy as np
import cv2
import re

from pathlib import Path
from http_parser.parser import HttpParser
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
from termcolor import colored

# suppress SSL certificate verification warning
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

class MyListener(ServiceListener):
    bridgelist = []
    def update_service(self, zeroconf, type, name):
        print(f"INFO: Received Bridge mDNS update.")

    def remove_service(self, zeroconf, type, name):
        print(f"INFO: Bridge removed from mDNS network.")

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        self.bridgelist.append(info.parsed_addresses()[0])
        verbose("INFO: Detected %s via mDNS at IP address: %s" % (name, info.parsed_addresses()[0]))

zeroconf = Zeroconf()
listener = MyListener()

parser = argparse.ArgumentParser()
parser.add_argument("-v","--verbose", dest="verbose", action="store_true")
parser.add_argument("-g","--groupid", dest="groupid")
parser.add_argument("-b","--bridgeid", dest="bridgeid")
parser.add_argument("-i","--bridgeip", dest="bridgeip")
parser.add_argument("-s","--single_light", dest="single_light", action="store_true")
parser.add_argument("-w","--video_wait_time", dest="video_wait_time", type=float, default=5.0)
parser.add_argument("-f","--stream_filename", dest="stream_filename")
parser.add_argument("-l","--light_brightness", dest="light_brightness", type=int, default=30)

commandlineargs = parser.parse_args()

is_single_light = False

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    
def verbose(*args, **kwargs):
    if commandlineargs.verbose==True:
        print(*args, **kwargs)

######### Initialization Complete - Now lets try and connect to the bridge ##########

def findhue(): #Auto-find bridges on mDNS network
    try:
        browser = ServiceBrowser(zeroconf, "_hue._tcp.local.", listener)
    except (
        zeroconf.BadTypeInNameException,
        NotImplementedError,
        OSError,
        socket.error,
        zeroconf.NonUniqueNameException,
    ) as exc:
        print("ERROR: Cannot create mDNS service discovery browser: {}".format(exc))
        sys.exit(1)
    
    # wait half a second for mDNS discovery lookup
    time.sleep(0.5)
    
    if len(listener.bridgelist) == 1:
        print("INFO: Single Hue bridge detected on network via mDNS.")
        return listener.bridgelist[0]
    
    bridgelist = []
    if len(listener.bridgelist) == 0:
        print("INFO: Bridge not detected via mDNS lookup, will try via discovery method.")
        try:
            r = requests.get("https://discovery.meethue.com/")
        except:
            sys.exit("ERROR: Discovery method did not execute properly. Please try again later. Exiting application.")
        bridgelist = json.loads(r.text)
        
        if len(bridgelist) == 1:
            print("INFO: Single Hue bridge detected via network discovery.")
            return bridgelist[0]['internalipaddress']
        
        if commandlineargs.bridgeid is not None:
            for idx, b in enumerate(bridgelist):
                if b["id"] == commandlineargs.bridgeid:
                    return bridgelist[idx]['internalipaddress']
            sys.exit("ERROR: Bridge {} was not found".format(commandlineargs.bridgeid))
        elif commandlineargs.bridgeip is not None:
            for idx, b in enumerate(bridgelist):
                if b["internalipaddress"] == commandlineargs.bridgeip:
                    return commandlineargs.bridgeip
            sys.exit("ERROR: Bridge {} was not found".format(commandlineargs.bridgeip))
    
    # if multiple bridges detected via mDNS
    if len(listener.bridgelist)>1:
            print("Multiple bridges found via mDNS lookup. Key a number corresponding to the list of bridges below:")
            for index, value in enumerate(listener.bridgelist):
                print("[" + str(index+1) + "]:", value)

            if commandlineargs.bridgeip is not None:
                for idx, b in enumerate(listener.bridgelist):
                    if b == commandlineargs.bridgeip:
                        return commandlineargs.bridgeip
                sys.exit("ERROR: Bridge {} was not found".format(commandlineargs.bridgeip))
            else:
                bridge = int(input())
                return listener.bridgelist[bridge-1]
    
    # if multiple bridges detected via network discovery
    if len(bridgelist)>1:
            print("Multiple bridges found via network discovery. Key a number corresponding to the list of bridges below:")
            for index, value in enumerate(bridgelist):
                print("[" + str(index+1) + "]:", value)
            bridge = int(input())
            return bridgelist[bridge-1]['internalipaddress']     
    
    return None

print(colored('--- Starting Harmonize Project ---','green'))
hueip = findhue() or None
if hueip is None:
    sys.exit("ERROR: Hue bridge not found. Please ensure proper network connectivity and power connection to the hue bridge.")
verbose("INFO: Hue bridge located at:", hueip)

baseurl = "http://{}/api".format(hueip)
clientdata = []

verbose("Checking whether Harmonizer application is already registered (Looking for client.json file).")

def register():
    global clientdata
    print("INFO: Device not registered on bridge")
    payload = {"devicetype":"harmonizehue","generateclientkey":True}
    print("INFO: You have 60 seconds to press the large button on the bridge! Checking for button press every 5 seconds.")
    attempts = 1
    while attempts < 12:
        r = requests.post(("http://%s/api" % (hueip)), json.dumps(payload))
        bridgeresponse = json.loads(r.text)
        if  'error' in bridgeresponse[0]:
            print("WARNING {}: {}".format(attempts, bridgeresponse[0]['error']['description']))
        elif('success') in bridgeresponse[0]:
            # generate client.json file
            clientdata = bridgeresponse[0]["success"]
            f = open("client.json", "w")
            f.write(json.dumps(clientdata))
            f.close()
            print("INFO: Username and client key generated to access the bridge Entertainment API functionality.")
            break
        else:
            print("INFO: No response detected.")
        attempts += 1
        time.sleep(5)
    else:
        print("ERROR: Button press not detected, exiting application.")
        exit()

if Path("./client.json").is_file():
    f = open("client.json", "r")
    jsonstr = f.read()
    clientdata = json.loads(jsonstr)
    f.close()
    verbose("INFO: Client data found from client.json file.")
    setupurl = baseurl + "/" + clientdata['username']
    r = requests.get(url = setupurl)
    setupresponse = dict()
    setupresponse = json.loads(r.text)
    if  setupresponse.get('error'):
        verbose("INFO: Client data no longer valid.")
        register()
    else:
        verbose("INFO: Client data valid:", clientdata)
else:
    register()

verbose("Requesting bridge information...") 
r = requests.get(url = baseurl+"/config")
jsondata = r.json()
if jsondata["swversion"]<"1948086000": #Check if the bridge supports streaming via API v1/v2
    sys.exit("ERROR: Firmware software version on the bridge is outdated and does not support streaming on APIv1/v2. Upgrade it using Hue app. Software version must be 1.XX.194808600 or greater.")
else:
    verbose("INFO: The bridge is capable of streaming via APIv2. Firmware version {} detected...".format(jsondata["swversion"]))

######### We're connected! - Now lets find entertainment areas in the list of groups via API v2 ##########
print("Querying hue bridge for entertainment areas on local network.")
r_v2 = requests.get("https://{}/clip/v2/resource/entertainment_configuration".format(hueip), verify=False, headers={"hue-application-key":clientdata['username']})
json_data_v2 = json.loads(r_v2.text)
#print(json_data_v2)
groupid = commandlineargs.groupid

if len(json_data_v2['data'])==0: #No entertainment areas or null = exit
    if groupid is not None:
        sys.exit("Entertainment area specified in command line argument groupid not found.")
    else:
        sys.exit("No Entertainment areas found. Please ensure at least one has been created in the Hue App.")

if len(json_data_v2['data'])==1:
    groupid = re.findall("\d+", json_data_v2['data'][0]['id_v1'])[0]
    entertainment_id = json_data_v2['data'][0]['id']
    print("groupid = ",groupid)

if len(json_data_v2['data'])>1:

    print("Multiple Entertainment areas found. Type in the number corresponding to the area you wish to use and hit Enter. (You can specify which with the optional argument --groupid ).")
    for value in json_data_v2['data']:
        print("[ " + str(re.findall("\d+",value['id_v1'])[0]) + " ]: " + str(value['name']))
    if groupid is None:
        groupid = input()

print("Using Entertainment area with group_id: {}".format(groupid))

# find entertainment_id from legacy group_id
for value in json_data_v2['data']:
    if groupid == re.findall("\d+",value['id_v1'])[0]:
        entertainment_id = str(value['id'])
        verbose("Selected Entertainment UDID:",entertainment_id)

#### Lets get the lights & their locations in our selected group and enable streaming ######
r_v2 = requests.get("https://{}/clip/v2/resource/entertainment_configuration/{}".format(hueip,entertainment_id), verify=False, headers={"hue-application-key":clientdata['username']}) # via APIv2
lights_data = json.loads(r_v2.text)
lights_dict = dict()

for index, value in enumerate(lights_data['data'][0]['channels']):
    #print(str(index) + " and " + str(value['position']))
    lights_dict.update({str(index): [value['position']['x'],value['position']['y'], value['position']['z']]})
verbose("INFO: {} light(s) found in selected Entertainment area. Locations [x,y,z] are as follows: \n".format(len(lights_dict)), lights_dict)

# Exit streaming application if number of lights is greater than 20
if len(lights_dict) > 20:
   sys.exit("ERROR: {} light(s) found. The maximum allowable is up to 20 per Entertainment area. Exiting application.".format(len(lights_dict)))

# Retrieve PSK identify for APIv2 
r_v2 = requests.get("https://{}/auth/v1".format(hueip), verify=False, headers={"hue-application-key":clientdata['username']}) # via APIv2
hue_app_id = r_v2.headers['hue-application-id']
verbose("Hue application id:",hue_app_id)

##### Setting up streaming service and calling the DTLS handshake command ######
verbose("Enabling streaming to your Entertainment area") #Allows us to send UPD packets to port 2100
r_v2 = requests.put("https://{}/clip/v2/resource/entertainment_configuration/{}".format(hueip,entertainment_id), json={"action":"start"}, verify=False, headers={"hue-application-key":clientdata['username']}) # via APIv2
jsondata = r_v2.json()
verbose(jsondata)

###### This is used to execute the command near the bottom of this document to create the DTLS handshake with the bridge on port 2100
def execute(cmd):
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True)
    verbose("Executing send commands... Cross your fingers")
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)
        
######### Prepare the messages' vessel for the RGB values we will insert
bufferlock = threading.Lock()
stopped = False
def stdin_to_buffer():
    for line in fileinput.input():
        print(line)
        if stopped:
            break

######################################################
################# Setup Complete #####################
######################################################

######################################################
### Scaling light locations and averaging colors #####
######################################################

########## Scales up locations to identify the nearest pixel based on lights' locations #######
def averageimage():
    for x, coords in lights_dict.items():
        coords[0] = ((coords[0])+1) * w//2 #Translates x value and resizes to video aspect ratio
        coords[2] = (-1*(coords[2])+1) * h//2 #Flips y, translates, and resize to vid aspect ratio

    scaled_locations = list(lights_dict.items()) #Makes it a list of locations by light
    verbose("INFO: Lights and locations (in order) scaled using video resolution input are as follows: ", scaled_locations)
  
#### This section assigns light locations to variable light1,2,3...etc. in JSON order
    avgsize = w/2 + h/2
    verbose('INFO: Average number of total pixels of video area to be analyzed is:', avgsize)
    breadth = .15 #approx percent of the screen outside the location to capture
    dist = int(breadth*avgsize) #Proportion of the pixels we want to average around in relation to the video size
    verbose('INFO: Distance in pixels from relative location is:', dist)

    global cords #array of coordinates
    global bounds #array of bounds for each coord, each item is formatted as [top, bottom, left, right]
    
    #initialize the arrays
    cords = {}
    bounds = {}
    for num, cds in scaled_locations:
        cords[num] = cds
        bds = [cds[2] - dist, cds[2] + dist, cds[0] - dist, cds[0] + dist]
        bds = list(map(int, bds))
        bds = list(map(lambda x: 0 if x < 0 else x, bds))
        bounds[num] = bds
   
    global rgb,rgb_bytes #array of rgb values, one for each light
    rgb = {}
    rgb_bytes = {}
    area = {}

# Constantly sets RGB values by location via taking average of nearby pixels
    while not stopped:
        for x, bds in bounds.items():
            area[x] = rgbframe[bds[0]:bds[1], bds[2]:bds[3], :]
            rgb[x] = cv2.mean(area[x])
        for x, c in rgb.items():
            rgb_bytes[x] = bytearray([int(c[0]/2), int(c[0]/2), int(c[1]/2), int(c[1]/2), int(c[2]/2), int(c[2]/2),] )
            

######################################################
############ Video Capture Setup #####################
######################################################

######### Initialize the video device for capture using OpenCV
def init_video_capture():
    try:
        if commandlineargs.stream_filename is None:
            #cap = cv2.VideoCapture(0,cv2.CAP_FFMPEG) #variable cap is our raw video input
            cap = cv2.VideoCapture(0,cv2.CAP_GSTREAMER) #variable cap is our raw video input
        else:
            cap = cv2.VideoCapture(commandlineargs.stream_filename) #capture from given file/url
    except:
        sys.exit("ERROR: Issue enabling video capture")
    if cap.isOpened(): # Try to get the first frame
        verbose('INFO: Capture device opened using OpenCV.')
    else: #Makes sure we can access the device
        sys.exit('ERROR: Unable to open capture device.') #quit
    return cap

######################################################
############ Frame Grabber ###########################
######################################################

######### Now that weve defined our RGB values as bytes, we define how we pull values from the video analyzer output
def cv2input_to_buffer(): ######### Section opens the device, sets buffer, pulls W/H
    global w,h,rgbframe, channels
    cap = init_video_capture()
    w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  # gets video width
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) # gets video height
    verbose("INFO: Video frame size (W by H): {} by {}".format(w, h)) #prints video frame size

########## This section loops & pulls re-colored frames and alwyas get the newest frame 
    cap.set(cv2.CAP_PROP_BUFFERSIZE,0) # No frame buffer to avoid lagging, always grab newest frame
    ct = 0 ######ct code grabs every X frame as indicated below
    while not stopped:
        ct += 1
        ret = cap.grab() #constantly grabs frames
        if ct % 1 == 0: # Skip frames (1=don't skip,2=skip half,3=skip 2/3rds)
            ret, bgrframe = cap.retrieve() #processes most recent frame
            if is_single_light:
                channels = cv2.mean(bgrframe)
            else:
                bgrframe = adjust_brightness(bgrframe,commandlineargs.light_brightness)
                rgbframe = cv2.cvtColor(bgrframe, cv2.COLOR_BGR2RGB) #corrects BGR to RGB
                #verbose('BGrframe is :',bgrframe)
            if not ret: break

def adjust_brightness(raw, value):
    hsv = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    lim = 255 - value
    v[v > lim] = 255
    v[v <= lim] += value

    final_hsv = cv2.merge((h, s, v))
    raw = cv2.cvtColor(final_hsv, cv2.COLOR_HSV2BGR)
    return raw


######################################################
############## Sending the messages ##################
######################################################

######### This is where we define our message format and insert our light#s, RGB values, and X,Y,Brightness ##########
def buffer_to_light(proc): #Potentially thread this into 2 processes?
    time.sleep(1.5) #Hold on so DTLS connection can be made & message format can get defined
    while not stopped:
        bufferlock.acquire()
        
        message = bytes('HueStream','utf-8') + b'\2\0\0\0\0\0\0' + bytes(entertainment_id,'utf-8')

        if is_single_light:
            single_light_bytes = bytearray([int(channels[2]/2), int(channels[2]/2), int(channels[1]/2), int(channels[1]/2), int(channels[0]/2), int(channels[0]/2),] ) # channels corrected here from BGR to RGB
            message += bytes(chr(int(1)), 'utf-8') + single_light_bytes
        else:
            for i in rgb_bytes:
                message += bytes(chr(int(i)), 'utf-8') + rgb_bytes[i]
 
        bufferlock.release()
        proc.stdin.write(message.decode('utf-8','ignore'))
        time.sleep(.015) #0.01 to 0.02 (slightly under 100 or 50 messages per sec // or (.015 = ~66.6))
        proc.stdin.flush()
        #verbose('Wrote message and flushed. Briefly waiting') #This will verbose after every send, spamming the console.

######################################################
############### Initialization Area ##################
######################################################

######### Section executes video input and establishes the connection stream to bridge ##########
#w,h,rgbframe, channels

try:
    try:
        threads = list()
        print(colored('Starting computer vision engine...','cyan'))
        verbose("OpenCV version:",cv2.__version__)
        try:
            if commandlineargs.stream_filename is None:
                subprocess.check_output("ls -ltrh /dev/video0",shell=True)
                print("--- INFO: Detected video capture card on /dev/video0 ---")
        except subprocess.CalledProcessError:                                                                                                  
            print("--- ERROR: Video capture card not detected on /dev/video0 ---")
        else:
            # Check to see if video stream is actually being captured properly before continuing.
            cap = init_video_capture()

            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  # gets video width
            try: w
            except NameError: sys.exit("Error capturing stream. Exiting application.")
            cap.release()

            t = threading.Thread(target=cv2input_to_buffer)
            t.start()
            threads.append(t)
            print("Initializing video frame grabber...")
            time.sleep(commandlineargs.video_wait_time) # wait sufficiently until rgbframe is defined
            if (commandlineargs.single_light is True) and (len(lights_dict)==1):
                is_single_light = True
                print("Enabled optimization for single light source") # averager thread is not utilized
            else:
                is_single_light = False
                verbose("Starting image analyzer...")
                t = threading.Thread(target=averageimage)
                t.start()
                threads.append(t)
            time.sleep(0.50) # wait sufficiently until rgb_bytes is defined from above thread
            verbose("Opening an SSL packet stream to lights on network...")
            cmd = ["openssl","s_client","-dtls1_2","-cipher","PSK-AES128-GCM-SHA256","-psk_identity",hue_app_id,"-psk",clientdata['clientkey'], "-connect", hueip+":2100"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            t = threading.Thread(target=buffer_to_light, args=(proc,))
            t.start()
            threads.append(t)
            print(colored('Press Return to stop streaming.','yellow'))
            input() # Allow us to exit easily
            stopped=True
            for t in threads:
                t.join()
    except Exception as e:
        print(e)
        stopped=True

finally: #Turn off streaming to allow normal function immedietly
    zeroconf.close()
    print("Disabling streaming on Entertainment area...")
    r = requests.put("https://{}/clip/v2/resource/entertainment_configuration/{}".format(hueip,entertainment_id), json={"action":"stop"}, verify=False, headers={"hue-application-key":clientdata['username']})
    jsondata = r.json()
    verbose(jsondata)
