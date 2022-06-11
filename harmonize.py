#!/usr/bin/python3

########################################
########## Harmonize Project ###########
##########        by         ###########
########## MCP Capital, LLC  ###########
########################################
# Github.com/MCPCapital/harmonizeproject
# Script Last Updated - Release 1.3.0
########################################
### -v to enable verbose messages     ##
### -g # to pre-select a group number ##
### -b # to pre-select a bridge by id ##
### -s # single light source optimized #
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

from pathlib import Path
from http_parser.parser import HttpParser
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

class MyListener(ServiceListener):
    bridgelist = []
    def update_service(self, zeroconf, type, name):
        print(f"Bridge updated")

    def remove_service(self, zeroconf, type, name):
        print(f"Bridge removed")

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        self.bridgelist.append(info.parsed_addresses()[0])
        print("INFO: Detected %s via mDNS at IP address: %s" % (name, info.parsed_addresses()[0]))

zeroconf = Zeroconf()
listener = MyListener()

parser = argparse.ArgumentParser()
parser.add_argument("-v","--verbose", dest="verbose", action="store_true")
parser.add_argument("-g","--groupid", dest="groupid")
parser.add_argument("-b","--bridgeid", dest="bridgeid")
parser.add_argument("-s","--single_light", dest="single_light", action="store_true")
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
    
    # wait 1 sec for mDNS discovery lookup
    time.sleep(1)
    
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
    
    # if multiple bridges detected via mDNS
    if len(listener.bridgelist)>1:
            print("Multiple bridges found via mDNS lookup. Key a number corresponding to the list of bridges below:")
            for index, value in enumerate(listener.bridgelist):
                print("[" + str(index+1) + "]:", value)
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

print("--- Starting Harmonizer application ---")
hueip = findhue() or None
if hueip is None:
    sys.exit("ERROR: Hue bridge not found. Please ensure proper network connectivity and power connection to the hue bridge.")
verbose("INFO: Hue bridge located at:", hueip)

verbose("Checking whether Harmonizer application is already registered (Looking for client.json file).") #Check if the username and client key have already been saved

def register():
    print("INFO: Device not registered on bridge")
    payload = {"devicetype":"harmonizehue","generateclientkey":True}
    print("INFO: You have 45 seconds to push the button! Checking for button press every 5 seconds.")
    attempts = 1
    while attempts < 10:
        r = requests.post(("http://%s/api" % (hueip)), json.dumps(payload))
        bridgeresponse = json.loads(r.text)
        if  'error' in bridgeresponse[0]:
            print(attempts,"WARNING: {0}".format(bridgeresponse[0]['error']['description']))
        elif('success') in bridgeresponse[0]:
            clientdata = bridgeresponse[0]["success"]
            did_get_username = True
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
    
    global baseurl, base_url_v2
    baseurl = "http://{}/api".format(hueip)
    base_url_v2 = "https://{}".format(hueip)
    
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
if jsondata["apiversion"]<"1.22": #Ensure the bridge supports streaming via API v1
    sys.exit("ERROR: Firmware API version on the bridge is outdated. Upgrade it using the Hue app. API version must be 1.22 or greater.")
verbose("INFO: The bridge is capable of streaming via APIv1. API version {} detected...".format(jsondata["apiversion"]))
if jsondata["swversion"]<"1948086000": #Check if the bridge supports streaming via API v2
    print("DEPRECATION NOTICE: Firmware software version on the bridge is outdated and does not support APIv2. Consider upgrading it using Hue app. Software version must be 194808600 or greater.")
else:
    verbose("INFO: The bridge is capable of streaming via APIv2. Firmware version {} detected...".format(jsondata["swversion"]))

######### We're connected! - Now lets find entertainment areas in the list of groups ##########
r = requests.get(url = baseurl+"/{}/groups".format(clientdata['username']))
jsondata = r.json()

groups = dict()
groupid = commandlineargs.groupid

if groupid is not None:
    verbose("Checking for entertainment group {}".format(groupid))
