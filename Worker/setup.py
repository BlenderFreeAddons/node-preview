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


from distutils.core import setup, Extension, DEBUG

MODULE_NAME_STR = "nodepreview_worker"
worker_module = Extension(MODULE_NAME_STR, sources = ["workermodule.cpp"])

setup(
    name = MODULE_NAME_STR,
    version = "1.0",
    description = "Node Preview Worker",
    ext_modules = [worker_module]
)
