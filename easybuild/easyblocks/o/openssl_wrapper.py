##
# Copyright 2021 Vrije Universiteit Brussel
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
import os
import re

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import change_dir, expand_glob_paths, mkdir, read_file, symlink, which
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import DARWIN, LINUX, get_os_type, get_shared_lib_ext, find_library_path
from easybuild.tools.build_log import EasyBuildError, print_warning


class EB_OpenSSL_wrapper(Bundle):
    """
    Locate the installation files of OpenSSL in the host system
    If available, wrap the system OpenSSL by symlinking all installation files
    Fall back to the bundled component otherwise
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
        openssl_libs = ['libssl', 'libcrypto']
        # list of relevant library extensions per system and version of OpenSSL
        # the first item should be the extension of an installation from source,
        # it will be used in the sanity checks of the component
        openssl_libext = {
            '1.0': {
                LINUX: ('so.1.0.0', 'so.10'),
                DARWIN: ('1.0.dylib', ),
            },
            '1.1': {
                LINUX: ('so.1.1', ),
                DARWIN: ('1.1.dylib', ),
            },
        }

        os_type = get_os_type()
        if self.version in openssl_libext and os_type in openssl_libext[self.version]:
            # generate matrix of versioned .so filenames
            self.openssl_libs = [
                ['%s.%s' % (lib, ext) for ext in openssl_libext[self.version][os_type]]
                for lib in openssl_libs
            ]
        else:
            raise EasyBuildError("Don't know name of OpenSSL system library for version %s and OS type %s",
                                 self.version, os_type)

        # folders containing engines libraries
        self.openssl_engines = {
            '1.0': 'engines',
            '1.1': 'engines-1.1',
        }

        # Paths to system libraries and headers of OpenSSL
        self.ssl_syslib = None
        self.ssl_sysheader = None
        self.ssl_sysengines = None
        self.ssl_sysbin = None

        if not self.cfg.get('wrap_system_openssl'):
            return

        # Check the system libraries of OpenSSL
        for idx, libssl in enumerate(self.openssl_libs[0]):
            self.ssl_syslib = find_library_path(libssl)
            if self.ssl_syslib:
                # reduce matrix of library names to the family of this one
                self.openssl_libs = list(zip(*self.openssl_libs))[idx]
                break

        if self.ssl_syslib:
            self.log.info("Found library '%s' in: %s", openssl_libs[0], self.ssl_syslib)
        else:
            self.log.info("Library '%s' not found!", openssl_libs[0])

        # Directory with engine libraries
        if self.ssl_syslib:
            lib_dir = os.path.dirname(self.ssl_syslib)
            openssl_engine = self.openssl_engines[self.version]
            lib_engines_dir = [
                os.path.join(lib_dir, 'openssl', openssl_engine),
                os.path.join(lib_dir, openssl_engine),
            ]

            for engines_path in lib_engines_dir:
                if os.path.isdir(engines_path):
                    self.ssl_sysengines = engines_path
                    self.log.debug("Found OpenSSL engines in: %s", self.ssl_sysengines)
                    break

            if not self.ssl_sysengines:
                self.ssl_syslib = None
                print_warning("Found OpenSSL in host system, but not its engines."
                              "Falling back to OpenSSL in EasyBuild")

        # Check system include paths for OpenSSL headers
        cmd = "LC_ALL=C gcc -E -Wp,-v -xc /dev/null"
        (out, ec) = run_cmd(cmd, log_all=True, simple=False, trace=False)

        sys_include_dirs = []
        for match in re.finditer(r'^\s(/[^\0\n]*)+', out, re.MULTILINE):
            sys_include_dirs.extend(match.groups())
        self.log.debug("Found the following include directories in host system: %s", ', '.join(sys_include_dirs))

        # headers are located in 'include/openssl' by default
        ssl_include_subdirs = [self.name.lower()]
        if self.version == '1.1':
            # but version 1.1 can be installed in 'include/openssl11/openssl' as well, for example in CentOS 7
            # we prefer 'include/openssl' as long as the version of headers matches
            ssl_include_subdirs.append(os.path.join('openssl11', self.name.lower()))

        ssl_include_dirs = [os.path.join(incd, subd) for incd in sys_include_dirs for subd in ssl_include_subdirs]
        ssl_include_dirs = [include for include in ssl_include_dirs if os.path.isdir(include)]

        # find location of header files, verify that the headers match our OpenSSL version
        openssl_version_regex = re.compile(r"SHLIB_VERSION_NUMBER\s\"([0-9]+\.[0-9]+)", re.M)
        for include_dir in ssl_include_dirs:
            opensslv_path = os.path.join(include_dir, 'opensslv.h')
            self.log.debug("Checking OpenSSL version in %s...", opensslv_path)
            if os.path.exists(opensslv_path):
                opensslv = read_file(opensslv_path)
                header_majmin_version = openssl_version_regex.search(opensslv)
                if header_majmin_version:
                    header_majmin_version = header_majmin_version.group(1)
                    if re.match('^' + header_majmin_version, self.version):
                        self.ssl_sysheader = include_dir
                        self.log.info("Found OpenSSL headers in host system: %s", self.ssl_sysheader)
                        break
                    else:
                        self.log.debug("Header major/minor version '%s' doesn't match with %s",
                                       header_majmin_version, self.version)
                else:
                    self.log.debug("Pattern '%s' not found in %s", openssl_version_regex.pattern, opensslv_path)
            else:
                self.log.debug("OpenSSL header file %s not found")

        if not self.ssl_sysheader:
            self.log.info("OpenSSL headers not found in host system")

        # Check system OpenSSL binary
        if self.version == '1.1':
            # prefer 'openssl11' over 'openssl' with v1.1
            self.ssl_sysbin = which('openssl11')

        if not self.ssl_sysbin:
            self.ssl_sysbin = which(self.name.lower())

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

        if self.ssl_syslib and self.ssl_sysheader:
            # note: symlink to individual files, not directories,
            # since directory symlinks get resolved easily...

            # link OpenSSL libraries in system
            lib64_dir = os.path.join(self.installdir, 'lib64')
            lib64_engines_dir = os.path.join(lib64_dir, os.path.basename(self.ssl_sysengines))
            mkdir(lib64_engines_dir, parents=True)

            # link existing known libraries
            ssl_syslibdir = os.path.dirname(self.ssl_syslib)
            lib_files = [os.path.join(ssl_syslibdir, x) for x in self.openssl_libs]
            for libso in lib_files:
                symlink(libso, os.path.join(lib64_dir, os.path.basename(libso)))

            # link engines library files
            lib64_engines_dir = os.path.join(lib64_dir, os.path.basename(self.ssl_sysengines))
            engine_lib_pattern = [os.path.join(self.ssl_sysengines, '*')]
            for engine_lib in expand_glob_paths(engine_lib_pattern):
                symlink(engine_lib, os.path.join(lib64_engines_dir, os.path.basename(engine_lib)))

            # relative symlink for unversioned libraries
            cwd = change_dir(lib64_dir)
            for libso in self.openssl_libs:
                unversioned_lib = '%s.%s' % (libso.split('.')[0], get_shared_lib_ext())
                symlink(libso, unversioned_lib, use_abspath_source=False)
            change_dir(cwd)

            # link OpenSSL headers in system
            include_dir = os.path.join(self.installdir, 'include', self.name.lower())
            mkdir(include_dir, parents=True)
            include_pattern = [os.path.join(self.ssl_sysheader, '*')]
            for header_file in expand_glob_paths(include_pattern):
                symlink(header_file, os.path.join(include_dir, os.path.basename(header_file)))

            # link OpenSSL binary in system
            bin_dir = os.path.join(self.installdir, 'bin')
            mkdir(bin_dir)
            symlink(self.ssl_sysbin, os.path.join(bin_dir, self.name.lower()))

        else:
            # without wrapping, reduce matrix of library names to first items
            self.openssl_libs = [libs[0] for libs in self.openssl_libs]

            # install OpenSSL component
            super(EB_OpenSSL_wrapper, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for OpenSSL wrapper."""
        shlib_ext = get_shared_lib_ext()

        ssl_files = [os.path.join('bin', self.name.lower())]
        ssl_files.extend(os.path.join('lib', libso) for libso in self.openssl_libs)
        ssl_files.extend(os.path.join('lib', '%s.%s' % (libso.split('.')[0], shlib_ext)) for libso in self.openssl_libs)

        ssl_dirs = [
            os.path.join('include', self.name.lower()),
            os.path.join('lib', self.openssl_engines[self.version]),
        ]

        custom_paths = {
            'files': ssl_files,
            'dirs': ssl_dirs,
        }

        # make sure that version mentioned in output of 'openssl version' matches version we are using
        custom_commands = ["ssl_ver=$(openssl version); [ ${ssl_ver:8:3} == '%s' ]" % self.version[:3]]

        super(Bundle, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