else:
    verbose("Checking for entertainment groups (not none)")

for k in jsondata:  #These 3 sections isolate Entertainment areas from normal groups (like rooms)
    if jsondata[k]["type"]=="Entertainment":
        if groupid is None or k==groupid:
            groups[k] = jsondata[k]

if len(groups)==0: #No groups or null = exit
    if groupid is not None:
        sys.exit("Entertainment group not found, set one up in the Hue App according to the instructions on github.")
    else:
        sys.exit("Entertainment group not found, set one up in the Hue App according to the instructions on github.")

if len(groups)>1:
    eprint("Multiple entertainment groups found (", groups,") specify which with --groupid")
    for g in groups:
        eprint("{} = {}".format(g,groups[g]["name"]))
    groupid = input()
    print("You selected groupid ", groupid)
    #sys.exit()

if groupid is None:
    groupid=next(iter(groups))
verbose("Using groupid={}".format(groupid))

#### Lets get the lights & their locations in our selected group and enable streaming ######
for l in jsondata:
    r = requests.get(url = baseurl+"/{}/groups/{}".format(clientdata['username'],groupid))
    jsondata = r.json()
    light_locations = dict()
    light_locations = jsondata['locations']
verbose("These are the lights and locations found: \n", light_locations)

##### Setting up streaming service and calling the DTLS handshake command ######
verbose("Enabling streaming on your Entertainment area") #Allows us to send UPD to port 2100
r = requests.put(url = baseurl+"/{}/groups/{}".format(clientdata['username'],groupid),json={"stream":{"active":True}})
jsondata = r.json()
######This is used to execute the command near the bottom of this document to create the DTLS handshake with the bridge on port 2100
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

def averageimage():
########## Scales up locations to identify the nearest pixel based on lights' locations #######
    time.sleep(1.2) #wait for video size to be defined
    for x, coords in light_locations.items():
        coords[0] = ((coords[0])+1) * w//2 #Translates x value and resizes to video aspect ratio
        coords[2] = (-1*(coords[2])+1) * h//2 #Flips y, translates, and resize to vid aspect ratio
        
    #for x, y in light_locations.items(): #Defines locations by light
        #time.sleep(.01)
    scaled_locations = list(light_locations.items()) #Makes it a list of locations by light
    verbose("Lights and locations (in order) on TV array after math are: ", scaled_locations)
  
#### This section assigns light locations to variable light1,2,3...etc. in JSON order
    avgsize = w/2 + h/2
    verbose('avgsize is', avgsize)
    breadth = .15 #approx percent of the screen outside the location to capture
    dist = int(breadth*avgsize) #Proportion of the pixels we want to average around in relation to the video size
    verbose('Distance from relative location is: ', dist)

    global cords #array of coordinates
    global bounds #array of bounds for each coord, each item is formatted as [top, bottom, left, right]
    
    #initialize the arrays
    cords = {}
    bounds = {}
    for num, cds in scaled_locations:
        #cords.append(cds)
        cords[num] = cds
        bds = [cds[2] - dist, cds[2] + dist, cds[0] - dist, cds[0] + dist]
        bds = list(map(int, bds))
        bds = list(map(lambda x: 0 if x < 0 else x, bds))
        #bounds.append(bds)
        bounds[num] = bds
   
    global rgb,rgb_bytes #array of rgb values, one for each light
    rgb = {}
    rgb_bytes = {}
    area = {}

# Constantly sets RGB values by location via taking average of nearby pixels
    while not stopped:
        for x, bds in bounds.items():
            #area[x] = rgbframe[bds[2]:bds[3], bds[0]:bds[1], :]
            area[x] = rgbframe[bds[0]:bds[1], bds[2]:bds[3], :]
            rgb[x] = cv2.mean(area[x])
        for x, c in rgb.items():
            rgb_bytes[x] = bytearray([int(c[0]/2), int(c[0]/2), int(c[1]/2), int(c[1]/2), int(c[2]/2), int(c[2]/2),] )
            

######################################################
############ Video Capture Setup #####################
######################################################

