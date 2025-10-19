##
# Copyright 2021-2025 Vrije Universiteit Brussel
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
EasyBuild support for installing a wrapper module file for systemd

@author: Mikael Öhman (Chalmers University of Technology)
"""
import os
import re
from urllib.parse import urlparse

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.filetools import change_dir, expand_glob_paths, mkdir, read_file, symlink, which, write_file
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import DARWIN, LINUX, get_os_type, get_shared_lib_ext, find_library_path


def get_sys_lib_dirs():
    res = run_shell_cmd('gcc -print-search-dirs', hidden=True, in_dry_run=True)
    match = re.search(r"^libraries:\s*=(.*)$", res.output, re.MULTILINE)
    if match:
        return [p for p in match.group(1).split(":") if p]
    return []


def get_sys_include_dirs():
    cmd = "LC_ALL=C gcc -E -Wp,-v -xc /dev/null"
    res = run_shell_cmd(cmd, hidden=True, in_dry_run=True)
    sys_include_dirs = []
    for match in re.finditer(r'^\s(/[^\0\n]*)+', res.output, re.MULTILINE):
        sys_include_dirs.extend(match.groups())
    return sys_include_dirs


def get_sys_pc_dirs():
    res = run_shell_cmd('pkg-config --variable pc_path pkgconf', hidden=True, in_dry_run=True)
    return res.output.strip().split(':')


class EB_systemd_wrapper(Bundle):
    """
    Find path to installation files of systemd and udev in the host system.
    """

    def __init__(self, *args, **kwargs):
        """Locate the installation files of systemd in the host system"""
        super().__init__(*args, **kwargs)

        shlib_ext = get_shared_lib_ext()
        systemd_lib_patterns = [f'libsystemd.{shlib_ext}', f'libudev.{shlib_ext}']
        systemd_include_patterns = ['systemd', 'libudev.h']
        systemd_pc_patterns = ['systemd.pc', 'udev.pc']

        self.systemd = dict()

        # Check lib paths for systemd libraries
        sys_lib_dirs = get_sys_lib_dirs()
        self.log.debug('Found the following lib directories in host system: %s', ', '.join(sys_lib_dirs))

        self.systemd['libs'] = []
        for systemd_lib_pattern in systemd_lib_patterns:
            for sys_lib_dir in sys_lib_dirs:
                file = os.path.join(sys_lib_dir, systemd_lib_pattern)
                if os.path.exists(file):
                    self.systemd['libs'].append(file)
                    break
            else:
                raise EasyBuildError('Could not find library: %s.', systemd_lib_pattern)

        # Check system include paths for systemd headers
        sys_include_dirs = get_sys_include_dirs()
        self.log.debug('Found the following include directories in host system: %s', ', '.join(sys_include_dirs))

        self.systemd['includes'] = []
        for systemd_include_pattern in systemd_include_patterns:
            for sys_include_dir in sys_include_dirs:
                file = os.path.join(sys_include_dir, systemd_include_pattern)
                if os.path.exists(file):
                    self.systemd['includes'].append(file)
                    break
            else:
                raise EasyBuildError('Could not find includes: %s.', systemd_include_pattern)

        # Check pkgconfig paths
        sys_pc_dirs = get_sys_pc_dirs()
        print(sys_pc_dirs)
        self.log.debug("Found the following pkgconfig directories in host system: %s", ', '.join(sys_pc_dirs))

        self.systemd['pcs'] = []
        for systemd_pc_pattern in systemd_pc_patterns:
            for sys_pc_dir in sys_pc_dirs:
                file = os.path.join(sys_pc_dir, systemd_pc_pattern)
                if os.path.exists(file):
                    self.systemd['pcs'].append(file)
                    break
            else:
                raise EasyBuildError('Could not find pkgconfig file: %s.', systemd_pc_pattern)

    def fetch_step(self, *args, **kwargs):
        """Nothing to fetch"""

    def extract_step(self):
        """No sources to extract"""

    def configure_step(self):
        """No configure step"""

    def build_step(self):
        """No configure step"""

    def install_step(self):
        """Symlink OS systemd installation"""
        include_dir = os.path.join(self.installdir, 'include')
        mkdir(include_dir, parents=True)
        for file in self.systemd['includes']:
            symlink(file, os.path.join(include_dir, os.path.basename(file)))

        lib_dir = os.path.join(self.installdir, 'lib')
        mkdir(lib_dir, parents=True)
        for file in self.systemd['libs']:
            symlink(file, os.path.join(lib_dir, os.path.basename(file)))

        pc_dir = os.path.join(self.installdir, 'share', 'pkgconfig')
        mkdir(pc_dir, parents=True)
        for file in self.systemd['pcs']:
            symlink(file, os.path.join(pc_dir, os.path.basename(file)))

    def sanity_check_step(self):
        """Custom sanity check for systemd wrapper."""
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [f'lib/libsystemd.{shlib_ext}', f'libudev.{shlib_ext}', 'include/udev.h',
                      'share/pkgconfig/libsystemd.pc', 'share/pkgconfig/libudev.pc'],
            'dirs': ['include/systemd'],
        }
        return super().sanity_check_step(custom_paths=custom_paths, custom_commands=[])
