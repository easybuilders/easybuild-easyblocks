##
# Copyright 2018-2021 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for installing a wrapper module file for OpenSSL

@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import ctypes
import ctypes.macholib.dyld
import os
import re

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.filetools import expand_glob_paths, find_glob_pattern, mkdir, read_file, symlink, which
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.tools.systemtools import DARWIN, LINUX, get_os_type, get_shared_lib_ext

def locate_solib(libobj):
    """
    Return absolute path to loaded library using dlinfo
    Based on https://stackoverflow.com/a/35683698
    """
    class LINKMAP(ctypes.Structure):
        _fields_ = [
            ("l_addr", ctypes.c_void_p),
            ("l_name", ctypes.c_char_p)
        ]

    libdl = ctypes.cdll.LoadLibrary(ctypes.util.find_library('dl'))

    dlinfo = libdl.dlinfo
    dlinfo.argtypes  = ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
    dlinfo.restype = ctypes.c_int

    libpointer = ctypes.c_void_p()
    dlinfo(libobj._handle, 2, ctypes.byref(libpointer))
    libpath = ctypes.cast(libpointer, ctypes.POINTER(LINKMAP)).contents.l_name

    return libpath

class EB_OpenSSL_wrapper(EasyBlock):
    """
    Create a wrapper .modulerc file for OpenSSL
    """

    def __init__(self, *args, **kwargs):
        """Define the names of OpenSSL shared objects"""
        super(EB_OpenSSL_wrapper, self).__init__(*args, **kwargs)

        # Libraries packaged in OpenSSL
        self.openssl_libs = ['libssl', 'libcrypto']

        # Check the system library of OpenSSL
        libssl = {
            '1.0': {LINUX: 'libssl.so.10', DARWIN: 'libssl.1.0.dylib'},
            '1.1': {LINUX: 'libssl.so.1.1', DARWIN: 'libssl.1.1.dylib'},
        }

        os_type = get_os_type()

        try:
            libssl_so = libssl[self.version][os_type]
            libssl_obj = ctypes.cdll.LoadLibrary(libssl_so)
        except OSError:
            self.ssl_syslib = None
            self.log.debug("Library '%s' not found in host system", libssl_so)
        else:
            # ctypes.util.find_library only accepts unversioned library names
            if os_type == LINUX:
                # find path to library with dlinfo
                self.ssl_syslib = locate_solib(libssl_obj)
            elif os_type == DARWIN:
                # ctypes.macholib.dyld.dyld_find accepts file names and returns full path
                self.ssl_syslib = ctypes.macholib.dyld.dyld_find(libssl_so)
            else:
                raise EasyBuildError("Unknown host system type: %s", os_type)

        self.log.debug("Found library '%s' in: %s", libssl_so, self.ssl_syslib)

        # Check system include paths for OpenSSL headers
        cmd = "gcc -E -Wp,-v -xc /dev/null"
        (out, ec) = run_cmd(cmd, log_all=True, simple=False, trace=False)

        sys_include_dirs = []
        for match in re.finditer(r'^\s(/[^\0\n]*)+', out, re.MULTILINE):
            sys_include_dirs.extend(match.groups())
        self.log.debug("Found the following include directories in host system: %s", ', '.join(sys_include_dirs))

        # headers are always in "include/openssl" subdirectories
        ssl_include_dirs = [os.path.join(include, self.name.lower()) for include in sys_include_dirs]
        ssl_include_dirs = [include for include in ssl_include_dirs if os.path.isdir(include)]

        # verify that the headers match our OpenSSL version
        self.ssl_syshead = None
        for include in ssl_include_dirs:
            opensslv = read_file(os.path.join(include, 'opensslv.h'))
            header_majmin_version = re.search("SHLIB_VERSION_NUMBER\s\"([0-9]+\.[0-9]+)", opensslv, re.M)
            if re.match("^{}".format(*header_majmin_version.groups()), self.version):
                self.ssl_syshead = include
                self.log.debug("Found OpenSSL headers in host system: %s", ', '.join(self.ssl_syshead))

        if not self.ssl_syshead:
            self.log.debug("OpenSSL headers not found in host system")

    def prepare_step(self, *args, **kwargs):
        """Use OpenSSL dependency in host systems without OpenSSL"""
        if self.ssl_syslib and self.ssl_syshead:
            self.cfg['dependencies'] = [dep for dep in self.cfg['dependencies'] if dep['name'] != self.name]
            self.log.debug("Host system provides OpenSSL, removing OpenSSL from list of dependencies")

        super(EB_OpenSSL_wrapper, self).prepare_step(*args, **kwargs)

    def configure_step(self):
        """Do nothing."""
        pass

    def build_step(self):
        """Do nothing."""
        pass

    def install_step(self):
        """Symlink target OpenSSL installation"""
        shlib_ext = get_shared_lib_ext()

        if self.ssl_syslib and self.ssl_syshead:
            # The host system already provides the necessary OpenSSL files
            ssl_lib_pattern = ['%s*.%s*' % (lib_so, shlib_ext) for lib_so in self.openssl_libs]
            ssl_lib_pattern = [
                os.path.join(os.path.dirname(self.ssl_syslib), '%s' % ptrn) for ptrn in ssl_lib_pattern
            ]
            ssl_include_path = self.ssl_syshead
            ssl_bin = which(self.name.lower())
        else:
            # Use OpenSSL from EasyBuild
            ssl_root = get_software_root(self.name)
            ssl_lib_pattern = [os.path.join(ssl_root, 'lib', '*.%s*' % shlib_ext)]
            ssl_include_path = os.path.join(get_software_root(self.name), 'include', self.name.lower())
            ssl_bin = os.path.join(ssl_root, 'bin', self.name.lower())

        # Link OpenSSL libraries
        lib64_dir = os.path.join(self.installdir, 'lib64')
        mkdir(lib64_dir)
        symlink('lib64', 'lib')

        ssl_lib_files = expand_glob_paths(ssl_lib_pattern)
        for libso in ssl_lib_files:
            symlink(libso, os.path.join(lib64_dir, os.path.basename(libso)))

        # Link OpenSSL headers
        include_dir = os.path.join(self.installdir, 'include')
        mkdir(include_dir)
        symlink(ssl_include_path, os.path.join(include_dir, self.name.lower()))

        # Link OpenSSL binary
        bin_dir = os.path.join(self.installdir, 'bin')
        mkdir(bin_dir)
        symlink(ssl_bin, os.path.join(bin_dir, self.name.lower()))

    def make_module_dep(self):
        """Make module file without OpenSSL dependency."""
        return ''

    def sanity_check_step(self):
        """Custom sanity check for OpenSSL wrapper."""
        shlib_ext = get_shared_lib_ext()

        ssl_bin = os.path.join('bin', self.name.lower())
        ssl_include_dir = os.path.join('include', self.name.lower())
        ssl_libs = [os.path.join('lib', '%s.%s' % (libso, shlib_ext)) for libso in self.openssl_libs]

        custom_paths = {
            'files': [ssl_bin] + ssl_libs,
            'dirs': [ssl_include_dir]
        }

        super(EB_OpenSSL_wrapper, self).sanity_check_step(custom_paths=custom_paths)
