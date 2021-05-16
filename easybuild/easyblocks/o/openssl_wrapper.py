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
import os
import re

try:
    # only needed on macOS, may not be available on Linux
    import ctypes.macholib.dyld
except ImportError:
    pass

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import expand_glob_paths, mkdir, read_file, symlink, which
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import DARWIN, LINUX, get_os_type, get_shared_lib_ext
from easybuild.tools.build_log import EasyBuildError, print_warning


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
    dlinfo.argtypes = ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
    dlinfo.restype = ctypes.c_int

    libpointer = ctypes.c_void_p()
    dlinfo(libobj._handle, 2, ctypes.byref(libpointer))
    libpath = ctypes.cast(libpointer, ctypes.POINTER(LINKMAP)).contents.l_name

    return libpath.decode('utf-8')


class EB_OpenSSL_wrapper(Bundle):
    """
    Locate the installation files of OpenSSL in the host system.
    If available, wrap the system OpenSSL by symlinking all installation files
    Fall back to the bundled component otherwise.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to OpenSSL wrapper"""
        extra_vars = Bundle.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'wrap_system_openssl': [True, 'Detect and wrap OpenSSL installation in host system', CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Locate the installation files of OpenSSL in the host system"""
        super(EB_OpenSSL_wrapper, self).__init__(*args, **kwargs)

        # Libraries packaged in OpenSSL
        self.openssl_libs = ['libssl', 'libcrypto']
        self.openssl_engines = {
            '1.0': 'engines',
            '1.1': 'engines-1.1',
        }

        # Paths to system libraries and headers of OpenSSL
        self.ssl_syslib = None
        self.ssl_sysheader = None
        self.ssl_sysengines = None

        if not self.cfg.get('wrap_system_openssl'):
            return

        # Check the system libraries of OpenSSL
        libssl = {
            '1.0': {
                DARWIN: 'libssl.1.0.dylib',
                LINUX: 'libssl.so.10',
            },
            '1.1': {
                LINUX: 'libssl.so.1.1',
                DARWIN: 'libssl.1.1.dylib',
            },
        }

        os_type = get_os_type()

        if self.version in libssl and os_type in libssl[self.version]:
            libssl_so = libssl[self.version][os_type]
        else:
            raise EasyBuildError("Don't know name of OpenSSL system library for version %s and OS type %s",
                                 self.version, os_type)

        try:
            libssl_obj = ctypes.cdll.LoadLibrary(libssl_so)
            self.log.info("Absolute path to %s: %s" % (libssl_so, libssl_obj))
        except OSError:
            self.log.info("Library '%s' not found in host system", libssl_so)
        else:
            # ctypes.util.find_library only accepts unversioned library names
            if os_type == LINUX:
                # find path to library with dlinfo
                self.ssl_syslib = locate_solib(libssl_obj)
            elif os_type == DARWIN:
                # ctypes.macholib.dyld.dyld_find accepts file names and returns full path
                self.ssl_syslib = ctypes.macholib.dyld.dyld_find(libssl_so)
            else:
                raise EasyBuildError("Unknown host OS type: %s", os_type)

        if self.ssl_syslib:
            self.log.info("Found library '%s' in: %s", libssl_so, self.ssl_syslib)
        else:
            self.log.info("Library '%s' not found!", libssl_so)

        # Directory with engine libraries
        if self.ssl_syslib:
            lib_dir = os.path.dirname(self.ssl_syslib)
            lib_engines_dir = [
                os.path.join(lib_dir, self.openssl_engines[self.version]),
                os.path.join(lib_dir, 'openssl', self.openssl_engines[self.version]),
            ]

            for engines_path in lib_engines_dir:
                if os.path.isdir(engines_path):
                    self.ssl_sysengines = engines_path
                    self.log.debug("Found OpenSSL engines in: %s", self.ssl_sysengines)

            if not self.ssl_sysengines:
                self.ssl_syslib = None
                print_warning("Found OpenSSL in host system, but not its engines."
                              "Falling back to OpenSSL in EasyBuild")

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
        for include in ssl_include_dirs:
            opensslv = read_file(os.path.join(include, 'opensslv.h'))
            header_majmin_version = re.search(r"SHLIB_VERSION_NUMBER\s\"([0-9]+\.[0-9]+)", opensslv, re.M)
            if re.match("^{}".format(*header_majmin_version.groups()), self.version):
                self.ssl_sysheader = include
                self.log.info("Found OpenSSL headers in host system: %s", self.ssl_sysheader)

        if not self.ssl_sysheader:
            self.log.info("OpenSSL headers not found in host system")

    def fetch_step(self, *args, **kwargs):
        """Fetch sources if OpenSSL component is needed"""
        if not all([self.ssl_syslib, self.ssl_sysheader]):
            super(EB_OpenSSL_wrapper, self).fetch_step(*args, **kwargs)

    def extract_step(self):
        """Extract sources if OpenSSL component is needed"""
        if not all([self.ssl_syslib, self.ssl_sysheader]):
            super(EB_OpenSSL_wrapper, self).extract_step()

    def install_step(self):
        """Symlink target OpenSSL installation"""
        shlib_ext = get_shared_lib_ext()

        if self.ssl_syslib and self.ssl_sysheader:
            # The host system already provides the necessary OpenSSL files
            lib_pattern = ['%s*.%s*' % (lib_so, shlib_ext) for lib_so in self.openssl_libs]
            lib_pattern = [os.path.join(os.path.dirname(self.ssl_syslib), '%s' % ptrn) for ptrn in lib_pattern]
            lib_pattern.append(os.path.join(self.ssl_sysengines, '*'))

            include_pattern = [os.path.join(self.ssl_sysheader, '*')]

            bin_path = which(self.name.lower())

            # Link OpenSSL libraries
            lib64_dir = os.path.join(self.installdir, 'lib64')
            lib64_engines_dir = os.path.join(lib64_dir, os.path.basename(self.ssl_sysengines))
            mkdir(lib64_engines_dir, parents=True)
            symlink('lib64', 'lib')

            lib_files = expand_glob_paths(lib_pattern)

            for libso in lib_files:
                if 'engines' in libso:
                    target_dir = lib64_engines_dir
                else:
                    target_dir = lib64_dir
                symlink(libso, os.path.join(target_dir, os.path.basename(libso)))

            # Link OpenSSL headers
            include_dir = os.path.join(self.installdir, 'include', self.name.lower())
            mkdir(include_dir, parents=True)

            include_files = expand_glob_paths(include_pattern)
            for header in include_files:
                symlink(header, os.path.join(include_dir, os.path.basename(header)))

            # Link OpenSSL binary
            bin_dir = os.path.join(self.installdir, 'bin')
            mkdir(bin_dir)
            symlink(bin_path, os.path.join(bin_dir, os.path.basename(bin_path)))

        else:
            # Install OpenSSL component
            super(EB_OpenSSL_wrapper, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for OpenSSL wrapper."""
        shlib_ext = get_shared_lib_ext()

        ssl_files = [os.path.join('bin', self.name.lower())]
        ssl_files.extend(os.path.join('lib', '%s.%s' % (libso, shlib_ext)) for libso in self.openssl_libs)

        ssl_dirs = [
            os.path.join('include', self.name.lower()),
            os.path.join('lib', self.openssl_engines[self.version]),
        ]

        custom_paths = {
            'files': ssl_files,
            'dirs': ssl_dirs,
        }

        custom_commands = ["openssl version"]

        super(Bundle, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
