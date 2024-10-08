##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for installing the Intel Threading Building Blocks (TBB) library, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Lumir Jasiok (IT4Innovations)
@author: Simon Branford (University of Birmingham)
"""

import glob
import os
import shutil
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.easyblocks.generic.intelbase import INSTALL_MODE_NAME_2015, INSTALL_MODE_2015
from easybuild.easyblocks.generic.intelbase import IntelBase, ACTIVATION_NAME_2012, LICENSE_FILE_NAME_2012
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import find_glob_pattern, move_file, symlink
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_version
from easybuild.tools.systemtools import POWER, get_cpu_architecture, get_gcc_version, get_platform_name
from easybuild.tools.run import run_cmd


def get_tbb_gccprefix(libpath):
    """
    Find the correct gcc version for the lib dir of TBB
    """
    # using get_software_version('GCC') won't work if the system toolchain is used
    gccversion = get_software_version('GCCcore') or get_software_version('GCC')
    # manual approach to at least have the system version of gcc
    if not gccversion:
        gccversion = get_gcc_version()

    # TBB directory structure
    # https://www.threadingbuildingblocks.org/docs/help/tbb_userguide/Linux_OS.html
    tbb_gccprefix = 'gcc4.4'  # gcc version 4.4 or higher that may or may not support exception_ptr
    if gccversion:
        gccversion = LooseVersion(gccversion)
        if gccversion >= LooseVersion("4.1") and gccversion < LooseVersion("4.4"):
            tbb_gccprefix = 'gcc4.1'  # gcc version number between 4.1 and 4.4 that do not support exception_ptr
        elif os.path.isdir(os.path.join(libpath, 'gcc4.8')) and gccversion >= LooseVersion("4.8"):
            tbb_gccprefix = 'gcc4.8'

    return tbb_gccprefix


class EB_tbb(IntelBase, ConfigureMake):
    """EasyBlock for tbb, threading building blocks"""

    @staticmethod
    def extra_options():
        extra_vars = IntelBase.extra_options()
        extra_vars.update(ConfigureMake.extra_options())
        extra_vars.update({
            'with_python': [False, "Should the TBB4Python bindings be built as well?", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for tbb"""
        super(EB_tbb, self).__init__(*args, **kwargs)

        platform_name = get_platform_name()
        myarch = get_cpu_architecture()
        if platform_name.startswith('x86_64'):
            self.arch = "intel64"
        elif platform_name.startswith('i386') or platform_name.startswith('i686'):
            self.arch = 'ia32'
        elif myarch == POWER:
            self.arch = 'ppc64'
        else:
            raise EasyBuildError("Failed to determine system architecture based on %s", platform_name)

        if not self.toolchain.is_system_toolchain():
            # open-source TBB version
            self.build_in_installdir = True
            self.cfg['requires_runtime_license'] = False

        if self.toolchain.is_system_toolchain():
            self.tbb_subdir = 'tbb'
        else:
            self.tbb_subdir = ''

    def extract_step(self):
        """Extract sources."""
        if not self.toolchain.is_system_toolchain():
            # strip off 'tbb-<version>' subdirectory
            self.cfg['unpack_options'] = "--strip-components=1"
        super(EB_tbb, self).extract_step()

    def configure_step(self):
        """Configure TBB build/installation."""
        if self.toolchain.is_system_toolchain():
            IntelBase.configure_step(self)
        else:
            # no custom configure step when building from source
            pass

    def build_step(self):
        """Configure TBB build/installation."""
        if self.toolchain.is_system_toolchain():
            IntelBase.build_step(self)
        else:
            # build with: make compiler={icl, icc, gcc, clang}
            self.cfg.update('buildopts', 'compiler="%s"' % os.getenv('CC'))
            ConfigureMake.build_step(self)

            if self.cfg['with_python']:
                # Uses the Makefile target `python`
                self.cfg.update('buildopts', 'python')
                ConfigureMake.build_step(self)

    def _has_cmake(self):
        """Check if CMake is included in the build deps"""
        build_deps = self.cfg.dependencies(build_only=True)
        return any(dep['name'] == 'CMake' for dep in build_deps)

    def install_step(self):
        """Custom install step, to add extra symlinks"""
        install_tbb_lib_path = os.path.join(self.installdir, 'tbb', 'lib')

        if self.toolchain.is_system_toolchain():
            silent_cfg_names_map = None
            silent_cfg_extras = None

            if LooseVersion(self.version) < LooseVersion('4.2'):
                silent_cfg_names_map = {
                    'activation_name': ACTIVATION_NAME_2012,
                    'license_file_name': LICENSE_FILE_NAME_2012,
                }

            elif LooseVersion(self.version) < LooseVersion('4.4'):
                silent_cfg_names_map = {
                    'install_mode_name': INSTALL_MODE_NAME_2015,
                    'install_mode': INSTALL_MODE_2015,
                }

            # In case of TBB 4.4.x and newer we have to specify ARCH_SELECTED in silent.cfg
            if LooseVersion(self.version) >= LooseVersion('4.4'):
                silent_cfg_extras = {
                    'ARCH_SELECTED': self.arch.upper()
                }

            IntelBase.install_step(self, silent_cfg_names_map=silent_cfg_names_map, silent_cfg_extras=silent_cfg_extras)

            # determine libdir
            libpath = os.path.join(self.installdir, 'tbb', 'libs', 'intel64')
            if LooseVersion(self.version) < LooseVersion('4.1.0'):
                libglob = os.path.join(libpath, 'cc*libc*_kernel*')
                libs = sorted(glob.glob(libglob), key=LooseVersion)
                if libs:
                    # take the last one, should be ordered by cc version
                    # we're only interested in the last bit
                    libpath = libs[-1]
                else:
                    raise EasyBuildError("No libs found using %s in %s", libglob, self.installdir)
            else:
                libpath = os.path.join(libpath, get_tbb_gccprefix(libpath))

            # applications go looking into tbb/lib so we move what's in there to tbb/libs
            shutil.move(install_tbb_lib_path, os.path.join(self.installdir, 'tbb', 'libs'))
            # And add a symlink of the library folder to tbb/lib
            symlink(libpath, install_tbb_lib_path)
        else:
            # no custom install step when building from source (building is done in install directory)
            libpath = find_glob_pattern(os.path.join(self.installdir, 'build', '*_release'))

        real_libpath = os.path.realpath(libpath)
        self.log.debug("libpath: %s, resolved: %s" % (libpath, real_libpath))
        libpath = real_libpath
        # applications usually look into /lib, so we move the folder there
        # This is also important so that /lib and /lib64 are actually on the same level
        root_lib_path = os.path.join(self.installdir, 'lib')
        move_file(libpath, root_lib_path)
        # Create a relative symlink at the original location as-if we didn't move it.
        # Note that the path must be relative from the folder where the symlink will be!
        symlink(os.path.relpath(root_lib_path, os.path.dirname(libpath)), libpath, use_abspath_source=False)

        # Install CMake config files if possible
        if self._has_cmake() and LooseVersion(self.version) >= LooseVersion('2020.0'):
            cmake_install_dir = os.path.join(root_lib_path, 'cmake', 'TBB')
            cmd = [
                'cmake',
                '-DINSTALL_DIR=' + cmake_install_dir,
                '-DSYSTEM_NAME=Linux',
                '-P tbb_config_installer.cmake',
            ]
            run_cmd(' '.join(cmd), path=os.path.join(self.builddir, 'cmake'))

    def sanity_check_step(self):
        """Custom sanity check for TBB"""
        custom_paths = {
            'files': [
                os.path.join('lib', 'libtbb.so'),
                os.path.join('lib', 'libtbbmalloc.so'),
            ],
            'dirs': [],
        }
        custom_commands = []

        if self.toolchain.is_system_toolchain():
            custom_paths['dirs'].extend(os.path.join('tbb', p) for p in
                                        ('bin', 'lib', 'libs', os.path.join('include', 'tbb')))
            custom_paths['files'].extend([
                os.path.join('tbb', 'lib', 'libtbb.so'),
                os.path.join('tbb', 'lib', 'libtbbmalloc.so'),
            ])
        else:
            custom_paths['dirs'].append(os.path.join('include', 'tbb'))

        if self._has_cmake():
            custom_paths['files'].extend([
                os.path.join('lib', 'cmake', 'TBB', 'TBBConfig.cmake'),
                os.path.join('lib', 'cmake', 'TBB', 'TBBConfigVersion.cmake'),
            ])

        if self.cfg['with_python']:
            custom_paths['dirs'].append(os.path.join(self.tbb_subdir, 'python'))
            custom_commands.extend(['python -s -c "import tbb"'])

        super(EB_tbb, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Add correct path to lib to LD_LIBRARY_PATH. and intel license file"""
        txt = super(EB_tbb, self).make_module_extra()

        if self.toolchain.is_system_toolchain():
            txt += self.module_generator.prepend_paths('CPATH', [os.path.join(self.tbb_subdir, 'include')])

        root_dir = os.path.join(self.installdir, self.tbb_subdir)
        txt += self.module_generator.set_environment('TBBROOT', root_dir)
        # TBB_ROOT used e.g. by FindTBB.cmake
        txt += self.module_generator.set_environment('TBB_ROOT', root_dir)

        if self.cfg['with_python']:
            txt += self.module_generator.prepend_paths('PYTHONPATH', [os.path.join(self.tbb_subdir, 'python')])

        return txt

    def cleanup_step(self):
        """Cleanup step"""
        if self.toolchain.is_system_toolchain():
            IntelBase.cleanup_step(self)
        else:
            ConfigureMake.cleanup_step(self)
