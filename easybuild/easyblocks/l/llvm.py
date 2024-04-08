##
# Copyright 2020-2024 Ghent University
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
EasyBuild support for building and installing LLVM, implemented as an easyblock

@author: Simon Branford (University of Birmingham)
@author: Kenneth Hoste (Ghent University)
"""
import os

from easybuild.easyblocks.clang import CLANG_TARGETS, DEFAULT_TARGETS_MAP
from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import move_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import get_cpu_architecture
from easybuild.tools import LooseVersion


class EB_LLVM(CMakeMake):
    """
    Support for building and installing LLVM
    """

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'build_targets': [None, "Build targets for LLVM (host architecture if None). Possible values: " +
                                    ', '.join(CLANG_TARGETS), CUSTOM],
            'enable_rtti': [True, "Enable RTTI", CUSTOM],
        })

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize LLVM-specific variables."""
        super(EB_LLVM, self).__init__(*args, **kwargs)

        self.build_shared = self.cfg.get('build_shared_libs', False)
        if LooseVersion(self.version) >= LooseVersion('14'):
            self.cfg['start_dir'] = '%s-%s.src' % (self.name.lower(), self.version)
            # avoid using -DBUILD_SHARED_LIBS directly, use -DLLVM_{BUILD,LINK}_LLVM_DYLIB flags instead
            if self.build_shared:
                self.cfg['build_shared_libs'] = None

    def configure_step(self):
        """
        Install extra tools in bin/; enable zlib if it is a dep; optionally enable rtti; and set the build target
        """
        if LooseVersion(self.version) >= LooseVersion('14'):
            self.cfg.update('configopts', '-DLLVM_INCLUDE_BENCHMARKS=OFF')
            if self.build_shared:
                self.cfg.update('configopts', '-DLLVM_BUILD_LLVM_DYLIB=ON -DLLVM_LINK_LLVM_DYLIB=ON')

        self.cfg.update('configopts', '-DLLVM_INSTALL_UTILS=ON')

        if get_software_root('zlib'):
            self.cfg.update('configopts', '-DLLVM_ENABLE_ZLIB=ON')

        if self.cfg["enable_rtti"]:
            self.cfg.update('configopts', '-DLLVM_ENABLE_RTTI=ON')

        build_targets = self.cfg['build_targets']
        if build_targets is None:
            arch = get_cpu_architecture()
            try:
                default_targets = DEFAULT_TARGETS_MAP[arch][:]
                self.cfg['build_targets'] = build_targets = default_targets
                self.log.debug("Using %s as default build targets for CPU architecture %s.", default_targets, arch)
            except KeyError:
                raise EasyBuildError("No default build targets defined for CPU architecture %s.", arch)

        unknown_targets = [target for target in build_targets if target not in CLANG_TARGETS]

        if unknown_targets:
            raise EasyBuildError("Some of the chosen build targets (%s) are not in %s.",
                                 ', '.join(unknown_targets), ', '.join(CLANG_TARGETS))

        self.cfg.update('configopts', '-DLLVM_TARGETS_TO_BUILD="%s"' % ';'.join(build_targets))

        if LooseVersion(self.version) >= LooseVersion('15.0'):
            # make sure that CMake modules are available in build directory,
            # by moving the extracted folder to the expected location
            cmake_modules_path = os.path.join(self.builddir, 'cmake-%s.src' % self.version)
            if os.path.exists(cmake_modules_path):
                move_file(cmake_modules_path, os.path.join(self.builddir, 'cmake'))
            else:
                raise EasyBuildError("Failed to find unpacked CMake modules directory at %s", cmake_modules_path)

        if LooseVersion(self.version) >= LooseVersion('16.0'):
            # make sure that third-party modules are available in build directory,
            # by moving the extracted folder to the expected location
            third_party_modules_path = os.path.join(self.builddir, 'third-party-%s.src' % self.version)
            if os.path.exists(third_party_modules_path):
                move_file(third_party_modules_path, os.path.join(self.builddir, 'third-party'))
            else:
                raise EasyBuildError("Failed to find unpacked 'third-party' modules directory at %s",
                                     third_party_modules_path)

        super(EB_LLVM, self).configure_step()
