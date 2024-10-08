##
# Copyright 2018-2024 Ghent University
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
@author: Simon Branford (University of Birmingham)
"""
import glob
import os
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import compute_checksum, copy
from easybuild.tools.modules import get_software_libdir, get_software_root, get_software_version
from easybuild.tools.systemtools import X86_64, get_cpu_architecture, get_cpu_features, get_shared_lib_ext
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC


class EB_OpenCV(CMakeMake):
    """Support for building/installing OpenCV."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters specific to OpenCV."""
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'cpu_dispatch': ['NONE', "Value to pass to -DCPU_DISPATCH configuration option", CUSTOM],
        })
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for OpenCV."""
        super(EB_OpenCV, self).__init__(*args, **kwargs)

        # can't be set before prepare_step is run
        self.pylibdir = None

    def prepare_step(self, *args, **kwargs):
        """Prepare environment for installing OpenCV."""
        super(EB_OpenCV, self).prepare_step(*args, **kwargs)

        self.pylibdir = det_pylibdir()

        if get_cpu_architecture() == X86_64:
            # IPP are Intel's Integrated Performance Primitives - so only make sense on X86_64
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

                    # for recent OpenCV 3.x versions (and newer), we must also specify the download location
                    # to prevent that the ippicv tarball is re-downloaded
                    if LooseVersion(self.version) >= LooseVersion('3.4.4'):
                        self.cfg.update('configopts', '-DOPENCV_DOWNLOAD_PATH=%s' % self.builddir)
                else:
                    raise EasyBuildError("Found multiple ippicv*.tgz source tarballs in %s: %s",
                                         self.builddir, ippicv_tgz)

    def configure_step(self):
        """Custom configuration procedure for OpenCV."""

        # enable Python support if unspecified and Python is a dependency
        if 'BUILD_PYTHON_SUPPORT' not in self.cfg['configopts']:
            if get_software_root('Python'):
                self.cfg.update('configopts', "-DBUILD_PYTHON_SUPPORT=ON -DBUILD_NEW_PYTHON_SUPPORT=ON")

                # recent OpenCV 3.x versions (and newer) use an alternative configure option to specify the location
                # where the OpenCV Python bindings should be installed
                py_pkgs_path = os.path.join(self.installdir, self.pylibdir)
                if LooseVersion(self.version) >= LooseVersion('3.4.4'):
                    self.cfg.update('configopts', '-DOPENCV_PYTHON_INSTALL_PATH=%s' % py_pkgs_path)
                else:
                    self.cfg.update('configopts', '-DPYTHON_PACKAGES_PATH=%s' % py_pkgs_path)
            else:
                self.cfg.update('configopts', "-DBUILD_PYTHON_SUPPORT=OFF -DBUILD_NEW_PYTHON_SUPPORT=OFF")

        # enable CUDA support if CUDA is a dependency
        if 'WITH_CUDA' not in self.cfg['configopts']:
            if get_software_root('CUDA'):
                self.cfg.update('configopts', '-DWITH_CUDA=ON')
            else:
                self.cfg.update('configopts', '-DWITH_CUDA=OFF')

        # disable bundled protobuf if it is a dependency
        if 'BUILD_PROTOBUF' not in self.cfg['configopts']:
            if get_software_root('protobuf'):
                self.cfg.update('configopts', '-DBUILD_PROTOBUF=OFF')
            else:
                self.cfg.update('configopts', '-DBUILD_PROTOBUF=ON')

        # configure for dependency libraries
        for dep in ['JasPer', 'libjpeg-turbo', 'libpng', 'LibTIFF', 'libwebp', 'OpenEXR', 'zlib']:
            if dep in ['libpng', 'LibTIFF', 'libwebp']:
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
                if dep == 'OpenEXR':
                    self.cfg.update('configopts', '-D%s_ROOT=%s' % (opt_name, dep_root))
                else:
                    inc_path = os.path.join(dep_root, 'include')
                    self.cfg.update('configopts', '-D%s_INCLUDE_DIR=%s' % (opt_name, inc_path))
                    libdir = get_software_libdir(dep, only_one=True)
                    lib_path = os.path.join(dep_root, libdir, lib_file)
                    self.cfg.update('configopts', '-D%s_LIBRARY=%s' % (opt_name, lib_path))

        # GTK+3 is used by default, use GTK+2 or none explicitely to avoid picking up a system GTK
        if get_software_root('GTK+'):
            if LooseVersion(get_software_version('GTK+')) < LooseVersion('3.0'):
                self.cfg.update('configopts', '-DWITH_GTK_2_X=ON')
        elif get_software_root('GTK3'):
            pass
        elif get_software_root('GTK2'):
            self.cfg.update('configopts', '-DWITH_GTK_2_X=ON')
        else:
            self.cfg.update('configopts', '-DWITH_GTK=OFF')

        # configure optimisation for CPU architecture
        # see https://github.com/opencv/opencv/wiki/CPU-optimizations-build-options
        if self.toolchain.options.get('optarch') and 'CPU_BASELINE' not in self.cfg['configopts']:
            optimal_arch_option = self.toolchain.COMPILER_OPTIMAL_ARCHITECTURE_OPTION.get(
                (self.toolchain.arch, self.toolchain.cpu_family), '')
            optarch = build_option('optarch')
            optarch_detect = False
            if not optarch:
                optarch_detect = True
            elif isinstance(optarch, str):
                optarch_detect = optimal_arch_option in optarch
            elif isinstance(optarch, dict):
                optarch_gcc = optarch.get('GCC')
                optarch_intel = optarch.get('Intel')
                gcc_detect = get_software_root('GCC') and (not optarch_gcc or optimal_arch_option in optarch_gcc)
                intel_root = get_software_root('iccifort') or get_software_root('intel-compilers')
                intel_detect = intel_root and (not optarch_intel or optimal_arch_option in optarch_intel)
                optarch_detect = gcc_detect or intel_detect

            if optarch_detect:
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
            common_dir = os.path.join('3rdparty', 'ippicv', 'ippicv_lnx')

            # for some recent OpenCV 3.x versions, libippicv.a is now in a subdirectory named 'icv'
            if LooseVersion(self.version) >= LooseVersion('3.4.4'):
                ipp_libs = glob.glob(os.path.join(common_dir, 'icv', 'lib', 'intel64', 'libippicv.*'))
            else:
                ipp_libs = glob.glob(os.path.join(common_dir, 'lib', 'intel64', 'libippicv.*'))

            copy(ipp_libs, os.path.join(self.installdir, 'lib'))

    def sanity_check_step(self):
        """Custom sanity check for OpenCV."""
        opencv_bins = ['annotation', 'interactive-calibration', 'version', 'visualisation']
        if LooseVersion(self.version) < LooseVersion('4.0'):
            opencv_bins.extend(['createsamples', 'traincascade'])

        libfile = 'libopencv_core.%s' % get_shared_lib_ext()
        custom_paths = {
            'files': [os.path.join('bin', 'opencv_%s' % x) for x in opencv_bins] + [os.path.join('lib64', libfile)],
            'dirs': ['include'],
        }
        if 'WITH_IPP=ON' in self.cfg['configopts']:
            custom_paths['files'].append(os.path.join('lib', 'libippicv.a'))

        custom_commands = []
        if get_software_root('Python'):
            custom_commands.append("python -s -c 'import cv2'")

        super(EB_OpenCV, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Custom extra module file entries for OpenCV."""
        txt = super(EB_OpenCV, self).make_module_extra()

        if LooseVersion(self.version) >= LooseVersion('4.0'):
            txt += self.module_generator.prepend_paths('CPATH', os.path.join('include', 'opencv4'))

        txt += self.module_generator.prepend_paths('CLASSPATH', os.path.join('share', 'OpenCV', 'java'))

        if os.path.exists(os.path.join(self.installdir, self.pylibdir)):
            txt += self.module_generator.prepend_paths('PYTHONPATH', self.pylibdir)

        return txt
