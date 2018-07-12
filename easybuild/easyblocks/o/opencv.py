##
# Copyright 2018-2018 Ghent University
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
EasyBuild support for building and installing OpenCV, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import glob
import os

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import compute_checksum, copy
from easybuild.tools.modules import get_software_libdir, get_software_root
from easybuild.tools.systemtools import get_cpu_features, get_shared_lib_ext
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC


class EB_OpenCV(CMakeMake):
    """Support for building/installing OpenCV."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters specific to OpenCV."""
        extra_vars = {
            'cpu_dispatch': ['NONE', "Value to pass to -DCPU_DISPATCH configuration option", CUSTOM],
        }
        return CMakeMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for OpenCV."""
        super(EB_OpenCV, self).__init__(*args, **kwargs)

        # can't be set before prepare_step is run
        self.pylibdir = None

        self.cfg['separate_build_dir'] = True

    def prepare_step(self, *args, **kwargs):
        """Prepare environment for installing OpenCV."""
        super(EB_OpenCV, self).prepare_step(*args, **kwargs)

        self.pylibdir = det_pylibdir()

        ippicv_tgz = glob.glob(os.path.join(self.builddir, 'ippicv*.tgz'))
        if ippicv_tgz:
            if len(ippicv_tgz) == 1:
                # copy ippicv tarball in the right place
                # expected location is 3rdparty/ippicv/downloads/linux-<md5sum>/
                ippicv_tgz = ippicv_tgz[0]
                ippicv_tgz_md5 = compute_checksum(ippicv_tgz, checksum_type='md5')
                target_subdir = os.path.join('3rdparty', 'ippicv', 'downloads', 'linux-%s' % ippicv_tgz_md5)
                copy([ippicv_tgz], os.path.join(self.cfg['start_dir'], target_subdir))

                self.cfg.update('configopts', '-DWITH_IPP=ON')

            else:
                raise EasyBuildError("Found multiple ippicv*.tgz source tarballs in %s: %s", self.builddir, ippicv_tgz)

    def configure_step(self):
        """Custom configuration procedure for OpenCV."""

        if 'CMAKE_BUILD_TYPE' not in self.cfg['configopts']:
            self.cfg.update('configopts', '-DCMAKE_BUILD_TYPE=Release')

        # enable Python support if unspecified and Python is a dependency
        if 'BUILD_PYTHON_SUPPORT' not in self.cfg['configopts']:
            if get_software_root('Python'):
                self.cfg.update('configopts', "-DBUILD_PYTHON_SUPPORT=ON -DBUILD_NEW_PYTHON_SUPPORT=ON")
                py_pkgs_path = os.path.join(self.installdir, self.pylibdir)
                self.cfg.update('configopts', '-DPYTHON_PACKAGES_PATH=%s' % py_pkgs_path)
            else:
                self.cfg.update('configopts', "-DBUILD_PYTHON_SUPPORT=OFF -DBUILD_NEW_PYTHON_SUPPORT=OFF")

        # enable CUDA support if CUDA is a dependency
        if 'WITH_CUDA' not in self.cfg['configopts']:
            if get_software_root('CUDA'):
                self.cfg.update('configopts', '-DWITH_CUDA=ON')
            else:
                self.cfg.update('configopts', '-DWITH_CUDA=OFF')

        # configure for dependency libraries
        for dep in ['JasPer', 'libjpeg-turbo', 'libpng', 'LibTIFF', 'zlib']:
            if dep in ['libpng', 'LibTIFF']:
                # strip off 'lib'
                opt_name = dep[3:].upper()
            elif dep == 'libjpeg-turbo':
                opt_name = 'JPEG'
            else:
                opt_name = dep.upper()

            shlib_ext = get_shared_lib_ext()
            if dep == 'zlib':
                lib_file = 'libz.%s' % shlib_ext
            else:
                lib_file = 'lib%s.%s' % (opt_name.lower(), shlib_ext)

            dep_root = get_software_root(dep)
            if dep_root:
                self.cfg.update('configopts', '-D%s_INCLUDE_DIR=%s' % (opt_name, os.path.join(dep_root, 'include')))
                libdir = get_software_libdir(dep, only_one=True)
                self.cfg.update('configopts', '-D%s_LIBRARY=%s' % (opt_name, os.path.join(dep_root, libdir, lib_file)))

        # configure optimisation for CPU architecture
        # see https://github.com/opencv/opencv/wiki/CPU-optimizations-build-options
        if self.toolchain.options.get('optarch') and 'CPU_BASELINE' not in self.cfg['configopts']:
            optarch = build_option('optarch')
            if optarch is None:
                # optimize for host arch (let OpenCV detect it)
                self.cfg.update('configopts', '-DCPU_BASELINE=DETECT')
            elif optarch == OPTARCH_GENERIC:
                # optimize for generic x86 architecture (lowest supported by OpenCV is SSE3)
                self.cfg.update('configopts', '-DCPU_BASELINE=SSE3')
            else:
                raise EasyBuildError("Don't know how to configure OpenCV in accordance with --optarch='%s'", optarch)

        if self.cfg['cpu_dispatch']:
            # using 'NONE' as value is equivalent with disabling the build of fat binaries (which is done by default)
            self.cfg.update('configopts', '-DCPU_DISPATCH=%s' % self.cfg['cpu_dispatch'])

        # make sure that host CPU supports FP16 (unless -DCPU_BASELINE_DISABLE is already specified)
        # Intel Sandy Bridge does not support FP16!
        if 'CPU_BASELINE_DISABLE' not in self.cfg['configopts']:
            avail_cpu_features = get_cpu_features()
            if 'f16c' not in avail_cpu_features:
                self.cfg.update('configopts', '-DCPU_BASELINE_DISABLE=FP16')

        super(EB_OpenCV, self).configure_step()

    def install_step(self):
        """
        Custom installation procedure for OpenCV: also copy IPP library into lib subdirectory of installation directory.
        """
        super(EB_OpenCV, self).install_step()

        if 'WITH_IPP=ON' in self.cfg['configopts']:
            ipp_libs = glob.glob(os.path.join('3rdparty', 'ippicv', 'ippicv_lnx', 'lib', 'intel64', 'libippicv.*'))
            copy(ipp_libs, os.path.join(self.installdir, 'lib'))

    def sanity_check_step(self):
        """Custom sanity check for OpenCV."""
        opencv_bins = ['annotation', 'createsamples', 'traincascade', 'interactive-calibration', 'version',
                       'visualisation']
        libfile = 'libopencv_core.%s' % get_shared_lib_ext()
        custom_paths = {
            'files': [os.path.join('bin', 'opencv_%s' % x) for x in opencv_bins] + [os.path.join('lib64', libfile)],
            'dirs': ['include', self.pylibdir],
        }
        if 'WITH_IPP=ON' in self.cfg['configopts']:
            custom_paths['files'].append(os.path.join('lib', 'libippicv.a'))

        custom_commands = []
        if get_software_root('Python'):
            custom_commands.append("python -c 'import cv2'")

        super(EB_OpenCV, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom extra module file entries for OpenCV."""
        txt = super(EB_OpenCV, self).make_module_extra()

        txt += self.module_generator.prepend_paths('CLASSPATH', os.path.join('share', 'OpenCV', 'java'))
        txt += self.module_generator.prepend_paths('PYTHONPATH', self.pylibdir)

        return txt
