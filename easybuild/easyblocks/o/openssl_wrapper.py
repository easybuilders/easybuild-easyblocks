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
            system_versioned_libs = [
                ['%s.%s' % (lib, ext) for ext in openssl_libext[self.version][os_type]]
                for lib in openssl_libs
            ]
            self.log.info("Matrix of version library names: %s", system_versioned_libs)
        else:
            raise EasyBuildError("Don't know name of OpenSSL system library for version %s and OS type %s",
                                 self.version, os_type)

        # by default target the first option of each OpenSSL library,
        # which corresponds to installation from source
        self.target_ssl_libs = [lib_name[0] for lib_name in system_versioned_libs]
        self.log.info("Target OpenSSL libraries: %s", self.target_ssl_libs)

        # folders containing engines libraries
        openssl_engines = {
            '1.0': 'engines',
            '1.1': 'engines-1.1',
        }
        self.target_ssl_engine = openssl_engines[self.version]

        # Paths to system libraries and headers of OpenSSL
        self.system_ssl = {
            'bin': None,
            'engines': None,
            'include': None,
            'lib': None,
        }

        # early return when we're not wrapping the system OpenSSL installation
        if not self.cfg.get('wrap_system_openssl'):
            self.log.info("Not wrapping system OpenSSL installation!")
            return

        # Check the system libraries of OpenSSL
        # (only needs first library in openssl_libs to find path to libraries)
        for idx, libssl in enumerate(system_versioned_libs[0]):
            self.system_ssl['lib'] = find_library_path(libssl)
            if self.system_ssl['lib']:
                # change target libraries to the ones found in the system
                self.target_ssl_libs = [lib_name[idx] for lib_name in system_versioned_libs]
                self.log.info("Target system OpenSSL libraries: %s", self.target_ssl_libs)
                break

        if self.system_ssl['lib']:
            self.log.info("Found library '%s' in: %s", openssl_libs[0], self.system_ssl['lib'])
        else:
            self.log.info("OpenSSL library '%s' not found, falling back to OpenSSL in EasyBuild", openssl_libs[0])

        # Directory with engine libraries
        if self.system_ssl['lib']:
            lib_dir = os.path.dirname(self.system_ssl['lib'])
            lib_engines_dir = [
                os.path.join(lib_dir, 'openssl', self.target_ssl_engine),
                os.path.join(lib_dir, self.target_ssl_engine),
            ]

            for engines_path in lib_engines_dir:
                if os.path.isdir(engines_path):
                    self.system_ssl['engines'] = engines_path
                    self.log.debug("Found OpenSSL engines in: %s", self.system_ssl['engines'])
                    break

            if not self.system_ssl['engines']:
                self.system_ssl['lib'] = None
                self.log.info("OpenSSL engines not found in host system, falling back to OpenSSL in EasyBuild")

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
            # prefer 'include/openssl' as long as the version of headers matches
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
                        self.system_ssl['include'] = include_dir
                        self.log.info("Found OpenSSL headers in host system: %s", self.system_ssl['include'])
                        break
                    else:
                        self.log.debug("Header major/minor version '%s' doesn't match with %s",
                                       header_majmin_version, self.version)
                else:
                    self.log.debug("Pattern '%s' not found in %s", openssl_version_regex.pattern, opensslv_path)
            else:
                self.log.info("OpenSSL header file %s not found", opensslv_path)

        if not self.system_ssl['include']:
            self.log.info("OpenSSL headers not found in host system, falling back to OpenSSL in EasyBuild")

        # Check system OpenSSL binary
        if self.version == '1.1':
            # prefer 'openssl11' over 'openssl' with v1.1
            self.system_ssl['bin'] = which('openssl11')

        if not self.system_ssl['bin']:
            self.system_ssl['bin'] = which(self.name.lower())

        if self.system_ssl['bin']:
            self.log.info("System OpenSSL binary found: %s", self.system_ssl['bin'])
        else:
            self.log.info("System OpenSSL binary not found!")

    def fetch_step(self, *args, **kwargs):
        """Fetch sources if OpenSSL component is needed"""
        if not all([self.system_ssl['lib'], self.system_ssl['include']]):
            super(EB_OpenSSL_wrapper, self).fetch_step(*args, **kwargs)

    def extract_step(self):
        """Extract sources if OpenSSL component is needed"""
        if not all([self.system_ssl['lib'], self.system_ssl['include']]):
            super(EB_OpenSSL_wrapper, self).extract_step()

    def install_step(self):
        """Symlink target OpenSSL installation"""

        if all(self.system_ssl[key] for key in ('bin', 'engines', 'include', 'lib')):
            # note: symlink to individual files, not directories,
            # since directory symlinks get resolved easily...

            # link OpenSSL libraries in system
            lib64_dir = os.path.join(self.installdir, 'lib64')
            lib64_engines_dir = os.path.join(lib64_dir, os.path.basename(self.system_ssl['engines']))
            mkdir(lib64_engines_dir, parents=True)

            # link existing known libraries
            ssl_syslibdir = os.path.dirname(self.system_ssl['lib'])
            lib_files = [os.path.join(ssl_syslibdir, x) for x in self.target_ssl_libs]
            for libso in lib_files:
                symlink(libso, os.path.join(lib64_dir, os.path.basename(libso)))

            # link engines library files
            engine_lib_pattern = [os.path.join(self.system_ssl['engines'], '*')]
            for engine_lib in expand_glob_paths(engine_lib_pattern):
                symlink(engine_lib, os.path.join(lib64_engines_dir, os.path.basename(engine_lib)))

            # relative symlink for unversioned libraries
            cwd = change_dir(lib64_dir)
            for libso in self.target_ssl_libs:
                unversioned_lib = '%s.%s' % (libso.split('.')[0], get_shared_lib_ext())
                symlink(libso, unversioned_lib, use_abspath_source=False)
            change_dir(cwd)

            # link OpenSSL headers in system
            include_dir = os.path.join(self.installdir, 'include', self.name.lower())
            mkdir(include_dir, parents=True)
            include_pattern = [os.path.join(self.system_ssl['include'], '*')]
            for header_file in expand_glob_paths(include_pattern):
                symlink(header_file, os.path.join(include_dir, os.path.basename(header_file)))

            # link OpenSSL binary in system
            bin_dir = os.path.join(self.installdir, 'bin')
            mkdir(bin_dir)
            symlink(self.system_ssl['bin'], os.path.join(bin_dir, self.name.lower()))

        else:
            # install OpenSSL component
            print_warning("Not all OpenSSL components found, falling back to OpenSSL in EasyBuild!")
            super(EB_OpenSSL_wrapper, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for OpenSSL wrapper."""
        shlib_ext = get_shared_lib_ext()

        ssl_libs = ['%s.%s' % (libso.split('.')[0], shlib_ext) for libso in self.target_ssl_libs]
        ssl_libs.extend(self.target_ssl_libs)

        ssl_files = [os.path.join('bin', self.name.lower())]
        ssl_files.extend(os.path.join('lib', libso) for libso in ssl_libs)

        ssl_dirs = [
            os.path.join('include', self.name.lower()),
            os.path.join('lib', self.target_ssl_engine),
        ]

        custom_paths = {
            'files': ssl_files,
            'dirs': ssl_dirs,
        }

        # make sure that version mentioned in output of 'openssl version' matches version we are using
        custom_commands = ["ssl_ver=$(openssl version); [ ${ssl_ver:8:3} == '%s' ]" % self.version[:3]]

        super(Bundle, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
