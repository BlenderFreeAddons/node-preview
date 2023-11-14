#
#     This file is part of NodePreview.
#     Copyright (C) 2021 Simon Wendsche
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.

import bpy
import bpy_extras

import threading
import queue
from multiprocessing.connection import Client
from array import array
from time import time, perf_counter
import os
import numpy as np

from . import THUMB_CHANNEL_COUNT, messages, get_image_linking_info, make_unique_image_name
from . import nodepreview_worker


jobs = queue.LifoQueue()
results = queue.SimpleQueue()
images_failed_to_link = queue.SimpleQueue()
node_timestamps = {}
free_requested = False
stop_requested = False
current_blend_abspath = ""


def background_print(*args, **kwargs):
    print("[NodePreview BG Process]", *args, **kwargs)


def free():
    """ Must be executed from main thread! """
    background_print("Freeing ressources")
    images = bpy.data.images
    for image in images:
        images.remove(image)

    node_timestamps.clear()

    # TODO better thread-safe way to clear a SimpleQueue?
    while not images_failed_to_link.empty():
        try:
            images_failed_to_link.get(block=False)
        except queue.Empty:
            pass


def watcher_func(wakeup_condition, port, authkey):
    with Client(("localhost", port), authkey=authkey) as connection:
        try:
            connection.send((messages.BACKGROUND_PROCESS_READY, None))

            while True:
                # background_print("Listener: polling")
                if connection.poll(timeout=0.05):
                    try:
                        msg = connection.recv()
                        tag, data = msg
                    except EOFError as error:
                        background_print(error)
                        tag = messages.STOP

                    if tag == messages.NEW_JOB:
                        with wakeup_condition:
                            jobs.put(data)
                            wakeup_condition.notify()
                    elif tag == messages.NEW_BLEND_ABSPATH:
                        global current_blend_abspath
                        current_blend_abspath = data
                        background_print("New .blend abspath:", current_blend_abspath)
                    elif tag == messages.FREE_RESSOURCES:
                        with wakeup_condition:
                            global free_requested
                            free_requested = True
                            wakeup_condition.notify()
                    elif tag == messages.STOP:
                        background_print("Listener: Stopping")
                        break

                while not results.empty():
                    try:
                        result = results.get(block=False)
                        connection.send((messages.JOB_DONE, result))
                    except queue.Empty:
                        pass

                while not images_failed_to_link.empty():
                    try:
                        image_names = images_failed_to_link.get(block=False)
                        connection.send((messages.IMAGES_FAILED_TO_LINK, image_names))
                    except queue.Empty:
                        pass

        except ConnectionResetError as error:
            background_print(error)

    with wakeup_condition:
        # No lock required because this operation is atomic in CPython
        global stop_requested
        stop_requested = True
        wakeup_condition.notify()


def run(port, authkey):
    global free_requested

    wakeup_condition = threading.Condition()

    watcher = threading.Thread(target=watcher_func, args=(wakeup_condition, port, authkey))
    watcher.start()

    while True:
        with wakeup_condition:
            while jobs.empty() and not stop_requested and not free_requested:
                wakeup_condition.wait()

        if stop_requested:
            break

        if free_requested:
            free()
            free_requested = False

        try:
            job = jobs.get(block=False)

            start = perf_counter()
            success, result = do(job)

            if success:
                elapsed = perf_counter() - start
                background_print("job done in %.3f s" % elapsed)
                results.put(result)
        except queue.Empty:
            continue

    watcher.join()


