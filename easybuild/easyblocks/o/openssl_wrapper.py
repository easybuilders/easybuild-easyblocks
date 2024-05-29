##
# Copyright 2021-2024 Vrije Universiteit Brussel
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

from urllib.parse import urlparse

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.filetools import change_dir, expand_glob_paths, mkdir, read_file, symlink, which, write_file
from easybuild.tools.py2vs3 import string_type
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import DARWIN, LINUX, get_os_type, get_shared_lib_ext, find_library_path


class EB_OpenSSL_wrapper(Bundle):
    """
    Find path to installation files of OpenSSL in the host system. Checks in
    order: library files defined in 'openssl_libs', engines libraries, header
    files and executables. Any missing component will trigger an installation
    from source of the fallback component.
    Libraries are located by soname using the major and minor subversions of
    the wrapper version. The full version of the wrapper or the option
    'minimum_openssl_version' determine the minimum required version of OpenSSL
    in the system. The wrapper checks for version strings in the library files
    and the opensslv.h header.
    If OpenSSL in host systems fulfills the version requirements, wrap it by
    symlinking all installation files. Otherwise fall back to the bundled
    component.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to OpenSSL wrapper"""
        extra_vars = Bundle.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'wrap_system_openssl': [True, 'Detect and wrap OpenSSL installation in host system', CUSTOM],
            'minimum_openssl_version': [None, 'Minimum version of OpenSSL required in host system', CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Locate the installation files of OpenSSL in the host system"""
        super(EB_OpenSSL_wrapper, self).__init__(*args, **kwargs)

        if LooseVersion(self.version) < LooseVersion('2'):
            try:
                subversions = self.version.split('.')
                self.generation = '%s.%s' % (subversions[0], subversions[1])
            except (AttributeError, IndexError):
                err_msg = "Wrapper for OpenSSL v1 version is missing a minor version: %s"
                raise EasyBuildError(err_msg, self.version)
        elif LooseVersion(self.version) < LooseVersion('4'):
            self.generation = "3"

        # Set minimum OpenSSL version
        self.min_version = self.cfg.get('minimum_openssl_version')
        if not self.min_version:
            self.min_version = self.version
        elif not isinstance(self.min_version, string_type):
            self.min_version = str(self.min_version)
        # Minimum OpenSSL version can only increase depth of wrapper version
        if self.min_version.startswith(self.version):
            self.log.debug("Requiring minimum OpenSSL version: %s", self.min_version)
        else:
            err_msg = "Requested minimum OpenSSL version '%s' does not fit in wrapper easyconfig version '%s'"
            raise EasyBuildError(err_msg, self.min_version, self.version)

        # Set maximum OpenSSL version (increase smallest revision by 1)
        max_version_parts = [int(subv) for subv in self.version.split('.')]
        max_version_parts[-1] += 1
        self.max_version = '.'.join([str(subv) for subv in max_version_parts])
        self.log.debug("Restricting maximum OpenSSL version: %s", self.max_version)

        # Regex pattern to find version strings in OpenSSL libraries and headers
        full_version_regex = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+[a-z]?')
        openssl_version_regex = re.compile(r'OpenSSL[\s_]+([0-9]+\.[0-9]+(\.[0-9]+[a-z]?)*)', re.M | re.I)

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
            '3': {
                LINUX: ('so.3', ),
                DARWIN: ('3.dylib', ),
            },
        }

        os_type = get_os_type()
        if self.generation in openssl_libext and os_type in openssl_libext[self.generation]:
            # generate matrix of versioned .so filenames
            system_versioned_libs = [
                ['%s.%s' % (lib, ext) for lib in openssl_libs]
                for ext in openssl_libext[self.generation][os_type]
            ]
            self.log.info("Matrix of version library names: %s", system_versioned_libs)
        else:
            err_msg = "OpenSSL system library for version %s and OS type %s is unsupported"
            raise EasyBuildError(err_msg, self.generation, os_type)

        # folders containing engines libraries
        openssl_engines = {
            '1.0': 'engines',
            '1.1': 'engines-1.1',
            '3': 'engines-3',
        }

        # Define targets for this generation
        # They are used to sanity check both installations from source or wrappers
        self.generation_targets = {
            'bin': 'openssl',
            'engines': openssl_engines[self.generation],
            'libs': system_versioned_libs[0],  # first set of libs match source installs
        }

        # Paths to system components of OpenSSL
        self.system_ssl = {
            'bin': None,
            'engines': None,
            'include': None,
            'libs': [],
        }

        # early return when we're not wrapping the system OpenSSL installation
        if not self.cfg.get('wrap_system_openssl'):
            self.log.info("Not wrapping system OpenSSL installation by user request")
            return

        # Check system OpenSSL binary
        target_ssl_bins = [self.generation_targets['bin']]
        if self.generation == '1.1':
            target_ssl_bins.insert(0, 'openssl11')  # prefer 'openssl11' over 'openssl' with v1.1
        elif self.generation == '3':
            target_ssl_bins.insert(0, 'openssl3')  # prefer 'openssl3' over 'openssl' with v3

        for ssl_bin in target_ssl_bins:
            ssl_bin_path, ssl_bin_version = self.get_openssl_bin_version(ssl_bin)
            if ssl_bin_path:
                if LooseVersion(self.min_version) <= LooseVersion(ssl_bin_version) < LooseVersion(self.max_version):
                    self.system_ssl['version'] = ssl_bin_version
                    self.system_ssl['bin'] = ssl_bin_path
                    break

        if self.system_ssl['bin'] and self.system_ssl['version']:
            log_msg = "System OpenSSL binary for version %s found: %s"
            self.log.info(log_msg, self.system_ssl['version'], self.system_ssl['bin'])
        else:
            log_msg = "OpenSSL binary for version %s not found in host system! "
            log_msg += "Falling back to building OpenSSL from source"
            self.log.info(log_msg, self.version)
            return

        # Check the system libraries of OpenSSL
        # Find library file and compare its version string
        for solibs in system_versioned_libs:
            target_ssl_libs = []
            for solib in solibs:
                system_solib = find_library_path(solib)
                if not system_solib:
                    # this OpenSSL library is missing, move on to next group of versioned libs
                    break

                try:
                    # get version of system library filename
                    ssl_lib_version = full_version_regex.search(os.path.realpath(system_solib)).group(0)
                except AttributeError:
                    # filename lacks the full version, fallback to version strings within the library
                    solib_strings = read_file(system_solib, mode="rb").decode('utf-8', 'replace')
                    try:
                        ssl_lib_support_versions = openssl_version_regex.findall(solib_strings)
                        ssl_lib_support_versions.sort()
                        dbg_msg = "System OpenSSL library '%s' supports versions: %s"
                        dbg_msg_support_versions = ', '.join([''.join(v) for v in ssl_lib_support_versions])
                        self.log.debug(dbg_msg, system_solib, dbg_msg_support_versions)
                        # pick highest supported version
                        ssl_lib_version = ssl_lib_support_versions[-1][0]
                    except IndexError:
                        dbg_msg = "Could not detect the full version of system OpenSSL library: %s"
                        self.log.debug(dbg_msg, system_solib)
                # check that system library version fulfills requirements
                if LooseVersion(self.min_version) <= LooseVersion(ssl_lib_version) < LooseVersion(self.max_version):
                    dbg_msg = "System OpenSSL library '%s' with version %s fulfills requested version %s"
                    self.log.debug(dbg_msg, system_solib, ssl_lib_version, self.min_version)
                    target_ssl_libs.append(system_solib)
                else:
                    dbg_msg = "System OpenSSL library '%s' with version %s is older than requested version %s"
                    self.log.debug(dbg_msg, system_solib, ssl_lib_version, self.min_version)

            if len(target_ssl_libs) == len(openssl_libs):
                # target libraries found, ignore further options
                break

        if len(target_ssl_libs) == len(openssl_libs):
            self.system_ssl['libs'] = target_ssl_libs
            self.generation_targets['libs'] = [os.path.basename(solib) for solib in target_ssl_libs]
            info_msg = "Found OpenSSL library version %s in host system: %s"
            self.log.info(info_msg, ssl_lib_version, os.path.dirname(self.system_ssl['libs'][0]))
        else:
            log_msg = "OpenSSL library for version %s not found in host system! "
            log_msg += "Falling back to building OpenSSL from source"
            self.log.info(log_msg, self.system_ssl['version'])
            return

        # Directory with engine libraries
        lib_dir = os.path.dirname(self.system_ssl['libs'][0])
        lib_engines_dir = [
            os.path.join(lib_dir, 'openssl', openssl_engines[self.generation]),
            os.path.join(lib_dir, openssl_engines[self.generation]),
        ]

        for engines_path in lib_engines_dir:
            if os.path.isdir(engines_path):
                self.system_ssl['engines'] = engines_path
                self.log.debug("Found OpenSSL engines in: %s", self.system_ssl['engines'])
                break

        if not self.system_ssl['engines']:
            log_msg = "OpenSSL engines for version %s not found in host system! "
            log_msg += "Falling back to building OpenSSL from source"
            self.log.info(log_msg, self.system_ssl['version'])
            return

        # Check system include paths for OpenSSL headers
        cmd = "LC_ALL=C gcc -E -Wp,-v -xc /dev/null"
        (out, ec) = run_cmd(cmd, log_all=True, simple=False, trace=False)

        sys_include_dirs = []
        for match in re.finditer(r'^\s(/[^\0\n]*)+', out, re.MULTILINE):
            sys_include_dirs.extend(match.groups())
        self.log.debug("Found the following include directories in host system: %s", ', '.join(sys_include_dirs))

        # headers are located in 'include/openssl' by default
        ssl_include_subdirs = ['openssl']
        if self.generation == '1.1':
            # but version 1.1 can be installed in 'include/openssl11/openssl' as well, for example in CentOS 7
            # prefer 'include/openssl' as long as the version of headers matches
            ssl_include_subdirs.append(os.path.join('openssl11', self.name.lower()))
        elif self.generation == '3':
            # but version 3.x can be installed in 'include/openssl3/openssl' as well, for example in RHEL 8 derivatives
            # prefer 'include/openssl' as long as the version of headers matches
            ssl_include_subdirs.append(os.path.join('openssl3', self.name.lower()))

        ssl_include_dirs = [os.path.join(incd, subd) for incd in sys_include_dirs for subd in ssl_include_subdirs]
        ssl_include_dirs = [include for include in ssl_include_dirs if os.path.isdir(include)]

        # find location of header files for this version of the OpenSSL libraries
        for include_dir in ssl_include_dirs:
            opensslv_path = os.path.join(include_dir, 'opensslv.h')
            self.log.debug("Checking OpenSSL version in %s...", opensslv_path)
            if os.path.exists(opensslv_path):
                # check version reported by opensslv.h
                opensslv = read_file(opensslv_path)
                try:
                    ssl_head_version = openssl_version_regex.search(opensslv).group(1)
                except AttributeError:
                    err_msg = "System OpenSSL header '%s' does not contain any recognizable version string"
                    raise EasyBuildError(err_msg, opensslv_path)

                if LooseVersion(self.min_version) <= LooseVersion(ssl_head_version) < LooseVersion(self.max_version):
                    self.system_ssl['include'] = include_dir
                    info_msg = "Found OpenSSL headers v%s in host system: %s"
                    self.log.info(info_msg, ssl_head_version, self.system_ssl['include'])
                    break
                else:
                    dbg_msg = "System OpenSSL header version '%s' does not fulfill minimum version requirement '%s'"
                    self.log.debug(dbg_msg, ssl_head_version, self.min_version)
            else:
                self.log.info("System OpenSSL header file %s not found", opensslv_path)

        if not self.system_ssl['include']:
            err_msg = ("OpenSSL v%s headers not found in host system, but libraries for v%s are present. "
                       "Install the development package of OpenSSL for your system or force building OpenSSL from "
                       "source in EasyBuild by setting 'wrap_system_openssl = False' in the OpenSSL easyconfig.")
            raise EasyBuildError(err_msg, self.version, self.system_ssl['version'])

    def fetch_step(self, *args, **kwargs):
        """Fetch sources if OpenSSL component is needed"""
        if not all(self.system_ssl[key] for key in ('bin', 'engines', 'include', 'libs')):
            super(EB_OpenSSL_wrapper, self).fetch_step(*args, **kwargs)

    def extract_step(self):
        """Extract sources if OpenSSL component is needed"""
        if not all(self.system_ssl[key] for key in ('bin', 'engines', 'include', 'libs')):
            super(EB_OpenSSL_wrapper, self).extract_step()

    def install_step(self):
        """Symlink target OpenSSL installation"""
        if all(self.system_ssl[key] for key in ('bin', 'engines', 'include', 'libs')):
            # note: symlink to individual files, not directories,
            # since directory symlinks get resolved easily...

            # link OpenSSL libraries in system
            lib64_dir = os.path.join(self.installdir, 'lib64')
            lib64_engines_dir = os.path.join(lib64_dir, os.path.basename(self.system_ssl['engines']))
            mkdir(lib64_engines_dir, parents=True)

            # link existing known libraries
            for libso in self.system_ssl['libs']:
                symlink(libso, os.path.join(lib64_dir, os.path.basename(libso)))

            # link engines library files
            engine_lib_pattern = [os.path.join(self.system_ssl['engines'], '*')]
            for engine_lib in expand_glob_paths(engine_lib_pattern):
                symlink(engine_lib, os.path.join(lib64_engines_dir, os.path.basename(engine_lib)))

            # relative symlink for unversioned libraries
            cwd = change_dir(lib64_dir)
            for libso in self.system_ssl['libs']:
                libso = os.path.basename(libso)
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

            # install pkg-config files
            self.install_pc_files()

        elif self.cfg.get('wrap_system_openssl'):
            # install OpenSSL component due to lack of OpenSSL in host system
            print_warning("Not all OpenSSL components found in host system, falling back to OpenSSL in EasyBuild!")
            super(EB_OpenSSL_wrapper, self).install_step()
        else:
            # install OpenSSL component by user request
            warn_msg = "Installing OpenSSL from source in EasyBuild by user request ('wrap_system_openssl=%s')"
            print_warning(warn_msg, self.cfg.get('wrap_system_openssl'))
            super(EB_OpenSSL_wrapper, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for OpenSSL wrapper."""
        shlib_ext = get_shared_lib_ext()

        ssl_libs = ['%s.%s' % (solib.split('.')[0], shlib_ext) for solib in self.generation_targets['libs']]
        ssl_libs.extend(self.generation_targets['libs'])

        ssl_files = [os.path.join('bin', self.generation_targets['bin'])]
        ssl_files.extend(os.path.join('lib', libso) for libso in ssl_libs)

        ssl_dirs = [
            os.path.join('include', self.name.lower()),
            os.path.join('lib', self.generation_targets["engines"]),
            os.path.join('lib', 'pkgconfig'),
        ]

        custom_paths = {
            'files': ssl_files,
            'dirs': ssl_dirs,
        }

        # use proxy to connect if https_proxy environment variable is defined
        proxy_arg = ''
        if os.environ.get('https_proxy'):
            # only use host & port from https_proxy env var, that is, strip
            # any protocol prefix and trailing slashes
            proxy_parsed = urlparse(os.environ.get('https_proxy'))
            if proxy_parsed.netloc:
                proxy_arg = ' -proxy %s' % proxy_parsed.netloc

        custom_commands = [
            # make sure that version mentioned in output of 'openssl version' matches version we are using
            '[[ "$(openssl version)" =~ ^OpenSSL.%s ]]' % self.generation,
            ("echo | openssl s_client%s -connect github.com:443 -verify 9 "
             "| grep 'Verify return code: 0 (ok)'" % proxy_arg),
        ]

        super(Bundle, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def get_openssl_bin_version(self, bin_name):
        """Check OpenSSL executable version"""
        bin_path = which(bin_name)
        if not bin_path:
            self.log.debug("OpenSSL executable '%s' not found", bin_name)
            return None, None

        cmd = "%s version" % bin_path
        out, _ = run_cmd(cmd, simple=False, log_ok=False, trace=False)

        try:
            bin_version = out.split(' ')[1]
        except (AttributeError, IndexError):
            raise EasyBuildError("Failed to check version of OpenSSL executable: %s", bin_path)
        else:
            self.log.debug("Version of OpenSSL executable '%s': %s", bin_path, bin_version)

        return bin_path, bin_version

    def install_pc_files(self):
        """Install pkg-config files for the wrapper"""

        PC_TEMPLATE = """prefix=%(root)s
exec_prefix=${prefix}
libdir=${exec_prefix}/lib64
includedir=${prefix}/include
%(enginesdir)s

Name: %(name)s
Description: %(description)s
Version: %(version)s
%(requires)s
%(libs)s
%(cflags)s
"""
        openssl_components = {
            'libcrypto': {
                'name': 'OpenSSL-libcrypto',
                'description': 'OpenSSL cryptography library',
                'enginesdir': self.generation_targets["engines"],
            },
            'libssl': {
                'name': 'OpenSSL-libssl',
                'description': 'Secure Sockets Layer and cryptography libraries',
                'enginesdir': None,
            },
            'openssl': {
                'name': 'OpenSSL',
                'description': 'Secure Sockets Layer and cryptography libraries and tools',
                'enginesdir': None,
            },
        }

        pc_install_dir = os.path.join(self.installdir, 'lib64', 'pkgconfig')
        mkdir(pc_install_dir)

        for pc_comp in openssl_components:
            pc_file = openssl_components[pc_comp]

            pc_file['root'] = self.installdir
            pc_file['version'] = self.system_ssl['version']

            # component name in system pkg-config
            pc_name = pc_comp
            if self.generation == '1.1':
                # check suffixed names with v1.1
                pc_name_suffix = pc_name + '11'
                pc_exists_cmd = "pkg-config --exists %s" % pc_name_suffix
                if run_cmd(pc_exists_cmd, simple=True, log_ok=False, log_all=False, trace=False):
                    self.log.info("%s exists", pc_name_suffix)
                    pc_name = pc_name_suffix

            # get requires from pkg-config
            pc_file['requires'] = []
            for require_type in ['Requires', 'Requires.private']:
                require_print = require_type.lower().replace('.', '-')
                pc_print_cmd = "pkg-config --print-%s %s" % (require_print, pc_name)
                out, _ = run_cmd(pc_print_cmd, simple=False, log_ok=False, trace=False)
                self.log.info("Output of '%s': %s", pc_print_cmd, out)

                if out:
                    requires = out
                    # use unsuffixed names for components provided by this wrapper
                    for wrap_comp in openssl_components:
                        requires = re.sub(r'^%s[0-9]+$' % wrap_comp, wrap_comp, requires, flags=re.M)
                    # format requires
                    requires = requires.rstrip().splitlines()
                    pc_file['requires'].append("%s: %s" % (require_type, ' '.join(requires)))

            pc_file['requires'] = '\n'.join(pc_file['requires'])

            if pc_comp.startswith('lib'):
                # add libs and cflags for library components
                c_lib_name = pc_comp[3:]
                pc_file['libs'] = "Libs: -L${libdir} -l%s" % c_lib_name
                pc_file['cflags'] = "Cflags: -I${includedir}"
                # infer private libs through pkg-config
                pc_libs_cmd = "pkg-config --libs %s" % pc_name
                out, _ = run_cmd(pc_libs_cmd, simple=False, log_ok=False, trace=False)
                self.log.info("Output of '%s': %s", pc_libs_cmd, out)
                linker_libs = out

                pc_libs_static_cmd = "pkg-config --libs --static %s" % pc_name
                out, _ = run_cmd(pc_libs_static_cmd, simple=False, log_ok=False, trace=False)
                self.log.info("Output of '%s': %s", pc_libs_static_cmd, out)

                libs_priv = "%s " % out.rstrip()
                for flag in linker_libs.rstrip().split(' '):
                    libs_priv = libs_priv.replace("%s " % flag, '')
                pc_file['libs'] += "\nLibs.private: %s" % libs_priv
            else:
                pc_file['libs'], pc_file['cflags'] = '', ''

            # format enginesdir
            if pc_file['enginesdir']:
                pc_file['enginesdir'] = 'enginesdir=${libdir}/%s' % pc_file['enginesdir']
            else:
                pc_file['enginesdir'] = ''

            pc_path = os.path.join(pc_install_dir, '%s.pc' % pc_comp)
            write_file(pc_path, PC_TEMPLATE % pc_file)
