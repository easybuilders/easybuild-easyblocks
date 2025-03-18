##
# Copyright 2021-2025 Ghent University
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
Support for building and installing AOMP - AMD OpenMP compiler, implemented as
an EasyBlock

@author: Jorgen Nordmoen (University Center for Information Technology - UiO)
"""
import os

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import move_file, remove_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import AARCH64, POWER, X86_64
from easybuild.tools.systemtools import get_cpu_architecture, get_shared_lib_ext

AOMP_ALL_COMPONENTS = ['roct', 'rocr', 'project', 'libdevice', 'openmp',
                       'extras', 'pgmath', 'flang', 'flang_runtime', 'comgr',
                       'rocminfo', 'vdi', 'hipvdi', 'ocl', 'rocdbgapi',
                       'rocgdb', 'roctracer', 'rocprofiler']
AOMP_DEFAULT_COMPONENTS = ['roct', 'rocr', 'project', 'libdevice', 'openmp',
                           'extras', 'pgmath', 'flang', 'flang_runtime',
                           'comgr', 'rocminfo']
AOMP_X86_COMPONENTS = ['vdi', 'hipvdi', 'ocl']
AOMP_DBG_COMPONENTS = ['rocdbgapi', 'rocgdb']
AOMP_PROF_COMPONENTS = ['roctracer', 'rocprofiler']


class EB_AOMP(Binary):
    """Support for installing AOMP"""

    @staticmethod
    def extra_options():
        extra_vars = Binary.extra_options()
        extra_vars.update({
            'components': [None, "AOMP components to build. Possible components: " +
                           ', '.join(AOMP_ALL_COMPONENTS), CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables for Clang."""
        super(EB_AOMP, self).__init__(*args, **kwargs)
        self.cfg['extract_sources'] = True
        self.cfg['dontcreateinstalldir'] = True
        # Bypass the .mod file check for GCCcore installs
        self.cfg['skip_mod_files_sanity_check'] = True

    def configure_step(self):
        """Configure AOMP build and let 'Binary' install"""
        # Setup install command
        self.cfg['install_cmd'] = './aomp/bin/build_aomp.sh'
        # Setup 'preinstallopts'
        version_major = self.version.split('.')[0]
        install_options = [
            'AOMP={!s}'.format(self.installdir),
            'AOMP_REPOS="{!s}/aomp{!s}"'.format(self.builddir, version_major),
            'AOMP_CMAKE={!s}/bin/cmake'.format(get_software_root('CMake')),
            'AOMP_CHECK_GIT_BRANCH=0',
            'AOMP_APPLY_ROCM_PATCHES=0',
            'AOMP_STANDALONE_BUILD=1',
        ]
        install_options.append(f'NUM_THREADS={self.cfg.parallel}')
        # Check if CUDA is loaded and alternatively build CUDA backend
        if get_software_root('CUDA') or get_software_root('CUDAcore'):
            cuda_root = get_software_root('CUDA') or get_software_root('CUDAcore')
            install_options.append('AOMP_BUILD_CUDA=1')
            install_options.append('CUDA="{!s}"'.format(cuda_root))
            # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
            # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
            # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
            ec_cuda_cc = self.cfg['cuda_compute_capabilities']
            cfg_cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cfg_cuda_cc or ec_cuda_cc or []
            if cfg_cuda_cc and ec_cuda_cc:
                warning_msg = "cuda_compute_capabilities specified in easyconfig (%s) are overruled by " % ec_cuda_cc
                warning_msg += "--cuda-compute-capabilities configuration option (%s)" % cfg_cuda_cc
                print_warning(warning_msg)
            if not cuda_cc:
                raise EasyBuildError("CUDA module was loaded, "
                                     "indicating a build with CUDA, "
                                     "but no CUDA compute capability "
                                     "was specified!")
            # Convert '7.0' to '70' format
            cuda_cc = [cc.replace('.', '') for cc in cuda_cc]
            cuda_str = ",".join(cuda_cc)
            install_options.append('NVPTXGPUS="{!s}"'.format(cuda_str))
        else:
            # Explicitly disable CUDA
            install_options.append('AOMP_BUILD_CUDA=0')
        # Combine install instructions above into 'preinstallopts'
        self.cfg['preinstallopts'] = ' '.join(install_options)
        # Setup components for install
        components = self.cfg.get('components', None)
        # If no components were defined we use the default
        if not components:
            components = AOMP_DEFAULT_COMPONENTS
            # NOTE: The following has not been tested properly and is therefore
            # removed
            #
            # Add X86 components if correct architecture
            # if get_cpu_architecture() == X86_64:
            #     components.extend(AOMP_X86_COMPONENTS)
        # Only build selected components
        self.cfg['installopts'] = 'select ' + ' '.join(components)

    def post_processing_step(self):
        super(EB_AOMP, self).post_processing_step()
        # The install script will create a symbolic link as the install
        # directory, this creates problems for EB as it won't remove the
        # symlink. To remedy this we remove the link here and rename the actual
        # install directory created by the AOMP install script
        if os.path.islink(self.installdir):
            remove_file(self.installdir)
        else:
            err_str = "Expected '{!s}' to be a symbolic link" \
                      " that needed to be removed, but it wasn't!"
            raise EasyBuildError(err_str.format(self.installdir))
        # Move the actual directory containing the install
        install_name = '{!s}_{!s}'.format(os.path.basename(self.installdir),
                                          self.version)
        actual_install = os.path.join(os.path.dirname(self.installdir),
                                      install_name)
        if os.path.exists(actual_install) and os.path.isdir(actual_install):
            move_file(actual_install, self.installdir)
        else:
            err_str = "Tried to move '{!s}' to '{!s}', " \
                      " but it either doesn't exist" \
                      " or isn't a directory!"
            raise EasyBuildError(err_str.format(actual_install,
                                                self.installdir))

    def sanity_check_step(self):
        """Custom sanity check for AOMP"""
        shlib_ext = get_shared_lib_ext()
        arch = get_cpu_architecture()
        # Check architecture explicitly since Clang uses potentially
        # different names
        arch_map = {
            X86_64: 'x86_64',
            POWER: 'ppc64',
            AARCH64: 'aarch64',
        }

        if arch in arch_map:
            arch = arch_map[arch]
        else:
            print_warning("Unknown CPU architecture (%s) for OpenMP offloading!" % arch)
        custom_paths = {
            'files': [
                "amdgcn/bitcode/hip.bc", "amdgcn/bitcode/opencl.bc", "bin/aompcc",
                "bin/aompversion", "bin/clang", "bin/flang", "bin/ld.lld", "bin/llvm-config",
                "bin/mygpu", "bin/opt", "bin/rocminfo", "include/amd_comgr.h",
                "include/hsa/amd_hsa_common.h", "include/hsa/hsa.h", "include/omp.h",
                "include/omp_lib.h", "lib/libclang.%s" % shlib_ext, "lib/libflang.%s" % shlib_ext,
                "lib/libomp.%s" % shlib_ext, "lib/libomptarget.rtl.amdgpu.%s" % shlib_ext,
                "lib/libomptarget.rtl.%s.%s" % (arch, shlib_ext), "lib/libomptarget.%s" % shlib_ext,
            ],
            'dirs': ["amdgcn", "include/clang", "include/hsa", "include/llvm"],
        }
        # If we are building with CUDA support we need to check if it was built properly
        if get_software_root('CUDA') or get_software_root('CUDAcore'):
            custom_paths['files'].append("lib/libomptarget.rtl.cuda.%s" % shlib_ext)
        custom_commands = [
            'aompcc --help', 'clang --help', 'clang++ --help', 'flang --help',
            'llvm-config --cxxflags',
        ]
        super(EB_AOMP, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
