##
# Copyright 2012-2022 Ghent University
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
EasyBuild support for CUDA compat libraries, implemented as an easyblock

Ref: https://docs.nvidia.com/deploy/cuda-compatibility/index.html#manually-installing-from-runfile

@author: Alexander Grund (TU Dresden)
"""

import os
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_file, find_glob_pattern, mkdir, symlink
from easybuild.tools.run import run_cmd


class EB_CUDAcompat(Binary):
    """
    Support for installing CUDA compat libraries.
    """

    @staticmethod
    def extra_options():
        """Add variable for driver version"""
        extra_vars = Binary.extra_options()
        extra_vars.update({
            'nv_version': [None, "Version of the driver package", MANDATORY],
        })
        # We don't need the extract and install step from the Binary EasyBlock
        del extra_vars['extract_sources']
        del extra_vars['install_cmd']
        # And also no need to modify the PATH
        del extra_vars['prepend_to_path']
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables for Clang."""
        super(EB_CUDAcompat, self).__init__(*args, **kwargs)

    def extract_step(self):
        """Extract the files without running the installer."""
        execpath = self.src[0]['path']
        tmpdir = os.path.join(self.builddir, 'tmp')
        targetdir = os.path.join(self.builddir, 'extracted')
        run_cmd("/bin/sh " + execpath + " --extract-only --tmpdir='%s' --target '%s'" % (tmpdir, targetdir))
        self.src[0]['finalpath'] = targetdir

    def install_step(self):
        """Install CUDA compat libraries by copying library files and creating the symlinks."""
        libdir = os.path.join(self.installdir, 'lib')
        mkdir(libdir)

        # From https://docs.nvidia.com/deploy/cuda-compatibility/index.html#installing-from-network-repo:
        # The cuda-compat package consists of the following files:
        #   - libcuda.so.* - the CUDA Driver
        #   - libnvidia-nvvm.so.* - JIT LTO ( CUDA 11.5 and later only)
        #   - libnvidia-ptxjitcompiler.so.* - the JIT (just-in-time) compiler for PTX files

        library_globs = [
            'libcuda.so.*',
            'libnvidia-ptxjitcompiler.so.*',
        ]
        if LooseVersion(self.version) >= '11.5':
            library_globs.append('libnvidia-nvvm.so.*')

        startdir = self.cfg['start_dir']
        nv_version = self.cfg['nv_version']
        for library_glob in library_globs:
            library_path = find_glob_pattern(os.path.join(startdir, library_glob))
            library = os.path.basename(library_path)
            # Sanity check the version
            if library_glob == 'libcuda.so.*':
                library_version = library.split('.', 2)[2]
                if library_version != nv_version:
                    raise EasyBuildError('Expected driver version %s (from nv_version) but found %s '
                                         '(determined from file %s)', nv_version, library_version, library_path)

            copy_file(library_path, os.path.join(libdir, library))
            if library.endswith('.' + nv_version):
                # E.g. libcuda.so.510.73.08 -> libcuda.so.1
                versioned_symlink = library[:-len(nv_version)] + '1'
            else:
                # E.g. libnvidia-nvvm.so.4.0.0 -> libnvidia-nvvm.so.4
                versioned_symlink = library.rsplit('.', 2)[0]
            symlink(library, os.path.join(libdir, versioned_symlink), use_abspath_source=False)
            # E.g. libcuda.so.1 -> libcuda.so
            unversioned_symlink = versioned_symlink.rsplit('.', 1)[0]
            symlink(versioned_symlink, os.path.join(libdir, unversioned_symlink), use_abspath_source=False)

    def make_module_extra(self):
        """Skip the changes from the Binary EasyBlock."""

        return super(Binary, self).make_module_extra()

    def sanity_check_step(self):
        """Check for core files (unversioned libs, symlinks)"""
        libraries = [
            'libcuda.so',
            'libnvidia-ptxjitcompiler.so',
        ]
        if LooseVersion(self.version) >= '11.5':
            libraries.append('libnvidia-nvvm.so')
        custom_paths = {
            'files': [os.path.join(self.installdir, 'lib', x) for x in libraries],
            'dirs': ['lib', 'lib64'],
        }
        super(EB_CUDAcompat, self).sanity_check_step(custom_paths=custom_paths)
