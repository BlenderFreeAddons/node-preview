/*
    This file is part of NodePreview.
    Copyright (C) 2021 Simon Wendsche

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#include <Python.h>

#include <cstdio>
#include <string>
#include <cctype>

#ifdef _WIN32
    // Note: has to be defined before including stb_image.h
    #define STBI_WINDOWS_UTF8
#endif

#define STB_IMAGE_IMPLEMENTATION
#include "deps/stb_image.h"
#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include "deps/stb_image_resize.h"
#define TINYEXR_IMPLEMENTATION
#include "deps/tinyexr.h"

#define MODULE_NAME_STR "nodepreview_worker"


static bool load_image(const std::string &filepath, char *target, size_t target_size) {
    int width = -1;
    int height = -1;
    int channelCount = -1;
    const int desiredChannels = 0;
    unsigned char *image = stbi_load(filepath.c_str(), &width, &height,
                                     &channelCount, desiredChannels);

    if (!image) {
        printf("[NodePreview] Could not load image from path: %s\n", filepath.c_str());
        return true;
    }

    const int imagePixelsCount = width * height * channelCount;

    if (imagePixelsCount != target_size) {
        const std::string msg = "Mismatch between target buffer size ("
            + std::to_string(target_size)
            + ") and size of loaded image ("
            + std::to_string(imagePixelsCount)
            + ")";
        PyErr_SetString(PyExc_ValueError, msg.c_str());
        stbi_image_free(image);
        return false;
    }

    // Can't simply copy because it's uchar vs char
    char *trgPtr = target;
    for (const unsigned char *p = image; p < image + imagePixelsCount; ) {
        *trgPtr++ = (*p++) / 2;
    }

    stbi_image_free(image);
    return true;
}


static PyObject *worker_load_image_array(PyObject *self, PyObject *args) {
    Py_buffer array;
    PyObject *filepath_raw = nullptr;

    if (!PyArg_ParseTuple(args, "w*O&", &array, PyUnicode_FSConverter, static_cast<void *>(&filepath_raw))) {
        return nullptr;
    }

    std::string filepath(PyBytes_AsString(filepath_raw));
    Py_XDECREF(filepath_raw);

    const bool success = load_image(filepath, static_cast<char *>(array.buf), array.len);
    PyBuffer_Release(&array);

    if (success) {
        Py_RETURN_NONE;
    } else {
        return nullptr;
    }
}


static PyObject *worker_load_image_scaled(PyObject *self, PyObject *args) {
    PyObject *filepath_raw = nullptr;
    int max_size = -1;

    if (!PyArg_ParseTuple(args, "O&i", PyUnicode_FSConverter, static_cast<void *>(&filepath_raw), &max_size)) {
        return nullptr;
    }

    std::string filepath(PyBytes_AsString(filepath_raw));
    Py_XDECREF(filepath_raw);

    // Load image (always as RGBA because Blender can't handle anything else anyway)
    int width = -1;
    int height = -1;
    int originalChannelCount = -1;
    const int channelCount = 4;
    float *bigImage = stbi_loadf(filepath.c_str(), &width, &height,
                                 &originalChannelCount, channelCount);

    if (!bigImage) {
        // stb_image could not load the file, try loading it as OpenEXR
        // Note: LoadEXR always loads RGBA (4 channels)
        const char* err = nullptr;
        originalChannelCount = 4;
        const int ret = LoadEXR(&bigImage, &width, &height, filepath.c_str(), &err);
        FreeEXRErrorMessage(err);

        if (ret != TINYEXR_SUCCESS) {
            const std::string msg = "[NodePreview Worker] Could not load image:" + filepath;
            PyErr_SetString(PyExc_ValueError, msg.c_str());
            return nullptr;
        }
    }

    int thumbWidth;
    int thumbHeight;

    if (width == height) {
        thumbWidth = max_size;
        thumbHeight = max_size;
    } else if (width < height) {
        const double aspect = static_cast<double>(width) / height;
        thumbWidth = int(max_size * aspect);
        thumbHeight = max_size;
    } else {
        const double aspect = static_cast<double>(height) / width;
        thumbWidth = max_size;
        thumbHeight = int(max_size * aspect);
    }

    // Scale down
    float *smallImage = new float[thumbWidth * thumbHeight * channelCount];
    const int inputStride = 0;
    const int outputStride = 0;
    stbir_resize_float(bigImage, width, height, inputStride,
                       smallImage, thumbWidth, thumbHeight, outputStride,
                       channelCount);
    stbi_image_free(bigImage);

    const int resultListSize = thumbWidth * thumbHeight * channelCount;

    PyObject *resultList = PyList_New(resultListSize);

    // Copy into Python list
    // For Blender, the image needs to be mirrored vertically, which is done here
    for (int y = 0; y < thumbHeight; ++y) {
        for (int x = 0; x < thumbWidth; ++x) {
            const int sourceIndex = (y * thumbWidth * channelCount) + (x * channelCount);
            const int mirroredY = thumbHeight - y - 1;
            const int targetIndex = (mirroredY * thumbWidth * channelCount) + (x * channelCount);

            for (int channel = 0; channel < channelCount; ++channel) {
                PyList_SET_ITEM(resultList, targetIndex + channel, PyFloat_FromDouble(smallImage[sourceIndex + channel]));
            }
        }
    }

    delete[] smallImage;

    return Py_BuildValue("(Oii)", resultList, thumbWidth, thumbHeight);
}

static bool isAlphaNumeric(unsigned char c) {
    return std::isdigit(c) || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
}

static PyObject *worker_to_valid_identifier(PyObject *self, PyObject *args) {
    PyObject *name_raw = nullptr;

    if (!PyArg_ParseTuple(args, "O&", PyUnicode_FSConverter, static_cast<void *>(&name_raw))) {
        return nullptr;
    }

    std::string name(PyBytes_AsString(name_raw));
    Py_XDECREF(name_raw);

    std::string result("n");  // Identifiers must start with a letter, not a digit

    for (int i = 0; i < name.size(); ++i) {
        const unsigned char c = name[i];
        if (isAlphaNumeric(c)) {
            result += c;
        } else {
            // Not alphanumeric, convert it to a numeric representation
            result += "_" + std::to_string(c);
        }
    }

    return Py_BuildValue("s", result.c_str());
}

// ----------------------------------------------------------------------------
// Boilerplate
// ----------------------------------------------------------------------------

static PyMethodDef WorkerMethods[] = {
    {"load_image_array", worker_load_image_array, METH_VARARGS,
     ""},
    {"load_image_scaled", worker_load_image_scaled, METH_VARARGS,
     ""},
    {"to_valid_identifier", worker_to_valid_identifier, METH_VARARGS,
     ""},
    {nullptr, nullptr, 0, nullptr} // Sentinel
};

static struct PyModuleDef workermodule = {
    PyModuleDef_HEAD_INIT,
    MODULE_NAME_STR,
    nullptr, /* module documentation, may be NULL */
    -1, /* size of per-interpreter state of the module,
         * or -1 if the module keeps state in global variables. */
    WorkerMethods
};

PyMODINIT_FUNC PyInit_nodepreview_worker(void) {
    return PyModule_Create(&workermodule);
}

// I don't think this will ever be called
int main(int argc, char *argv[]) {
    wchar_t *program = Py_DecodeLocale(argv[0], nullptr);
    if (program == nullptr) {
        fprintf(stderr, "Fatal error: cannot decode argv[0]\n");
        exit(1);
    }

    /* Add a built-in module, before Py_Initialize */
    PyImport_AppendInittab(MODULE_NAME_STR, PyInit_nodepreview_worker);

    /* Pass argv[0] to the Python interpreter */
    Py_SetProgramName(program);

    /* Initialize the Python interpreter.  Required. */
    Py_Initialize();

    /* Optionally import the module; alternatively,
     * import can be deferred until the embedded script
     * imports it. */
    PyImport_ImportModule(MODULE_NAME_STR);

    // ...

    PyMem_RawFree(program);
    return 0;
}