def do(job):
    (
        node_key,
        script,
        images_to_load,
        images_to_link,
        image_info,
        blend_abspath,
        thumb_path,
        thumb_resolution,
        timestamp
    ) = job

    # print("\nScript: --------------------\n")
    # print(node_key, "\n")
    # print("import bpy")
    # print(script)
    # print("--------------------\n")

    try:
        last_timestamp = node_timestamps[node_key]
        if timestamp < last_timestamp:
            # Job is outdated, ignore it (a newer job was already completed)
            return False, None
    except KeyError:
        pass

    if blend_abspath != current_blend_abspath:
        # Job is outdated, ignore it (another .blend was loaded)
        return False, None

    # Link images from .blend files
    loaded_images = set()
    for image in bpy.data.images:
        _, blendpath = get_image_linking_info(image)
        # In images_to_link, the original image names are used, not the mangled versions
        original_image_name = image.get("nodepreview_original_name", image.name)
        loaded_images.add((original_image_name, blendpath))

    new_images_to_link = images_to_link - loaded_images

    blendpath_image_mapping = {}
    for image_name, blendpath in new_images_to_link:
        try:
            blendpath_image_mapping[blendpath].add(image_name)
        except KeyError:
            blendpath_image_mapping[blendpath] = {image_name}

    for blendpath in blendpath_image_mapping.keys():
        image_names = blendpath_image_mapping[blendpath]
        if os.path.isfile(blendpath):
            with bpy.data.libraries.load(blendpath, link=True) as (data_from, data_to):
                data_to.images = [name for name in data_from.images if name in image_names]

            # Rename the images to unique names to avoid possible name collisions between
            # images linked from different .blend files
            # (e.g. image "stone.png" from textures.blend and image "stone.png" from other_tex_lib.blend)
            for name in image_names:
                try:
                    image = bpy.data.images[name]
                    image["nodepreview_original_name"] = image.name
                    image.name = make_unique_image_name(image)
                except KeyError:
                    # The image could not be linked, probably because it doesn't exist (yet) in the .blend.
                    # Can e.g. happen if a new generated image is created and used in a node without saving the .blend.
                    images_failed_to_link.put({name})
        else:
            # .blend doesn't exist (e.g. because it was not saved yet)
            background_print(".blend doesn't exist:", blendpath)
            images_failed_to_link.put(image_names)

    # Load images from disk
    for image_name, abspath in images_to_load:
        need_to_load = False
        if image_name not in bpy.data.images:
            background_print("loading image", image_name, "because it's not loaded yet")
            need_to_load = True
        else:
            old_image = bpy.data.images[image_name]
            old_abspath = old_image.get("nodepreview_abspath", "")
            # Ignore images without old abspath. These were linked in successfully already
            if old_abspath and old_abspath != abspath:
                background_print("replacing image", image_name, "because the path changed")
                bpy.data.images.remove(old_image)
                need_to_load = True

        if need_to_load:
            # Blender images are always created with 4 channels
            max_size = thumb_resolution
            try:
                pixels, width, height = nodepreview_worker.load_image_scaled(abspath, max_size)
                image = bpy.data.images.new(image_name, width, height, alpha=True,
                                            float_buffer=True, is_data=False)
                if hasattr(image.pixels, "foreach_set"):
                    image.pixels.foreach_set(pixels)
                else:
                    image.pixels[:] = pixels
            except ValueError as error:
                # Fallback for ValueError from nodepreview_worker.load_image_scaled()
                # This happens if the worker doesn't support the image format. 
                # We use Blender to load the image instead in that case.
                background_print("Trying fallback")
                image = bpy_extras.image_utils.load_image(abspath, place_holder=False, check_existing=True,
                                                          force_reload=False)
                if image:
                    image.name = image_name
                # I'd like to scale the image down to save memory, but that doesn't work due to a bug in Blender:
                # (https://developer.blender.org/T85772)
                # image.scale(width, height)  # Calculate correct width and height first
                background_print("Fallback successful" if image else "Fallback could not load image")

            if image:
                image["nodepreview_abspath"] = abspath
                assert image.name == image_name

    node_tree = bpy.data.materials['Material'].node_tree
    starting_nodes = [node.name for node in node_tree.nodes]
    error_message = ""
    full_error_log = ""

    try:
        script = "import bpy; import mathutils; from contextlib import suppress; " + script
        exec(script)
    except Exception as error:
        error_message = str(error)

        full_error_log += "\nScript: --------------------\n"
        for i, line in enumerate(script.split("\n")):
            full_error_log += str(i + 1) + " \t" + line + "\n"
        full_error_log += "----------------------------"

        import traceback
        full_error_log += traceback.format_exc()

        # Red surface
        node_tree = bpy.data.materials['Material'].node_tree
        output_node = node_tree.nodes['Material Output']
        error_node = node_tree.nodes.new("ShaderNodeEmission")
        error_node.inputs[0].default_value = [1, 0, 0, 1]
        node_tree.links.new(error_node.outputs[0], output_node.inputs[0])

    settings = bpy.context.scene.render
    settings.filepath = thumb_path
    settings.resolution_x = thumb_resolution
    settings.resolution_y = thumb_resolution
    bpy.ops.render.render(write_still=True)
    result_array = array("b", [0]) * (thumb_resolution * thumb_resolution * THUMB_CHANNEL_COUNT)
    # Could also load the result into a Blender image (overwrite always the same), to avoid using a C++ module
    nodepreview_worker.load_image_array(result_array, thumb_path)
    if result_array:
        # Convert from bytes with values in range 0..128 to floats in range 0..1, because
        # currently the new GPUTexture in Blender only supports float
        result_array = np.array(result_array, dtype=np.float32)
        result_array = np.divide(result_array, 128.0)

        # Set alpha channel to 1 (full opacity). We don't use it anyway, and
        # this eliminates (very) slight transparency due to inaccuracies.
        alpha_channel = result_array[3::4]
        alpha_channel[:] = 1.0

    for node in node_tree.nodes:
        if node.name not in starting_nodes:
            node_tree.nodes.remove(node)

    # Delete all node groups
    for node_tree in bpy.data.node_groups[:]:
        bpy.data.node_groups.remove(node_tree, do_unlink=True, do_id_user=True, do_ui_user=True)

    # Check if this node contains an image that could not be loaded, and show a helpful error message in that case
    if image_info:
        name, needs_linking, abspath = image_info
        if name not in bpy.data.images:
            if needs_linking:
                error_message = "Save .blend to render preview"
            else:
                if os.path.exists(abspath):
                    error_message = "Could not load image"
                else:
                    error_message = "File not found"

    node_timestamps[node_key] = time()
    return True, (node_key, result_array, thumb_resolution, timestamp, error_message, full_error_log)
