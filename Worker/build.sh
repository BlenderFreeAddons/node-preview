#!/bin/bash

# Python 3.7 for Blender 2.83-2.92

python3.7 setup.py build_ext --inplace
mv nodepreview_worker.*.so ..
rm -r ./build


# Python 3.9 for Blender 2.93

python3.9 setup.py build_ext --inplace
mv nodepreview_worker.*.so ..
rm -r ./build


# Python 3.10 for Blender 3.1

python3.10 setup.py build_ext --inplace
mv nodepreview_worker.*.so ..
rm -r ./build