######### Now that weve defined our RGB values as bytes, we define how we pull values from the video analyzer output
def cv2input_to_buffer(): ######### Section opens the device, sets buffer, pulls W/H
    global w,h,rgbframe, channels
    cap = cv2.VideoCapture(0) #variable cap is our raw video input
    if cap.isOpened(): # Try to get the first frame
        verbose('Capture Device Opened')
    else: #Makes sure we can access the device
        sys.exit('Unable to open Capture Device') #quit
    w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  # gets video width
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) # gets video height
    verbose('Video Shape is: ', w, h) #prints video shape

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
                rgbframe = cv2.cvtColor(bgrframe, cv2.COLOR_BGR2RGB) #corrects BGR to RGB
                #verbose('BGrframe is :',bgrframe)
            if not ret: break

######################################################
############## Sending the messages ##################
######################################################

######### This is where we define our message format and insert our light#s, RGB values, and X,Y,Brightness ##########
def buffer_to_light(proc): #Potentially thread this into 2 processes?
    time.sleep(1.5) #Hold on so DTLS connection can be made & message format can get defined
    while not stopped:
        bufferlock.acquire()
        
        message = bytes('HueStream','utf-8') + b'\1\0\0\0\0\0\0'
        if is_single_light:
            single_light_bytes = bytearray([int(channels[2]/2), int(channels[2]/2), int(channels[1]/2), int(channels[1]/2), int(channels[0]/2), int(channels[0]/2),] ) # channels corrected here from BGR to RGB
            message += b'\0\0' + bytes(chr(int(1)), 'utf-8') + single_light_bytes
        else:
            for i in rgb_bytes:
                message += b'\0\0' + bytes(chr(int(i)), 'utf-8') + rgb_bytes[i]
 
        bufferlock.release()
        proc.stdin.write(message.decode('utf-8','ignore'))
        time.sleep(.01) #0.01 to 0.02 (slightly under 100 or 50 messages per sec // or (.015 = ~66.6))
        proc.stdin.flush()
        #verbose('Wrote message and flushed. Briefly waiting') #This will verbose after every send, spamming the console.

######################################################
############### Initialization Area ##################
######################################################

######### Section executes video input and establishes the connection stream to bridge ##########
try:
    try:
        threads = list()
        print("Starting computer vision engine...")
        try:
            subprocess.check_output("ls -ltrh /dev/video0",shell=True)
        except subprocess.CalledProcessError:                                                                                                  
            print("--- ERROR: Video capture card not detected on /dev/video0 ---")
        else:
            print("--- INFO: Detected video capture card on /dev/video0 ---")
            t = threading.Thread(target=cv2input_to_buffer)
            t.start()
            threads.append(t)
            time.sleep(.75)
            if (commandlineargs.single_light is True) and (len(light_locations)==1):
                is_single_light = True
                print("Enabled optimization for single light source") # averager thread is not utilized
            else:
                is_single_light = False
                verbose("Starting image averager...")
                t = threading.Thread(target=averageimage)
                t.start()
                threads.append(t)
            time.sleep(.25) #Initialize and find bridge IP before creating connection
            verbose("Opening SSL stream to lights...")
            cmd = ["openssl","s_client","-dtls1_2","-cipher","PSK-AES128-GCM-SHA256","-psk_identity",clientdata['username'],"-psk",clientdata['clientkey'], "-connect", hueip+":2100"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            t = threading.Thread(target=buffer_to_light, args=(proc,))
            t.start()
            threads.append(t)

            input("Press return to stop\n") # Allow us to exit easily
            stopped=True
            for t in threads:
                t.join()
    except Exception as e:
        print(e)
        stopped=True

finally: #Turn off streaming to allow normal function immedietly
    zeroconf.close()
    print("Disabling streaming on Entertainment area")
    r = requests.put(url = baseurl+"/{}/groups/{}".format(clientdata['username'],groupid),json={"stream":{"active":False}}) 
    jsondata = r.json()
    verbose(jsondata)
