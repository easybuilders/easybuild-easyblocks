##
# Copyright 2020-2025 Alexander Grund
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
@author: Alexander Grund (TU Dresden)
"""
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.modules import get_software_root, get_software_libdir
import easybuild.tools.environment as env
from easybuild.tools.filetools import symlink


class EB_CMake(ConfigureMake):
    """
    EasyBlock to install CMake
    """

    @staticmethod
    def extra_options():
        extra_vars = ConfigureMake.extra_options()
        extra_vars.update({
            'use_openssl': [True, "Use openSSL (if building CURL in CMake)", CUSTOM],
        })
        return extra_vars

    def patch_step(self):
        """
        Apply patch files, and do runtime patching (if needed).

        Tweak UnixPaths.cmake if EasyBuild is configured with --sysroot.
        """
        super(EB_CMake, self).patch_step()

        sysroot = build_option('sysroot')
        if sysroot:
            # prepend custom sysroot to all hardcoded paths like /lib and /usr
            # see also patch applied by Gentoo:
            # https://gitweb.gentoo.org/repo/gentoo.git/tree/dev-util/cmake/files/cmake-3.14.0_rc3-prefix-dirs.patch
            srcdir = os.path.join(self.builddir, 'cmake-%s' % self.version)
            unixpaths_cmake = os.path.join(srcdir, 'Modules', 'Platform', 'UnixPaths.cmake')
            self.log.info("Patching %s to take into account --sysroot=%s", unixpaths_cmake, sysroot)

            sysroot_lib_dirs = [os.path.join(sysroot, x) for x in ['/usr/lib64', '/usr/lib', '/lib64', '/lib']]
            if os.path.exists(unixpaths_cmake):
                regex_subs = [
                    # add <sysroot>/usr/lib* and <sysroot>/lib* paths to CMAKE_SYSTEM_LIBRARY_PATH
                    (r'(APPEND CMAKE_SYSTEM_LIBRARY_PATH)', r'\1 %s' % ' '.join(sysroot_lib_dirs)),
                    # replace all hardcoded paths like /usr with <sysroot>/usr
                    (r' /([a-z])', r' %s/\1' % sysroot),
                    # also replace hardcoded '/' (root path)
                    (r' / ', r' %s ' % sysroot),
                    # also replace just '/' appearing at the end of a line
                    (r' /$', r' %s' % sysroot),
                ]
                apply_regex_substitutions(unixpaths_cmake, regex_subs)
            else:
                raise EasyBuildError("File to patch %s not found", unixpaths_cmake)

    def configure_step(self):
        """
        Run qmake on the GUI, if necessary
        """
        configopts = self.cfg['configopts']
        configopts = configopts.split('-- ' if configopts.startswith('-- ') else ' -- ', 1)
        configure_opts = configopts[0]
        cmake_opts = configopts[1] if len(configopts) == 2 else ''

        add_configure_opts = {'parallel': '%(parallel)s'}
        if build_option('debug'):
            add_configure_opts['verbose'] = None

        add_cmake_opts = {}
        if self.cfg['use_openssl']:
            add_cmake_opts['CMAKE_USE_OPENSSL'] = 'ON'

        cmake_prefix_path = os.environ.get('CMAKE_PREFIX_PATH', '').split(':')
        cmake_library_path = os.environ.get('CMAKE_LIBRARY_PATH', '').split(':')
        cmake_include_path = []

        available_system_options = ['BZIP2', 'CURL', 'EXPAT', 'LIBARCHIVE', 'ZLIB']
        for dep in self.cfg.dependencies():
            dep_name = dep['name']
            dep_root = get_software_root(dep_name)
            if not dep_root:
                self.log.debug('Skipping dependency %s as it was not found', dep_name)
                continue
            # Allow CMake to find this dependency
            if dep_root in cmake_prefix_path:
                self.log.debug('Not adding dependency %s to CMAKE_PREFIX_PATH as it is already contained', dep_name)
            else:
                cmake_prefix_path.append(dep_root)
            dep_lib_dir = get_software_libdir(dep_name, only_one=False)
            for lib_dir in dep_lib_dir or []:
                # /lib is automatically searched, so skip that
                if os.path.basename(lib_dir) != 'lib' and lib_dir not in cmake_library_path:
                    cmake_library_path.append(lib_dir)
            dep_name_upper = dep_name.upper()
            # Do not add this option if --system-<lib> or --no-system-<lib> is passed to configure
            if dep_name_upper in available_system_options and '-system-' + dep_name.lower() not in configure_opts:
                add_cmake_opts['CMAKE_USE_SYSTEM_' + dep_name_upper] = 'ON'

        cmake_path_env_vars = {
            'CMAKE_PREFIX_PATH': cmake_prefix_path,
            'CMAKE_LIBRARY_PATH': cmake_library_path,
            'CMAKE_INCLUDE_PATH': cmake_include_path,
        }
        for var, values in cmake_path_env_vars.items():
            value = ':'.join(values)
            if os.environ.get(var, '') != value:
                env.setvar(var, value)

        for var, value in add_configure_opts.items():
            if '--' + var not in cmake_opts:
                configure_opts += ' --' + var if value is None else ' --%s=%s' % (var, value)

        for var, value in add_cmake_opts.items():
            if '-D%s=' % var not in cmake_opts:
                cmake_opts += ' -D%s=%s' % (var, value)

        self.cfg['configopts'] = configure_opts + ' -- ' + cmake_opts

        super(EB_CMake, self).configure_step()

    def install_step(self):
        """Create symlinks for CMake binaries"""
        super(EB_CMake, self).install_step()
        # Some applications assume the existance of e.g. cmake3 to distinguish it from cmake, which can be 2 or 3
        maj_ver = self.version.split('.')[0]
        bin_path = os.path.join(self.installdir, 'bin')
        for binary in ('ccmake', 'cmake', 'cpack', 'ctest'):
            symlink_name = binary + maj_ver
            symlink(binary, os.path.join(bin_path, symlink_name), use_abspath_source=False)

    def sanity_check_step(self):
        """
        Custom sanity check for CMake.
        """
        paths = {
            'files': [os.path.join('bin', x) for x in ('ccmake', 'cmake', 'cpack', 'ctest')],
            'dirs': [],
        }
        commands = ['cmake --help', 'ccmake --help']

        super(EB_CMake, self).sanity_check_step(custom_paths=paths, custom_commands=commands)
