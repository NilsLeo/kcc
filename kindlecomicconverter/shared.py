# -*- coding: utf-8 -*-
#
# Copyright (c) 2012-2014 Ciro Mattia Gonano <ciromattia@gmail.com>
# Copyright (c) 2013-2019 Pawel Jastrzebski <pawelj@iosphe.re>
#
# Permission to use, copy, modify, and/or distribute this software for
# any purpose with or without fee is hereby granted, provided that the
# above copyright notice and this permission notice appear in all
# copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL
# WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE
# AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL
# DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA
# OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
# TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.
#

import os
from html.parser import HTMLParser
import subprocess
from packaging.version import Version
from re import split
import sys
from traceback import format_tb


IMAGE_TYPES = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.jp2', '.avif')


def configured_pool_size():
    """Return the process pool size requested via the KCC_WORKERS environment
    variable, or None to use the multiprocessing default (cpu_count).

    Constrained environments (containers, low-memory machines) can set
    KCC_WORKERS to bound peak memory usage: each image-processing worker holds
    several decoded full-resolution pages in RAM at once.
    """
    try:
        value = int(os.environ.get('KCC_WORKERS', ''))
    except ValueError:
        return None
    return value if value > 0 else None


def drop_file_cache(path, sync=False):
    """Best-effort hint to the kernel that a file's page cache is no longer
    needed (POSIX_FADV_DONTNEED).

    After extracting a large source archive its cached bytes are dead weight;
    in memory-limited cgroups (Docker/Kubernetes) they still count toward the
    container's memory usage until reclaimed. No-op on platforms without
    posix_fadvise (Windows, macOS).

    Freshly written files must be flushed first (sync=True): DONTNEED skips
    dirty pages, so without a writeback the hint would do nothing.
    """
    if not hasattr(os, 'posix_fadvise'):
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        if sync:
            os.fdatasync(fd)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    except OSError:
        pass
    finally:
        os.close(fd)


class HTMLStripper(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)

    def error(self, message):
        pass


def dot_clean(filetree):
    for root, _, files in os.walk(filetree, topdown=False):
        for name in files:
            if name.startswith('._') or name == '.DS_Store':
                if os.path.exists(os.path.join(root, name)):
                    os.remove(os.path.join(root, name))


def getImageFileName(imgfile):
    name, ext = os.path.splitext(imgfile)
    ext = ext.lower()
    return [name, ext]

def get_contain_resolution(image, size):
    '''same code as Pillow ImageOps.contain()'''
    im_ratio = image.width / image.height
    dest_ratio = size[0] / size[1]

    if im_ratio != dest_ratio:
        if im_ratio > dest_ratio:
            new_height = round(image.height / image.width * size[0])
            if new_height != size[1]:
                size = (size[0], new_height)
        else:
            new_width = round(image.width / image.height * size[1])
            if new_width != size[0]:
                size = (new_width, size[1])
    
    return size


def walkSort(dirnames, filenames):
    convert = lambda text: int(text) if text.isdigit() else text
    alphanum_key = lambda key: [convert(c) for c in split('([0-9]+)', key)]
    dirnames.sort(key=lambda name: alphanum_key(name.lower()))
    filenames.sort(key=lambda name: alphanum_key(name.lower()))
    return dirnames, filenames


def walkLevel(some_dir, level=1):
    some_dir = some_dir.rstrip(os.path.sep)
    assert os.path.isdir(some_dir)
    num_sep = some_dir.count(os.path.sep)
    for root, dirs, files in os.walk(some_dir):
        dirs, files = walkSort(dirs, files)
        yield root, dirs, files
        num_sep_this = root.count(os.path.sep)
        if num_sep + level <= num_sep_this:
            del dirs[:]



def sanitizeTrace(traceback):
    return ''.join(format_tb(traceback))\
        .replace('C:/projects/kcc/', '')\
        .replace('c:/projects/kcc/', '')\
        .replace('C:/python37-x64/', '')\
        .replace('c:/python37-x64/', '')\
        .replace('C:\\projects\\kcc\\', '')\
        .replace('c:\\projects\\kcc\\', '')\
        .replace('C:\\python37-x64\\', '')\
        .replace('c:\\python37-x64\\', '')


# noinspection PyUnresolvedReferences
def dependencyCheck(level):
    missing = []
    if level > 2:
        try:
            from PySide6.QtCore import qVersion as qtVersion
            if Version('6.0.0') > Version(qtVersion()):
                missing.append('PySide 6.0.0')
        except ImportError:
            missing.append('PySide 6.0.0+')
    if level > 1:
        try:
            from psutil import __version__ as psutilVersion
            if Version('5.0.0') > Version(psutilVersion):
                missing.append('psutil 5.0.0+')
        except ImportError:
            missing.append('psutil 5.0.0+')
        try:
            from types import ModuleType
            from slugify import __version__ as slugifyVersion
            if isinstance(slugifyVersion, ModuleType):
                slugifyVersion = slugifyVersion.__version__
            if Version('1.2.1') > Version(slugifyVersion):
                missing.append('python-slugify 1.2.1+')
        except ImportError:
            missing.append('python-slugify 1.2.1+')
    try:
        from PIL import __version__ as pillowVersion
        if Version('8.3.0') > Version(pillowVersion):
            missing.append('Pillow 8.3.0+')
    except ImportError:
        missing.append('Pillow 8.3.0+')
    try:
        from pymupdf import __version__ as pymupdfVersion
        if Version('1.16.1') > Version(pymupdfVersion):
            missing.append('PyMuPDF 1.16.1+')
    except ImportError:
        missing.append('PyMuPDF 1.16.1+')
    if len(missing) > 0:
        print('ERROR: ' + ', '.join(missing) + ' is not installed!')
        sys.exit(1)

def subprocess_run(command, **kwargs):
    if (os.name == 'nt'):
        kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
    return subprocess.run(command, **kwargs)
