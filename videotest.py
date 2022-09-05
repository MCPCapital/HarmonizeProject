#!/usr/bin/python3

import cv2             # Script Last Updated - Release 1.1.2
import argparse

print("Press ESC to exit.")

parser = argparse.ArgumentParser()
parser.add_argument("-f","--stream_filename", dest="stream_filename")
commandlineargs = parser.parse_args()

cv2.namedWindow("preview")

if commandlineargs.stream_filename is None:
    vc = cv2.VideoCapture(0)
else:
    vc = cv2.VideoCapture(commandlineargs.stream_filename)

if vc.isOpened(): # try to get the first frame
    rval, frame = vc.read()
else:
    rval = False

while rval:
    cv2.imshow("preview", frame)
    rval, frame = vc.read()
    key = cv2.waitKey(20)
    if key == 27: # exit on ESC
        break
cv2.destroyWindow("preview")
