:: Python 3.7 for Blender 2.83-2.92

call C:\Users\Simon\AppData\Local\Programs\Python\Python37\python.exe setup.py build_ext --inplace
if ERRORLEVEL 1 pause
move /Y nodepreview_worker.*.pyd ..
rmdir /S /Q .\build


:: Python 3.9 for Blender 2.93

call C:\Users\Simon\AppData\Local\Programs\Python\Python39\python.exe setup.py build_ext --inplace
if ERRORLEVEL 1 pause
move /Y nodepreview_worker.*.pyd ..
rmdir /S /Q .\build


:: Python 3.10 for Blender 3.1

call C:\Users\Simon\AppData\Local\Programs\Python\Python310\python.exe setup.py build_ext --inplace
if ERRORLEVEL 1 pause
move /Y nodepreview_worker.*.pyd ..
rmdir /S /Q .\build