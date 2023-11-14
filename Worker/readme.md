# How to compile

* Install the correct Python version for the Blender version you are targeting. Blender prints the required version in the Python console, e.g. Python 3.7.0 for Blender 2.80
* Run the compilation script for your platform: build.bat on Windows, build.sh on Linux
* The resulting nodepreview_worker.*.pyd is moved into the parent directory, where it can be imported from the Python addon
